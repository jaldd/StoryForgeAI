"""storage 模块测试：章节落盘、run 日志、工作记忆持久化。"""
from novel_agent.memory import WorkingMemory
from novel_agent.storage import (
    _strip_leading_title,
    list_runs,
    load_run,
    load_working_memory,
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
