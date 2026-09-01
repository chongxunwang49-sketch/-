"""
RAG 智能问答"股小智"(第五批)

- answer_question:检索知识库(ChromaDB)+ 组装多轮上下文 -> LLM 回答(强制引用来源)
- 多轮对话:读取最近 N 轮历史拼入上下文
- ingest_document:把用户上传的 PDF/TXT 文本分块写入知识库(扩充语料)
- list_history:拉取某会话的完整对话
降级:知识库无内容时 LLM 诚实说明并常识作答;LLM 失败返回友好提示。
"""
import logging
import uuid
from typing import List, Optional

from sqlalchemy import select

from ..agents.llm import LLMClient, LLMError
from ..models import ChatHistory, SessionLocal

logger = logging.getLogger(__name__)

QA_SYSTEM_PROMPT = """你是一位专业的股票投资问答助手"股小智"。请基于提供的知识库内容回答用户问题。

要求:
1. 只依据知识库内容回答,严禁编造数据。
2. 回答末尾列出引用来源,格式:【来源:知识库第N条】
3. 若知识库无法回答,明确说"知识库暂无相关信息",可结合常识谨慎作答但不杜撰。
4. 回答不超过 250 字,不构成投资建议。"""

CHUNK_SIZE = 500
CHUNK_OVERLAP = 50


def _retrieve(query: str, top_k: int = 3) -> List[str]:
    try:
        from .vector_store import retrieve
        result = retrieve(query, top_k=top_k)
        return [d for d in (result.get("documents", [[]])[0]) if d][:top_k]
    except Exception as e:
        logger.warning("[qa] 知识库检索不可用: %s", e)
        return []


def _save_msg(user_id: int, session_id: str, role: str, content: str) -> None:
    with SessionLocal() as session:
        session.add(ChatHistory(user_id=user_id, session_id=session_id, role=role, content=content))
        session.commit()


def _recent_history(user_id: int, session_id: str, limit: int = 6) -> str:
    with SessionLocal() as session:
        rows = session.scalars(
            select(ChatHistory)
            .where(ChatHistory.user_id == user_id, ChatHistory.session_id == session_id)
            .order_by(ChatHistory.created_at.desc()).limit(limit)
        ).all()
    rows = list(reversed(rows))
    return "\n".join(f"{'用户' if r.role == 'user' else '助手'}: {r.content[:200]}" for r in rows)


def answer_question(user_id: int, session_id: str, message: str,
                    client: Optional[LLMClient] = None) -> dict:
    """回答用户问题并落库,返回 {answer, sources, session_id}"""
    client = client or LLMClient()
    sources = _retrieve(message)
    history = _recent_history(user_id, session_id)
    kb = "\n".join(f"[知识库{i}] {src}" for i, src in enumerate(sources, 1))
    user_prompt = (f"多轮上下文:\n{history or '(无)'}\n\n"
                   f"知识库内容:\n{kb or '(无)'}\n\n用户问题:{message}")
    try:
        answer = client.complete(QA_SYSTEM_PROMPT, user_prompt, temperature=0.4)
    except (LLMError, Exception) as e:
        logger.warning("[qa] LLM 失败: %s", e)
        answer = "抱歉,问答服务暂时不可用,请稍后重试。"

    _save_msg(user_id, session_id, "user", message)
    _save_msg(user_id, session_id, "assistant", answer)
    return {"answer": answer, "sources": sources, "session_id": session_id}


def list_history(user_id: int, session_id: str) -> List[dict]:
    with SessionLocal() as session:
        rows = session.scalars(
            select(ChatHistory)
            .where(ChatHistory.user_id == user_id, ChatHistory.session_id == session_id)
            .order_by(ChatHistory.created_at)
        ).all()
    return [{"role": r.role, "content": r.content,
             "created_at": str(r.created_at)[:19] if r.created_at else None} for r in rows]


def new_session_id() -> str:
    return uuid.uuid4().hex[:12]


def _chunk_text(text: str) -> List[str]:
    text = text.strip()
    return [text[i:i + CHUNK_SIZE]
            for i in range(0, len(text), CHUNK_SIZE - CHUNK_OVERLAP) if text[i:i + CHUNK_SIZE].strip()]


def ingest_document(text: str, source: str) -> int:
    """把文本分块写入知识库(扩充语料);失败抛异常由调用方降级。"""
    import chromadb
    from scripts.build_vector_store import COLLECTION_NAME, DB_PATH, Embedder

    chunks = _chunk_text(text)
    if not chunks:
        return 0
    embedder = Embedder()
    client = chromadb.PersistentClient(path=str(DB_PATH))
    collection = client.get_or_create_collection(COLLECTION_NAME)
    ids = [f"doc_{source}_{i}" for i in range(len(chunks))]
    vectors = [embedder.embed_query(c).tolist() for c in chunks]
    metas = [{"source": source, "chunk": i} for i in range(len(chunks))]
    collection.upsert(ids=ids, embeddings=vectors, documents=chunks, metadatas=metas)
    logger.info("[qa] 知识库已写入 %d 个分块(source=%s)", len(chunks), source)
    return len(chunks)
