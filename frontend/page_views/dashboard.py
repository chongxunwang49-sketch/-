"""
驾驶舱页(v4.0 步骤4)

- 市场指数行情条:横向滚动 marquee + 涨跌数字闪烁(红涨绿跌)
- 自选股列表:玻璃卡片行 + 悬停背景流动 + 涨跌幅 + 「深度研究」跳转
- 撒花彩蛋:某只自选股涨幅 >= 5% 时,该股触发一次五彩纸屑庆祝(会话内只一次)
"""
from __future__ import annotations

import streamlit as st
import streamlit.components.v1 as components

from api_client import ApiError, watchlist_add, watchlist_list
from components.ui import wow
from data_layer import cached_indices
from stock_map import COMMON_STOCKS, lookup_name


def _index_card(pal: dict, name: str, price, pct) -> str:
    if price is None:
        val, pct_cls, pct_txt = "—", "tc-muted", "暂无数据"
    else:
        pct = pct if pct is not None else 0.0
        val = f"{price:,.2f}"
        pct_cls = "tc-up" if pct >= 0 else "tc-down"
        pct_txt = f"{'+' if pct >= 0 else ''}{pct:.2f}%"
    blink = " tc-blink" if pct is not None else ""
    return f"""
    <div class="tc-card" style="flex:0 0 auto;min-width:132px;text-align:center;padding:12px 10px;margin-bottom:0;">
      <div class="tc-label">{name}</div>
      <div class="tc-value" style="font-size:20px;">{val}</div>
      <div class="tc-sub {pct_cls}{blink}" style="font-size:13px;font-weight:700;">{pct_txt}</div>
    </div>"""


def _render_index_marquee(pal: dict):
    try:
        idx = cached_indices()
    except ApiError:
        idx = {"items": [], "source": "no_data"}
    items = idx.get("items") or []
    if not items:
        st.info("指数行情暂不可用(后端未启动或数据源不可达)。")
        return
    cards = "".join(_index_card(pal, i["name"], i.get("price"), i.get("pct")) for i in items)
    # 复制一份实现无缝循环滚动
    st.markdown(f"""
    <div style="overflow:hidden;border-radius:14px;margin-bottom:4px;">
      <div class="tc-marquee">{cards}{cards}</div>
    </div>""", unsafe_allow_html=True)
    _src = {"real": "实时(东财)", "backup": "日线(新浪兜底)", "no_data": "暂不可用"}.get(
        idx.get("source"), "暂不可用")
    st.caption(f"指数数据源:{_src} · 更新于 {idx.get('updated_at', '-')} · 悬停暂停滚动")


def render(pal: dict):
    st.markdown(f'<div class="tc-enter" style="font-size:18px;font-weight:800;color:{pal["fg"]};">📊 驾驶舱</div>',
                unsafe_allow_html=True)

    # ---- 指数行情条(marquee) ----
    _render_index_marquee(pal)

    st.markdown("---")

    # ---- 自选股列表(玻璃卡片 + 跳转 + 撒花) ----
    st.markdown(f'<div style="font-size:16px;font-weight:700;color:{pal["fg"]};">⭐ 我的自选股</div>',
                unsafe_allow_html=True)
    token = st.session_state.token
    try:
        wl = watchlist_list(token) or {"items": []}
    except ApiError as e:
        st.warning(f"自选股加载失败: {e}")
        wl = {"items": []}
    rows = wl.get("items") or []

    if rows:
        celebrated = None
        for r in rows:
            code, name = r["stock_code"], r.get("stock_name") or lookup_name(r["stock_code"])
            price = r.get("price")
            pct = r.get("pct_change")
            if pct is None:
                sig, pct_txt, cls = "⚪ 中性", "—", "tc-muted"
            else:
                pct_txt = f"{'+' if pct >= 0 else ''}{pct:.2f}%"
                if pct >= 0:
                    sig, cls = "🟢 偏多", "tc-up"
                else:
                    sig, cls = "🔴 偏空", "tc-down"
                # 撒花彩蛋:涨幅 >= 5% 且本会话未庆祝过
                if pct >= 5 and not st.session_state.get(f"_celebrated_{code}"):
                    celebrated = celebrated or (code, name, pct)
            price_txt = f"{price:,.2f}" if price is not None else "—"

            c1, c2 = st.columns([4.4, 1])
            with c1:
                st.markdown(f"""
                <div class="wl-row tc-card" style="padding:10px 16px;margin-bottom:6px;">
                  <div style="display:flex;align-items:center;justify-content:space-between;gap:14px;flex-wrap:wrap;">
                    <div style="display:flex;align-items:center;gap:12px;">
                      <span style="font-size:16px;font-weight:800;color:{pal['fg']};">{name}</span>
                      <span style="font-size:11px;color:{pal['muted']};">{code}</span>
                    </div>
                    <div style="display:flex;align-items:baseline;gap:16px;">
                      <span style="font-size:18px;font-weight:700;color:{pal['fg']};">{price_txt}</span>
                      <span class="{cls}" style="font-size:14px;font-weight:700;">{pct_txt}</span>
                      <span style="font-size:12px;">{sig}</span>
                    </div>
                  </div>
                </div>""", unsafe_allow_html=True)
            with c2:
                if st.button("📈 深度研究", key=f"dash_deep_{code}", use_container_width=True):
                    st.session_state.code = code
                    st.session_state["page"] = "deep"
                    st.rerun()

        # 撒花彩蛋(触发一次)
        if celebrated:
            code, name, pct = celebrated
            st.session_state[f"_celebrated_{code}"] = True
            components.html(
                wow.confetti_html(f"🎉 {name} 今日上涨 +{pct:.1f}% 超过 5%,撒花庆祝!", height=150),
                height=150)
            st.toast(f"{name} 涨幅超过 5%,撒花! 🎉", icon="🎊")

        st.caption("信号说明:🟢 上涨(偏多) / 🔴 下跌(偏空) / ⚪ 无数据 · 悬停行有流动高亮 · 完整技术信号见「深度研究」")
    else:
        st.info("自选股为空。前往「⭐ 星标自选」页添加,或点击下方快速添加。")

    # 快速添加
    st.markdown("#### 快速添加自选股")
    c1, c2 = st.columns([2, 1])
    options = ["手动输入"] + [f"{c} · {n}" for c, n in COMMON_STOCKS]
    pick = c1.selectbox("选择标的", options, key="dash_watch_pick")
    code = ""
    if pick != "手动输入":
        code = pick.split(" · ")[0]
    else:
        code = c1.text_input("股票代码", key="dash_watch_code").strip()
    if c2.button("➕ 添加", use_container_width=True):
        code = code or (pick.split(" · ")[0] if pick != "手动输入" else "")
        if code:
            try:
                watchlist_add(token, code)
                st.toast(f"已添加 {lookup_name(code)}", icon="⭐")
                st.rerun()
            except ApiError as e:
                st.toast(f"添加失败: {e}", icon="❌")
        else:
            st.toast("请输入股票代码", icon="⚠️")

    st.markdown("---")
    st.markdown(f"""
    <div class="tc-card" style="border-left:3px solid {pal['warning']};">
      <div style="font-size:14px;font-weight:700;color:{pal['fg']};">📌 市场热点 / 涨幅榜</div>
      <div style="font-size:12px;color:{pal['muted']};">自选股涨幅超过 5% 会触发撒花彩蛋;完整分析见「深度研究」。</div>
    </div>""", unsafe_allow_html=True)
