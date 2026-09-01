"""
专业级股票投研终端(第三批:导航壳 + 多页面)

布局:
  侧边栏  Logo / 后端状态 / 主题切换 / 用户信息+退出 / 导航菜单(行情看板|深度分析|自选股|历史记录)
          / 分析控制面板(代码/时间范围/模式/数据源指示灯/重新分析)
  主区    按导航路由到各页面;分析任务运行中全局显示流水线进度(任意页面可见)

页面:
  行情看板  市场指数行情条 + 自选股列表 + 热点占位
  深度分析  行情概览卡 + 专业K线/指标卡片 + 5 Tab + 个股新闻
  自选股    增删自选股
  历史记录  按时间倒序 + 点击重新查看

启动: streamlit run frontend/app.py
"""
import os
import sys
import time
from datetime import date, timedelta

import streamlit as st

# 保证本目录可被 import(直接 streamlit run 时 sys.path 已含本目录,再加一层保险)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from api_client import ApiError, health, start_analysis, task_result, task_status
from components import pipeline
from data_layer import clear_all_cached
from page_views import dashboard, deep_analysis, history, watchlist
from stock_map import COMMON_STOCKS, lookup_name
from theme import apply_theme

st.set_page_config(page_title="多智能体股票投研终端", page_icon="📈", layout="wide")

# 导航菜单: 显示文案 -> 页面 key
NAV_MENU = {
    "📊 行情看板": "dashboard",
    "📈 深度分析": "deep",
    "⭐ 自选股": "watchlist",
    "📋 历史记录": "history",
}

# ------------------------------------------------------------
# 主题与会话状态
# ------------------------------------------------------------
if "theme" not in st.session_state:
    st.session_state.theme = "dark"
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


def _reset_analysis():
    st.session_state.analysis_result = None
    st.session_state.last_stages = None
    st.session_state.llm_stats = None


# ------------------------------------------------------------
# 侧边栏:导航 + 用户 + 分析控制面板
# ------------------------------------------------------------
with st.sidebar:
    st.markdown(f'<div style="font-size:18px;font-weight:800;color:{pal["fg"]};">📈 多智能体投研终端</div>',
                unsafe_allow_html=True)
    st.caption("LangGraph 多智能体 · RAG 财报知识库 · 三级数据降级")

    if st.session_state.backend_ok:
        st.success("后端已连接", icon="🟢")
    else:
        st.error("后端未连接:请先启动 uvicorn backend.main:app --port 8000", icon="🔴")

    # 主题切换
    theme_choice = st.radio("主题", ["dark", "light"],
                            index=0 if st.session_state.theme == "dark" else 1,
                            horizontal=True, label_visibility="collapsed")
    if theme_choice != st.session_state.theme:
        st.session_state.theme = theme_choice
        st.rerun()

    # 用户信息 + 退出登录
    _user = st.session_state.user or {}
    _role_badge = "👑 管理员" if _user.get("role") == "admin" else "👤 普通用户"
    st.markdown(f"""
    <div class="tc-card" style="padding:10px 12px;">
      <div style="display:flex;align-items:center;gap:10px;">
        <div style="width:34px;height:34px;border-radius:50%;background:{pal['accent']};color:#fff;
                    display:flex;align-items:center;justify-content:center;font-size:16px;">👤</div>
        <div>
          <div style="font-size:14px;font-weight:700;color:{pal['fg']};">{_user.get('username', '-')}</div>
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
    st.radio("导航", list(NAV_MENU.keys()), key="nav_radio")
    st.session_state.page = NAV_MENU.get(st.session_state.nav_radio, "dashboard")

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
            # 进行中:显示骨架屏,轮询等待
            st.markdown('<div class="tc-skeleton"></div>', unsafe_allow_html=True)
            st.markdown('<div class="tc-skeleton line" style="width:60%"></div>', unsafe_allow_html=True)
            time.sleep(1.0)
            st.rerun()
    st.stop()

# ------------------------------------------------------------
# 页面路由
# ------------------------------------------------------------
_page = st.session_state.get("page", "dashboard")
if _page == "deep":
    deep_analysis.render(pal)
elif _page == "watchlist":
    watchlist.render(pal)
elif _page == "history":
    history.render(pal)
else:
    dashboard.render(pal)
