"""
v4.0 前端组件公共库(js_lib)

- ELASTIC   : 全局弹性贝塞尔(v4.0 动效标准)
- json_embed: 把数据安全 JSON 序列化后注入 iframe HTML(供组件 JS 读取)
- echarts_loader: 多 CDN 兜底加载 ECharts,成功/失败分别触发回调(失败进入静态降级)

设计原则:唯一真正需要 CDN 的是 ECharts(拓扑图);其余动效全部用纯 CSS / 内联 JS,
零外部依赖,最大程度保证 Docker 部署与离线稳定性。
"""
from __future__ import annotations

import json

ELASTIC = "cubic-bezier(0.34, 1.56, 0.64, 1)"

# ECharts 5.x 多 CDN 兜底(按序尝试,首个成功即用)
_ECHARTS_URLS = [
    "https://cdn.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js",
    "https://unpkg.com/echarts@5.5.1/dist/echarts.min.js",
    "https://cdnjs.cloudflare.com/ajax/libs/echarts/5.5.0/echarts.min.js",
]


def json_embed(key: str, data) -> str:
    """把数据安全嵌入 iframe 的 window 全局变量(防 XSS: 用 json.dumps 转义)"""
    return f"<script>window.{key} = {json.dumps(data, ensure_ascii=False)};</script>"


def echarts_loader(on_ok: str, on_fail: str) -> str:
    """加载 ECharts;window.echarts 就绪后执行 on_ok(),全部 CDN 失败后执行 on_fail()。

    注意 on_ok/on_fail 是 JS 代码字符串(通常是函数名或 IIFE)。
    """
    return f"""
<script>
(function(){{
  var urls = {json.dumps(_ECHARTS_URLS)};
  var i = 0;
  function next(){{
    if (i >= urls.length) {{ try {{ {on_fail}; }} catch(e){{}} return; }}
    var s = document.createElement('script');
    s.src = urls[i++];
    s.onload = function(){{
      try {{ if (window.echarts) {{ {on_ok}; return; }} }} catch(e){{}}
      next();
    }};
    s.onerror = function(){{ s.remove(); next(); }};
    document.head.appendChild(s);
  }}
  next();
}})();
</script>"""


def scoped_style(css: str) -> str:
    """把组件 CSS 包进 <style> 标签(iframe 内独立作用域,不受页面 CSS 干扰)"""
    return f"<style>{css}</style>"
