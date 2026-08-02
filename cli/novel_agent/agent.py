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


def _review_result(data: dict) -> Tuple[bool, str]:
    """从解析出的 dict 取 (pass, reason)；有 issues 则折进 reason 便于回看。"""
    passed = bool(data.get("pass", True))
    reason = str(data.get("reason", ""))
    issues = data.get("issues") or []
    if issues:
        extra = "；".join(str(i) for i in issues)
        reason = f"{reason}；问题：{extra}" if reason else f"问题：{extra}"
    return passed, reason


def parse_review(text: str) -> Tuple[bool, str]:
    """解析审稿 JSON，返回 (是否通过, 原因)。容错 LLM 不规范输出。

    1) 直接 json.loads；
    2) 失败则取第一个 { 到最后一个 } 之间再解析；
    3) JSON 截断（没结尾 }）：补 } 再试；
    4) 都失败才兜底。
    """
    # 1) 直接解析
    try:
        return _review_result(json.loads(text))
    except (json.JSONDecodeError, TypeError):
        pass
    # 2) 提取第一个 { 到最后一个 } 之间再解析
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            return _review_result(json.loads(text[start:end + 1]))
        except json.JSONDecodeError:
            pass
    # 3) 截断兜底：有 { 但没结尾 }，逐个补 } 再试
    start = text.find("{")
    if start != -1:
        snippet = text[start:]
        for _ in range(3):
            snippet += "}"
            try:
                return _review_result(json.loads(snippet))
            except json.JSONDecodeError:
                pass
    # 4) 最终兜底
    if "不通过" in text or "false" in text.lower():
        return False, text[:200]
    return True, "（解析失败，默认通过）"


def _strip_polisher_meta(text: str) -> str:
    """截掉 polisher 混入的标题/说明，只留正文。

    - 遇到"## 润色说明"/"## 说明"即截断（其后是说明）；
    - 去掉开头的"## 润色后正文"等 meta 标题与空行。
    - 注意：--- 是场景分隔符，不能截断！
    干净正文（无 meta）原样返回。
    """
    if not text:
        return text
    out: List[str] = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("## 润色说明") or s == "## 说明":
            break
        out.append(line)
    text = "\n".join(out)
    # 去掉开头的 meta 标题（## 润色后正文 等）和空行
    lines = text.splitlines()
    while lines and (lines[0].strip().startswith("## 润色") or not lines[0].strip()):
        lines.pop(0)
    return "\n".join(lines).strip()


class NovelAgent:
    """小说创作 Agent：四角色状态机编排。

    依赖全部注入，便于测试（传 fake llm/rag 即可不联网跑完整流程）。
    """

    def __init__(
        self,
        llm: LLMClient,
        rag: Optional[RAGStore] = None,
        exemplar: str = "",
        instruction: str = "",
        settings: Optional[Settings] = None,
        working_memory: Optional[WorkingMemory] = None,
        max_reviews: Optional[int] = None,
        max_rounds: Optional[int] = None,
    ):
        self.llm = llm
        self.rag = rag
        self.exemplar = exemplar
        self.instruction = instruction
        self.settings = settings or get_settings()
        self.novel_name = self.settings.novel_name
        self.working_memory = working_memory
        self.max_reviews = self.settings.max_reviews if max_reviews is None else max_reviews
        self.max_rounds = self.settings.max_rounds if max_rounds is None else max_rounds
        # reviewer 打回目标：run 走 writer，refine 走 polisher（无 writer）
        self._reject_target = "writer"

        self.agents: Dict[str, Callable[[PipelineState], None]] = {
            "director": self._director,
            "writer": self._writer,
            "polisher": self._polisher,
            "reviewer": self._reviewer,
        }

    # ---------- RAG 检索辅助 ----------
    def _retrieve(self, task: str, with_prior: bool = True) -> str:
        """检索设定+人物（必须遵守）+ 前文（参考），拼成带出处分段的字符串。

        - writer/polisher：with_prior=True（含前文参考）
        - reviewer：with_prior=False（只看设定一致性，不管前文风格）
        内部固定 top_k=3。RAG 不可用或检索失败时返回空，不阻断流程。
        """
        if self.rag is None:
            return ""
        parts: List[str] = []
        try:
            # 1. 设定+人物（必须遵守）
            char_hits = self.rag.retrieve(task, top_k=3, doc_type="character")
            setting_hits = self.rag.retrieve(task, top_k=3, doc_type="setting")
            if char_hits or setting_hits:
                parts.append("【必须遵守的设定】（人设、世界观、规则，不可违背）")
                for txt, src in char_hits:
                    parts.append(f"[人物·{src}]\n{txt}")
                for txt, src in setting_hits:
                    parts.append(f"[设定·{src}]\n{txt}")

            # 2. 前文正文（参考，不是硬性规则）
            if with_prior:
                chap_hits = self.rag.retrieve(task, top_k=3, doc_type="chapter")
                if chap_hits:
                    parts.append("【前文参考】（已有正文，保持剧情连贯，不是硬性规则）")
                    for txt, src in chap_hits:
                        parts.append(f"[前文·{src}]\n{txt}")
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
        print("  ✍️  写作中（约30秒）...")
        retrieved = self._retrieve(state.task)
        system = writer_system(self.novel_name, retrieved, self.exemplar, self.instruction) + self._working_context()

        feedback_hint = ""
        if state.feedback and "不通过" in state.feedback:
            feedback_hint = f"\n\n【上次审稿意见，请据此改进】\n{state.feedback}"

        if state.source_content:
            user_msg = (
                f"参考以下已有内容，自由重写一个完整章节：{state.task}"
                "\n你可以自行决定参考多少，结构和情节可以调整，但要保留核心意图。"
                f"\n\n【已有内容（参考）】\n{state.source_content}"
                "\n请先用一段话说明构思（涉及人物、情绪走向、场景细节），然后用 === 分隔，再写正文。"
                f"{feedback_hint}"
            )
        else:
            user_msg = (
                f"写一段新章节：{state.task}。约200字，不要解释风代表什么。"
                f"\n请先用一段话说明构思（涉及人物、情绪走向、场景细节），然后用 === 分隔，再写正文。"
                f"{feedback_hint}"
            )

        raw = self.llm.chat(
            system,
            user_msg,
            max_tokens=4096,
            temperature=0.8,
        )
        # 按 === 分隔，丢弃构思说明，只取正文存入 draft
        if raw and "===" in raw:
            state.draft = raw.split("===", 1)[1].strip()
        else:
            state.draft = (raw or "").strip()
        if not state.draft:
            state.draft = f"（初稿兜底）{state.task}"
            state.log.append("[writer] 模型未返回内容，已用占位兜底")
        state.log.append(f"[writer] 写完初稿，{len(state.draft)} 字")
        state.next_agent = "polisher"

    def _polisher(self, state: PipelineState) -> None:
        """润色：查设定兜底，基于初稿润色。"""
        print("  🔧 润色中（约30秒）...")
        retrieved = self._retrieve(state.task)
        system = polisher_system(
            self.novel_name, retrieved, self.instruction
        )
        # 防止 GLM 把 --- 当结束标记截断，预处理换掉，润色后换回
        draft_safe = state.draft.replace("\n---\n", "\n【场景分隔】\n")
        # 打回重写时，把审稿意见传给 polisher
        feedback_hint = ""
        if state.feedback and "不通过" in state.feedback:
            feedback_hint = f"\n\n【上次审稿意见，必须据此改进】\n{state.feedback}"
        raw = self.llm.chat(
            system,
            f"以下是初稿，请润色：\n\n{draft_safe}{feedback_hint}",
            max_tokens=4096,
            temperature=0.6,
        )
        if not raw:
            state.polished = state.draft
            state.log.append("[polisher] 模型未返回内容，已用初稿兜底")
        else:
            state.polished = _strip_polisher_meta(raw)
            # 换回场景分隔符
            state.polished = state.polished.replace("【场景分隔】", "---")
            if not state.polished:
                state.polished = state.draft
                state.log.append("[polisher] 清洗后无正文，已用初稿兜底")
            elif len(state.polished) < len(state.draft) * 0.5:
                print(f"  ⚠️ 字数保护：{len(state.polished)} 字 < 原文50%（{len(state.draft)}字），保留初稿")
                state.log.append(
                    f"[polisher] ⚠️ 字数保护：{len(state.polished)} 字 < 原文50%（{len(state.draft)}字），保留初稿"
                )
                state.polished = state.draft
        state.log.append(f"[polisher] 完成，{len(state.polished)} 字")
        state.next_agent = "reviewer"

    def _reviewer(self, state: PipelineState) -> None:
        """审稿人：通过则定稿，不通过则打回 writer。"""
        if state.review_count >= self.max_reviews:
            state.feedback = f"审稿通过（已达打回上限 {self.max_reviews} 次，强制定稿）"
            state.final_chapter = state.polished
            state.log.append(f"[reviewer] {state.feedback}")
            state.next_agent = "done"
            return

        print("  🔍 审稿中（约10秒）...")
        retrieved = self._retrieve(state.task, with_prior=False)
        system = reviewer_system(self.novel_name, retrieved, self.instruction)
        result = self.llm.chat(
            system,
            f"请审查以下稿件：\n\n{state.polished}",
            max_tokens=2048,
            temperature=0.2,
        )
        passed, reason = parse_review(result)
        if "解析失败" in reason and result:
            state.log.append(f"[reviewer] 解析失败，原始返回前200字：{result[:200]}")

        if passed:
            state.feedback = f"审稿通过：{reason}"
            state.final_chapter = state.polished
            print(f"  ✅ 审稿通过：{reason}")
            state.log.append(f"[reviewer] {state.feedback}")
            state.next_agent = "done"
        else:
            state.review_count += 1
            state.feedback = f"审稿不通过（第{state.review_count}次）：{reason}"
            print(f"  ❌ 审稿不通过：{reason}，打回重写")
            state.log.append(f"[reviewer] {state.feedback}，打回 {self._reject_target}")
            state.next_agent = self._reject_target

    # ---------- 主循环 ----------
    def _run_loop(
        self,
        state: PipelineState,
        agents_map: Dict[str, Callable[[PipelineState], None]],
        steps: List[dict],
    ) -> None:
        """共享主循环：按 state.next_agent 跑到 done / 超限 / 未知 agent。"""
        while state.next_agent != "done":
            state.round += 1
            if state.round > self.max_rounds:
                state.log.append(f"[system] 超过 {self.max_rounds} 轮，强制定稿")
                state.final_chapter = state.polished or state.draft
                break

            agent = agents_map.get(state.next_agent)
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

    def _record(
        self, run_id: str, task: str, temperature: float,
        state: PipelineState, steps: List[dict],
    ) -> Dict[str, Any]:
        """构造运行记录，供 storage 落盘 / harness 回放。"""
        return {
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

    def run(
        self,
        task: str,
        run_id: Optional[str] = None,
        temperature: float = 0.9,
    ) -> Tuple[PipelineState, Dict[str, Any]]:
        """跑完整流程（director->writer->polisher->reviewer），返回 (state, record)。"""
        if run_id is None:
            run_id = "run_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

        state = PipelineState(task=task)
        steps: List[dict] = []
        self._run_loop(state, self.agents, steps)
        return state, self._record(run_id, task, temperature, state, steps)

    def refine(
        self,
        content: str,
        task: str,
        run_id: Optional[str] = None,
        temperature: float = 0.7,
    ) -> Tuple[PipelineState, Dict[str, Any]]:
        """精修已有正文：跳过 writer，直接从 polisher 开始打磨。

        - state.draft = 传入的正文（作为初稿）
        - state.next_agent = "polisher"（跳过 director 和 writer）
        - reviewer 不通过时打回 polisher（不回 writer，因为不写新场景）
        后面 polisher -> reviewer 循环与 run() 一致。
        """
        if run_id is None:
            run_id = "refine_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

        state = PipelineState(task=task)
        state.draft = content
        state.next_agent = "polisher"
        state.log.append(f"[refine] 精修开始，初稿 {len(content)} 字")

        refine_agents: Dict[str, Callable[[PipelineState], None]] = {
            "polisher": self._polisher,
            "reviewer": self._reviewer,
        }
        self._reject_target = "polisher"
        steps: List[dict] = []
        try:
            self._run_loop(state, refine_agents, steps)
        finally:
            self._reject_target = "writer"
        return state, self._record(run_id, task, temperature, state, steps)

    def rewrite(
        self,
        content: str,
        task: str,
        run_id: Optional[str] = None,
        temperature: float = 0.9,
    ) -> Tuple[PipelineState, Dict[str, Any]]:
        """重写已有正文：走 writer->polisher->reviewer，writer 参考原文自由重写。

        - state.source_content = 传入的正文（writer 作为参考）
        - state.next_agent = "writer"（跳过 director，直接写）
        - reviewer 不通过时打回 writer（和 run 一致，可重写场景）
        与 run() 的区别：writer 拿到已有内容作为参考，而非从零创作。
        与 refine() 的区别：走 writer 而非 polisher，能大幅扩写/重构。
        """
        if run_id is None:
            run_id = "rewrite_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

        state = PipelineState(task=task)
        state.source_content = content
        state.next_agent = "writer"
        state.log.append(f"[rewrite] 重写开始，参考原文 {len(content)} 字")

        rewrite_agents: Dict[str, Callable[[PipelineState], None]] = {
            "writer": self._writer,
            "polisher": self._polisher,
            "reviewer": self._reviewer,
        }
        steps: List[dict] = []
        self._run_loop(state, rewrite_agents, steps)
        return state, self._record(run_id, task, temperature, state, steps)
