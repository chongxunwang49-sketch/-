"""
估值分析 Agent(第四批)

- compute_valuation:从 AKShare 抓取 PE/PB 及 PE 历史分位(最佳努力)
- run_valuation_agent:LLM 判断估值吸引力(0-1,高=低估)
"""
import logging
from typing import Optional

import pandas as pd

from ..schemas import ValuationResult
from .llm import LLMClient, LLMError, extract_json
from .prompts import VALUATION_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


def _num(v) -> Optional[float]:
    try:
        if v is None or pd.isna(v):
            return None
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None


def compute_valuation(stock_code: str) -> Optional[dict]:
    """抓取 PE/PB 与 PE 历史分位(最佳努力,失败返回 None)"""
    try:
        import akshare as ak
        df = ak.stock_a_indicator_lg(symbol=stock_code)
        if df is None or df.empty:
            return None
        pe_col = "pe_ttm" if "pe_ttm" in df.columns else "pe"
        last_pe = _num(df.iloc[-1].get(pe_col))
        pe_series = df[pe_col].dropna()
        percentile = None
        if last_pe is not None and len(pe_series) > 0:
            percentile = round(float((pe_series <= last_pe).mean()), 3)
        return {
            "pe": last_pe,
            "pb": _num(df.iloc[-1].get("pb")),
            "pe_percentile": percentile,
        }
    except Exception as e:
        logger.warning("[valuation] 估值数据抓取失败(降级): %s", e)
        return None


def run_valuation_agent(stock_code: str, client: LLMClient) -> ValuationResult:
    data = compute_valuation(stock_code)
    if data and data.get("pe") is not None:
        data_txt = (f"PE:{data['pe']}, PB:{data['pb']}, "
                    f"PE历史分位:{data['pe_percentile']}")
        data_source = "real"
    else:
        data_txt = "估值数据暂不可用"
        data_source = "none"

    user_prompt = f"股票:{stock_code}\n估值数据:{data_txt}"
    try:
        out = extract_json(client.complete(VALUATION_SYSTEM_PROMPT, user_prompt))
        return ValuationResult(stock_code=stock_code,
                               score=max(0.0, min(1.0, float(out.get("score", 0.5)))),
                               pe=(data or {}).get("pe"),
                               pb=(data or {}).get("pb"),
                               pe_percentile=(data or {}).get("pe_percentile"),
                               summary=str(out.get("summary", "")), data_source=data_source)
    except (LLMError, ValueError, KeyError) as e:
        logger.warning("[valuation] LLM 失败,降级中性: %s", e)
        return ValuationResult(stock_code=stock_code, score=0.5,
                               summary="估值分析暂不可用", data_source=data_source)
