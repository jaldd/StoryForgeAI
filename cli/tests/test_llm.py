"""llm.py 测试：load_profiles 纯函数 / LLMClient profile / 思考块剥除。

全程不联网：load_profiles 直构 Settings（纯函数无 env 依赖）；LLMClient 注入
SpyClient（伪造 client 记录 create kwargs）；_strip_think_blocks 纯函数直测。
"""
from __future__ import annotations

import pytest

from novel_agent.config import Settings
from novel_agent.llm import (
    LLMClient,
    ModelProfile,
    Profiles,
    _strip_think_blocks,
    load_profiles,
)

# 拼接写法：源码/文档不出现完整思考块标签字面量
_THINK_OPEN = "<" + "think" + ">"
_THINK_CLOSE = "</" + "think" + ">"


def _settings(**kw) -> Settings:
    """直构 Settings（绕过 get_settings 的 env 读与 lru_cache）。"""
    base = dict(
        ark_api_key="ark-key",
        base_url="https://ark.example/api/v3",
        model="glm-5.2",
    )
    base.update(kw)
    return Settings(**base)


# ---------------- T2：load_profiles 纯函数四态 ----------------


class TestLoadProfiles:
    def test_empty_settings_keeps_current_shape(self):
        """全空：与现状形状一致（writer == default，各字段同值）。"""
        p = load_profiles(_settings())
        assert p.default.base_url == "https://ark.example/api/v3"
        assert p.default.api_key == "ark-key"          # llm_api_key 空 -> ark_api_key
        assert p.default.model == "glm-5.2"
        assert p.default.extra == {}
        # 未配 WRITER_*：writer 逐字段回落 default
        assert p.writer == p.default

    def test_writer_model_only_partial_override(self):
        """只配 WRITER_MODEL：writer.model 覆盖，其余仍回落 default。"""
        p = load_profiles(_settings(writer_model="kimi-k3"))
        assert p.writer.model == "kimi-k3"
        assert p.writer.base_url == p.default.base_url
        assert p.writer.api_key == p.default.api_key

    def test_fully_configured_writer_independent(self):
        """全配：writer 完整独立（含 llm_api_key 高于 ark_api_key 的主键链）。"""
        p = load_profiles(
            _settings(
                llm_api_key="llm-key",
                writer_base_url="https://kimi.example/v1",
                writer_api_key="writer-key",
                writer_model="kimi-k3",
                llm_extra={"max_tokens": 8192},
            )
        )
        assert p.default.api_key == "llm-key"           # llm_api_key 优先
        assert p.writer.base_url == "https://kimi.example/v1"
        assert p.writer.api_key == "writer-key"
        assert p.writer.model == "kimi-k3"
        assert p.writer.extra == {"max_tokens": 8192}

    def test_extra_shared_by_both_profiles(self):
        """extra 同值进两个 profile（Z4）。"""
        p = load_profiles(_settings(llm_extra={"reasoning_effort": "low"}))
        assert p.default.extra == {"reasoning_effort": "low"}
        assert p.writer.extra == {"reasoning_effort": "low"}
        # 返回的是独立副本，改一个不影响另一个
        assert p.default.extra is not p.writer.extra

    def test_writer_falls_back_to_resolved_llm_key(self):
        """只配 ark key + WRITER_MODEL：writer.api_key 回落 ARK 解析值（两段式回落）。"""
        p = load_profiles(_settings(writer_model="kimi-k3"))
        assert p.writer.api_key == "ark-key"

    # ---------------- reasoning_effort（0.8 思考深度分流） ----------------

    def test_effort_unset_sends_nothing(self):
        """都不配：extra 不带 reasoning_effort（现状零漂移）。"""
        p = load_profiles(_settings())
        assert p.default.extra == {}
        assert p.writer.extra == {}

    def test_global_effort_applies_to_both(self):
        """只配全局：两 profile 都带（writer 继承）。"""
        p = load_profiles(_settings(reasoning_effort="low"))
        assert p.default.extra == {"reasoning_effort": "low"}
        assert p.writer.extra == {"reasoning_effort": "low"}

    def test_writer_effort_overrides_global(self):
        """全局 + writer 专属：各自生效（审稿深、写作浅的分流）。"""
        p = load_profiles(
            _settings(reasoning_effort="max", writer_reasoning_effort="low")
        )
        assert p.default.extra == {"reasoning_effort": "max"}
        assert p.writer.extra == {"reasoning_effort": "low"}

    def test_writer_effort_only_leaves_default_clean(self):
        """只配 writer 专属：default 不带参数、writer 带。"""
        p = load_profiles(_settings(writer_reasoning_effort="low"))
        assert p.default.extra == {}
        assert p.writer.extra == {"reasoning_effort": "low"}

    def test_llm_extra_effort_wins(self):
        """NOVEL_LLM_EXTRA 显式 reasoning_effort 赢过专用字段（Z2 逃生门）。"""
        p = load_profiles(
            _settings(
                reasoning_effort="low",
                llm_extra={"reasoning_effort": "high"},
            )
        )
        assert p.default.extra == {"reasoning_effort": "high"}
        assert p.writer.extra == {"reasoning_effort": "high"}


# ---------------- T4：_strip_think_blocks 纯函数四态 ----------------


class TestStripThinkBlocks:
    def test_complete_pair_stripped(self):
        """完整对：剥除（含闭合标签后的空白）。"""
        text = _THINK_OPEN + "内心戏" + _THINK_CLOSE + "\n正文内容"
        assert _strip_think_blocks(text) == "正文内容"

    def test_unclosed_prefix_stripped_to_start(self):
        """未闭合前缀：从标签开头整段丢弃（流式截断事故形态）。"""
        text = "正文A" + _THINK_OPEN + "未完成的思考"
        assert _strip_think_blocks(text) == "正文A"

    def test_no_tags_untouched(self):
        """无标签：原样返回。"""
        assert _strip_think_blocks("普通正文") == "普通正文"
        assert _strip_think_blocks("") == ""

    def test_pure_think_block_returns_empty(self):
        """纯思考块 -> 空串（落现有空回路径）。"""
        assert _strip_think_blocks(_THINK_OPEN + "全部是思考" + _THINK_CLOSE) == ""

    def test_multiple_blocks_all_stripped(self):
        """多个完整对全部剥除，中间正文保留。"""
        text = (
            _THINK_OPEN + "a" + _THINK_CLOSE
            + "正文1"
            + _THINK_OPEN + "b" + _THINK_CLOSE
            + "正文2"
        )
        assert _strip_think_blocks(text) == "正文1正文2"


# ---------------- T3：LLMClient 接 profile（SpyClient，不联网） ----------------


class _FakeResp:
    """最小伪 OpenAI response：choices[0].message.content / finish_reason。

    reasoning_content 模拟思考模型（GLM-5.3 等）把思考放独立字段的行为。
    """

    def __init__(self, content: str, finish: str = "stop", reasoning: str = ""):
        msg = type("M", (), {"content": content, "reasoning_content": reasoning})()
        self.choices = [type("C", (), {"message": msg, "finish_reason": finish})()]


class SpyClient:
    """伪 OpenAI client：记录 create kwargs，返回固定文本。

    self.client.chat.completions.create(**req) 链路映射到本类的 create。
    """

    def __init__(self, content: str = "正文内容"):
        self.content = content
        self.kwargs: dict = {}
        self.chat = self
        self.completions = self

    def create(self, **kwargs):
        self.kwargs = kwargs
        return _FakeResp(self.content)


class _ScriptedClient(SpyClient):
    """伪 OpenAI client：按脚本顺序返回响应/抛异常，记录每次 create kwargs。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.all_kwargs: list = []
        self.chat = self
        self.completions = self

    def create(self, **kwargs):
        self.all_kwargs.append(kwargs)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class TestLLMClientProfile:
    def test_model_from_profile(self):
        """model 来自 profile（原来读 settings.model）。"""
        spy = SpyClient()
        profile = ModelProfile(
            base_url="https://kimi.example/v1",
            api_key="k",
            model="kimi-k3",
        )
        LLMClient(client=spy, profile=profile).chat("sys", "user")
        assert spy.kwargs["model"] == "kimi-k3"

    def test_profile_none_falls_back_to_default(self):
        """profile=None 注入回落 default（模型/键同源）。"""
        s = _settings()
        spy = SpyClient()
        llm = LLMClient(settings=s, client=spy)
        assert llm.profile == load_profiles(s).default
        llm.chat("sys", "user")
        assert spy.kwargs["model"] == "glm-5.2"

    def test_temperature_uses_call_site_value(self):
        """调用点温度直传请求体（0.9 温度融合上移 agent._temp，profile 不再覆盖）。"""
        spy = SpyClient()
        profile = ModelProfile(base_url="u", api_key="k", model="m")
        LLMClient(client=spy, profile=profile).chat("sys", "user", temperature=0.6)
        assert spy.kwargs["temperature"] == 0.6

    def test_extra_merged_into_request(self):
        """extra 合并进请求体。"""
        spy = SpyClient()
        profile = ModelProfile(
            base_url="u", api_key="k", model="m",
            extra={"reasoning_effort": "high"},
        )
        LLMClient(client=spy, profile=profile).chat("sys", "user")
        assert spy.kwargs["reasoning_effort"] == "high"
        assert spy.kwargs["model"] == "m"

    def test_extra_same_key_wins_over_builtin(self):
        """extra 与内建同名键赢：max_tokens 覆盖调用点预算（Z2 逃生门）。"""
        spy = SpyClient()
        profile = ModelProfile(
            base_url="u", api_key="k", model="m",
            extra={"max_tokens": 8192},
        )
        LLMClient(client=spy, profile=profile).chat("sys", "user", max_tokens=1024)
        assert spy.kwargs["max_tokens"] == 8192

    def test_missing_key_error_names_both_vars(self):
        """缺 key 且惰性建 client 时报错，文案含两个变量名。"""
        llm = LLMClient(settings=Settings(ark_api_key=""))
        with pytest.raises(RuntimeError, match="LLM_API_KEY.*ARK_API_KEY"):
            _ = llm.client

    def test_missing_key_ok_when_client_injected(self):
        """无 key 但注入了 client：不触发惰性建 client，不报错（测试兼容）。"""
        spy = SpyClient()
        profile = ModelProfile(base_url="u", api_key="", model="m")
        llm = LLMClient(settings=Settings(ark_api_key=""), client=spy, profile=profile)
        assert llm.chat("sys", "user") == "正文内容"

    def test_chat_exit_strips_think_blocks(self):
        """chat() 出口统一剥思考块（A19 接线点）。"""
        spy = SpyClient(_THINK_OPEN + "思考" + _THINK_CLOSE + "正文")
        profile = ModelProfile(base_url="u", api_key="k", model="m")
        assert LLMClient(client=spy, profile=profile).chat("sys", "user") == "正文"

    def test_retry_and_empty_semantics_unchanged(self, monkeypatch):
        """重试/空回语义不动：空回重试 max_retries 次后返回 ""。"""
        monkeypatch.setattr("novel_agent.llm.time.sleep", lambda s: None)
        calls = {"n": 0}

        class EmptySpy(SpyClient):
            def create(self, **kwargs):
                calls["n"] += 1
                return _FakeResp("")

        spy = EmptySpy()
        profile = ModelProfile(base_url="u", api_key="k", model="m")
        out = LLMClient(client=spy, profile=profile).chat(
            "sys", "user", max_retries=3
        )
        assert out == ""
        assert calls["n"] == 3


# ---------------- 思考模型：max_tokens 翻倍重试 ----------------


class TestThinkingModelDoubling:
    def test_thinking_exhausted_doubles_and_succeeds(self, monkeypatch):
        """思考烧光 max_tokens：翻倍重试后成功，第二次请求 max_tokens 翻倍。"""
        monkeypatch.setattr("novel_agent.llm.time.sleep", lambda s: None)
        exhausted = _FakeResp("", finish="length", reasoning="（很长的思考）")
        ok = _FakeResp("正文内容")
        spy = _ScriptedClient([exhausted, ok])
        profile = ModelProfile(base_url="u", api_key="k", model="m")
        out = LLMClient(client=spy, profile=profile).chat(
            "sys", "user", max_tokens=2048
        )
        assert out == "正文内容"
        assert spy.all_kwargs[0]["max_tokens"] == 2048
        assert spy.all_kwargs[1]["max_tokens"] == 4096

    def test_explicit_extra_max_tokens_never_doubles(self, monkeypatch):
        """extra 显式配 max_tokens：尊重配置不自动翻倍（Z2 逃生门）。"""
        monkeypatch.setattr("novel_agent.llm.time.sleep", lambda s: None)
        empty = _FakeResp("", finish="length", reasoning="思考")
        spy = _ScriptedClient([empty, empty, empty])
        profile = ModelProfile(
            base_url="u", api_key="k", model="m", extra={"max_tokens": 8192}
        )
        out = LLMClient(client=spy, profile=profile).chat(
            "sys", "user", max_tokens=1024, max_retries=3
        )
        assert out == ""
        assert [kw["max_tokens"] for kw in spy.all_kwargs] == [8192, 8192, 8192]

    def test_double_caps_at_limit(self, monkeypatch):
        """翻倍封顶 _MAX_TOKENS_CAP=16384，到顶后原值重试至耗尽。"""
        monkeypatch.setattr("novel_agent.llm.time.sleep", lambda s: None)
        empty = _FakeResp("", finish="length", reasoning="思考")
        spy = _ScriptedClient([empty] * 6)
        profile = ModelProfile(base_url="u", api_key="k", model="m")
        out = LLMClient(client=spy, profile=profile).chat(
            "sys", "user", max_tokens=8192, max_retries=6
        )
        assert out == ""
        assert [kw["max_tokens"] for kw in spy.all_kwargs] == [
            8192, 16384, 16384, 16384, 16384, 16384,
        ]

    def test_plain_empty_without_reasoning_keeps_original(self, monkeypatch):
        """普通空回（无 reasoning_content）：不翻倍，原样重试语义不变。"""
        monkeypatch.setattr("novel_agent.llm.time.sleep", lambda s: None)
        empty = _FakeResp("", finish="stop")
        spy = _ScriptedClient([empty, empty, empty])
        profile = ModelProfile(base_url="u", api_key="k", model="m")
        out = LLMClient(client=spy, profile=profile).chat(
            "sys", "user", max_tokens=2048, max_retries=3
        )
        assert out == ""
        assert [kw["max_tokens"] for kw in spy.all_kwargs] == [2048, 2048, 2048]


# ---------------- 思考模型：temperature=1 锁定 ----------------

_KIMI_TEMP_400 = Exception(
    "Error code: 400 - {'error': {'message': 'field Temperature invalid, "
    "only 1 is allowed for this model', 'type': 'invalid_request_error', "
    "'param': 'temperature', 'code': '3'}}"
)


class TestTemperatureLock:
    def test_temp_400_locks_one_and_retries(self, monkeypatch):
        """kimi-k3 式 temperature 400：锁定 1 立即重试成功。"""
        sleeps: list = []
        monkeypatch.setattr("novel_agent.llm.time.sleep", lambda s: sleeps.append(s))
        spy = _ScriptedClient([_KIMI_TEMP_400, _FakeResp("正文")])
        profile = ModelProfile(base_url="u", api_key="k", model="kimi-k3")
        out = LLMClient(client=spy, profile=profile).chat(
            "sys", "user", temperature=0.2
        )
        assert out == "正文"
        assert spy.all_kwargs[0]["temperature"] == 0.2
        assert spy.all_kwargs[1]["temperature"] == 1
        assert sleeps == []  # 参数错误不退避

    def test_other_400_not_locked(self, monkeypatch):
        """非 temperature 的 400：不锁定，正常退避重试到耗尽。"""
        monkeypatch.setattr("novel_agent.llm.time.sleep", lambda s: None)
        err = Exception("Error code: 400 - {'param': 'model'}")
        spy = _ScriptedClient([err, err, err])
        profile = ModelProfile(base_url="u", api_key="k", model="m")
        out = LLMClient(client=spy, profile=profile).chat(
            "sys", "user", temperature=0.8, max_retries=3
        )
        assert out == ""
        assert [kw["temperature"] for kw in spy.all_kwargs] == [0.8, 0.8, 0.8]
