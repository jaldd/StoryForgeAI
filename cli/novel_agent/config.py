"""配置：从 .env / 环境变量加载，集中路径/模型/key。

遵循 spec 约束：
- API Key 走环境变量，不硬编码
- run 日志 -> py/runs/，向量库 -> ./chroma_db（保持和现有一致）
- 章节产物 -> docs/.../正文/AI生成/（独立子目录，不污染 正文/新/）
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv


def _repo_root() -> Path:
    """项目根目录：优先 STORYFORGE_ROOT 环境变量，否则当前工作目录。"""
    env = os.environ.get("STORYFORGE_ROOT")
    return Path(env).expanduser().resolve() if env else Path.cwd().resolve()


@dataclass(frozen=True)
class Settings:
    """全局配置。所有相对路径在运行时按 repo_root 解析成绝对路径。"""

    # --- LLM（火山方舟 OpenAI 兼容 coding 网关）---
    ark_api_key: str
    model: str = "glm-5.2"
    base_url: str = "https://ark.cn-beijing.volces.com/api/coding/v3"

    # --- Embedding（火山方舟 multimodal embedding，套餐内）---
    embed_model: str = "doubao-embedding-vision"
    embed_url: str = (
        "https://ark.cn-beijing.volces.com/api/coding/v3/embeddings/multimodal"
    )

    # --- 路径（相对仓库根）---
    repo_root: Path = field(default_factory=_repo_root)
    doc_dir: str = "docs/修仙不如陪她看云"
    runs_dir: str = "py/runs"
    chroma_dir: str = "chroma_db"
    chapter_dir: str = "docs/修仙不如陪她看云/正文/AI生成"
    exemplar_path: str = "docs/修仙不如陪她看云/文风基准/1.txt"

    # --- 检索分块 ---
    chunk_size: int = 300
    chunk_overlap: int = 80

    # --- 编排控制 ---
    max_rounds: int = 10
    max_reviews: int = 2  # 审稿最多打回次数，防死循环

    # --- 路径解析 ---
    def path(self, rel: str) -> Path:
        """相对路径 -> 绝对路径（已是绝对路径则原样返回）。"""
        p = Path(rel)
        return p if p.is_absolute() else (self.repo_root / p)

    @property
    def doc_path(self) -> Path:
        return self.path(self.doc_dir)

    @property
    def runs_path(self) -> Path:
        return self.path(self.runs_dir)

    @property
    def chroma_path(self) -> Path:
        return self.path(self.chroma_dir)

    @property
    def chapter_path(self) -> Path:
        return self.path(self.chapter_dir)

    @property
    def exemplar_full(self) -> Path:
        return self.path(self.exemplar_path)

    def require_api_key(self) -> str:
        """用到 key 时调用：缺失则给清晰错误（而不是构造时崩溃，便于测试）。"""
        if not self.ark_api_key:
            raise RuntimeError(
                "未配置 ARK_API_KEY。请在仓库根目录 .env 或环境变量中设置 "
                "ARK_API_KEY（参考 cli/.env.example）。"
            )
        return self.ark_api_key


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """加载 .env 并构造 Settings 单例。"""
    # .env 优先在仓库根；load_dotenv() 再向上兜底查找
    load_dotenv(_repo_root() / ".env")
    load_dotenv()
    return Settings(
        ark_api_key=os.environ.get("ARK_API_KEY", ""),
        model=os.environ.get("CLAUDE_MODEL", "glm-5.2"),
        repo_root=_repo_root(),
    )
