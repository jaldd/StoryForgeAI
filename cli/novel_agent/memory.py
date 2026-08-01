"""三层记忆：从 py/agent_memory_volcano.py 迁移。

- ShortTermMemory：短期，最近 N 轮对话窗口
- WorkingMemory：工作记忆，小说当前客观状态（原 NovelState，改名避免和
  流水线 PipelineState 撞名）
- LongTermMemory：长期，溢出窗口的旧对话摘要

改进：LongTermMemory.summarize 改用 LLMClient（统一调用入口，可注入测试）。
"""
from __future__ import annotations

from typing import List, Optional

from .llm import LLMClient
from .prompts import SUMMARIZER_SYSTEM

__all__ = ["ShortTermMemory", "WorkingMemory", "LongTermMemory"]


class ShortTermMemory:
    """短期记忆：存最近几轮对话，超出窗口的留给长期记忆做摘要。"""

    def __init__(self, max_messages: int = 10):
        self.max_messages = max_messages
        self.history: List[dict] = []

    def add(self, message: dict) -> None:
        """往队尾加一条消息（user / assistant / tool 都行）。"""
        self.history.append(message)

    def recent(self) -> List[dict]:
        """窗口内的最近消息（每次问模型前塞进上下文）。"""
        return self.history[-self.max_messages:]

    def overflow(self) -> List[dict]:
        """窗口外被挤掉的旧消息（交给长期记忆摘要）。"""
        return self.history[: -self.max_messages] if len(self.history) > self.max_messages else []


class WorkingMemory:
    """工作记忆：记小说当前的客观状态（写到哪了），不记聊天内容。"""

    def __init__(self):
        self.current_chapter: Optional[int] = None
        self.character_states: dict = {}
        self.unresolved_foreshadowing: List[str] = []
        self.last_plot_point: Optional[str] = None

    def update_after_write(
        self,
        chapter_no: Optional[int],
        plot_summary: Optional[str],
        new_foreshadowing: Optional[List[str]] = None,
    ) -> None:
        """每写完一章调用一次，刷新状态。"""
        self.current_chapter = chapter_no
        self.last_plot_point = plot_summary
        if new_foreshadowing:
            self.unresolved_foreshadowing.extend(new_foreshadowing)

    def snapshot(self) -> str:
        """压成一段文字，塞进 system prompt 让模型知道"写到哪了"。"""
        return (
            f"当前进度：第{self.current_chapter}章。\n"
            f"最近剧情：{self.last_plot_point}\n"
            f"角色状态：{self.character_states}\n"
            f"未回收伏笔：{self.unresolved_foreshadowing}"
        )


class LongTermMemory:
    """长期记忆：把溢出窗口的旧对话摘要成精简文字，永久保留。"""

    def __init__(self):
        self.summaries: List[str] = []

    def summarize(self, old_messages: List, llm: LLMClient) -> str:
        """把溢出的旧消息丢给 LLM 压成摘要，返回摘要文本（由调用方决定是否存）。"""
        text = "\n".join(str(m) for m in old_messages)
        return llm.chat(
            SUMMARIZER_SYSTEM, text, max_tokens=300, temperature=0.3
        )

    def add_summary(self, text: str) -> None:
        """把新摘要存进列表，永久保留。"""
        if text:
            self.summaries.append(text)

    def context(self) -> str:
        """所有摘要拼起来，给模型当"很久以前的事"的备忘。"""
        return "\n".join(self.summaries)
