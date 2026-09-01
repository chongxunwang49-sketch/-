"""
专业级股票投研终端(专业看板升级)

布局:
  侧边栏   控制面板:股票代码(自动补全公司名) / 时间范围 / 分析模式 / 数据源指示灯 / 重新分析
  主区顶部 实时行情概览卡(名称/现价/涨跌幅/开高低量)
  主区中部 左:K线图(均线开关+成交量+MACD/RSI副图+范围滑块)  右:技术指标信号卡片
  主区底部 5 个 Tab:投资报告 / 情感分析详情 / 风险评估细项 / 数据溯源(RAG) / 系统日志·Token

交互模式:
  点击「重新分析」-> POST /analyze 拿 task_id -> 每 ~1s 轮询 /task/status 渲染流水线
  -> 完成后拉取 /task/result 渲染全部看板。全程无长 HTTP 阻塞。

启动: streamlit run frontend/app.py
"""
import os
import sys
import time
from datetime import date, timedelta

import pandas as pd
import streamlit as st

# 保证本目录可被 import(直接 streamlit run 时 sys.path 已含本目录,再加一层保险)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from api_client import ApiError, health, start_analysis, stock_history, stock_info, task_result, task_status
from components import charts, pipeline, report_card as rc
from stock_map import COMMON_STOCKS, lookup_name
from theme import apply_theme

st.set_page_config(page_title="多智能体股票投研终端", page_icon="📈", layout="wide")

# ------------------------------------------------------------
# 主题与会话状态
# ------------------------------------------------------------
if "theme" not in st.session_state:
    st.session_state.theme = "dark"
pal = apply_theme(st.session_state.theme)

if "code" not in st.session_state:
    st.session_state.code = "600519"
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
if "backend_ok" not in st.session_state:
    try:
        health()
        st.session_state.backend_ok = True
    except ApiError:
        st.session_state.backend_ok = False

# 后台数据缓存(历史行情与分析信息,短 TTL 即可)
@st.cache_data(ttl=120, show_spinner=False)
def cached_history(code: str, time_range: str, start: str, end: str) -> dict:
    return stock_history(code, time_range, start=start, end=end)


@st.cache_data(ttl=120, show_spinner=False)
def cached_info(code: str) -> dict:
    return stock_info(code)


def _reset_analysis():
    st.session_state.analysis_result = None
    st.session_state.last_stages = None
    st.session_state.llm_stats = None


# ------------------------------------------------------------
# 侧边栏:控制面板
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

    st.markdown("---")
    running = st.session_state.running_task is not None

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
    rng = _rng_map[time_range]
    start_str, end_str = "", ""
    if rng == "custom":
        c1, c2 = st.columns(2)
        start_d = c1.date_input("起始", value=date.today() - timedelta(days=90))
        end_d = c2.date_input("结束", value=date.today())
        if start_d > end_d:
            start_d, end_d = end_d, start_d
        start_str, end_str = start_d.strftime("%Y-%m-%d"), end_d.strftime("%Y-%m-%d")

    mode = st.radio("分析模式", ["完整模式(全 Agent)", "快速模式(跳过情感)"], index=0, disabled=running)
    mode_key = "full" if mode.startswith("完整") else "quick"

    st.markdown("---")
    st.markdown("**数据源状态**")
    st.markdown(pipeline.data_source_light_html(st.session_state.data_source, pal),
                unsafe_allow_html=True)

    if st.button("🚀 重新分析", type="primary", use_container_width=True, disabled=running):
        try:
            resp = start_analysis(code or "600519", mode_key)
            st.session_state.running_task = resp["task_id"]
            _reset_analysis()
            cached_info.clear()
            cached_history.clear()
            st.rerun()
        except ApiError as e:
            st.toast(f"启动分析失败: {e}", icon="❌")

    st.markdown("---")
    st.caption("数据仅用于学习与技术演示,不构成投资建议")

# ------------------------------------------------------------
# 主区:顶部行情概览卡
# ------------------------------------------------------------
try:
    info = cached_info(st.session_state.code)
except ApiError:
    info = {"code": st.session_state.code, "name": lookup_name(st.session_state.code),
            "price": None, "pct_change": None}
rc.render_quote_card(info, pal)

# ------------------------------------------------------------
# 主区:分析流水线(任务运行中)
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
            cached_info.clear()
            cached_history.clear()
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
# 主区:中部 K 线 + 技术指标卡片
# ------------------------------------------------------------
chart_col, side_col = st.columns([2.6, 1.1], gap="medium")

with chart_col:
    st.markdown(f'<div style="font-size:15px;font-weight:700;color:{pal["fg"]};">📉 行情走势</div>',
                unsafe_allow_html=True)
    mcols = st.columns(4)
    ma_sel = {w: mcols[i].checkbox(f"MA{w}", value=True, key=f"ma{w}") for i, w in enumerate([5, 10, 20, 60])}
    secondary = st.selectbox("副图指标", ["MACD", "RSI", "关闭"],
                             index=0, key="secondary", format_func=lambda x: f"副图: {x}")
    _sec_map = {"MACD": "macd", "RSI": "rsi", "关闭": "none"}

    try:
        data = cached_history(st.session_state.code, rng, start_str, end_str)
    except ApiError as e:
        st.warning(f"行情加载失败: {e}")
        data = {}

    if data and data.get("rows"):
        df = pd.DataFrame(data["rows"])
        fig = charts.build_kline_chart(
            df, pal, [w for w in ma_sel if ma_sel[w]],
            _sec_map[secondary], height=600,
        )
        st.plotly_chart(fig, use_container_width=True,
                        config={"scrollZoom": True, "displaylogo": False})
        st.caption(f"{data.get('name', st.session_state.code)} · 共 {len(df)} 个交易日"
                   f"{' · 部分指标前期为空(滚动窗口未满)' if secondary != '关闭' else ''}")
    else:
        st.info("暂无行情数据。请点击左侧「重新分析」触发数据采集,或检查后端与数据库。")

with side_col:
    st.markdown(f'<div style="font-size:15px;font-weight:700;color:{pal["fg"]};">⚡ 技术指标信号</div>',
                unsafe_allow_html=True)
    ind = info.get("indicators")
    rc.render_indicator_cards(ind, pal)
    if ind:
        close = ind.get("close_price")
        st.markdown(f"""
        <div class="tc-card">
          <div style="font-size:12px;color:{pal['muted']};">涨跌幅</div>
          <div style="font-size:22px;font-weight:700;"
               class="{'tc-up' if (ind.get('pct_change') or 0) >= 0 else 'tc-down'}">
            {ind.get('pct_change'):+.2f}%
          </div>
        </div>""", unsafe_allow_html=True)

# ------------------------------------------------------------
# 主区:底部多标签页
# ------------------------------------------------------------
st.markdown("---")
result = st.session_state.analysis_result
tab_report, tab_senti, tab_risk, tab_rag, tab_logs = st.tabs(
    ["📝 投资报告", "💬 情感分析详情", "⚠️ 风险评估细项", "📚 数据溯源(RAG)", "🧾 系统日志 / Token"])

with tab_report:
    rc.render_report_tab(result, pal)
    if result:
        html_report = rc.build_report_html(result, pal)
        st.download_button("⬇️ 导出报告(HTML · 浏览器打印为 PDF)", data=html_report,
                           file_name=f"分析报告_{st.session_state.code}.html",
                           mime="text/html")
        st.caption("下载后在浏览器打开,按 Ctrl+P 另存为 PDF 即可。")

with tab_senti:
    rc.render_sentiment_tab(result, pal)

with tab_risk:
    rc.render_risk_tab(result, pal)

with tab_rag:
    rc.render_rag_tab(result, pal)

with tab_logs:
    rc.render_logs_tab(st.session_state.last_stages, st.session_state.llm_stats,
                       st.session_state.data_source, pal)
