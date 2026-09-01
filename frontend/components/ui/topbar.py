"""
顶部状态栏组件(v4.0 步骤3:「太空舱式仪表盘」,declare_component 双向)

- 左: 🔍 搜索触发(Ctrl+K)+ 实时时钟(秒跳动冒号 + 日期)
- 右: 数据源状态指示灯(主源/备用/模拟,脉冲光晕) · 通知铃铛(未读抖动)
-     用户头像(悬停弹出个人中心下拉卡)
- 事件: 点击搜索 / Ctrl+K -> 返回 {action:"open_search", heatmap:{...}}(由 app.py 消费)

承载: declare_component(自定义组件,iframe height=52),JS->Python 双向桥。
"""
from __future__ import annotations

import os

import streamlit.components.v1 as components

from components.pipeline import SOURCE_META

_BASE = os.path.dirname(os.path.abspath(__file__))          # .../components/ui
_COMP = components.declare_component(
    "stock_topbar",
    path=os.path.join(_BASE, "..", "static", "topbar", "frontend"),
)


def render_topbar(pal: dict, username: str, role: str,
                  data_source: str, bell_new: bool = False) -> dict | None:
    """渲染顶部状态栏并返回事件(open_search 等);无事件返回 None。

    调用方(app.py)需对返回事件做 _handled 防重处理。
    """
    src_text, src_key, _ = SOURCE_META.get(data_source, (data_source, "muted", ""))
    src_color = pal.get(src_key, pal["muted"])
    args = dict(
        username=username,
        initial=(username[:1] or "?").upper(),
        role_txt="👑 管理员" if role == "admin" else "👤 普通用户",
        src_text=src_text,
        src_color=src_color,
        bell=bool(bell_new),
        fg=pal["fg"],
        muted=pal["muted"],
        accent=pal["accent"],
        purple=pal.get("purple", "#b45cff"),
        danger=pal["danger"],
        card="rgba(16,22,36,.72)",
    )
    return _COMP(**args, default=None)
