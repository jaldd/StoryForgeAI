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
        assert p.default.temperature is None            # 主配置永不带温度覆盖
        assert p.default.extra == {}
        # 未配 WRITER_*：writer 逐字段回落 default
        assert p.writer == p.default

    def test_writer_model_only_partial_override(self):
        """只配 WRITER_MODEL：writer.model 覆盖，其余仍回落 default。"""
        p = load_profiles(_settings(writer_model="kimi-k3"))
        assert p.writer.model == "kimi-k3"
        assert p.writer.base_url == p.default.base_url
        assert p.writer.api_key == p.default.api_key
        assert p.writer.temperature is None

    def test_fully_configured_writer_independent(self):
        """全配：writer 完整独立（含 llm_api_key 高于 ark_api_key 的主键链）。"""
        p = load_profiles(
            _settings(
                llm_api_key="llm-key",
                writer_base_url="https://kimi.example/v1",
                writer_api_key="writer-key",
                writer_model="kimi-k3",
                llm_temperature=0.7,
                llm_extra={"max_tokens": 8192},
            )
        )
        assert p.default.api_key == "llm-key"           # llm_api_key 优先
        assert p.writer.base_url == "https://kimi.example/v1"
        assert p.writer.api_key == "writer-key"
        assert p.writer.model == "kimi-k3"
        assert p.writer.temperature == 0.7
        assert p.writer.extra == {"max_tokens": 8192}

    def test_temperature_none_when_unset(self):
        """llm_temperature 未设（None）：writer.temperature 为 None（哨兵=不覆盖）。"""
        p = load_profiles(_settings())
        assert p.writer.temperature is None

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
    """最小伪 OpenAI response：choices[0].message.content / finish_reason。"""

    def __init__(self, content: str):
        msg = type("M", (), {"content": content})()
        self.choices = [type("C", (), {"message": msg, "finish_reason": "stop"})()]


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

    def test_temperature_none_uses_call_site_value(self):
        """profile.temperature=None（哨兵）：用调用点现值。"""
        spy = SpyClient()
        profile = ModelProfile(base_url="u", api_key="k", model="m")
        LLMClient(client=spy, profile=profile).chat("sys", "user", temperature=0.6)
        assert spy.kwargs["temperature"] == 0.6

    def test_temperature_set_overrides_call_site(self):
        """profile.temperature 设值：压掉调用点现值（仅 writer profile 可能配）。"""
        spy = SpyClient()
        profile = ModelProfile(base_url="u", api_key="k", model="m", temperature=0.7)
        LLMClient(client=spy, profile=profile).chat("sys", "user", temperature=0.6)
        assert spy.kwargs["temperature"] == 0.7

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
