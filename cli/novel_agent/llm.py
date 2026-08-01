"""LLM 客户端：封装火山方舟 OpenAI 兼容网关调用。

从 py/multiagent_novel.py 的 call_model 抽出，改进：
- 去掉调试 print
- 保留控制字符清洗（避免网关静默空回）+ 指数退避重试（应对偶发空回/限流）
- 可注入 client（测试 mock）：传入带 .chat.completions.create 的任意对象即可
- 最后一次失败不再多睡
"""
from __future__ import annotations

import re
import time
from typing import Any, Optional

from openai import OpenAI

from .config import Settings, get_settings

__all__ = ["LLMClient", "clean_text"]

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


class LLMClient:
    """单次 chat completion 调用封装，带重试。

    用法：
        llm = LLMClient()              # 用 get_settings() 的配置
        text = llm.chat(system, user)
    测试：
        llm = LLMClient(client=fake)   # 注入 fake client，不联网
    """

    def __init__(self, settings: Optional[Settings] = None, client: Any = None):
        self.settings = settings or get_settings()
        self._client = client

    @property
    def client(self) -> Any:
        """惰性创建 OpenAI client（缺 key 时这里才报错，便于无 key 测试）。"""
        if self._client is None:
            self._client = OpenAI(
                api_key=self.settings.require_api_key(),
                base_url=self.settings.base_url,
            )
        return self._client

    def chat(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int = 800,
        temperature: float = 0.9,
        max_retries: int = 5,
    ) -> str:
        """一次模型调用，返回生成文本；多次重试仍空则返回 ""。"""
        system = clean_text(system)
        user = clean_text(user)
        last_err = ""
        for attempt in range(1, max_retries + 1):
            try:
                resp = self.client.chat.completions.create(
                    model=self.settings.model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                )
                content = (resp.choices[0].message.content or "").strip()
                if content:
                    return content
                # 空回：finish_reason 可能是 content_filter / length / stop
                last_err = f"empty content, finish_reason={resp.choices[0].finish_reason}"
            except Exception as e:  # 网络/限流/网关错误
                last_err = str(e)
            # 指数退避：2/4/8/16/32 秒；最后一次不再多睡
            if attempt < max_retries:
                time.sleep(2 ** attempt)
        return ""
