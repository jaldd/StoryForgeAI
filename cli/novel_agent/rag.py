"""RAG 检索：从 py/rag_volcano.py 迁移，生产化重构。

改进：
- 去模块级副作用：原版 import 时就建 chroma client + 读 os.environ[ARK_API_KEY]（缺则崩）。
  本版改为 RAGStore 类，惰性初始化、config 注入。
- chromadb / requests 惰性导入，纯函数（chunk_text/classify_type）单测不依赖它们。
- embedding 函数与路径均可注入，便于测试。
"""
from __future__ import annotations

import glob
import time
from pathlib import Path
from typing import Any, List, Optional, Tuple

from .config import Settings, get_settings

__all__ = ["RAGStore", "chunk_text", "classify_type", "load_documents"]

COLLECTION_NAME = "novel_kb"


# ---------- 纯函数（不依赖 settings / 联网，可单测）----------
def chunk_text(text: str, size: int = 300, overlap: int = 80) -> List[str]:
    """按字符切块：每块 size 字，相邻块重叠 overlap 字（避免一刀切断语义）。"""
    chunks: List[str] = []
    start = 0
    while start < len(text):
        end = start + size
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start = end - overlap  # 退 overlap 字，制造重叠
    return chunks


def classify_type(path: str) -> str:
    """根据出处路径给块打类型标签，供检索时 where 过滤。"""
    p = path.lower()
    if "人物" in p or "大方向共识备忘" in p:
        return "character"
    if "每章" in p or "正文" in p or "章节" in p:
        return "chapter"
    return "other"


def load_documents(doc_dir: Path) -> List[Tuple[str, str]]:
    """递归读出目录下所有 .md/.txt，返回 [(相对路径, 全文)]。"""
    docs: List[Tuple[str, str]] = []
    for path in glob.glob(f"{doc_dir}/**/*", recursive=True):
        if path.endswith(".md") or path.endswith(".txt"):
            with open(path, encoding="utf-8") as f:
                docs.append((path, f.read()))
    return docs


# ---------- 火山方舟 multimodal embedding 适配器 ----------
class VolcanoEmbedding:
    """Chroma 适配器：输入一串文本，返回一串向量（Chroma 在存/查时自动调用）。"""

    def __init__(self, settings: Settings, max_workers: int = 3, sleep: float = 0.2):
        self.settings = settings
        self.max_workers = max_workers
        self.sleep = sleep  # 成功后限速，主动压低 QPS，避免触发 429

    def _embed_one(self, text: str, retries: int = 6) -> List[float]:
        import requests  # 惰性导入

        last_err: Optional[Exception] = None
        for attempt in range(retries):
            try:
                resp = requests.post(
                    self.settings.embed_url,
                    headers={"Authorization": f"Bearer {self.settings.require_api_key()}"},
                    json={"model": self.settings.embed_model,
                          "input": [{"type": "text", "text": text}]},
                    timeout=60,
                )
                resp.raise_for_status()
                if self.sleep:
                    time.sleep(self.sleep)
                return resp.json()["data"][0]["embedding"]
            except Exception as e:
                last_err = e
                time.sleep(0.5 * (2 ** attempt))  # 指数退避
        raise RuntimeError(f"embedding 失败：{last_err}")

    # Chroma 调用接口（三处都可能被调到，统一返回 List[List[float]]）
    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return [self._embed_one(t) for t in texts]

    def __call__(self, input: List[str]) -> List[List[float]]:
        return [self._embed_one(t) for t in input]

    def embed_query(self, input: List[str]) -> List[List[float]]:
        return [self._embed_one(input[0])]

    def name(self) -> str:
        return "volcano_embedding"


# ---------- RAGStore ----------
class RAGStore:
    """设定检索库：惰性建 Chroma，向量化存取 + 语义检索。

    用法：
        store = RAGStore()
        store.build_index()                 # 首次建库
        hits = store.retrieve("云依是谁")   # 检索
    测试：
        store = RAGStore(embed_fn=FakeEF(), client=FakeChroma())
    """

    def __init__(
        self,
        settings: Optional[Settings] = None,
        embed_fn: Any = None,
        client: Any = None,
    ):
        self.settings = settings or get_settings()
        self._embed_fn = embed_fn
        self._chroma_client = client
        self._collection: Any = None

    # -- 惰性初始化 --
    def _collection_obj(self) -> Any:
        if self._collection is None:
            import chromadb  # 惰性导入，纯函数单测无需付导入开销

            if self._chroma_client is None:
                self._chroma_client = chromadb.PersistentClient(
                    path=str(self.settings.chroma_path)
                )
            if self._embed_fn is None:
                self._embed_fn = VolcanoEmbedding(self.settings)
            self._collection = self._chroma_client.get_or_create_collection(
                COLLECTION_NAME, embedding_function=self._embed_fn
            )
        return self._collection

    @property
    def count(self) -> int:
        return self._collection_obj().count()

    # -- 建库 --
    def build_all_chunks(self) -> List[Tuple[str, str]]:
        """把所有文档切成带出处的小块，返回 [(文本, 出处路径)]。"""
        all_chunks: List[Tuple[str, str]] = []
        for path, text in load_documents(self.settings.doc_path):
            for piece in chunk_text(text, self.settings.chunk_size, self.settings.chunk_overlap):
                if piece.strip():
                    all_chunks.append((piece, path))
        return all_chunks

    def build_index(self, batch_size: int = 50, progress=print) -> int:
        """把所有切块向量化并存入 Chroma（持久化）。返回索引块数。"""
        collection = self._collection_obj()
        chunks = self.build_all_chunks()
        total = len(chunks)
        done = 0
        for start in range(0, total, batch_size):
            batch = chunks[start:start + batch_size]
            docs = [text for text, _ in batch]
            metas = [{"source": src, "type": classify_type(src)} for _, src in batch]
            ids = [f"c{start + j}" for j in range(len(batch))]
            collection.upsert(ids=ids, documents=docs, metadatas=metas)
            done += len(batch)
            if progress:
                progress(f"  已索引 {done}/{total}")
        if progress:
            progress(f"✅ 已索引 {total} 块到 Chroma（存于 {self.settings.chroma_path}）")
        return total

    # -- 检索 --
    def retrieve(
        self, query: str, top_k: int = 5, doc_type: Optional[str] = None
    ) -> List[Tuple[str, str]]:
        """语义检索 top_k 块，返回 [(文本, 出处)]。doc_type 可按 character/chapter/other 过滤。"""
        kwargs: dict = {}
        if doc_type:
            kwargs["where"] = {"type": doc_type}
        res = self._collection_obj().query(query_texts=[query], n_results=top_k, **kwargs)
        docs = res["documents"][0]
        metas = res["metadatas"][0]
        return [(d, m["source"]) for d, m in zip(docs, metas)]

    def search_knowledge(self, query: str, top_k: int = 5) -> str:
        """给 Agent 用的检索：返回拼接好的字符串（带出处）。"""
        hits = self.retrieve(query, top_k)
        return "\n\n".join(f"【出自 {src}】\n{text}" for text, src in hits)
