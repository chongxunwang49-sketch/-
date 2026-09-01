"""
技术分析 Agent(步骤8)
包含两部分:
  1. compute_indicators:从行情 DataFrame 计算技术指标(MA/RSI/MACD/涨跌幅)
  2. run_technical_agent:把指标交给 LLM 做技术面解读
"""
import logging
from datetime import date
from typing import Optional

import pandas as pd

from ..schemas import TechnicalIndicators
from .llm import LLMClient
from .prompts import TECHNICAL_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


def compute_indicators(df: pd.DataFrame, stock_code: str = "600519") -> Optional[TechnicalIndicators]:
    """
    从日线行情 DataFrame 计算技术指标。
    DataFrame 需含列:date/open_price/close_price/high_price/low_price/volume(与数据库一致)。
    返回 None 表示数据不足(少于 20 条无法算 MA20)。
    """
    if df is None or len(df) < 20:
        logger.warning("技术分析:行情不足 20 条,无法计算指标")
        return None
    df = df.sort_values("date").reset_index(drop=True)
    close = df["close_price"]

    close_ma5 = close.rolling(5).mean().iloc[-1]
    close_ma10 = close.rolling(10).mean().iloc[-1]
    close_ma20 = close.rolling(20).mean().iloc[-1]

    # RSI(14):标准 Wilder 简化实现(用简单平均)
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, float("nan"))
    rsi14 = float(100 - 100 / (1 + rs).iloc[-1]) if not pd.isna(rs.iloc[-1]) else None

    # MACD(12,26,9)
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    dif = ema12 - ema26
    dea = dif.ewm(span=9, adjust=False).mean()
    hist = dif - dea

    # 涨跌幅(%):最后一日的相对变化
    pct = (close.iloc[-1] / close.iloc[-2] - 1) * 100

    return TechnicalIndicators(
        stock_code=stock_code,
        latest_date=df["date"].iloc[-1] if isinstance(df["date"].iloc[-1], date) else pd.to_datetime(df["date"].iloc[-1]).date(),
        close_price=float(close.iloc[-1]),
        pct_change=round(float(pct), 2),
        ma5=round(float(close_ma5), 2),
        ma10=round(float(close_ma10), 2),
        ma20=round(float(close_ma20), 2),
        rsi14=round(rsi14, 2) if rsi14 is not None else None,
        macd_dif=round(float(dif.iloc[-1]), 3),
        macd_dea=round(float(dea.iloc[-1]), 3),
        macd_hist=round(float(hist.iloc[-1]), 3),
        volume=int(df["volume"].iloc[-1]),
    )


def run_technical_agent(indicators: TechnicalIndicators, client: LLMClient) -> str:
    """把技术指标交给 LLM 做技术面解读,返回解读文本"""
    user_prompt = f"请解读以下技术指标:\n{indicators.to_llm_text()}"
    if client.provider == "dify":
        # 用户在 dify 搭建的技术解读应用,输入变量名 indicators
        out = client.complete_dify({"indicators": indicators.to_llm_text()})
        return str(out.get("analysis", "")).strip()
    text = client.complete(TECHNICAL_SYSTEM_PROMPT, user_prompt)
    logger.info("技术解读完成: %s", text[:80])
    return text.strip()
