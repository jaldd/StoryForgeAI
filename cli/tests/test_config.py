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
    assert tmp_settings.exemplar_tags_full == novel / "文风基准/样文标签.md"  # exemplar-routing
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


# ---------- exemplar-routing：标签文件路径 ----------
def test_exemplar_tags_subpath_empty(tmp_settings):
    """exemplar_tags_subpath 留空 = 显式禁用路由：exemplar_tags_full 不指向存在文件。"""
    s = Settings(
        ark_api_key="k",
        repo_root=tmp_settings.repo_root,
        novel_dir=tmp_settings.novel_dir,
        exemplar_tags_subpath="",
    )
    assert s.exemplar_tags_full == s.novel_path / ""
    assert not s.exemplar_tags_full.is_file()


def test_exemplar_tags_env(monkeypatch):
    """NOVEL_EXEMPLAR_TAGS 环境变量生效（自定义标签文件路径）。"""
    from novel_agent.config import get_settings
    monkeypatch.setenv("NOVEL_EXEMPLAR_TAGS", "文风基准/我的标签.md")
    get_settings.cache_clear()
    try:
        s = get_settings()
        assert s.exemplar_tags_subpath == "文风基准/我的标签.md"
        assert s.exemplar_tags_full == s.novel_path / "文风基准/我的标签.md"
    finally:
        get_settings.cache_clear()


def test_reasoning_effort_env(monkeypatch):
    """NOVEL_REASONING_EFFORT / NOVEL_WRITER_REASONING_EFFORT 环境变量生效。"""
    from novel_agent.config import get_settings
    monkeypatch.setenv("NOVEL_REASONING_EFFORT", "low")
    monkeypatch.setenv("NOVEL_WRITER_REASONING_EFFORT", "max")
    get_settings.cache_clear()
    try:
        s = get_settings()
        assert s.reasoning_effort == "low"
        assert s.writer_reasoning_effort == "max"
    finally:
        get_settings.cache_clear()


def test_agent_temperature_env(monkeypatch):
    """NOVEL_{WRITER,POLISHER,REVIEWER}_TEMPERATURE 环境变量生效。"""
    from novel_agent.config import get_settings
    monkeypatch.setenv("NOVEL_WRITER_TEMPERATURE", "0.9")
    monkeypatch.setenv("NOVEL_POLISHER_TEMPERATURE", "0.5")
    monkeypatch.setenv("NOVEL_REVIEWER_TEMPERATURE", "0.3")
    get_settings.cache_clear()
    try:
        s = get_settings()
        assert s.writer_temperature == 0.9
        assert s.polisher_temperature == 0.5
        assert s.reviewer_temperature == 0.3
    finally:
        get_settings.cache_clear()


def test_aux_temperature_env(monkeypatch):
    """辅助角色温度 env 接线：ROUTER/FIXER/JUDGE/SUMMARIZER。"""
    from novel_agent.config import get_settings
    monkeypatch.setenv("NOVEL_ROUTER_TEMPERATURE", "0.1")
    monkeypatch.setenv("NOVEL_FIXER_TEMPERATURE", "0.4")
    monkeypatch.setenv("NOVEL_JUDGE_TEMPERATURE", "0.2")
    monkeypatch.setenv("NOVEL_SUMMARIZER_TEMPERATURE", "0.35")
    get_settings.cache_clear()
    try:
        s = get_settings()
        assert s.router_temperature == 0.1
        assert s.fixer_temperature == 0.4
        assert s.judge_temperature == 0.2
        assert s.summarizer_temperature == 0.35
    finally:
        get_settings.cache_clear()


# ---------- 伏笔追踪（3.1 foreshadow，F11/F12/Z1）----------
def test_foreshadow_defaults():
    """默认：回路开、温度 None（走调用点 0.2）、cap 30。"""
    from novel_agent.config import get_settings
    get_settings.cache_clear()
    try:
        s = get_settings()
        assert s.foreshadow_enabled is True
        assert s.foreshadow_temperature is None
        assert s.foreshadow_cap == 30
    finally:
        get_settings.cache_clear()


def test_foreshadow_env_overrides(monkeypatch):
    """三个 env 都生效：0 = 关回路；温度可配；cap=0 = 不截断。"""
    from novel_agent.config import get_settings
    monkeypatch.setenv("NOVEL_FORESHADOW", "0")
    monkeypatch.setenv("NOVEL_FORESHADOW_TEMPERATURE", "0.15")
    monkeypatch.setenv("NOVEL_FORESHADOW_CAP", "0")
    get_settings.cache_clear()
    try:
        s = get_settings()
        assert s.foreshadow_enabled is False
        assert s.foreshadow_temperature == 0.15
        assert s.foreshadow_cap == 0
    finally:
        get_settings.cache_clear()


def test_foreshadow_temperature_invalid_fails_fast(monkeypatch):
    """温度非法值 fail-fast（同 _env_float 既有纪律）。"""
    import pytest

    from novel_agent.config import get_settings
    monkeypatch.setenv("NOVEL_FORESHADOW_TEMPERATURE", "abc")
    get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError):
            get_settings()
    finally:
        get_settings.cache_clear()


# ---------- 角色弧光（3.2 character-arc，C11/C12/Z1）----------
def test_arc_defaults():
    """默认：回路开、温度 None（走调用点 0.2）、cap 8。"""
    from novel_agent.config import get_settings
    get_settings.cache_clear()
    try:
        s = get_settings()
        assert s.arc_enabled is True
        assert s.arc_temperature is None
        assert s.arc_cap == 8
    finally:
        get_settings.cache_clear()


def test_arc_env_overrides(monkeypatch):
    """三个 env 都生效：0 = 关回路；温度可配；cap=0 = 不截断。"""
    from novel_agent.config import get_settings
    monkeypatch.setenv("NOVEL_ARC", "0")
    monkeypatch.setenv("NOVEL_ARC_TEMPERATURE", "0.1")
    monkeypatch.setenv("NOVEL_ARC_CAP", "0")
    get_settings.cache_clear()
    try:
        s = get_settings()
        assert s.arc_enabled is False
        assert s.arc_temperature == 0.1
        assert s.arc_cap == 0
    finally:
        get_settings.cache_clear()


def test_arc_temperature_invalid_fails_fast(monkeypatch):
    """温度非法值 fail-fast（同 _env_float 既有纪律）。"""
    import pytest

    from novel_agent.config import get_settings
    monkeypatch.setenv("NOVEL_ARC_TEMPERATURE", "abc")
    get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError):
            get_settings()
    finally:
        get_settings.cache_clear()


# ---------- 卷对齐落盘（volume-align，V5/Z1）----------
def test_volume_align_default_off():
    """默认关（opt-in）：现状平铺落盘零变化。"""
    from novel_agent.config import get_settings
    get_settings.cache_clear()
    try:
        assert get_settings().volume_align is False
    finally:
        get_settings.cache_clear()


def test_planner_default_off():
    """3.3 planner 默认关（opt-in）：现状 writer 自行构思零变化。"""
    from novel_agent.config import get_settings
    get_settings.cache_clear()
    try:
        assert get_settings().planner_enabled is False
        assert get_settings().planner_temperature is None
    finally:
        get_settings.cache_clear()


def test_planner_env_overrides(monkeypatch):
    """NOVEL_PLANNER=1 开 / =0 关；NOVEL_PLANNER_TEMPERATURE 覆盖默认。"""
    from novel_agent.config import get_settings
    monkeypatch.setenv("NOVEL_PLANNER", "1")
    monkeypatch.setenv("NOVEL_PLANNER_TEMPERATURE", "0.4")
    get_settings.cache_clear()
    try:
        assert get_settings().planner_enabled is True
        assert get_settings().planner_temperature == 0.4
    finally:
        get_settings.cache_clear()
    monkeypatch.setenv("NOVEL_PLANNER", "0")
    monkeypatch.delenv("NOVEL_PLANNER_TEMPERATURE", raising=False)
    get_settings.cache_clear()
    try:
        assert get_settings().planner_enabled is False
        assert get_settings().planner_temperature is None
    finally:
        get_settings.cache_clear()


def test_volume_align_env_overrides(monkeypatch):
    """NOVEL_VOLUME_ALIGN=1 开 / =0 关。"""
    from novel_agent.config import get_settings
    monkeypatch.setenv("NOVEL_VOLUME_ALIGN", "1")
    get_settings.cache_clear()
    try:
        assert get_settings().volume_align is True
    finally:
        get_settings.cache_clear()
    monkeypatch.setenv("NOVEL_VOLUME_ALIGN", "0")
    get_settings.cache_clear()
    try:
        assert get_settings().volume_align is False
    finally:
        get_settings.cache_clear()


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
    assert s.max_reviews == 6
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


# ---------- 1.1 质量门禁（quality-gate T1）----------
def test_quality_paths_default(tmp_settings):
    """A23/A27：质量规则与人工语料默认路径。"""
    assert tmp_settings.quality_rules_subpath == "质量规则.json"
    assert tmp_settings.human_text_subpath == "正文"
    assert tmp_settings.quality_rules_full == tmp_settings.novel_path / "质量规则.json"
    assert tmp_settings.human_text_full == tmp_settings.novel_path / "正文"


def test_quality_rules_env_wiring(monkeypatch):
    """A23：NOVEL_QUALITY_RULES / NOVEL_HUMAN_TEXT 接线；空串 = 禁用（full 退回 novel_path）。

    get_settings 带 @lru_cache(maxsize=1)：setenv 后必须先 cache_clear
    才能读到新值，收尾再 clear 一次防污染其他用例（0.8 纪律）。
    """
    from novel_agent.config import get_settings
    monkeypatch.setenv("NOVEL_QUALITY_RULES", "设定/门禁.json")
    monkeypatch.setenv("NOVEL_HUMAN_TEXT", "正文/旧稿")
    get_settings.cache_clear()
    try:
        s = get_settings()
        assert s.quality_rules_subpath == "设定/门禁.json"
        assert s.human_text_subpath == "正文/旧稿"
        assert s.quality_rules_full.name == "门禁.json"
        assert s.human_text_full.name == "旧稿"
    finally:
        get_settings.cache_clear()
    # 空串 = 禁用：full 退回 novel_path（同 rules_subpath 空串先例）
    monkeypatch.setenv("NOVEL_QUALITY_RULES", "")
    monkeypatch.setenv("NOVEL_HUMAN_TEXT", "")
    get_settings.cache_clear()
    try:
        s = get_settings()
        assert s.quality_rules_subpath == "" and s.human_text_subpath == ""
        assert s.quality_rules_full == s.novel_path
        assert s.human_text_full == s.novel_path
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


# ---------- 1.5 滚动注入（style-loop T1）----------
def test_style_injection_defaults():
    """B1/B18：默认 recent_n=3、slice_chars=1000。"""
    s = Settings(ark_api_key="k")
    assert s.style_recent_n == 3
    assert s.style_slice_chars == 1000


def test_style_injection_env(monkeypatch):
    """B1：NOVEL_STYLE_RECENT_N / NOVEL_STYLE_SLICE_CHARS 环境变量生效；0 值合法解析。"""
    from novel_agent.config import get_settings
    monkeypatch.setenv("NOVEL_STYLE_RECENT_N", "5")
    monkeypatch.setenv("NOVEL_STYLE_SLICE_CHARS", "800")
    get_settings.cache_clear()
    try:
        s = get_settings()
        assert s.style_recent_n == 5
        assert s.style_slice_chars == 800
    finally:
        get_settings.cache_clear()
    # 0 值合法：0 = 禁用注入 / 不截断（B18 降级开关）
    monkeypatch.setenv("NOVEL_STYLE_RECENT_N", "0")
    monkeypatch.setenv("NOVEL_STYLE_SLICE_CHARS", "0")
    get_settings.cache_clear()
    try:
        s = get_settings()
        assert s.style_recent_n == 0
        assert s.style_slice_chars == 0
    finally:
        get_settings.cache_clear()


# ---------- 2.1/2.2 吞吐（throughput W1）----------
def test_throughput_defaults():
    """T21/T26：默认 stream=True、batch_max=10、chapter_plan_subpath=每章.md。"""
    s = Settings(ark_api_key="k")
    assert s.stream is True
    assert s.batch_max == 10
    assert s.chapter_plan_subpath == "每章.md"
    assert s.plan_full == s.novel_path / "每章.md"


def test_throughput_env(monkeypatch):
    """T26：NOVEL_STREAM / NOVEL_BATCH_MAX / NOVEL_CHAPTER_PLAN 接线；0/空为合法降级值。"""
    from novel_agent.config import get_settings
    monkeypatch.setenv("NOVEL_STREAM", "0")
    monkeypatch.setenv("NOVEL_BATCH_MAX", "5")
    monkeypatch.setenv("NOVEL_CHAPTER_PLAN", "规划/章节表.md")
    get_settings.cache_clear()
    try:
        s = get_settings()
        assert s.stream is False
        assert s.batch_max == 5
        assert s.chapter_plan_subpath == "规划/章节表.md"
        assert s.plan_full.name == "章节表.md"
    finally:
        get_settings.cache_clear()
    # 章纲留空 = 禁用：plan_full 退回 novel_path（同 rules_subpath 空串先例）
    monkeypatch.setenv("NOVEL_CHAPTER_PLAN", "")
    monkeypatch.setenv("NOVEL_STREAM", "1")
    get_settings.cache_clear()
    try:
        s = get_settings()
        assert s.stream is True
        assert s.chapter_plan_subpath == ""
        assert s.plan_full == s.novel_path
    finally:
        get_settings.cache_clear()


def test_plan_full_empty_subpath(tmp_settings):
    """T14：chapter_plan_subpath 留空时 plan_full 退回 novel_path。"""
    s = Settings(
        ark_api_key="k",
        repo_root=tmp_settings.repo_root,
        novel_dir=tmp_settings.novel_dir,
        chapter_plan_subpath="",
    )
    assert s.plan_full == s.novel_path
