"""
主题系统(v4.0 UI 全面改造)

- 暗色(默认,专业金融终端) / 亮色 两套配色 + 赛博朋克模式,侧边栏可切换
- apply_theme():注入全局 CSS ——
    玻璃拟态卡片 + 霓虹蓝紫渐变 + 弹性缓动 cubic-bezier(0.34,1.56,0.64,1)
    + 悬停上浮 + 点击涟漪 + 页面入场 + Tab 横向滑动 + 指数 marquee
    + 呼吸灯/骨架屏 + 环形进度/液位关键帧 + 赛博朋克故障风
- get_palette():返回当前配色字典,供图表与 HTML 卡片使用
- card_html():玻璃态指标卡片 HTML

说明:Streamlit 原生控件底色由 .streamlit/config.toml 决定(dark),
运行时切换主题主要作用于自定义 HTML 卡片、Plotly 图表与原生控件表面覆盖。
"""
from __future__ import annotations

import streamlit as st

# "QQ弹弹"弹性贝塞尔(v4.0 全局动效标准,供所有 CSS 过渡/动画使用)
ELASTIC = "cubic-bezier(0.34, 1.56, 0.64, 1)"

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
        "purple": "#b45cff",      # 霓虹紫(渐变用)
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
        "purple": "#7c3aed",
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


def _rgba(hex_color: str, alpha: float) -> str:
    """#RRGGBB -> rgba(r,g,b,a)(供玻璃态/光晕插值用)"""
    h = hex_color.lstrip("#")
    return f"rgba({int(h[0:2], 16)},{int(h[2:4], 16)},{int(h[4:6], 16)},{alpha})"


def get_palette(theme_name: str) -> dict:
    return PALETTES.get(theme_name, PALETTES["dark"])


def apply_theme(theme_name: str) -> dict:
    """注入 v4.0 主题 CSS,返回配色字典。

    - 暗色直接使用原生深色控件;亮色通过 surface_css 覆盖为浅底深字。
    - 赛博朋克模式(st.session_state.cyberpunk=True)追加故障风样式。
    """
    pal = get_palette(theme_name)
    cyber = bool(st.session_state.get("cyberpunk", False))
    fg, muted, border = pal["fg"], pal["muted"], pal["border"]
    acc, purp = pal["accent"], pal.get("purple", "#b45cff")
    card_rgb = _rgba(pal["card"], 0.82)
    glow = f"0 0 18px {_rgba(acc, .35)}"

    # 亮色模式:原生控件表面覆盖(浅底深字)
    surface_css = ""
    if pal["mode"] == "light":
        surface_css = f"""
    /* ---- 亮色:原生控件跟随页面(浅底深字) ---- */
    [data-testid="stTextInput"] input,
    [data-testid="stNumberInput"] input,
    [data-testid="stDateInput"] input,
    [data-testid="stTextArea"] textarea {{
        background-color: #ffffff !important; color: {fg} !important; border-color: {border} !important;
    }}
    [data-testid="stTextInput"] input::placeholder {{ color: #9aa4b8 !important; }}
    [data-testid="stSelectbox"] [data-baseweb="select"],
    [data-testid="stSelectbox"] [data-baseweb="select"] * {{
        background-color: #ffffff !important; color: {fg} !important; border-color: {border} !important;
    }}
    ul[data-baseweb="menu"] {{ background-color: #ffffff !important; color: {fg} !important; }}
    ul[data-baseweb="menu"] li {{ color: {fg} !important; }}
    ul[data-baseweb="menu"] li[aria-selected="true"], ul[data-baseweb="menu"] li:hover {{
        background-color: #dbe7ff !important;
    }}
    [data-testid="stExpander"] details {{ background-color: #ffffff !important; color: {fg} !important; border-color: {border} !important; }}
    [data-testid="stAlert"], [data-testid="stToast"] {{ background-color: #ffffff !important; color: {fg} !important; }}
    [data-testid="stMetricValue"] {{ color: {fg} !important; }}
    [data-testid="stMetricLabel"] p {{ color: {muted} !important; }}
    [data-testid="stSidebar"] .tc-card {{ background: {card_rgb}; }}
    """

    # v4.1 游戏化 HUD:扫描线(全局固定,轻微)
    scan_css = """
    @keyframes tc-scan { 0% { transform: translateY(-6vh); } 100% { transform: translateY(106vh); } }
    .tc-scanline { position: fixed; left:0; right:0; top:0; height:2px; z-index:998; pointer-events:none;
        background: linear-gradient(90deg, transparent, rgba(79,140,255,.14), transparent);
        animation: tc-scan 9s linear infinite; }"""

    # v4.1 游戏化 HUD:四角括号卡 / 雷达 / 导航图块 / 控制台 / 按钮粒子迸发
    hud_css = f"""
    /* ---- v4.1 游戏化 HUD ---- */
    /* 按钮点击:粒子迸发(科技感) */
    .stButton button::before, .stFormSubmitButton button::before {{
        content:""; position:absolute; inset:0; pointer-events:none; z-index:2;
        background:
            radial-gradient(circle at 25% 30%, rgba(255,255,255,.95) 0 1.5px, transparent 2.5px),
            radial-gradient(circle at 68% 42%, rgba(180,92,255,.95) 0 1.5px, transparent 2.5px),
            radial-gradient(circle at 44% 82%, rgba(79,140,255,.95) 0 1.5px, transparent 2.5px),
            radial-gradient(circle at 88% 18%, rgba(255,255,255,.8) 0 1.5px, transparent 2.5px),
            radial-gradient(circle at 12% 68%, rgba(224,64,251,.9) 0 1.5px, transparent 2.5px),
            radial-gradient(circle at 56% 10%, rgba(79,140,255,.9) 0 1.5px, transparent 2.5px);
        opacity:0; transform:scale(.3);
    }}
    .stButton button:active::before, .stFormSubmitButton button:active::before {{
        animation: tc-spark .5s {ELASTIC};
    }}
    @keyframes tc-spark {{
        0% {{ opacity:1; transform: scale(.3) rotate(0deg); }}
        100% {{ opacity:0; transform: scale(1.8) rotate(45deg); }}
    }}

    /* 四角括号 HUD 卡 */
    .tc-hud {{ position:relative; }}
    .tc-hud::before, .tc-hud::after {{
        content:""; position:absolute; width:16px; height:16px; pointer-events:none;
        border-color:{_rgba(acc,.85)}; border-style:solid; opacity:.9; z-index:5;
    }}
    .tc-hud::before {{ top:5px; left:5px; border-width:2px 0 0 2px; }}
    .tc-hud::after {{ bottom:5px; right:5px; border-width:0 2px 2px 0; }}

    /* 数据源雷达环 */
    @keyframes tc-radar {{
        0% {{ transform: scale(.4); opacity:.85; }}
        100% {{ transform: scale(1.8); opacity:0; }}
    }}
    .tc-radar {{ position:relative; display:inline-block; width:12px; height:12px; }}
    .tc-radar::after {{
        content:""; position:absolute; inset:0; border-radius:50%;
        border:1px solid currentColor; animation:tc-radar 1.8s ease-out infinite;
    }}

    /* 侧边栏导航游戏图块 */
    [data-testid="stSidebar"] [data-testid="stRadio"] [role="radiogroup"] {{
        display:flex; flex-direction:column; gap:6px;
    }}
    [data-testid="stSidebar"] [data-testid="stRadio"] [role="radiogroup"] label {{
        display:flex; align-items:center; width:100%;
        background:{pal['card2']}; border:1px solid {border}; border-radius:11px;
        padding:9px 12px; margin:0; cursor:pointer;
        transition: all .28s {ELASTIC};
    }}
    [data-testid="stSidebar"] [data-testid="stRadio"] [role="radiogroup"] label:hover {{
        transform: translateX(5px);
        border-color: {_rgba(acc,.55)};
        box-shadow: 0 4px 14px {_rgba(acc,.18)};
    }}
    [data-testid="stSidebar"] [data-testid="stRadio"] [role="radiogroup"] label:has(input:checked) {{
        background: linear-gradient(120deg, {_rgba(acc,.20)}, {_rgba(purp,.14)});
        border-color: {acc};
        box-shadow: {glow};
    }}
    [data-testid="stSidebar"] [data-testid="stRadio"] [role="radiogroup"] label:has(input:checked) div:nth-child(2),
    [data-testid="stSidebar"] [data-testid="stRadio"] [role="radiogroup"] label:has(input:checked) span {{
        color: {pal['fg']}; font-weight: 700;
    }}
    /* 不隐藏任何 label 子元素——Streamlit 1.62 中 div:first-child 可能是文字容器,
       display:none 会误藏文字(用户反馈:导航无文字)。保持默认圆点,仅做图块美化 */

    /* 分析控制台(st.expander 玻璃面板) */
    [data-testid="stExpander"] details {{
        background: linear-gradient(120deg, {_rgba(acc,.05)}, {_rgba(purp,.06)}) , {card_rgb};
        border: 1px solid {_rgba(acc,.28)}; border-radius: 16px;
        box-shadow: 0 10px 30px rgba(0,0,0,.22), inset 0 1px 0 rgba(255,255,255,.04);
    }}
    [data-testid="stExpander"] details summary {{
        background: linear-gradient(90deg, {_rgba(acc,.12)}, {_rgba(purp,.08)});
        border-radius: 16px; font-weight: 800; color:{pal['fg']};
        transition: all .3s {ELASTIC};
    }}
    [data-testid="stExpander"] details summary:hover {{ background: linear-gradient(90deg, {_rgba(acc,.2)}, {_rgba(purp,.14)}); }}
    @keyframes tc-console-in {{ from {{ opacity:0; transform:translateY(-8px); }} to {{ opacity:1; transform:translateY(0); }} }}
    [data-testid="stExpander"] details[aria-expanded="true"] > div {{ animation: tc-console-in .3s {ELASTIC}; }}

    {scan_css}
    """

    # 赛博朋克模式追加(霓虹字 + 故障线 + 点阵背景)
    cyber_css = ""
    if cyber:
        cyber_css = f"""
    /* ---- 赛博朋克模式(纯视觉,不影响功能) ---- */
    .stApp {{
        background:
            radial-gradient(rgba(255,255,255,.035) 1px, transparent 1px) 0 0/24px 24px,
            radial-gradient(1200px 600px at 80% -10%, rgba(124,58,237,.18), transparent 60%),
            {pal['bg']} !important;
    }}
    .stApp h1, .stApp h2, .stApp h3, .stApp h4,
    .stApp [data-testid="stSidebar"] div, .stApp .tc-label, .stApp .tc-value {{
        text-shadow: 0 0 8px {_rgba(purp, .6)}, 0 0 22px {_rgba(acc, .45)} !important;
    }}
    [data-testid="stSidebar"] {{ border-right: 1px solid {_rgba(purp, .55)} !important; }}
    .tc-card {{ border-color: {_rgba(purp, .5)} !important; }}
    .stButton button, .stFormSubmitButton button {{
        text-shadow: 0 0 6px rgba(255,255,255,.45);
        background: linear-gradient(120deg, {acc}, {purp}) !important;
        border-color: {_rgba(purp, .8)} !important;
    }}
    /* 故障干扰线(动态噪声条) */
    @keyframes cp-glitch {{
        0%, 88%, 100% {{ opacity: 0; }}
        89% {{ opacity: .5; transform: translateX(0); }}
        92% {{ opacity: .35; transform: translateX(-6px); }}
        95% {{ opacity: .45; transform: translateX(4px); }}
    }}
    .cp-glitch {{
        position: fixed; left: 0; right: 0; z-index: 9999; pointer-events: none;
        height: 3px; background: linear-gradient(90deg, {_rgba(acc,0)}, {acc}, {_rgba(purp,1)}, {_rgba(acc,0)});
        mix-blend-mode: screen;
        animation: cp-glitch 4.2s infinite;
    }}
    """

    css = f"""
    <style>
    .stApp {{ background-color: {pal['bg']}; --ease-spring: {ELASTIC}; }}
    [data-testid="stSidebar"] {{ background-color: {pal['card']}; border-right: 1px solid {border}; }}
    [data-testid="stHeader"] {{ background: transparent; }}
    /* 隐藏 streamlit 原生英文工具栏(右上角 Deploy / ⋮ 菜单 / Running 条),
       其功能由中文顶部状态栏接管;原生 chrome 无法翻译成中文 */
    [data-testid="stToolbar"] {{ display: none !important; }}
    [data-testid="stDecoration"] {{ display: none !important; }}

    /* 滚动条 */
    ::-webkit-scrollbar {{ width: 8px; height: 8px; }}
    ::-webkit-scrollbar-track {{ background: {pal['bg']}; }}
    ::-webkit-scrollbar-thumb {{ background: {pal['border']}; border-radius: 8px; }}
    ::-webkit-scrollbar-thumb:hover {{ background: {acc}; }}

    /* ---- 文本跟随主题 ---- */
    h1, h2, h3, h4, h5, h6, p, li, label, summary {{ color: {fg} !important; }}
    [data-testid="stWidgetLabel"], [data-testid="stWidgetLabel"] * {{ color: {fg} !important; }}
    [data-testid="stRadio"] label, [data-testid="stRadio"] label *,
    [data-testid="stCheckbox"] label, [data-testid="stCheckbox"] label * {{ color: {fg} !important; }}

    /* ---- 页签(Tab):玻璃胶囊 + 横向滑入 ---- */
    .stTabs [data-baseweb="tab-list"] {{ gap: 6px; }}
    .stTabs [data-baseweb="tab"] {{
        background: {pal['card2']}; border: 1px solid {border}; border-radius: 10px 10px 0 0;
        color: {fg}; padding: 7px 18px; transition: transform .3s {ELASTIC}, background .25s;
    }}
    .stTabs [data-baseweb="tab"]:hover {{ transform: translateY(-2px); }}
    .stTabs [aria-selected="true"] {{
        background: linear-gradient(120deg, {acc}, {purp}); color: #fff !important; border-color: {acc};
        box-shadow: {glow};
    }}
    @keyframes tc-tab-slide {{
        from {{ opacity: 0; transform: translateX(28px); }}
        to   {{ opacity: 1; transform: translateX(0); }}
    }}
    .stTabs [role="tabpanel"] {{ animation: tc-tab-slide .32s {ELASTIC}; }}

    /* ---- 通用玻璃态卡片(新拟态融合毛玻璃 + 渐变描边) ---- */
    .tc-card {{
        background: {card_rgb};
        backdrop-filter: blur(10px);
        -webkit-backdrop-filter: blur(10px);
        border: 1px solid {_rgba(acc, .18)};
        border-radius: 14px;
        padding: 14px 18px; margin-bottom: 10px;
        box-shadow: 0 6px 22px rgba(0,0,0,.18), inset 0 1px 0 rgba(255,255,255,.05);
        transition: transform .3s {ELASTIC}, box-shadow .3s, border-color .3s;
    }}
    .tc-card:hover {{
        transform: translateY(-5px) scale(1.02);
        box-shadow: 0 14px 34px rgba(0,0,0,.28), 0 0 18px {_rgba(acc, .22)};
        border-color: {_rgba(acc, .5)};
    }}
    /* 霓虹渐变描边(opt-in,用于标题/重点卡) */
    .tc-grad-border {{
        border: 1px solid transparent;
        background:
            linear-gradient({pal['card']}, {pal['card']}) padding-box,
            linear-gradient(120deg, {_rgba(acc,.9)}, {_rgba(purp,.75)}) border-box;
        box-shadow: 0 0 20px {_rgba(acc, .18)};
    }}
    .tc-glow {{ box-shadow: {glow}; }}
    .tc-label {{ font-size: 12px; color: {muted}; }}
    .tc-value {{ font-size: 22px; font-weight: 700; color: {fg}; }}
    .tc-value.small {{ font-size: 16px; }}
    .tc-sub {{ font-size: 12px; color: {muted}; }}
    .tc-up {{ color: {pal['up']}; }} .tc-down {{ color: {pal['down']}; }}
    .tc-accent {{ color: {acc}; }} .tc-warn {{ color: {pal['warning']}; }}
    .tc-ok {{ color: {pal['ok']}; }} .tc-danger {{ color: {pal['danger']}; }} .tc-muted {{ color: {muted}; }}

    /* ---- 弹性按钮 + 点击涟漪(v4.0) ---- */
    .stButton button, .stFormSubmitButton button {{
        position: relative; overflow: hidden;
        transition: transform .25s {ELASTIC}, box-shadow .25s, filter .25s;
    }}
    .stButton button:hover, .stFormSubmitButton button:hover {{
        transform: translateY(-2px);
        box-shadow: 0 8px 22px {_rgba(acc, .35)};
        filter: brightness(1.06);
    }}
    .stButton button:active, .stFormSubmitButton button:active {{ transform: scale(.95); }}
    .stButton button::after, .stFormSubmitButton button::after {{
        content: ""; position: absolute; inset: 0; pointer-events: none;
        background: radial-gradient(circle at center, rgba(255,255,255,.4), transparent 62%);
        opacity: 0;
    }}
    .stButton button:active::after, .stFormSubmitButton button:active::after {{
        animation: tc-ripple .5s ease-out;
    }}
    @keyframes tc-ripple {{
        0%   {{ opacity: .9; transform: scale(.15); }}
        100% {{ opacity: 0; transform: scale(2.1); }}
    }}

    /* ---- 页面入场(v4.0:淡入 + Y上移20px) ---- */
    @keyframes tc-enter {{
        from {{ opacity: 0; transform: translateY(20px); }}
        to   {{ opacity: 1; transform: translateY(0); }}
    }}
    .tc-enter {{ animation: tc-enter .3s {ELASTIC}; }}

    /* ---- 指数条横向滚动(marquee) ---- */
    @keyframes tc-marquee {{
        0%   {{ transform: translateX(0); }}
        100% {{ transform: translateX(-50%); }}
    }}
    .tc-marquee {{ display: flex; gap: 10px; width: max-content; animation: tc-marquee 30s linear infinite; }}
    .tc-marquee:hover {{ animation-play-state: paused; }}

    /* ---- 涨跌数字闪烁 ---- */
    @keyframes tc-blink {{
        0%, 100% {{ opacity: 1; }}
        50%      {{ opacity: .45; }}
    }}
    .tc-blink {{ animation: tc-blink 1.8s ease-in-out infinite; }}

    /* ---- 流水线呼吸灯(运行中) ---- */
    @keyframes tc-pulse {{
        0%   {{ box-shadow: 0 0 0 0 {_rgba(acc,.45)}; }}
        70%  {{ box-shadow: 0 0 0 9px {_rgba(acc,0)}; }}
        100% {{ box-shadow: 0 0 0 0 {_rgba(acc,0)}; }}
    }}
    .tc-running {{ animation: tc-pulse 1.4s infinite; border-color: {acc}; }}

    /* 呼吸灯(在线/运行态指示灯) */
    @keyframes tc-breathe {{
        0%, 100% {{ opacity: 1; box-shadow: 0 0 6px currentColor; }}
        50%      {{ opacity: .45; box-shadow: 0 0 2px currentColor; }}
    }}
    .tc-breathe {{ animation: tc-breathe 2.2s ease-in-out infinite; }}

    /* ---- 骨架屏 shimmer ---- */
    @keyframes tc-shimmer {{ 0% {{ background-position: -400px 0; }} 100% {{ background-position: 400px 0; }} }}
    .tc-skeleton {{
        height: 200px; border-radius: 12px; margin-bottom: 12px;
        background: linear-gradient(90deg, {pal['card']} 25%, {pal['card2']} 50%, {pal['card']} 75%);
        background-size: 800px 100%; animation: tc-shimmer 1.6s infinite linear;
    }}
    .tc-skeleton.line {{ height: 18px; width: 100%; }}

    /* ---- 环形进度充能(step7:stroke-dashoffset 弹性) ---- */
    .tc-ring circle.ring-bg {{ stroke: {pal['border']}; }}
    .tc-ring circle.ring-val {{
        stroke: url(#tc-ring-grad); stroke-linecap: round;
        transition: stroke-dashoffset 1s {ELASTIC};
    }}

    /* ---- 液位波动(step7:波浪填充) ---- */
    @keyframes tc-wave-x {{ from {{ transform: translateX(0); }} to {{ transform: translateX(-50%); }} }}
    @keyframes tc-wave-y {{ 0% {{ transform: translateY(0) scale(1); }} 50% {{ transform: translateY(-8%) scale(1.04); }} 100% {{ transform: translateY(0) scale(1); }} }}
    .tc-liquid {{ position: relative; overflow: hidden; border-radius: 12px; background: {pal['card2']}; }}
    .tc-liquid .wave {{ position: absolute; left: 0; right: 0; bottom: 0; height: 200%; }}
    .tc-liquid .wave svg {{ display: block; width: 200%; height: 100%; animation: tc-wave-x 7s linear infinite, tc-wave-y 5s ease-in-out infinite; }}

    {hud_css}
    {surface_css}
    {cyber_css}
    </style>
    """
    st.markdown(css, unsafe_allow_html=True)

    # v4.1 扫描线 + 赛博朋克故障干扰线(纯视觉覆盖层)
    st.markdown('<div class="tc-scanline"></div>', unsafe_allow_html=True)
    if cyber:
        st.markdown('<div class="cp-glitch"></div><div class="cp-glitch" style="top:38%;"></div>'
                    '<div class="cp-glitch" style="top:72%;animation-delay:1.3s;"></div>',
                    unsafe_allow_html=True)
    return pal


def card_html(pal: dict, label: str, value: str, sub: str = "",
              value_class: str = "") -> str:
    """生成一张玻璃态指标卡片 HTML(供 st.markdown unsafe 渲染)"""
    return f"""
    <div class="tc-card">
      <div class="tc-label">{label}</div>
      <div class="tc-value {value_class}">{value}</div>
      <div class="tc-sub">{sub}</div>
    </div>"""
