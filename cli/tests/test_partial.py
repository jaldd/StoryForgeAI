"""partial 纯函数测试：切分 / 选段 / 上下文 / 回填（无 mock，不联网）。

对应 design.md §8.1。逐字节保真的工程口径：选区外前后缀 read_bytes 级不变。
"""
from __future__ import annotations

import pytest

from novel_agent.partial import (
    apply_replacements,
    build_context_pair,
    parse_selection,
    preview_line,
    split_paragraphs,
)


# ---------- split：基本切分 ----------
def test_split_basic_paragraphs():
    """空行切块，para 按出现顺序从 1 编号。"""
    text = "第一段。\n\n第二段。\n\n第三段。\n"
    blocks = split_paragraphs(text)
    assert [b.no for b in blocks] == [1, 2, 3]
    assert all(b.kind == "para" for b in blocks)
    assert blocks[0].body == "第一段。"


def test_split_trailing_blank_lines_to_prev():
    """块后连续空行归前段尾部：text 含空行，body 不含。"""
    text = "第一段。\n\n\n\n第二段。\n"
    blocks = split_paragraphs(text)
    assert len(blocks) == 2
    assert blocks[0].text == "第一段。\n\n\n\n"
    assert blocks[0].body == "第一段。"


def test_split_multi_line_block_body_keeps_inner_newlines():
    """无空行分隔的连续非空行聚为一块，body 保留中间换行。"""
    text = "第一行\n第二行\n\n第二段。\n"
    blocks = split_paragraphs(text)
    assert len(blocks) == 2
    assert blocks[0].body == "第一行\n第二行"
    assert blocks[0].text == "第一行\n第二行\n\n"


def test_split_roundtrip_concat():
    """保真必要条件：所有块 text 拼接 == 原文（含 \\r\\n、BOM、无尾换行）。"""
    text = "\ufeff\n\n第5章 风起\n\n第一段。\n\n\n---\r\n\r\n第二段。\r\n最后一段"
    assert "".join(b.text for b in split_paragraphs(text)) == text


# ---------- split：title / sep 不占编号 ----------
def test_split_title_and_sep_not_numbered():
    """文件头章节标题与独立 --- 不占编号，编号连续正确。"""
    text = "第5章 风起\n\n第一段。\n\n---\n\n第二段。\n"
    blocks = split_paragraphs(text)
    assert [b.kind for b in blocks] == ["title", "para", "sep", "para"]
    assert [b.no for b in blocks] == [None, 1, None, 2]


def test_split_title_variants():
    """markdown # 前缀与中文数字章节头也识别为 title。"""
    for head in ("# 第12章 夜雨", "第 十二 章 夜雨", "第3章：风起"):
        blocks = split_paragraphs(f"{head}\n\n正文段。\n")
        assert blocks[0].kind == "title", head
        assert blocks[0].no is None
        assert blocks[1].no == 1


def test_split_title_only_first_content_block():
    """章节头只识别文件头（跳过 preamble 后的第一个内容块），中间出现按 para 编号。"""
    text = "第一段。\n\n第5章 风起\n"
    blocks = split_paragraphs(text)
    assert [b.kind for b in blocks] == ["para", "para"]
    assert [b.no for b in blocks] == [1, 2]


def test_split_no_numberable_paragraphs():
    """仅标题/分隔符：无可编号段落（cli 层据此退出命令，A3）。"""
    text = "第5章 风起\n\n---\n\n---\n"
    blocks = split_paragraphs(text)
    assert [b.kind for b in blocks] == ["title", "sep", "sep"]
    assert all(b.no is None for b in blocks)


# ---------- split：字节保真（\r\n / BOM / 文件尾） ----------
def test_split_keeps_crlf():
    """\\r\\n 行尾原样保留在块 text 中。"""
    text = "第5章 风起\r\n\r\n第一段。\r\n\r\n---\r\n\r\n第二段。\r\n"
    blocks = split_paragraphs(text)
    assert blocks[0].kind == "title"
    assert blocks[0].text == "第5章 风起\r\n\r\n"
    assert blocks[2].kind == "sep"
    assert blocks[2].text == "---\r\n\r\n"
    assert blocks[3].body == "第二段。"


def test_split_keeps_bom_in_first_block():
    """BOM 保留在首块头部（非 utf-8-sig decode），章节头仍可识别。"""
    text = "\ufeff第5章 风起\n\n正文。\n"
    blocks = split_paragraphs(text)
    assert blocks[0].kind == "title"
    assert blocks[0].text.startswith("\ufeff")
    assert blocks[1].no == 1


def test_split_leading_blank_with_bom_is_preamble():
    """开头空行 + BOM 聚为 preamble 匿名块（不编号、不占段落）。"""
    text = "\ufeff\n\n第5章 风起\n\n正文。\n"
    blocks = split_paragraphs(text)
    assert blocks[0].no is None
    assert blocks[0].text == "\ufeff\n\n"
    assert blocks[1].kind == "title"
    assert blocks[2].no == 1


def test_split_no_trailing_newline():
    """文件尾无换行：原样保留，不补字节。"""
    blocks = split_paragraphs("第一段。\n\n第二段。")
    assert blocks[1].text == "第二段。"
    assert blocks[1].body == "第二段。"


def test_split_single_line_file():
    """整个文件一行无空行：1 个 para 块，正常可选可改。"""
    blocks = split_paragraphs("只有一段没有换行")
    assert len(blocks) == 1
    assert blocks[0].kind == "para"
    assert blocks[0].no == 1
    assert blocks[0].text == "只有一段没有换行"


# ---------- parse：合法 5 式 ----------
def test_parse_single():
    """单段：3 -> [(3, 3)]。"""
    assert parse_selection("3", 10) == [(3, 3)]


def test_parse_range():
    """闭区间：3-5 -> [(3, 5)]。"""
    assert parse_selection("3-5", 10) == [(3, 5)]


def test_parse_comma():
    """并列：3,7 -> [(3, 3), (7, 7)]。"""
    assert parse_selection("3,7", 10) == [(3, 3), (7, 7)]


def test_parse_combined():
    """组合：3-5,7 -> [(3, 5), (7, 7)]。"""
    assert parse_selection("3-5,7", 10) == [(3, 5), (7, 7)]


def test_parse_merge_adjacent():
    """相邻编号合并：3,4,5 -> [(3, 5)]。"""
    assert parse_selection("3,4,5", 10) == [(3, 5)]


def test_parse_space_as_comma_and_unordered_input():
    """项间空格等同逗号；乱序输入升序合并；连续分隔符合并为一个。"""
    assert parse_selection("3 7", 10) == [(3, 3), (7, 7)]
    assert parse_selection("7,3-5", 10) == [(3, 5), (7, 7)]
    assert parse_selection("3,,5", 10) == [(3, 3), (5, 5)]


def test_parse_reject_full_width_comma():
    """全角逗号不在允许字符集（规格只支持半角），按非法字符拒绝。"""
    with pytest.raises(ValueError) as e:
        parse_selection("3，5", 10)
    assert "不合法" in str(e.value)


# ---------- parse：非法 4 式（消息含原因） ----------
def test_parse_reject_zero():
    """编号 0 -> 抛错且消息含原因。"""
    with pytest.raises(ValueError) as e:
        parse_selection("0", 10)
    assert "0" in str(e.value)
    assert "超出范围" in str(e.value)


def test_parse_reject_out_of_range():
    """超界：99（共 10 段）-> 消息含编号与段数。"""
    with pytest.raises(ValueError) as e:
        parse_selection("99", 10)
    assert "99" in str(e.value)
    assert "10" in str(e.value)


def test_parse_reject_reversed_range():
    """区间倒置：5-3 -> 消息含倒置原因。"""
    with pytest.raises(ValueError) as e:
        parse_selection("5-3", 10)
    assert "倒置" in str(e.value)


def test_parse_reject_non_numeric():
    """非数字：abc -> 消息含不合法原因。"""
    with pytest.raises(ValueError) as e:
        parse_selection("abc", 10)
    assert "不合法" in str(e.value)


def test_parse_reject_empty_and_malformed():
    """空串/空项/畸形组合均拒绝。"""
    for bad in ("", "  ", "3-", "3-5-7", "3;5", "3.5", "3..5"):
        with pytest.raises(ValueError):
            parse_selection(bad, 10)


def test_parse_boundary_ok():
    """边界编号 1 与 max_no 合法。"""
    assert parse_selection("1", 1) == [(1, 1)]
    assert parse_selection("1-3", 3) == [(1, 3)]


# ---------- context：物理相邻上下文 ----------
def test_context_adjacent_paragraphs():
    """前后各取物理相邻 1 块（普通段落）：选区 2-3 的 before 是 1 段、after 是 4 段。"""
    text = "第一段。\n\n第二段。\n\n第三段。\n\n第四段。\n\n第五段。\n"
    blocks = split_paragraphs(text)
    assert build_context_pair(blocks, (2, 3)) == ("第一段。", "第四段。")


def test_context_sep_and_title_can_be_context():
    """`---` 与章节头可作上下文（保持文本流原貌，D4）。"""
    text = "第5章 风起\n\n第一段。\n\n---\n\n第二段。\n\n第三段。\n"
    blocks = split_paragraphs(text)
    # 第 1 段物理前是章节头
    before, after = build_context_pair(blocks, (1, 1))
    assert before == "第5章 风起"
    assert after == "---"
    # 第 2 段物理前是 ---
    before, after = build_context_pair(blocks, (2, 2))
    assert before == "---"
    assert after == "第三段。"


def test_context_first_and_last_block_empty():
    """物理首段（无前置块）无 before、物理末段无 after：返回空串。"""
    text = "第一段。\n\n第二段。\n\n第三段。\n"
    blocks = split_paragraphs(text)
    assert build_context_pair(blocks, (1, 1)) == ("", "第二段。")
    assert build_context_pair(blocks, (3, 3)) == ("第二段。", "")
    assert build_context_pair(blocks, (1, 3)) == ("", "")


# ---------- apply：逐字节保真回填 ----------
def test_apply_range_preserves_outside_bytes():
    """改 3-5（跨 sep 的区间）：选区外前缀逐字节不变；区间整体替换。"""
    text = "第5章 风起\n\n第一段。\n\n第二段。\n\n第三段。\n\n---\n\n第四段。\n\n第五段。\n"
    blocks = split_paragraphs(text)
    new = apply_replacements(text, blocks, [(3, 5)], ["新选区内容。"])
    prefix = "第5章 风起\n\n第一段。\n\n第二段。\n\n"
    # 末块（第五段）text 为 "第五段。\n"，尾部换行保留
    assert new == prefix + "新选区内容。\n"
    # read_bytes 级：前缀逐字节一致
    assert new.startswith(prefix)
    assert new.encode("utf-8").startswith(prefix.encode("utf-8"))


def test_apply_keeps_title_and_sep_outside_range():
    """区间外的 title 与 `---` 原样保留（A9）。"""
    text = "第5章 风起\n\n第一段。\n\n---\n\n第二段。\n\n第三段。\n"
    blocks = split_paragraphs(text)
    new = apply_replacements(text, blocks, [(2, 2)], ["第二段改。"])
    assert new == "第5章 风起\n\n第一段。\n\n---\n\n第二段改。\n\n第三段。\n"


def test_apply_trailing_blank_lines_of_last_block_kept():
    """区间末块尾部空行（含连续多个）原样保留，选区后块相对位置不变。"""
    text = "第一段。\n\n第二段。\n\n\n\n第三段。\n"
    blocks = split_paragraphs(text)
    new = apply_replacements(text, blocks, [(1, 2)], ["改后段。"])
    # 末块（第二段）行尾 + 其后 3 个空行共 4 个 \n 原样保留
    assert new == "改后段。\n\n\n\n第三段。\n"


def test_apply_multiple_spans_each_replaced():
    """多区间 `3,7`：各区间替换为对应新文本（R2 前置）。"""
    text = "一\n\n二\n\n三\n\n四\n\n五\n\n六\n\n七"
    blocks = split_paragraphs(text)
    new = apply_replacements(text, blocks, [(3, 3), (7, 7)], ["叁", "柒"])
    assert new == "一\n\n二\n\n叁\n\n四\n\n五\n\n六\n\n柒"


def test_apply_no_trailing_newline_at_eof():
    """区间含文件末块且原文件无尾换行：替换后仍无尾换行。"""
    text = "第一段。\n\n第二段。"
    blocks = split_paragraphs(text)
    new = apply_replacements(text, blocks, [(2, 2)], ["改后末段"])
    assert new == "第一段。\n\n改后末段"


def test_apply_crlf_and_bom_preserved():
    """`\\r\\n` 与 BOM：区间外字节原样，末块 `\\r\\n` 尾保留。"""
    text = "\ufeff第5章 风起\r\n\r\n第一段。\r\n\r\n第二段。\r\n\r\n---\r\n\r\n第三段。\r\n"
    blocks = split_paragraphs(text)
    new = apply_replacements(text, blocks, [(2, 2)], ["改后第二段。"])
    assert new == "\ufeff第5章 风起\r\n\r\n第一段。\r\n\r\n改后第二段。\r\n\r\n---\r\n\r\n第三段。\r\n"


def test_apply_empty_spans_identity():
    """spans 为空：恒等回填（返回原文）。"""
    text = "第5章 风起\n\n第一段。\n"
    blocks = split_paragraphs(text)
    assert apply_replacements(text, blocks, [], []) == text


def test_apply_range_with_internal_blank_structure_replaced():
    """区间内部空行结构一并替换（块一的尾部空行不残留，末块（块二）尾部保留）。"""
    text = "一\n\n\n\n二\n\n三\n"
    blocks = split_paragraphs(text)
    new = apply_replacements(text, blocks, [(1, 2)], ["合并段。"])
    # 块一尾部 3 个空行被替换掉；末块（块二）行尾 + 1 空行保留
    assert new == "合并段。\n\n三\n"


# ---------- preview：段落列表单行 ----------
def test_preview_para_line():
    """para 行格式：编号: 预览（字数）。"""
    blocks = split_paragraphs("第5章 风起\n\n第一段。\n\n第二段较长。\n")
    assert preview_line(blocks[1]) == "1: 第一段。（4字）"
    assert preview_line(blocks[2]) == "2: 第二段较长。（6字）"


def test_preview_long_line_clipped():
    """超 40 字预览截断加省略号。"""
    long_para = "长" * 50
    blocks = split_paragraphs(f"第5章 风起\n\n{long_para}\n")
    line = preview_line(blocks[1])
    assert line.startswith("1: ")
    assert line.endswith("…（50字）")
    assert "长" * 40 in line


def test_preview_title_sep_preamble():
    """title/sep 显示类型行；preamble 返回空串。"""
    blocks = split_paragraphs("\ufeff\n\n第5章 风起\n\n---\n\n第一段。\n")
    assert preview_line(blocks[0]) == ""
    assert preview_line(blocks[1]) == "  [章节头] 第5章 风起"
    assert preview_line(blocks[2]) == "  [分隔符] ---"
    assert preview_line(blocks[3]) == "1: 第一段。（4字）"
