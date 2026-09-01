"""
智能问答页(第五批)"股小智"

- 聊天界面:st.chat_message 消息气泡 + st.chat_input 输入
- 多轮对话:会话存于 session_state,并同步后端 chat_history 表
- 回答展示 RAG 引用来源
- "深度研究"按钮:识别聊天中的股票代码,一键触发多 Agent 深度分析
"""
from __future__ import annotations

import re

import streamlit as st

from api_client import ApiError, chat, chat_history, start_analysis, upload_doc
from stock_map import lookup_name


def _ensure_session() -> str:
    if "chat_session" not in st.session_state:
        st.session_state["chat_session"] = "sess_default"
    if "chat_messages" not in st.session_state:
        st.session_state["chat_messages"] = []   # [{role, content, sources}]
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


def render(pal: dict):
    token = st.session_state.token
    session_id = _ensure_session()

    st.markdown(f'<div style="font-size:18px;font-weight:800;color:{pal["fg"]};">🤖 股小智 · RAG 智能问答</div>',
                unsafe_allow_html=True)
    st.caption("基于财报知识库(ChromaDB + bge)检索增强,回答引用知识库来源;支持多轮追问。")
    _load_history(token)

    # 会话操作
    c1, c2 = st.columns([3, 1])
    with c2:
        if st.button("🔄 新会话", use_container_width=True):
            st.session_state["chat_session"] = "sess_" + str(len(st.session_state.get("chat_messages", [])))[-6:]
            st.session_state["chat_messages"] = []
            st.session_state["_chat_loaded"] = False
            st.rerun()

    # 历史消息渲染
    for m in st.session_state.get("chat_messages", []):
        with st.chat_message("user" if m["role"] == "user" else "assistant"):
            st.markdown(m["content"])
            if m.get("sources"):
                with st.expander(f"📚 引用来源({len(m['sources'])} 条)"):
                    for i, s in enumerate(m["sources"], 1):
                        st.markdown(f"`[知识库{i}]` {s[:200]}{'…' if len(s) > 200 else ''}")

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
