"""
多智能体股票投研终端(v4.0 UI 全面改造)

布局:
  顶部状态栏(时钟/数据源灯/搜索触发/头像下拉)  <- declare_component,可回传 open_search
  侧边栏  Logo / 后端状态 / 主题+赛博朋克 / 用户信息+退出 / 导航(驾驶舱|深度研究|股小智|星标自选|历史轨迹|个人中心)
          / 分析控制面板 / 数据源指示灯 / 键盘热力 / 免责声明
  主区    全局搜索面板(Ctrl+K) -> 按导航路由到各页面;任务运行中全局流水线进度

页面:
  驾驶舱  市场指数行情条(marquee) + 自选股 + 撒花彩蛋
  深度研究 行情概览(计速器) + 专业K线/MA滑块 + Agent 拓扑 + 5 Tab + 新闻
  股小智   RAG 问答(打字机/画中画进度卡)
  星标自选 增删自选股
  历史轨迹 按时间倒序 + 重新查看
  个人中心 环形进度 + 资料编辑
  管理后台 用户管理/监控/数据源(仅管理员)

启动: streamlit run frontend/app.py
"""
import os
import sys
import time
from datetime import date, timedelta

import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from api_client import ApiError, health, start_analysis, task_result, task_status
from components import agent_topology, pipeline
from components.ui import pip_card, topbar
from data_layer import clear_all_cached
from page_views import admin, dashboard, deep_analysis, history, profile, qa, watchlist
from stock_map import COMMON_STOCKS, lookup_name
from theme import apply_theme

st.set_page_config(page_title="多智能体股票投研终端", page_icon="📈", layout="wide")

# 导航菜单(v4.0 文案):显示文案 -> 页面 key(管理后台仅管理员可见)
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

if "code" not in st.session_state:
    st.session_state.code = "600519"
if "rng" not in st.session_state:
    st.session_state.rng = "3m"
if "start_str" not in st.session_state:
    st.session_state.start_str = ""
if "end_str" not in st.session_state:
    st.session_state.end_str = ""
if "mode_key" not in st.session_state:
    st.session_state.mode_key = "full"
if "page" not in st.session_state:
    st.session_state.page = "dashboard"
if "running_task" not in st.session_state:
    st.session_state.running_task = None
if "analysis_result" not in st.session_state:
    st.session_state.analysis_result = None
if "data_source" not in st.session_state:
    st.session_state.data_source = "no_data"
if "last_stages" not in st.session_state:
    st.session_state.last_stages = None
if "llm_stats" not in st.session_state:
    st.session_state.llm_stats = None
if "cum_tokens" not in st.session_state:
    st.session_state.cum_tokens = 0
if "search_open" not in st.session_state:
    st.session_state.search_open = False
if "key_heatmap" not in st.session_state:
    st.session_state.key_heatmap = None
if "token" not in st.session_state:
    st.session_state.token = None
if "user" not in st.session_state:
    st.session_state.user = None
if "backend_ok" not in st.session_state:
    try:
        health()
        st.session_state.backend_ok = True
    except ApiError:
        st.session_state.backend_ok = False

# ------------------------------------------------------------
# 认证门禁:未登录一律先登录/注册
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
# 顶部状态栏(declare_component,可回传 open_search)
# ------------------------------------------------------------
_bell = st.session_state.pop("_bell", False)
_tb_ev = topbar.render_topbar(pal, _username, _user.get("role", "user"),
                              st.session_state.data_source, bell_new=_bell)
if _tb_ev and _tb_ev != st.session_state.get("_tb_handled"):
    st.session_state["_tb_handled"] = _tb_ev
    if _tb_ev.get("action") == "open_search":
        st.session_state["search_open"] = True
        if _tb_ev.get("heatmap"):
            st.session_state["key_heatmap"] = _tb_ev["heatmap"]
        st.rerun()


def _render_search(pal):
    """全局搜索面板(Ctrl+K / 顶部🔍触发)"""
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
            try:
                resp = start_analysis(code, st.session_state.mode_key, token=st.session_state.token)
                st.session_state.running_task = resp["task_id"]
                st.session_state["page"] = "deep"
                st.session_state.analysis_result = None
                st.toast(f"已启动 {lookup_name(code)} 分析", icon="🚀")
                st.rerun()
            except ApiError as e:
                if e.status_code == 401:
                    from auth_ui import logout
                    logout()
                    st.rerun()
                st.toast(f"启动失败: {e}", icon="❌")

if st.session_state.get("search_open"):
    _render_search(pal)


# ------------------------------------------------------------
# 侧边栏:导航 + 用户 + 主题 + 分析控制面板
# ------------------------------------------------------------
with st.sidebar:
    st.markdown(f'<div style="font-size:18px;font-weight:800;color:{pal["fg"]};">📈 多智能体投研终端</div>',
                unsafe_allow_html=True)
    st.caption("LangGraph 多智能体 · RAG 财报知识库 · 三级数据降级")

    if st.session_state.backend_ok:
        st.success("后端已连接", icon="🟢")
    else:
        st.error("后端未连接:请先启动 uvicorn backend.main:app --port 8000", icon="🔴")

    # 主题 + 赛博朋克
    theme_choice = st.radio("主题", ["dark", "light"],
                            index=0 if st.session_state.theme == "dark" else 1,
                            horizontal=True, label_visibility="collapsed")
    if theme_choice != st.session_state.theme:
        st.session_state.theme = theme_choice
        st.rerun()
    cp = st.toggle("赛博朋克模式", value=bool(st.session_state.get("cyberpunk")), key="sb_cyberpunk")
    if cp != bool(st.session_state.get("cyberpunk")):
        st.session_state["cyberpunk"] = cp
        st.rerun()

    # 用户信息 + 退出登录
    _role_badge = "👑 管理员" if _user.get("role") == "admin" else "👤 普通用户"
    st.markdown(f"""
    <div class="tc-card" style="padding:10px 12px;">
      <div style="display:flex;align-items:center;gap:10px;">
        <div style="width:34px;height:34px;border-radius:50%;background:linear-gradient(135deg,{pal['accent']},{pal.get('purple','#b45cff')});color:#fff;
                    display:flex;align-items:center;justify-content:center;font-size:16px;">{_username[:1].upper() if _username else '?'}</div>
        <div>
          <div style="font-size:14px;font-weight:700;color:{pal['fg']};">{_username}</div>
          <div style="font-size:11px;color:{pal['muted']};">{_role_badge}</div>
        </div>
      </div>
    </div>""", unsafe_allow_html=True)
    if st.button("🚪 退出登录", use_container_width=True):
        from auth_ui import logout
        logout()
        st.rerun()

    st.markdown("---")
    st.markdown(f'<div style="font-size:12px;color:{pal["muted"]};">🧭 导航</div>', unsafe_allow_html=True)
    _menu = dict(NAV_MENU)
    if _user.get("role") != "admin":
        _menu.pop("⚙️ 管理后台", None)   # 非管理员不显示管理后台入口
    st.radio("导航", list(_menu.keys()), key="nav_radio")
    st.session_state.page = _menu.get(st.session_state.nav_radio, "dashboard")

    st.markdown("---")
    running = st.session_state.running_task is not None
    st.markdown(f'<div style="font-size:12px;color:{pal["muted"]};">🎛 分析控制面板</div>',
                unsafe_allow_html=True)

    # 常用标的快速选择(写入 text_input 的 key)
    preset_options = ["手动输入"] + [f"{c} · {n}" for c, n in COMMON_STOCKS]
    preset = st.selectbox("常用标的", preset_options, index=0, disabled=running)
    if preset != "手动输入" and st.session_state.get("_last_preset") != preset:
        st.session_state["code_input"] = preset.split(" · ")[0]
        st.session_state["_last_preset"] = preset

    code = st.text_input("股票代码", value="600519", key="code_input", disabled=running).strip()
    st.session_state.code = code or "600519"

    resolved = lookup_name(code)
    if resolved and resolved != code:
        st.caption(f"✓ 已识别:{resolved}")
    else:
        st.caption("未收录的代码,按代码显示名称")

    time_range = st.radio("时间范围",
                          ["近 1 月", "近 3 月", "近 6 月", "近 1 年", "自定义"],
                          index=1, disabled=running)
    _rng_map = {"近 1 月": "1m", "近 3 月": "3m", "近 6 月": "6m", "近 1 年": "1y", "自定义": "custom"}
    st.session_state.rng = _rng_map[time_range]
    start_str, end_str = "", ""
    if st.session_state.rng == "custom":
        c1, c2 = st.columns(2)
        start_d = c1.date_input("起始", value=date.today() - timedelta(days=90))
        end_d = c2.date_input("结束", value=date.today())
        if start_d > end_d:
            start_d, end_d = end_d, start_d
        start_str, end_str = start_d.strftime("%Y-%m-%d"), end_d.strftime("%Y-%m-%d")
    st.session_state.start_str, st.session_state.end_str = start_str, end_str

    mode = st.radio("分析模式", ["完整模式(全 Agent)", "快速模式(跳过情感)"], index=0, disabled=running)
    st.session_state.mode_key = "full" if mode.startswith("完整") else "quick"

    st.markdown("---")
    st.markdown("**数据源状态**")
    st.markdown(pipeline.data_source_light_html(st.session_state.data_source, pal),
                unsafe_allow_html=True)

    if st.button("🚀 重新分析", type="primary", use_container_width=True, disabled=running):
        try:
            resp = start_analysis(code or "600519", st.session_state.mode_key,
                                  token=st.session_state.token)
            st.session_state.running_task = resp["task_id"]
            _reset_analysis()
            clear_all_cached()
            st.rerun()
        except ApiError as e:
            if e.status_code == 401:  # token 过期 → 回登录页
                from auth_ui import logout
                logout()
                st.toast("登录已过期,请重新登录", icon="🔐")
                st.rerun()
            st.toast(f"启动分析失败: {e}", icon="❌")

    # 键盘热力图(趣味)
    km = st.session_state.get("key_heatmap")
    if km:
        top = sorted(km.items(), key=lambda kv: -kv[1])[:6]
        tiles = "".join(
            f'<span style="background:{pal["card2"]};border:1px solid {pal["border"]};'
            f'border-radius:6px;padding:2px 8px;margin:2px;font-size:11px;color:{pal["fg"]};">'
            f'{k if k.isalnum() else "⌨"}:{v}</span>' for k, v in top)
        st.markdown(f'<div style="font-size:12px;color:{pal["muted"]};margin-top:8px;">⌨ 键盘热力</div>{tiles}',
                    unsafe_allow_html=True)

    st.markdown("---")
    st.caption("数据仅用于学习与技术演示,不构成投资建议")


# ------------------------------------------------------------
# 全局:分析任务运行中 → 流水线进度(任意页面可见)
# ------------------------------------------------------------
if st.session_state.running_task:
    try:
        status = task_status(st.session_state.running_task)
    except ApiError as e:
        st.toast(f"查询任务失败: {e}", icon="❌")
        st.session_state.running_task = None
        status = None

    if status:
        pipeline.render_pipeline(status.get("stages") or [], status.get("status"), pal)

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
            # 进行中:Agent 拓扑图(live 抗重挂载)+ 画中画进度卡 + 骨架屏,轮询等待
            pc1, pc2 = st.columns([3, 1])
            with pc1:
                if status.get("stages"):
                    agent_topology.render_topology(status["stages"], live=True, height=300)
            with pc2:
                pip_card.render(status.get("stages") or [], status["status"], pal)
            if st.session_state.get("fish_tank_open"):
                from components.ui import fish_tank
                fish_tank.render(status.get("stages") or [], height=230)
            st.markdown('<div class="tc-skeleton"></div>', unsafe_allow_html=True)
            st.markdown('<div class="tc-skeleton line" style="width:60%"></div>', unsafe_allow_html=True)
            time.sleep(1.5)
            st.rerun()
    st.stop()

# ------------------------------------------------------------
# 页面路由
# ------------------------------------------------------------
_page = st.session_state.get("page", "dashboard")
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
