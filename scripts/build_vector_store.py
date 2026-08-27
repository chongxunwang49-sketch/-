"""
RAG 知识库构建脚本(阶段1-步骤5)

流程:
  1. 读取 data/rag_docs/ 下所有 PDF(pypdf,PyPDF2 的官方继任者)
  2. 文本清洗:换行/制表符统一为空格,连续空白压成一个空格
  3. 分块:chunk_size=500 字符、overlap=50 字符的滑动窗口切分
     (步长 = 500 - 50 = 450,尾部不足一块的剩余文本单独成块,不丢信息)
  4. 向量化(Embedding 提供方可配置,见 .env 的 EMBED_PROVIDER):
     - ollama(默认):本地 Ollama 跑 quentinz/bge-large-zh-v1.5,零下载
     - st:本地 sentence-transformers 加载 BAAI/bge-m3(需模型已下载)
  5. 入库:ChromaDB 持久化到 data/chroma_db;原文存 documents 字段
     (检索时直接返回),metadata 存来源文件/块序号/字符位置/预览
  6. 测试查询:"茅台近三年的净利润是多少",打印最相关的 3 个知识块

直接运行: python scripts/build_vector_store.py
"""
import logging
import os
import re
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# 本地服务的请求绝不允许被系统代理接管(否则 Ollama 11434 会被代理拦成 502)
os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1,0.0.0.0")
os.environ.setdefault("no_proxy", "localhost,127.0.0.1,0.0.0.0")

# HF 镜像配置(仅 st 提供方下载 BGE-M3 时需要)
if os.getenv("HF_ENDPOINT"):
    os.environ["HF_ENDPOINT"] = os.getenv("HF_ENDPOINT")

import chromadb  # noqa: E402
from pypdf import PdfReader  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ------------------------------------------------------------
# 配置(分块策略:chunk_size=500 / overlap=50,自主制作决策)
# ------------------------------------------------------------
DOC_DIR = PROJECT_ROOT / "data" / "rag_docs"          # 知识库语料目录
DB_PATH = PROJECT_ROOT / "data" / "chroma_db"         # ChromaDB 持久化路径
COLLECTION_NAME = "rag_docs"                          # 集合名
CHUNK_SIZE = 500                                      # 块大小(字符)
CHUNK_OVERLAP = 50                                    # 块间重叠(字符)
TEST_QUERY = "茅台近三年的净利润是多少"
TOP_K = 3

# Embedding 提供方: ollama(本地 bge 平替,默认) / st(BGE-M3)
EMBED_PROVIDER = os.getenv("EMBED_PROVIDER", "ollama")
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "quentinz/bge-large-zh-v1.5")
ST_MODEL_NAME = "BAAI/bge-m3"
# bge 系列官方建议:查询侧加指令前缀(文档侧不加),小幅提升中文检索质量
QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章:"


class Embedder:
    """Embedding 抽象层:同一套接口,两种本地实现,按配置切换"""

    def __init__(self, provider: str = EMBED_PROVIDER):
        self.provider = provider
        if provider == "ollama":
            import ollama
            # 显式指定 127.0.0.1 并配合上面的 NO_PROXY,确保走本地直连
            self._client = ollama.Client(host=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434"))
            try:
                self._client.list()  # 探测 Ollama 服务是否在运行
            except Exception as e:
                raise RuntimeError(f"Ollama 服务未运行,请先启动 Ollama: {e}") from e
            self.model_name = OLLAMA_EMBED_MODEL
        elif provider == "st":
            from sentence_transformers import SentenceTransformer
            try:
                self._model = SentenceTransformer(ST_MODEL_NAME)
            except RuntimeError as e:
                if "CUDA" in str(e) or "memory" in str(e).lower():
                    logger.warning("GPU 加载失败(%s),回退 CPU", e)
                    self._model = SentenceTransformer(ST_MODEL_NAME, device="cpu")
                else:
                    raise
            self.model_name = ST_MODEL_NAME
        else:
            raise ValueError(f"未知的 EMBED_PROVIDER: {provider}")
        logger.info("Embedding 提供方=%s, 模型=%s", provider, self.model_name)

    def embed_documents(self, texts: list[str], batch_size: int = 32) -> np.ndarray:
        """批量向量化文档块,输出归一化向量(配合 Chroma 余弦相似度)"""
        vectors = []
        if self.provider == "ollama":
            for i in range(0, len(texts), batch_size):
                batch = texts[i:i + batch_size]
                resp = self._client.embed(model=self.model_name, input=batch)
                vectors.extend(resp["embeddings"])
        else:
            vectors = self._model.encode(
                texts, batch_size=batch_size,
                normalize_embeddings=True, show_progress_bar=True,
            ).tolist()
        arr = np.asarray(vectors, dtype=np.float32)
        # 统一归一化:Ollama 返回的向量未必归一,手动归一后再入库
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        norms[norms == 0] = 1e-9  # 防零向量除零
        return arr / norms

    def embed_query(self, query: str) -> np.ndarray:
        """向量化查询(带 bge 指令前缀),输出归一化向量"""
        return self.embed_documents([QUERY_PREFIX + query])[0]


def load_pdf_texts(doc_dir: Path) -> list[dict]:
    """读取目录下所有 PDF,返回 [{filename, text}]"""
    pdf_files = sorted(doc_dir.glob("*.pdf"))
    if not pdf_files:
        raise FileNotFoundError(f"{doc_dir} 下没有找到 PDF 文件")
    docs = []
    for pdf_file in pdf_files:
        reader = PdfReader(str(pdf_file))
        # 逐页提取并拼接
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        if text.strip():
            docs.append({"filename": pdf_file.name, "text": text})
            logger.info("读取 %s: %d 页, %d 字符", pdf_file.name, len(reader.pages), len(text))
        else:
            logger.warning("%s 未提取到文本,跳过", pdf_file.name)
    return docs


def clean_text(text: str) -> str:
    """清洗:换行/制表符→空格,连续空白压成一个空格"""
    return re.sub(r"\s+", " ", text).strip()


def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """
    滑动窗口分块:块长 size,相邻两块重叠 overlap 字符。
    步长 = size - overlap;尾部不足一块的剩余文本单独成块,保证信息不丢。
    """
    text = text.strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]
    step = size - overlap
    chunks = []
    start = 0
    while start + size <= len(text):
        chunks.append(text[start:start + size])
        start += step
    if start < len(text):  # 收尾:剩余的短尾也保留
        chunks.append(text[start:])
    return chunks


def build_vector_store() -> int:
    """
    构建知识库:读 PDF -> 清洗 -> 分块 -> 向量化 -> 存入 ChromaDB。
    返回入库的知识块总数。
    """
    start_time = time.perf_counter()

    # 1. 读取全部 PDF 并清洗
    docs = load_pdf_texts(DOC_DIR)
    logger.info("共读取 %d 个 PDF 文档", len(docs))

    # 2. 分块(500/50 滑动窗口)
    chunk_records = []  # {filename, index, start, text}
    for doc in docs:
        cleaned = clean_text(doc["text"])
        chunks = chunk_text(cleaned)
        for i, ch in enumerate(chunks):
            chunk_records.append({
                "filename": doc["filename"],
                "index": i,
                "start": i * (CHUNK_SIZE - CHUNK_OVERLAP),  # 该块在原文的起始字符位置
                "text": ch,
            })
    logger.info("分块完成: 共 %d 个知识块(块长 %d, 重叠 %d)", len(chunk_records), CHUNK_SIZE, CHUNK_OVERLAP)

    # 3. 向量化
    embedder = Embedder()
    embeddings = embedder.embed_documents([r["text"] for r in chunk_records])
    logger.info("向量化完成: %d 个向量, 维度 %d", embeddings.shape[0], embeddings.shape[1])

    # 4. 写入 ChromaDB(持久化目录 data/chroma_db)
    client = chromadb.PersistentClient(path=str(DB_PATH))
    # 重建语义:已存在同名集合则先删除,保证库里永远是最新一次构建的结果
    existing = [c.name for c in client.list_collections()]
    if COLLECTION_NAME in existing:
        client.delete_collection(COLLECTION_NAME)
        logger.info("已删除旧集合 %s(重建)", COLLECTION_NAME)
    collection = client.create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},  # 配合归一化向量,检索用余弦相似度
    )
    collection.add(
        ids=[f"{r['filename']}-{r['index']}" for r in chunk_records],
        embeddings=[e.tolist() for e in embeddings],
        documents=[r["text"] for r in chunk_records],      # 原文存 documents,检索直接返回
        metadatas=[{
            "source": r["filename"],
            "chunk_index": r["index"],
            "start_char": r["start"],
            "preview": r["text"][:100],                    # metadata 里附 100 字预览
        } for r in chunk_records],
    )
    logger.info("已写入集合 %s: %d 个块(持久化路径 %s)", COLLECTION_NAME, collection.count(), DB_PATH)

    elapsed = time.perf_counter() - start_time
    logger.info("build_vector_store 完成: %d 个知识块入库, 耗时 %.2f 秒", len(chunk_records), elapsed)
    return len(chunk_records)


def test_query(embedder: Embedder, collection, query: str = TEST_QUERY, top_k: int = TOP_K) -> None:
    """测试检索:输入问题,打印最相关的 top_k 个知识块"""
    logger.info("测试查询: %s", query)
    query_embedding = embedder.embed_query(query)
    results = collection.query(query_embeddings=[query_embedding.tolist()], n_results=top_k)

    print("\n" + "=" * 70)
    print(f"查询:「{query}」→ 最相关的 {top_k} 个知识块:")
    print("=" * 70)
    for rank, (doc, meta, dist) in enumerate(
        zip(results["documents"][0], results["metadatas"][0], results["distances"][0]), start=1
    ):
        # Chroma 的 cosine 距离 = 1 - 余弦相似度,越小越相关
        print(f"\n--- 第 {rank} 名 | 相似度 {1 - dist:.4f} | 来源 {meta['source']} | "
              f"块序号 {meta['chunk_index']}(原文偏移 {meta['start_char']}) ---")
        print(doc)


if __name__ == "__main__":
    count = build_vector_store()
    if count:
        # 复用同一个 Embedder 做测试查询,避免重复加载模型
        embedder = Embedder()
        client = chromadb.PersistentClient(path=str(DB_PATH))
        collection = client.get_collection(COLLECTION_NAME)
        test_query(embedder, collection)
