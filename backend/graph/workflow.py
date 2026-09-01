"""
LangGraph 多智能体编排(步骤10+步骤11)

流程图:
  采集(collect)
    ├─▶ 技术分析(technical) ─┐
    └─▶ 情感分析(sentiment) ─┼─▶ 风险评估(risk) ─▶ 报告生成(report) ─▶ END
                              (technical 与 sentiment 并行 fan-out)
  条件路由:collect 后若新闻为空 -> 跳过 sentiment 直接 risk(数据驱动降级)
  异常降级:任一 Agent 抛异常 -> 节点捕获后在 State 打标记 ->
            risk 用规则兜底 / report 生成降级报告,图不崩

编译入口:build_workflow()
执行入口:run_analysis(stock_code)
"""
import concurrent.futures
import logging
import sys
from pathlib import Path
from typing import List, Optional, TypedDict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))  # 项目根

import pandas as pd  # noqa: E402
from langgraph.graph import END, START, StateGraph  # noqa: E402

from ..agents.event import run_event_agent  # noqa: E402
from ..agents.flow import run_flow_agent  # noqa: E402
from ..agents.fundamental import run_fundamental_agent  # noqa: E402
from ..agents.industry import run_industry_agent  # noqa: E402
from ..agents.llm import LLMClient  # noqa: E402
from ..agents.report import run_report_agent  # noqa: E402
from ..agents.risk import run_risk_agent, _rule_based_fallback  # noqa: E402
from ..agents.sentiment import run_sentiment_agent  # noqa: E402
from ..agents.technical import compute_indicators, run_technical_agent  # noqa: E402
from ..agents.valuation import run_valuation_agent  # noqa: E402
from ..models import StockPrice  # noqa: E402
from ..models import engine  # noqa: E402
from ..schemas import (  # noqa: E402
    AnalysisReport,
    EventResult,
    FundamentalResult,
    FundFlowResult,
    IndustryResult,
    NewsItem,
    RiskAssessment,
    SentimentResult,
    TechnicalIndicators,
    ValuationResult,
)
from sqlalchemy import select  # noqa: E402

# 单个 Agent 超时熔断阈值(第四批):超过 30 秒未返回则跳过该 Agent 并记录
NODE_TIMEOUT_SECONDS = 30

logger = logging.getLogger(__name__)

# 复用 scripts 里的采集函数(含三级降级链)
from scripts.fetch_news import fetch_news_data  # noqa: E402
from scripts.fetch_stock_data import fetch_stock_with_degradation  # noqa: E402

# LLM 客户端进程内复用(避免每次节点调用都重新初始化)
_llm_cache: Optional[LLMClient] = None


def _llm() -> LLMClient:
    global _llm_cache
    if _llm_cache is None:
        _llm_cache = LLMClient()
    return _llm_cache


# ------------------------------------------------------------
# State:多智能体之间的共享状态(步骤9/10)
# ------------------------------------------------------------
class WorkflowState(TypedDict):
    stock_code: str
    news_items: List[NewsItem]
    technical: Optional[TechnicalIndicators]
    technical_analysis: Optional[str]
    sentiment: Optional[SentimentResult]
    sentiment_failed: bool
    fundamental: Optional[FundamentalResult]   # 第四批:基本面
    valuation: Optional[ValuationResult]       # 第四批:估值
    flow: Optional[FundFlowResult]             # 第四批:资金流向
    industry: Optional[IndustryResult]         # 第四批:行业
    event: Optional[EventResult]               # 第四批:事件驱动
    risk: Optional[RiskAssessment]
    report: Optional[AnalysisReport]
    data_source: str  # real/backup/mock,来自采集降级链
    mode: str  # full=完整链路 / quick=仅技术→风险→报告(专业看板升级,默认 full)


# ------------------------------------------------------------
# 数据层辅助:从数据库读行情/新闻
# ------------------------------------------------------------
def _load_latest_quotes(code: str) -> Optional[pd.DataFrame]:
    """从 PostgreSQL 读最近 60 个交易日行情,用于技术指标计算"""
    with engine.connect() as conn:
        rows = conn.execute(
            select(StockPrice).where(StockPrice.stock_code == code).order_by(StockPrice.date.desc()).limit(60)
        ).all()
    if not rows:
        return None
    df = pd.DataFrame([{
        "date": r.date, "open_price": r.open_price, "close_price": r.close_price,
        "high_price": r.high_price, "low_price": r.low_price, "volume": r.volume,
    } for r in rows])
    return df.sort_values("date").reset_index(drop=True)


def _load_news(code: str) -> List[NewsItem]:
    """从 PostgreSQL 读该股票最近的新闻"""
    from ..models import NewsArticle
    with engine.connect() as conn:
        rows = conn.execute(
            select(NewsArticle).where(NewsArticle.stock_code == code).order_by(NewsArticle.publish_time.desc()).limit(10)
        ).all()
    return [
        NewsItem(stock_code=r.stock_code, title=r.title, content=r.content,
                 publish_time=r.publish_time, source=r.source)
        for r in rows
    ]


# ------------------------------------------------------------
# 节点:5 个 Agent
# ------------------------------------------------------------
def collect_node(state: WorkflowState) -> dict:
    """采集:行情(带三级降级)+ 新闻,写入 State。quick 模式跳过新闻抓取与情感分析。"""
    code = state["stock_code"]
    logger.info("[collect] 开始采集 %s (mode=%s)", code, state.get("mode", "full"))

    # 行情:调三级降级链(主源失败自动降级),数据入库
    result = fetch_stock_with_degradation(code)
    df = _load_latest_quotes(code)
    technical = compute_indicators(df, code) if df is not None else None
    if technical is None:
        logger.warning("[collect] 行情不足 20 条,技术指标不可用")

    # 新闻:快速模式不抓新闻(情感分析随之跳过),完整模式刷新并读库(关键词用公司名)
    news: List[NewsItem] = []
    if state.get("mode") != "quick":
        try:
            from ..agents.report import COMPANY_NAMES
            keyword = COMPANY_NAMES.get(code, code)
            fetch_news_data(stock_code=code, keyword=keyword)
        except Exception as e:
            logger.warning("[collect] 新闻刷新失败(用库中已有数据): %s", e)
        news = _load_news(code)
    logger.info("[collect] 完成: source=%s, 新闻 %d 条", result.get("source"), len(news))

    return {
        "technical": technical,
        "news_items": news,
        "data_source": result.get("source", "real"),
    }


def technical_node(state: WorkflowState) -> dict:
    """技术分析:指标 -> LLM 解读"""
    tech = state.get("technical")
    if tech is None:
        return {"technical_analysis": "数据不足,无法解读"}
    try:
        analysis = run_technical_agent(tech, _llm())
        return {"technical_analysis": analysis}
    except Exception as e:
        logger.error("[technical] 降级(无技术解读): %s", e)
        return {"technical_analysis": "技术分析暂不可用"}


def sentiment_node(state: WorkflowState) -> dict:
    """情感分析:新闻 -> 情感得分(并回填单条新闻得分);异常时打降级标记,不中断图"""
    code = state["stock_code"]
    items = state.get("news_items") or []
    try:
        sentiment = run_sentiment_agent(items, _llm(), code)
        return {"sentiment": sentiment, "sentiment_failed": False, "news_items": items}
    except Exception as e:
        logger.error("[sentiment] 降级(返回中性): %s", e)
        return {
            "sentiment": SentimentResult(stock_code=code, score=0.5,
                                         reason="情感分析降级,默认中性", source="degraded"),
            "sentiment_failed": True,
            "news_items": items,
        }


# ------------------------------------------------------------
# 超时熔断(第四批):单个 Agent 超过 NODE_TIMEOUT_SECONDS 未返回则跳过并记录
# ------------------------------------------------------------
def timeout_guard(node_fn, default_builder):
    """包装节点函数:线程内执行,超时返回 default_builder(state) 的降级结果。

    说明:线程无法强杀,超时后后台线程继续跑但结果被丢弃(不阻塞主流程)。
    """
    def wrapped(state: WorkflowState) -> dict:
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        future = executor.submit(node_fn, state)
        try:
            return future.result(timeout=NODE_TIMEOUT_SECONDS)
        except concurrent.futures.TimeoutError:
            logger.warning("[%s] 超时熔断(>%ds),跳过该 Agent",
                           getattr(node_fn, "__name__", "node"), NODE_TIMEOUT_SECONDS)
            default = default_builder(state)
            default["timed_out"] = True  # 供 task_manager 在流水线标注
            return default
        finally:
            executor.shutdown(wait=False)  # 不等待被熔断线程

    wrapped.__name__ = getattr(node_fn, "__name__", "wrapped")
    return wrapped


# ------------------------------------------------------------
# 第四批:基本面 / 估值 / 资金流向 / 行业 / 事件驱动 节点
# ------------------------------------------------------------
def fundamental_node(state: WorkflowState) -> dict:
    """基本面分析:财务数据 -> 公司质地评分"""
    code = state["stock_code"]
    try:
        return {"fundamental": run_fundamental_agent(code, _llm())}
    except Exception as e:
        logger.error("[fundamental] 降级: %s", e)
        return {"fundamental": FundamentalResult(stock_code=code, score=0.5,
                                                 summary="基本面分析暂不可用")}


def _default_fundamental(state: WorkflowState) -> dict:
    return {"fundamental": FundamentalResult(stock_code=state["stock_code"], score=0.5,
                                             summary="基本面分析超时/不可用")}


def valuation_node(state: WorkflowState) -> dict:
    """估值分析:PE/PB -> 估值吸引力(依赖基本面节点完成后运行)"""
    code = state["stock_code"]
    try:
        return {"valuation": run_valuation_agent(code, _llm())}
    except Exception as e:
        logger.error("[valuation] 降级: %s", e)
        return {"valuation": ValuationResult(stock_code=code, score=0.5,
                                             summary="估值分析暂不可用")}


def _default_valuation(state: WorkflowState) -> dict:
    return {"valuation": ValuationResult(stock_code=state["stock_code"], score=0.5,
                                         summary="估值分析超时/不可用")}


def flow_node(state: WorkflowState) -> dict:
    """资金流向:主力资金净流入 -> 资金情绪"""
    code = state["stock_code"]
    try:
        return {"flow": run_flow_agent(code, _llm())}
    except Exception as e:
        logger.error("[flow] 降级: %s", e)
        return {"flow": FundFlowResult(stock_code=code, score=0.5,
                                       summary="资金流向暂不可用")}


def _default_flow(state: WorkflowState) -> dict:
    return {"flow": FundFlowResult(stock_code=state["stock_code"], score=0.5,
                                   summary="资金流向超时/不可用")}


def industry_node(state: WorkflowState) -> dict:
    """行业分析:行业映射 + LLM 景气度判断"""
    code = state["stock_code"]
    try:
        return {"industry": run_industry_agent(code, _llm())}
    except Exception as e:
        logger.error("[industry] 降级: %s", e)
        return {"industry": IndustryResult(stock_code=code, score=0.5,
                                           summary="行业分析暂不可用")}


def _default_industry(state: WorkflowState) -> dict:
    return {"industry": IndustryResult(stock_code=state["stock_code"], score=0.5,
                                       summary="行业分析超时/不可用")}


def event_node(state: WorkflowState) -> dict:
    """事件驱动:新闻/公告 -> 事件影响方向"""
    code = state["stock_code"]
    items = state.get("news_items") or []
    try:
        return {"event": run_event_agent(items, _llm(), code)}
    except Exception as e:
        logger.error("[event] 降级: %s", e)
        return {"event": EventResult(stock_code=code, score=0.5,
                                     events=[], summary="事件分析暂不可用")}


def _default_event(state: WorkflowState) -> dict:
    return {"event": EventResult(stock_code=state["stock_code"], score=0.5,
                                 events=[], summary="事件分析超时/不可用")}


def risk_node(state: WorkflowState) -> dict:
    """风险评估:情感+技术 -> 风险;情感失败时走纯技术规则兜底"""
    code = state["stock_code"]
    if state.get("sentiment_failed"):
        logger.warning("[risk] 情感不可用,改用纯技术指标规则评估")
        risk = _rule_based_fallback(None, state.get("technical_analysis"), code)
    else:
        try:
            risk = run_risk_agent(state.get("sentiment"), state.get("technical_analysis"),
                                  _llm(), code)
        except Exception as e:
            logger.error("[risk] 降级(规则兜底): %s", e)
            risk = _rule_based_fallback(state.get("sentiment"), state.get("technical_analysis"), code)
    return {"risk": risk}


def report_node(state: WorkflowState) -> dict:
    """报告生成:汇总所有环节 -> 最终 Markdown 报告(含 RAG 知识库引用,防幻觉)"""
    code = state["stock_code"]

    # RAG 检索:从知识库捞该股票相关的财报片段,供报告引用;检索失败则跳过(不阻断)
    rag_sources: list = []
    try:
        from ..services.vector_store import retrieve as rag_retrieve
        from ..agents.report import COMPANY_NAMES
        query = f"{COMPANY_NAMES.get(code, code)} {code} 财务数据 营收 净利润"
        result = rag_retrieve(query, top_k=3)
        rag_sources = result.get("documents", [[]])[0]
        logger.info("[report] RAG 命中 %d 条知识库片段", len(rag_sources))
    except Exception as e:
        logger.warning("[report] RAG 检索不可用,报告不带知识库引用: %s", e)

    try:
        report = run_report_agent(
            state.get("sentiment"), state.get("technical_analysis"), state.get("risk"),
            _llm(), code, state.get("data_source", "real"), rag_sources,
            fundamental=state.get("fundamental"), valuation=state.get("valuation"),
            flow=state.get("flow"), industry=state.get("industry"), event=state.get("event"),
        )
        return {"report": report}
    except Exception as e:
        logger.error("[report] 降级(占位报告): %s", e)
        report = AnalysisReport(
            stock_code=code, company_name=code,
            report="## 综合结论\n报告生成环节暂不可用,请稍后重试。",
            data_source=state.get("data_source", "real"),
            rag_sources=rag_sources,
        )
        return {"report": report}


# ------------------------------------------------------------
# 条件路由:新闻为空时跳过情感分析(步骤10 的 Conditional Edge)
# ------------------------------------------------------------
def _route_after_collect(state: WorkflowState) -> list:
    """条件 fan-out(第四批):
    - quick 模式:仅 technical(快速路径:采集→技术→风险→报告)
    - full 模式:technical + fundamental + flow + industry + event 并行,
      新闻非空时再加 sentiment(无新闻则跳过情感分析,沿用原降级)
    """
    if state.get("mode") == "quick":
        return ["technical"]
    targets = ["technical", "fundamental", "flow", "industry", "event"]
    if state.get("news_items"):
        targets.append("sentiment")
    return targets


# ------------------------------------------------------------
# 构图与执行
# ------------------------------------------------------------
def build_workflow():
    """构建并编译 LangGraph 状态图(第四批:并行组扩大 + 超时熔断 + 条件依赖)

    collect
      ├─▶ technical ──────────────┐
      ├─▶ sentiment(新闻非空时) ───┼─▶ risk ─▶ report ─▶ END
      ├─▶ fundamental ─▶ valuation┘
      ├─▶ flow ───────────────────┘
      ├─▶ industry ───────────────┘
      └─▶ event ──────────────────┘
    quick 模式只走 technical → risk → report
    """
    g = StateGraph(WorkflowState)

    # 数据采集不设超时(它承载三级降级采集,是整条链路的数据地基)
    g.add_node("collect", collect_node)
    # 分析类节点统一接入超时熔断(>30s 跳过并记录)
    g.add_node("technical", timeout_guard(technical_node, lambda s: {"technical_analysis": "技术分析超时"}))
    g.add_node("sentiment", timeout_guard(sentiment_node, lambda s: {
        "sentiment": SentimentResult(stock_code=s["stock_code"], score=0.5,
                                     reason="情感分析超时", source="timeout"),
        "sentiment_failed": True}))
    g.add_node("fundamental", timeout_guard(fundamental_node, _default_fundamental))
    g.add_node("valuation", timeout_guard(valuation_node, _default_valuation))
    g.add_node("flow", timeout_guard(flow_node, _default_flow))
    g.add_node("industry", timeout_guard(industry_node, _default_industry))
    g.add_node("event", timeout_guard(event_node, _default_event))
    g.add_node("risk", timeout_guard(risk_node, lambda s: {
        "risk": _rule_based_fallback(s.get("sentiment"), s.get("technical_analysis"), s["stock_code"]),
        "risk_timeout": True}))
    g.add_node("report", timeout_guard(report_node, lambda s: {"report": AnalysisReport(
        stock_code=s["stock_code"], company_name=s["stock_code"],
        report="## 综合结论\n报告生成环节超时,请稍后重试。",
        data_source=s.get("data_source", "real"))}))

    g.add_edge(START, "collect")
    # 并行 fan-out(quick 模式只出 technical)
    g.add_conditional_edges("collect", _route_after_collect,
                            {"technical": "technical", "sentiment": "sentiment",
                             "fundamental": "fundamental", "flow": "flow",
                             "industry": "industry", "event": "event"})
    # 条件依赖:估值分析依赖基本面
    g.add_edge("fundamental", "valuation")
    # fan-in 汇聚到 risk
    for node in ("technical", "sentiment", "valuation", "flow", "industry", "event"):
        g.add_edge(node, "risk")
    g.add_edge("risk", "report")
    g.add_edge("report", END)

    return g.compile()


def run_analysis(stock_code: str, mode: str = "full") -> AnalysisReport:
    """
    主执行入口:输入股票代码,跑完整多智能体流程,返回最终报告。
    示例: run_analysis("600519")
    mode: full=完整链路 / quick=跳过情感分析(专业看板升级)
    """
    graph = build_workflow()
    result = graph.invoke({
        "stock_code": stock_code,
        "news_items": [],
        "technical": None,
        "technical_analysis": None,
        "sentiment": None,
        "sentiment_failed": False,
        "fundamental": None,
        "valuation": None,
        "flow": None,
        "industry": None,
        "event": None,
        "risk": None,
        "report": None,
        "data_source": "real",
        "mode": mode,
    })
    report = result.get("report")
    if report is None:
        raise RuntimeError("工作流未生成报告")
    logger.info("run_analysis(%s) 完成: 数据源=%s", stock_code, result.get("data_source"))
    return report
