"""
管理后台页(第六批,仅管理员可见)

- 用户管理:列表 + 禁用/启用 + 删除
- 系统监控:用户数/分析任务/API调用/LLM token
- 数据源管理:手动触发采集 + 调度状态
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from api_client import ApiError, admin_data_refresh, admin_delete_user, admin_stats, admin_update_user, admin_users


def render(pal: dict):
    user = st.session_state.user or {}
    if user.get("role") != "admin":
        st.warning("需要管理员权限才能访问此页面。")
        return

    st.markdown(f'<div style="font-size:18px;font-weight:800;color:{pal["fg"]};">⚙️ 管理后台</div>',
                unsafe_allow_html=True)
    token = st.session_state.token

    # ---- 系统监控 ----
    try:
        stats = admin_stats(token)
    except ApiError as e:
        st.error(f"监控数据加载失败: {e}")
        stats = {}
    st.markdown("#### 📊 系统监控")
    if stats:
        c = st.columns(5)
        c[0].metric("用户数", stats.get("users", "-"))
        c[1].metric("分析任务", stats.get("analysis_tasks", "-"))
        c[2].metric("API 调用", stats.get("api_calls", "-"))
        llm = stats.get("llm_stats") or {}
        c[3].metric("LLM 调用", llm.get("calls", 0))
        c[4].metric("Token 消耗", llm.get("total_tokens", 0))
        top = stats.get("api_by_path") or {}
        if top:
            st.caption("TOP API 路径:" + " ｜ ".join(f"{k}×{v}" for k, v in top.items()))

    st.markdown("---")

    # ---- 数据源管理 ----
    st.markdown("#### 🛠 数据源管理")
    c1, c2 = st.columns([2, 1])
    c1.markdown(f"调度器状态:`{stats.get('scheduler', '-')}` (每日 08:30 + 每 6 小时自动采集自选股行情/新闻)")
    if c2.button("🔄 立即采集数据", use_container_width=True):
        try:
            resp = admin_data_refresh(token)
            st.toast(f"采集完成,刷新 {resp.get('stocks_refreshed', 0)} 只股票", icon="✅")
            st.rerun()
        except ApiError as e:
            st.error(f"采集失败: {e}")

    st.markdown("---")

    # ---- 用户管理 ----
    st.markdown("#### 👥 用户管理")
    try:
        data = admin_users(token)
    except ApiError as e:
        st.error(f"用户列表加载失败: {e}")
        data = {"items": []}
    rows = data.get("items") or []
    if rows:
        st.caption(f"共 {len(rows)} 个用户")
        for u in rows:
            role_badge = "👑" if u["role"] == "admin" else "👤"
            status = "🟢 正常" if u.get("is_active", True) else "🔴 已禁用"
            c1, c2, c3, c4, c5 = st.columns([2.2, 1.2, 1.4, 0.9, 0.9])
            c1.markdown(f"**{u['username']}** {role_badge} <span style='color:{pal['muted']};font-size:11px'>(id:{u['id']})</span>",
                        unsafe_allow_html=True)
            c2.markdown(f"<span style='font-size:12px;color:{pal['muted']}'>{u.get('email') or '无邮箱'}</span>",
                        unsafe_allow_html=True)
            c3.markdown(status + f" <span style='font-size:11px;color:{pal['muted']}'>{u.get('created_at','')[:10]}</span>",
                        unsafe_allow_html=True)
            if u["username"] == st.session_state.user.get("username"):
                c4.markdown("—")
                c5.markdown("—")
                continue
            if c4.button("⛔ 禁用" if u.get("is_active", True) else "✅ 启用", key=f"tog_{u['id']}"):
                try:
                    admin_update_user(token, u["id"], is_active=not u.get("is_active", True))
                    st.rerun()
                except ApiError as e:
                    st.error(f"操作失败: {e}")
            if c5.button("🗑 删除", key=f"del_{u['id']}"):
                try:
                    admin_delete_user(token, u["id"])
                    st.toast(f"已删除用户 {u['username']}", icon="🗑")
                    st.rerun()
                except ApiError as e:
                    st.error(f"删除失败: {e}")
            st.markdown("---")
    else:
        st.info("暂无用户。")
