"""
个人中心页(v4.0 步骤3/7)

- 环形进度条(纯 SVG + CSS 充能动画):Token 累计消耗 / 分析次数 / 自选股数
- 用户信息卡(角色 / 邮箱 / 最近登录 / 后端状态)
- 资料编辑:修改邮箱 / 修改密码(调 PUT /user/profile)
- 赛博朋克模式开关也在本页(设置区)

数据来源全部为现有接口:user_history / watchlist_list / 会话内累计 Token。
"""
from __future__ import annotations

import math

import streamlit as st

from api_client import ApiError, update_profile, user_history, watchlist_list

_RING_R = 48
_RING_C = 2 * math.pi * _RING_R


def _ring_html(pal: dict, value: float, maxv: float, label: str, gid: int) -> str:
    """SVG 环形进度(充能动画:stroke-dashoffset 弹性过渡)"""
    pct = 0.0 if maxv <= 0 else max(0.0, min(1.0, value / maxv))
    offset = _RING_C * (1 - pct)
    return f"""
    <div class="tc-card tc-grad-border" style="text-align:center;padding:18px 10px;">
      <svg width="132" height="132" viewBox="0 0 132 132">
        <defs><linearGradient id="rg-{gid}" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stop-color="{pal['accent']}"/><stop offset="1" stop-color="{pal.get('purple', '#b45cff')}"/></linearGradient></defs>
        <circle cx="66" cy="66" r="{_RING_R}" fill="none" stroke="{pal['border']}" stroke-width="10"/>
        <circle cx="66" cy="66" r="{_RING_R}" fill="none" stroke="url(#rg-{gid})" stroke-width="10"
                stroke-linecap="round" stroke-dasharray="{_RING_C:.1f}" stroke-dashoffset="{offset:.1f}"
                transform="rotate(-90 66 66)"
                style="transition:stroke-dashoffset 1.1s cubic-bezier(.34,1.56,.64,1);"/>
        <text x="66" y="62" text-anchor="middle" fill="{pal['fg']}" font-size="24" font-weight="800">{value:,.0f}</text>
        <text x="66" y="84" text-anchor="middle" fill="{pal['muted']}" font-size="11">{label}</text>
      </svg>
      <div style="font-size:12px;color:{pal['muted']};margin-top:4px;">{pct * 100:.0f}%</div>
    </div>"""


def render(pal: dict):
    st.markdown(f'<div class="tc-enter" style="font-size:18px;font-weight:800;color:{pal["fg"]};">⚙️ 个人中心</div>',
                unsafe_allow_html=True)
    user = st.session_state.user or {}
    token = st.session_state.token

    # ---- 统计 ----
    try:
        hist = user_history(token) or {"items": []}
        hist_count = len(hist.get("items") or [])
    except ApiError:
        hist_count = 0
    try:
        wl = watchlist_list(token) or {"items": []}
        wl_count = len(wl.get("items") or [])
    except ApiError:
        wl_count = 0
    cum_tokens = st.session_state.get("cum_tokens", 0)

    # ---- 环形进度 ----
    c1, c2, c3 = st.columns(3)
    c1.markdown(_ring_html(pal, cum_tokens, 1_000_000, "Token 累计消耗", 1), unsafe_allow_html=True)
    c2.markdown(_ring_html(pal, hist_count, 50, "分析次数", 2), unsafe_allow_html=True)
    c3.markdown(_ring_html(pal, wl_count, 20, "自选股数", 3), unsafe_allow_html=True)
    st.caption("Token 累计 = 本次会话内各次分析任务消耗之和(任务完成后自动累加);分析次数上限与自选股上限为软指标。")

    st.markdown("---")

    # ---- 用户信息卡 ----
    role_badge = "👑 管理员" if user.get("role") == "admin" else "👤 普通用户"
    backend_txt = "🟢 已连接" if st.session_state.get("backend_ok") else "🔴 未连接"
    st.markdown(f"""
    <div class="tc-card">
      <div style="display:flex;align-items:center;gap:14px;">
        <div style="width:52px;height:52px;border-radius:50%;display:flex;align-items:center;justify-content:center;
                    font-size:24px;font-weight:800;color:#fff;background:linear-gradient(135deg,{pal['accent']},{pal.get('purple','#b45cff')});
                    box-shadow:0 0 16px {_rgba(pal['accent'], .5)};">{(user.get('username') or '?')[:1].upper()}</div>
        <div>
          <div style="font-size:18px;font-weight:800;color:{pal['fg']};">{user.get('username', '-')} {role_badge}</div>
          <div style="font-size:12px;color:{pal['muted']};">邮箱:{user.get('email') or '未设置'} ｜ 最近登录:{user.get('last_login') or '-'} ｜ 后端:{backend_txt}</div>
        </div>
      </div>
    </div>""", unsafe_allow_html=True)

    st.markdown("---")

    # ---- 资料编辑 ----
    st.markdown(f'<div style="font-size:15px;font-weight:700;color:{pal["fg"]};">✏️ 资料编辑</div>',
                unsafe_allow_html=True)
    with st.form("profile_form"):
        email = st.text_input("邮箱", value=user.get("email") or "", key="pf_email")
        old_pw = st.text_input("旧密码(改密码时填写)", type="password", key="pf_old")
        new_pw = st.text_input("新密码(留空表示不改)", type="password", key="pf_new")
        submitted = st.form_submit_button("保存修改", type="primary", use_container_width=True)
    if submitted:
        try:
            resp = update_profile(token, email=email or None,
                                  old_password=old_pw or None,
                                  new_password=new_pw or None)
            st.session_state.user = resp.get("user", user)
            st.toast("资料已更新 ✅", icon="✨")
            st.rerun()
        except ApiError as e:
            if e.status_code == 401:
                from auth_ui import logout
                logout()
                st.rerun()
            st.error(f"保存失败:{e.message}")

    st.markdown("---")
    # 设置区:赛博朋克模式
    cp = st.toggle("赛博朋克模式(霓虹/故障风)", value=bool(st.session_state.get("cyberpunk")),
                   key="pf_cyberpunk")
    if cp != bool(st.session_state.get("cyberpunk")):
        st.session_state["cyberpunk"] = cp
        st.rerun()
    st.caption("开启后全站叠加霓虹像素字 + 故障干扰线 + 点阵背景(纯视觉,不影响功能)。")


def _rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    return f"rgba({int(h[0:2], 16)},{int(h[2:4], 16)},{int(h[4:6], 16)},{alpha})"
