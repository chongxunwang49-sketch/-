"""
资金流向 Agent(第四批)

- compute_fund_flow:从 AKShare 抓取主力资金净流入(万元,最佳努力)
- run_flow_agent:LLM 判断资金情绪(0-1)
"""
import logging
from typing import Optional

import pandas as pd

from ..schemas import FundFlowResult
from .llm import LLMClient, LLMError, extract_json
from .prompts import FLOW_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


def _num(v) -> Optional[float]:
    try:
        if v is None or pd.isna(v):
            return None
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None


def compute_fund_flow(stock_code: str) -> Optional[dict]:
    """抓取主力资金净流入(单位转万元,最佳努力)"""
    try:
        import akshare as ak
        market = "sh" if stock_code.startswith("6") else "sz"
        df = ak.stock_individual_fund_flow(stock=stock_code, market=market)
        if df is None or df.empty:
            return None
        col = "主力净流入-净额"
        last = df.iloc[-1]
        if col not in df.columns:
            return None
        return {"main_net": _num(last.get(col) / 1e4)}  # 元 -> 万元
    except Exception as e:
        logger.warning("[flow] 资金流向抓取失败(降级): %s", e)
        return None


def run_flow_agent(stock_code: str, client: LLMClient) -> FundFlowResult:
    data = compute_fund_flow(stock_code)
    if data and data.get("main_net") is not None:
        data_txt = f"主力资金净流入:{data['main_net']}万元"
        data_source = "real"
    else:
        data_txt = "资金数据暂不可用"
        data_source = "none"

    user_prompt = f"股票:{stock_code}\n资金数据:{data_txt}"
    try:
        out = extract_json(client.complete(FLOW_SYSTEM_PROMPT, user_prompt))
        return FundFlowResult(stock_code=stock_code,
                              score=max(0.0, min(1.0, float(out.get("score", 0.5)))),
                              main_net=(data or {}).get("main_net"),
                              summary=str(out.get("summary", "")), data_source=data_source)
    except (LLMError, ValueError, KeyError) as e:
        logger.warning("[flow] LLM 失败,降级中性: %s", e)
        return FundFlowResult(stock_code=stock_code, score=0.5,
                              summary="资金流向暂不可用", data_source=data_source)
