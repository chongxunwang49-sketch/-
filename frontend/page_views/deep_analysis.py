"""
深度研究页(v4.0 步骤5:核心主战场)

- 顶部概览卡:股价/涨跌幅「计速器」滚动(值变化时翻滚,未变直出)
- K线:MA5/10/20/60 勾选 + 副图切换 + 动态 MA 周期滑块(前端现算叠加)
- Agent 网络拓扑图(ECharts 力导向,完成态渲染;运行中在 app.py 轮询分支渲染 live)
- 底部 5 Tab(横向滑入) + 个股新闻
"""
from __future__ import annotations

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from api_client import ApiError, stock_news
from components import agent_topology, charts, report_card as rc
from components.ui import wow
from data_layer import cached_history, cached_info
from stock_map import lookup_name


def _quote_card(pal: dict, info: dict) -> None:
    """顶部报价卡(计速器):值变化时数字翻滚,未变化直出终值"""
    price = info.get("price")
    pct = info.get("pct_change")
    name = info.get("name") or info.get("code", "-")
    code = info.get("code", "-")
    if price is None:
        st.markdown(f"""
        <div class="tc-card" style="display:flex;align-items:center;justify-content:space-between;padding:18px 24px;">
          <div>
            <div style="font-size:24px;font-weight:800;color:{pal['fg']};">{name}</div>
            <div style="color:{pal['muted']};font-size:13px;">{code} · 暂无行情数据,点击「重新分析」采集</div>
          </div>
        </div>""", unsafe_allow_html=True)
        return

    key = (round(float(price), 2), round(float(pct or 0), 2))
    animate = st.session_state.get("_quote_prev") != key
    st.session_state["_quote_prev"] = key

    up = pct >= 0 if pct is not None else True
    pct_color = pal["up"] if up else pal["down"]
    sign = "+" if up else ""
    pct_v = abs(pct) if pct is not None else 0.0

    price_el = (wow.countup_html(float(price), 2, font_size="38px", color=pal["fg"], el_id="cu_price")
                if animate else f'<div style="font-size:38px;font-weight:800;color:{pal["fg"]};">{float(price):,.2f}</div>')
    pct_el = (wow.countup_html(pct_v, 2, duration=700, font_size="22px", color=pct_color, el_id="cu_pct")
              if animate else f'<div style="font-size:22px;font-weight:800;color:{pct_color};">{sign}{pct_v:.2f}%</div>')

    oh, hi, lo = info.get("open"), info.get("high"), info.get("low")
    vol = info.get("volume", 0)
    html = f"""
    <div style="background:linear-gradient(135deg,rgba(79,140,255,.08),rgba(180,92,255,.10));
                border:1px solid rgba(79,140,255,.22);border-radius:14px;
                padding:16px 22px;display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap;">
      <div>
        <div style="font-size:22px;font-weight:800;color:{pal['fg']};">{name}</div>
        <div style="color:{pal['muted']};font-size:12px;">{code} · 最新交易日 {info.get('latest_date','-')}</div>
      </div>
      <div style="display:flex;align-items:baseline;gap:18px;">{price_el}{pct_el}</div>
      <div style="display:flex;gap:20px;color:{pal['muted']};font-size:12px;">
        <div>开盘<div style="color:{pal['fg']};font-size:15px;font-weight:600;">{oh if oh is not None else '-'}</div></div>
        <div>最高<div style="color:{pal['up']};font-size:15px;font-weight:600;">{hi if hi is not None else '-'}</div></div>
        <div>最低<div style="color:{pal['down']};font-size:15px;font-weight:600;">{lo if lo is not None else '-'}</div></div>
        <div>成交量<div style="color:{pal['fg']};font-size:15px;font-weight:600;">{vol:,}</div></div>
      </div>
    </div>"""
    components.html(html, height=150)


def render(pal: dict):
    code = st.session_state.code
    rng = st.session_state.get("rng", "3m")
    start_str = st.session_state.get("start_str", "")
    end_str = st.session_state.get("end_str", "")

    # ---- 顶部:行情概览卡(计速器) ----
    try:
        info = cached_info(code)
    except ApiError:
        info = {"code": code, "name": lookup_name(code), "price": None, "pct_change": None}
    _quote_card(pal, info)

    # ---- 中部:K线 + 技术指标 ----
    chart_col, side_col = st.columns([2.6, 1.1], gap="medium")

    with chart_col:
        st.markdown(f'<div style="font-size:15px;font-weight:700;color:{pal["fg"]};">📉 行情走势</div>',
                    unsafe_allow_html=True)
        mcols = st.columns(4)
        ma_sel = {w: mcols[i].checkbox(f"MA{w}", value=True, key=f"ma{w}")
                  for i, w in enumerate([5, 10, 20, 60])}
        c_sec, c_slider = st.columns([1.2, 2])
        with c_sec:
            secondary = st.selectbox("副图指标", ["MACD", "RSI", "关闭"],
                                     index=0, key="secondary", format_func=lambda x: f"副图: {x}")
        _sec_map = {"MACD": "macd", "RSI": "rsi", "关闭": "none"}

        # v4.0 动态 MA 周期滑块(前端现算,不改后端)
        extra_ma = None
        ma_n = c_slider.slider("动态 MA 周期", 5, 90, 20, key="ma_dyn")

        try:
            data = cached_history(code, rng, start_str, end_str)
        except ApiError as e:
            st.warning(f"行情加载失败: {e}")
            data = {}

        if data and data.get("rows"):
            df = pd.DataFrame(data["rows"])
            if "close" in df.columns:
                extra_ma = (ma_n, df["close"].rolling(ma_n).mean())
            fig = charts.build_kline_chart(
                df, pal, [w for w in ma_sel if ma_sel[w]],
                _sec_map[secondary], height=600, extra_ma=extra_ma,
            )
            st.plotly_chart(fig, use_container_width=True,
                            config={"scrollZoom": True, "displaylogo": False})
            st.caption(f"{data.get('name', code)} · 共 {len(df)} 个交易日 · 青色线为动态 MA{ma_n}"
                       f"{' · 部分指标前期为空(滚动窗口未满)' if secondary != '关闭' else ''}")
        else:
            st.info("暂无行情数据。请点击左侧「重新分析」触发数据采集,或检查后端与数据库。")

    with side_col:
        st.markdown(f'<div style="font-size:15px;font-weight:700;color:{pal["fg"]};">⚡ 技术指标信号</div>',
                    unsafe_allow_html=True)
        ind = info.get("indicators")
        rc.render_indicator_cards(ind, pal)
        if ind and ind.get("pct_change") is not None:
            st.markdown(f"""
            <div class="tc-card">
              <div style="font-size:12px;color:{pal['muted']};">涨跌幅</div>
              <div style="font-size:22px;font-weight:700;"
                   class="{'tc-up' if (ind.get('pct_change') or 0) >= 0 else 'tc-down'}">
                {ind.get('pct_change'):+.2f}%
              </div>
            </div>""", unsafe_allow_html=True)

    # ---- Agent 网络拓扑图(完成态) + 思维链鱼缸 ----
    if st.session_state.get("last_stages") or st.session_state.get("fish_tank_open"):
        st.markdown("---")
        st.markdown(f'<div style="font-size:15px;font-weight:700;color:{pal["fg"]};">🧠 Agent 协作拓扑</div>',
                    unsafe_allow_html=True)
        st.caption("节点可拖拽重排,悬停查看该 Agent 耗时/状态/备注;运行中的拓扑见上方流水线区。")
        if st.session_state.get("last_stages"):
            agent_topology.render_topology(st.session_state.last_stages, live=False, height=460)

        # 思维链鱼缸(彩蛋)
        tank_on = st.toggle("🐟 思维链鱼缸", value=bool(st.session_state.get("fish_tank_open")),
                            key="tank_toggle")
        if tank_on != bool(st.session_state.get("fish_tank_open")):
            st.session_state["fish_tank_open"] = tank_on
            st.rerun()
        if st.session_state.get("fish_tank_open"):
            from components.ui import fish_tank
            fish_tank.render(st.session_state.last_stages or [], height=230)

    # ---- 底部:多标签页 ----
    st.markdown("---")
    result = st.session_state.analysis_result
    tab_report, tab_fund, tab_senti, tab_risk, tab_rag, tab_logs = st.tabs(
        ["📝 投资报告", "💰 基本面与估值", "💬 情感分析详情", "⚠️ 风险评估细项",
         "📚 数据溯源(RAG)", "🧾 系统日志 / Token"])

    with tab_report:
        rc.render_report_tab(result, pal)
        if result:
            html_report = rc.build_report_html(result, pal)
            st.download_button("⬇️ 导出报告(HTML · 浏览器打印为 PDF)", data=html_report,
                               file_name=f"分析报告_{code}.html", mime="text/html")
            st.caption("下载后在浏览器打开,按 Ctrl+P 另存为 PDF 即可。")

    with tab_fund:
        rc.render_fundamental_tab(result, pal)

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
