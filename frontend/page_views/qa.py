"""
智能问答页(v4.0 步骤6)「股小智」

- 聊天界面:非对称气泡(用户右·蓝色玻璃 / AI 左·暗色玻璃+全息头环)
- AI 回复打字机效果:最新一条 AI 消息逐字打印(一次性标志防重播,刷新后直出)
- 回答展示 RAG 引用来源
- "深度研究":识别对话中的股票代码,一键转多 Agent 分析;运行期间由 app.py
  轮询分支展示拓扑图 + 画中画进度卡
"""
from __future__ import annotations

import math
import re

import streamlit as st
import streamlit.components.v1 as components

from api_client import ApiError, chat, chat_history, start_analysis, upload_doc
from components.ui import wow
from stock_map import lookup_name


def _ensure_session() -> str:
    if "chat_session" not in st.session_state:
        st.session_state["chat_session"] = "sess_default"
    if "chat_messages" not in st.session_state:
        st.session_state["chat_messages"] = []   # [{role, content, sources}]
    if "_typed" not in st.session_state:
        st.session_state["_typed"] = []
    return st.session_state["chat_session"]


def _load_history(token: str):
    """从后端拉取当前会话历史(仅首次)"""
    if st.session_state.get("_chat_loaded"):
        return
    try:
        data = chat_history(st.session_state["chat_session"], token)
        st.session_state["chat_messages"] = [{"role": m["role"], "content": m["content"]}
                                             for m in data.get("items", [])]
    except ApiError:
        pass
    st.session_state["_chat_loaded"] = True


def _send_message(token: str, message: str):
    try:
        resp = chat(st.session_state["chat_session"], message, token)
        st.session_state["chat_messages"].append({"role": "user", "content": message})
        st.session_state["chat_messages"].append(
            {"role": "assistant", "content": resp.get("answer", ""),
             "sources": resp.get("sources") or []})
    except ApiError as e:
        if e.status_code == 401:
            from auth_ui import logout
            logout()
            st.rerun()
        st.session_state["chat_messages"].append(
            {"role": "assistant", "content": f"❌ 问答失败:{e.message}"})


def _detect_stock_code() -> str | None:
    """从最近对话里找 A股 6 位代码"""
    for m in reversed(st.session_state.get("chat_messages", [])):
        hits = re.findall(r"\b(6\d{5}|0\d{5}|3\d{5})\b", m.get("content", ""))
        if hits:
            return hits[0]
    return None


def _user_bubble(pal: dict, text: str) -> str:
    return f"""
    <div style="display:flex;justify-content:flex-end;margin:10px 0;">
      <div style="max-width:78%;background:linear-gradient(135deg,{pal['accent']},{pal.get('purple', '#b45cff')});
                  color:#fff;border-radius:16px 16px 4px 16px;padding:10px 15px;
                  font-size:14px;line-height:1.7;white-space:pre-wrap;word-break:break-word;
                  box-shadow:0 6px 18px rgba(79,140,255,.25);">{text}</div>
    </div>"""


def _ai_bubble(pal: dict, text: str) -> str:
    return f"""
    <div style="display:flex;justify-content:flex-start;margin:10px 0;gap:10px;">
      <div style="flex:0 0 32px;width:32px;height:32px;border-radius:50%;display:flex;align-items:center;
                  justify-content:center;font-size:14px;
                  background:linear-gradient(135deg,{pal['accent']},{pal.get('purple', '#b45cff')});
                  box-shadow:0 0 12px rgba(124,92,255,.55);">🌀</div>
      <div style="max-width:78%;background:rgba(30,38,58,.55);border:1px solid {_rgba(pal['accent'], .22)};
                  color:{pal['fg']};border-radius:4px 16px 16px 16px;padding:10px 15px;
                  font-size:14px;line-height:1.7;white-space:pre-wrap;word-break:break-word;">{text}</div>
    </div>"""


def _sources_html(pal: dict, sources: list) -> str:
    if not sources:
        return ""
    items = "".join(f"<div style='padding:2px 0;color:{pal['muted']};font-size:12px;'>[知识库{i}] {s[:200]}{'…' if len(s) > 200 else ''}</div>"
                    for i, s in enumerate(sources, 1))
    return f"""
    <div style="display:flex;justify-content:flex-start;margin:0 0 8px 42px;">
      <div style="max-width:78%;background:{pal['card2']};border:1px dashed {pal['border']};
                  border-radius:10px;padding:8px 12px;font-size:12px;color:{pal['muted']};">
        📚 引用来源({len(sources)} 条){items}
      </div>
    </div>"""


def _render_messages(pal: dict):
    msgs = st.session_state.get("chat_messages", [])
    typed = st.session_state.get("_typed", [])
    # 最新一条 assistant 消息下标
    last_ai = None
    for i in range(len(msgs) - 1, -1, -1):
        if msgs[i]["role"] == "assistant":
            last_ai = i
            break

    for i, m in enumerate(msgs):
        if m["role"] == "user":
            st.markdown(_user_bubble(pal, m["content"]), unsafe_allow_html=True)
        else:
            if i == last_ai and i not in typed:
                # 打字机:渲染组件并立即写入一次性标志(防重播)
                st.session_state["_typed"] = typed + [i]
                est_h = min(420, 42 + max(1, math.ceil(len(m["content"]) / 36)) * 26)
                components.html(wow.typewriter_html(m["content"], height=est_h), height=est_h)
                st.markdown(_sources_html(pal, m.get("sources") or []), unsafe_allow_html=True)
            else:
                st.markdown(_ai_bubble(pal, m["content"]), unsafe_allow_html=True)
                st.markdown(_sources_html(pal, m.get("sources") or []), unsafe_allow_html=True)


def render(pal: dict):
    token = st.session_state.token
    session_id = _ensure_session()

    st.markdown(f'<div class="tc-enter" style="font-size:18px;font-weight:800;color:{pal["fg"]};">🤖 股小智 · RAG 智能问答</div>',
                unsafe_allow_html=True)
    st.caption("基于财报知识库(ChromaDB + bge)检索增强,回答引用知识库来源;支持多轮追问。")
    _load_history(token)

    # 会话操作
    c1, c2 = st.columns([3, 1])
    with c2:
        if st.button("🔄 新会话", use_container_width=True):
            st.session_state["chat_session"] = "sess_" + str(len(st.session_state.get("chat_messages", [])))[-6:]
            st.session_state["chat_messages"] = []
            st.session_state["_typed"] = []
            st.session_state["_chat_loaded"] = False
            st.rerun()

    # 消息渲染(非对称气泡 + 打字机)
    _render_messages(pal)

    # 输入
    user_input = st.chat_input("输入问题,如:茅台2024年营收增速是多少?")
    if user_input:
        _send_message(token, user_input)
        st.rerun()

    st.markdown("---")
    # 深度研究
    code = _detect_stock_code() or st.session_state.code
    name = lookup_name(code)
    if st.button(f"🧠 深度研究 {name}({code}):将对话转为多 Agent 分析", use_container_width=True):
        try:
            resp = start_analysis(code, "full", token=token)
            st.session_state.running_task = resp["task_id"]
            st.session_state.code = code
            st.session_state["page"] = "deep"
            st.session_state.analysis_result = None
            st.toast(f"已启动 {name} 深度分析", icon="🧠")
            st.rerun()
        except ApiError as e:
            if e.status_code == 401:
                from auth_ui import logout
                logout()
                st.rerun()
            st.toast(f"启动失败: {e}", icon="❌")

    # 知识库扩充(上传文档)
    with st.expander("📤 扩充知识库(上传 PDF/TXT)"):
        up = st.file_uploader("上传财报/公告/研报文档", type=["pdf", "txt"])
        if up and st.button("入库", key="qa_upload"):
            try:
                resp = upload_doc(up.getvalue(), up.name, token)
                st.toast(f"已入库 {resp.get('chunks', 0)} 个分块: {up.name}", icon="✅")
                st.session_state._chat_loaded = False
                st.rerun()
            except ApiError as e:
                st.error(f"上传失败: {e}")


def _rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    return f"rgba({int(h[0:2], 16)},{int(h[2:4], 16)},{int(h[4:6], 16)},{alpha})"
