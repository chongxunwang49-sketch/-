"""
行情看板页(第三批)

- 顶部:市场指数行情条(上证/深证/创业板/沪深300/恒生/标普500)
- 中部:自选股列表(代码/名称/最新价/涨跌幅/技术信号)
- 底部:热点提示(占位,待第二批数据接入)
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from api_client import ApiError, watchlist_add, watchlist_list
from data_layer import cached_indices
from stock_map import COMMON_STOCKS, lookup_name


def _index_card(pal: dict, name: str, price, pct) -> str:
    if price is None:
        val, pct_cls, pct_txt = "—", "tc-muted", "暂无数据"
    else:
        pct = pct if pct is not None else 0.0
        val = f"{price:,.2f}"
        pct_cls = "tc-up" if pct >= 0 else "tc-down"
        pct_txt = f"{'+' if pct >= 0 else ''}{pct:.2f}%"
    return f"""
    <div class="tc-card" style="flex:1;min-width:130px;text-align:center;padding:12px 8px;">
      <div class="tc-label">{name}</div>
      <div class="tc-value" style="font-size:20px;">{val}</div>
      <div class="tc-sub {pct_cls}">{pct_txt}</div>
    </div>"""


def render(pal: dict):
    st.markdown(f'<div style="font-size:18px;font-weight:800;color:{pal["fg"]};">📊 行情看板</div>',
                unsafe_allow_html=True)

    # ---- 市场指数行情条 ----
    try:
        idx = cached_indices()
    except ApiError:
        idx = {"items": [], "source": "no_data"}
    items = idx.get("items") or []
    if items:
        cards = "".join(_index_card(pal, i["name"], i.get("price"), i.get("pct")) for i in items)
        st.markdown(f'<div style="display:flex;gap:8px;flex-wrap:wrap;">{cards}</div>',
                    unsafe_allow_html=True)
        _src = {"real": "实时(东财)", "backup": "日线(新浪兜底)", "no_data": "暂不可用"}.get(
            idx.get("source"), "暂不可用")
        st.caption(f"指数数据源:{_src} · 更新于 {idx.get('updated_at', '-')}")
    else:
        st.info("指数行情暂不可用(后端未启动或数据源不可达)。")

    st.markdown("---")

    # ---- 自选股列表 ----
    st.markdown(f'<div style="font-size:16px;font-weight:700;color:{pal["fg"]};">⭐ 我的自选股</div>',
                unsafe_allow_html=True)
    token = st.session_state.token
    try:
        wl = watchlist_list(token) or {"items": []}
    except ApiError as e:
        st.warning(f"自选股加载失败: {e}")
        wl = {"items": []}
    rows = wl.get("items") or []

    if rows:
        df = pd.DataFrame([{
            "代码": r["stock_code"],
            "名称": r.get("stock_name") or lookup_name(r["stock_code"]),
            "最新价": r.get("price") if r.get("price") is not None else "—",
            "涨跌幅": f"{r['pct_change']:+.2f}%" if r.get("pct_change") is not None else "—",
            "信号": ("🟢" if (r.get("pct_change") or 0) >= 0 else "🔴") if r.get("pct_change") is not None else "⚪",
        } for r in rows])
        st.dataframe(df, use_container_width=True, hide_index=True)
        st.caption("信号说明:🟢 上涨(偏多) / 🔴 下跌(偏空) / ⚪ 无数据 · 完整技术信号见「深度分析」")
    else:
        st.info("自选股为空。前往「⭐ 自选股」页添加,或点击下方快速添加。")

    # 快速添加
    st.markdown("#### 快速添加自选股")
    c1, c2 = st.columns([2, 1])
    options = ["手动输入"] + [f"{c} · {n}" for c, n in COMMON_STOCKS]
    pick = c1.selectbox("选择标的", options, key="dash_watch_pick")
    code = ""
    if pick != "手动输入":
        code = pick.split(" · ")[0]
    else:
        code = c1.text_input("股票代码", key="dash_watch_code").strip()
    if c2.button("➕ 添加", use_container_width=True):
        code = code or (pick.split(" · ")[0] if pick != "手动输入" else "")
        if code:
            try:
                watchlist_add(token, code)
                st.toast(f"已添加 {lookup_name(code)}", icon="⭐")
                st.rerun()
            except ApiError as e:
                st.toast(f"添加失败: {e}", icon="❌")
        else:
            st.toast("请输入股票代码", icon="⚠️")

    st.markdown("---")
    st.markdown(f"""
    <div class="tc-card" style="border-left:3px solid {pal['warning']};">
      <div style="font-size:14px;font-weight:700;color:{pal['fg']};">📌 市场热点 / 涨幅榜</div>
      <div style="font-size:12px;color:{pal['muted']};">待第二批「多源数据采集 + 板块/宏观」接入后展示。当前已具备:指数行情条 + 自选股 + 深度分析。</div>
    </div>""", unsafe_allow_html=True)
