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
from .memory import WorkingMemory

__all__ = [
    "parse_chapter_task",
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
    """把定稿存到 docs/.../正文/AI生成/。

    文件名：第05章-异乡风起.md（解析失败则用 run_id）。
    同名已存在时不覆盖，追加 run_id 后缀保留历史。
    """
    settings = settings or get_settings()
    settings.chapter_path.mkdir(parents=True, exist_ok=True)

    num, title = parse_chapter_task(task)
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
        wm.character_states = data.get("character_states", {}) or {}
        wm.unresolved_foreshadowing = data.get("unresolved_foreshadowing", []) or []
        wm.last_plot_point = data.get("last_plot_point")
    return wm
