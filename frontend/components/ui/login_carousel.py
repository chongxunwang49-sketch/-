"""
登录页品牌轮播组件(v4.0 步骤2)

左侧 60% 品牌价值轮播:4 张 AI 生成的 SVG 概念图(系统架构/功能优势/多智能体协同/使用说明)
+ 自动轮播(3D 翻转过渡)+ 动态进度点 + 标题/Slogan。纯 SVG + 内联 JS,零外部图片。

对外接口: render_html(pal) -> str,交给 st.components.v1.html 承载(iframe)。
"""
from __future__ import annotations

from .js_lib import ELASTIC


def _defs(cid: str) -> str:
    """渐变 + 发光滤镜定义(深蓝紫霓虹)"""
    return f"""
    <defs>
      <linearGradient id="gx-{cid}" x1="0%" y1="0%" x2="100%" y2="100%">
        <stop offset="0%" stop-color="#4f8cff"/><stop offset="100%" stop-color="#b45cff"/>
      </linearGradient>
      <linearGradient id="gx-{cid}-soft" x1="0%" y1="0%" x2="100%" y2="100%">
        <stop offset="0%" stop-color="rgba(79,140,255,.35)"/><stop offset="100%" stop-color="rgba(180,92,255,.35)"/>
      </linearGradient>
      <filter id="glow-{cid}" x="-40%" y="-40%" width="180%" height="180%">
        <feGaussianBlur stdDeviation="6" result="b"/><feMerge>
          <feMergeNode in="b"/><feMergeNode in="SourceGraphic"/>
        </feMerge>
      </filter>
    </defs>"""


def _svg_arch(cid: str) -> str:
    """图1 系统架构:数据采集 -> 多智能体矩阵 -> RAG 知识库(分层立体流程)"""
    return f"""<svg viewBox="0 0 480 320" xmlns="http://www.w3.org/2000/svg" width="100%" height="100%">
{_defs(cid)}
  <!-- 数据采集层 -->
  <rect x="60" y="24" width="360" height="56" rx="12" fill="url(#gx-{cid}-soft)" stroke="url(#gx-{cid})" stroke-width="1.4"/>
  <circle cx="92" cy="52" r="10" fill="url(#gx-{cid})" filter="url(#glow-{cid})"/>
  <text x="112" y="58" fill="#e8edf6" font-size="15" font-weight="600">数据采集层 · 多源行情 / 新闻</text>
  <!-- 多智能体矩阵 -->
  <rect x="60" y="112" width="360" height="80" rx="12" fill="url(#gx-{cid}-soft)" stroke="url(#gx-{cid})" stroke-width="1.4"/>
  <text x="82" y="138" fill="#e8edf6" font-size="15" font-weight="600">多智能体矩阵 · 并行分析</text>
  <circle cx="104" cy="170" r="13" fill="#4f8cff" filter="url(#glow-{cid})"/><text x="104" y="175" fill="#fff" font-size="11" text-anchor="middle">技</text>
  <circle cx="152" cy="170" r="13" fill="#b45cff" filter="url(#glow-{cid})"/><text x="152" y="175" fill="#fff" font-size="11" text-anchor="middle">情</text>
  <circle cx="200" cy="170" r="13" fill="#4f8cff" filter="url(#glow-{cid})"/><text x="200" y="175" fill="#fff" font-size="11" text-anchor="middle">基</text>
  <circle cx="248" cy="170" r="13" fill="#b45cff" filter="url(#glow-{cid})"/><text x="248" y="175" fill="#fff" font-size="11" text-anchor="middle">估</text>
  <circle cx="296" cy="170" r="13" fill="#4f8cff" filter="url(#glow-{cid})"/><text x="296" y="175" fill="#fff" font-size="11" text-anchor="middle">流</text>
  <circle cx="344" cy="170" r="13" fill="#b45cff" filter="url(#glow-{cid})"/><text x="344" y="175" fill="#fff" font-size="11" text-anchor="middle">险</text>
  <circle cx="392" cy="170" r="13" fill="#4f8cff" filter="url(#glow-{cid})"/><text x="392" y="175" fill="#fff" font-size="11" text-anchor="middle">事</text>
  <!-- RAG 知识库 -->
  <rect x="60" y="224" width="360" height="56" rx="12" fill="url(#gx-{cid}-soft)" stroke="url(#gx-{cid})" stroke-width="1.4"/>
  <path d="M400 96 L420 96 L410 108 Z" fill="#4f8cff"/>
  <circle cx="400" cy="96" r="4" fill="#4f8cff" filter="url(#glow-{cid})"/>
  <path d="M400 208 L420 208 L410 220 Z" fill="#b45cff"/>
  <circle cx="400" cy="208" r="4" fill="#b45cff" filter="url(#glow-{cid})"/>
  <text x="82" y="258" fill="#e8edf6" font-size="15" font-weight="600">RAG 财报知识库 · 检索增强</text>
  <text x="360" y="258" fill="#9fb0d8" font-size="12" text-anchor="end">ChromaDB</text>
</svg>"""


def _svg_feats(cid: str) -> str:
    """图2 功能优势:实时行情 / 智能问答 / 深度报告(三张全息悬浮卡)"""
    cards = [
        (34, "实时行情", "K线 / 指标 / 多市场", "#4f8cff"),
        (175, "智能问答", "股小智 · RAG 溯源", "#b45cff"),
        (316, "深度报告", "9-Agent 综合研判", "#6d5cff"),
    ]
    parts = []
    for x, t, s, c in cards:
        parts.append(f"""
        <rect x="{x}" y="60" width="130" height="210" rx="14" fill="rgba(20,26,38,.5)"
              stroke="url(#gx-{cid})" stroke-width="1.3" filter="url(#glow-{cid})"/>
        <rect x="{x}" y="60" width="130" height="46" rx="14" fill="{c}" opacity=".28"/>
        <text x="{x+65}" y="96" fill="#e8edf6" font-size="15" font-weight="700" text-anchor="middle">{t}</text>
        <text x="{x+65}" y="138" fill="#9fb0d8" font-size="12" text-anchor="middle">{s}</text>
        <circle cx="{x+65}" cy="205" r="22" fill="none" stroke="url(#gx-{cid})" stroke-width="2"/>
        <text x="{x+65}" y="212" fill="#b45cff" font-size="18" font-weight="800" text-anchor="middle">✦</text>""")
    return f"""<svg viewBox="0 0 480 320" xmlns="http://www.w3.org/2000/svg" width="100%" height="100%">
{_defs(cid)}
{''.join(parts)}
</svg>"""


def _svg_agents(cid: str) -> str:
    """图3 多智能体协同:中央协调器 + 卫星 Agent + 数据流动光点"""
    hub = """
    <circle cx="240" cy="160" r="46" fill="url(#gx-soft)"/>
    <circle cx="240" cy="160" r="46" fill="none" stroke="url(#gx)" stroke-width="2" filter="url(#glow)"/>
    <circle cx="240" cy="160" r="22" fill="url(#gx)"/>
    <text x="240" y="165" fill="#fff" font-size="14" font-weight="800" text-anchor="middle">协调</text>
    <text x="240" y="222" fill="#9fb0d8" font-size="12" text-anchor="middle">LangGraph 编排</text>"""
    nodes = [(90, 70, "技术"), (390, 70, "情感"), (90, 250, "基本面"), (390, 250, "估值"),
             (60, 160, "资金"), (420, 160, "事件")]
    parts = []
    for i, (x, y, t) in enumerate(nodes):
        color = "#4f8cff" if i % 2 == 0 else "#b45cff"
        parts.append(f"""
        <circle cx="{x}" cy="{y}" r="20" fill="{color}" opacity=".22"/>
        <circle cx="{x}" cy="{y}" r="20" fill="none" stroke="{color}" stroke-width="1.5"/>
        <text x="{x}" y="{y+5}" fill="#e8edf6" font-size="13" font-weight="600" text-anchor="middle">{t}</text>
        <line x1="{240}" y1="{160}" x2="{x}" y2="{y}" stroke="url(#gx)" stroke-width="1.2"
              stroke-dasharray="5 5" opacity=".55"/>
        <circle cx="{(240+x)//2}" cy="{(160+y)//2}" r="4" fill="{color}" filter="url(#glow)"/>""")
    return f"""<svg viewBox="0 0 480 320" xmlns="http://www.w3.org/2000/svg" width="100%" height="100%">
{_defs(cid)}
{hub.replace('url(#gx)', f'url(#gx-{cid})').replace('url(#gx-soft)', f'url(#gx-{cid}-soft)').replace('url(#glow)', f'url(#glow-{cid})')}
{''.join(parts)}
</svg>"""


def _svg_steps(cid: str) -> str:
    """图4 使用说明:输入代码 -> 智能分析 -> 获得报告(1-2-3 步骤)"""
    steps = [
        (80, "1", "输入代码", "600519 等"),
        (240, "2", "智能分析", "9-Agent 并行"),
        (400, "3", "获得报告", "评分+建议"),
    ]
    parts = []
    for x, num, t, s in steps:
        color = "#4f8cff" if num in ("1",) else ("#b45cff" if num == "2" else "#6d5cff")
        parts.append(f"""
        <circle cx="{x}" cy="150" r="44" fill="rgba(20,26,38,.5)" stroke="url(#gx-{cid})" stroke-width="1.6"/>
        <circle cx="{x}" cy="150" r="44" fill="none" stroke="url(#gx-{cid})" stroke-width="1.6" filter="url(#glow-{cid})"/>
        <text x="{x}" y="143" fill="#fff" font-size="30" font-weight="800" text-anchor="middle" filter="url(#glow-{cid})">{num}</text>
        <text x="{x}" y="166" fill="#9fb0d8" font-size="11" text-anchor="middle">步骤</text>
        <text x="{x}" y="238" fill="#e8edf6" font-size="15" font-weight="700" text-anchor="middle">{t}</text>
        <text x="{x}" y="262" fill="#9fb0d8" font-size="12" text-anchor="middle">{s}</text>""")
    arrows = """
    <path d="M132 150 L178 150 M136 143 L178 143" stroke="#b45cff" stroke-width="2.4" opacity=".8" fill="none" stroke-linecap="round"/>
    <path d="M292 150 L338 150 M296 143 L338 143" stroke="#b45cff" stroke-width="2.4" opacity=".8" fill="none" stroke-linecap="round"/>"""
    return f"""<svg viewBox="0 0 480 320" xmlns="http://www.w3.org/2000/svg" width="100%" height="100%">
{_defs(cid)}
{''.join(parts)}
{arrows}
</svg>"""


SLIDES = [
    {"title": "系统架构", "slogan": "数据采集 → 多智能体矩阵 → RAG 知识库", "svg": _svg_arch("s1")},
    {"title": "功能优势", "slogan": "实时行情 · 智能问答 · 深度报告", "svg": _svg_feats("s2")},
    {"title": "多智能体协同", "slogan": "让每一份数据,都有 AI 的深度洞察", "svg": _svg_agents("s3")},
    {"title": "使用说明", "slogan": "输入代码 → 智能分析 → 获得报告", "svg": _svg_steps("s4")},
]


def render_html() -> str:
    """生成轮播组件 HTML(交给 st.components.v1.html 承载)"""
    slides_html = []
    for i, s in enumerate(SLIDES):
        active = " active" if i == 0 else ""
        slides_html.append(f"""
      <div class="slide{active}" data-i="{i}">
        <div class="svg-box">{s['svg']}</div>
        <div class="cap-title">{s['title']}</div>
        <div class="cap-slogan">{s['slogan']}</div>
      </div>""")

    dots = "".join(
        f'<span class="dot{" on" if i == 0 else ""}" data-i="{i}"></span>'
        for i in range(len(SLIDES)))

    return f"""<div class="caro-wrap">
<style>
  .caro-wrap {{ position: relative; width: 100%; padding: 6px 2px; }}
  .caro {{ position: relative; width: 100%; height: 380px; perspective: 1000px; }}
  .slide {{
    position: absolute; inset: 0; text-align: center;
    opacity: 0; transform: rotateY(48deg) scale(.9); pointer-events: none;
    transition: opacity .7s {ELASTIC}, transform .7s {ELASTIC};
  }}
  .slide.active {{ opacity: 1; transform: rotateY(0) scale(1); pointer-events: auto; }}
  .svg-box {{ width: 100%; height: 296px; filter: drop-shadow(0 10px 26px rgba(79,140,255,.25)); }}
  .cap-title {{ font-size: 20px; font-weight: 800; color: #e8edf6; margin-top: 6px;
                text-shadow: 0 0 12px rgba(180,92,255,.55); }}
  .cap-slogan {{ font-size: 13px; color: #9fb0d8; margin-top: 3px; }}
  .dots {{ text-align: center; margin-top: 14px; }}
  .dot {{
    display: inline-block; width: 9px; height: 9px; border-radius: 50%;
    background: #33405c; margin: 0 6px; cursor: pointer;
    transition: all .4s {ELASTIC};
  }}
  .dot.on {{ width: 26px; border-radius: 5px; background: linear-gradient(90deg, #4f8cff, #b45cff);
             box-shadow: 0 0 10px rgba(124,92,255,.7); }}
</style>
  <div class="caro">{''.join(slides_html)}</div>
  <div class="dots">{dots}</div>
<script>
(function(){{
  var n = {len(SLIDES)};
  var idx = 0;
  var slides = document.querySelectorAll('.slide');
  var dots = document.querySelectorAll('.dot');
  function go(k){{
    slides[idx].classList.remove('active'); dots[idx].classList.remove('on');
    idx = (k + n) % n;
    slides[idx].classList.add('active'); dots[idx].classList.add('on');
  }}
  dots.forEach(function(d){{
    d.addEventListener('click', function(){{ go(parseInt(d.getAttribute('data-i'))); }});
  }});
  setInterval(function(){{ go(idx + 1); }}, 4200);
}})();
</script>
</div>"""
