"""
进度流水线组件(专业看板升级)

- render_pipeline : 水平时间线,展示各 Agent 阶段(等待→进行中→完成/跳过/失败)+ 耗时 + 降级标记
- data_source_light_html : 数据源状态指示灯(主源/备用/Mock/未采集)
"""
from __future__ import annotations

import streamlit as st

from theme import STATUS_COLORS, STATUS_ICONS

# 数据源状态 -> (文案, 颜色, 说明)
SOURCE_META = {
    "real":    ("主源 · AKShare",    "ok",      "东方财富通道"),
    "backup":  ("备用 · 新浪财经",    "warning", "主源不可用已降级"),
    "mock":    ("Mock 模拟数据",      "danger",  "数据采集全面降级"),
    "db":      ("数据库已有数据",     "ok",      "从 PostgreSQL 读取"),
    "no_data": ("未采集",             "muted",   "尚未对该股票运行分析"),
}


def _stage_html(s: dict, pal: dict) -> str:
    label, color = STATUS_LABELS.get(s["status"], ("?", "#888"))
    note = s.get("note") or ""
    elapsed = f"{s['elapsed']:.1f}s" if s.get("elapsed") is not None else "—"
    running = ' tc-running' if s["status"] == "running" else ''
    return f"""
    <div style="flex:1;min-width:118px;border:1px solid {pal['border']};
                border-left:3px solid {color};border-radius:8px;padding:8px 10px;
                background:{pal['card']};{'' if not running else ''}" class="tc-card{running}">
      <div style="font-size:13px;font-weight:600;color:{pal['fg']};">{STATUS_ICONS.get(s['status'],'')} {s['label']}</div>
      <div style="font-size:12px;color:{color};margin-top:2px;">{label}</div>
      <div style="font-size:11px;color:{pal['muted']};">⏱ {elapsed} {note}</div>
    </div>"""


STATUS_LABELS = {
    "waiting": ("等待中", STATUS_COLORS["waiting"]),
    "running": ("进行中", STATUS_COLORS["running"]),
    "completed": ("已完成", STATUS_COLORS["completed"]),
    "skipped": ("已跳过", STATUS_COLORS["skipped"]),
    "failed": ("失败", STATUS_COLORS["failed"]),
}


def render_pipeline(stages: list[dict], overall_status: str, pal: dict):
    """渲染 Agent 流水线水平时间线(各阶段状态/耗时/降级标记)"""
    if not stages:
        st.info("暂无流水线状态")
        return
    html = ['<div style="display:flex;align-items:stretch;gap:8px;flex-wrap:wrap;margin:6px 0;">']
    for i, s in enumerate(stages):
        html.append(_stage_html(s, pal))
        if i < len(stages) - 1:
            html.append(f'<div style="align-self:center;color:{pal["muted"]};">➜</div>')
    html.append('</div>')
    overall = "✅ 分析完成" if overall_status == "completed" else (
        "❌ 分析失败" if overall_status == "failed" else "🔄 分析进行中")
    html.append(f'<div style="color:{pal["muted"]};font-size:12px;margin-top:2px;">{overall}</div>')
    st.markdown("".join(html), unsafe_allow_html=True)


def data_source_light_html(source: str, pal: dict) -> str:
    """数据源状态指示灯(v4.1:带雷达扫描环)"""
    text, color_key, desc = SOURCE_META.get(source, (source, "muted", ""))
    color = pal[color_key]
    return f"""
    <div class="tc-card" style="padding:8px 12px;">
      <div style="display:flex;align-items:center;gap:8px;">
        <span class="tc-radar" style="color:{color};display:inline-block;width:12px;height:12px;">
          <span style="position:absolute;inset:0;width:10px;height:10px;border-radius:50%;background:{color};
                       box-shadow:0 0 8px {color};display:inline-block;"></span>
        </span>
        <span style="font-size:13px;font-weight:600;color:{pal['fg']};">{text}</span>
      </div>
      <div style="font-size:11px;color:{pal['muted']};margin-left:18px;">{desc}</div>
    </div>"""
