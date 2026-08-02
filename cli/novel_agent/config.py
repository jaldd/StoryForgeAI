"""配置：从 .env / 环境变量加载。

设计原则（见 .specify/memory/constitution.md）：
- Agent 与具体小说**解耦**：书名、小说目录都不硬编码，全走配置。
- 小说内容 + Agent 运行时都在**仓库外**的 NOVEL_DIR 下；代码仓库保持纯代码。
- API Key 走环境变量，不硬编码。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

__all__ = ["Settings", "get_settings"]


def _repo_root() -> Path:
    """代码仓库根：用于找 .env。优先 STORYFORGE_ROOT，否则当前工作目录。"""
    env = os.environ.get("STORYFORGE_ROOT")
    return Path(env).expanduser().resolve() if env else Path.cwd().resolve()


@dataclass(frozen=True)
class Settings:
    """全局配置。小说相关路径都以 novel_dir 为根解析。"""

    # --- LLM（火山方舟 OpenAI 兼容 coding 网关）---
    ark_api_key: str = ""
    model: str = "glm-5.2"
    base_url: str = "https://ark.cn-beijing.volces.com/api/coding/v3"

    # --- Embedding（火山方舟 multimodal embedding，套餐内）---
    embed_model: str = "doubao-embedding-vision"
    embed_url: str = (
        "https://ark.cn-beijing.volces.com/api/coding/v3/embeddings/multimodal"
    )

    # --- 小说（仓库外，不硬编码）---
    novel_name: str = "本小说"            # NOVEL_NAME：prompt 里用的显示名
    novel_dir: str = ""                   # NOVEL_DIR：小说内容根目录（设定+文风基准+正文）

    # --- 小说内相对路径（相对 novel_dir）---
    chapter_subdir: str = "正文/AI生成"   # NOVEL_CHAPTER_SUBDIR
    exemplar_subpath: str = "文风基准/1.txt"  # NOVEL_EXEMPLAR（相对 novel_dir；留空则不用范例）
    instruction_subpath: str = "写作指令.md"  # NOVEL_INSTRUCTION（相对 novel_dir；留空则不加载写作指令全文）
    index_exclude: str = "正文"          # NOVEL_INDEX_EXCLUDE：建索引时跳过的目录名（逗号分隔），默认排除正文（300章太慢）

    # --- Agent 运行时（默认放 novel_dir/.agent，可覆盖到别处）---
    runs_dir: str = ""                    # NOVEL_RUNS_DIR，空则 <novel_dir>/.agent/runs
    chroma_dir: str = ""                  # NOVEL_CHROMA_DIR，空则 <novel_dir>/.agent/chroma_db
    working_memory_name: str = "working_memory.json"

    # --- 仓库根（仅用于找 .env；小说路径不依赖它）---
    repo_root: Path = field(default_factory=_repo_root)

    # --- 检索分块 ---
    chunk_size: int = 300
    chunk_overlap: int = 80

    # --- 编排控制 ---
    max_rounds: int = 10
    max_reviews: int = 6  # 审稿最多打回次数，防死循环

    # ---------- 路径解析 ----------
    def path(self, rel: str) -> Path:
        """相对路径 -> 绝对路径（相对 repo_root）。已是绝对路径则原样返回。"""
        p = Path(rel)
        return p if p.is_absolute() else (self.repo_root / p)

    @property
    def novel_path(self) -> Path:
        """小说内容根目录。"""
        return Path(self.novel_dir).expanduser() if self.novel_dir else (self.repo_root / self.novel_dir)

    @property
    def doc_path(self) -> Path:
        """RAG 索引源目录（= 小说根）。"""
        return self.novel_path

    @property
    def chapter_path(self) -> Path:
        """Agent 产出章节目录。"""
        return self.novel_path / self.chapter_subdir

    @property
    def exemplar_full(self) -> Path:
        """文风金标准文件（novel_dir 内的相对路径）。"""
        return self.novel_path / self.exemplar_subpath if self.exemplar_subpath else self.novel_path

    @property
    def instruction_full(self) -> Path:
        """写作指令文件（novel_dir 内的相对路径）。"""
        return self.novel_path / self.instruction_subpath if self.instruction_subpath else self.novel_path

    @property
    def runs_path(self) -> Path:
        """run 日志目录：显式 runs_dir 优先，否则 <novel_dir>/.agent/runs。"""
        if self.runs_dir:
            return self.path(self.runs_dir)
        return self.novel_path / ".agent" / "runs"

    @property
    def chroma_path(self) -> Path:
        """向量库目录：显式 chroma_dir 优先，否则 <novel_dir>/.agent/chroma_db。"""
        if self.chroma_dir:
            return self.path(self.chroma_dir)
        return self.novel_path / ".agent" / "chroma_db"

    @property
    def working_memory_path(self) -> Path:
        """工作记忆文件（跨进程持久化）。"""
        return self.runs_path / self.working_memory_name

    # ---------- 校验 ----------
    def require_api_key(self) -> str:
        if not self.ark_api_key:
            raise RuntimeError(
                "未配置 ARK_API_KEY。请在 .env 或环境变量中设置 ARK_API_KEY（参考 cli/.env.example）。"
            )
        return self.ark_api_key

    def require_novel_dir(self) -> Path:
        """用到小说内容时调用：novel_dir 未配置则给清晰错误。"""
        if not self.novel_dir:
            raise RuntimeError(
                "未配置 NOVEL_DIR。请在 .env 中设置 NOVEL_DIR 指向小说内容根目录"
                "（仓库外，含设定/文风基准/正文）。参考 cli/.env.example。"
            )
        return self.novel_path


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """加载 .env 并构造 Settings 单例。"""
    load_dotenv(_repo_root() / ".env")
    load_dotenv()
    return Settings(
        ark_api_key=os.environ.get("ARK_API_KEY", ""),
        model=os.environ.get("CLAUDE_MODEL", "glm-5.2"),
        novel_name=os.environ.get("NOVEL_NAME", "本小说"),
        novel_dir=os.environ.get("NOVEL_DIR", ""),
        chapter_subdir=os.environ.get("NOVEL_CHAPTER_SUBDIR", "正文/AI生成"),
        exemplar_subpath=os.environ.get("NOVEL_EXEMPLAR", "文风基准/1.txt"),
        instruction_subpath=os.environ.get("NOVEL_INSTRUCTION", "写作指令.md"),
        index_exclude=os.environ.get("NOVEL_INDEX_EXCLUDE", "正文"),
        runs_dir=os.environ.get("NOVEL_RUNS_DIR", ""),
        chroma_dir=os.environ.get("NOVEL_CHROMA_DIR", ""),
        repo_root=_repo_root(),
    )
