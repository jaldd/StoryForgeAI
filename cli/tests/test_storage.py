"""storage 模块测试：章节落盘、run 日志、工作记忆持久化。"""
from pathlib import Path

from novel_agent.memory import WorkingMemory
from novel_agent.storage import (
    _strip_leading_title,
    list_runs,
    load_run,
    load_working_memory,
    parse_chapter_file,
    parse_chapter_task,
    save_chapter,
    save_run,
    save_working_memory,
)


# ---------- parse_chapter_task ----------
def test_parse_chapter_task_arabic():
    assert parse_chapter_task("写第5章：异乡风起") == (5, "异乡风起")


def test_parse_chapter_task_plain():
    assert parse_chapter_task("第12章：风裂") == (12, "风裂")


def test_parse_chapter_task_no_match():
    num, title = parse_chapter_task("随便写点")
    assert num is None and title == "随便写点"


# ---------- parse_chapter_file（0.8 T11）----------
def test_parse_chapter_file_standard():
    """匹配 save_chapter 落盘格式（零填充章号 + '-' 分隔）。"""
    assert parse_chapter_file(Path("第05章-异乡风起.md")) == (5, "异乡风起")


def test_parse_chapter_file_variants():
    """无零填充同样匹配；run_id 冲突后缀名也拿到章号。"""
    num, _ = parse_chapter_file(Path("第5章-风裂.md"))
    assert num == 5
    num, _ = parse_chapter_file(Path("第05章-异乡风起-run_b.md"))
    assert num == 5


def test_parse_chapter_file_no_match():
    num, title = parse_chapter_file(Path("随便.md"))
    assert num is None and title == "随便"


def test_parse_chapter_file_with_directory():
    """带目录的完整路径：只看文件名。"""
    assert parse_chapter_file(Path("novel/正文/AI生成/第12章-夜行.md")) == (12, "夜行")


# ---------- _strip_leading_title ----------
def test_strip_markdown_title():
    assert _strip_leading_title("# 第五章 异乡风起\n\n正文") == "正文"


def test_strip_chinese_numeral():
    assert _strip_leading_title("第十二章 风裂\n\n正文") == "正文"


def test_strip_arabic_numeral():
    assert _strip_leading_title("第5章 异乡风起\n正文") == "正文"


def test_strip_no_title_unchanged():
    assert _strip_leading_title("正文无标题") == "正文无标题"


# ---------- save_chapter ----------
def test_save_chapter_strips_llm_header(tmp_settings):
    """LLM 自带 '# 第五章 ...' 头部时，存盘只保留我们的单标题。"""
    chap = "# 第五章 异乡风起\n\n南方的风起了。"
    p = save_chapter(chap, "写第5章：异乡风起", "run_x", tmp_settings)
    lines = p.read_text(encoding="utf-8").split("\n")
    assert lines[0] == "第5章 异乡风起"  # 我们的标题
    assert lines[1] == ""                # 空行
    assert lines[2] == "南方的风起了。"   # 正文（LLM 头部已被去掉）
    assert "# 第五章" not in p.read_text(encoding="utf-8")


def test_save_chapter_filename(tmp_settings):
    p = save_chapter("正文", "写第5章：异乡风起", "run_x", tmp_settings)
    assert p.name == "第05章-异乡风起.md"


def test_save_chapter_collision_keeps_history(tmp_settings):
    """同名已存在时不覆盖，追加 run_id 后缀。"""
    p1 = save_chapter("第一版", "写第5章：异乡风起", "run_a", tmp_settings)
    p2 = save_chapter("第二版", "写第5章：异乡风起", "run_b", tmp_settings)
    assert p1.name == "第05章-异乡风起.md"
    assert p2.name == "第05章-异乡风起-run_b.md"
    assert p1.read_text(encoding="utf-8").endswith("第一版")  # 原文件未变


def test_save_chapter_no_chapter_number(tmp_settings):
    """任务解析不出章节号时，文件名用 run_id，不加标题头。"""
    p = save_chapter("正文", "随便写点", "run_x", tmp_settings)
    assert p.name == "run_x.md"
    assert p.read_text(encoding="utf-8") == "正文"


# ---------- run 日志 ----------
def test_run_save_load_list(tmp_settings):
    rec = {"run_id": "run_20260801_120000", "task": "t", "steps": [],
           "final_state": {"final_chapter": "c"}}
    save_run(rec, tmp_settings)
    assert load_run("run_20260801_120000", tmp_settings)["task"] == "t"
    assert load_run("run_20260801_120000.json", tmp_settings)["task"] == "t"  # 带 .json
    assert "run_20260801_120000" in list_runs(tmp_settings)


# ---------- 工作记忆 ----------
def test_working_memory_roundtrip(tmp_settings):
    wm = WorkingMemory()
    wm.update_after_write(5, "风起想她", ["伏笔A"])
    save_working_memory(wm, tmp_settings)
    wm2 = load_working_memory(tmp_settings)
    assert wm2.current_chapter == 5
    assert wm2.last_plot_point == "风起想她"
    assert wm2.unresolved_foreshadowing == ["伏笔A"]


def test_working_memory_empty_when_absent(tmp_settings):
    wm = load_working_memory(tmp_settings)
    assert wm.current_chapter is None
    assert wm.unresolved_foreshadowing == []


# ---------- 2.2 区间/章纲解析（throughput W4，D6/D7/T11/T13/T16）----------
from novel_agent.storage import cn_numeral, parse_chapter_plan, parse_chapter_range  # noqa: E402


def test_parse_chapter_range_plain():
    assert parse_chapter_range("写第5-10章") == (5, 10, None)


def test_parse_chapter_range_with_title():
    assert parse_chapter_range("写第5-10章：异乡风起") == (5, 10, "异乡风起")


def test_parse_chapter_range_fullwidth_colon():
    assert parse_chapter_range("写第5-10章: 半 ascii 冒号") == (5, 10, "半 ascii 冒号")


def test_parse_chapter_range_separator_variants():
    for sep in ("-", "－", "–", "~", "～", "至"):
        assert parse_chapter_range(f"写第3{sep}7章") == (3, 7, None), sep


def test_parse_chapter_range_spaces_around_numbers():
    assert parse_chapter_range("写第 5 - 10 章：模板") == (5, 10, "模板")


def test_parse_chapter_range_no_match_single_chapter():
    """单章命令不匹配区间正则（互斥靠分发「先区间后单章」）。"""
    assert parse_chapter_range("写第5章：标题") is None
    assert parse_chapter_range("写第5章") is None
    assert parse_chapter_range("精修 /tmp/a.md") is None


_PLAN_MD = """
散文说明文字，不是表格。

| 章 | 标题 | 核心事件 | 天气 | 矛盾种子 |
| --- | --- | --- | --- | --- |
| 5 | 风起 | 主角遇袭 | 雨 | 黑衣人 |
| 6 | 云涌 | 追查线索 | 晴 | 内奸 |

## 第二卷（分卷多表格）

| 章 | 暂定标题 | 核心事件 |
| --- | --- | --- |
| 7 | 山雨 | 入山 |
| 7 | 山雨欲来 | 入山遇伏 |

| 人物 | 说明 |
| --- | --- |
| 林晚 | 女主（首列非章号，整表跳过） |

正文行 | 夹杂竖线 | 但不以 | 开头（不是表格）
"""


def test_parse_chapter_plan_merge_and_notes():
    plans = parse_chapter_plan(_PLAN_MD)
    assert set(plans) == {5, 6, 7}
    assert plans[5]["title"] == "风起"
    assert plans[5]["notes"] == [
        ("核心事件", "主角遇袭"), ("天气", "雨"), ("矛盾种子", "黑衣人"),
    ]
    # 分卷表格合并；「暂定标题」列头变体同样命中
    assert plans[7]["title"] == "山雨欲来"  # 同章号后者覆盖（Z7）
    # 首列非章号的表格（人物表）整表跳过
    assert all("林晚" not in str(p) for p in plans.values())


def test_parse_chapter_plan_dirty_rows_skipped():
    md = """| 章 | 标题 | 核心事件 |
| --- | --- | --- |
| 五 | 中文数字行跳过 | x |
| abc | 非整数跳过 | y |
| 8 |  | 空标题保留（可被命令模板覆盖） |
"""
    plans = parse_chapter_plan(md)
    assert set(plans) == {8}
    assert plans[8]["title"] == ""
    assert plans[8]["notes"] == [("核心事件", "空标题保留（可被命令模板覆盖）")]


def test_parse_chapter_plan_row_shorter_than_header():
    """行比列头短：缺的 notes 列补空串（不越界不丢行）。"""
    md = """| 章 | 标题 | 核心事件 | 天气 |
| --- | --- | --- | --- |
| 9 | 短行 | 只有事件 |
"""
    plans = parse_chapter_plan(md)
    assert plans[9]["notes"] == [("核心事件", "只有事件"), ("天气", "")]


def test_parse_chapter_plan_chapter_forms():
    """首列兼容「第5章」带章字形态（实际章纲的常见脏形态）。"""
    md = """| 章 | 标题 |
| --- | --- |
| 第12章 | 带章字 |
"""
    plans = parse_chapter_plan(md)
    assert plans == {12: {"title": "带章字", "notes": []}}


def test_parse_chapter_plan_empty():
    assert parse_chapter_plan("") == {}
    assert parse_chapter_plan("没有表格的纯散文。") == {}


def test_cn_numeral_spot_checks():
    assert cn_numeral(1) == "一"
    assert cn_numeral(2) == "二"
    assert cn_numeral(9) == "九"
    assert cn_numeral(10) == "十"
    assert cn_numeral(11) == "十一"
    assert cn_numeral(20) == "二十"
    assert cn_numeral(21) == "二十一"
    assert cn_numeral(99) == "九十九"


def test_cn_numeral_out_of_range_raises():
    import pytest
    for bad in (0, -1, 100):
        with pytest.raises(ValueError):
            cn_numeral(bad)
