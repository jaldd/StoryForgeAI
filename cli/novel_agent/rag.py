"""RAG 检索：从 py/rag_volcano.py 迁移，生产化重构。

改进：
- 去模块级副作用：原版 import 时就建 chroma client + 读 os.environ[ARK_API_KEY]（缺则崩）。
  本版改为 RAGStore 类，惰性初始化、config 注入。
- chromadb / requests 惰性导入，纯函数（chunk_text/classify_type）单测不依赖它们。
- embedding 函数与路径均可注入，便于测试。
"""
from __future__ import annotations

import glob
import json
import time
from pathlib import Path
from typing import Any, List, Optional, Tuple

from .config import Settings, get_settings

__all__ = ["RAGStore", "chunk_text", "classify_type", "load_documents",
           "VolcanoEmbedding", "OpenAIEmbedding"]

COLLECTION_NAME = "novel_kb"
MANIFEST_NAME = "rebuild_manifest.json"  # 0.6：rebuild 块 id 清单，存 chroma_path 下


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
    """根据出处路径给块打类型标签，供检索时 where 过滤。

    - 人物 -> character
    - 总纲/伏笔/时间线/写作指令/每章/进度表/日常素材/防崩 -> setting
    - 文风基准 -> exemplar
    - 正文/章节 -> chapter（前文参考；rebuild 时正文已被 NOVEL_INDEX_EXCLUDE 跳过，
      仅 index add 手动加的正文走这条，否则 writer 的前文检索查不到）
    - 其他 -> other
    """
    p = path.lower()
    if "人物" in p:
        return "character"
    if ("总纲" in p or "伏笔" in p or "时间线" in p or "写作指令" in p
            or "每章" in p or "进度表" in p or "日常素材" in p or "防崩" in p):
        return "setting"
    if "文风基准" in p:
        return "exemplar"
    if "正文" in p or "章节" in p:
        return "chapter"
    return "other"


def load_documents(doc_dir: Path, exclude: Optional[List[str]] = None) -> List[Tuple[str, str]]:
    """递归读出目录下所有 .md/.txt，返回 [(路径, 全文)]。

    exclude：目录名列表，命中任一祖先目录即整目录跳过
    （如 ["正文"] 跳过 300 章正文，只索引设定/文风基准）。
    """
    exclude = exclude or []
    docs: List[Tuple[str, str]] = []
    for path in glob.glob(f"{doc_dir}/**/*", recursive=True):
        if not (path.endswith(".md") or path.endswith(".txt")):
            continue
        if exclude:
            # 相对 doc_dir 的祖先目录段，命中 exclude 任一段则跳过整个目录
            rel_parts = Path(path).relative_to(doc_dir).parts[:-1]
            if any(part in exclude for part in rel_parts):
                continue
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
                    headers={"Authorization": f"Bearer {self.settings.require_embed_key()}"},
                    json={"model": self.settings.embed_model,
                          "input": [{"type": "text", "text": text}]},
                    timeout=60,
                )
                resp.raise_for_status()
                if self.sleep:
                    time.sleep(self.sleep)
                # 火山 multimodal embedding 返回 {"data": {"embedding": [...]}}
                # （单条时是 dict；部分批量场景可能是 list，两种都兼容）
                data = resp.json().get("data")
                if isinstance(data, dict):
                    return data["embedding"]
                if isinstance(data, list):
                    return data[0]["embedding"]
                raise RuntimeError(f"未知的 embedding 响应结构：{resp.text[:200]}")
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


# ---------- OpenAI 兼容 embedding 适配器（SenseNova Kimi / OpenAI / 本地 vLLM 等）----------
class OpenAIEmbedding:
    """Chroma 适配器：OpenAI 兼容 /embeddings 接口（SenseNova Kimi、OpenAI、vLLM、Xinference 等）。

    与 VolcanoEmbedding 接口一致（Chroma 在存/查时自动调用）。
    - 请求：POST {embed_url}  [Authorization: Bearer {key}]  body {"input": [texts], "model": model}
    - 响应：{"data": [{"embedding": [...]}, ...]}
    - embed_url 应为完整端点（如 vLLM/Xinference 的 http://host:port/v1/embeddings）。
    - key 可选：本地/局域网服务（无需鉴权）可不设 EMBED_API_KEY，此时不带 Authorization 头。
    - 支持批量（一次传整批 texts），比逐条更高效。
    - 注：Ollama 原生 /api/embeddings 的报文/响应格式不同，本适配器不直接兼容；
      用 Ollama 请改用 Xinference/vLLM（OpenAI 兼容）或加 ollama provider。
    """

    def __init__(self, settings: Settings, max_workers: int = 3, sleep: float = 0.2):
        self.settings = settings
        self.max_workers = max_workers
        self.sleep = sleep  # 成功后限速，主动压低 QPS，避免触发 429

    def _embed_batch(self, texts: List[str], retries: int = 6) -> List[List[float]]:
        import requests  # 惰性导入

        last_err: Optional[Exception] = None
        for attempt in range(retries):
            try:
                # 本地/局域网 embedding 服务（vLLM/Xinference 等）通常不需要 key；
                # 仅当配置了 EMBED_API_KEY（或回落 ARK_API_KEY）时才带 Authorization 头。
                key = self.settings.embed_api_key or self.settings.ark_api_key
                headers = {}
                if key:
                    headers["Authorization"] = f"Bearer {key}"
                # 本地/局域网自建服务不走系统代理（Mac 上为连火山配的 http_proxy 会误伤局域网 IP）
                resp = requests.post(
                    self.settings.embed_url,
                    headers=headers,
                    json={"model": self.settings.embed_model, "input": texts},
                    timeout=60,
                    trust_env=False,
                )
                resp.raise_for_status()
                if self.sleep:
                    time.sleep(self.sleep)
                data = resp.json().get("data")
                if isinstance(data, list) and data:
                    # 返回条数应与输入一致；单条返回（不应发生）则广播兜底
                    if len(data) == len(texts):
                        return [d["embedding"] for d in data]
                    return [data[0]["embedding"] for _ in texts]
                raise RuntimeError(f"未知的 embedding 响应结构：{resp.text[:200]}")
            except Exception as e:
                last_err = e
                time.sleep(0.5 * (2 ** attempt))  # 指数退避
        raise RuntimeError(f"embedding 失败：{last_err}")

    # Chroma 调用接口（三处都可能被调到，统一返回 List[List[float]]）
    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return self._embed_batch(texts)

    def __call__(self, input: List[str]) -> List[List[float]]:
        return self._embed_batch(input)

    def embed_query(self, input: List[str]) -> List[List[float]]:
        return self._embed_batch([input[0]])

    def name(self) -> str:
        return "openai_embedding"


class OllamaEmbedding:
    """Chroma 适配器：Ollama 原生 /api/embed 接口（本地嵌入，Windows/Mac 均可跑）。

    与 VolcanoEmbedding / OpenAIEmbedding 接口一致（Chroma 在存/查时自动调用）。
    - 请求：POST {embed_url}  [Authorization: Bearer {key}]  body {"model": model, "input": [texts]}（批量）
    - 响应：{"embeddings": [[...], ...]}（与 OpenAI 的 {"data":[...]} 不同）
    - embed_url 应为完整端点（如 http://host:11434/api/embed）。
    - key 可选：Ollama 本地服务通常不需要 key，此时不带 Authorization 头。
    - 不使用系统代理（trust_env=False），直连本地/局域网 Ollama，避免被 http_proxy 误伤。
    """

    def __init__(self, settings: Settings, max_workers: int = 3, sleep: float = 0.2):
        self.settings = settings
        self.max_workers = max_workers
        self.sleep = sleep  # 成功后限速，主动压低 QPS，避免触发 429

    def _embed_batch(self, texts: List[str], retries: int = 6) -> List[List[float]]:
        import requests  # 惰性导入

        last_err: Optional[Exception] = None
        for attempt in range(retries):
            try:
                # Ollama 本地服务通常不需要 key；仅配置时才带 Authorization 头
                key = self.settings.embed_api_key or self.settings.ark_api_key
                headers = {"Content-Type": "application/json"}
                if key:
                    headers["Authorization"] = f"Bearer {key}"
                resp = requests.post(
                    self.settings.embed_url,
                    headers=headers,
                    json={"model": self.settings.embed_model, "input": texts},
                    timeout=60,
                    trust_env=False,
                )
                resp.raise_for_status()
                if self.sleep:
                    time.sleep(self.sleep)
                data = resp.json().get("embeddings")
                if isinstance(data, list) and data:
                    # 返回条数应与输入一致；单条返回（不应发生）则广播兜底
                    if len(data) == len(texts):
                        return [list(d) for d in data]
                    return [list(data[0]) for _ in texts]
                raise RuntimeError(f"未知的 Ollama embedding 响应结构：{resp.text[:200]}")
            except Exception as e:
                last_err = e
                time.sleep(0.5 * (2 ** attempt))  # 指数退避
        raise RuntimeError(f"Ollama embedding 失败：{last_err}")

    # Chroma 调用接口（三处都可能被调到，统一返回 List[List[float]]）
    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return self._embed_batch(texts)

    def __call__(self, input: List[str]) -> List[List[float]]:
        return self._embed_batch(input)

    def embed_query(self, input: List[str]) -> List[List[float]]:
        return self._embed_batch([input[0]])

    def name(self) -> str:
        return "ollama_embedding"


# ---------- RAGStore ----------
class RAGStore:
    """设定检索库：惰性建 Chroma，向量化存取 + 语义检索。

    用法：
        store = RAGStore()
        store.build_index()                 # 首次建库
        hits = store.retrieve("主角是谁")   # 检索
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
    def _make_embedding(self) -> Any:
        """按配置选 embedding 适配器：

        - EMBED_PROVIDER=ollama  -> Ollama 原生 /api/embed（本地部署，Windows/Mac 均可）
        - EMBED_PROVIDER=openai  -> OpenAI 兼容（SenseNova Kimi / OpenAI / vLLM / Xinference）
        - EMBED_PROVIDER=volcano -> 火山方舟 multimodal（默认）
        - 空 -> 按 embed_url 域名推断（含 volces.com 即火山，否则 openai）
        """
        provider = self.settings.embed_provider
        if not provider:
            provider = "volcano" if "volces.com" in self.settings.embed_url else "openai"
        if provider == "openai":
            return OpenAIEmbedding(self.settings)
        if provider == "ollama":
            return OllamaEmbedding(self.settings)
        return VolcanoEmbedding(self.settings)

    def _collection_obj(self) -> Any:
        if self._collection is None:
            import chromadb  # 惰性导入，纯函数单测无需付导入开销

            if self._chroma_client is None:
                self._chroma_client = chromadb.PersistentClient(
                    path=str(self.settings.chroma_path)
                )
            if self._embed_fn is None:
                self._embed_fn = self._make_embedding()
            self._collection = self._chroma_client.get_or_create_collection(
                COLLECTION_NAME, embedding_function=self._embed_fn
            )
        return self._collection

    @property
    def count(self) -> int:
        return self._collection_obj().count()

    # -- 建库 --
    def build_all_chunks(self) -> List[Tuple[str, str]]:
        """把所有文档切成带出处的小块，返回 [(文本, 相对 NOVEL_DIR 的出处路径)]。"""
        exclude = [s.strip() for s in self.settings.index_exclude.split(",") if s.strip()]
        all_chunks: List[Tuple[str, str]] = []
        for path, text in load_documents(self.settings.doc_path, exclude=exclude):
            src = self._to_store_source(path)  # 相对 NOVEL_DIR，跨机可移植
            for piece in chunk_text(text, self.settings.chunk_size, self.settings.chunk_overlap):
                if piece.strip():
                    all_chunks.append((piece, src))
        return all_chunks

    # -- rebuild manifest（0.6 陈块精确清理）--
    def _load_manifest(self) -> List[str]:
        """上次 rebuild 写入的块 id 清单；文件不存在/损坏返回 []（不阻断本次 rebuild）。"""
        p = self.settings.chroma_path / MANIFEST_NAME
        if not p.exists():
            return []
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            ids = data.get("ids", [])
            return [i for i in ids if isinstance(i, str)]
        except (OSError, ValueError):
            return []

    def _save_manifest(self, ids: List[str]) -> None:
        """记录本次 rebuild 写入的块 id，供下次精确清理；写失败不阻断。"""
        p = self.settings.chroma_path / MANIFEST_NAME
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(
                json.dumps({"ids": ids, "count": len(ids)}, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError:
            pass

    def build_index(self, batch_size: int = 50, progress=print) -> int:
        """把所有切块向量化并存入 Chroma（持久化）。返回索引块数。

        0.6 陈块精确清理：rebuild 只负责自己写入的 c* 块（manifest 记录 id
        清单，存 chroma_path 下），下次 rebuild 先按清单精确删旧块再 upsert。
        不碰 index add 写入的章节块（id 形如 {文件名}_{i}，两套 id 不冲突）。
        """
        collection = self._collection_obj()
        old_ids = self._load_manifest()
        if old_ids:
            collection.delete(ids=old_ids)
            if progress:
                progress(f"  已按 manifest 精确清理上次 rebuild 的 {len(old_ids)} 块陈块")
        chunks = self.build_all_chunks()
        total = len(chunks)
        done = 0
        new_ids: List[str] = []
        for start in range(0, total, batch_size):
            batch = chunks[start:start + batch_size]
            docs = [text for text, _ in batch]
            metas = [{"source": src, "type": classify_type(src)} for _, src in batch]
            ids = [f"c{start + j}" for j in range(len(batch))]
            new_ids.extend(ids)
            collection.upsert(ids=ids, documents=docs, metadatas=metas)
            done += len(batch)
            if progress:
                progress(f"  已索引 {done}/{total}")
        self._save_manifest(new_ids)
        if progress:
            progress(f"✅ 已索引 {total} 块到 Chroma（存于 {self.settings.chroma_path}）")
        return total

    # -- 单文件增删（手动操作，不受 NOVEL_INDEX_EXCLUDE 限制）--
    def _resolve_source(self, file_path: str) -> str:
        """文件路径 -> 用于读文件的绝对路径：相对路径按 NOVEL_DIR 解析，绝对路径原样。"""
        p = Path(file_path).expanduser()
        if not p.is_absolute():
            p = self.settings.novel_path / p
        return str(p)

    def _to_store_source(self, file_path: str) -> str:
        """存进向量库的 source：相对 NOVEL_DIR 的路径（跨机可移植，不绑死绝对路径）。

        - 先按 _resolve_source 解析成绝对路径，再 relative_to(NOVEL_DIR) 取相对路径；
        - 不在 NOVEL_DIR 下的外部文件（如绝对路径传入）：退回绝对路径，保证仍可用。
        """
        abs_path = self._resolve_source(file_path)
        try:
            return Path(abs_path).relative_to(self.settings.novel_path).as_posix()
        except ValueError:
            return abs_path

    def add_document(self, file_path: str, progress=print) -> int:
        """手动加单个文件进向量库：读 -> 分块 -> 向量化 -> upsert。

        不检查 NOVEL_INDEX_EXCLUDE（用户手动加什么都行，常用于精修后的单章正文）。
        先删该文件旧块再 upsert，故精修后重跑也安全（块数变化不留孤儿块）。
        id 用 "{文件名}_{块序号}"，metadata.source 存相对 NOVEL_DIR 的路径（跨机可移植）。
        返回索引块数。
        """
        abs_path = self._resolve_source(file_path)
        path = Path(abs_path)
        if not path.is_file():
            raise FileNotFoundError(abs_path)
        text = path.read_text(encoding="utf-8")
        src = self._to_store_source(file_path)  # 相对 NOVEL_DIR，跨机可移植
        collection = self._collection_obj()
        # 先清掉该文件旧块，避免精修后块数变化留下孤儿
        collection.delete(where={"source": src})
        fname = path.name
        chunks = [c for c in chunk_text(text, self.settings.chunk_size, self.settings.chunk_overlap)
                  if c.strip()]
        if not chunks:
            if progress:
                progress(f"⚠️ {fname} 无有效内容，已清空旧块")
            return 0
        ids = [f"{fname}_{i}" for i in range(len(chunks))]
        metas = [{"source": src, "type": classify_type(src)} for _ in chunks]
        collection.upsert(ids=ids, documents=chunks, metadatas=metas)
        if progress:
            progress(f"✅ 已索引 {fname}：{len(chunks)} 块（type={classify_type(src)}）")
        return len(chunks)

    def remove_document(self, file_path: str) -> int:
        """删该文件在向量库里的所有块（按 source 相对路径匹配）。返回删除的块数。"""
        src = self._to_store_source(file_path)
        collection = self._collection_obj()
        before = collection.get(where={"source": src}) or {}
        n = len(before.get("ids", []) or [])
        collection.delete(where={"source": src})
        return n

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
