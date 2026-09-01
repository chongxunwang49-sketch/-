"""
RAG 向量库访问层

复用 scripts/build_vector_store.py 的 Embedder(ollama/st 可插拔)与
同一持久化库(data/chroma_db),为报告生成 Agent 提供"知识库引用"。

对外接口:
  retrieve(query, top_k=3) -> Chroma query 结果(含 documents/metadatas/distances)
    - 查询带 bge 指令前缀,向量与建库时一致
    - 集合不存在时抛异常,由调用方(workflow)降级为"不使用知识库"
"""
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
load_dotenv(PROJECT_ROOT / ".env")
os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1,0.0.0.0")
os.environ.setdefault("no_proxy", "localhost,127.0.0.1,0.0.0.0")

import chromadb  # noqa: E402

# 复用建库脚本里的 Embedder 与路径常量(保证查询与入库向量一致)
from scripts.build_vector_store import COLLECTION_NAME, DB_PATH, Embedder  # noqa: E402

_embedder: Embedder | None = None
_collection = None


def _get_embedder() -> Embedder:
    global _embedder
    if _embedder is None:
        _embedder = Embedder()
    return _embedder


def _get_collection():
    global _collection
    if _collection is None:
        client = chromadb.PersistentClient(path=str(DB_PATH))
        _collection = client.get_collection(COLLECTION_NAME)
    return _collection


def retrieve(query: str, top_k: int = 3) -> dict:
    """
    语义检索:返回最相关的 top_k 个知识块。
    返回结构同 Chroma query:{documents, metadatas, distances}
    """
    embedder = _get_embedder()
    collection = _get_collection()
    query_vec = embedder.embed_query(query)
    result = collection.query(query_embeddings=[query_vec.tolist()], n_results=top_k)
    logger.info("RAG 检索: query=%s, 命中 %d 条", query[:30], len(result["documents"][0]))
    return result
