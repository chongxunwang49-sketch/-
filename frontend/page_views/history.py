"""
历史记录页(第三批)

按时间倒序展示当前用户的所有分析任务:代码/时间/模式/综合评分,点击可跳转重新查看。
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from api_client import ApiError, user_history


def render(pal: dict):
    st.markdown(f'<div style="font-size:18px;font-weight:800;color:{pal["fg"]};">📋 历史分析记录</div>',
                unsafe_allow_html=True)
    token = st.session_state.token

    try:
        data = user_history(token) or {"items": []}
    except ApiError as e:
        st.warning(f"历史记录加载失败: {e}")
        data = {"items": []}
    items = data.get("items") or []

    if not items:
        st.info("还没有分析记录。前往「📈 深度分析」输入股票代码并点击「重新分析」。")
        return

    st.caption(f"共 {len(items)} 条记录(按时间倒序)")
    for h in items:
        score = h.get("score")
        score_txt = f"{score:.2f}" if score is not None else "—"
        name = h.get("company_name") or h.get("stock_code")
        mode_txt = "完整" if h.get("mode") == "full" else "快速"

        with st.container(border=True):
            c1, c2, c3, c4 = st.columns([2.2, 1.2, 1.4, 1.0])
            c1.markdown(f"**{name}** <span style='color:{pal['muted']};font-size:11px'>({h.get('stock_code')})</span>",
                        unsafe_allow_html=True)
            c2.markdown(f"<span style='font-size:12px;color:{pal['muted']}'>⏰ {h.get('created_at','')}</span>",
                        unsafe_allow_html=True)
            c3.markdown(f"综合评分 <b style='color:{pal['accent']}'>{score_txt}</b>  ·  {mode_txt}模式",
                        unsafe_allow_html=True)
            if c4.button("🔍 重新查看", key=f"re_{h['id']}", use_container_width=True):
                st.session_state.code = h.get("stock_code", "600519")
                st.session_state["page"] = "深度分析"
                st.session_state.analysis_result = None
                st.rerun()

    st.caption("「重新查看」会切换到深度分析页并填入该股票代码,点「重新分析」即可生成新报告。")
