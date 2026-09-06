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

__all__ = [
    "ShortTermMemory",
    "WorkingMemory",
    "LongTermMemory",
    "normalize_foreshadowing",
    "normalize_resolved",
    "normalize_character_states",
]


# ---------- 伏笔条目归一化（3.1 F6：旧版纯字符串兼容读取）----------
def _entry_desc(item) -> str:
    """条目 -> 描述文本（dict 取 desc，str 就是它自己，其余类型当脏数据 -> ""）。"""
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        return str(item.get("desc") or "")
    return ""


def _entry_chapter(item) -> Optional[int]:
    """条目 -> 埋设章号（缺失/非法 -> None）。"""
    if isinstance(item, dict):
        chapter = item.get("chapter")
        return chapter if isinstance(chapter, int) else None
    return None


def normalize_foreshadowing(items) -> List[dict]:
    """未回收伏笔列表归一化：str -> {"desc", "chapter": None}；脏元素丢弃（不因一条脏数据拒载）。"""
    out: List[dict] = []
    for entry in items or []:
        desc = _entry_desc(entry).strip()
        if not desc:
            continue
        item = {"desc": desc, "chapter": _entry_chapter(entry)}
        if isinstance(entry, dict) and entry.get("manual"):
            item["manual"] = True
        out.append(item)
    return out


def normalize_resolved(items) -> List[dict]:
    """已回收归档列表归一化：只收有 desc 的 dict，章号非法归 None。"""
    out: List[dict] = []
    for entry in items or []:
        if not isinstance(entry, dict):
            continue
        desc = str(entry.get("desc") or "").strip()
        if not desc:
            continue
        resolved = entry.get("resolved_chapter")
        out.append({
            "desc": desc,
            "chapter": _entry_chapter(entry),
            "resolved_chapter": resolved if isinstance(resolved, int) else None,
        })
    return out


# ---------- 角色状态条目归一化（3.2 C6：脏条目丢弃不拒载）----------
def _arc_history(items) -> List[dict]:
    """history 归一化：只收 {chapter: int, stage: 非空} 的条目，按原序保留。"""
    out: List[dict] = []
    for h in items or []:
        if not isinstance(h, dict):
            continue
        chapter = h.get("chapter")
        stage = str(h.get("stage") or "").strip()
        if not isinstance(chapter, int) or not stage:
            continue
        out.append({"chapter": chapter, "stage": stage})
    return out


def normalize_character_states(states) -> dict:
    """character_states 归一化：非 dict -> {}；条目非 dict 或缺 stage -> 丢弃。

    旧 working_memory.json 该字段恒为 {}（从未被写过），天然无迁移（C6）。
    """
    if not isinstance(states, dict):
        return {}
    out: dict = {}
    for name, entry in states.items():
        if not isinstance(entry, dict):
            continue
        stage = str(entry.get("stage") or "").strip()
        if not stage:
            continue
        chapter = entry.get("chapter")
        out[str(name)] = {
            "stage": stage,
            "goal": str(entry.get("goal") or ""),
            "conflict": str(entry.get("conflict") or ""),
            "belief": str(entry.get("belief") or ""),
            "chapter": chapter if isinstance(chapter, int) else None,
            "history": _arc_history(entry.get("history")),
        }
    return out


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
    """工作记忆：记小说当前的客观状态（写到哪了），不记聊天内容。

    伏笔条目（3.1）：`{"desc": 描述, "chapter": 埋设章号}`，人工补录另带 `"manual": True`；
    回收不是物理删除，而是从 unresolved 移入 resolved_foreshadowing 归档（F15，
    误判可人工移回）。
    """

    def __init__(self):
        self.current_chapter: Optional[int] = None
        self.character_states: dict = {}
        self.unresolved_foreshadowing: List[dict] = []
        self.resolved_foreshadowing: List[dict] = []
        self.last_plot_point: Optional[str] = None

    def update_after_write(
        self,
        chapter_no: Optional[int],
        plot_summary: Optional[str],
        new_foreshadowing: Optional[List[dict]] = None,
    ) -> None:
        """每写完一章调用一次，刷新状态。

        new_foreshadowing 收 dict 条目；str 元素按容错转成 {"desc", "chapter": chapter_no}。
        """
        self.current_chapter = chapter_no
        self.last_plot_point = plot_summary
        for item in new_foreshadowing or []:
            desc = _entry_desc(item).strip()
            if not desc:
                continue
            entry = {"desc": desc, "chapter": chapter_no}
            if isinstance(item, dict) and item.get("manual"):
                entry["manual"] = True
            self.unresolved_foreshadowing.append(entry)

    def add_foreshadowing(
        self, desc: str, chapter: Optional[int] = None, manual: bool = False
    ) -> dict:
        """追加一条未回收伏笔（人工补录走 manual=True：不被同章覆盖清洗清掉，F16）。"""
        entry = {"desc": desc, "chapter": chapter}
        if manual:
            entry["manual"] = True
        self.unresolved_foreshadowing.append(entry)
        return entry

    def resolve_foreshadowing(
        self, indices: List[int], chapter_no: Optional[int] = None
    ) -> List[dict]:
        """按 1 起编号把未回收伏笔出列并移入归档（模型回收与人工 `伏笔 删` 同路径）。

        越界/重复/非整数编号静默忽略；一次结算（先取条目再重建列表，避免删一条后错位）。
        返回被归档的条目列表。
        """
        total = len(self.unresolved_foreshadowing)
        picked = sorted(
            {i for i in (indices or [])
             if isinstance(i, int) and not isinstance(i, bool) and 1 <= i <= total}
        )
        if not picked:
            return []
        moved: List[dict] = []
        for i in picked:
            entry = self.unresolved_foreshadowing[i - 1]
            archived = {
                "desc": _entry_desc(entry),
                "chapter": _entry_chapter(entry),
                "resolved_chapter": chapter_no,
            }
            if isinstance(entry, dict) and entry.get("manual"):
                archived["manual"] = True
            moved.append(archived)
        dropped = set(picked)
        self.unresolved_foreshadowing = [
            e for i, e in enumerate(self.unresolved_foreshadowing, 1) if i not in dropped
        ]
        self.resolved_foreshadowing.extend(moved)
        return moved

    # ---------- 角色弧光（3.2 character-arc）----------
    ARC_HISTORY_CAP = 20  # history 护栏：超出丢最老（Z3：固定常量不进配置）

    def update_character_states(
        self, entries: List[dict], chapter_no: Optional[int] = None
    ) -> None:
        """写后弧光抽取结果落账（C2/C15）。

        entries 为 LLM 回报条目 [{"name", "stage", "goal", "conflict", "belief",
        "changed"}]：名字与既有键同串 -> 覆盖；异串 -> 新角色（dict 键天然去重，D2）；
        changed 为真 -> history 追加 {"chapter": chapter_no, "stage": 新 stage}（变化点
        = 新阶段起点，D7 语义判定）；同章重写覆盖：chapter_no 非 None 时先清各角色
        history 中 chapter == chapter_no 的条目（num=None 守卫：不清洗，C15）。
        """
        if chapter_no is not None:
            for entry in self.character_states.values():
                entry["history"] = [
                    h for h in entry.get("history", []) if h.get("chapter") != chapter_no
                ]
        for item in entries or []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            stage = str(item.get("stage") or "").strip()
            if not name or not stage:
                continue
            old = self.character_states.get(name)
            history = list(old.get("history", [])) if old else []
            if item.get("changed"):
                history.append({"chapter": chapter_no, "stage": stage})
            # C6：按章升序（重写旧章插入的变化点归位；None 章号排尾，稳定排序保追加序）
            history.sort(key=lambda h: (h.get("chapter") is None, h.get("chapter") or 0))
            self.character_states[name] = {
                "stage": stage,
                "goal": str(item.get("goal") or ""),
                "conflict": str(item.get("conflict") or ""),
                "belief": str(item.get("belief") or ""),
                "chapter": chapter_no,
                "history": history[-self.ARC_HISTORY_CAP:],
            }

    def remove_character(self, name: str) -> bool:
        """停止跟踪一个角色（直接移除不归档，Z4；再出场会被抽取重新发现）。"""
        return self.character_states.pop(name, None) is not None

    def revise_character_stage(
        self, name: str, stage: str, chapter: Optional[int] = None
    ) -> bool:
        """人工修正当前阶段（D9：不打 manual，下章抽取在其基础上演进）。"""
        entry = self.character_states.get(name)
        if entry is None:
            return False
        entry["stage"] = stage
        entry["chapter"] = chapter
        return True

    def arc_lines(self, arc_cap: Optional[int] = None) -> List[str]:
        """角色弧光渲染行（名字（更新章）：阶段｜目标｜信念，C7）。

        arc_cap 为 None 或 <=0 -> 全量；否则按更新章倒序取前 arc_cap 个（最近活跃
        优先，D10）。截断标注由 arc_block 负责（与伏笔同构）。
        """
        if not self.character_states:
            return []
        items = sorted(
            self.character_states.items(),
            key=lambda kv: (kv[1].get("chapter") is not None, kv[1].get("chapter") or 0),
            reverse=True,
        )
        shown = items
        if arc_cap is not None and arc_cap > 0 and len(items) > arc_cap:
            shown = items[:arc_cap]
        lines: List[str] = []
        for name, entry in shown:
            chapter = entry.get("chapter")
            prefix = f"（第{chapter}章）" if chapter is not None else ""
            parts = [f"{name}{prefix}：{entry.get('stage', '')}"]
            if entry.get("goal"):
                parts.append(f"目标：{entry['goal']}")
            if entry.get("belief"):
                parts.append(f"信念：{entry['belief']}")
            lines.append("  " + "｜".join(parts))
        return lines

    def arc_block(self, arc_cap: Optional[int] = None) -> str:
        """角色弧光块（注入 prompt 用）：指令文案 + 渲染行 + 截断标注（C7/C8）。"""
        lines = self.arc_lines(arc_cap=arc_cap)
        if not lines:
            return ""
        head = "角色弧光（写作时保持各角色当前阶段与人设连续，不可无故突变）："
        total = len(self.character_states)
        parts = [head] + lines
        if len(lines) < total:
            parts.append(f"  …（共 {total} 角色，仅注入最近更新 {len(lines)} 个）")
        return "\n".join(parts)

    def foreshadow_lines(self, cap: Optional[int] = None) -> List[str]:
        """未回收伏笔的渲染行（编号 + 埋设章号 + 描述）。

        cap 为 None 或 <=0 -> 全量；否则只取尾部 cap 条但**保留原编号**（F8，与 `伏笔`
        命令的全量编号一致，防截断重排后对不上）。
        """
        items = self.unresolved_foreshadowing
        if not items:
            return []
        shown = items
        if cap is not None and cap > 0 and len(items) > cap:
            shown = items[-cap:]
        offset = len(items) - len(shown)
        lines: List[str] = []
        for i, entry in enumerate(shown):
            no = offset + i + 1
            chapter = _entry_chapter(entry)
            prefix = f"（第{chapter}章埋）" if chapter is not None else ""
            lines.append(f"  {no}.{prefix}{_entry_desc(entry)}")
        return lines

    def foreshadow_block(self, cap: Optional[int] = None) -> str:
        """未回收伏笔块（注入 prompt 用）：指令文案 + 渲染行 + 截断标注。"""
        lines = self.foreshadow_lines(cap=cap)
        if not lines:
            return ""
        head = "未回收伏笔（写作时应考虑推进或回收，不强行回收）："
        total = len(self.unresolved_foreshadowing)
        parts = [head] + lines
        if len(lines) < total:
            parts.append(f"  …（共 {total} 条，仅注入最近 {len(lines)} 条）")
        return "\n".join(parts)

    def snapshot(self, cap: Optional[int] = None, arc_cap: Optional[int] = None) -> str:
        """压成一段文字，塞进 system prompt 让模型知道"写到哪了"。

        cap：注入 prompt 时传 settings.foreshadow_cap（截断护栏）；`状态`/`伏笔`
        等命令侧传 None 看全量（F8）。arc_cap 同理（3.2 C8，角色弧光注入护栏）。
        """
        parts = [
            f"当前进度：第{self.current_chapter}章。",
            f"最近剧情：{self.last_plot_point}",
        ]
        arc = self.arc_block(arc_cap=arc_cap)
        parts.append(arc if arc else "角色状态：无")
        block = self.foreshadow_block(cap=cap)
        parts.append(block if block else "未回收伏笔：无")
        return "\n".join(parts)


class LongTermMemory:
    """长期记忆：把溢出窗口的旧对话摘要成精简文字，永久保留。"""

    def __init__(self):
        self.summaries: List[str] = []

    def summarize(
        self, old_messages: List, llm: LLMClient, temperature: float = 0.3
    ) -> str:
        """把溢出的旧消息丢给 LLM 压成摘要，返回摘要文本（由调用方决定是否存）。

        temperature 由调用方从 settings.summarizer_temperature 传入（0.9 全量可配）。
        """
        text = "\n".join(str(m) for m in old_messages)
        return llm.chat(
            SUMMARIZER_SYSTEM, text, max_tokens=1024, temperature=temperature
        )

    def add_summary(self, text: str) -> None:
        """把新摘要存进列表，永久保留。"""
        if text:
            self.summaries.append(text)

    def context(self) -> str:
        """所有摘要拼起来，给模型当"很久以前的事"的备忘。"""
        return "\n".join(self.summaries)
