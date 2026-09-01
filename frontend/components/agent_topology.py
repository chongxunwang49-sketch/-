"""
Agent 网络拓扑图(v4.0 步骤5,ECharts force graph)

- 节点 = 10 个 Agent,边 = DAG 依赖(与 backend/task_manager.py 同构)
- 节点颜色按 stage 状态(waiting灰/running蓝/completed绿/skipped黄/failed红)
- running 节点尺寸更大 + 呼吸;连线波浪脉冲(模拟数据流动)
- 力导向布局 + 可拖拽(force + draggable + roam);悬停节点出 tooltip(耗时/状态/备注)
- live 模式(轮询中):animationDuration:0 抗重挂载;完成态保留入场
- ECharts CDN 全部失败:降级为静态 SVG 径向拓扑(纯 HTML,无交互)

承载: st.components.v1.html(iframe)。
"""
from __future__ import annotations

import math

import streamlit.components.v1 as components

from .ui.js_lib import echarts_loader, json_embed

NODE_ORDER = ["collect", "technical", "sentiment", "fundamental", "valuation",
              "flow", "industry", "event", "risk", "report"]
NODE_LABELS = {
    "collect": "数据采集", "technical": "技术分析", "sentiment": "情感分析",
    "fundamental": "基本面分析", "valuation": "估值分析", "flow": "资金流向",
    "industry": "行业分析", "event": "事件驱动", "risk": "风险评估", "report": "报告生成",
}
PREDECESSORS = {
    "collect": [], "technical": ["collect"], "sentiment": ["collect"],
    "fundamental": ["collect"], "valuation": ["fundamental"],
    "flow": ["collect"], "industry": ["collect"], "event": ["collect"],
    "risk": ["technical", "sentiment", "valuation", "flow", "industry", "event"],
    "report": ["risk"],
}
STATUS_COLORS = {
    "waiting": "#5a6478", "running": "#4f8cff", "completed": "#2eb872",
    "skipped": "#ffb020", "failed": "#ff5b4d",
}
STATUS_TEXT = {
    "waiting": "等待中", "running": "进行中", "completed": "已完成",
    "skipped": "已跳过", "failed": "失败",
}


def render_topology(stages: list[dict] | None, live: bool = False,
                    height: int = 340) -> None:
    """渲染 Agent 拓扑图。stages: /task/status 返回的阶段列表"""
    status = {s.get("name"): s for s in (stages or [])}

    nodes = []
    for name in NODE_ORDER:
        stg = status.get(name) or {}
        st = stg.get("status", "waiting")
        nodes.append({
            "id": name,
            "name": NODE_LABELS[name],
            "status": st,
            "color": STATUS_COLORS.get(st, "#5a6478"),
            "elapsed": stg.get("elapsed"),
            "note": stg.get("note") or "",
        })

    edges = []
    for succ, deps in PREDECESSORS.items():
        for dep in deps:
            edges.append({"source": dep, "target": succ})

    data = {"nodes": nodes, "edges": edges}
    on_ok = "initChart();"
    on_fail = "renderStatic();"
    html = (
        f'<div id="topo" style="width:100%;height:{height}px;"></div>'
        f'<div id="topoFallback" style="display:none;width:100%;height:{height}px;"></div>'
        + json_embed("__TOPO__", data)
        + echarts_loader(on_ok, on_fail)
        + _chart_js(live)
    )
    components.html(html, height=height)


def _chart_js(live: bool) -> str:
    anim = 0 if live else 600
    return f"""
<script>
var D = window.__TOPO__;
var STATUS_TEXT = {json_embed_js()};
function initChart() {{
  var dom = document.getElementById('topo');
  var chart = echarts.init(dom);
  var data = D.nodes.map(function(n){{
    var size = n.status === 'running' ? 52 : (n.status === 'completed' ? 42 :
              (n.status === 'failed' ? 42 : 34));
    return {{
      id: n.id, name: n.name, symbolSize: size,
      itemStyle: {{ color: n.color, shadowBlur: n.status==='running'?18:6,
                   shadowColor: n.color }},
      label: {{ show: true, fontSize: 12, color: '#e8edf6' }},
      status: n.status, elapsed: n.elapsed, note: n.note,
    }};
  }});
  var edges = D.edges.map(function(e){{
    return {{ source: e.source, target: e.target,
              lineStyle: {{ color: 'rgba(79,140,255,.5)', width: 1.6, curveness: 0.18,
                            opacity: 0.55 }} }};
  }});
  chart.setOption({{
    backgroundColor: 'transparent',
    animationDuration: {anim},
    tooltip: {{
      backgroundColor: 'rgba(13,19,32,.94)', borderColor: 'rgba(79,140,255,.4)',
      textStyle: {{ color: '#e8edf6', fontSize: 12 }},
      formatter: function(p){{
        var n = p.data;
        if (!n || !n.name) return '';
        var st = STATUS_TEXT[n.status] || n.status;
        var el = n.elapsed != null ? n.elapsed.toFixed(1)+'s' : '—';
        return '<b>' + n.name + '</b><br/>状态: ' + st +
               '<br/>耗时: ' + el + (n.note ? '<br/>备注: ' + n.note : '');
      }}
    }},
    series: [{{
      type: 'graph', layout: 'force', draggable: true, roam: true,
      data: data, edges: edges,
      force: {{ repulsion: 260, edgeLength: [80, 150], gravity: 0.08 }},
      emphasis: {{ focus: 'adjacency',
                   itemStyle: {{ shadowBlur: 24, shadowColor: '#4f8cff' }} }},
      lineStyle: {{ color: 'rgba(79,140,255,.45)', width: 1.6, curveness: 0.18 }},
    }}]
  }});

  // 运行节点呼吸 + 连线波浪脉冲(不重算布局)
  setInterval(function(){{
    var t = Date.now() / 180;
    var d2 = data.map(function(n){{
      if (n.status === 'running') {{
        return Object.assign({{}}, n, {{ symbolSize: 52 + 6 * Math.sin(t) }});
      }}
      return n;
    }});
    var e2 = edges.map(function(e, i){{
      return Object.assign({{}}, e, {{
        lineStyle: Object.assign({{}}, e.lineStyle,
          {{ opacity: 0.35 + 0.4 * Math.sin(Date.now()/260 + i*0.9) }})
      }});
    }});
    chart.setOption({{ series: [{{ data: d2, edges: e2 }}] }});
  }}, 200);

  window.addEventListener('resize', function(){{ chart.resize(); }});
}}

function renderStatic() {{
  var dom = document.getElementById('topoFallback');
  dom.style.display = 'block';
  var N = D.nodes.length, R = Math.min(dom.clientWidth, 280) * 0.40;
  var cx = 150, cy = 170;
  var html = '<svg width="100%" height="100%" viewBox="0 0 300 340">';
  D.edges.forEach(function(e){{
    var a = D.nodes.findIndex(function(n){{ return n.id === e.source; }});
    var b = D.nodes.findIndex(function(n){{ return n.id === e.target; }});
    var x1 = cx + R*Math.cos(2*Math.PI*a/N), y1 = cy + R*Math.sin(2*Math.PI*a/N);
    var x2 = cx + R*Math.cos(2*Math.PI*b/N), y2 = cy + R*Math.sin(2*Math.PI*b/N);
    html += '<line x1="'+x1.toFixed(1)+'" y1="'+y1.toFixed(1)+
            '" x2="'+x2.toFixed(1)+'" y2="'+y2.toFixed(1)+
            '" stroke="rgba(79,140,255,.4)" stroke-width="1"/>';
  }});
  D.nodes.forEach(function(n, i){{
    var x = cx + R*Math.cos(2*Math.PI*i/N), y = cy + R*Math.sin(2*Math.PI*i/N);
    html += '<circle cx="'+x.toFixed(1)+'" cy="'+y.toFixed(1)+'" r="20" fill="'+n.color+
            '" fill-opacity=".22" stroke="'+n.color+'" stroke-width="1.5"/>' +
            '<text x="'+x.toFixed(1)+'" y="'+(y+4).toFixed(1)+'" fill="#e8edf6" ' +
            'font-size="11" text-anchor="middle">'+n.name+'</text>';
  }});
  html += '<text x="150" y="320" fill="#8792a8" font-size="11" text-anchor="middle">' +
          '(ECharts CDN 不可用,已降级为静态拓扑)</text></svg>';
  dom.innerHTML = html;
}}
</script>"""


def json_embed_js() -> str:
    import json
    return json.dumps(STATUS_TEXT, ensure_ascii=False)
