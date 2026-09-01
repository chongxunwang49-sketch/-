"""
画中画进度卡(v4.0 步骤6)

深度研究触发后,分析运行期间显示一张可拖拽的进度卡(类似画中画),方便边聊边看进度。
- 进度条 = 已完成 Agent / 总数;当前运行阶段实时显示
- 卡片可拖拽(pointer events),位置记忆在 iframe 内 localStorage(轮询重挂载不丢)
- 承载: st.components.v1.html(iframe)。在 app.py 轮询分支渲染,保证轮询期间存活
"""
from __future__ import annotations

import streamlit.components.v1 as components

FINISHED = ("completed", "skipped", "failed")


def render(stages: list[dict] | None, overall_status: str, pal: dict) -> None:
    stages = stages or []
    total = max(1, len(stages))
    done = sum(1 for s in stages if s.get("status") in FINISHED)
    current = next((s for s in stages if s.get("status") == "running"), None)
    pct = int(done / total * 100)

    if current:
        stage_txt = f"⏳ {current.get('label', '')}"
    elif overall_status == "completed":
        stage_txt = "✅ 分析完成"
    elif overall_status == "failed":
        stage_txt = "❌ 分析失败"
    else:
        stage_txt = "⏳ 等待调度…"

    bar_color = pal["ok"] if overall_status == "completed" else pal["accent"]
    html = f"""
<div style="position:relative;height:118px;">
  <style>
    .pip {{ position:absolute; left:6px; top:4px; width:268px;
            background:rgba(13,19,32,.92); border:1px solid {_rgba(pal['accent'], .35)};
            border-radius:14px; padding:12px 16px; cursor:grab; z-index:60;
            box-shadow:0 16px 40px rgba(0,0,0,.45); backdrop-filter:blur(14px);
            user-select:none; touch-action:none; }}
    .pip:active {{ cursor:grabbing; }}
    .pip-h {{ display:flex; justify-content:space-between; font-size:13px; font-weight:700; color:{pal['fg']}; }}
    .pip-bar {{ height:8px; border-radius:6px; background:{pal['border']}; margin:10px 0 8px; overflow:hidden; }}
    .pip-fill {{ height:100%; border-radius:6px; background:linear-gradient(90deg,{pal['accent']},{pal.get('purple','#b45cff')});
                transition:width .5s cubic-bezier(.34,1.56,.64,1); }}
    .pip-stage {{ font-size:12px; color:{pal['muted']}; }}
    .pip-tip {{ position:absolute; right:8px; bottom:6px; font-size:9px; color:{pal['muted']}; opacity:.7; }}
  </style>
  <div class="pip" id="pip">
    <div class="pip-h"><span>📌 深度研究</span><b>{pct}%</b></div>
    <div class="pip-bar"><div class="pip-fill" style="width:{pct}%;"></div></div>
    <div class="pip-stage">{stage_txt}</div>
    <div class="pip-tip">拖拽移动</div>
  </div>
</div>
<script>
(function(){{
  var el = document.getElementById('pip');
  var K = 'pip_pos';
  try {{ var saved = JSON.parse(localStorage.getItem(K)); if (saved) {{ el.style.left = saved.x + 'px'; el.style.top = saved.y + 'px'; }} }} catch(e){{}}
  var sx=0, sy=0, ox=0, oy=0, drag=false;
  el.addEventListener('pointerdown', function(e){{
    drag = true; sx = e.clientX; sy = e.clientY;
    ox = el.offsetLeft; oy = el.offsetTop;
    el.setPointerCapture(e.pointerId);
  }});
  el.addEventListener('pointermove', function(e){{
    if (!drag) return;
    el.style.left = Math.max(0, ox + e.clientX - sx) + 'px';
    el.style.top = Math.max(0, oy + e.clientY - sy) + 'px';
  }});
  el.addEventListener('pointerup', function(e){{
    if (!drag) return;
    drag = false;
    try {{ localStorage.setItem(K, JSON.stringify({{x: el.offsetLeft, y: el.offsetTop}})); }} catch(err){{}}
  }});
}})();
</script>
"""
    components.html(html, height=118)


def _rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    return f"rgba({int(h[0:2], 16)},{int(h[2:4], 16)},{int(h[4:6], 16)},{alpha})"
