"""
顶部状态栏组件(v4.0/4.1,declare_component 双向)

顶部 HUD(游戏化):
- 左: 🔍 全局搜索(Ctrl+K) + 实时时钟(秒跳动冒号 + 日期)
- 右: 后端状态灯 · 数据源雷达环+文案 · 主题切换(🌙/☀️) · 赛博朋克开关(⚡)
-     通知铃铛(未读抖动) · 用户头像(悬停下拉: 信息 + 退出登录)

事件(由 app.py 消费并做 _handled 防重):
  open_search / toggle_theme / toggle_cyberpunk / logout
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


def render_topbar(pal: dict, username: str, role: str, data_source: str,
                  backend_ok: bool = True, theme: str = "dark",
                  cyberpunk: bool = False, bell_new: bool = False) -> dict | None:
    """渲染顶部状态栏并返回事件;无事件返回 None。"""
    src_text, src_key, _ = SOURCE_META.get(data_source, (data_source, "muted", ""))
    src_color = pal.get(src_key, pal["muted"])
    args = dict(
        username=username,
        initial=(username[:1] or "?").upper(),
        role_txt="👑 管理员" if role == "admin" else "👤 普通用户",
        src_text=src_text,
        src_color=src_color,
        backend_ok=bool(backend_ok),
        theme=theme,
        cyberpunk=bool(cyberpunk),
        bell=bool(bell_new),
        fg=pal["fg"],
        muted=pal["muted"],
        accent=pal["accent"],
        purple=pal.get("purple", "#b45cff"),
        ok=pal["ok"],
        danger=pal["danger"],
        card="rgba(16,22,36,.72)",
    )
    return _COMP(**args, default=None)
