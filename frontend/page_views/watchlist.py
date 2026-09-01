"""
自选股管理页(第三批)

- 自选股列表:代码/名称/最新价/涨跌幅/技术信号,每行可移除
- 添加自选股:搜索框 + 自动补全(映射表)
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from api_client import ApiError, watchlist_add, watchlist_delete, watchlist_list
from stock_map import COMMON_STOCKS, lookup_name


def render(pal: dict):
    st.markdown(f'<div class="tc-enter" style="font-size:18px;font-weight:800;color:{pal["fg"]};">⭐ 星标自选</div>',
                unsafe_allow_html=True)
    token = st.session_state.token

    # ---- 添加 ----
    st.markdown("#### ➕ 添加自选股")
    c1, c2 = st.columns([2.2, 1])
    options = ["手动输入"] + [f"{c} · {n}" for c, n in COMMON_STOCKS]
    pick = c1.selectbox("选择或输入", options, key="wl_pick")
    if pick != "手动输入":
        code = pick.split(" · ")[0]
    else:
        code = c1.text_input("股票代码", key="wl_code").strip()
    resolved = lookup_name(code)
    if code:
        st.caption(f"✓ 已识别: {resolved}" if resolved != code else "未收录代码,按代码保存")
    if c2.button("➕ 添加", use_container_width=True):
        if not code:
            st.toast("请输入股票代码", icon="⚠️")
        else:
            try:
                watchlist_add(token, code)
                st.toast(f"已添加 {resolved}", icon="⭐")
                st.rerun()
            except ApiError as e:
                st.toast(f"添加失败: {e}", icon="❌")

    st.markdown("---")

    # ---- 列表(可移除) ----
    try:
        wl = watchlist_list(token) or {"items": []}
    except ApiError as e:
        st.warning(f"自选股加载失败: {e}")
        wl = {"items": []}
    rows = wl.get("items") or []

    if not rows:
        st.info("自选股为空,请在上方添加。")
        return

    # 信号:涨跌方向 + 简单技术信号
    for r in rows:
        code, name = r["stock_code"], r.get("stock_name") or lookup_name(r["stock_code"])
        price = r.get("price")
        pct = r.get("pct_change")
        if pct is None:
            sig, cls = "⚪ 中性", "tc-muted"
        elif pct >= 0:
            sig, cls = "🟢 偏多", "tc-up"
        else:
            sig, cls = "🔴 偏空", "tc-down"
        price_txt = f"{price:,.2f}" if price is not None else "—"
        pct_txt = f"{'+' if (pct or 0) >= 0 else ''}{pct:.2f}%" if pct is not None else "—"

        c1, c2, c3, c4, c5 = st.columns([1.2, 1.4, 1.2, 1.2, 0.8])
        c1.markdown(f"<b>{name}</b><br><span style='color:{pal['muted']};font-size:11px'>{code}</span>",
                    unsafe_allow_html=True)
        c2.markdown(price_txt)
        c3.markdown(f"<span class='{cls}'>{pct_txt}</span>", unsafe_allow_html=True)
        c4.markdown(f"<span style='font-size:13px'>{sig}</span>", unsafe_allow_html=True)
        if c5.button("🗑", key=f"del_{code}", use_container_width=True):
            try:
                watchlist_delete(token, code)
                st.toast(f"已移除 {name}", icon="🗑")
                st.rerun()
            except ApiError as e:
                st.toast(f"移除失败: {e}", icon="❌")
        st.markdown("---")

    st.caption("提示:在「深度分析」页设置好时间范围后,可对自选股逐只分析。")
