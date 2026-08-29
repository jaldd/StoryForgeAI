"""LLM 客户端：封装 OpenAI 兼容网关调用（火山方舟为默认回落）。

从 py/multiagent_novel.py 的 call_model 抽出，改进：
- 去掉调试 print
- 保留控制字符清洗（避免网关静默空回）+ 指数退避重试（应对偶发空回/限流）
- 可注入 client（测试 mock）：传入带 .chat.completions.create 的任意对象即可
- 最后一次失败不再多睡
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from openai import OpenAI

from .config import Settings, get_settings

__all__ = ["LLMClient", "ModelProfile", "Profiles", "clean_text", "load_profiles"]

# 控制字符（含 NUL \x00、除 \t \n 外）一律去掉，避免火山网关静默空回
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_MULTI_NL_RE = re.compile(r"\n{3,}")


def clean_text(s: str) -> str:
    """清洗：去控制字符（含 NUL），压缩多余换行。"""
    if not s:
        return ""
    s = _CTRL_RE.sub("", s)
    s = _MULTI_NL_RE.sub("\n\n", s)
    return s.strip()


@dataclass(frozen=True)
class ModelProfile:
    """单角色模型来源：base_url/api_key/model + 可选行为参数。"""

    base_url: str
    api_key: str
    model: str
    temperature: Optional[float] = None      # None = 不覆盖，用调用点现值
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Profiles:
    default: ModelProfile   # 审稿/摘要/评分等全部非生成调用
    writer: ModelProfile    # writer/polisher/partial_refine


def load_profiles(settings: Optional[Settings] = None) -> Profiles:
    """从 Settings 解析双角色 profile（纯函数：只吃 Settings，不读 env、不联网）。

    WRITER_* 空串回落 default 同名字段；temperature 只挂 writer（A10-A12）；
    extra 同值进两个 profile（Z4）。
    """
    s = settings or get_settings()
    default = ModelProfile(
        base_url=s.base_url,
        api_key=s.llm_api_key or s.ark_api_key,
        model=s.model,
        temperature=None,                    # 主配置永不带温度覆盖（A12 由构造保证）
        extra=dict(s.llm_extra),
    )
    writer = ModelProfile(
        base_url=s.writer_base_url or default.base_url,
        api_key=s.writer_api_key or default.api_key,
        model=s.writer_model or default.model,
        temperature=s.llm_temperature,       # NOVEL_TEMPERATURE 只挂 writer（A10-A12）
        extra=dict(s.llm_extra),
    )
    return Profiles(default=default, writer=writer)


# 思考块标签（拼接写法：源码不出现完整标签字面量，防文档管道误吃）
_THINK_OPEN = "<" + "think" + ">"
_THINK_CLOSE = "</" + "think" + ">"
_THINK_BLOCK_RE = re.compile(
    _THINK_OPEN + r".*?" + _THINK_CLOSE + r"\s*", re.DOTALL
)


def _strip_think_blocks(text: str) -> str:
    """剥思考块：完整对（DOTALL 非贪婪）+ 未闭合前缀（从标签处剥到结尾）。"""
    if not text:
        return text
    out = _THINK_BLOCK_RE.sub("", text)
    idx = out.find(_THINK_OPEN)
    if idx != -1 and _THINK_CLOSE not in out:
        out = out[:idx]
    return out


class LLMClient:
    """单次 chat completion 调用封装，带重试。

    用法：
        llm = LLMClient()              # 用 get_settings() 的配置
        text = llm.chat(system, user)
    测试：
        llm = LLMClient(client=fake)   # 注入 fake client，不联网
    """

    def __init__(
        self,
        settings: Optional[Settings] = None,
        client: Any = None,
        profile: Optional[ModelProfile] = None,
    ):
        self.settings = settings or get_settings()
        self._client = client
        # None -> 主配置；writer 注入见 cli._build_agent
        self.profile = (
            profile if profile is not None else load_profiles(self.settings).default
        )

    @property
    def client(self) -> Any:
        """惰性创建 OpenAI client（缺 key 时这里才报错，便于无 key 测试）。"""
        if self._client is None:
            if not self.profile.api_key:
                raise RuntimeError("chat 调用缺 API key：设置 LLM_API_KEY（或 ARK_API_KEY）")
            self._client = OpenAI(
                api_key=self.profile.api_key,
                base_url=self.profile.base_url,
            )
        return self._client

    def chat(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int = 1024,
        temperature: float = 0.9,
        max_retries: int = 5,
    ) -> str:
        """一次模型调用，返回生成文本；多次重试仍空则返回 ""。"""
        system = clean_text(system)
        user = clean_text(user)
        # 温度覆盖：profile 配了温度则压掉调用点现值（仅 writer profile 可能配）
        effective = (
            temperature if self.profile.temperature is None else self.profile.temperature
        )
        req = {
            "model": self.profile.model,
            "max_tokens": max_tokens,
            "temperature": effective,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        req.update(self.profile.extra)  # 在内建 kwargs 之后：同名键 extra 赢（Z2）
        last_err = ""
        print("  ⏳ 等待模型响应...")
        for attempt in range(1, max_retries + 1):
            try:
                resp = self.client.chat.completions.create(**req)
                content = (resp.choices[0].message.content or "").strip()
                if content:
                    return _strip_think_blocks(content)
                # 空回：finish_reason 可能是 content_filter / length / stop
                last_err = f"empty content, finish_reason={resp.choices[0].finish_reason}"
            except Exception as e:  # 网络/限流/网关错误
                last_err = str(e)
            # 指数退避：2/4/8/16/32 秒；最后一次不再多睡
            if attempt < max_retries:
                time.sleep(2 ** attempt)
        return ""
