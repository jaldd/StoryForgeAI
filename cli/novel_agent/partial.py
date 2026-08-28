"""局部精修的纯函数层：段落切分 / 选段解析 / 上下文构造 / 逐字节保真回填。

设计见 specs/partial-refine/design.md §4：
- 全部为纯函数：无 IO、无 LLM、无 settings 依赖，可独立单测（宪法 §5）。
- 逐字节保真的口径（design.md §5.1）：切分保留原始行尾（\\r\\n）、BOM 与
  文件尾字节，回填只替换选区区间内的块，区间外原样拼接；读写由 cli 层
  用 read_bytes().decode("utf-8") / write_bytes 完成，不走 read_text/write_text。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

__all__ = [
    "Block",
    "split_paragraphs",
    "parse_selection",
    "build_context_pair",
    "apply_replacements",
    "preview_line",
]

# 章节头行（复用 storage._LEADING_TITLE_RE 思路）：第N章 / # 第N章 / 第 十二 章，
# 数字兼容阿拉伯与中文。partial 不 import storage，避免引入 config 依赖链。
_CHAP_NUM = r"[0-9一二三四五六七八九十百千零两]+"
_LEADING_TITLE_RE = re.compile(rf"^\s*(?:#+\s*)?第\s*{_CHAP_NUM}\s*章")


@dataclass
class Block:
    """段落块：split_paragraphs 的切分单元。

    - no:   段落编号（para 按出现顺序从 1 递增）；title/sep/preamble 块为 None
    - kind: "title"（文件头章节标题，不编号）| "sep"（独立 --- 场景分隔，不编号）
            | "para"（正文段）| "preamble"（文件开头悬挂空行，含 BOM，永不编号）
    - text: 原始文本（keepends，含块尾空行，保 \\r\\n），回填拼接时用
    - body: 内容部分（去掉尾部空行），预览 / 送 LLM 时用
    """

    no: Optional[int]
    kind: str
    text: str
    body: str


def _is_blank_line(line: str) -> bool:
    """空行判断：strip 后为空；行首 BOM 也视作空白（开头悬挂 BOM 行归 preamble）。"""
    return not line.strip("\ufeff").strip()


def _is_title_body(body: str) -> bool:
    """单行且匹配章节头模式（容忍行首 BOM）。"""
    line = body.lstrip("\ufeff")
    return "\n" not in line and bool(_LEADING_TITLE_RE.match(line))


def split_paragraphs(text: str) -> List[Block]:
    """把全文切成 Block 列表（纯函数，保字节）。

    规则（design.md §4）：
    - 连续「strip 后非空」的行聚为一块，块后空行归入该块尾部；
    - 文件开头悬挂空行（含 BOM）聚为一个 preamble 匿名块（不编号）；
    - 第一个内容块若单行且匹配章节头模式 -> title（不编号）；
    - 块内容 strip 后等于 --- -> sep（不编号）；
    - 其余 -> para，按出现顺序从 1 编号。

    保真："".join(b.text for b in blocks) == text 恒成立。
    """
    lines = text.splitlines(keepends=True)
    blocks: List[Block] = []

    # 1. 开头悬挂空行（含 BOM）-> preamble 匿名块
    i = 0
    while i < len(lines) and _is_blank_line(lines[i]):
        i += 1
    if i:
        blocks.append(Block(no=None, kind="preamble", text="".join(lines[:i]), body=""))

    # 2. 聚合：连续非空行为块内容，其后连续空行归该块尾部
    while i < len(lines):
        j = i
        while j < len(lines) and not _is_blank_line(lines[j]):
            j += 1
        content = "".join(lines[i:j])
        k = j
        while k < len(lines) and _is_blank_line(lines[k]):
            k += 1
        trailing = "".join(lines[j:k])
        blocks.append(
            Block(no=None, kind="para", text=content + trailing,
                  body=content.rstrip("\r\n"))
        )
        i = k

    # 3. 分类与编号（只看第一个内容块是否章节头，与 storage 存盘格式对齐）
    no = 0
    seen_content = False
    for b in blocks:
        if b.kind == "preamble":
            continue
        if not seen_content:
            seen_content = True
            if _is_title_body(b.body):
                b.kind = "title"
                continue
        if b.body.strip() == "---":
            b.kind = "sep"
        else:
            no += 1
            b.no = no
    return blocks


def parse_selection(spec: str, max_no: int) -> List[Tuple[int, int]]:
    """解析选段表达式为升序闭区间列表（纯函数）。

    语法（design.md §4）：`<no>` | `<a>-<b>` | 逗号组合（`3-5,7`）；项间允许空格。
    相邻/重叠编号去重合并为区间（`3,4,5` -> [(3, 5)]）。
    非法输入（编号为 0、超出 max_no、区间倒置、非数字）raise ValueError，
    错误消息含原因（宪法 §1：不含任何小说名）。
    """
    text = (spec or "").strip()
    if not text:
        raise ValueError("选段表达式为空")
    # 字符集快速校验：只允许数字、逗号、连字符、空格
    if not re.fullmatch(r"[0-9,\s\-]+", text):
        raise ValueError(f"选段表达式不合法：{text}（只支持数字、连字符、逗号和空格）")
    # 项间空格（含全角）等同逗号
    text = re.sub(r"[,\s]+", ",", text)

    nums: List[int] = []
    for item in text.split(","):
        m = re.fullmatch(r"(\d+)-(\d+)", item)
        if m:
            lo, hi = int(m.group(1)), int(m.group(2))
            if lo > hi:
                raise ValueError(f"区间倒置：{item}（应从小到大，如 {hi}-{lo}）")
        elif re.fullmatch(r"\d+", item):
            lo = hi = int(item)
        else:
            raise ValueError(f"选段表达式不合法：{item}")
        for n in (lo, hi):
            if n < 1 or n > max_no:
                raise ValueError(f"编号 {n} 超出范围（共 {max_no} 段）")
        nums.extend(range(lo, hi + 1))

    # 排序去重 -> 聚合相邻编号为区间
    spans: List[Tuple[int, int]] = []
    for n in sorted(set(nums)):
        if spans and n == spans[-1][1] + 1:
            spans[-1] = (spans[-1][0], n)
        else:
            spans.append((n, n))
    return spans


def build_context_pair(blocks: List[Block], span: Tuple[int, int]) -> Tuple[str, str]:
    """取选区物理相邻的前后块文本（纯函数）。

    - span 为闭区间 (lo, hi)；选区首段物理前最近的 1 个块作 before，
      末段物理后最近的 1 个块作 after（无论 kind：`---`、章节头、preamble 亦可，
      保持文本流原貌，design.md §4 D4）。
    - 文件首段无 before、末段无 after 时返回空串。
    - 返回块的 body（不含尾部空行），作 LLM 上下文输入。
    """
    index_of = {b.no: i for i, b in enumerate(blocks) if b.no is not None}
    lo, hi = span
    first_i = index_of[lo]
    last_i = index_of[hi]
    before = blocks[first_i - 1].body if first_i > 0 else ""
    after = blocks[last_i + 1].body if last_i + 1 < len(blocks) else ""
    return before, after


def apply_replacements(
    text: str,
    blocks: List[Block],
    spans: List[Tuple[int, int]],
    new_texts: List[str],
) -> str:
    """把各选区区间整块替换为对应新文本，返回回填后的全文（纯函数，保字节）。

    规则（design.md §4）：
    - spans 与 new_texts 按序一一对应（升序互不重叠由 parse_selection 保证）；
    - 每个区间覆盖的全部块（含区间内部的空行结构）整块替换为
      `new_text.rstrip("\n") + 区间末块原尾部空行`（含行尾 \r\n 与块后空行）；
    - 区间外的所有块原样拼接（含 `\r\n`、BOM、文件尾字节）；
    - 恒等式：spans 为空时返回原文（"".join(b.text) == text）。
    """
    index_of = {b.no: i for i, b in enumerate(blocks) if b.no is not None}
    # 区间 -> 物理块索引闭区间
    regions = [(index_of[lo], index_of[hi]) for lo, hi in spans]

    parts: List[str] = []
    i = 0
    ri = 0
    while i < len(blocks):
        if ri < len(regions) and i == regions[ri][0]:
            _, hi_i = regions[ri]
            last = blocks[hi_i]
            # 末块 text 中 body 之后的尾部（行尾换行 + 块后空行）原样保留
            trailing = last.text[len(last.body):]
            parts.append(new_texts[ri].rstrip("\n") + trailing)
            i = hi_i + 1
            ri += 1
        else:
            parts.append(blocks[i].text)
            i += 1
    return "".join(parts)


def preview_line(block: Block, width: int = 40) -> str:
    """段落列表的单行预览（A1/D10：全量列出，预览 40 字）。

    - para：`编号: 预览（字数）`；多行块折叠为单行后按 width 截断；
    - title/sep：无编号行，标明类型（内容完整保留在文件中，仅列表展示）；
    - preamble：返回空串（悬挂空行无展示价值，cli 层跳过）。
    """
    if block.kind == "para":
        body = block.body.replace("\n", " ").replace("\r", "")
        clip = body[:width] + ("…" if len(body) > width else "")
        return f"{block.no}: {clip}（{len(block.body)}字）"
    if block.kind == "title":
        body = block.body.replace("\n", " ").replace("\r", "")
        clip = body[:width] + ("…" if len(body) > width else "")
        return f"  [章节头] {clip}"
    if block.kind == "sep":
        return "  [分隔符] ---"
    return ""
