"""
主题系统(专业看板升级)

- 暗色(默认,金融终端风格) / 亮色 两套配色,侧边栏可切换
- apply_theme():注入全局 CSS(覆盖 Streamlit 容器背景 + 自定义卡片样式 + 流水线动画)
- get_palette():返回当前配色字典,供图表与 HTML 卡片使用

说明:Streamlit 原生组件底色由 .streamlit/config.toml 决定(dark),
运行时切换主题主要作用于自定义 HTML 卡片与 Plotly 图表(看板主体视觉)。
"""
import streamlit as st

# 配色表:暗色以专业金融终端深蓝黑为基调,A股红涨绿跌
PALETTES = {
    "dark": {
        "mode": "dark",
        "bg": "#0b0e14",          # 页面背景
        "card": "#141a26",        # 卡片背景
        "card2": "#1a2233",       # 次卡片/图内背景
        "border": "#283244",      # 边框
        "fg": "#e8edf6",          # 主文字
        "muted": "#8792a8",       # 次要文字
        "grid": "#20293a",        # 图表网格线
        "up": "#ff5b4d",          # 涨(红)
        "down": "#2eb872",        # 跌(绿)
        "accent": "#4f8cff",      # 强调蓝
        "warning": "#ffb020",     # 警告/降级
        "ok": "#2eb872",
        "danger": "#ff5b4d",
    },
    "light": {
        "mode": "light",
        "bg": "#f5f7fb",
        "card": "#ffffff",
        "card2": "#eef2f9",
        "border": "#d9e0ec",
        "fg": "#1f2a3d",
        "muted": "#7c869c",
        "grid": "#e3e9f3",
        "up": "#d5340f",          # 涨(红)
        "down": "#1a9a6a",        # 跌(绿)
        "accent": "#2f6bff",
        "warning": "#c78a00",
        "ok": "#1a9a6a",
        "danger": "#d5340f",
    },
}

# 阶段状态图标与颜色(流水线)
STATUS_ICONS = {
    "waiting": "⏳", "running": "🔄", "completed": "✅",
    "skipped": "⏭️", "failed": "❌",
}
STATUS_COLORS = {
    "waiting": "#5a6478", "running": "#4f8cff", "completed": "#2eb872",
    "skipped": "#ffb020", "failed": "#ff5b4d",
}


def get_palette(theme_name: str) -> dict:
    return PALETTES.get(theme_name, PALETTES["dark"])


def apply_theme(theme_name: str) -> dict:
    """注入主题 CSS,返回配色字典"""
    pal = get_palette(theme_name)
    css = f"""
    <style>
    .stApp {{ background-color: {pal['bg']}; }}
    [data-testid="stSidebar"] {{ background-color: {pal['card']}; border-right: 1px solid {pal['border']}; }}
    [data-testid="stHeader"] {{ background: transparent; }}
    [data-testid="stSidebar"] * {{ color: {pal['fg']}; }}
    h1, h2, h3, h4, h5, h6, p, span, label, div {{ color: {pal['fg']}; }}
    .stTabs [data-baseweb="tab-list"] {{ gap: 4px; }}
    .stTabs [data-baseweb="tab"] {{
        background: {pal['card2']}; border: 1px solid {pal['border']}; border-radius: 8px 8px 0 0;
        color: {pal['fg']}; padding: 6px 16px;
    }}
    .stTabs [aria-selected="true"] {{ background: {pal['accent']}; color: #fff; border-color: {pal['accent']}; }}

    /* ---- 通用卡片 ---- */
    .tc-card {{
        background: {pal['card']}; border: 1px solid {pal['border']}; border-radius: 12px;
        padding: 14px 18px; margin-bottom: 10px;
    }}
    .tc-label {{ font-size: 12px; color: {pal['muted']}; }}
    .tc-value {{ font-size: 22px; font-weight: 700; color: {pal['fg']}; }}
    .tc-value.small {{ font-size: 16px; }}
    .tc-sub {{ font-size: 12px; color: {pal['muted']}; }}
    .tc-up {{ color: {pal['up']}; }} .tc-down {{ color: {pal['down']}; }}
    .tc-accent {{ color: {pal['accent']}; }} .tc-warn {{ color: {pal['warning']}; }} .tc-ok {{ color: {pal['ok']}; }} .tc-danger {{ color: {pal['danger']}; }} .tc-muted {{ color: {pal['muted']}; }}

    /* ---- 流水线动画(运行中呼吸灯) ---- */
    @keyframes tc-pulse {{
        0%   {{ box-shadow: 0 0 0 0 rgba(79,140,255,.45); }}
        70%  {{ box-shadow: 0 0 0 8px rgba(79,140,255,0); }}
        100% {{ box-shadow: 0 0 0 0 rgba(79,140,255,0); }}
    }}
    .tc-running {{ animation: tc-pulse 1.4s infinite; border-color: {pal['accent']}; }}

    /* ---- 骨架屏 shimmer ---- */
    @keyframes tc-shimmer {{ 0% {{ background-position: -400px 0; }} 100% {{ background-position: 400px 0; }} }}
    .tc-skeleton {{
        height: 200px; border-radius: 12px; margin-bottom: 12px;
        background: linear-gradient(90deg, {pal['card']} 25%, {pal['card2']} 50%, {pal['card']} 75%);
        background-size: 800px 100%; animation: tc-shimmer 1.6s infinite linear;
    }}
    .tc-skeleton.line {{ height: 18px; width: 100%; }}
    </style>
    """
    st.markdown(css, unsafe_allow_html=True)
    return pal


def card_html(pal: dict, label: str, value: str, sub: str = "",
              value_class: str = "") -> str:
    """生成一张指标卡片 HTML(供 st.markdown unsafe 渲染)"""
    return f"""
    <div class="tc-card">
      <div class="tc-label">{label}</div>
      <div class="tc-value {value_class}">{value}</div>
      <div class="tc-sub">{sub}</div>
    </div>"""
