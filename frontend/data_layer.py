"""
共享数据层(第三批前端重构)

所有页面共用的后端数据缓存(带 TTL),避免每个页面重复拉取/卡顿。
"""
from __future__ import annotations

import streamlit as st

from api_client import market_indices, stock_history, stock_info


@st.cache_data(ttl=120, show_spinner=False)
def cached_info(code: str) -> dict:
    """股票基础信息(名称/现价/涨跌幅/指标快照)"""
    return stock_info(code)


@st.cache_data(ttl=120, show_spinner=False)
def cached_history(code: str, time_range: str, start: str, end: str) -> dict:
    """K线历史(含指标序列)"""
    return stock_history(code, time_range, start=start, end=end)


@st.cache_data(ttl=300, show_spinner=False)
def cached_indices() -> dict:
    """市场指数行情条"""
    return market_indices()


def clear_all_cached() -> None:
    """清除行情缓存(分析完成后调用,让新数据生效)"""
    cached_info.clear()
    cached_history.clear()
    cached_indices.clear()
