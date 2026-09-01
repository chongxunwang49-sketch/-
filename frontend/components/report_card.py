"""
报告结构化卡片组件(专业看板升级)

- render_quote_card : 顶部实时行情概览卡
- render_report_tab : 投资报告(综合评分仪表盘 + 投资建议 + 技术/消息/基本面三板块 + 完整报告)
- render_sentiment_tab : 情感分析详情(得分 + 情绪时间线 + 逐条新闻)
- render_risk_tab : 风险评估细项
- render_rag_tab : 数据溯源(RAG 引用片段)
- render_logs_tab : 系统日志 / Token 消耗
- render_indicator_cards : 右侧技术指标信号卡片(RSI/MACD/BOLL/均线)
- build_report_html : 导出报告的 HTML 版本(浏览器打印为 PDF)
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from components import charts
from theme import card_html


# ------------------------------------------------------------
# 顶部行情概览卡
# ------------------------------------------------------------
def render_quote_card(info: dict, pal: dict):
    price = info.get("price")
    pct = info.get("pct_change")
    name = info.get("name") or info.get("code", "-")
    code = info.get("code", "-")

    if price is None:
        # 未采集:只展示名称/代码,提示运行分析
        st.markdown(f"""
        <div class="tc-card" style="display:flex;align-items:center;justify-content:space-between;padding:18px 24px;">
          <div>
            <div style="font-size:24px;font-weight:800;color:{pal['fg']};">{name}</div>
            <div style="color:{pal['muted']};font-size:13px;">{code} · 暂无行情数据,点击「重新分析」采集</div>
          </div>
        </div>""", unsafe_allow_html=True)
        return

    pct_cls = "tc-up" if (pct if pct is not None else 0) >= 0 else "tc-down"
    pct_sign = "+" if (pct if pct is not None else 0) >= 0 else ""
    pct_txt = f"{pct_sign}{pct:.2f}%" if pct is not None else "-"
    price_str = f"{price:,.2f}"
    # 迷你指标
    oh = f"{info.get('open', '-'):,.2f}" if info.get("open") else "-"
    hi = f"{info.get('high', '-'):,.2f}" if info.get("high") else "-"
    lo = f"{info.get('low', '-'):,.2f}" if info.get("low") else "-"
    vol = f"{info.get('volume', 0):,}"
    st.markdown(f"""
    <div class="tc-card" style="display:flex;align-items:center;justify-content:space-between;
                gap:18px;flex-wrap:wrap;padding:18px 24px;">
      <div>
        <div style="font-size:24px;font-weight:800;color:{pal['fg']};">{name}</div>
        <div style="color:{pal['muted']};font-size:13px;">{code} · 最新交易日 {info.get('latest_date','-')}</div>
      </div>
      <div style="display:flex;align-items:baseline;gap:10px;">
        <span style="font-size:34px;font-weight:800;color:{pal['fg']};">{price_str}</span>
        <span class="tc-value {pct_cls}" style="font-size:18px;font-weight:700;">{pct_txt}</span>
      </div>
      <div style="display:flex;gap:22px;color:{pal['muted']};font-size:12px;">
        <div>开盘<div style="color:{pal['fg']};font-size:15px;font-weight:600;">{oh}</div></div>
        <div>最高<div style="color:{pal['up']};font-size:15px;font-weight:600;">{hi}</div></div>
        <div>最低<div style="color:{pal['down']};font-size:15px;font-weight:600;">{lo}</div></div>
        <div>成交量<div style="color:{pal['fg']};font-size:15px;font-weight:600;">{vol}</div></div>
      </div>
    </div>""", unsafe_allow_html=True)


# ------------------------------------------------------------
# 综合评分与投资建议
# ------------------------------------------------------------
def _tech_score(tech: dict | None) -> float:
    """技术面得分 0-1(基于 RSI/MACD/价格与MA20 相对位置)"""
    if not tech:
        return 0.5
    ts = 0.5
    rsi = tech.get("rsi14")
    hist = tech.get("macd_hist")
    close, ma20 = tech.get("close_price"), tech.get("ma20")
    if rsi is not None:
        ts = 0.5 * ts + 0.5 * max(0.0, min(1.0, (rsi - 30) / 40))
    if hist is not None:
        ts = 0.5 * ts + 0.5 * (1.0 if hist > 0 else 0.0)
    if close is not None and ma20:
        ts = 0.5 * ts + 0.5 * (1.0 if close >= ma20 else 0.0)
    return ts


def composite_score(result: dict) -> float:
    """综合评分 = 技术0.35 + 情感0.30 + 风险0.20 + 基本面(RAG)0.15"""
    tech = _tech_score((result or {}).get("technical"))
    senti = ((result or {}).get("sentiment") or {}).get("score")
    senti = float(senti) if senti is not None else 0.5
    risk_level = ((result or {}).get("risk") or {}).get("risk_level")
    rscore = {"低": 0.8, "中": 0.5, "高": 0.2}.get(risk_level, 0.5)
    has_rag = bool(((result or {}).get("report") or {}).get("rag_sources"))
    fundamental = 0.62 if has_rag else 0.5
    return 0.35 * tech + 0.30 * senti + 0.20 * rscore + 0.15 * fundamental


def advice_of(score: float) -> tuple[str, str]:
    """(建议文案, 颜色关键字)"""
    if score >= 0.66:
        return "买入 / 重点关注", "tc-up"
    if score >= 0.55:
        return "持有 / 中性偏多", "tc-accent"
    if score >= 0.45:
        return "观望 / 谨慎", "tc-warn"
    return "规避 / 谨慎参与", "tc-danger"


# ------------------------------------------------------------
# 右侧技术指标信号卡片
# ------------------------------------------------------------
def indicator_signals(ind: dict) -> list[dict]:
    """从技术指标快照计算 4 张卡片:RSI/MACD/布林带/均线"""
    cards = []
    rsi = ind.get("rsi14")
    if rsi is not None:
        if rsi >= 70:
            sig, cls, txt = "超买 · 偏空", "tc-warn", f"{rsi:.1f} ≥ 70,注意回调"
        elif rsi <= 30:
            sig, cls, txt = "超卖 · 偏多", "tc-up", f"{rsi:.1f} ≤ 30,或存反弹"
        else:
            sig, cls, txt = "中性", "tc-muted", f"{rsi:.1f} 处于 30-70 区间"
        cards.append({"label": "RSI(14)", "value": f"{rsi:.1f}", "signal": sig, "cls": cls, "sub": txt})
    else:
        cards.append({"label": "RSI(14)", "value": "-", "signal": "无数据", "cls": "tc-muted", "sub": ""})

    hist = ind.get("macd_hist")
    if hist is not None:
        sig, cls = ("多头", "tc-up") if hist >= 0 else ("空头", "tc-down")
        cards.append({"label": "MACD柱", "value": f"{hist:+.3f}",
                      "signal": sig, "cls": cls, "sub": f"DIF {ind.get('macd_dif', '-')} / DEA {ind.get('macd_dea', '-')}"})
    else:
        cards.append({"label": "MACD柱", "value": "-", "signal": "无数据", "cls": "tc-muted", "sub": ""})

    close, up, low = ind.get("close_price"), ind.get("boll_up"), ind.get("boll_low")
    if close is not None and up is not None and low is not None:
        if close >= up:
            sig, cls, txt = "突破上轨", "tc-up", "强势但需防过热"
        elif close <= low:
            sig, cls, txt = "跌破下轨", "tc-down", "弱势或超跌"
        else:
            pos = (close - low) / (up - low) * 100
            sig, cls, txt = "区间内", "tc-accent", f"位于布林带 {pos:.0f}% 位置"
        cards.append({"label": "布林带(20)", "value": f"{close:,.2f}", "signal": sig, "cls": cls,
                      "sub": f"上 {up:,.2f} / 下 {low:,.2f} · {txt}"})
    else:
        cards.append({"label": "布林带(20)", "value": "-", "signal": "无数据", "cls": "tc-muted", "sub": ""})

    ma5, ma20 = ind.get("ma5"), ind.get("ma20")
    if ma5 is not None and ma20 is not None:
        if ma5 >= ma20:
            sig, cls, txt = "多头排列", "tc-up", "短期均线在上,趋势偏强"
        else:
            sig, cls, txt = "空头排列", "tc-down", "短期均线在下,趋势偏弱"
        cards.append({"label": "均线 MA5/20", "value": f"{ma5:,.2f}", "signal": sig, "cls": cls,
                      "sub": f"MA5 {ma5:,.2f} / MA20 {ma20:,.2f} · {txt}"})
    else:
        cards.append({"label": "均线 MA5/20", "value": "-", "signal": "无数据", "cls": "tc-muted", "sub": ""})
    return cards


def render_indicator_cards(ind: dict | None, pal: dict):
    if not ind:
        st.markdown(card_html(pal, "技术指标", "暂无数据",
                              "行情不足 20 个交易日,无法计算指标", "tc-muted"), unsafe_allow_html=True)
        return
    for c in indicator_signals(ind):
        st.markdown(card_html(pal, c["label"], c["value"], f"{c['signal']} · {c['sub']}", c["cls"]),
                    unsafe_allow_html=True)


# ------------------------------------------------------------
# Tab 1: 投资报告
# ------------------------------------------------------------
def render_report_tab(result: dict | None, pal: dict):
    if not result:
        st.info("尚无分析结果。请确认左侧已启动分析,或点击「重新分析」。")
        return
    report = result.get("report") or {}
    score = composite_score(result)
    label, cls = advice_of(score)

    c1, c2 = st.columns([1, 1.4], gap="medium")
    with c1:
        st.plotly_chart(charts.build_gauge(score, pal, "综合评分"), use_container_width=True)
        # 投资建议横幅
        st.markdown(f"""
        <div class="tc-card" style="text-align:center;border:1px solid {pal['border']};">
          <div style="font-size:12px;color:{pal['muted']};">投资建议</div>
          <div style="font-size:28px;font-weight:800;" class="{cls}">{label}</div>
          <div style="font-size:12px;color:{pal['muted']};">综合评分 {score:.2f}/1.00 · 仅供参考,不构成投资建议</div>
        </div>""", unsafe_allow_html=True)
    with c2:
        tech_s = _tech_score(result.get("technical"))
        senti = float((result.get("sentiment") or {}).get("score") or 0.5)
        risk_level = (result.get("risk") or {}).get("risk_level")
        rscore = {"低": 0.8, "中": 0.5, "高": 0.2}.get(risk_level, 0.5)
        fundamental = 0.62 if report.get("rag_sources") else 0.5
        st.plotly_chart(charts.build_radar(senti, tech_s, fundamental, rscore, pal),
                        use_container_width=True)

    st.markdown("#### 分板块结论")
    with st.expander("📊 技术面分析", expanded=True):
        st.markdown(report.get("technical_analysis") or result.get("technical_analysis") or "无技术面数据")
        ind = result.get("technical")
        if ind:
            df = pd.DataFrame([
                {"指标": "RSI(14)", "数值": ind.get("rsi14")},
                {"指标": "MACD 柱", "数值": ind.get("macd_hist")},
                {"指标": "MA5", "数值": ind.get("ma5")},
                {"指标": "MA10", "数值": ind.get("ma10")},
                {"指标": "MA20", "数值": ind.get("ma20")},
                {"指标": "收盘价", "数值": ind.get("close_price")},
            ])
            st.caption("技术指标数值快照")
            st.dataframe(df, use_container_width=True, hide_index=True)
    with st.expander("💬 消息面 · 情感分析", expanded=False):
        senti = result.get("sentiment")
        if senti:
            st.markdown(f"**情感得分:{senti.get('score', '-')}**  ·  得分来源:{senti.get('source', '-')}")
            st.markdown(f"理由:{senti.get('reason') or '无'}")
        else:
            st.info("无情感分析结果(快速模式跳过或新闻为空)。")
    with st.expander("🏛 基本面 · RAG 财报知识库", expanded=False):
        sources = report.get("rag_sources") or []
        if sources:
            st.markdown(f"检索到 **{len(sources)}** 条财报知识库片段,详见「数据溯源(RAG)」Tab。")
            for i, src in enumerate(sources[:3], 1):
                st.markdown(f"- `[知识库{i}]` {src[:80]}{'…' if len(src) > 80 else ''}")
        else:
            st.info("本次未检索到知识库引用(RAG 不可用或语料为空)。")
    with st.expander("📄 完整 Markdown 报告", expanded=False):
        st.markdown(report.get("report", "无报告内容"))


# ------------------------------------------------------------
# Tab 2: 情感分析详情
# ------------------------------------------------------------
def render_sentiment_tab(result: dict | None, pal: dict):
    if not result:
        st.info("尚无分析结果。")
        return
    senti = result.get("sentiment")
    news = result.get("news_items") or []
    if not senti:
        st.info("无情感分析结果(快速模式跳过或新闻为空)。")
        return
    score = float(senti.get("score", 0.5))
    c1, c2 = st.columns([1, 2.2], gap="medium")
    with c1:
        st.plotly_chart(charts.build_gauge(score, pal, "情感得分"), use_container_width=True)
        st.markdown(f"**情感来源:** {senti.get('source', '-')}")
        st.markdown(f"**理由:** {senti.get('reason') or '无'}")
    with c2:
        st.plotly_chart(charts.build_sentiment_timeline(news, score, pal),
                        use_container_width=True)

    st.markdown("#### 逐条新闻明细")
    if news:
        rows = [{
            "时间": (n.get("publish_time") or "")[:10],
            "标题": n.get("title", ""),
            "情感得分": n.get("sentiment_score"),
            "来源": n.get("source", ""),
        } for n in news]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True,
                     column_config={"情感得分": st.column_config.ProgressColumn(
                         "情感得分", min_value=0.0, max_value=1.0)})
    else:
        st.info("未采集到新闻(情感分析输入为空)。")


# ------------------------------------------------------------
# Tab 3: 风险评估细项
# ------------------------------------------------------------
def render_risk_tab(result: dict | None, pal: dict):
    if not result:
        st.info("尚无分析结果。")
        return
    risk = result.get("risk")
    if not risk:
        st.info("无风险评估结果。")
        return
    level = risk.get("risk_level", "中")
    color = {"低": pal["ok"], "中": pal["warning"], "高": pal["danger"]}.get(level, pal["muted"])
    st.markdown(f"""
    <div class="tc-card" style="display:flex;align-items:center;justify-content:space-between;">
      <div>
        <div style="font-size:12px;color:{pal['muted']};">风险等级</div>
        <div style="font-size:32px;font-weight:800;color:{color};">{level}</div>
      </div>
      <div style="max-width:60%;font-size:13px;color:{pal['muted']};">{risk.get('summary') or '无总结'}</div>
    </div>""", unsafe_allow_html=True)
    st.markdown("#### 风险点")
    for r in risk.get("risks") or []:
        st.markdown(f"- ⚠️ {r}")


# ------------------------------------------------------------
# Tab 4: 数据溯源(RAG)
# ------------------------------------------------------------
def render_rag_tab(result: dict | None, pal: dict):
    if not result:
        st.info("尚无分析结果。")
        return
    sources = (result.get("report") or {}).get("rag_sources") or []
    if not sources:
        st.info("本次报告未引用知识库(RAG 检索不可用或语料为空)。报告中数字无法溯源。")
        return
    st.caption("以下片段来自公司财报知识库(ChromaDB + bge 中文向量检索),报告生成 Agent 据此引用数据、防幻觉。")
    for i, src in enumerate(sources, 1):
        with st.expander(f"📎 引用片段 {i} · 来源:财报知识库"):
            st.text(src)
    st.markdown("> 提示:报告中出现「来源:知识库」标注的数据,可回查对应片段核实。")


# ------------------------------------------------------------
# Tab 5: 系统日志 / Token 消耗
# ------------------------------------------------------------
def render_logs_tab(stages: list[dict] | None, llm_stats: dict | None,
                    data_source: str | None, pal: dict):
    if stages:
        st.markdown("#### Agent 流水线耗时")
        rows = [{
            "阶段": s["label"],
            "状态": s["status"],
            "耗时(秒)": s.get("elapsed"),
            "备注": s.get("note") or "",
        } for s in stages]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.info("尚无任务日志。")

    st.markdown("#### LLM Token 消耗(本任务)")
    stats = llm_stats or {}
    if stats.get("calls"):
        c = st.columns(4)
        c[0].metric("调用次数", stats.get("calls", 0))
        c[1].metric("输入 Token", stats.get("prompt_tokens", 0))
        c[2].metric("输出 Token", stats.get("completion_tokens", 0))
        c[3].metric("合计 Token", stats.get("total_tokens", 0))
        st.caption("统计来源:后端 LLM 调用层(agents/llm.py)进程级计数器,按任务前后增量计算。")
    else:
        st.info("本任务未产生可统计的 LLM 调用(Ollama 通常不返回 token 用量)。")

    st.markdown("#### 数据源")
    if data_source:
        from components.pipeline import data_source_light_html
        st.markdown(data_source_light_html(data_source, pal), unsafe_allow_html=True)
    st.markdown("#### 后端日志")
    st.caption("完整结构化日志(含单条 Agent 失败/降级/耗时)见后端控制台与 logging_config.py 配置。")


# ------------------------------------------------------------
# 导出报告(HTML -> 浏览器打印为 PDF)
# ------------------------------------------------------------
def build_report_html(result: dict, pal: dict) -> str:
    report = result.get("report") or {}
    score = composite_score(result)
    label, cls = advice_of(score)
    senti = result.get("sentiment") or {}
    risk = result.get("risk") or {}
    tech_analysis = report.get("technical_analysis") or result.get("technical_analysis") or "无"
    sources = report.get("rag_sources") or []
    news = result.get("news_items") or []

    senti_html = (f"情感得分: {senti.get('score')} · 理由: {senti.get('reason')}" if senti else "无情感数据")
    risk_html = f"风险等级: {risk.get('risk_level', '未知')} · 风险点: {'、'.join(risk.get('risks') or [])}"
    sources_html = "".join(f"<li>{s}</li>" for s in sources) or "<li>无</li>"
    news_html = "".join(
        f"<li>{(n.get('publish_time') or '')[:10] or '未知'} [{n.get('source','')}] {n.get('title')} "
        f"(情感 {n.get('sentiment_score', '-')})</li>" for n in news[:10]) or "<li>无新闻</li>"

    return f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<title>股票分析报告 - {report.get('company_name', result.get('stock_code',''))}</title>
<style>
  body {{ font-family: 'Microsoft YaHei', sans-serif; margin: 32px; color: #1f2a3d; }}
  h1 {{ color: #141a26; }} h2 {{ border-bottom: 2px solid #4f8cff; padding-bottom: 4px; }}
  .score {{ font-size: 26px; font-weight: 800; color: #2f6bff; }}
  .advice {{ font-size: 20px; font-weight: 800; color: #d5340f; }}
  .box {{ background: #f5f7fb; border: 1px solid #d9e0ec; border-radius: 8px; padding: 12px 16px; margin: 10px 0; }}
  ul {{ line-height: 1.7; }} small {{ color: #7c869c; }}
</style></head><body>
<h1>📈 多智能体股票分析报告</h1>
<p>{report.get('company_name', '-')} ({result.get('stock_code', '-')}) ·
生成时间: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
<div class="box"><span class="score">综合评分 {score:.2f}</span> ·
<span class="advice">投资建议: {label}</span></div>
<h2>一、消息面(情感分析)</h2><div class="box">{senti_html}</div>
<h2>二、技术面</h2><div class="box">{tech_analysis}</div>
<h2>三、风险评估</h2><div class="box">{risk_html}</div>
<h2>四、基本面(RAG 财报知识库)</h2><div class="box"><ul>{sources_html}</ul></div>
<h2>五、完整报告</h2><div class="box">{report.get('report', '无')}</div>
<h2>六、相关新闻</h2><ul>{news_html}</ul>
<small>本报告由多智能体系统自动生成,仅供学习与技术演示,不构成投资建议。</small>
</body></html>"""
