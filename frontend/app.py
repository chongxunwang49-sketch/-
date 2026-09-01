"""
多智能体股票投研终端(v4.1 主框架重构 —— 「太空舱 HUD」)

不再"左参数/右界面"的死板布局,改为游戏化太空舱:
- 顶部状态栏 HUD(declare_component): 时钟/搜索(Ctrl+K)/后端灯/数据源雷达/
    主题切换/赛博朋克开关/铃铛/头像下拉(退出)
- 主区顶部: 分析控制台(可折叠玻璃面板,全站可见,所见即所得)
- 侧边栏: 紧凑游戏 dock —— 仅 Logo + 导航图块
- 主区: 搜索面板 → 轮询进度(拓扑+画中画) → 页面内容 → 页脚

页面: 驾驶舱 / 深度研究 / 股小智 / 星标自选 / 历史轨迹 / 个人中心 / 管理后台
"""
import os
import sys
import time
from datetime import date, timedelta

import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from api_client import ApiError, health, start_analysis, task_result, task_status
from components import agent_topology, pipeline
from components.ui import topbar
from data_layer import clear_all_cached
from page_views import admin, dashboard, deep_analysis, history, profile, qa, watchlist
from stock_map import COMMON_STOCKS, lookup_name
from theme import apply_theme


def _rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    return f"rgba({int(h[0:2], 16)},{int(h[2:4], 16)},{int(h[4:6], 16)},{alpha})"


st.set_page_config(page_title="多智能体股票投研终端", page_icon="📈", layout="wide")

NAV_MENU = {
    "📊 驾驶舱": "dashboard",
    "📈 深度研究": "deep",
    "🤖 股小智": "qa",
    "⭐ 星标自选": "watchlist",
    "🗂 历史轨迹": "history",
    "⚙️ 个人中心": "profile",
    "⚙️ 管理后台": "admin",
}

# ------------------------------------------------------------
# 主题与会话状态
# ------------------------------------------------------------
if "theme" not in st.session_state:
    st.session_state.theme = "dark"
if "cyberpunk" not in st.session_state:
    st.session_state.cyberpunk = False
pal = apply_theme(st.session_state.theme)

for _k, _v in {
    "code": "600519", "rng": "3m", "start_str": "", "end_str": "",
    "mode_key": "full", "page": "dashboard",
    "running_task": None, "analysis_result": None, "data_source": "no_data",
    "last_stages": None, "llm_stats": None, "cum_tokens": 0,
    "search_open": False, "key_heatmap": None,
    "token": None, "user": None, "backend_ok": None,
}.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

if st.session_state.backend_ok is None:
    try:
        health()
        st.session_state.backend_ok = True
    except ApiError:
        st.session_state.backend_ok = False

# ------------------------------------------------------------
# 认证门禁
# ------------------------------------------------------------
if not st.session_state.token:
    from auth_ui import render_auth
    render_auth(pal)
    st.stop()

_user = st.session_state.user or {}
_username = _user.get("username", "")


def _reset_analysis():
    st.session_state.analysis_result = None
    st.session_state.last_stages = None
    st.session_state.llm_stats = None


# ------------------------------------------------------------
# 顶部状态栏 HUD(declare_component,双向事件)
# ------------------------------------------------------------
_bell = st.session_state.pop("_bell", False)
_tb_ev = topbar.render_topbar(pal, _username, _user.get("role", "user"),
                              st.session_state.data_source,
                              backend_ok=bool(st.session_state.backend_ok),
                              theme=st.session_state.theme,
                              cyberpunk=bool(st.session_state.get("cyberpunk")),
                              bell_new=_bell)
if _tb_ev and _tb_ev != st.session_state.get("_tb_handled"):
    st.session_state["_tb_handled"] = _tb_ev
    _a = _tb_ev.get("action")
    if _a == "open_search":
        st.session_state["search_open"] = True
        if _tb_ev.get("heatmap"):
            st.session_state["key_heatmap"] = _tb_ev["heatmap"]
        st.rerun()
    elif _a == "toggle_theme":
        st.session_state["theme"] = "light" if st.session_state.theme == "dark" else "dark"
        st.rerun()
    elif _a == "toggle_cyberpunk":
        st.session_state["cyberpunk"] = not st.session_state.get("cyberpunk", False)
        st.rerun()
    elif _a == "logout":
        from auth_ui import logout
        logout()
        st.rerun()


# ------------------------------------------------------------
# 主区顶部:分析控制台(玻璃面板,全站可见,所见即所得)
# ------------------------------------------------------------
def _render_console(pal):
    running = st.session_state.running_task is not None
    # 默认折叠:切换板块时不残留"驾驶舱 UI",需要时再展开(v4.2)
    with st.expander("⚡ 分析控制台 · 输入代码快速发起 9-Agent 分析", expanded=False):
        c1, c2, c3, c4 = st.columns([1.35, 1.35, 1.35, 1], gap="medium")

        with c1:
            st.markdown(f'<div class="tc-label">🎯 常用标的</div>', unsafe_allow_html=True)
            preset_options = ["手动输入"] + [f"{c} · {n}" for c, n in COMMON_STOCKS]
            preset = st.selectbox("常用标的", preset_options, index=0, disabled=running, label_visibility="collapsed")
            if preset != "手动输入" and st.session_state.get("_last_preset") != preset:
                st.session_state["code_input"] = preset.split(" · ")[0]
                st.session_state["_last_preset"] = preset
            code = st.text_input("股票代码", value="600519", key="code_input",
                                 disabled=running, placeholder="如 600519").strip()
            st.session_state.code = code or "600519"
            resolved = lookup_name(code or "600519")
            if resolved and resolved != (code or "600519"):
                st.caption(f"✓ {resolved}")

        with c2:
            st.markdown(f'<div class="tc-label">🕐 时间范围</div>', unsafe_allow_html=True)
            time_range = st.radio("时间范围",
                                  ["近 1 月", "近 3 月", "近 6 月", "近 1 年", "自定义"],
                                  index=1, disabled=running, label_visibility="collapsed")
            _rng_map = {"近 1 月": "1m", "近 3 月": "3m", "近 6 月": "6m", "近 1 年": "1y", "自定义": "custom"}
            st.session_state.rng = _rng_map[time_range]
            start_str, end_str = "", ""
            if st.session_state.rng == "custom":
                d1, d2 = st.columns(2)
                sd = d1.date_input("起始", value=date.today() - timedelta(days=90))
                ed = d2.date_input("结束", value=date.today())
                if sd > ed:
                    sd, ed = ed, sd
                start_str, end_str = sd.strftime("%Y-%m-%d"), ed.strftime("%Y-%m-%d")
            st.session_state.start_str, st.session_state.end_str = start_str, end_str

        with c3:
            st.markdown(f'<div class="tc-label">🧠 分析模式</div>', unsafe_allow_html=True)
            mode = st.radio("分析模式", ["完整模式(全 Agent)", "快速模式(跳过情感)"],
                            index=0, disabled=running, label_visibility="collapsed")
            st.session_state.mode_key = "full" if mode.startswith("完整") else "quick"

        with c4:
            st.markdown(f'<div class="tc-label">📡 数据源</div>', unsafe_allow_html=True)
            st.markdown(pipeline.data_source_light_html(st.session_state.data_source, pal),
                        unsafe_allow_html=True)
            if st.button("🚀 重新分析", type="primary", use_container_width=True, disabled=running):
                _start(code or "600519")

    # 键盘热力图(趣味,随控制台显示)
    km = st.session_state.get("key_heatmap")
    if km:
        top = sorted(km.items(), key=lambda kv: -kv[1])[:6]
        tiles = "".join(
            f'<span style="background:{pal["card2"]};border:1px solid {pal["border"]};'
            f'border-radius:6px;padding:2px 8px;margin:2px;font-size:11px;color:{pal["fg"]};">'
            f'{k if k.isalnum() else "⌨"}:{v}</span>' for k, v in top)
        st.markdown(f'<div style="font-size:12px;color:{pal["muted"]};">⌨ 键盘热力</div>{tiles}',
                    unsafe_allow_html=True)


def _start(code: str):
    try:
        resp = start_analysis(code, st.session_state.mode_key, token=st.session_state.token)
        st.session_state.running_task = resp["task_id"]
        st.session_state.code = code
        _reset_analysis()
        clear_all_cached()
        st.rerun()
    except ApiError as e:
        if e.status_code == 401:
            from auth_ui import logout
            logout()
            st.toast("登录已过期,请重新登录", icon="🔐")
            st.rerun()
        st.toast(f"启动分析失败: {e}", icon="❌")


def _render_search(pal):
    st.markdown(f'<div class="tc-card tc-glow">🔍 <b>全局搜索</b> <span style="color:{pal["muted"]}">(Ctrl+K)</span></div>',
                unsafe_allow_html=True)
    options = ["手动输入"] + [f"{c} · {n}" for c, n in COMMON_STOCKS]
    pick = st.selectbox("选择标的", options, key="gs_pick")
    code = pick.split(" · ")[0] if pick != "手动输入" else st.text_input("股票代码", key="gs_code").strip()
    c1, c2 = st.columns(2)
    if c1.button("📈 前往深度研究", use_container_width=True):
        if code:
            st.session_state.code = code
            st.session_state["page"] = "deep"
            st.session_state["search_open"] = False
            st.rerun()
    if c2.button("🚀 直接启动分析", use_container_width=True):
        if code:
            st.session_state.code = code
            st.session_state["search_open"] = False
            _start(code)


_render_console(pal)

if st.session_state.get("search_open"):
    _render_search(pal)


# ------------------------------------------------------------
# 侧边栏:紧凑游戏 dock(仅 Logo + 导航图块)
# ------------------------------------------------------------
with st.sidebar:
    st.markdown(f"""
    <div style="text-align:center;margin:6px 0 2px;">
      <div class="tc-breath-title" style="font-size:20px;font-weight:900;letter-spacing:1px;
           background:linear-gradient(90deg,{pal['accent']},{pal.get('purple', '#b45cff')});
           -webkit-background-clip:text;-webkit-text-fill-color:transparent;">📈 多智能体投研终端</div>
      <div class="tc-glitch" style="font-size:11px;color:{pal['muted']};margin-top:5px;letter-spacing:.5px;
           background:{pal['card2']};border:1px solid {_rgba(pal.get('purple', '#b45cff'), .4)};border-radius:20px;
           display:inline-block;padding:3px 12px;">LangGraph 9-Agent · RAG 财报 · 三级降级</div>
    </div>""", unsafe_allow_html=True)
    st.markdown("---")
    _menu = dict(NAV_MENU)
    if _user.get("role") != "admin":
        _menu.pop("⚙️ 管理后台", None)
    st.markdown(f'<div style="font-size:12px;color:{pal["muted"]};">🧭 导航</div>', unsafe_allow_html=True)
    st.radio("导航", list(_menu.keys()), key="nav_radio")
    st.session_state.page = _menu.get(st.session_state.nav_radio, "dashboard")
    st.markdown("---")
    st.caption("设置与分析控制台已移至主页面 · 顶部状态栏可切换主题/赛博朋克 · Ctrl+K 全局搜索")


# ------------------------------------------------------------
# 页面渲染(含太空舱转场:切换板块时旧窗口飞出 + 光束粒子)
# ------------------------------------------------------------
def _render_page(pal):
    _page = st.session_state.get("page", "dashboard")
    # 板块切换光束(仅在板块变化时注入一次)
    if st.session_state.get("_last_page") != _page:
        st.session_state["_last_page"] = _page
        st.markdown('<div class="page-beam"></div>', unsafe_allow_html=True)
    if _page == "deep":
        deep_analysis.render(pal)
    elif _page == "qa":
        qa.render(pal)
    elif _page == "watchlist":
        watchlist.render(pal)
    elif _page == "history":
        history.render(pal)
    elif _page == "profile":
        profile.render(pal)
    elif _page == "admin":
        admin.render(pal)
    else:
        dashboard.render(pal)


def _compact_progress(status: dict, pal) -> None:
    """轮询期间紧凑进度条(v4.2:不阻塞导航,随时可切板块)"""
    stages = status.get("stages") or []
    total = max(1, len(stages))
    done = sum(1 for s in stages if s.get("status") in ("completed", "skipped", "failed"))
    current = next((s for s in stages if s.get("status") == "running"), None)
    pct = int(done / total * 100)
    stage_txt = f"⏳ {current.get('label', '')}" if current else "⏳ 调度中…"
    st.markdown(f'''
    <div class="prog-wrap tc-card tc-glow" style="padding:10px 16px;">
      <div class="prog-head"><span>🛸 深度分析进行中 · {stage_txt}</span><b style="color:{pal['accent']};">{pct}%</b></div>
      <div class="prog-bar"><div class="prog-fill" style="width:{pct}%"></div></div>
    </div>''', unsafe_allow_html=True)
    # 深度研究页展示 Agent 拓扑(其余板块只显示进度条,保持轻量)
    if st.session_state.get("page") == "deep" and stages:
        agent_topology.render_topology(stages, live=True, height=240)


# ------------------------------------------------------------
# 全局:分析任务运行中 → 紧凑进度 + 仍可切换板块
# ------------------------------------------------------------
if st.session_state.running_task:
    try:
        status = task_status(st.session_state.running_task)
    except ApiError as e:
        st.toast(f"查询任务失败: {e}", icon="❌")
        st.session_state.running_task = None
        status = None

    if status:
        if status["status"] == "completed":
            try:
                res = task_result(st.session_state.running_task)
                result = res.get("result") or {}
                st.session_state.analysis_result = result
                st.session_state.data_source = result.get("data_source", "real")
                st.session_state.last_stages = status.get("stages")
                st.session_state.llm_stats = result.get("llm_stats")
                _tok = (result.get("llm_stats") or {}).get("total_tokens") or 0
                st.session_state.cum_tokens = st.session_state.get("cum_tokens", 0) + _tok
                st.session_state["_bell"] = True
                st.toast("✅ 分析完成", icon="🎉")
            except ApiError as e:
                st.toast(f"获取结果失败: {e}", icon="❌")
            st.session_state.running_task = None
            clear_all_cached()
            st.rerun()
        elif status["status"] == "failed":
            st.error(f"分析失败: {status.get('error')}")
            st.session_state.running_task = None
            st.rerun()
        else:
            # 进行中:紧凑进度 + 渲染当前页面(允许切换板块) + 继续轮询
            _compact_progress(status, pal)
            _render_page(pal)
            if st.session_state.get("fish_tank_open"):
                from components.ui import fish_tank
                fish_tank.render(status.get("stages") or [], height=230)
            time.sleep(1.2)
            st.rerun()
    else:
        _render_page(pal)
else:
    _render_page(pal)

st.markdown("---")
st.caption("数据仅用于学习与技术演示,不构成投资建议 · 多智能体投研终端 v4.2")
