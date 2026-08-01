"""MultiAgent 编排：director -> writer -> polisher -> reviewer 状态机。

从 py/multiagent_novel.py 迁移，生产化：
- 去模块级全局（client/EXEMPLAR/rag._collection），改为 NovelAgent 持有依赖
- writer/polisher/reviewer 注入 LLMClient/RAGStore/exemplar，可测试
- WorkingMemory 注入：writer 把"当前写作状态"塞进上下文，实现跨章连续性（P1）
- run() 返回 (state, record)，落盘交给 storage（T8），不在本模块写文件
"""
from __future__ import annotations

import datetime
import json
import re
from dataclasses import asdict
from typing import Any, Callable, Dict, List, Optional, Tuple

from .config import Settings, get_settings
from .llm import LLMClient
from .memory import WorkingMemory
from .prompts import (
    polisher_system,
    reviewer_system,
    writer_system,
)
from .rag import RAGStore
from .state import PipelineState

__all__ = ["NovelAgent", "parse_review"]


def parse_review(text: str) -> Tuple[bool, str]:
    """解析审稿 JSON，返回 (是否通过, 原因)。容错 LLM 不规范输出。"""
    try:
        data = json.loads(text)
        return bool(data.get("pass", True)), str(data.get("reason", ""))
    except json.JSONDecodeError:
        pass
    # 容错：LLM 可能用 ```json 包裹或带多余文字，提取 JSON 片段
    match = re.search(r"\{[^}]+\}", text)
    if match:
        try:
            data = json.loads(match.group())
            return bool(data.get("pass", True)), str(data.get("reason", ""))
        except json.JSONDecodeError:
            pass
    # 最终兜底：看文本里有没有"不通过"
    if "不通过" in text or "false" in text.lower():
        return False, text[:200]
    return True, "（解析失败，默认通过）"


class NovelAgent:
    """小说创作 Agent：四角色状态机编排。

    依赖全部注入，便于测试（传 fake llm/rag 即可不联网跑完整流程）。
    """

    def __init__(
        self,
        llm: LLMClient,
        rag: Optional[RAGStore] = None,
        exemplar: str = "",
        settings: Optional[Settings] = None,
        working_memory: Optional[WorkingMemory] = None,
        max_reviews: Optional[int] = None,
        max_rounds: Optional[int] = None,
    ):
        self.llm = llm
        self.rag = rag
        self.exemplar = exemplar
        self.settings = settings or get_settings()
        self.working_memory = working_memory
        self.max_reviews = self.settings.max_reviews if max_reviews is None else max_reviews
        self.max_rounds = self.settings.max_rounds if max_rounds is None else max_rounds

        self.agents: Dict[str, Callable[[PipelineState], None]] = {
            "director": self._director,
            "writer": self._writer,
            "polisher": self._polisher,
            "reviewer": self._reviewer,
        }

    # ---------- RAG 检索辅助 ----------
    def _retrieve(self, task: str, char_k: int, chap_k: int) -> str:
        """按类型检索人物 + 前文，拼成带出处的字符串。RAG 不可用时返回空。"""
        if self.rag is None:
            return ""
        parts: List[str] = []
        try:
            if char_k:
                for txt, src in self.rag.retrieve(task, top_k=char_k, doc_type="character"):
                    parts.append(f"【人物·出自 {src}】\n{txt}")
            if chap_k:
                for txt, src in self.rag.retrieve(task, top_k=chap_k, doc_type="chapter"):
                    parts.append(f"【前文·出自 {src}】\n{txt}")
        except Exception as e:
            parts.append(f"【检索失败】{e}")
        return "\n\n".join(parts)

    def _working_context(self) -> str:
        """工作记忆快照（当前进度/角色/伏笔），让 writer 记得前文。

        仅在已写过至少一章（current_chapter 已设置）时给出，避免空状态噪音。
        """
        if self.working_memory is None or self.working_memory.current_chapter is None:
            return ""
        return f"\n--- 当前写作状态（工作记忆）---\n{self.working_memory.snapshot()}"

    # ---------- 四个 Agent ----------
    def _director(self, state: PipelineState) -> None:
        """导演：拿到任务，派给 Writer。"""
        state.log.append(f"[director] 收到任务：{state.task}")
        state.next_agent = "writer"

    def _writer(self, state: PipelineState) -> None:
        """写手：查设定 + 调模型产出初稿。"""
        retrieved = self._retrieve(state.task, char_k=3, chap_k=3)
        system = writer_system(retrieved, self.exemplar) + self._working_context()

        feedback_hint = ""
        if state.feedback and "不通过" in state.feedback:
            feedback_hint = f"\n\n【上次审稿意见，请据此改进】\n{state.feedback}"

        state.draft = self.llm.chat(
            system,
            f"写一段新章节：{state.task}。约200字，不要解释风代表什么。{feedback_hint}",
            max_tokens=4096,
            temperature=0.9,
        )
        if not state.draft:
            state.draft = f"（初稿兜底）{state.task}"
            state.log.append("[writer] 模型未返回内容，已用占位兜底")
        state.log.append(f"[writer] 写完初稿，{len(state.draft)} 字")
        state.next_agent = "polisher"

    def _polisher(self, state: PipelineState) -> None:
        """润色师：查设定兜底，基于初稿润色。"""
        retrieved = self._retrieve(state.task, char_k=2, chap_k=2)
        system = polisher_system(retrieved)
        state.polished = self.llm.chat(
            system,
            f"以下是初稿，请润色：\n\n{state.draft}",
            max_tokens=4096,
            temperature=0.7,
        )
        if not state.polished:
            state.polished = state.draft  # 兜底：保留初稿
            state.log.append("[polisher] 模型未返回内容，已用初稿兜底")
        state.log.append(f"[polisher] 润色完成，{len(state.polished)} 字")
        state.next_agent = "reviewer"

    def _reviewer(self, state: PipelineState) -> None:
        """审稿人：通过则定稿，不通过则打回 writer。"""
        if state.review_count >= self.max_reviews:
            state.feedback = f"审稿通过（已达打回上限 {self.max_reviews} 次，强制定稿）"
            state.final_chapter = state.polished
            state.log.append(f"[reviewer] {state.feedback}")
            state.next_agent = "done"
            return

        retrieved = self._retrieve(state.task, char_k=2, chap_k=0)
        system = reviewer_system(retrieved)
        result = self.llm.chat(
            system,
            f"请审查以下稿件：\n\n{state.polished}",
            max_tokens=1024,
            temperature=0.3,
        )
        passed, reason = parse_review(result)

        if passed:
            state.feedback = f"审稿通过：{reason}"
            state.final_chapter = state.polished
            state.log.append(f"[reviewer] {state.feedback}")
            state.next_agent = "done"
        else:
            state.review_count += 1
            state.feedback = f"审稿不通过（第{state.review_count}次）：{reason}"
            state.log.append(f"[reviewer] {state.feedback}，打回 writer 重写")
            state.next_agent = "writer"

    # ---------- 主循环 ----------
    def run(
        self,
        task: str,
        run_id: Optional[str] = None,
        temperature: float = 0.9,
    ) -> Tuple[PipelineState, Dict[str, Any]]:
        """跑完整流程，返回 (state, record)。record 供 storage 落盘 / harness 回放。"""
        if run_id is None:
            run_id = "run_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

        state = PipelineState(task=task)
        steps: List[dict] = []

        while state.next_agent != "done":
            state.round += 1
            if state.round > self.max_rounds:
                state.log.append(f"[system] 超过 {self.max_rounds} 轮，强制定稿")
                state.final_chapter = state.polished or state.draft
                break

            agent = self.agents.get(state.next_agent)
            if agent is None:
                state.log.append(f"[system] 未知 agent: {state.next_agent}")
                break

            which = state.next_agent
            before = asdict(state)
            agent(state)
            after = asdict(state)
            steps.append({
                "step_id": len(steps) + 1,
                "agent": which,
                "round": after["round"],
                "input_state": before,
                "output_state": after,
                "decision": after["next_agent"],
            })

        record = {
            "run_id": run_id,
            "task": task,
            "timestamp": datetime.datetime.now().isoformat(),
            "config": {
                "model": self.settings.model,
                "temperature": temperature,
                "max_rounds": self.max_rounds,
                "max_reviews": self.max_reviews,
            },
            "initial_state": asdict(PipelineState(task=task)),
            "steps": steps,
            "final_state": asdict(state),
        }
        return state, record
