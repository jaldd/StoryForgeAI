"""config 模块测试。"""
from pathlib import Path

from novel_agent.config import Settings


def test_settings_path_resolution(tmp_settings, tmp_path):
    """小说相关路径都以 novel_dir 为根解析；运行时默认在 .agent/ 下。"""
    novel = tmp_path / "novel"
    assert tmp_settings.novel_path == novel
    assert tmp_settings.doc_path == novel                       # RAG 索引源 = 小说根
    assert tmp_settings.chapter_path == novel / "正文/AI生成"
    assert tmp_settings.exemplar_full == novel / "文风基准"    # 0.5 目录级语料
    assert tmp_settings.instruction_full == novel / "写作指令.md"
    assert tmp_settings.rules_full == novel / "写作铁律.md"      # 0.2 铁律外置
    assert tmp_settings.runs_path == novel / ".agent" / "runs"
    assert tmp_settings.chroma_path == novel / ".agent" / "chroma_db"
    assert tmp_settings.working_memory_path == novel / ".agent" / "runs" / "working_memory.json"


def test_rules_subpath_empty(tmp_settings):
    """rules_subpath 留空时 rules_full 退回 novel_path（不指向文件，_load_rules 返回空）。"""
    s = Settings(
        ark_api_key="k",
        repo_root=tmp_settings.repo_root,
        novel_dir=tmp_settings.novel_dir,
        rules_subpath="",
    )
    assert s.rules_full == s.novel_path


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


# ---------- target_words（0.8 T6）----------
def test_target_words_default():
    """A12：单章目标字数默认 1500。"""
    assert Settings(ark_api_key="k").target_words == 1500


def test_target_words_from_env(monkeypatch):
    """A14：NOVEL_TARGET_WORDS 环境变量生效。

    get_settings 带 @lru_cache(maxsize=1)：setenv 后必须先 cache_clear
    才能读到新值，收尾再 clear 一次防污染其他用例。
    """
    from novel_agent.config import get_settings
    monkeypatch.setenv("NOVEL_TARGET_WORDS", "2200")
    get_settings.cache_clear()
    try:
        assert get_settings().target_words == 2200
    finally:
        get_settings.cache_clear()


# ---------- 0.7 模型来源可换（T1）----------
def test_llm_api_key_env(monkeypatch):
    """A2：LLM_API_KEY 设置则生效；未设时字段为空（回落 ark 发生在 load_profiles，T2 测）。"""
    from novel_agent.config import get_settings
    monkeypatch.setenv("LLM_API_KEY", "sk-new")
    get_settings.cache_clear()
    try:
        assert get_settings().llm_api_key == "sk-new"
    finally:
        get_settings.cache_clear()


def test_llm_api_key_unset_empty():
    from novel_agent.config import get_settings
    get_settings.cache_clear()
    try:
        assert get_settings().llm_api_key == ""
    finally:
        get_settings.cache_clear()


def test_model_three_level_fallback(monkeypatch):
    """A3：LLM_MODEL -> CLAUDE_MODEL -> glm-5.2 三级回落。"""
    from novel_agent.config import get_settings
    # 1) LLM_MODEL 赢
    monkeypatch.setenv("LLM_MODEL", "kimi-k3")
    get_settings.cache_clear()
    try:
        assert get_settings().model == "kimi-k3"
    finally:
        get_settings.cache_clear()
    # 2) LLM_MODEL 未设 -> CLAUDE_MODEL
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.setenv("CLAUDE_MODEL", "glm-4.7")
    get_settings.cache_clear()
    try:
        assert get_settings().model == "glm-4.7"
    finally:
        get_settings.cache_clear()
    # 3) 都未设 -> 内置默认
    monkeypatch.delenv("CLAUDE_MODEL", raising=False)
    get_settings.cache_clear()
    try:
        assert get_settings().model == "glm-5.2"
    finally:
        get_settings.cache_clear()


def test_base_url_env(monkeypatch):
    """A1/A4：LLM_BASE_URL 设置则生效；未设回落火山 URL（现状不变）。"""
    from novel_agent.config import get_settings
    monkeypatch.setenv("LLM_BASE_URL", "https://api.moonshot.cn/v1")
    get_settings.cache_clear()
    try:
        assert get_settings().base_url == "https://api.moonshot.cn/v1"
    finally:
        get_settings.cache_clear()
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    get_settings.cache_clear()
    try:
        assert get_settings().base_url == "https://ark.cn-beijing.volces.com/api/coding/v3"
    finally:
        get_settings.cache_clear()


def test_writer_env_wiring(monkeypatch):
    """A6/A7：WRITER_* 接线；设空串时字段为空（等价未设，回落主配置在 load_profiles）。"""
    from novel_agent.config import get_settings
    monkeypatch.setenv("WRITER_BASE_URL", "https://api.sensenova.cn/compatible-mode/v2")
    monkeypatch.setenv("WRITER_API_KEY", "sk-w")
    monkeypatch.setenv("WRITER_MODEL", "kimi-k3")
    get_settings.cache_clear()
    try:
        s = get_settings()
        assert s.writer_base_url == "https://api.sensenova.cn/compatible-mode/v2"
        assert s.writer_api_key == "sk-w"
        assert s.writer_model == "kimi-k3"
    finally:
        get_settings.cache_clear()
    # 空串 = 未设（A7 各自独立回落）
    monkeypatch.setenv("WRITER_BASE_URL", "")
    monkeypatch.setenv("WRITER_API_KEY", "")
    monkeypatch.setenv("WRITER_MODEL", "")
    get_settings.cache_clear()
    try:
        s = get_settings()
        assert s.writer_base_url == "" and s.writer_api_key == "" and s.writer_model == ""
    finally:
        get_settings.cache_clear()


def test_temperature_env(monkeypatch):
    """A10/A11：NOVEL_TEMPERATURE 合法浮点生效；未设为 None。"""
    from novel_agent.config import get_settings
    monkeypatch.setenv("NOVEL_TEMPERATURE", "0.7")
    get_settings.cache_clear()
    try:
        assert get_settings().llm_temperature == 0.7
    finally:
        get_settings.cache_clear()
    monkeypatch.delenv("NOVEL_TEMPERATURE", raising=False)
    get_settings.cache_clear()
    try:
        assert get_settings().llm_temperature is None
    finally:
        get_settings.cache_clear()


def test_temperature_invalid_fail_fast(monkeypatch):
    """A14 纪律：非法浮点在配置加载阶段 fail-fast，报错含变量名。"""
    from novel_agent.config import get_settings
    monkeypatch.setenv("NOVEL_TEMPERATURE", "abc")
    get_settings.cache_clear()
    try:
        try:
            get_settings()
            assert False, "应抛错"
        except RuntimeError as e:
            assert "NOVEL_TEMPERATURE" in str(e)
    finally:
        get_settings.cache_clear()


def test_llm_extra_env(monkeypatch):
    """A13：NOVEL_LLM_EXTRA 合法 JSON 对象生效；未设为 {}。"""
    from novel_agent.config import get_settings
    monkeypatch.setenv("NOVEL_LLM_EXTRA", '{"reasoning_effort": "low"}')
    get_settings.cache_clear()
    try:
        assert get_settings().llm_extra == {"reasoning_effort": "low"}
    finally:
        get_settings.cache_clear()
    monkeypatch.delenv("NOVEL_LLM_EXTRA", raising=False)
    get_settings.cache_clear()
    try:
        assert get_settings().llm_extra == {}
    finally:
        get_settings.cache_clear()


def test_llm_extra_invalid_json_fail_fast(monkeypatch):
    """A14：非法 JSON 在配置加载阶段 fail-fast，报错含变量名。"""
    from novel_agent.config import get_settings
    monkeypatch.setenv("NOVEL_LLM_EXTRA", "{not json")
    get_settings.cache_clear()
    try:
        try:
            get_settings()
            assert False, "应抛错"
        except RuntimeError as e:
            assert "NOVEL_LLM_EXTRA" in str(e)
    finally:
        get_settings.cache_clear()


def test_llm_extra_non_object_fail_fast(monkeypatch):
    """A14：非对象（数组）同样 fail-fast。"""
    from novel_agent.config import get_settings
    monkeypatch.setenv("NOVEL_LLM_EXTRA", "[1, 2]")
    get_settings.cache_clear()
    try:
        try:
            get_settings()
            assert False, "应抛错"
        except RuntimeError as e:
            assert "NOVEL_LLM_EXTRA" in str(e) and "JSON 对象" in str(e)
    finally:
        get_settings.cache_clear()


def test_no_llm_envs_keeps_current_behavior(monkeypatch):
    """A4：全部 0.7 变量未设时与现状一致（火山端点 + glm-5.2 + 各字段空/None）。"""
    from novel_agent.config import get_settings
    for var in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL",
                "WRITER_BASE_URL", "WRITER_API_KEY", "WRITER_MODEL",
                "NOVEL_TEMPERATURE", "NOVEL_LLM_EXTRA", "CLAUDE_MODEL"):
        monkeypatch.delenv(var, raising=False)
    get_settings.cache_clear()
    try:
        s = get_settings()
        assert s.base_url == "https://ark.cn-beijing.volces.com/api/coding/v3"
        assert s.model == "glm-5.2"
        assert s.llm_api_key == "" and s.writer_base_url == ""
        assert s.writer_api_key == "" and s.writer_model == ""
        assert s.llm_temperature is None and s.llm_extra == {}
    finally:
        get_settings.cache_clear()
