"""
异步任务管理器 —— 把一次 LangGraph 分析封装成可轮询的后台任务(专业看板升级)。

设计:
- 前端启动分析 -> POST /analyze 立即返回 task_id(不等分析结束,避免长 HTTP 超时)
- 后台线程跑 LangGraph,直接消费 _graph.stream() 的事件流(每个事件 = 一个节点完成),
  由本模块把事件流映射成流水线 DAG 的逐阶段状态:等待/运行中/完成/跳过/失败 + 耗时
- GET /task/status  轮询 -> 各 Agent 状态(前端据此渲染水平时间线)
- GET /task/result  获取最终报告 + 全部中间数据 + LLM token 统计

设计要点:
- 不修改 LangGraph 节点逻辑:stream 事件天然给出"哪个节点跑完了",配合固定的
  DAG 拓扑推断后继节点状态(fan-in 节点等待全部前置完成)
- 工作流一次编译进程内复用;无 checkpointer 的图可并发 invoke(线程安全)
"""
import logging
import threading
import time
import uuid
from typing import Dict, Optional

from ..agents.llm import TOKEN_STATS as LLM_STATS
from ..graph.workflow import build_workflow

logger = logging.getLogger(__name__)

# 流水线 DAG:与 graph/workflow.py 的拓扑一致,仅用于前端进度可视化
# quick 模式去掉 sentiment 依赖(risk 只等 technical)
NODE_ORDER = ["collect", "technical", "sentiment", "risk", "report"]
PREDECESSORS = {
    "collect": [],
    "technical": ["collect"],
    "sentiment": ["collect"],
    "risk": ["technical", "sentiment"],  # fan-in:两个前置都完成才开始
    "report": ["risk"],
}
NODE_LABELS = {
    "collect": "数据采集",
    "technical": "技术分析",
    "sentiment": "情感分析",
    "risk": "风险评估",
    "report": "报告生成",
}

# 工作流级一次编译,进程内复用
_GRAPH = build_workflow()


class Stage:
    """流水线中的单个 Agent 阶段"""

    __slots__ = ("name", "label", "status", "elapsed", "note")

    def __init__(self, name: str, label: str):
        self.name = name
        self.label = label
        self.status = "waiting"  # waiting / running / completed / skipped / failed
        self.elapsed: Optional[float] = None  # 秒
        self.note: str = ""  # 如 "⚠️ 使用备用数据源"

    def to_dict(self) -> dict:
        return {
            "name": self.name, "label": self.label,
            "status": self.status, "elapsed": self.elapsed, "note": self.note,
        }


class TaskRecord:
    """一次分析任务的状态容器(线程共享,用锁保护写操作)"""

    def __init__(self, task_id: str, stock_code: str, mode: str, user_id: Optional[int] = None):
        self.task_id = task_id
        self.stock_code = stock_code
        self.mode = mode          # quick / full
        self.user_id = user_id    # 触发分析的用户(为空则不落分析历史)
        self.status = "pending"   # pending / running / completed / failed
        self.error: Optional[str] = None
        self.data_source = "real"
        self.created_at = time.time()
        self.updated_at = time.time()
        self.stages: Dict[str, Stage] = {n: Stage(n, NODE_LABELS[n]) for n in NODE_ORDER}
        self.result: Optional[dict] = None
        self._token_before: dict = dict(LLM_STATS)

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id, "stock_code": self.stock_code, "mode": self.mode,
            "status": self.status, "error": self.error, "data_source": self.data_source,
            "created_at": self.created_at, "updated_at": self.updated_at,
            "stages": [self.stages[n].to_dict() for n in NODE_ORDER],
        }


class TaskManager:
    """线程安全的任务注册表:create 立即返回,后台线程执行"""

    MAX_TASKS = 200  # 简单防内存膨胀:超出后清理已完成任务

    def __init__(self):
        self._tasks: Dict[str, TaskRecord] = {}
        self._lock = threading.Lock()

    # ---------- 对外接口 ----------
    def create(self, stock_code: str, mode: str = "full", user_id: Optional[int] = None) -> TaskRecord:
        task = TaskRecord(uuid.uuid4().hex[:12], stock_code, mode, user_id=user_id)
        with self._lock:
            self._tasks[task.task_id] = task
            self._cleanup_locked()
        thread = threading.Thread(target=self._run, args=(task,), daemon=True)
        thread.start()
        return task

    def get(self, task_id: str) -> Optional[TaskRecord]:
        with self._lock:
            return self._tasks.get(task_id)

    def _cleanup_locked(self):
        """任务数超上限时,优先清掉已完成的旧任务"""
        if len(self._tasks) <= self.MAX_TASKS:
            return
        for tid, t in list(self._tasks.items()):
            if len(self._tasks) <= self.MAX_TASKS:
                break
            if t.status in ("completed", "failed"):
                self._tasks.pop(tid, None)

    # ---------- 内部:状态更新 ----------
    def _update_stage(self, task: TaskRecord, name: str, status: str,
                      elapsed: Optional[float] = None, note: Optional[str] = None):
        stage = task.stages[name]
        stage.status = status
        if elapsed is not None:
            stage.elapsed = round(elapsed, 1)
        if note:
            stage.note = note
        task.updated_at = time.time()

    def _mark_successors_running(self, task: TaskRecord, node: str, done: dict):
        """节点完成后,推进后继阶段:fan-in 前置未齐则 'waiting',齐了则 'running'"""
        for succ, deps in PREDECESSORS.items():
            if succ in done:  # 已完成的不再改动
                continue
            if task.mode == "quick" and succ == "sentiment":
                continue  # 快速模式情感阶段直接跳过(末尾统一标记 skipped)
            # 实际依赖(quick 模式下 risk 只依赖 technical)
            deps_eff = [d for d in deps if not (task.mode == "quick" and d == "sentiment")]
            if node in deps_eff:
                if all(d in done for d in deps_eff):
                    self._update_stage(task, succ, "running")
                else:
                    self._update_stage(task, succ, "waiting")

    # ---------- 内部:主执行 ----------
    def _run(self, task: TaskRecord):
        task.status = "running"
        self._update_stage(task, "collect", "running")
        try:
            state = {
                "stock_code": task.stock_code,
                "news_items": [],
                "technical": None,
                "technical_analysis": None,
                "sentiment": None,
                "sentiment_failed": False,
                "risk": None,
                "report": None,
                "data_source": "real",
                "mode": task.mode,
            }
            done: dict = {}
            prev_finish = time.perf_counter()

            for ev in _GRAPH.stream(state):
                node = next(iter(ev))
                update = ev[node]
                now = time.perf_counter()
                elapsed = now - prev_finish  # 上一个节点完成到本节点完成的窗口 ≈ 本节点活跃时间
                prev_finish = now
                done[node] = update
                self._update_stage(task, node, "completed", elapsed)
                self._mark_successors_running(task, node, done)

            # 没出事件的节点 = 被条件路由跳过(如新闻为空跳情感、quick 模式跳情感)
            for name in NODE_ORDER:
                if name not in done:
                    self._update_stage(task, name, "skipped")

            # 数据源标记(来自采集降级链)
            source = (done.get("collect") or {}).get("data_source", "real")
            task.data_source = source
            if source in ("backup", "mock"):
                self._update_stage(task, "collect", "completed",
                                   note=f"⚠️ 降级:{'备用源' if source == 'backup' else 'Mock'}")
            if (done.get("sentiment") or {}).get("sentiment_failed"):
                self._update_stage(task, "sentiment", "completed",
                                   note="⚠️ LLM 降级,返回中性")

            task.result = self._build_result(task, done)
            task.status = "completed"
            # 分析历史落库(仅登录用户;失败不影响主流程)
            try:
                from .history_service import save_analysis_history
                save_analysis_history(task.user_id, task.result)
            except Exception as e:
                logger.warning("分析历史入库异常(忽略): %s", e)
        except Exception as e:
            logger.exception("[task %s] 分析失败", task.task_id)
            task.status = "failed"
            task.error = str(e)
        finally:
            task.updated_at = time.time()

    def _build_result(self, task: TaskRecord, done: dict) -> dict:
        """汇总最终报告 + 全部中间数据 + 该任务期间的 LLM token 消耗"""
        collect = done.get("collect") or {}
        technical = collect.get("technical")
        news = (done.get("sentiment") or {}).get("news_items") or collect.get("news_items") or []
        sentiment_update = done.get("sentiment") or {}
        sentiment = sentiment_update.get("sentiment")
        risk = (done.get("risk") or {}).get("risk")
        report = (done.get("report") or {}).get("report")

        # 逐条新闻情绪(情感 Agent 已回填 sentiment_score),供前端情绪时间线
        news_items = [{
            "title": n.title,
            "publish_time": n.publish_time.isoformat() if n.publish_time else None,
            "source": n.source or "",
            "sentiment_score": getattr(n, "sentiment_score", None),
            "content": (n.content or "")[:200],
        } for n in news]

        # 该任务期间的 token 增量
        after = dict(LLM_STATS)
        before = task._token_before
        llm_stats = {k: after.get(k, 0) - before.get(k, 0)
                     for k in ("calls", "prompt_tokens", "completion_tokens", "total_tokens")}

        return {
            "stock_code": task.stock_code,
            "report": report.model_dump(mode="json") if report else None,
            "technical": technical.model_dump(mode="json") if technical else None,
            "technical_analysis": (done.get("technical") or {}).get("technical_analysis"),
            "sentiment": sentiment.model_dump(mode="json") if sentiment else None,
            "sentiment_failed": bool(sentiment_update.get("sentiment_failed", False)),
            "risk": risk.model_dump(mode="json") if risk else None,
            "news_items": news_items,
            "data_source": task.data_source,
            "mode": task.mode,
            "llm_stats": llm_stats,
        }
