"""
登录 / 注册页面(用户体系第一批)

设计:专业金融终端暗色风格
- 暗色渐变背景 + CSS 星空粒子动画(纯 CSS,零 JS,兼容性好)
- 居中登录卡片:Logo / 系统名称 / 输入框 / 登录按钮
- 登录失败 Toast 通知;加载中按钮脉冲
- 注册页:密码强度实时检测(弱/中/强)、用户名唯一性校验(提交时)
- 注册成功自动登录并跳转

对外接口:render_auth(pal) —— 未登录时在 app.py 调用,渲染整页后自行 st.stop()
"""
from __future__ import annotations

import random

import streamlit as st

from api_client import ApiError, login, register
from theme import STATUS_COLORS


def _starfield_html(n: int = 46) -> str:
    """生成固定种子星空粒子(同一会话内位置稳定,不闪烁)"""
    rng = random.Random(42)
    parts = []
    for _ in range(n):
        x, y = rng.uniform(0, 100), rng.uniform(0, 100)
        size = rng.choice([1, 1, 1, 2, 2, 3])
        delay = round(rng.uniform(0, 4), 2)
        dur = round(rng.uniform(2, 5), 2)
        parts.append(
            f'<i style="left:{x:.1f}%;top:{y:.1f}%;width:{size}px;height:{size}px;'
            f'animation-delay:{delay}s;animation-duration:{dur}s;"></i>')
    return "".join(parts)


def _auth_css(pal: dict) -> str:
    return f"""
    <style>
    .auth-bg {{
        position: fixed; inset: 0; z-index: 0; overflow: hidden;
        background: radial-gradient(1000px 520px at 15% 0%, #1a2b47 0%, #0b0e14 55%, #06090f 100%);
    }}
    .auth-bg i {{
        position: absolute; border-radius: 50%; background: #dfe9ff;
        animation: auth-twinkle 3s ease-in-out infinite;
    }}
    @keyframes auth-twinkle {{ 0%,100% {{ opacity: .12 }} 50% {{ opacity: .9 }} }}
    /* 卡片:中间列容器 */
    [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(2) [data-testid="stVerticalBlock"] {{
        background: rgba(17, 23, 36, .86); border: 1px solid #2c3a52; border-radius: 18px;
        padding: 30px 30px 26px; margin-top: 8vh;
        box-shadow: 0 24px 80px rgba(0,0,0,.55), inset 0 1px 0 rgba(255,255,255,.06);
        backdrop-filter: blur(8px); position: relative; z-index: 2;
    }}
    .auth-logo {{ text-align: center; font-size: 34px; }}
    .auth-title {{ text-align: center; font-size: 22px; font-weight: 800; color: {pal['fg']}; margin: 2px 0 2px; }}
    .auth-sub {{ text-align: center; font-size: 12px; color: {pal['muted']}; margin-bottom: 18px; }}
    .auth-strength {{ text-align: center; font-size: 12px; margin-top: 2px; }}
    .auth-foot {{ text-align: center; font-size: 12px; color: {pal['muted']}; margin-top: 14px; }}
    /* 登录/注册按钮脉冲 */
    @keyframes auth-pulse {{ 0%,100% {{ box-shadow: 0 0 0 0 rgba(79,140,255,.5); }} 70% {{ box-shadow: 0 0 0 10px rgba(79,140,255,0); }} }}
    .auth-btn button {{ animation: auth-pulse 1.6s infinite; }}
    </style>
    """


def _strength_html(password: str) -> str:
    s = _strength(password)
    color = {"弱": STATUS_COLORS["failed"], "中": STATUS_COLORS["skipped"],
             "强": STATUS_COLORS["completed"]}.get(s["label"], STATUS_COLORS["waiting"])
    bar = (f'<span style="color:{color};">●</span>' * s["score"] +
           f'<span style="color:#3a4658;">●</span>' * (4 - s["score"]))
    return f'<div class="auth-strength">密码强度:{bar} <span style="color:{color};">{s["label"]}</span></div>'


def _strength(password: str) -> dict:
    """密码强度(与后端 auth.password_strength 一致的评分逻辑)"""
    if not password:
        return {"score": 0, "label": "未输入", "ok": False}
    score = 0
    if len(password) >= 8:
        score += 1
    if any(c.isupper() for c in password) and any(c.islower() for c in password):
        score += 1
    if any(c.isdigit() for c in password):
        score += 1
    if any(c in "!@#$%^&*()-_=+[]{};:,.?/" for c in password):
        score += 1
    return {"score": score, "label": "弱" if score <= 1 else ("中" if score == 2 else "强"),
            "ok": score >= 2}


def _logo_header(pal: dict) -> str:
    return f"""
    <div class="auth-logo">📈</div>
    <div class="auth-title">多智能体股票投研终端</div>
    <div class="auth-sub">LangGraph 多智能体 · RAG 财报知识库 · 专业级可视化</div>
    """


def render_auth(pal: dict):
    """渲染登录/注册整页(调用方需随后 st.stop())"""
    st.markdown(f'<div class="auth-bg">{_starfield_html()}</div>{_auth_css(pal)}',
                unsafe_allow_html=True)

    _, mid, _ = st.columns([1, 2.4, 1])
    with mid:
        st.markdown(_logo_header(pal), unsafe_allow_html=True)
        mode = st.session_state.get("auth_mode", "login")
        if mode == "login":
            _render_login(pal)
        else:
            _render_register(pal)
        st.markdown('<div class="auth-foot">数据仅用于学习与技术演示 · 不构成投资建议</div>',
                    unsafe_allow_html=True)


def _render_login(pal: dict):
    with st.form("login_form"):
        username = st.text_input("用户名", key="auth_username")
        password = st.text_input("密码", type="password", key="auth_password")
        submitted = st.form_submit_button("登 录", type="primary", use_container_width=True)

    if submitted:
        if not username or not password:
            st.toast("请输入用户名和密码", icon="⚠️")
        else:
            try:
                resp = login(username, password)
                _set_session(resp)
                st.toast(f"欢迎回来,{resp['user']['username']} 🎉", icon="✅")
                st.rerun()
            except ApiError as e:
                st.error(f"登录失败:{e.message}")

    c1, c2 = st.columns(2)
    if c1.button("注册新账号", use_container_width=True):
        st.session_state["auth_mode"] = "register"
        st.rerun()
    if c2.button("忘记密码", use_container_width=True):
        st.toast("请联系管理员重置密码(演示占位)", icon="🔒")


def _render_register(pal: dict):
    with st.form("register_form"):
        username = st.text_input("用户名(3-20 位字母/数字/下划线)", key="reg_username")
        password = st.text_input("密码", type="password", key="reg_password")
        confirm = st.text_input("确认密码", type="password", key="reg_confirm")
        email = st.text_input("邮箱(可选)", key="reg_email")
        submitted = st.form_submit_button("注 册", type="primary", use_container_width=True)

    # 密码强度实时提示(每次 rerun 随输入更新)
    st.markdown(_strength_html(st.session_state.get("reg_password", "")), unsafe_allow_html=True)

    if submitted:
        if len(username.strip()) < 3:
            st.toast("用户名至少 3 个字符", icon="⚠️")
        elif password != confirm:
            st.toast("两次输入的密码不一致", icon="⚠️")
        elif not _strength(password)["ok"]:
            st.toast("密码强度不足:建议至少 8 位且含大小写字母/数字", icon="⚠️")
        else:
            try:
                resp = register(username.strip(), password, st.session_state.get("reg_email", ""))
                _set_session(resp)
                st.toast("注册成功,已自动登录 🎉", icon="✅")
                st.rerun()
            except ApiError as e:
                st.error(f"注册失败:{e.message}")

    if st.button("已有账号,去登录", use_container_width=True):
        st.session_state["auth_mode"] = "login"
        st.rerun()


def _set_session(resp: dict):
    """登录/注册成功后写入会话状态"""
    st.session_state["token"] = resp["token"]
    st.session_state["user"] = resp["user"]
    st.session_state["auth_mode"] = "login"
    st.session_state["backend_ok"] = True


def logout():
    """退出登录:清空会话并跳回登录页"""
    st.session_state["token"] = None
    st.session_state["user"] = None
    st.session_state["analysis_result"] = None
    st.session_state["running_task"] = None
