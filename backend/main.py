"""
FastAPI 后端入口(步骤13)

接口:
  GET  /health           健康检查
  POST /analyze          同步分析:返回 报告 + K线数据(简单调用方用)
  GET  /analyze/stream   流式分析(SSE):逐 Agent 推送进度,最后推送 报告+K线

启动: uvicorn backend.main:app --reload --port 8000
前端: streamlit run frontend/app.py
"""
import json
import logging
from typing import List

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .graph.workflow import _load_latest_quotes, build_workflow

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="多智能体股票分析系统", version="1.0")

# 启动时编译一次工作流,复用实例(避免每次请求重新编译)
_graph = build_workflow()


class AnalyzeRequest(BaseModel):
    stock_code: str = "600519"


def _initial_state(code: str) -> dict:
    """工作流初始 State"""
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
    }


def _quotes_to_list(code: str) -> List[dict]:
    """从数据库读行情,转成前端 K线可用的记录列表"""
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


@app.get("/health")
def health():
    return {"status": "ok", "service": "stock-agent-system"}


@app.post("/analyze")
def analyze(req: AnalyzeRequest):
    """同步分析:跑完整工作流,返回报告与 K 线数据"""
    from .graph.workflow import run_analysis
    report = run_analysis(req.stock_code)
    return {
        "report": report.model_dump(mode="json"),
        "quotes": _quotes_to_list(req.stock_code),
    }


@app.get("/analyze/stream")
def analyze_stream(stock_code: str = "600519"):
    """SSE 流式分析:每跑完一个 Agent 推一个事件,前端据此渲染进度条。"""

    def gen():
        try:
            events = _graph.stream(_initial_state(stock_code))
            report_data = None
            for event in events:
                node = next(iter(event))
                update = event[node]
                if node == "report" and update.get("report"):
                    report_data = update["report"].model_dump(mode="json")
                # 每个事件推一条 SSE(字段 node),done 事件附带最终报告+K线
                yield f"data: {json.dumps({'node': node}, ensure_ascii=False)}\n\n"
            quotes = _quotes_to_list(stock_code)
            yield f"data: {json.dumps({'node': 'done', 'report': report_data, 'quotes': quotes}, ensure_ascii=False)}\n\n"
        except Exception as e:
            logger.exception("流式分析失败")
            yield f"data: {json.dumps({'node': 'error', 'error': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")
