"""
Streamlit 前端(步骤13)

功能:
- 输入股票代码,点击"开始分析"
- SSE 流式接收后端进度,进度条逐个显示 Agent 状态(采集→技术&情感→风险→报告)
- 左侧:Plotly K线图;右侧:最终分析报告(Markdown)

启动前提:后端已运行 `uvicorn backend.main:app --port 8000`
运行本页: `streamlit run frontend/app.py`
"""
import json

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

API_BASE = "http://localhost:8000"

# Agent 节点 -> 前端文案 + 进度顺序
NODE_ORDER = ["collect", "technical", "sentiment", "risk", "report"]
NODE_LABELS = {
    "collect": "📥 采集数据",
    "technical": "📊 技术分析",
    "sentiment": "💬 情感分析",
    "risk": "⚠️ 风险评估",
    "report": "📝 报告生成",
}

st.set_page_config(page_title="多智能体股票分析系统", layout="wide")
st.title("📈 多智能体股票分析系统")
st.caption("数据采集 → 技术 & 情感并行分析 → 风险评估 → 报告生成")

code = st.text_input("股票代码", "600519")

if st.button("🚀 开始分析", type="primary"):
    bar = st.progress(0.0)
    status = st.empty()
    done_nodes: list[str] = []
    report, quotes = None, []

    try:
        # SSE 流式读取后端进度
        with requests.get(f"{API_BASE}/analyze/stream", params={"stock_code": code},
                          stream=True, timeout=600) as resp:
            for line in resp.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data: "):
                    continue
                msg = json.loads(line[6:])
                node = msg.get("node")

                if node == "error":
                    status.error(f"❌ 分析出错:{msg.get('error')}")
                    st.stop()
                if node == "done":
                    report = msg.get("report")
                    quotes = msg.get("quotes") or []
                    bar.progress(1.0)
                    status.success("✅ 分析完成")
                    break
                if node in NODE_ORDER and node not in done_nodes:
                    done_nodes.append(node)
                # 进度 = 已完成节点数 / 总节点数
                bar.progress(len(done_nodes) / len(NODE_ORDER))
                labels = " → ".join(NODE_LABELS[n] for n in done_nodes if n in NODE_LABELS)
                status.info(f"⏳ 正在执行: {labels}")
    except Exception as e:
        status.error(f"❌ 无法连接后端({API_BASE})。请先启动:\nuvicorn backend.main:app --port 8000\n\n{e}")
        st.stop()

    if not report:
        st.warning("未收到分析结果,请检查后端日志")
        st.stop()

    # ---- 展示:K线图(左) + 报告(右) ----
    col_left, col_right = st.columns([3, 2], gap="large")

    with col_left:
        st.subheader("📉 K线走势")
        if quotes:
            df = pd.DataFrame(quotes)
            fig = go.Figure(data=[
                go.Candlestick(
                    x=df["date"],
                    open=df["open"], high=df["high"], low=df["low"], close=df["close"],
                    increasing_line_color="#e74c3c", decreasing_line_color="#27ae60",
                )
            ])
            fig.update_layout(
                xaxis_rangeslider_visible=False,
                height=520,
                margin=dict(l=10, r=10, t=30, b=10),
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.warning("暂无K线数据(行情不足)")

    with col_right:
        st.subheader("📄 分析报告")
        st.markdown(report.get("report", ""))

        meta = report.get("sentiment")
        risk = report.get("risk")
        st.caption(
            f"数据源:{report.get('data_source', '-')} ｜ "
            f"情感:{meta.get('score', '-') if meta else '-'} ｜ "
            f"风险:{risk.get('risk_level', '-') if risk else '-'}"
        )
