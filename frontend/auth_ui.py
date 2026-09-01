"""
登录 / 注册页面(v4.0 步骤2:「沉浸式双栏品牌展厅」)

布局: Left 60%(SVG 品牌轮播) + Right 40%(玻璃登录卡)
- 左侧: 4 张 AI 生成 SVG 概念图自动轮播(3D 翻转 + 进度点 + Slogan),st.components.html 承载
- 右侧: 毛玻璃登录卡(星空粒子背景 + 密码眼睛 + 流光按钮 + 管理员快捷登录)
- 注册页: 密码强度实时检测(弱/中/强)、用户名唯一性校验(提交时)
- 注册成功自动登录并跳转

对外接口: render_auth(pal) —— 未登录时在 app.py 调用,渲染整页后自行 st.stop()
"""
from __future__ import annotations

import random

import streamlit as st
import streamlit.components.v1 as components

from api_client import ApiError, login, register
from components.ui import login_carousel
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
    fg = pal["fg"]
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
    /* 右侧登录卡:玻璃态(毛玻璃 + 霓虹描边)。
       用 > 直取第二列的 vertical block,避免误匹配卡内嵌套列导致穿模 */
    [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(2) > [data-testid="stVerticalBlock"] {{
        background: rgba(15, 21, 34, .72);
        border: 1px solid rgba(79, 140, 255, .28);
        border-radius: 18px;
        padding: 26px 26px 20px;
        box-shadow: 0 24px 80px rgba(0,0,0,.55), 0 0 28px rgba(124,92,255,.16), inset 0 1px 0 rgba(255,255,255,.06);
        backdrop-filter: blur(14px); -webkit-backdrop-filter: blur(14px);
        position: relative; z-index: 2;
        align-self: stretch;
    }}
    .auth-logo {{ text-align: center; font-size: 34px;
        filter: drop-shadow(0 0 14px rgba(124,92,255,.6)); }}
    .auth-title {{ text-align: center; font-size: 22px; font-weight: 800; color: {fg}; margin: 2px 0 2px;
        background: linear-gradient(90deg, {pal['accent']}, {pal.get('purple', '#b45cff')});
        -webkit-background-clip: text; -webkit-text-fill-color: transparent; }}
    .auth-sub {{ text-align: center; font-size: 12px; color: {pal['muted']}; margin-bottom: 16px; }}
    .auth-strength {{ text-align: center; font-size: 12px; margin-top: 2px; }}
    .auth-foot {{ text-align: center; font-size: 12px; color: {pal['muted']}; margin-top: 14px; }}
    .auth-demo {{ text-align: center; font-size: 11px; color: {pal['muted']}; margin-top: 8px; }}
    /* 输入框聚焦流光下划线 */
    [data-testid="stTextInput"] {{ position: relative; }}
    [data-testid="stTextInput"]:focus-within::after {{
        content: ""; position: absolute; left: 0; right: 0; bottom: 2px; height: 2px;
        background: linear-gradient(90deg, transparent, {pal['accent']}, {pal.get('purple', '#b45cff')}, transparent);
        animation: auth-flow 1.6s linear infinite; border-radius: 2px;
    }}
    @keyframes auth-flow {{ 0% {{ background-position: -200% 0; }} 100% {{ background-position: 200% 0; }} }}
    [data-testid="stTextInput"]:focus-within::after {{ background-size: 200% 100%; }}
    /* 登录/注册按钮:流光 + 按压弹性 + 脉冲(streamlit 的 form_submit_button 渲染为此 testid) */
    [data-testid="stFormSubmitButton"] button {{
        position: relative; overflow: hidden;
        background: linear-gradient(120deg, {pal['accent']}, {pal.get('purple', '#b45cff')}) !important;
        border: none !important;
        transition: transform .25s cubic-bezier(0.34,1.56,0.64,1), box-shadow .25s !important;
    }}
    [data-testid="stFormSubmitButton"] button:hover {{ transform: translateY(-2px); box-shadow: 0 8px 24px rgba(124,92,255,.5) !important; }}
    [data-testid="stFormSubmitButton"] button:active {{ transform: scale(.95); }}
    @keyframes auth-pulse {{ 0%,100% {{ box-shadow: 0 0 0 0 rgba(124,92,255,.55); }} 70% {{ box-shadow: 0 0 0 10px rgba(124,92,255,0); }} }}
    [data-testid="stFormSubmitButton"] button {{ animation: auth-pulse 1.8s infinite; }}
    /* 显示密码 / 快捷登录等小按钮 */
    .stCheckbox label {{ color: {pal['muted']} !important; font-size: 12px !important; }}
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
    """渲染双栏登录/注册整页(调用方需随后 st.stop())"""
    st.markdown(f'<div class="auth-bg">{_starfield_html()}</div>{_auth_css(pal)}',
                unsafe_allow_html=True)

    left, right = st.columns([3, 2], gap="medium")
    with left:
        # 左 60%:品牌 SVG 轮播(iframe 承载,登录页 rerun 少,开销可接受)
        components.html(login_carousel.render_html(), height=530)
    with right:
        st.markdown(_logo_header(pal), unsafe_allow_html=True)
        mode = st.session_state.get("auth_mode", "login")
        if mode == "login":
            _render_login(pal)
        else:
            _render_register(pal)
        st.markdown('<div class="auth-foot">数据仅用于学习与技术演示 · 不构成投资建议</div>',
                    unsafe_allow_html=True)


def _render_login(pal: dict):
    show = st.checkbox("显示密码", key="auth_show_pw")
    pw_type = "" if show else "password"
    with st.form("login_form"):
        username = st.text_input("用户名", key="auth_username")
        password = st.text_input("密码", type=pw_type, key="auth_password")
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

    # 管理员快捷登录:一键填充 admin/admin123
    if st.button("👑 管理员快捷登录(演示)", use_container_width=True):
        st.session_state["auth_username"] = "admin"
        st.session_state["auth_password"] = "admin123"
        st.toast("已填充 admin/admin123,点击「登 录」即可", icon="✨")
        st.rerun()
    st.markdown('<div class="auth-demo">演示账号: admin / admin123</div>', unsafe_allow_html=True)


def _render_register(pal: dict):
    show = st.checkbox("显示密码", key="reg_show_pw")
    pw_type = "" if show else "password"
    with st.form("register_form"):
        username = st.text_input("用户名(3-20 位字母/数字/下划线)", key="reg_username")
        password = st.text_input("密码", type=pw_type, key="reg_password")
        confirm = st.text_input("确认密码", type=pw_type, key="reg_confirm")
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
