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
import re
from dataclasses import asdict, dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

from .config import Settings, get_settings
from .checker import run_checks, run_cross_checks, run_structure_checks
from .llm import LLMClient, load_profiles
from .memory import WorkingMemory
from .partial import Block, apply_replacements, build_context_pair, split_paragraphs
from .prompts import (
    ARC_SYSTEM,
    COMPARE_SYSTEM,
    FORESHADOW_SYSTEM,
    PARTIAL_REFINE_SUFFIX,
    PLOT_SUMMARY_SYSTEM,
    arc_user,
    deai_system,
    deai_user,
    fixer_system,
    fixer_user,
    fixer_whole_user,
    foreshadow_user,
    partial_refine_user,
    planner_system,
    planner_user,
    polisher_system,
    reviewer_system,
    writer_system,
)
from .rag import RAGStore
from .state import PipelineState

__all__ = ["NovelAgent", "parse_review", "parse_review_full"]


def _review_result(data: dict) -> Tuple[bool, str]:
    """从解析出的 dict 取 (pass, reason)；有 issues 则折进 reason 便于回看。"""
    passed = bool(data.get("pass", True))
    reason = str(data.get("reason", ""))
    issues = data.get("issues") or []
    if issues:
        extra = "；".join(str(i) for i in issues)
        reason = f"{reason}；问题：{extra}" if reason else f"问题：{extra}"
    return passed, reason


def _extract_json(text: str) -> Optional[dict]:
    """四级容错提取 LLM 输出中的 JSON 对象（design §3.3）。

    1) 直接 json.loads（仅顶层为 dict 才算数）；
    2) 失败则取第一个 { 到最后一个 } 之间再解析；
    3) JSON 截断（没结尾 }）：逐个补 } 再试（最多 3 次）；
    4) 都失败返回 None。
    """
    # 1) 直接解析
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, TypeError):
        pass
    # 2) 提取第一个 { 到最后一个 } 之间再解析
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            data = json.loads(text[start:end + 1])
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass
    # 3) 截断兜底：有 { 但没结尾 }，逐个补 } 再试
    start = text.find("{")
    if start != -1:
        snippet = text[start:]
        for _ in range(3):
            snippet += "}"
            try:
                data = json.loads(snippet)
                if isinstance(data, dict):
                    return data
            except json.JSONDecodeError:
                pass
    return None


def parse_review(text: str) -> Tuple[Optional[bool], str]:
    """解析审稿 JSON，返回 (是否通过, 原因)。容错 LLM 不规范输出。

    1) 直接 json.loads；
    2) 失败则取第一个 { 到最后一个 } 之间再解析；
    3) JSON 截断（没结尾 }）：补 } 再试；
    4) 都失败：文本含"不通过"/"false" 保守判不通过；否则返回 None（不可解析）。

    None 意味着不静默过审（0.1）：判定权上交--REPL 走人工确认，
    未来批量模式注入恒"弃"的 confirm 即 fail-closed，见 specs/stage0-batch。
    """
    data = _extract_json(text)
    if data is not None:
        return _review_result(data)
    # 4) 最终兜底：不再默认通过（fail-open 是 0.1 要消灭的行为）
    if "不通过" in text or "false" in text.lower():
        return False, text[:200]
    return None, "（审稿结果不可解析）"


@dataclass
class ReviewResult:
    """审稿富解析结果（1.1 A5-A6）：scores 八维分 + issues 结构化问题。"""

    passed: bool
    reason: str
    scores: Dict[str, int]   # 只收 1-5 整数，越界/非整数丢弃
    issues: List[dict]        # 字符串项归一为 {"quote": "", "problem": s, "fix": ""}


def parse_review_full(text: str) -> Optional[ReviewResult]:
    """审稿富解析（design §3.3）：JSON 提取复用 _extract_json，不可解析返回 None。

    - scores：值必须是 1-5 整数（bool 不算整数），其余丢弃（A6 容错）；
    - issues：dict 项原样（新 schema 同构 checker），字符串项归一为
      {"quote": "", "problem": s, "fix": ""}（旧 schema 兼容，D4）；
    - reason 为纯总评，不折叠 issues（结构化字段已分离）。
    """
    data = _extract_json(text)
    if data is None:
        return None

    scores: Dict[str, int] = {}
    for k, v in (data.get("scores") or {}).items():
        if isinstance(v, bool) or not isinstance(v, int) or not 1 <= v <= 5:
            continue
        scores[str(k)] = v

    issues: List[dict] = []
    for item in data.get("issues") or []:
        if isinstance(item, dict):
            issues.append(item)
        else:  # 旧 schema 字符串项归一
            issues.append({"quote": "", "problem": str(item), "fix": ""})

    return ReviewResult(
        passed=bool(data.get("pass", True)),
        reason=str(data.get("reason", "")),
        scores=scores,
        issues=issues,
    )


# event-anchor D10：事件锚 issue 前缀判定（容忍半角冒号）
_ANCHOR_ISSUE_PREFIXES = ("事件锚：", "事件锚:")


def _is_anchor_issue(issue: dict) -> bool:
    """problem 前缀「事件锚：」的 issue = 结构问题，不可段落修复（D10）。"""
    p = str(issue.get("problem") or "").strip()
    return p.startswith(_ANCHOR_ISSUE_PREFIXES)


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


# fixer 标记协议（D11）：【第N段·修复后】标记行 + 整段修复后文本
_FIXER_MARK_RE = re.compile(r"【第(\d+)段·修复后】")


def _clean_fixer_whole_output(new_text: str, original: str) -> str:
    """整文修复输出清洗：剥离标记协议残留行与开头重复的标题回显。

    fixer_system 复用段落标记协议（D11），整文降级模式下模型仍可能惯性输出
    「【第N段·修复后】」标记行，并在开头回显一遍原稿标题（真车 52 章脏文本），
    采纳前剥离，避免脏标记/重复标题写回正文。
    """
    lines = [ln for ln in new_text.split("\n") if not _FIXER_MARK_RE.fullmatch(ln.strip())]
    cleaned = "\n".join(lines)
    title = original.lstrip().split("\n", 1)[0].strip()
    if title:
        body = cleaned.lstrip("\n")
        head, _, rest = body.partition("\n")
        if head.strip() == title and rest.lstrip("\n").startswith(title):
            cleaned = rest.lstrip("\n")
    return cleaned


def _parse_fixer_output(raw: str) -> Dict[int, str]:
    """解析 fixer 标记协议输出（D11），返回 {段号: 该段修复后文本}。

    - 相邻两个标记之间的内容为前一个段号的正文（strip 后非空才收）；
    - 未出现的段号不在结果中，调用方让其回落原文（保底不破坏）；
    - 兼容「标记后同行写内容」与「换行后写」两种形态（strip 消化）。
    """
    result: Dict[int, str] = {}
    marks = list(_FIXER_MARK_RE.finditer(raw or ""))
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(raw)
        body = raw[m.end():end].strip()
        if body:
            result[int(m.group(1))] = body
    return result


def _locate_issues(text: str, issues: List[dict]) -> Optional[Dict[int, List[dict]]]:
    """issue -> 段号映射（A10）；任一 issue 不可定位返回 None（D12 整文降级判定）。

    不可定位 = quote 为空 / 非原文子串 / 落在标题或分隔符块（无 para 块包含）。
    """
    para_blocks = [b for b in split_paragraphs(text) if b.kind == "para" and b.no is not None]
    hit: Dict[int, List[dict]] = {}
    for issue in issues:
        quote = str(issue.get("quote") or "")
        target = next((b for b in para_blocks if quote and quote in b.body), None)
        if target is None:
            return None
        hit.setdefault(target.no, []).append(issue)
    return hit


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
        quality_rules: Optional[dict] = None,
        writer_llm: Optional[LLMClient] = None,
        recent_human: str = "",
        stream: bool = False,
        recent_endings: Optional[list[str]] = None,
        style_taboos: str = "",
    ):
        self.llm = llm
        self.rag = rag
        # 2.1 流式（D4）：仅 writer/polisher 开流式（on_delta 打印增量）；
        # 默认 False -> 直构测试与既有调用点零变化。
        self.stream = stream
        self.exemplar = exemplar
        self.instruction = instruction
        # 1.5 滚动注入：人工正文尾部 N 章片段，只进 writer prompt（B5）。
        self.recent_human = recent_human
        # 1.7 跨章禁则：参照章归一化结尾（checker 跨章比对用；None = ending 键未配置）
        # 与 writer 禁则分节（空串不占位，C9/C10）。
        self.recent_endings = recent_endings
        self.style_taboos = style_taboos
        # 0.2：写作铁律全文（NOVEL_DIR 下「写作铁律.md」），注入 writer/polisher/reviewer。
        self.rules = rules
        # 1.1：质量规则 dict（checker 五项机械检查）；None = 无规则 = checker 直通。
        self.quality_rules = quality_rules
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

        self.agents: Dict[str, Callable[[PipelineState], None]] = {
            "planner": self._planner,
            "writer": self._writer,
            "polisher": self._polisher,
            "checker": self._checker,
            "reviewer": self._reviewer,
            "fixer": self._fixer,
        }

    # ---------- RAG 检索辅助 ----------
    def _temp(self, kind: str, default: float) -> float:
        """调用点温度（0.9 全量可配）：单代理 NOVEL_<KIND>_TEMPERATURE >
        NOVEL_TEMPERATURE（写作侧兜底）> 调用点默认。

        - kind ∈ {writer, polisher, reviewer, router, fixer, judge, summarizer, planner}；
        - 写作侧（writer/polisher/fixer/planner，走 writer_llm）多一档 NOVEL_TEMPERATURE 兜底；
        - reviewer/judge/summarizer（走主 llm）与 router 只看自己的键和默认值。
        """
        per = getattr(self.settings, f"{kind}_temperature", None)
        if per is not None:
            return per
        if kind in ("writer", "polisher", "fixer", "planner") and self.settings.llm_temperature is not None:
            return self.settings.llm_temperature
        return default

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
        # 3.1 F8：注入侧带 cap 护栏（截断只影响注入，不影响抽取判定的全量清单）
        cap = getattr(self.settings, "foreshadow_cap", 30)
        # 3.2 C8：弧光注入护栏同款（截断只影响注入，不影响抽取输入清单）
        arc_cap = getattr(self.settings, "arc_cap", 8)
        text = self.working_memory.snapshot(cap=cap, arc_cap=arc_cap)
        return f"\n--- 当前写作状态（工作记忆）---\n{text}"

    # ---------- 三个 Agent ----------
    def _print_delta(self, text: str) -> None:
        """流式增量打印（2.1，D4）：writer/polisher 的 on_delta 回调。"""
        print(text, end="", flush=True)

    def _planner(self, state: PipelineState) -> None:
        """规划师（3.3 planner）：汇合章纲/伏笔/弧光/长度目标，产出本章节拍（先于 writer）。

        - 节拍存 state.outline（构思前移，D2：polisher/reviewer 既有消费面零改动）；
        - chat 包 try/except（Z4）：planner 在 _run_loop 状态机内运行，异常会
          中断整个 run，须自包；异常/空回视同降级（P3），writer 走现状分支；
        - rewrite 路径（T8）：source_content 非空时节拍基于原文结构（D9），
          降级逻辑同款（P15）；
        - 不走 streaming（design §5：节拍非正文，无需逐 token 输出）。
        """
        print("  📋 规划节拍中（约20秒）...")
        retrieved = self._retrieve(state.task)
        system = planner_system(
            self.novel_name, retrieved, self.instruction, self.rules,
        ) + self._working_context()
        try:
            raw = self.writer_llm.chat(
                system,
                planner_user(  # T8：rewrite 路径带原文（D9/D10，节拍基于原文结构）
                    state.task, state.plan, self.target_words,
                    state.source_content or "",
                ),
                max_tokens=2048,  # Z1：宪法 §4 推理预算
                temperature=self._temp("planner", 0.5),
            )
        except Exception as e:  # 异常视同空回降级，不中断 run（Z4）
            raw = ""
            state.log.append(f"[planner] ⚠️ 节拍规划调用失败：{e}")
        beats = _strip_code_fence(raw or "").strip()
        if beats:
            state.outline = beats
            state.log.append(f"[planner] 节拍完成，{len(beats)} 字")
        else:
            state.log.append("[planner] ⚠️ 节拍规划未返回内容，回落 writer 自行构思")
        state.next_agent = "writer"

    def _writer(self, state: PipelineState) -> None:
        """写手：查设定 + 调模型产出初稿（构思与正文按 === 分离，构思存入 state.outline）。"""
        # 2.1（T8）：流式下角色头标注且正文前换行（增量打印自然接管屏幕）
        print("  ✍️  写作中（流式）...\n" if self.stream else "  ✍️  写作中（约30秒）...")
        retrieved = self._retrieve(state.task)
        # 1.5：滚动人工正文只注入 writer（polisher/reviewer 零改动，B5）
        # 1.7：文风禁则分节同款只进 writer（C10，定调归 writer，D5）
        system = writer_system(
            self.novel_name, retrieved, self.exemplar, self.instruction,
            self.rules, self.recent_human, self.style_taboos,
        ) + self._working_context()

        # 2.2 规划注入（D12）：章纲要点进 writer prompt（空串整块不占位）；
        # 3.3 D7：planner 节拍已消化章纲时不双注入（节拍是唯一真源）
        plan_block = ""
        if state.plan and not state.outline:
            plan_block = (
                "\n\n【本章规划】（按此展开本章，是写作依据；天气与矛盾种子是本章的既定设定）"
                f"\n{state.plan}"
            )

        # 3.3 P7：planner 节拍注入（outline 已填 = 按节拍写；未填 = 现状自行构思）
        beats_block = ""
        if state.outline:
            beats_block = (
                f"\n\n【本章节拍（planner 规划，按此展开写作）】\n{state.outline}"
            )

        # 构思请求行二选一（D6：按 outline 是否已填，与 planner 开关解耦）
        if state.outline:
            draft_request = "\n请直接写正文，不要再写构思说明。"
        else:
            draft_request = (
                "\n请先用一段话说明构思（涉及人物、情绪走向、场景细节），"
                "然后用 === 分隔，再写正文。"
            )

        if state.source_content:
            user_msg = (
                f"参考以下已有内容，自由重写一个完整章节：{state.task}。目标约{self.target_words}字。"
                "\n你可以自行决定参考多少，结构和情节可以调整，但要保留核心意图。"
                "\n若原文缺少完整事件（碎片章/状态章），按章节规划补事件锚重写，不要只润色状态描写。"
                f"\n\n【已有内容（参考）】\n{state.source_content}"
                f"{plan_block}{beats_block}"
                f"{draft_request}"
            )
        else:
            user_msg = (
                f"写一段新章节：{state.task}。目标约{self.target_words}字。"
                f"{plan_block}{beats_block}"
                f"{draft_request}"
            )

        raw = self.writer_llm.chat(
            system,
            user_msg,
            max_tokens=4096,
            temperature=self._temp("writer", 0.8),
            on_delta=self._print_delta if self.stream else None,  # 键恒在（D4）
        )
        if self.stream:
            print()  # 流式正文结束补换行（T8）
        # 按 === 分隔：构思存入 state.outline（0.8 保留传递，供 polisher/reviewer/run 日志消费），正文进 draft
        outline, body = _split_writer_output(raw or "")
        if not state.outline:  # P8：planner 节拍是唯一真源，writer 残余构思不覆盖
            state.outline = outline
        state.draft = body
        if not state.draft:
            state.draft = f"（初稿兜底）{state.task}"
            state.log.append("[writer] 模型未返回内容，已用占位兜底")
        state.log.append(f"[writer] 写完初稿，{len(state.draft)} 字")
        state.next_agent = "polisher"

    def _polisher(self, state: PipelineState) -> None:
        """润色：查设定兜底，基于初稿润色。"""
        print("  🔧 润色中（流式）...\n" if self.stream else "  🔧 润色中（约30秒）...")
        retrieved = self._retrieve(state.task)
        system = polisher_system(
            self.novel_name, retrieved, self.instruction,
            target_words=self.target_words, rules=self.rules,
        ) + self._working_context()
        # 防止 GLM 把 --- 当结束标记截断，预处理换掉，润色后换回
        draft_safe = state.draft.replace("\n---\n", "\n【场景分隔】\n")
        # 0.8：writer 构思传给 polisher（润色不跑偏意图）；3.3 Z3：文案中性化（planner 节拍同走此链）
        outline_hint = ""
        if state.outline:
            outline_hint = f"\n\n【本章构思/节拍（润色时保持此意图，不要跑偏）】\n{state.outline}"
        raw = self.writer_llm.chat(
            system,
            f"以下是初稿，请润色：\n\n{draft_safe}{outline_hint}",
            max_tokens=4096,
            temperature=self._temp("polisher", 0.6),
            on_delta=self._print_delta if self.stream else None,  # 键恒在（D4）
        )
        if self.stream:
            print()  # 流式正文结束补换行（T8）
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
        # 1.1：润色后进 checker 做机械检查（无规则直通），再到 reviewer
        state.next_agent = "checker"

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
        """审稿人：通过则定稿，不通过则打回 fixer 修复（1.1 D9：打回固定 fixer）。

        富解析（1.1 A4/A24）：parse_review_full 的 scores / issues 落 state
        （asdict 自动进 run record）；打回 feedback = reason + 各 issue 的
        problem 摘要（维度名自带指路，A3）。
        event-anchor D10 分流：事件锚 issue 是结构问题（fixer 铁律禁增删情节，
        改不动）——仅事件锚不达标 -> 放行留痕定稿；混合不达标 -> 事件锚剔除出
        fixer 批次仅留痕；复检仅余事件锚同款放行（防循环，零新状态）。
        审稿返回不可解析（parse_review_full 为 None）时不静默过审（0.1）：
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
        # 0.8：writer 构思作为验收基准（正文是否实现了该构思）；3.3 Z3：文案中性化（planner 节拍同走此链）
        outline_hint = ""
        if state.outline:
            outline_hint = f"\n\n【本章构思/节拍（验收基准：请审查正文是否实现了该构思/节拍）】\n{state.outline}"
        result = self.llm.chat(
            system,
            f"请审查以下稿件：\n\n{state.polished}{outline_hint}",
            max_tokens=2048,
            temperature=self._temp("reviewer", 0.2),
        )
        parsed = parse_review_full(result)

        if parsed is None:
            # 0.1：不可解析不静默过审，交人工确认（存/弃），不走打回循环
            if self._confirm_unparseable(state, result or ""):
                state.final_chapter = state.polished
                print(f"  ✅ {state.feedback}")
                state.log.append(f"[reviewer] {state.feedback}")
            else:
                print(f"  🗑️ {state.feedback}")
            state.next_agent = "done"
            return

        # 富解析结果落 state（A4/A24）
        state.scores = parsed.scores
        state.issues = parsed.issues

        if parsed.passed:
            state.feedback = f"审稿通过：{parsed.reason}"
            state.final_chapter = state.polished
            print(f"  ✅ 审稿通过：{parsed.reason}")
            state.log.append(f"[reviewer] {state.feedback}")
            state.next_agent = "done"
            return

        # event-anchor D10 分流（不通过时）：事件锚 issue 剔除出修复批次仅留痕；
        # 复检仅余事件锚时走下方放行（防循环：每章最多一轮可修复项的 fixer 循环）。
        anchor_issues = [i for i in parsed.issues if _is_anchor_issue(i)]
        fixable = [i for i in parsed.issues if not _is_anchor_issue(i)]
        for i in anchor_issues:
            problem = str(i.get("problem") or "").strip()
            print(f"  ⚠️ {problem}（不可段落修复，仅留痕）")
            state.log.append(f"[reviewer] ⚠️ report-only：{problem}（事件锚不达标，建议人工重写）")

        if anchor_issues and not fixable:
            # 仅事件锚不达标：放行留痕定稿（E8/D10）
            state.feedback = f"审稿通过（事件锚不达标，建议人工重写）：{parsed.reason}"
            state.final_chapter = state.polished
            print(f"  ⚠️ {state.feedback}")
            state.log.append(f"[reviewer] {state.feedback}")
            state.next_agent = "done"
            return

        # 打回：feedback = reason + 各 issue 的 problem 摘要（A3：维度名自带指路；
        # 事件锚已剔除，不进 fixer 意见）
        state.issues = fixable
        summary = parsed.reason
        problems = "；".join(
            str(i.get("problem") or "").strip() for i in fixable
            if str(i.get("problem") or "").strip()
        )
        if problems:
            summary = f"{summary}；问题：{problems}" if summary else f"问题：{problems}"
        state.review_count += 1
        state.feedback = f"审稿不通过（第{state.review_count}次）：{summary}"
        print(f"  ❌ 审稿不通过：{summary}，打回修复")
        state.log.append(f"[reviewer] {state.feedback}，打回 fixer")
        state.next_agent = "fixer"

    # ---------- 规则检查器与修稿师（1.1 质量门禁）----------
    def _checker(self, state: PipelineState) -> None:
        """规则检查器（纯代码零 LLM）：无规则 / 无命中 -> reviewer；命中 -> fixer。

        - 与 reviewer 共享 review_count 预算（A14）；达上限放行 reviewer，
          强制定稿由 reviewer 逃生门统一收口（D7）；
        - 打回 feedback 附命中摘要（规则名+次数，Z2），明细在 state.issues；
        - 结构检查（event-anchor D9）走 report-only 通道：显著警告 + state.log
          留痕，不进 state.issues、不消耗 review_count、不触发 fixer——结构问题
          闭环内修不好（fixer 铁律禁增删情节），正解是人工「重写」。
        """
        issues = run_checks(state.polished, self.quality_rules)
        # 1.7 跨章检查（C6）：并入同一 issues 流（打回 fixer / review_count 共享 /
        # 复检全部既有机制，零新状态）。两键全缺时 run_cross_checks 返回 []，
        # 行为与现状逐字节一致（C16）；ending 键缺失时 recent_endings=None，
        # ending 项跳过、syntax 项照跑（C5 各键独立降级）。
        if self.quality_rules:
            issues += run_cross_checks(state.polished, self.recent_endings, self.quality_rules)
        # event-anchor 结构检查（D9 report-only）：每轮复检重复警告/留痕是有意为之
        # （持续可见、实现零状态，不去重）；quality_rules 为 None 时返回 []，零行为差异（E12）。
        for issue in run_structure_checks(state.polished, self.quality_rules):
            print(f"  ⚠️ 结构检查：{issue['problem']}")
            state.log.append(f"[checker] ⚠️ report-only：{issue['problem']}（建议人工重写）")
        if not issues or state.review_count >= self.max_reviews:
            if issues:
                print(f"  ⚠️ 规则检查命中 {len(issues)} 项，但打回已达上限 {self.max_reviews} 次，放行审稿")
                state.log.append(
                    f"[checker] ⚠️ 命中 {len(issues)} 项但达打回上限，放行 reviewer（强制定稿由 reviewer 收口）"
                )
            state.next_agent = "reviewer"
            return

        state.review_count += 1  # 与 reviewer 共享预算（A14）
        state.issues = issues
        details = [str(i.get("problem") or "").strip() for i in issues]
        details = [d for d in details if d]
        summary = "；".join(details[:3])
        if len(details) > 3:
            summary += f"…（共{len(details)}项）"
        state.feedback = f"规则检查不通过（第{state.review_count}次）：{summary}"
        print(f"  ❌ 规则检查不通过：{summary}，交修复")
        state.log.append(f"[checker] {state.feedback}，打回 fixer")
        state.next_agent = "fixer"

    def _fixer(self, state: PipelineState) -> None:
        """修稿师：消费 state.issues 定位修复 state.polished，修完回 checker 复检（A8-A15）。

        - 定位（A10）：issue.quote 非空且为原文子串 -> 首个含 quote 的 para 块；
        - 任一 quote 为空或非原文子串 -> 整组整文降级（D12，不做混合协议）；
        - 段落级走 _fix_spans 共用子过程（1.6 D2 抽取，行为不变）：全部问题段
          + 各自意见 + 上下文合成一次 writer_llm 调用（A11/Z3），输出按
          【第N段·修复后】标记协议解析（D11），未返回段回落原文；
          逐段字数保护（A15）；apply_replacements 回填，区间外逐字节不变；
        - 修复后清空 state.issues（Z5，防陈旧意见重复触发）。
        """
        text = state.polished
        issues = state.issues or []
        if not text or not issues:
            state.next_agent = "checker"  # 无可修意见，直接复检
            return

        # ---- 定位（D12：任一不可定位即整文修复）----
        if _locate_issues(text, issues) is None:
            state.polished = self._fixer_whole(state, text, issues)
            state.issues = []  # Z5
            state.next_agent = "checker"
            return

        new_text, n_spans = self._fix_spans(
            text, issues,
            fixer_system(self.novel_name, self.rules),
            fixer_user,
            log=state.log,
        )
        state.polished = new_text
        state.issues = []  # Z5
        state.log.append(f"[fixer] 修复 {n_spans} 段，{len(state.polished)} 字，回 checker 复检")
        state.next_agent = "checker"

    def _fix_spans(
        self,
        text: str,
        issues: List[dict],
        system: str,
        user_builder: Callable[[List[dict]], str],
        log_tag: str = "fixer",
        log: Optional[List[str]] = None,
        doing: str = "修复",
    ) -> Tuple[str, int]:
        """共用修复子过程（1.6 D2）：定位 -> spans 合并 -> 单次调用 -> 标记协议解析
        -> 逐段回填 + 字数保护。返回 (新文本, 问题段数)。

        - issues 应为可定位 issue（_fixer 已整组校验、deai_refine 已过滤；
          残余不可定位项在此丢弃不阻断）；
        - 与 _fixer 既有行为逐条一致（A10/A11/D11/A15 是回归护栏）；
        - log_tag/doing 只影响提示文案；log 传入时同步留痕（fixer 传 state.log）。
        """
        blocks = split_paragraphs(text)
        para_blocks = {b.no: b for b in blocks if b.kind == "para" and b.no is not None}
        hit: Dict[int, List[dict]] = {}
        for issue in issues:
            quote = str(issue.get("quote") or "")
            target = next((b for b in para_blocks.values() if quote and quote in b.body), None)
            if target is not None:
                hit.setdefault(target.no, []).append(issue)
        if not hit:
            return text, 0

        # ---- 问题段号排序去重合并相邻为 spans（A10）----
        nos = sorted(hit)
        spans: List[Tuple[int, int]] = []
        for no in nos:
            if spans and no == spans[-1][1] + 1:
                spans[-1] = (spans[-1][0], no)
            else:
                spans.append((no, no))

        # ---- 逐段独立构造（before/after/text/issues），合并单次调用（A11）----
        spans_data: List[dict] = []
        for no in nos:
            b = para_blocks[no]
            before, after = build_context_pair(blocks, (no, no))
            spans_data.append({
                "no": no,
                "before": before,
                "text": b.body,
                "after": after,
                "issues": hit[no],
            })
        print(f"  🩹 {doing}中（{len(nos)} 个问题段，约30秒）...")
        raw = self.writer_llm.chat(
            system,
            user_builder(spans_data),
            max_tokens=4096,
            temperature=self._temp("fixer", 0.5),
        )
        fixed = _parse_fixer_output(_strip_code_fence(raw or ""))

        # ---- 逐段回填（未返回段回落原文 D11 + 字数保护 A15）----
        new_texts: List[str] = []
        for lo, hi in spans:
            parts: List[str] = []
            for no in range(lo, hi + 1):
                b = para_blocks[no]
                new_body = fixed.get(no)
                if new_body is None:
                    new_body = b.body  # 未返回段保持原文（保底不破坏）
                elif len(b.body) >= 50 and len(new_body) < len(b.body) * 0.5:
                    print(f"  ⚠️ 字数保护：第{no}段{doing}缩水（{len(new_body)}字 < 原文50% {len(b.body)}字），保留原段")
                    if log is not None:
                        log.append(
                            f"[{log_tag}] ⚠️ 第{no}段{doing}缩水（{len(new_body)}字 < 原文50% {len(b.body)}字），保留原段"
                        )
                    new_body = b.body
                parts.append(new_body)
                if no != hi:
                    # 原块尾部空行原样保留（末块尾部由 apply_replacements 统一补回）
                    parts.append(b.text[len(b.body):])
            new_texts.append("".join(parts))

        return apply_replacements(text, blocks, spans, new_texts), len(nos)

    # ---------- 去 AI 人味重写（1.6 style-loop，B9-B17）----------
    def deai_refine(self, text: str, issues: List[dict]) -> Tuple[str, int]:
        """人味重写 pass 本体（D1 旁挂方法）：对可定位问题段做去 AI 表达重写。

        - 不可定位 issue（quote 空/非子串）直接丢弃，不整文降级（D8：
          B10 只传问题句是硬约束；fixer 服务打回语义必须全消费，两角色差异点）；
        - 全部不可定位 / 无 issue -> 返回 (原文, 0)，零 LLM 调用（B17 防空跑）；
        - 管线复用 _fix_spans（D2）：单次 writer_llm 调用（A11 同款纪律）
          + 标记协议解析（D11）+ 逐段回填 + 字数保护，区间外逐字节不变（B12）；
        - 温度 self._temp("fixer", 0.5)（Z3 同 fixer 档，可配覆盖）。
        """
        if not text or not issues:
            return text, 0
        locatable = [
            i for i in issues
            if str(i.get("quote") or "") and str(i.get("quote") or "") in text
        ]
        if not locatable:
            return text, 0
        return self._fix_spans(
            text, locatable,
            deai_system(self.novel_name, self.rules),
            deai_user,
            log_tag="deai",
            doing="人味重写",
        )

    def _fixer_whole(self, state: PipelineState, text: str, issues: List[dict]) -> str:
        """整文修复降级（A12/D12）：单次调用全文改写，整体字数保护（A15）。"""
        print("  🩹 修复中（整文降级，约30秒）...")
        raw = self.writer_llm.chat(
            fixer_system(self.novel_name, self.rules),
            fixer_whole_user(text, issues),
            max_tokens=4096,
            temperature=self._temp("fixer", 0.5),
        )
        new_text = _clean_fixer_whole_output(_strip_code_fence(raw or ""), text)
        if not new_text.strip():
            state.log.append("[fixer] 整文修复未返回内容，保留原稿")
            return text
        if len(new_text) < len(text) * 0.5:
            print(f"  ⚠️ 字数保护：{len(new_text)} 字 < 原文50%（{len(text)}字），保留原稿")
            state.log.append(f"[fixer] ⚠️ 整文修复缩水（{len(new_text)}字 < 原文50% {len(text)}字），保留原稿")
            return text
        state.log.append("[fixer] 整文修复完成（quote 不可定位降级）")
        return new_text

    # ---------- 单次调用能力（0.8 从 cli 收编） ----------
    def summarize_chapter(self, chapter_text: str, max_tokens: int = 1024) -> str:
        """剧情摘要（0.8 从 cli 收编）：1-2 句话关键情节与情绪落点。

        异常向上抛（原 cli 侧 try/except 兜底逻辑保留在调用方 _do_write）。
        """
        return self.llm.chat(
            PLOT_SUMMARY_SYSTEM, chapter_text,
            max_tokens=max_tokens, temperature=self._temp("summarizer", 0.3),
        )

    def extract_foreshadowing(
        self,
        chapter_text: str,
        unresolved: List[dict],
        chapter_no: Optional[int] = None,
    ) -> dict:
        """伏笔抽取（3.1，D1/D2/D8）：一次调用同时完成「找新伏笔」与「判旧伏笔是否回收」。

        - 输入：本章定稿正文 + 带编号的未回收清单（编号 = 列表序，1 起，与回报协议同源）；
        - 输出：{"new": [{"desc", "chapter"}], "resolved": [编号...], "raw": 原始返回}；
        - resolved 越界/重复/非整数编号静默丢弃；new 与既有 desc 完全同串的跳过（D7）；
          new 内部自身重复也跳过；
        - 空返回 / 剥围栏后仍非法 / 缺 new 或 resolved 键 -> 抛异常（F3 整体放弃，
          不做部分采信：半次更新比不更新更难推理）；
        - max_tokens=2048（Z6）：推理模型思考计入预算，30 条判定 + 多条自包含描述比
          审稿 JSON 更长，1024 偏紧；
        - ≤5 条是 prompt 软约束，模型返回超限时全收不截断（截断会丢真伏笔，F5）。
        """
        def _desc(item) -> str:
            if isinstance(item, str):
                return item
            return str(item.get("desc") or "") if isinstance(item, dict) else ""

        lines = []
        for i, entry in enumerate(unresolved or [], 1):
            chapter = entry.get("chapter") if isinstance(entry, dict) else None
            prefix = f"（第{chapter}章埋）" if isinstance(chapter, int) else ""
            lines.append(f"{i}.{prefix}{_desc(entry)}")

        raw = self.llm.chat(
            FORESHADOW_SYSTEM,
            foreshadow_user(chapter_text, lines),
            max_tokens=2048,
            temperature=self._temp("foreshadow", 0.2),
        )
        if not raw or not raw.strip():
            raise ValueError("抽取返回为空")
        data = _extract_json(_strip_code_fence(raw))
        if not isinstance(data, dict) or "new" not in data or "resolved" not in data:
            raise ValueError(f"抽取返回不可解析：{(raw or '')[:80]!r}")

        existing = {_desc(e).strip() for e in (unresolved or [])}
        new_items: List[dict] = []
        for item in data.get("new") or []:
            desc = item.get("desc") if isinstance(item, dict) else item
            desc = str(desc or "").strip()
            if not desc or desc in existing:
                continue
            existing.add(desc)  # new 内部自身重复也跳过
            entry = {"desc": desc}
            if chapter_no is not None:
                entry["chapter"] = chapter_no
            new_items.append(entry)

        total = len(unresolved or [])
        resolved: List[int] = []
        for no in data.get("resolved") or []:
            if isinstance(no, bool) or not isinstance(no, int):
                continue
            if 1 <= no <= total and no not in resolved:
                resolved.append(no)
        return {"new": new_items, "resolved": resolved, "raw": raw}

    def extract_character_arc(
        self,
        chapter_text: str,
        character_states: Dict[str, dict],
        chapter_no: Optional[int] = None,
    ) -> dict:
        """角色弧光抽取（3.2，D1/D2/D5）：一次调用完成「更新出场角色状态 + 发现
        新角色 + 判定阶段是否实质变化」三件事。

        - 输入：本章定稿正文 + 既有角色状态清单（全量，截断只影响注入不影响抽取）；
        - 输出：{"characters": [{name, stage, goal, conflict, belief, changed}],
          "raw": 原始返回}；名字同串覆盖/异串新键的机械判定在 memory 侧（D2）；
        - 空返回 / 剥围栏后仍非法 / 缺 characters 键 -> 抛异常（C3 整体放弃，
          不做部分采信：错误状态污染后续所有章 prompt，比空着更糟）；
        - max_tokens=2048（Z6）：推理模型思考计入预算，6 角色 × 4 字段的 JSON
          比伏笔描述长；
        - ≤6 个主要角色是 prompt 软约束，模型返回超限时全收不截断（C5）。
        """
        lines = []
        for name, entry in (character_states or {}).items():
            chapter = entry.get("chapter") if isinstance(entry, dict) else None
            prefix = f"（第{chapter}章）" if isinstance(chapter, int) else ""
            lines.append(f"{name}{prefix}：{entry.get('stage', '')}")

        raw = self.llm.chat(
            ARC_SYSTEM,
            arc_user(chapter_text, lines),
            max_tokens=2048,
            temperature=self._temp("arc", 0.2),
        )
        if not raw or not raw.strip():
            raise ValueError("弧光抽取返回为空")
        data = _extract_json(_strip_code_fence(raw))
        if not isinstance(data, dict) or "characters" not in data:
            raise ValueError(f"弧光抽取返回不可解析：{(raw or '')[:80]!r}")

        characters: List[dict] = []
        for item in data.get("characters") or []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            stage = str(item.get("stage") or "").strip()
            if not name or not stage:
                continue
            characters.append({
                "name": name,
                "stage": stage,
                "goal": str(item.get("goal") or ""),
                "conflict": str(item.get("conflict") or ""),
                "belief": str(item.get("belief") or ""),
                "changed": bool(item.get("changed")),
            })
        return {"characters": characters, "raw": raw}

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
            temperature=self._temp("judge", 0.2),
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
                # D7：强制定稿由 reviewer 逃生门统一收口；超轮只中止不落盘
                # （结果留运行日志供 replay 人工处理），不冒用「强制定稿」字样
                state.log.append(
                    f"[system] 超过 {self.max_rounds} 轮，中止（结果未入库，可 replay 查看）"
                )
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
                "llm_temperature": self.settings.llm_temperature,
                "writer_temperature": self.settings.writer_temperature,
                "polisher_temperature": self.settings.polisher_temperature,
                "reviewer_temperature": self.settings.reviewer_temperature,
                "max_rounds": self.max_rounds,
                "max_reviews": self.max_reviews,
                "target_words": self.target_words,
                "quality_rules": self.quality_rules is not None,  # Z6：可追溯该 run 是否带规则跑
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
        plan: str = "",
    ) -> Tuple[PipelineState, Dict[str, Any]]:
        """跑完整流程（writer->polisher->checker->reviewer，打回统一进 fixer），返回 (state, record)。

        plan：本章规划（2.2 章纲要点，D12）——只注入 writer prompt 并随 state
        进 record（asdict 自然落 final_state，replay 可见当时按什么规划写的）。
        3.3 planner：NOVEL_PLANNER=1 时先规划再写（planner 汇合章纲/伏笔/
        弧光/字数产节拍存 outline，构思前移；refine 不触发，rewrite 同触发
        见 rewrite()，T8）。
        """
        if run_id is None:
            run_id = "run_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

        state = PipelineState(task=task, plan=plan)
        if self.settings.planner_enabled:
            state.next_agent = "planner"  # P1：planner 是状态机真角色
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
        - 后面 polisher -> checker -> reviewer，与 run() 一致；
          checker/reviewer 打回统一进 fixer（1.1 D9：refine 无 writer，
          打回不回 polisher 重润，交给 fixer 按意见精修）。
        """
        if run_id is None:
            run_id = "refine_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

        state = PipelineState(task=task)
        state.draft = content
        state.next_agent = "polisher"
        state.log.append(f"[refine] 精修开始，初稿 {len(content)} 字")

        refine_agents: Dict[str, Callable[[PipelineState], None]] = {
            "polisher": self._polisher,
            "checker": self._checker,
            "reviewer": self._reviewer,
            "fixer": self._fixer,
        }
        steps: List[dict] = []
        self._run_loop(state, refine_agents, steps)
        return state, self._record(run_id, task, temperature, state, steps)

    def rewrite(
        self,
        content: str,
        task: str,
        run_id: Optional[str] = None,
        temperature: float = 0.9,
    ) -> Tuple[PipelineState, Dict[str, Any]]:
        """重写已有正文：走 writer->polisher->checker->reviewer，writer 参考原文自由重写。

        - state.source_content = 传入的正文（writer 作为参考）
        - state.next_agent = "planner"（NOVEL_PLANNER=1 时，T8：节拍基于原文
          结构——场景提取->重排/增强，不从零规划）/ "writer"（默认，现状）
        - checker/reviewer 打回统一进 fixer（与 run 一致）
        与 run() 的区别：writer 拿到已有内容作为参考，而非从零创作。
        与 refine() 的区别：走 writer 而非 polisher，能大幅扩写/重构。
        """
        if run_id is None:
            run_id = "rewrite_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

        state = PipelineState(task=task)
        state.source_content = content
        if self.settings.planner_enabled:
            state.next_agent = "planner"  # T8/P13：重写先规划（节拍基于原文结构）
        else:
            state.next_agent = "writer"  # P16：现状
        state.log.append(f"[rewrite] 重写开始，参考原文 {len(content)} 字")

        steps: List[dict] = []
        self._run_loop(state, self.agents, steps)
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
                temperature=self._temp("polisher", 0.6),
            )
            text = _strip_code_fence(_strip_polisher_meta(raw or ""))
            results.append(text if text.strip() else None)
        return results
