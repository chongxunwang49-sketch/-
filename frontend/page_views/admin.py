"""
管理后台页(v4.0 步骤7,仅管理员可见)

- 系统监控:指标卡(用户/任务/API/LLM) + 液位波动图(CPU/内存/磁盘,psutil;
  psutil 缺失自动降级为业务指标百分比)
- 数据源管理:手动触发采集 + 调度状态
- 用户管理:列表 + 呼吸灯状态(在线/离线) + 禁用/启用 + 删除
"""
from __future__ import annotations

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

import time

import pandas as pd

from api_client import (ApiError, admin_collect_status, admin_data,
                        admin_data_refresh, admin_delete_user, admin_stats,
                        admin_update_user, admin_users)
from components.ui import wow


def render(pal: dict):
    user = st.session_state.user or {}
    if user.get("role") != "admin":
        st.warning("需要管理员权限才能访问此页面。")
        return

    st.markdown(f'<div class="tc-enter" style="font-size:18px;font-weight:800;color:{pal["fg"]};">⚙️ 管理后台</div>',
                unsafe_allow_html=True)
    token = st.session_state.token

    # ---- 系统监控 ----
    try:
        stats = admin_stats(token)
    except ApiError as e:
        st.error(f"监控数据加载失败: {e}")
        stats = {}
    st.markdown("#### 📊 系统监控")
    if stats:
        c = st.columns(5)
        c[0].metric("用户数", stats.get("users", "-"))
        c[1].metric("分析任务", stats.get("analysis_tasks", "-"))
        c[2].metric("API 调用", stats.get("api_calls", "-"))
        llm = stats.get("llm_stats") or {}
        c[3].metric("LLM 调用", llm.get("calls", 0))
        c[4].metric("Token 消耗", llm.get("total_tokens", 0))

        # 液位波动图:psutil 真实值优先,否则业务指标兜底
        sys = stats.get("sys_stats")
        if sys:
            mem = f"{sys.get('memory_used_gb', 0)}/{sys.get('memory_total_gb', 0)}G"
            items = [
                {"label": "CPU", "percent": sys.get("cpu_percent", 0), "sub": f"核心利用率", "color": pal["accent"]},
                {"label": "内存", "percent": sys.get("memory_percent", 0), "sub": mem, "color": pal.get("purple", "#b45cff")},
                {"label": "磁盘", "percent": sys.get("disk_percent", 0), "sub": "存储使用", "color": pal["warning"]},
            ]
        else:
            api = min(stats.get("api_calls", 0), 1000)
            tok = min((llm or {}).get("total_tokens", 0), 1_000_000)
            tsk = min(stats.get("analysis_tasks", 0), 200)
            items = [
                {"label": "API 调用", "percent": api / 10, "sub": f"{stats.get('api_calls', 0)}/1000", "color": pal["accent"]},
                {"label": "Token 消耗", "percent": tok / 10_000, "sub": f"{tok}/100万", "color": pal.get("purple", "#b45cff")},
                {"label": "分析任务", "percent": tsk / 2, "sub": f"{tsk}/200", "color": pal["warning"]},
            ]
        components.html(wow.liquid_html(items, pal, height=150), height=150)
        if not sys:
            st.caption("psutil 未安装,液位图已降级为业务指标百分比(容器内安装 psutil 后显示真实 CPU/内存)。")

        top = stats.get("api_by_path") or {}
        if top:
            st.caption("TOP API 路径:" + " ｜ ".join(f"{k}×{v}" for k, v in top.items()))

    st.markdown("---")

    # ---- 爬虫数据集(采集进度 + 列表窗口) ----
    st.markdown("#### 🕷 爬虫数据集")
    c1, c2 = st.columns([2, 1])
    c1.markdown(f"调度器:`{stats.get('scheduler', '-')}` (每日 08:30 + 每 6 小时自动采集) · 手动采集走后台线程,实时显示进度")
    if c2.button("🔄 立即采集", use_container_width=True):
        try:
            resp = admin_data_refresh(token)
            if resp.get("ok"):
                st.session_state["collect_running"] = True
                st.rerun()
            else:
                st.toast(resp.get("message", "采集已在进行中"), icon="⏳")
        except ApiError as e:
            st.error(f"启动采集失败: {e}")

    # 采集进度条(轮询 /admin/collect/status)
    if st.session_state.get("collect_running"):
        try:
            cp = admin_collect_status(token)
        except ApiError:
            cp = {}
        running = bool(cp.get("running"))
        total = max(1, int(cp.get("total") or 1))
        cur = int(cp.get("current") or 0)
        pct = min(100, int(cur / total * 100))
        msg = cp.get("message") or "采集进行中"
        st.markdown(f"""
        <div class="prog-wrap tc-card" style="padding:10px 16px;">
          <div class="prog-head"><span>🕷 爬虫采集 · {msg}</span><b style="color:{pal['accent']};">{pct}%</b></div>
          <div class="prog-bar"><div class="prog-fill" style="width:{pct}%"></div></div>
        </div>""", unsafe_allow_html=True)
        if running:
            time.sleep(1.5)
            st.rerun()
        else:
            st.session_state["collect_running"] = False
            st.toast(f"✅ 采集完成: {msg}", icon="🎉")

    # 数据集列表窗口
    try:
        ds = admin_data(token, limit=30)
    except ApiError as e:
        st.warning(f"数据集加载失败: {e}")
        ds = {"prices": [], "news": [], "total_prices": 0, "total_news": 0}
    st.markdown(f"**数据集总量**: 行情 `{ds.get('total_prices', 0)}` 行 · 新闻 `{ds.get('total_news', 0)}` 条(下表显示最近 30)")
    tab_p, tab_n = st.tabs(["📈 行情数据", "📰 新闻数据"])
    with tab_p:
        prices = ds.get("prices") or []
        if prices:
            df_p = pd.DataFrame([{
                "代码": p["stock_code"], "日期": p["date"],
                "开": p["open"], "高": p["high"], "低": p["low"],
                "收": p["close"], "量": p["volume"],
            } for p in prices])
            st.dataframe(df_p, use_container_width=True, hide_index=True)
        else:
            st.info("暂无行情数据,点击上方「立即采集」触发爬虫。")
    with tab_n:
        news = ds.get("news") or []
        if news:
            df_n = pd.DataFrame([{
                "代码": n["stock_code"], "时间": n["publish_time"],
                "标题": n["title"], "来源": n["source"],
            } for n in news])
            st.dataframe(df_n, use_container_width=True, hide_index=True)
        else:
            st.info("暂无新闻数据,点击上方「立即采集」触发爬虫。")

    st.markdown("---")

    # ---- 用户管理 ----
    st.markdown("#### 👥 用户管理")
    try:
        data = admin_users(token)
    except ApiError as e:
        st.error(f"用户列表加载失败: {e}")
        data = {"items": []}
    rows = data.get("items") or []
    if rows:
        st.caption(f"共 {len(rows)} 个用户(状态用呼吸灯表示)")
        for u in rows:
            active = u.get("is_active", True)
            role_badge = "👑" if u["role"] == "admin" else "👤"
            status_color = pal["ok"] if active else pal["danger"]
            status_txt = "在线" if active else "离线"
            c1, c2, c3, c4, c5 = st.columns([2.2, 1.2, 1.4, 0.9, 0.9])
            c1.markdown(
                f"**{u['username']}** {role_badge} "
                f"<span style='color:{pal['muted']};font-size:11px'>(id:{u['id']})</span>",
                unsafe_allow_html=True)
            c2.markdown(f"<span style='font-size:12px;color:{pal['muted']}'>{u.get('email') or '无邮箱'}</span>",
                        unsafe_allow_html=True)
            # 呼吸灯状态
            c3.markdown(
                f"<span style='display:inline-block;width:9px;height:9px;border-radius:50%;background:{status_color};"
                f"color:{status_color};vertical-align:middle;' class='tc-breathe'></span> "
                f"<span style='font-size:12px;color:{pal['muted']}'>{status_txt} · {u.get('created_at', '')[:10]}</span>",
                unsafe_allow_html=True)
            if u["username"] == user.get("username"):
                c4.markdown("—")
                c5.markdown("—")
                continue
            if c4.button("⛔ 禁用" if active else "✅ 启用", key=f"tog_{u['id']}"):
                try:
                    admin_update_user(token, u["id"], is_active=not active)
                    st.rerun()
                except ApiError as e:
                    st.error(f"操作失败: {e}")
            if c5.button("🗑 删除", key=f"del_{u['id']}"):
                try:
                    admin_delete_user(token, u["id"])
                    st.toast(f"已删除用户 {u['username']}", icon="🗑")
                    st.rerun()
                except ApiError as e:
                    st.error(f"删除失败: {e}")
            st.markdown("---")
    else:
        st.info("暂无用户。")
