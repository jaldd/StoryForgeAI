"""config 模块测试。"""
from pathlib import Path

from novel_agent.config import Settings


def test_settings_path_resolution(tmp_settings, tmp_path):
    """小说相关路径都以 novel_dir 为根解析；运行时默认在 .agent/ 下。"""
    novel = tmp_path / "novel"
    assert tmp_settings.novel_path == novel
    assert tmp_settings.doc_path == novel                       # RAG 索引源 = 小说根
    assert tmp_settings.chapter_path == novel / "正文/AI生成"
    assert tmp_settings.exemplar_full == novel / "文风基准/1.txt"
    assert tmp_settings.instruction_full == novel / "写作指令.md"
    assert tmp_settings.runs_path == novel / ".agent" / "runs"
    assert tmp_settings.chroma_path == novel / ".agent" / "chroma_db"
    assert tmp_settings.working_memory_path == novel / ".agent" / "runs" / "working_memory.json"


def test_runtime_dir_override(tmp_path):
    """显式 runs_dir / chroma_dir 覆盖默认 .agent 路径。"""
    s = Settings(
        ark_api_key="k",
        repo_root=tmp_path,
        novel_dir=str(tmp_path / "novel"),
        runs_dir="py/runs",        # 相对 repo_root
        chroma_dir="/abs/chroma",  # 绝对
    )
    assert s.runs_path == tmp_path / "py/runs"
    assert s.chroma_path == Path("/abs/chroma")
    assert s.working_memory_path == tmp_path / "py/runs" / "working_memory.json"


def test_require_novel_dir_raises_when_unset():
    """novel_dir 未配置时给清晰错误。"""
    s = Settings(ark_api_key="k", repo_root=Path("/tmp"))
    try:
        s.require_novel_dir()
        assert False, "应抛错"
    except RuntimeError as e:
        assert "NOVEL_DIR" in str(e)


def test_require_novel_dir_ok_when_set(tmp_settings):
    assert tmp_settings.require_novel_dir() == tmp_settings.novel_path


def test_require_api_key_raises_when_empty():
    s = Settings(ark_api_key="", novel_dir="/tmp/n", repo_root=Path("/tmp"))
    try:
        s.require_api_key()
        assert False, "应抛错"
    except RuntimeError as e:
        assert "ARK_API_KEY" in str(e)


def test_require_api_key_returns_when_set(tmp_settings):
    assert tmp_settings.require_api_key() == "test-key"


def test_defaults():
    s = Settings(ark_api_key="k")
    assert s.model == "glm-5.2"
    assert s.novel_name == "本小说"
    assert s.max_reviews == 2
    assert s.chunk_size == 300 and s.chunk_overlap == 80
    assert s.chapter_subdir == "正文/AI生成"
    assert s.index_exclude == "正文"
    assert s.instruction_subpath == "写作指令.md"
