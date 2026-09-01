"""
深度分析页(第三批前端重构)

从原 app.py 主体迁移:顶部行情概览卡 + 中部 K线/技术指标卡片 + 底部 5 Tab。
任务轮询已上移到 app.py 全局(任何页面都能看到流水线进度),本页只负责静态渲染。
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from api_client import ApiError, stock_news
from components import charts, report_card as rc
from data_layer import cached_history, cached_info
from stock_map import lookup_name


def render(pal: dict):
    code = st.session_state.code
    rng = st.session_state.get("rng", "3m")
    start_str = st.session_state.get("start_str", "")
    end_str = st.session_state.get("end_str", "")

    # ---- 顶部:行情概览卡 ----
    try:
        info = cached_info(code)
    except ApiError:
        info = {"code": code, "name": lookup_name(code), "price": None, "pct_change": None}
    rc.render_quote_card(info, pal)

    # ---- 中部:K线 + 技术指标卡片 ----
    chart_col, side_col = st.columns([2.6, 1.1], gap="medium")

    with chart_col:
        st.markdown(f'<div style="font-size:15px;font-weight:700;color:{pal["fg"]};">📉 行情走势</div>',
                    unsafe_allow_html=True)
        mcols = st.columns(4)
        ma_sel = {w: mcols[i].checkbox(f"MA{w}", value=True, key=f"ma{w}")
                  for i, w in enumerate([5, 10, 20, 60])}
        secondary = st.selectbox("副图指标", ["MACD", "RSI", "关闭"],
                                 index=0, key="secondary", format_func=lambda x: f"副图: {x}")
        _sec_map = {"MACD": "macd", "RSI": "rsi", "关闭": "none"}

        try:
            data = cached_history(code, rng, start_str, end_str)
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
            st.caption(f"{data.get('name', code)} · 共 {len(df)} 个交易日"
                       f"{' · 部分指标前期为空(滚动窗口未满)' if secondary != '关闭' else ''}")
        else:
            st.info("暂无行情数据。请点击左侧「重新分析」触发数据采集,或检查后端与数据库。")

    with side_col:
        st.markdown(f'<div style="font-size:15px;font-weight:700;color:{pal["fg"]};">⚡ 技术指标信号</div>',
                    unsafe_allow_html=True)
        ind = info.get("indicators")
        rc.render_indicator_cards(ind, pal)
        if ind:
            st.markdown(f"""
            <div class="tc-card">
              <div style="font-size:12px;color:{pal['muted']};">涨跌幅</div>
              <div style="font-size:22px;font-weight:700;"
                   class="{'tc-up' if (ind.get('pct_change') or 0) >= 0 else 'tc-down'}">
                {ind.get('pct_change'):+.2f}%
              </div>
            </div>""", unsafe_allow_html=True)

    # ---- 底部:多标签页 ----
    st.markdown("---")
    result = st.session_state.analysis_result
    tab_report, tab_senti, tab_risk, tab_rag, tab_logs = st.tabs(
        ["📝 投资报告", "💬 情感分析详情", "⚠️ 风险评估细项", "📚 数据溯源(RAG)", "🧾 系统日志 / Token"])

    with tab_report:
        rc.render_report_tab(result, pal)
        if result:
            html_report = rc.build_report_html(result, pal)
            st.download_button("⬇️ 导出报告(HTML · 浏览器打印为 PDF)", data=html_report,
                               file_name=f"分析报告_{code}.html", mime="text/html")
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

    # ---- 舆情:个股新闻(底部) ----
    st.markdown("---")
    with st.expander("📰 个股新闻(近 10 条)", expanded=False):
        try:
            news = stock_news(code) or {}
            items = news.get("items") or []
        except ApiError:
            items = []
        if items:
            for n in items:
                st.markdown(f"**{n.get('title','')}**  ·  {n.get('source','')} · {(n.get('publish_time') or '')[:16]}")
                if n.get("content"):
                    st.caption(n["content"])
        else:
            st.info("暂无新闻数据(运行完整分析会抓取东方财富新闻)。")
