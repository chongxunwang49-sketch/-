"""
基本面分析 Agent(第四批)

- compute_fundamentals:从 AKShare 最佳努力抓取财务指标(营收增速/ROE/净利率),失败返回 None
- run_fundamental_agent:把财务数据交给 LLM 评估公司质地,输出 0-1 评分
降级:数据不可用或 LLM 失败时返回中性,不中断工作流。
"""
import logging
from typing import Optional

import pandas as pd

from ..schemas import FundamentalResult
from .llm import LLMClient, LLMError, extract_json
from .prompts import FUNDAMENTAL_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


def _num(v) -> Optional[float]:
    try:
        if v is None or pd.isna(v):
            return None
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None


def compute_fundamentals(stock_code: str) -> Optional[dict]:
    """抓取财务指标(最佳努力,失败返回 None)"""
    try:
        import akshare as ak
        df = ak.stock_financial_analysis_indicator(symbol=stock_code, start_year="2023")
        if df is None or df.empty:
            return None
        last = df.iloc[-1]
        return {
            "revenue_growth": _num(last.get("主营业务收入增长率")),
            "roe": _num(last.get("净资产收益率")),
            "profit_margin": _num(last.get("销售净利率")),
        }
    except Exception as e:
        logger.warning("[fundamental] 财务指标抓取失败(降级): %s", e)
        return None


def run_fundamental_agent(stock_code: str, client: LLMClient) -> FundamentalResult:
    """基本面分析:数据 -> LLM 质地评分"""
    data = compute_fundamentals(stock_code)
    if data and any(v is not None for v in data.values()):
        data_txt = (f"营收同比增速:{data['revenue_growth']}%, "
                    f"ROE:{data['roe']}%, 净利率:{data['profit_margin']}%")
        data_source = "real"
    else:
        data_txt = "财务数据暂不可用"
        data_source = "none"

    user_prompt = f"股票:{stock_code}\n财务数据:{data_txt}"
    try:
        out = extract_json(client.complete(FUNDAMENTAL_SYSTEM_PROMPT, user_prompt))
        score = max(0.0, min(1.0, float(out.get("score", 0.5))))
        summary = str(out.get("summary", ""))
        return FundamentalResult(stock_code=stock_code, score=score,
                                 revenue_growth=(data or {}).get("revenue_growth"),
                                 roe=(data or {}).get("roe"),
                                 profit_margin=(data or {}).get("profit_margin"),
                                 summary=summary, data_source=data_source)
    except (LLMError, ValueError, KeyError) as e:
        logger.warning("[fundamental] LLM 失败,降级中性: %s", e)
        return FundamentalResult(stock_code=stock_code, score=0.5,
                                 summary="基本面分析暂不可用", data_source=data_source)
