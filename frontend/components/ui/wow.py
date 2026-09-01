"""
v4.0 趣味动效组件库(wow)

每个函数返回一段自包含 HTML+CSS+JS,交给 st.components.v1.html(iframe)承载。
原则: 纯 CSS/内联 JS 实现,零外部依赖;Canvas 粒子/滚数/打字机均手写。

- confetti_html  : 撒花彩蛋(canvas 五彩纸屑 + 庆祝横幅)
- countup_html   : 数字计速器(requestAnimationFrame 翻滚到目标)
- typewriter_html: 打字机效果(逐字打印)
- liquid_html    : 液位波动图(SVG 波浪填充)
"""
from __future__ import annotations

from .js_lib import ELASTIC


def confetti_html(message: str, colors: list[str] | None = None,
                  height: int = 150) -> str:
    """撒花彩蛋:canvas 五彩纸屑从顶部洒落 + 底部庆祝横幅。

    只播一次即可,由调用方用 session 标志控制是否渲染。
    """
    cols = colors or ["#4f8cff", "#b45cff", "#ff5b4d", "#f0b90b", "#2eb872", "#e040fb"]
    color_arr = "[" + ",".join(f"'{c}'" for c in cols) + "]"
    return f"""
<div style="position:relative;height:{height}px;border-radius:14px;overflow:hidden;
            background:linear-gradient(120deg,rgba(79,140,255,.10),rgba(180,92,255,.12));
            border:1px solid rgba(79,140,255,.25);">
  <canvas id="cf-canvas" style="position:absolute;inset:0;width:100%;height:100%;"></canvas>
  <div style="position:absolute;left:0;right:0;bottom:10px;text-align:center;">
    <span style="font-size:20px;font-weight:800;
                 background:linear-gradient(90deg,#4f8cff,#b45cff);
                 -webkit-background-clip:text;-webkit-text-fill-color:transparent;
                 filter:drop-shadow(0 2px 10px rgba(124,92,255,.4));">{message}</span>
  </div>
</div>
<script>
(function(){{
  var c = document.getElementById('cf-canvas'), x = c.getContext('2d');
  var W = c.width = c.offsetWidth, H = c.height = c.offsetHeight;
  var COLORS = {color_arr};
  var P = [];
  for (var i = 0; i < 160; i++) {{
    P.push({{
      x: Math.random()*W, y: Math.random()*-H*0.5,
      w: 5+Math.random()*6, h: 8+Math.random()*8,
      c: COLORS[Math.floor(Math.random()*COLORS.length)],
      vy: 2+Math.random()*3.4, vx: (Math.random()-0.5)*2.4,
      rot: Math.random()*Math.PI, vr: (Math.random()-0.5)*0.3,
    }});
  }}
  var t0 = performance.now();
  function frame(t) {{
    x.clearRect(0,0,W,H);
    var dead = true;
    for (var i = 0; i < P.length; i++) {{
      var p = P[i];
      p.y += p.vy; p.x += p.vx; p.rot += p.vr; p.vx *= 0.995;
      if (p.y > H) {{ if (t - t0 < 1800) {{ p.y = -20; p.x = Math.random()*W; }} }}
      if (p.y < H) {{
        dead = false;
        x.save(); x.translate(p.x, p.y); x.rotate(p.rot);
        x.fillStyle = p.c; x.fillRect(-p.w/2, -p.h/2, p.w, p.h); x.restore();
      }}
    }}
    if (dead && t - t0 > 800) return;
    requestAnimationFrame(frame);
  }}
  requestAnimationFrame(frame);
}})();
</script>"""


def countup_html(value: float, decimals: int = 2, duration: int = 900,
                 font_size: str = "30px", color: str = "#e8edf6",
                 el_id: str = "cu") -> str:
    """数字计速器:从 0 翻滚到目标值(带弹性收尾)。

    注意:同一 iframe 渲染多个 countup 时必须传不同 el_id,否则 id 冲突
    (getElementById 只命中第一个,后渲染的会覆盖先前的显示)。
    """
    return f"""
<div style="font-size:{font_size};font-weight:800;font-variant-numeric:tabular-nums;
            color:{color};text-shadow:0 0 14px rgba(79,140,255,.4);" id="{el_id}">0</div>
<script>
(function(){{
  var el = document.getElementById('{el_id}');
  var target = {value}, dec = {decimals}, dur = {duration};
  var t0 = null;
  function fmt(v){{
    return v.toLocaleString('zh-CN', {{minimumFractionDigits:dec, maximumFractionDigits:dec}});
  }}
  function step(t){{
    if (t0 === null) t0 = t;
    var p = Math.min(1, (t - t0) / dur);
    // ease-out 缓动
    var e = 1 - Math.pow(1 - p, 3);
    el.textContent = fmt(target * e);
    if (p < 1) requestAnimationFrame(step);
  }}
  requestAnimationFrame(step);
}})();
</script>"""


def typewriter_html(text: str, height: int = 0, speed: int = 28,
                    head_rotate: bool = True) -> str:
    """打字机效果:AI 回复逐字打印 + 全息头像旋转(可选)"""
    import json
    text_json = json.dumps(text, ensure_ascii=False)
    return f"""
<style>
  .tw {{ display:flex; gap:10px; align-items:flex-start; }}
  .tw-head {{ flex:0 0 34px; width:34px; height:34px; border-radius:50%;
              display:flex; align-items:center; justify-content:center; font-size:15px;
              background:linear-gradient(135deg,#4f8cff,#b45cff);
              box-shadow:0 0 14px rgba(124,92,255,.55);
              {'animation:tw-spin 3s linear infinite;' if head_rotate else ''} }}
  @keyframes tw-spin {{ to {{ transform:rotate(360deg); }} }}
  .tw-body {{ color:#e8edf6; font-size:14px; line-height:1.7;
             background:rgba(30,38,58,.6); border:1px solid rgba(79,140,255,.22);
             border-radius:12px; padding:10px 14px; white-space:pre-wrap; word-break:break-word; }}
  .tw-cursor {{ display:inline-block; width:8px; height:15px; background:#4f8cff;
                vertical-align:-2px; animation:tw-blink .6s steps(1) infinite; }}
  @keyframes tw-blink {{ 50% {{ opacity:0; }} }}
</style>
<div class="tw" style="min-height:{height}px;">
  <div class="tw-head">🌀</div>
  <div class="tw-body"><span id="twtext"></span><span class="tw-cursor" id="twcur"></span></div>
</div>
<script>
(function(){{
  var txt = {text_json};
  var el = document.getElementById('twtext');
  var cur = document.getElementById('twcur');
  var i = 0, speed = {speed};
  (function type(){{
    if (i <= txt.length) {{
      el.textContent = txt.slice(0, i);
      i++;
      setTimeout(type, speed);
    }} else {{
      cur.style.display = 'none';
    }}
  }})();
}})();
</script>"""


def liquid_html(items: list[dict], pal: dict, height: int = 150) -> str:
    """液位波动图:SVG 波浪填充(SVG 200% 宽平移 + Y 向呼吸)。

    items: [{label, percent(0-100), sub, color}]
    """
    from .js_lib import json_embed
    tiles = []
    for i, it in enumerate(items):
        pct = max(0.0, min(100.0, float(it.get("percent", 0))))
        color = it.get("color", pal["accent"])
        tiles.append(f"""
        <div style="flex:1;min-width:120px;position:relative;height:{height}px;border-radius:12px;overflow:hidden;
                    background:{pal['card2']};border:1px solid {pal['border']};">
          <div style="position:absolute;left:0;right:0;bottom:0;height:200%;pointer-events:none;">
            <svg width="200%" height="100%" viewBox="0 0 400 100" preserveAspectRatio="none"
                 style="display:block;animation:tc-wave-x 6s linear infinite, tc-wave-y 4.5s ease-in-out infinite;">
              <path d="M0,60 C50,40 100,75 150,60 S250,40 300,60 S400,45 400,60 L400,100 L0,100 Z"
                    fill="{color}" opacity="0.55"/>
              <path d="M0,70 C50,52 100,82 150,70 S250,52 300,70 S400,56 400,70 L400,100 L0,100 Z"
                    fill="{color}" opacity="0.8"/>
            </svg>
          </div>
          <div style="position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;">
            <div style="font-size:26px;font-weight:800;color:{pal['fg']};text-shadow:0 0 10px {_rgba(color,.5)};">{pct:.0f}%</div>
            <div style="font-size:12px;color:{pal['muted']};">{it.get('label','')}</div>
            <div style="font-size:10px;color:{pal['muted']};">{it.get('sub','')}</div>
          </div>
        </div>""")
    return f"""
<style>
  @keyframes tc-wave-x {{ from {{ transform:translateX(0); }} to {{ transform:translateX(-50%); }} }}
  @keyframes tc-wave-y {{ 0%{{ transform:translateY(0) scale(1); }} 50%{{ transform:translateY(-6%) scale(1.03); }} 100%{{ transform:translateY(0) scale(1); }} }}
</style>
<div style="display:flex;gap:10px;flex-wrap:wrap;">{''.join(tiles)}</div>"""


def _rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    return f"rgba({int(h[0:2], 16)},{int(h[2:4], 16)},{int(h[4:6], 16)},{alpha})"
