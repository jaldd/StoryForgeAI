"""存储层：章节落盘 + run 日志 + 工作记忆持久化。

补 py/multiagent_novel.py 的 gap：原版只存 run 日志，没存章节文件。
工作记忆持久化让"连续写多章、后章记得前章"跨进程成立（P1）。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .config import Settings, get_settings
from .memory import (
    WorkingMemory,
    normalize_character_states,
    normalize_foreshadowing,
    normalize_resolved,
)

__all__ = [
    "parse_chapter_task",
    "parse_chapter_range",
    "parse_chapter_plan",
    "cn_numeral",
    "parse_chapter_file",
    "save_run",
    "load_run",
    "list_runs",
    "run_path",
    "save_chapter",
    "save_working_memory",
    "load_working_memory",
]

WORKING_MEMORY_FILE = "working_memory.json"

# 开头的章节标题行（LLM 常自带头部，存盘时去掉避免与我们的标题重复）
# 数字兼容阿拉伯（5）与中文（五、十二）
_CHAP_NUM = r"[0-9一二三四五六七八九十百千零两]+"
_LEADING_TITLE_RE = re.compile(rf"^\s*(?:#+\s*)?第\s*{_CHAP_NUM}\s*章[^\n]*\n+", re.M)


def _strip_leading_title(text: str) -> str:
    """去掉正文开头的章节标题行（markdown 或纯文本）+ 紧随的空行。"""
    text = text.lstrip()
    while True:
        m = _LEADING_TITLE_RE.match(text)
        if not m:
            break
        text = text[m.end():].lstrip()
    return text


# ---------- 任务解析 ----------
def parse_chapter_task(task: str) -> Tuple[Optional[int], str]:
    """从任务里解析章节号和标题。

    "写第5章：异乡风起" -> (5, "异乡风起")
    解析失败 -> (None, task 去掉前缀后的文本)
    """
    m = re.search(r"第\s*(\d+)\s*章\s*[：:]\s*(.+)", task)
    if m:
        return int(m.group(1)), m.group(2).strip()
    return None, task.strip()


# ---------- 区间与章纲解析（2.2 批量，D6/D7）----------
# 区间命令：写第5-10章 / 写第5-10章：模板。分隔符认 -/-/–/～/至（Z3：全角形态高频）
_RANGE_RE = re.compile(
    r"第\s*(\d+)\s*[-－–~～至]\s*(\d+)\s*章(?:\s*[：:]\s*(.+))?"
)
# 章纲表格首列的章号形态：纯整数（5）或带章字（第5章/5章）
_PLAN_CHAP_RE = re.compile(r"^\s*(?:第\s*)?(\d+)\s*章?\s*$")
# 分隔行：| --- | --- |（冒号对齐语法也认）
_PLAN_SEP_RE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")


def parse_chapter_range(task: str) -> Optional[Tuple[int, int, Optional[str]]]:
    """区间写命令 -> (起始章, 结束章, 标题模板或 None)；不匹配 -> None。

    "写第5-10章" -> (5, 10, None)；"写第5-10章：异乡风起" -> (5, 10, "异乡风起")。
    单章命令（写第5章：标题）不匹配（无第二数字），依赖分发「先区间后单章」
    保证互斥（design §6）。
    """
    m = _RANGE_RE.search(task)
    if not m:
        return None
    title = m.group(3).strip() if m.group(3) else None
    return int(m.group(1)), int(m.group(2)), title


def parse_chapter_plan(text: str) -> Dict[int, Dict[str, Any]]:
    """章纲 markdown -> {章号: {"title": 标题, "notes": [(列名, 值), ...]}}。

    - 扫描全部 markdown 表格块（分卷多表格合并成一个映射，T16）；
    - 列头兼容「标题/暂定标题」；首列非章号的表格（无「章」+「标题」列头）跳过；
    - 分隔行（---）跳过；章号非整数行跳过；
    - notes = 标题列之后的各列 (列名, 值) 对，列名原样保留
      （核心事件/天气/矛盾种子……未来加列零改动）；
    - 同章号重复取后者（Z7：修订覆盖草稿）。
    """
    plans: Dict[int, Dict[str, Any]] = {}
    lines = text.splitlines()
    i, n = 0, len(lines)
    while i < n:
        if not lines[i].lstrip().startswith("|"):
            i += 1
            continue
        block: List[str] = []
        while i < n and lines[i].lstrip().startswith("|"):
            block.append(lines[i].strip())
            i += 1
        _parse_plan_table(block, plans)
    return plans


def _parse_plan_table(block: List[str], plans: Dict[int, Dict[str, Any]]) -> None:
    """单个表格块并入 plans（不合法的表格静默跳过，对齐缺失静默降级纪律）。"""
    rows = [
        [c.strip() for c in line.strip().strip("|").split("|")]
        for line in block
        if not _PLAN_SEP_RE.match(line)
    ]
    if len(rows) < 2 or not rows[0]:
        return
    header = rows[0]
    # 首列须是「章」列头，且存在「标题/暂定标题」列头（否则不是章纲表格，跳过）
    if "章" not in header[0]:
        return
    title_idx = next(
        (j for j, name in enumerate(header[1:], start=1) if name in ("标题", "暂定标题")),
        None,
    )
    if title_idx is None:
        return
    for row in rows[1:]:
        m = _PLAN_CHAP_RE.match(row[0]) if row else None
        if not m:
            continue  # 脏行/散文说明行：首列非章号，跳过
        num = int(m.group(1))
        title = row[title_idx] if len(row) > title_idx else ""
        notes = [
            (header[j], row[j] if len(row) > j else "")
            for j in range(title_idx + 1, len(header))
        ]
        plans[num] = {"title": title, "notes": notes}


_CN_DIGITS = "零一二三四五六七八九"


def cn_numeral(n: int) -> str:
    """1 -> 一 … 99 -> 九十九（标题模板的中文序数后缀，纯函数）。

    越界（<1 或 >99）抛 ValueError（Z6：纯函数 fail-fast）。
    """
    if not isinstance(n, int) or n < 1 or n > 99:
        raise ValueError(f"cn_numeral 只支持 1-99，收到 {n!r}")
    if n < 10:
        return _CN_DIGITS[n]
    tens, ones = divmod(n, 10)
    if tens == 1:
        return "十" + (_CN_DIGITS[ones] if ones else "")
    return _CN_DIGITS[tens] + "十" + (_CN_DIGITS[ones] if ones else "")


def parse_chapter_file(path: Path) -> Tuple[Optional[int], str]:
    """从章节文件名解析 (章号, 标题)。

    匹配 save_chapter 落盘格式「第05章-标题.md」（按「-」分隔，零填充章号）；
    同名追加 run_id 后缀的「第05章-标题-run_xxx.md」同样匹配（标题取到第一个后缀前）。
    卷对齐格式「第一卷-38.md」（卷名-卷内章号，volume-align V6）返回 (38, "")；
    判定序：既有格式先、卷格式后（防「第05章-标题2」类标题以数字结尾的误判，D5）。
    不匹配 -> (None, stem)，调用方按「无章号」处理（如跳过工作记忆刷新，A21）。
    """
    stem = path.stem
    m = re.match(r"第\s*0*(\d+)\s*章\s*-\s*(.+)", stem)
    if m:
        return int(m.group(1)), m.group(2).strip()
    m = re.match(r"^(.+?)-(\d{1,4})$", stem)  # 卷名-NN（懒匹配，锚定结尾）
    if m:
        return int(m.group(2)), ""
    return None, stem


# ---------- run 日志 ----------
def run_path(run_id: str, settings: Optional[Settings] = None) -> Path:
    """run_id（带或不带 .json）-> 对应 JSON 文件路径。"""
    settings = settings or get_settings()
    rid = run_id if run_id.endswith(".json") else f"{run_id}.json"
    return settings.runs_path / rid


def save_run(record: Dict[str, Any], settings: Optional[Settings] = None) -> Path:
    """把运行记录落盘到 py/runs/<run_id>.json。"""
    settings = settings or get_settings()
    settings.runs_path.mkdir(parents=True, exist_ok=True)
    path = settings.runs_path / f"{record['run_id']}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)
    return path


def load_run(run_id: str, settings: Optional[Settings] = None) -> Dict[str, Any]:
    """读取一次运行的 JSON 日志。"""
    path = run_path(run_id, settings)
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def list_runs(settings: Optional[Settings] = None) -> List[str]:
    """列出所有 run_id（不带 .json），按文件名倒序（新的在前）。"""
    settings = settings or get_settings()
    if not settings.runs_path.exists():
        return []
    ids = [p.stem for p in settings.runs_path.glob("run_*.json")]
    ids.sort(reverse=True)
    return ids


# ---------- 章节落盘 ----------
def save_chapter(
    final_chapter: str,
    task: str,
    run_id: str,
    settings: Optional[Settings] = None,
) -> Path:
    """把定稿存到章节目录（NOVEL_CHAPTER_SUBDIR）。

    平铺模式（默认）：文件名 第05章-异乡风起.md（解析失败则用 run_id）；
    同名已存在时不覆盖，追加 run_id 后缀保留历史。

    卷对齐模式（NOVEL_VOLUME_ALIGN=1，volume-align V1-V4）：前提 subdir 指到
    当前卷目录（如 正文/第一卷）；文件名 {卷名}-{NN}.md（卷名 = subdir 末段，
    不含标题），头行 ## 第{中文数字}章 {标题}（对齐人工原稿约定），**直接覆盖**
    已有文件（重写工作流：git diff 即比对，run record 另存全文双保险）；
    章号解析不出（番外）回落平铺命名不覆盖。
    """
    settings = settings or get_settings()
    settings.chapter_path.mkdir(parents=True, exist_ok=True)

    num, title = parse_chapter_task(task)
    if num is not None and settings.volume_align:
        vol = Path(settings.chapter_subdir).name
        path = settings.chapter_path / f"{vol}-{num:02d}.md"
        try:
            cn = cn_numeral(num)
        except ValueError:
            cn = str(num)  # >99 回落阿拉伯数字（V2），不崩
        body = _strip_leading_title(final_chapter)
        header = f"## 第{cn}章 {title}".rstrip() + "\n\n"
        with open(path, "w", encoding="utf-8") as f:
            f.write(header + body)
        return path

    if num is not None:
        base = f"第{num:02d}章-{title}"
    else:
        base = run_id
    path = settings.chapter_path / f"{base}.md"
    if path.exists():
        path = settings.chapter_path / f"{base}-{run_id}.md"

    # 正文头部：第N章 标题（与现有文风基准格式一致：标题行 + 空行 + 正文）
    if num is not None:
        body = _strip_leading_title(final_chapter)
        header = f"第{num}章 {title}\n\n"
    else:
        body = final_chapter
        header = ""
    with open(path, "w", encoding="utf-8") as f:
        f.write(header + body)
    return path


# ---------- 工作记忆持久化 ----------
def _wm_path(settings: Settings) -> Path:
    return settings.working_memory_path


def save_working_memory(
    wm: WorkingMemory, settings: Optional[Settings] = None
) -> Path:
    """把工作记忆落盘（跨进程连续写作用）。"""
    settings = settings or get_settings()
    settings.runs_path.mkdir(parents=True, exist_ok=True)
    path = _wm_path(settings)
    data = {
        "current_chapter": wm.current_chapter,
        "character_states": wm.character_states,
        "unresolved_foreshadowing": wm.unresolved_foreshadowing,
        "resolved_foreshadowing": wm.resolved_foreshadowing,
        "last_plot_point": wm.last_plot_point,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def load_working_memory(settings: Optional[Settings] = None) -> WorkingMemory:
    """加载工作记忆；文件不存在则返回空实例。"""
    settings = settings or get_settings()
    path = _wm_path(settings)
    wm = WorkingMemory()
    if path.exists():
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        wm.current_chapter = data.get("current_chapter")
        # 3.2 C6：条目非 dict 或缺 stage 丢弃，不因一条脏数据拒载整个文件
        wm.character_states = normalize_character_states(
            data.get("character_states", {})
        )
        # 3.1 F6：旧版纯字符串列表 -> dict 条目；脏元素丢弃，不因一条脏数据拒载整个文件
        wm.unresolved_foreshadowing = normalize_foreshadowing(
            data.get("unresolved_foreshadowing", [])
        )
        wm.resolved_foreshadowing = normalize_resolved(
            data.get("resolved_foreshadowing", [])
        )
        wm.last_plot_point = data.get("last_plot_point")
    return wm
