"""
FastAPI 后端入口(步骤13 + 专业看板升级)

接口:
  基础数据
    GET  /health               健康检查
    GET  /stock/info           股票基础信息(名称/现价/涨跌幅/技术指标快照)
    GET  /stock/history        K线历史(时间范围 + MA/MACD/RSI/BOLL 指标序列)
  分析任务(异步轮询,前端不再长连接)
    POST /analyze              异步启动分析 -> {task_id}(mode: quick/full)
    GET  /task/status          轮询任务状态(各 Agent 进度/耗时/降级标记)
    GET  /task/result          获取最终报告与全部中间数据
  兼容旧接口(保留,不影响新前端)
    POST /analyze/sync         同步分析(原 /analyze 语义)
    GET  /analyze/stream       SSE 流式分析

启动: uvicorn backend.main:app --reload --port 8000
前端: streamlit run frontend/app.py
"""
import json
import logging
from datetime import date, datetime, timedelta
from typing import List

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator
from sqlalchemy import select

from .graph.workflow import _load_latest_quotes, build_workflow
from .models import StockPrice, engine
from .services import stock_meta
from .services.task_manager import TaskManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="多智能体股票分析系统", version="2.0")

# 异步任务管理器(后台线程执行分析,前端轮询状态)
task_manager = TaskManager()

# 启动时编译一次工作流,复用实例(SSE 兼容接口用)
_graph = build_workflow()


class AnalyzeRequest(BaseModel):
    stock_code: str = "600519"
    mode: str = "full"  # quick=跳过情感分析 / full=完整链路

    @field_validator("mode")
    @classmethod
    def _check_mode(cls, v: str) -> str:
        return v if v in ("quick", "full") else "full"


def _initial_state(code: str, mode: str = "full") -> dict:
    """工作流初始 State(SSE 兼容接口用)"""
    return {
        "stock_code": code,
        "news_items": [],
        "technical": None,
        "technical_analysis": None,
        "sentiment": None,
        "sentiment_failed": False,
        "risk": None,
        "report": None,
        "data_source": "real",
        "mode": mode,
    }


# ------------------------------------------------------------
# 数据层辅助:行情读写
# ------------------------------------------------------------
def _load_history(code: str, start_date: date, end_date: date) -> List:
    """按日期区间从 PostgreSQL 读行情(升序)"""
    with engine.connect() as conn:
        rows = conn.execute(
            select(StockPrice)
            .where(StockPrice.stock_code == code,
                   StockPrice.date >= start_date,
                   StockPrice.date <= end_date)
            .order_by(StockPrice.date)
        ).all()
    return rows


def _f2(v) -> float | None:
    """转两位小数;NaN/None 转 None"""
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None


def _f3(v) -> float | None:
    """转三位小数;NaN/None 转 None"""
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
        return round(float(v), 3)
    except (TypeError, ValueError):
        return None


def _history_payload(code: str, rows: List) -> List[dict]:
    """把行情行转成含 MA/MACD/RSI/BOLL 序列的记录列表(供 Plotly 直接绘图)"""
    df = pd.DataFrame([{
        "date": r.date, "open": r.open_price, "high": r.high_price,
        "low": r.low_price, "close": r.close_price, "volume": r.volume,
    } for r in rows])
    if df.empty:
        return []
    close = df["close"]
    for w in (5, 10, 20, 60):
        df[f"ma{w}"] = close.rolling(w).mean()
    df["boll_mid"] = close.rolling(20).mean()
    df["boll_std"] = close.rolling(20).std()
    df["boll_up"] = df["boll_mid"] + 2 * df["boll_std"]
    df["boll_low"] = df["boll_mid"] - 2 * df["boll_std"]
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    df["macd_dif"] = ema12 - ema26
    df["macd_dea"] = (ema12 - ema26).ewm(span=9, adjust=False).mean()
    df["macd_hist"] = df["macd_dif"] - df["macd_dea"]
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, float("nan"))
    df["rsi14"] = 100 - 100 / (1 + rs)

    out = []
    for r in df.itertuples():
        out.append({
            "date": str(r.date),
            "open": _f2(r.open), "high": _f2(r.high), "low": _f2(r.low), "close": _f2(r.close),
            "volume": int(r.volume),
            "ma5": _f2(r.ma5), "ma10": _f2(r.ma10), "ma20": _f2(r.ma20), "ma60": _f2(r.ma60),
            "boll_up": _f2(r.boll_up), "boll_mid": _f2(r.boll_mid), "boll_low": _f2(r.boll_low),
            "macd_dif": _f3(r.macd_dif), "macd_dea": _f3(r.macd_dea), "macd_hist": _f3(r.macd_hist),
            "rsi14": _f2(r.rsi14),
        })
    return out


def _latest_indicators(code: str) -> dict | None:
    """基于最近 60 个交易日计算技术指标快照(行情不足 20 条返回 None)"""
    df = _load_latest_quotes(code)
    if df is None or len(df) < 20:
        return None
    from .agents.technical import compute_indicators
    ti = compute_indicators(df, code)
    if ti is None:
        return None
    close = df["close_price"]
    ma20 = close.rolling(20).mean().iloc[-1]
    std20 = close.rolling(20).std().iloc[-1]
    return {
        "close_price": ti.close_price,
        "pct_change": ti.pct_change,
        "rsi14": ti.rsi14,
        "macd_dif": ti.macd_dif,
        "macd_dea": ti.macd_dea,
        "macd_hist": ti.macd_hist,
        "ma5": ti.ma5, "ma10": ti.ma10, "ma20": ti.ma20,
        "boll_up": _f2(ma20 + 2 * std20),
        "boll_mid": _f2(ma20),
        "boll_low": _f2(ma20 - 2 * std20),
    }


def _quotes_to_list(code: str) -> List[dict]:
    """从数据库读行情,转成前端 K线可用的记录列表(SSE 兼容接口用)"""
    df = _load_latest_quotes(code)
    if df is None:
        return []
    return [{
        "date": str(r["date"]),
        "open": float(r["open_price"]),
        "high": float(r["high_price"]),
        "low": float(r["low_price"]),
        "close": float(r["close_price"]),
        "volume": int(r["volume"]),
    } for r in df.to_dict("records")]


# ------------------------------------------------------------
# 健康检查
# ------------------------------------------------------------
@app.get("/health")
def health():
    return {"status": "ok", "service": "stock-agent-system"}


# ------------------------------------------------------------
# 基础数据:股票信息 / 历史行情
# ------------------------------------------------------------
@app.get("/stock/info")
def stock_info(code: str = "600519"):
    """返回基础信息(名称/现价/涨跌幅/最新技术指标快照)。不触发网络采集,仅读库。"""
    name = stock_meta.lookup_name(code)
    try:
        rows = _load_history(code, date(1900, 1, 1), date.today())
    except Exception as e:
        logger.warning("/stock/info 读库失败: %s", e)
        rows = []
    if len(rows) < 2:
        return {"code": code, "name": name, "price": None, "pct_change": None,
                "latest_date": None, "open": None, "high": None, "low": None,
                "volume": None, "data_source": "no_data", "indicators": None}
    latest, prev = rows[-1], rows[-2]
    pct = round((latest.close_price / prev.close_price - 1) * 100, 2)
    return {
        "code": code, "name": name,
        "price": latest.close_price, "pct_change": pct,
        "latest_date": str(latest.date),
        "open": latest.open_price, "high": latest.high_price,
        "low": latest.low_price, "volume": latest.volume,
        "data_source": "db", "indicators": _latest_indicators(code),
    }


@app.get("/stock/history")
def stock_history(
    code: str = "600519",
    range: str = Query("3m", alias="range", description="1m/3m/6m/1y/custom"),
    start: str = Query("", alias="start", description="自定义起始日期 YYYY-MM-DD"),
    end: str = Query("", alias="end", description="自定义结束日期 YYYY-MM-DD"),
):
    """K线历史:按时间范围读库并返回 MA/MACD/RSI/BOLL 序列。库中无数据时按需采集(最佳努力)。"""
    days = {"1m": 30, "3m": 90, "6m": 180, "1y": 365}
    ndays = days.get(range, 90)
    end_date = date.today()
    if end:
        try:
            end_date = datetime.strptime(end, "%Y-%m-%d").date()
        except ValueError:
            pass
    if start:
        try:
            start_date = datetime.strptime(start, "%Y-%m-%d").date()
        except ValueError:
            start_date = end_date - timedelta(days=ndays)
    else:
        start_date = end_date - timedelta(days=ndays)

    rows = _load_history(code, start_date, end_date)
    if not rows:
        # 首次访问该股票:触发三级降级采集,让图表有数据可画
        try:
            from scripts.fetch_stock_data import fetch_stock_with_degradation
            fetch_stock_with_degradation(code, max(ndays, 90))
        except Exception as e:
            logger.warning("/stock/history 按需采集失败: %s", e)
        rows = _load_history(code, start_date, end_date)

    payload = _history_payload(code, rows) if rows else []
    return {"code": code, "name": stock_meta.lookup_name(code), "rows": payload, "count": len(payload)}


# ------------------------------------------------------------
# 异步分析任务
# ------------------------------------------------------------
@app.post("/analyze")
def start_analysis(req: AnalyzeRequest):
    """异步启动分析,立即返回 task_id。mode: quick=跳过情感分析(更快) / full=完整链路"""
    task = task_manager.create(req.stock_code, mode=req.mode)
    logger.info("启动分析任务: task_id=%s code=%s mode=%s", task.task_id, req.stock_code, req.mode)
    return {"task_id": task.task_id, "status": task.status, "stock_code": req.stock_code}


@app.get("/task/status")
def task_status(task_id: str):
    """轮询任务状态:各 Agent 阶段(等待/运行/完成/跳过/失败)+ 耗时 + 降级标记"""
    task = task_manager.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")
    return task.to_dict()


@app.get("/task/result")
def task_result(task_id: str):
    """获取最终报告与全部中间数据(任务未完成时返回 status=running)"""
    task = task_manager.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")
    if task.status == "running":
        return {"task_id": task_id, "status": "running", "result": None}
    if task.status == "failed":
        return {"task_id": task_id, "status": "failed", "error": task.error, "result": None}
    return {"task_id": task_id, "status": "completed", "result": task.result}


# ------------------------------------------------------------
# 兼容旧接口(保留)
# ------------------------------------------------------------
@app.post("/analyze/sync")
def analyze_sync(req: AnalyzeRequest):
    """同步分析:跑完整工作流,返回报告与 K 线数据(旧 /analyze 语义)"""
    from .graph.workflow import run_analysis
    report = run_analysis(req.stock_code, mode=req.mode)
    return {
        "report": report.model_dump(mode="json"),
        "quotes": _quotes_to_list(req.stock_code),
    }


@app.get("/analyze/stream")
def analyze_stream(stock_code: str = "600519"):
    """SSE 流式分析:每跑完一个 Agent 推一个事件,前端据此渲染进度条(旧接口,保留)"""

    def gen():
        try:
            events = _graph.stream(_initial_state(stock_code))
            report_data = None
            for event in events:
                node = next(iter(event))
                update = event[node]
                if node == "report" and update.get("report"):
                    report_data = update["report"].model_dump(mode="json")
                yield f"data: {json.dumps({'node': node}, ensure_ascii=False)}\n\n"
            quotes = _quotes_to_list(stock_code)
            yield f"data: {json.dumps({'node': 'done', 'report': report_data, 'quotes': quotes}, ensure_ascii=False)}\n\n"
        except Exception as e:
            logger.exception("流式分析失败")
            yield f"data: {json.dumps({'node': 'error', 'error': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")
