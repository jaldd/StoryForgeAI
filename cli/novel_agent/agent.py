"""MultiAgent 编排：writer -> polisher -> reviewer 状态机。

从 py/multiagent_novel.py 迁移，生产化：
- 去模块级全局（client/EXEMPLAR/rag._collection），改为 NovelAgent 持有依赖
- writer/polisher/reviewer 注入 LLMClient/RAGStore/exemplar，可测试
- WorkingMemory 注入：writer/polisher/reviewer 把"当前写作状态"塞进上下文，实现跨章连续性
- run() 返回 (state, record)，落盘交给 storage（T8），不在本模块写文件
"""
from __future__ import annotations

import datetime
import json
from dataclasses import asdict
from typing import Any, Callable, Dict, List, Optional, Tuple

from .config import Settings, get_settings
from .llm import LLMClient, load_profiles
from .memory import WorkingMemory
from .partial import Block, build_context_pair
from .prompts import (
    COMPARE_SYSTEM,
    PARTIAL_REFINE_SUFFIX,
    PLOT_SUMMARY_SYSTEM,
    partial_refine_user,
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


def parse_review(text: str) -> Tuple[Optional[bool], str]:
    """解析审稿 JSON，返回 (是否通过, 原因)。容错 LLM 不规范输出。

    1) 直接 json.loads；
    2) 失败则取第一个 { 到最后一个 } 之间再解析；
    3) JSON 截断（没结尾 }）：补 } 再试；
    4) 都失败：文本含"不通过"/"false" 保守判不通过；否则返回 None（不可解析）。

    None 意味着不静默过审（0.1）：判定权上交--REPL 走人工确认，
    未来批量模式注入恒"弃"的 confirm 即 fail-closed，见 specs/stage0-batch。
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
    # 4) 最终兜底：不再默认通过（fail-open 是 0.1 要消灭的行为）
    if "不通过" in text or "false" in text.lower():
        return False, text[:200]
    return None, "（审稿结果不可解析）"


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


def _strip_code_fence(text: str) -> str:
    """剥掉 LLM 偶尔给整段输出套的 ``` 围栏（含 ```markdown 等语言标记）。

    非 ``` 开头原样返回；只有开头围栏没有结尾的取首行之后全部。
    """
    s = text.strip()
    if not s.startswith("```"):
        return text
    first_nl = s.find("\n")
    if first_nl == -1:
        return ""
    body = s[first_nl + 1:]
    stripped = body.rstrip()
    if stripped.endswith("```"):
        body = stripped[:-3]
    return body.strip()


def _split_writer_output(raw: str) -> Tuple[str, str]:
    """writer 输出按首个 === 切分，返回 (构思, 正文)。无分隔符时构思为空、正文为全文。"""
    if not raw:
        return "", ""
    if "===" in raw:
        outline, _, body = raw.partition("===")
        return outline.strip(), body.strip()
    return "", raw.strip()


class NovelAgent:
    """小说创作 Agent：三角色状态机编排。

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
        target_words: Optional[int] = None,
        review_confirm: Optional[Callable[[str], str]] = None,
        rules: str = "",
        writer_llm: Optional[LLMClient] = None,
    ):
        self.llm = llm
        self.rag = rag
        self.exemplar = exemplar
        self.instruction = instruction
        # 0.2：写作铁律全文（NOVEL_DIR 下「写作铁律.md」），注入 writer/polisher/reviewer。
        self.rules = rules
        self.settings = settings or get_settings()
        self.novel_name = self.settings.novel_name
        self.working_memory = working_memory
        self.max_reviews = self.settings.max_reviews if max_reviews is None else max_reviews
        self.max_rounds = self.settings.max_rounds if max_rounds is None else max_rounds
        # 0.8：单章目标字数（writer 写作 / polisher 扩写共用口径，进 prompt）
        self.target_words = self.settings.target_words if target_words is None else target_words
        # 0.7：写作侧独立模型来源（writer/polisher/局部精修）；None 回落 self.llm（A9）。
        self.writer_llm = writer_llm if writer_llm is not None else llm
        # 0.1：审稿结果不可解析时的人工确认函数（prompt -> 应答）。
        # None = REPL 交互 input；未来批量模式注入恒"弃"（返回"n"）即 fail-closed。
        self.review_confirm = review_confirm
        # reviewer 打回目标：run 走 writer，refine 走 polisher（无 writer）
        self._reject_target = "writer"

        self.agents: Dict[str, Callable[[PipelineState], None]] = {
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

    # ---------- 三个 Agent ----------
    def _writer(self, state: PipelineState) -> None:
        """写手：查设定 + 调模型产出初稿（构思与正文按 === 分离，构思存入 state.outline）。"""
        print("  ✍️  写作中（约30秒）...")
        retrieved = self._retrieve(state.task)
        system = writer_system(self.novel_name, retrieved, self.exemplar, self.instruction, self.rules) + self._working_context()

        feedback_hint = ""
        if state.feedback and "不通过" in state.feedback:
            feedback_hint = f"\n\n【上次审稿意见，请据此改进】\n{state.feedback}"

        if state.source_content:
            user_msg = (
                f"参考以下已有内容，自由重写一个完整章节：{state.task}。目标约{self.target_words}字。"
                "\n你可以自行决定参考多少，结构和情节可以调整，但要保留核心意图。"
                f"\n\n【已有内容（参考）】\n{state.source_content}"
                "\n请先用一段话说明构思（涉及人物、情绪走向、场景细节），然后用 === 分隔，再写正文。"
                f"{feedback_hint}"
            )
        else:
            user_msg = (
                f"写一段新章节：{state.task}。目标约{self.target_words}字。"
                f"\n请先用一段话说明构思（涉及人物、情绪走向、场景细节），然后用 === 分隔，再写正文。"
                f"{feedback_hint}"
            )

        raw = self.writer_llm.chat(
            system,
            user_msg,
            max_tokens=4096,
            temperature=0.8,
        )
        # 按 === 分隔：构思存入 state.outline（0.8 保留传递，供 polisher/reviewer/run 日志消费），正文进 draft
        outline, body = _split_writer_output(raw or "")
        state.outline = outline
        state.draft = body
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
            self.novel_name, retrieved, self.instruction,
            target_words=self.target_words, rules=self.rules,
        ) + self._working_context()
        # 防止 GLM 把 --- 当结束标记截断，预处理换掉，润色后换回
        draft_safe = state.draft.replace("\n---\n", "\n【场景分隔】\n")
        # 打回重写时，把审稿意见传给 polisher
        feedback_hint = ""
        if state.feedback and "不通过" in state.feedback:
            feedback_hint = f"\n\n【上次审稿意见，必须据此改进】\n{state.feedback}"
        # 0.8：writer 构思传给 polisher（润色不跑偏意图）
        outline_hint = ""
        if state.outline:
            outline_hint = f"\n\n【writer 构思（润色时保持此意图，不要跑偏）】\n{state.outline}"
        raw = self.writer_llm.chat(
            system,
            f"以下是初稿，请润色：\n\n{draft_safe}{outline_hint}{feedback_hint}",
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

    def _confirm_unparseable(self, state: PipelineState, raw: str) -> bool:
        """审稿结果不可解析时的人工确认：True=存（定稿），False=弃（不定稿不存盘）。

        - 显著警告（控制台 + state.log 双留痕，含原始返回前 200 字）；
        - review_confirm 注入时用它应答；未注入走 REPL input（EOF/Ctrl-C 视为弃，保守）。
        """
        print("  ⚠️  审稿结果不可解析（非 JSON），无法机器判定，不静默过审！")
        if raw:
            print(f"      原始返回前200字：{raw[:200]}")
        state.log.append(f"[reviewer] ⚠️ 审稿结果不可解析，原始返回前200字：{raw[:200]}")
        prompt = "  人工确认：本稿是否定稿保存？(存=y / 弃=n)："
        try:
            if self.review_confirm is not None:
                answer = str(self.review_confirm(prompt))
            else:
                answer = input(prompt)
        except (EOFError, KeyboardInterrupt):
            answer = "n"
        if answer.strip().lower().startswith("y"):
            state.feedback = "审稿通过（审稿结果不可解析，人工确认存稿）"
            state.log.append("[reviewer] 人工确认：存（定稿）")
            return True
        state.feedback = "审稿不通过（审稿结果不可解析，人工确认弃稿，本章未定稿）"
        state.log.append("[reviewer] 人工确认：弃（本章未定稿，不存盘）")
        return False

    def _reviewer(self, state: PipelineState) -> None:
        """审稿人：通过则定稿，不通过则打回 writer。

        审稿返回不可解析（parse_review 为 None）时不静默过审（0.1）：
        显著警告 + 人工确认存/弃--存则定稿留痕，弃则流程结束不定稿
        （final_chapter 保持空，cli 侧自然不保存章节，fail-closed）。
        """
        if state.review_count >= self.max_reviews:
            print(f"  ⚠️  审稿打回已达上限 {self.max_reviews} 次，强制定稿（逃生门，防死循环）")
            state.feedback = f"审稿通过（已达打回上限 {self.max_reviews} 次，强制定稿）"
            state.final_chapter = state.polished
            state.log.append(f"[reviewer] {state.feedback}")
            state.next_agent = "done"
            return

        print("  🔍 审稿中（约10秒）...")
        retrieved = self._retrieve(state.task, with_prior=False)
        system = reviewer_system(self.novel_name, retrieved, self.instruction, self.rules) + self._working_context()
        # 0.8：writer 构思作为验收基准（正文是否实现了该构思）
        outline_hint = ""
        if state.outline:
            outline_hint = f"\n\n【writer 构思（验收基准：请审查正文是否实现了该构思）】\n{state.outline}"
        result = self.llm.chat(
            system,
            f"请审查以下稿件：\n\n{state.polished}{outline_hint}",
            max_tokens=2048,
            temperature=0.2,
        )
        passed, reason = parse_review(result)

        if passed is None:
            # 0.1：不可解析不静默过审，交人工确认（存/弃），不走打回循环
            if self._confirm_unparseable(state, result or ""):
                state.final_chapter = state.polished
                print(f"  ✅ {state.feedback}")
                state.log.append(f"[reviewer] {state.feedback}")
            else:
                print(f"  🗑️ {state.feedback}")
            state.next_agent = "done"
            return

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

    # ---------- 单次调用能力（0.8 从 cli 收编） ----------
    def summarize_chapter(self, chapter_text: str, max_tokens: int = 1024) -> str:
        """剧情摘要（0.8 从 cli 收编）：1-2 句话关键情节与情绪落点。

        异常向上抛（原 cli 侧 try/except 兜底逻辑保留在调用方 _do_write）。
        """
        return self.llm.chat(
            PLOT_SUMMARY_SYSTEM, chapter_text,
            max_tokens=max_tokens, temperature=0.3,
        )

    def is_better(self, original: str, refined: str) -> bool:
        """对比原文与润色版（0.8 从 cli._is_better 收编）：润色后是否更好。

        - 空返回 False；
        - 返回纯 JSON 时取 better 字段（缺省 False）；
        - 解析失败兜底：文本含 "true" 则 True。
        """
        result = self.llm.chat(
            COMPARE_SYSTEM,
            f"【原文】\n{original[:2000]}\n\n【润色后】\n{refined[:2000]}\n\n"
            f"润色后是否比原文更好？只返回 JSON。",
            max_tokens=256,
            temperature=0.2,
        )
        if not result:
            return False
        try:
            return bool(json.loads(result.strip()).get("better", False))
        except Exception:
            return "true" in result.lower()

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
        """构造运行记录，供 storage 落盘 / harness 回放。

        config 从 load_profiles(settings) 同源重算而非读注入对象（Z5：
        FakeLLM 无 profile 属性；直构 Settings 测试确定性；生产路径两者同源）。
        api_key / base_url 不进 record（密钥绝不落盘）。
        """
        profiles = load_profiles(self.settings)
        return {
            "run_id": run_id,
            "task": task,
            "timestamp": datetime.datetime.now().isoformat(),
            "config": {
                "model": profiles.default.model,
                "temperature": temperature,
                "writer_model": profiles.writer.model,
                "llm_temperature": profiles.writer.temperature,
                "max_rounds": self.max_rounds,
                "max_reviews": self.max_reviews,
                "target_words": self.target_words,
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
        """跑完整流程（writer->polisher->reviewer），返回 (state, record)。"""
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
        - state.next_agent = "polisher"（跳过 writer，直接打磨）
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
        - state.next_agent = "writer"（直接从 writer 起）
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

    def partial_refine(
        self,
        blocks: List[Block],
        spans: List[Tuple[int, int]],
        task: str,
        run_id: Optional[str] = None,
    ) -> List[Optional[str]]:
        """局部精修：对每个编号区间独立调一次 LLM 润色，返回各区间的改写文本。

        - system = polisher_system(...) + PARTIAL_REFINE_SUFFIX；user = 三段式标记
          （上文 / 待润色片段 / 下文，见 prompts.partial_refine_user）。
        - 检索复用 _retrieve(task)（task 形如「局部精修：<文件名>」）。
        - 输出过 _strip_polisher_meta + 剥代码围栏；空回记为失败（该区间为 None 项）。
        - 不走 _run_loop 状态机；KeyboardInterrupt 等异常向上传播，由 cli 捕获视为取消。
        """
        index_of = {b.no: i for i, b in enumerate(blocks) if b.no is not None}
        retrieved = self._retrieve(task)
        system = polisher_system(
            self.novel_name, retrieved, self.instruction, rules=self.rules
        ) + PARTIAL_REFINE_SUFFIX

        results: List[Optional[str]] = []
        for lo, hi in spans:
            first_i, last_i = index_of[lo], index_of[hi]
            # 选区 = 区间覆盖的全部块（含区间内夹的 sep 等）的 body，块间空行连接
            selection = "\n\n".join(b.body for b in blocks[first_i:last_i + 1])
            before, after = build_context_pair(blocks, (lo, hi))
            label = f"第{lo}段" if lo == hi else f"第{lo}-{hi}段"
            print(f"  🔧 局部润色中（{label}，约30秒）...")
            raw = self.writer_llm.chat(
                system,
                partial_refine_user(before, selection, after),
                max_tokens=4096,
                temperature=0.6,
            )
            text = _strip_code_fence(_strip_polisher_meta(raw or ""))
            results.append(text if text.strip() else None)
        return results
