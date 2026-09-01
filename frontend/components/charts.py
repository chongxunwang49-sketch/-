"""
专业图表组件(专业看板升级)

- build_kline_chart : 标准金融 K线图(蜡烛图 + 均线开关 + 成交量副图 + MACD/RSI 副图 + 范围滑块)
- build_sentiment_timeline : 情绪时间线(逐条新闻情感得分折线)
- build_gauge : 环状仪表盘(综合评分/情感得分)
- build_radar : 四维雷达图(消息面/技术面/基本面/风险控制)
- build_score_distribution: 无

配色遵循 A股红涨绿跌;深浅主题由 pal 字典驱动。
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

MA_COLORS = {"ma5": "#f0b90b", "ma10": "#4f8cff", "ma20": "#e040fb", "ma60": "#ff7043"}


def _rgba(hex_color: str, alpha: float) -> str:
    """#RRGGBB -> rgba(r,g,b,alpha)(plotly 5.x 不接受 8 位 HEX,统一转 rgba)"""
    h = hex_color.lstrip("#")
    return f"rgba({int(h[0:2], 16)},{int(h[2:4], 16)},{int(h[4:6], 16)},{alpha})"


def _base_layout(pal: dict, height: int, title: str = "") -> dict:
    return dict(
        template="plotly_dark" if pal["mode"] == "dark" else "plotly_white",
        height=height,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor=pal["card2"],
        font=dict(color=pal["fg"], size=12, family="Segoe UI, Microsoft YaHei, sans-serif"),
        margin=dict(l=10, r=10, t=36 if title else 12, b=14),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, font=dict(size=11)),
    )


def _style_axes(fig: go.Figure, pal: dict, n_rows: int):
    """统一坐标轴样式:网格线/零线/十字光标。

    注意:只有 make_subplots 的图才有 subplot 网格,普通 go.Figure 传 row/col 会报错,
    plotly 5.x 下需分情况处理。
    """
    if fig._grid_ref:  # 有子图网格
        for i in range(1, n_rows + 1):
            fig.update_xaxes(gridcolor=pal["grid"], zeroline=False, row=i, col=1,
                             showspikes=(i == 1), spikemode="across",
                             spikecolor=pal["muted"], spikethickness=1)
            fig.update_yaxes(gridcolor=pal["grid"], zeroline=False, row=i, col=1)
    else:  # 普通单图
        fig.update_xaxes(gridcolor=pal["grid"], zeroline=False, showspikes=True,
                         spikemode="across", spikecolor=pal["muted"], spikethickness=1)
        fig.update_yaxes(gridcolor=pal["grid"], zeroline=False)


def build_kline_chart(df: pd.DataFrame, pal: dict, ma_periods: list[int],
                      secondary: str = "macd", height: int = 600,
                      extra_ma: tuple[int, pd.Series] | None = None) -> go.Figure:
    """标准 K线图。

    df 需含列: date/open/high/low/close/volume/ma5/ma10/ma20/ma60/
               macd_dif/macd_dea/macd_hist/rsi14
    secondary: "macd" | "rsi" | "none"  副图指标
    extra_ma: (周期N, 前端现算的 MA 序列) -> 叠加一条动态均线(v4.0 滑块)
    """
    up, down = pal["up"], pal["down"]
    n_rows = 3 if secondary != "none" else 2
    row_heights = [0.60, 0.22, 0.18] if n_rows == 3 else [0.72, 0.28]

    fig = make_subplots(
        rows=n_rows, cols=1, shared_xaxes=True, vertical_spacing=0.03,
        row_heights=row_heights,
        specs=[[{}], [{}], [{}]][:n_rows],
    )

    # ---- 主图:蜡烛 + 均线 ----
    # 注意:plotly 5.x 的 Candlestick 不支持 hovertemplate,用 hovertext 数组构造悬停(兼容 5/7 两版)
    hover_texts = [
        f"<b>{d}</b><br>开 {o:.2f}<br>高 {h:.2f}<br>低 {l:.2f}<br>收 {c:.2f}<br>量 {v:,.0f}"
        for d, o, h, l, c, v in zip(df["date"], df["open"], df["high"],
                                    df["low"], df["close"], df["volume"])
    ]
    fig.add_trace(go.Candlestick(
        x=df["date"], open=df["open"], high=df["high"], low=df["low"], close=df["close"],
        increasing_line_color=up, increasing_fillcolor=up,
        decreasing_line_color=down, decreasing_fillcolor=down,
        name="K线", showlegend=False, text=hover_texts, hoverinfo="text",
    ), row=1, col=1)

    for w in ma_periods:
        col = f"ma{w}"
        if col in df.columns:
            fig.add_trace(go.Scatter(
                x=df["date"], y=df[col], name=f"MA{w}",
                line=dict(width=1.2, color=MA_COLORS.get(col, "#999999")),
                hovertemplate=f"MA{w}: %{{y:.2f}}<extra></extra>",
            ), row=1, col=1)

    # v4.0:动态 MA 滑块(前端现算的周期均线,青色高亮)
    if extra_ma is not None:
        period, series = extra_ma
        if series is not None:
            fig.add_trace(go.Scatter(
                x=df["date"], y=series, name=f"MA{period}",
                line=dict(width=1.8, color="#00e5ff"),
                hovertemplate=f"MA{period}: %{{y:.2f}}<extra></extra>",
            ), row=1, col=1)

    # ---- 成交量副图(红涨绿跌) ----
    vol_colors = [up if c >= o else down for c, o in zip(df["close"], df["open"])]
    fig.add_trace(go.Bar(
        x=df["date"], y=df["volume"], marker_color=vol_colors, name="成交量",
        showlegend=False, hovertemplate="量 %{y:,.0f}手<extra></extra>",
    ), row=2, col=1)

    # ---- 第三副图:MACD 或 RSI ----
    if secondary == "macd":
        hist_colors = [up if v >= 0 else down for v in df["macd_hist"]]
        fig.add_trace(go.Bar(
            x=df["date"], y=df["macd_hist"], marker_color=hist_colors,
            name="MACD柱", showlegend=False, hovertemplate="柱 %{y:.3f}<extra></extra>",
        ), row=3, col=1)
        fig.add_trace(go.Scatter(x=df["date"], y=df["macd_dif"], name="DIF",
                                 line=dict(width=1, color="#f0b90b"),
                                 hovertemplate="DIF %{y:.3f}<extra></extra>"), row=3, col=1)
        fig.add_trace(go.Scatter(x=df["date"], y=df["macd_dea"], name="DEA",
                                 line=dict(width=1, color=pal["accent"]),
                                 hovertemplate="DEA %{y:.3f}<extra></extra>"), row=3, col=1)
    elif secondary == "rsi":
        fig.add_trace(go.Scatter(x=df["date"], y=df["rsi14"], name="RSI14",
                                 line=dict(width=1.3, color="#e040fb"),
                                 hovertemplate="RSI %{y:.1f}<extra></extra>"), row=3, col=1)
        for band, color in ((70, pal["muted"]), (30, pal["muted"])):
            fig.add_trace(go.Scatter(
                x=df["date"], y=[band] * len(df), mode="lines",
                line=dict(dash="dot", width=0.8, color=color),
                showlegend=False, hoverinfo="skip",
            ), row=3, col=1)

    # ---- 范围滑块(挂最底部副图,控制全图缩放) ----
    fig.update_xaxes(rangeslider_visible=True, rangeslider_thickness=0.04, row=n_rows, col=1)

    _style_axes(fig, pal, n_rows)
    fig.update_layout(**_base_layout(pal, height, title="K线走势"))
    return fig


def build_sentiment_timeline(items: list[dict], overall: float | None,
                             pal: dict, height: int = 280) -> go.Figure:
    """情绪时间线:按发布时间绘制逐条新闻情感得分;overall 为总体均值参考线"""
    xs, ys, titles = [], [], []
    for it in items:
        if it.get("publish_time") and it.get("sentiment_score") is not None:
            xs.append(it["publish_time"])
            ys.append(float(it["sentiment_score"]))
            titles.append(it.get("title", ""))

    fig = go.Figure()
    if xs:
        fig.add_trace(go.Scatter(
            x=xs, y=ys, mode="markers+lines",
            marker=dict(size=10, color=ys, cmin=0, cmax=1,
                        colorscale=[[0.0, pal["down"]], [0.5, "#8a94a6"], [1.0, pal["up"]]],
                        showscale=True, colorbar=dict(thickness=8, len=0.6, x=1.02)),
            text=titles,
            hovertemplate="%{x}<br>情感得分 %{y:.2f}<br>%{text}<extra></extra>",
            name="新闻情绪",
        ))
    # plotly 5.x 的 add_hline 需要子图网格,统一用 add_shape 画参考线
    x0, x1 = (xs[0], xs[-1]) if xs else ("", "")
    fig.add_shape(type="line", xref="x", yref="y", x0=x0, x1=x1, y0=0.5, y1=0.5,
                  line=dict(dash="dot", width=1, color=pal["muted"]), layer="below")
    if overall is not None and xs:
        fig.add_shape(type="line", xref="x", yref="y", x0=x0, x1=x1,
                      y0=overall, y1=overall,
                      line=dict(width=2, color=pal["accent"]), layer="below")
        fig.add_annotation(x=x1, y=overall, text=f"总体均值 {overall:.2f}",
                           showarrow=False, yanchor="bottom", xanchor="right",
                           font=dict(color=pal["accent"], size=11))
    if not xs:
        fig.add_annotation(text="暂无逐条新闻情绪数据(情感 Agent 未返回明细)", showarrow=False,
                           font=dict(color=pal["muted"]))
    fig.update_layout(**_base_layout(pal, height, title="情绪时间线"))
    _style_axes(fig, pal, 1)
    return fig


def _score_color(score: float, pal: dict) -> str:
    if score >= 0.6:
        return pal["up"]
    if score <= 0.4:
        return pal["down"]
    return pal["warning"]


def build_gauge(score: float, pal: dict, title: str = "综合评分", height: int = 230) -> go.Figure:
    """环状仪表盘(0-1)"""
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=max(0.0, min(1.0, score)),
        number=dict(suffix="", font=dict(size=36, color=pal["fg"])),
        title=dict(text=title, font=dict(color=pal["muted"], size=13)),
        gauge=dict(
            axis=dict(range=[0, 1], tickwidth=1, tickcolor=pal["muted"]),
            bar=dict(color=_score_color(score, pal), thickness=0.32),
            bgcolor="rgba(0,0,0,0)",
            steps=[
                dict(range=[0, 0.4], color=_rgba(pal["down"], 0.35)),
                dict(range=[0.4, 0.6], color=_rgba(pal["warning"], 0.35)),
                dict(range=[0.6, 1.0], color=_rgba(pal["up"], 0.35)),
            ],
            threshold=dict(line=dict(color=pal["fg"], width=2), value=score),
        ),
    ))
    fig.update_layout(height=height, margin=dict(l=10, r=10, t=40, b=10),
                      paper_bgcolor="rgba(0,0,0,0)", font=dict(color=pal["fg"]))
    return fig


def build_radar(sentiment: float, technical: float, fundamental: float,
                risk_ctl: float, pal: dict, height: int = 260) -> go.Figure:
    """四维雷达:消息面/技术面/基本面/风险控制(均 0-1)"""
    labels = ["消息面", "技术面", "基本面", "风险控制"]
    vals = [max(0, min(1, v)) for v in (sentiment, technical, fundamental, risk_ctl)]
    fig = go.Figure(go.Scatterpolar(
        r=vals + [vals[0]], theta=labels + [labels[0]],
        fill="toself", line=dict(color=pal["accent"], width=2),
        fillcolor="rgba(79,140,255,0.25)",
        hovertemplate="%{theta}: %{r:.2f}<extra></extra>",
    ))
    fig.update_layout(
        height=height, margin=dict(l=10, r=10, t=10, b=10),
        paper_bgcolor="rgba(0,0,0,0)", font=dict(color=pal["fg"]), showlegend=False,
        polar=dict(radialaxis=dict(visible=True, range=[0, 1], gridcolor=pal["grid"],
                                   tickfont=dict(color=pal["muted"], size=9)),
                   angularaxis=dict(gridcolor=pal["grid"], tickfont=dict(color=pal["fg"]))),
    )
    return fig
