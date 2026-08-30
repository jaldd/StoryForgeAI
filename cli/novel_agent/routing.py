"""文风基准按章路由（exemplar-routing）：标签解析 + 一次 LLM 路由调用。

设计见 specs/exemplar-routing/design.md §3：
- parse_tag_lines：纯函数，解析《样文标签.md》的标签行；
- route_exemplars：一次廉价 LLM 调用（主 profile，max_tokens=1024，温度 0.2），
  按本章任务从标签列表选样文；解析失败/编造文件名/全落空 -> None（cli 层回落现状加载）。
- 路由永远不阻塞写作：LLM 异常由调用方（cli._build_agent）捕获后回落。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .llm import LLMClient
from .prompts import EXEMPLAR_ROUTER_SYSTEM, exemplar_router_user

__all__ = ["RouteResult", "parse_tag_lines", "route_exemplars"]

# 标签行：`- 5.txt: 她在场时他慢慢落下来`。文件名 token 口径同 prompts._MANIFEST_LINE_RE
# （截到空白/全半角括号/冒号逗号），再要求紧跟冒号 + 非空描述。
_TAG_LINE_RE = re.compile(r"^[-*]\s+([^\s（()：:，,]+)[：:]\s*(\S.*)$")


@dataclass(frozen=True)
class RouteResult:
    """路由结果：选中的样文文件名（有序）+ 一句话理由。"""

    files: List[str] = field(default_factory=list)
    reason: str = ""


def parse_tag_lines(text: str) -> List[Tuple[str, str]]:
    """解析《样文标签.md》为 (文件名, 描述) 列表（纯函数，按出现顺序）。

    - 只取 `- 文件名: 描述` / `* 文件名：描述` 形态的列表行；
    - 标题/说明文字/无冒号描述的行一律跳过（容错：标签文件是人写的）。
    """
    tags: List[Tuple[str, str]] = []
    for line in text.splitlines():
        m = _TAG_LINE_RE.match(line.strip())
        if m:
            tags.append((m.group(1), m.group(2).strip()))
    return tags


def _parse_router_json(raw: str) -> Optional[dict]:
    """路由输出 JSON 容错链：直读 -> 剥代码围栏 -> 抓首个 {...} 块；全败 None。

    与 agent.parse_review 同哲学（多级解析 + 兜底 None），但出口结构不同（files/reason）。
    """
    if not raw:
        return None
    text = raw.strip()
    candidates = [text]
    # 剥 ``` 围栏（```json ... ``` / ``` ... ```）
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        candidates.insert(0, fenced.group(1).strip())
    # 抓首个大括号块（前后有散文时）
    brace = re.search(r"\{.*\}", text, re.DOTALL)
    if brace:
        candidates.append(brace.group(0))
    for cand in candidates:
        try:
            val = json.loads(cand)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(val, dict):
            return val
    return None


def route_exemplars(
    llm: LLMClient,
    task: str,
    tags: List[Tuple[str, str]],
    temperature: float = 0.2,
) -> Optional[RouteResult]:
    """按本章任务路由样文：返回选中文件名 + 理由；失败返回 None（回落）。

    - tags 为空直接 None（调用方不必先判空，防御性兜底）；
    - files 过滤：不在标签文件名集合内的丢弃（模型编造的文件名不进加载）；
      过滤后为空也返回 None（全落空 = 失败，A4）。
    - LLM 调用异常向上传播，由 cli 层捕获回落（A3：路由不阻塞写作）。
    - temperature 由调用方从 settings 传入（0.9 全量可配；默认 0.2 要稳）。
    """
    if not tags:
        return None
    valid_names = {name for name, _ in tags}
    raw = llm.chat(
        EXEMPLAR_ROUTER_SYSTEM,
        exemplar_router_user(task, tags),
        max_tokens=1024,      # 宪法 §4：短输出调用至少 1024
        temperature=temperature,
    )
    data = _parse_router_json(raw)
    if data is None:
        return None
    files_raw = data.get("files")
    if not isinstance(files_raw, list):
        return None
    files = [f for f in files_raw if isinstance(f, str) and f in valid_names]
    # 去重保序
    seen = set()
    ordered = [f for f in files if not (f in seen or seen.add(f))]
    if not ordered:
        return None
    reason = data.get("reason")
    return RouteResult(files=ordered, reason=reason if isinstance(reason, str) else "")
