"""
步骤14-测试场景②:技术指标计算
- 数据不足(<20条)返回 None(触发下游"数据不足"降级)
- 均线/涨跌幅计算正确
"""
import datetime as dt

import pandas as pd

from backend.agents.technical import compute_indicators


def _make_df(n: int, base: float = 1200.0) -> pd.DataFrame:
    """构造 n 天单调上涨的行情(收盘=开盘,高+1 低-1)"""
    dates = [dt.date(2026, 1, 1) + dt.timedelta(days=i) for i in range(n)]
    close = [base + i for i in range(n)]
    return pd.DataFrame({
        "date": dates,
        "open_price": close,
        "close_price": close,
        "high_price": [c + 1 for c in close],
        "low_price": [c - 1 for c in close],
        "volume": [10000] * n,
    })


def test_insufficient_data_returns_none():
    """少于 20 条 -> 无法算 MA20 -> 返回 None(触发降级)"""
    assert compute_indicators(_make_df(10), "600519") is None


def test_ma20_correct():
    """MA20 = 最近 20 日收盘均值"""
    ind = compute_indicators(_make_df(30), "600519")
    assert ind is not None
    # 收盘价 1200..1229,最后 20 条 1210..1229,均值 = 1219.5
    assert abs(ind.ma20 - 1219.5) < 0.01


def test_pct_change_correct():
    ind = compute_indicators(_make_df(30), "600519")
    assert ind is not None
    # 连续 +1 元,最新日涨幅 = 1/1228 ≈ 0.0814%
    assert abs(ind.pct_change - (1 / 1228 * 100)) < 0.01


def test_macd_fields_present():
    ind = compute_indicators(_make_df(40), "600519")
    assert ind is not None
    assert ind.macd_dif is not None
    assert ind.macd_dea is not None
