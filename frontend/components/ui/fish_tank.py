"""
思维链鱼缸(v4.0 步骤8 彩蛋)

深度分析页底部的侧拉抽屉:打开后是一个动态鱼缸。
- 每条鱼 = 一个 Agent(10 只,与拓扑同构),CSS 游动
- 某个 Agent 运行时,对应的鱼加速游动,并向上吐气泡(气泡内显示该 Agent 短日志/状态)
- 纯 CSS + 内联 JS,零外部依赖;轮询期重挂载可接受(idle 游动即最终形态)

承载: st.components.v1.html(iframe)。由 app.py / deep_analysis.py 条件渲染。
"""
from __future__ import annotations

import streamlit.components.v1 as components

NODE_ORDER = ["collect", "technical", "sentiment", "fundamental", "valuation",
              "flow", "industry", "event", "risk", "report"]
NODE_LABELS = {
    "collect": "数据采集", "technical": "技术分析", "sentiment": "情感分析",
    "fundamental": "基本面分析", "valuation": "估值分析", "flow": "资金流向",
    "industry": "行业分析", "event": "事件驱动", "risk": "风险评估", "report": "报告生成",
}
FISH_COLORS = ["#4f8cff", "#b45cff", "#f0b90b", "#2eb872", "#e040fb",
               "#ff7043", "#26c6da", "#7c4dff", "#ff5b4d", "#66bb6a"]


def render(stages: list[dict] | None, height: int = 230) -> None:
    stages = stages or []
    status = {s.get("name"): s for s in stages}
    running_labels = [NODE_LABELS[n] for n in NODE_ORDER
                      if (status.get(n) or {}).get("status") == "running"]

    fish_html = []
    for i, name in enumerate(NODE_ORDER):
        color = FISH_COLORS[i % len(FISH_COLORS)]
        running = (status.get(name) or {}).get("status") == "running"
        dur = 3.2 if running else (8 + i * 0.7)
        top = 12 + (i % 5) * 30 + (0 if i < 5 else 10)
        # 鱼身(简化 SVG:椭圆体 + 尾鳍),颜色按 Agent 区分
        fish_html.append(f"""
        <div class="fish" style="top:{top}px;animation-duration:{dur}s;opacity:{1 if not running else 1.0};">
          <svg width="34" height="20" viewBox="0 0 34 20">
            <ellipse cx="15" cy="10" rx="12" ry="6.5" fill="{color}" opacity=".92"/>
            <polygon points="26,10 34,3 34,17" fill="{color}" opacity=".7"/>
            <circle cx="10" cy="8" r="1.6" fill="#fff"/>
          </svg>
          <div class="fname">{NODE_LABELS[name][:4]}</div>
        </div>""")

    # 气泡:运行中的 Agent 吐泡(带短日志)
    bubbles = ""
    if running_labels:
        bubbles = "\n".join(
            f'<div class="bubble" style="animation-delay:{i * 0.5}s;left:{12 + i * 17}%;'
            f'">🐟 {label}</div>'
            for i, label in enumerate(running_labels[:6]))

    html = f"""
<style>
  .tank {{ position:relative; height:200px; overflow:hidden; border-radius:14px;
          background:
            linear-gradient(180deg, rgba(79,140,255,.10) 0%, rgba(20,26,38,.35) 60%, rgba(20,26,38,.55) 100%);
          border:1px solid rgba(79,140,255,.25); }}
  .fish {{ position:absolute; animation-name:swim; animation-timing-function:ease-in-out;
          animation-iteration-count:infinite; animation-direction:alternate; }}
  @keyframes swim {{
    from {{ left:-6%; transform:scaleX(1); }}
    to   {{ left:calc(100% - 46px); transform:scaleX(-1); }}
  }}
  .fname {{ font-size:8px; color:rgba(255,255,255,.75); text-align:center; margin-top:-2px;
           text-shadow:0 0 4px rgba(0,0,0,.6); }}
  .bubble {{ position:absolute; bottom:-20px; min-width:74px; text-align:center;
            font-size:10px; color:#dbe7ff; background:rgba(13,19,32,.82);
            border:1px solid rgba(79,140,255,.4); border-radius:12px; padding:3px 7px;
            animation:rise 3.2s ease-in infinite; opacity:0; }}
  @keyframes rise {{
    0%   {{ transform:translateY(0); opacity:0; }}
    12%  {{ opacity:.95; }}
    100% {{ transform:translateY(-190px); opacity:0; }}
  }}
  .tank-tip {{ position:absolute; right:10px; bottom:6px; font-size:10px; color:rgba(255,255,255,.45); }}
</style>
<div class="tank">
  {''.join(fish_html)}
  {bubbles}
  <div class="tank-tip">{'🧠 思维链可视化:运行中的 Agent 加速游动并吐泡' if running_labels else '🧠 思维链鱼缸 · 启动分析后 Agent 会加速游动'}</div>
</div>
"""
    components.html(html, height=height)
