"""storage 模块测试：章节落盘、run 日志、工作记忆持久化。

3.1 伏笔条目结构升级后，memory 侧用例也同居本文件（见 §伏笔条目结构）。
"""
import json
from pathlib import Path

from novel_agent.memory import WorkingMemory
from novel_agent.storage import (
    _strip_leading_title,
    extract_leading_title,
    list_runs,
    load_run,
    load_working_memory,
    parse_chapter_file,
    parse_chapter_task,
    preserve_leading_title,
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


# ---------- 卷对齐落盘（volume-align，V1-V6）----------
def _vol_settings(tmp_settings):
    """卷对齐测试配置：subdir 指到第一卷目录。"""
    import dataclasses

    return dataclasses.replace(tmp_settings, volume_align=True, chapter_subdir="正文/第一卷")


def test_parse_chapter_file_volume_format():
    """V6：卷文件名「卷名-NN.md」-> (NN, "")；既有格式优先防误判。"""
    assert parse_chapter_file(Path("第一卷-38.md")) == (38, "")
    assert parse_chapter_file(Path("正文/第一卷/第一卷-05.md")) == (5, "")
    # 判定序（D5）：既有「第N章-标题」先匹配，标题以数字结尾不被卷模式误吃
    assert parse_chapter_file(Path("第05章-标题2.md")) == (5, "标题2")
    # run_id 后缀名（下划线非连字符）不落卷模式
    num, _ = parse_chapter_file(Path("run_20260905_095613.md"))
    assert num is None


def test_save_chapter_volume_align_naming_and_header(tmp_settings):
    """V1/V2：文件名 {卷名}-{NN}.md、头行 ## 第{中文}章 标题、模型头行剥重。"""
    settings = _vol_settings(tmp_settings)
    chap = "## 第三十八章 空\n\n天灰了一整天。"
    p = save_chapter(chap, "写第38章：空", "run_x", settings)
    assert p.parent == settings.chapter_path          # 正文/第一卷/
    assert p.name == "第一卷-38.md"
    text = p.read_text(encoding="utf-8")
    assert text == "## 第三十八章 空\n\n天灰了一整天。"  # 单头行（模型头被剥后重写）


def test_save_chapter_volume_align_overwrites(tmp_settings):
    """V3：目标已存在直接覆盖（无 run_id 后缀文件产生）。"""
    settings = _vol_settings(tmp_settings)
    settings.chapter_path.mkdir(parents=True, exist_ok=True)
    old = settings.chapter_path / "第一卷-38.md"
    old.write_text("人工原稿内容", encoding="utf-8")

    p = save_chapter("AI 重写后的正文。", "写第38章：空", "run_x", settings)
    assert p == old                                    # 同文件替换
    text = old.read_text(encoding="utf-8")
    assert "AI 重写后的正文。" in text and "人工原稿内容" not in text
    assert len(list(settings.chapter_path.glob("*.md"))) == 1  # 无后缀副本


def test_save_chapter_volume_align_extras_fallback(tmp_settings):
    """V4：章号解析不出（番外）回落平铺 run_id 命名，不覆盖。"""
    settings = _vol_settings(tmp_settings)
    p = save_chapter("番外内容。", "写一段番外", "run_extra", settings)
    assert p.name == "run_extra.md"
    assert p.read_text(encoding="utf-8") == "番外内容。"


def test_save_chapter_volume_align_big_num_arabic(tmp_settings):
    """V2：章号 >99 中文数字越界，头行回落阿拉伯数字不崩。"""
    settings = _vol_settings(tmp_settings)
    p = save_chapter("正文。", "写第105章：百", "run_x", settings)
    assert p.name == "第一卷-105.md"
    assert p.read_text(encoding="utf-8").startswith("## 第105章 百\n\n")


def test_save_chapter_volume_align_off_unchanged(tmp_settings):
    """V5：开关关 = 现状平铺命名（既有用例全覆盖，此处补对照）。"""
    p = save_chapter("正文。", "写第38章：空", "run_x", tmp_settings)
    assert p.name == "第38章-空.md"


# ---------- _strip_leading_title ----------
def test_strip_markdown_title():
    assert _strip_leading_title("# 第五章 异乡风起\n\n正文") == "正文"


def test_strip_chinese_numeral():
    assert _strip_leading_title("第十二章 风裂\n\n正文") == "正文"


def test_strip_arabic_numeral():
    assert _strip_leading_title("第5章 异乡风起\n正文") == "正文"


def test_strip_no_title_unchanged():
    assert _strip_leading_title("正文无标题") == "正文无标题"


# ---------- preserve_leading_title（精修/重写存回标题保真）----------
def test_extract_leading_title_variants():
    """volume-align「## 第四章 余温」/平铺「第4章 标题」/中文数字均可提取。"""
    assert extract_leading_title("## 第四章 余温\n\n正文") == "## 第四章 余温"
    assert extract_leading_title("第4章 标题\n\n正文") == "第4章 标题"
    assert extract_leading_title("第十二章 风裂\n正文") == "第十二章 风裂"
    assert extract_leading_title("正文无标题") == ""
    assert extract_leading_title("") == ""


def test_preserve_title_polisher_dropped_title():
    """polisher 洗掉标题（真车第一卷-04 场景）-> 以原文标题补回。"""
    original = "## 第四章 余温\n\n灯关了。\n\n正文。"
    refined = "灯关了。\n\n正文改后。"
    assert preserve_leading_title(original, refined) == "## 第四章 余温\n\n灯关了。\n\n正文改后。"


def test_preserve_title_kept_unchanged():
    """polisher 回显了标题 -> 原样（不重复补）。"""
    original = "## 第四章 余温\n\n正文。"
    refined = "## 第四章 余温\n\n正文改后。"
    assert preserve_leading_title(original, refined) == refined


def test_preserve_title_variant_normalized_to_original():
    """polisher 回显变体（少 ## 前缀）-> 统一替换回原文标题格式。"""
    original = "## 第四章 余温\n\n正文。"
    refined = "第四章 余温\n\n正文改后。"
    assert preserve_leading_title(original, refined) == "## 第四章 余温\n\n正文改后。"


def test_preserve_title_no_title_in_original_untouched():
    """原文无标题 -> 不凭空添（改稿原样返回）。"""
    refined = "正文改后。"
    assert preserve_leading_title("正文。", refined) == refined


def test_preserve_title_flat_format():
    """平铺格式「第4章 标题」同款生效。"""
    original = "第4章 标题\n\n正文。"
    assert preserve_leading_title(original, "正文改后。") == "第4章 标题\n\n正文改后。"


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
    # 3.1 F6：条目从纯 str 升级为 {"desc", "chapter"}（str 输入按容错转 dict，章号取当前章）
    assert wm2.unresolved_foreshadowing == [{"desc": "伏笔A", "chapter": 5}]


def test_working_memory_empty_when_absent(tmp_settings):
    wm = load_working_memory(tmp_settings)
    assert wm.current_chapter is None
    assert wm.unresolved_foreshadowing == []


# ---------- 伏笔条目结构（3.1 foreshadow，F6/F8/F14/F15）----------
def _write_wm_json(tmp_settings, data: dict) -> None:
    path = tmp_settings.working_memory_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_legacy_str_list_compat(tmp_settings):
    """F6/F14：旧格式纯字符串列表 -> dict 条目（chapter=None）；无 resolved 键 -> 空归档。"""
    _write_wm_json(tmp_settings, {
        "current_chapter": 7,
        "character_states": {},
        "unresolved_foreshadowing": ["伏笔A", "伏笔B"],
        "last_plot_point": "摘要",
    })
    wm = load_working_memory(tmp_settings)
    assert wm.unresolved_foreshadowing == [
        {"desc": "伏笔A", "chapter": None},
        {"desc": "伏笔B", "chapter": None},
    ]
    assert wm.resolved_foreshadowing == []      # 旧文件无该键


def test_dirty_foreshadowing_entries_dropped(tmp_settings):
    """F6：脏元素丢弃（空串/非 dict/无 desc），不因一条脏数据拒载整个文件。"""
    _write_wm_json(tmp_settings, {
        "unresolved_foreshadowing": ["好伏笔", "", 42, {"desc": "有描述的", "chapter": 3}, {"章号": 5}],
        "resolved_foreshadowing": [
            {"desc": "已收的", "chapter": 3, "resolved_chapter": 9},
            "坏数据", {"没有描述": 1},
        ],
    })
    wm = load_working_memory(tmp_settings)
    assert wm.unresolved_foreshadowing == [
        {"desc": "好伏笔", "chapter": None},
        {"desc": "有描述的", "chapter": 3},
    ]
    assert wm.resolved_foreshadowing == [
        {"desc": "已收的", "chapter": 3, "resolved_chapter": 9}
    ]


def test_manual_flag_and_archive_roundtrip(tmp_settings):
    """F15/F16：manual 标记与归档字段随 working_memory.json 落盘读回。"""
    wm = WorkingMemory()
    wm.add_foreshadowing("人工补的线", chapter=5, manual=True)
    wm.resolve_foreshadowing([1], 6)
    save_working_memory(wm, tmp_settings)

    wm2 = load_working_memory(tmp_settings)
    assert wm2.unresolved_foreshadowing == []
    assert wm2.resolved_foreshadowing == [
        {"desc": "人工补的线", "chapter": 5, "resolved_chapter": 6}
    ]


def test_resolve_foreshadowing_archives_instead_of_deleting():
    """F15/D8：出列 = 移入归档（不物理删除）；越界/重复编号忽略，一次结算不错位。"""
    wm = WorkingMemory()
    wm.unresolved_foreshadowing = [{"desc": f"v{i}", "chapter": i} for i in range(1, 6)]
    moved = wm.resolve_foreshadowing([5, 2, 2, 99, "x"], 8)

    assert [m["desc"] for m in moved] == ["v2", "v5"]        # 按编号升序，越界/重复/非整数忽略
    assert all(m["resolved_chapter"] == 8 for m in moved)
    assert [e["desc"] for e in wm.unresolved_foreshadowing] == ["v1", "v3", "v4"]  # 一次结算不错位
    assert wm.resolved_foreshadowing == moved


def test_foreshadow_lines_cap_keeps_original_numbering():
    """F8：截断取尾部但保留原编号；cap=0/None = 全量；chapter=None 无章号前缀。"""
    wm = WorkingMemory()
    wm.unresolved_foreshadowing = [{"desc": f"v{i}", "chapter": i} for i in range(1, 4)]
    wm.add_foreshadowing("无章号的线")          # chapter=None

    assert wm.foreshadow_lines()[0] == "  1.（第1章埋）v1"
    assert wm.foreshadow_lines()[-1] == "  4.无章号的线"      # 无「（第N章埋）」前缀
    assert len(wm.foreshadow_lines(cap=0)) == 4               # 0 = 不截断
    assert len(wm.foreshadow_lines(cap=None)) == 4            # 命令侧全量

    lines = wm.foreshadow_lines(cap=2)
    assert lines == ["  3.（第3章埋）v3", "  4.无章号的线"]     # 尾部 2 条
    assert "3." in lines[0]                                    # 原编号，不重排


def test_snapshot_new_format_and_cap():
    """F7/F8：snapshot 渲染带指令文案 + 编号 + 埋设章；截断标注仅注入侧出现。"""
    wm = WorkingMemory()
    wm.update_after_write(5, "风起想她", [{"desc": "怀表停在十点", "chapter": 5}])
    snap = wm.snapshot()
    assert "未回收伏笔（写作时应考虑推进或回收，不强行回收）：" in snap
    assert "1.（第5章埋）怀表停在十点" in snap
    assert "仅注入最近" not in snap              # 未超限不标注

    wm.unresolved_foreshadowing = [{"desc": f"v{i}", "chapter": i} for i in range(1, 6)]
    capped = wm.snapshot(cap=2)
    assert "…（共 5 条，仅注入最近 2 条）" in capped
    assert "  4." in capped and "  1." not in capped

    empty = WorkingMemory()
    empty.current_chapter = 5
    assert "未回收伏笔：无" in empty.snapshot()


# ---------- 角色弧光条目结构（3.2 character-arc，C6/C7/C8/C15）----------
def test_character_states_roundtrip(tmp_settings):
    """C6：结构化条目（含 history）随 working_memory.json 落盘读回。"""
    wm = WorkingMemory()
    wm.update_character_states(
        [{"name": "林晚", "stage": "复仇决心初动摇", "goal": "查清真相",
          "conflict": "复仇与良知", "belief": "真相值得代价", "changed": True}],
        chapter_no=5,
    )
    save_working_memory(wm, tmp_settings)
    wm2 = load_working_memory(tmp_settings)
    assert wm2.character_states["林晚"] == {
        "stage": "复仇决心初动摇", "goal": "查清真相",
        "conflict": "复仇与良知", "belief": "真相值得代价",
        "chapter": 5, "history": [{"chapter": 5, "stage": "复仇决心初动摇"}],
    }


def test_dirty_character_states_dropped(tmp_settings):
    """C6：character_states 非 dict 置空；条目非 dict / 缺 stage 丢弃，不拒载。"""
    _write_wm_json(tmp_settings, {
        "character_states": "脏数据",
        "unresolved_foreshadowing": [],
    })
    assert load_working_memory(tmp_settings).character_states == {}

    _write_wm_json(tmp_settings, {
        "character_states": {
            "林晚": {"stage": "好的", "goal": "查清真相", "chapter": 5,
                     "history": [{"chapter": 3, "stage": "旧阶段"}, "脏", {"stage": "无章号"}]},
            "沈砚": {"goal": "缺 stage 的条目"},
            "路人": "字符串条目",
        },
        "unresolved_foreshadowing": [],
    })
    wm = load_working_memory(tmp_settings)
    assert list(wm.character_states) == ["林晚"]
    assert wm.character_states["林晚"]["history"] == [{"chapter": 3, "stage": "旧阶段"}]


def test_update_character_states_cover_new_changed():
    """C2/D2/D7：同串覆盖、异串新角色、changed 追加 history、未 changed 不追加。"""
    wm = WorkingMemory()
    wm.update_character_states(
        [{"name": "林晚", "stage": "蒙冤受屈", "goal": "活下去",
          "conflict": "", "belief": "天理昭昭", "changed": True}], chapter_no=3)
    wm.update_character_states(
        [{"name": "林晚", "stage": "复仇决心初动摇", "goal": "查清真相",
          "conflict": "复仇与良知", "belief": "真相值得代价", "changed": True},
         {"name": "沈砚", "stage": "暗中观察", "goal": "守住秘密",
          "conflict": "", "belief": "职责为先", "changed": False}], chapter_no=5)

    lin = wm.character_states["林晚"]
    assert lin["stage"] == "复仇决心初动摇" and lin["chapter"] == 5
    assert lin["history"] == [
        {"chapter": 3, "stage": "蒙冤受屈"},
        {"chapter": 5, "stage": "复仇决心初动摇"},
    ]
    shen = wm.character_states["沈砚"]                    # 新角色入库
    assert shen["history"] == []                          # 未 changed 不追加


def test_update_character_states_history_cap():
    """C6：history 护栏 20 条，超出丢最老。"""
    wm = WorkingMemory()
    for ch in range(1, 23):                               # 22 次变化
        wm.update_character_states(
            [{"name": "林晚", "stage": f"阶段{ch}", "changed": True}], chapter_no=ch)
    history = wm.character_states["林晚"]["history"]
    assert len(history) == 20
    assert history[0] == {"chapter": 3, "stage": "阶段3"}  # 最老的 1、2 被丢


def test_update_character_states_same_chapter_overwrite():
    """C15：同章重写先清该章 history 条目再落账，不产生「同一章两个阶段」。"""
    wm = WorkingMemory()
    wm.update_character_states(
        [{"name": "林晚", "stage": "阶段A", "changed": True}], chapter_no=5)
    wm.update_character_states(
        [{"name": "林晚", "stage": "阶段B", "changed": True}], chapter_no=6)
    assert [h["stage"] for h in wm.character_states["林晚"]["history"]] == ["阶段A", "阶段B"]

    wm.update_character_states(                            # 重写第 5 章
        [{"name": "林晚", "stage": "阶段A2", "changed": True}], chapter_no=5)
    lin = wm.character_states["林晚"]
    assert [h["chapter"] for h in lin["history"]] == [5, 6]  # 旧第 5 章条目被清
    assert lin["history"][0]["stage"] == "阶段A2"
    assert lin["stage"] == "阶段A2" and lin["chapter"] == 5   # 状态快照回到该章时点


def test_update_character_states_num_none_guard():
    """C15 守卫：chapter_no=None（番外）不清洗，无章号 history 条目不被抹掉。"""
    wm = WorkingMemory()
    wm.update_character_states(
        [{"name": "林晚", "stage": "番外态", "changed": True}], chapter_no=None)
    wm.update_character_states(
        [{"name": "林晚", "stage": "番外态2", "changed": True}], chapter_no=None)
    history = wm.character_states["林晚"]["history"]
    assert history == [
        {"chapter": None, "stage": "番外态"},
        {"chapter": None, "stage": "番外态2"},
    ]


def test_remove_and_revise_character():
    """C9/D9/Z4：删 = 直接移除不归档；改 = 只动 stage 与更新章，不打 manual。"""
    wm = WorkingMemory()
    wm.update_character_states(
        [{"name": "林晚", "stage": "蒙冤受屈", "goal": "活下去",
          "conflict": "", "belief": "天理昭昭", "changed": True}], chapter_no=3)

    assert wm.revise_character_stage("林晚", "复仇决心已崩溃", chapter=5)
    lin = wm.character_states["林晚"]
    assert lin["stage"] == "复仇决心已崩溃" and lin["chapter"] == 5
    assert lin["goal"] == "活下去"                          # 其余字段保留
    assert "manual" not in lin                              # D9：不打 manual

    assert wm.remove_character("林晚") is True
    assert wm.character_states == {}
    assert wm.remove_character("林晚") is False             # 再删未命中
    assert wm.revise_character_stage("林晚", "x") is False  # 改未命中


def test_arc_lines_render_and_cap():
    """C7/C8/D10：分节渲染 + 更新章倒序截断 + 空不占位 + None 无章号前缀。"""
    wm = WorkingMemory()
    wm.current_chapter = 6
    assert wm.arc_block() == ""                             # 空 -> 整块不占位

    wm.update_character_states(
        [{"name": "林晚", "stage": "复仇决心初动摇", "goal": "查清真相",
          "conflict": "", "belief": "真相值得代价", "changed": True}], chapter_no=6)
    wm.update_character_states(
        [{"name": "沈砚", "stage": "暗中观察", "goal": "守住秘密",
          "conflict": "", "belief": "职责为先", "changed": False}], chapter_no=3)
    wm.update_character_states(
        [{"name": "阿婆", "stage": "无章号条目", "changed": False}], chapter_no=None)

    block = wm.arc_block()
    assert "角色弧光（写作时保持各角色当前阶段与人设连续，不可无故突变）：" in block
    assert "林晚（第6章）：复仇决心初动摇｜目标：查清真相｜信念：真相值得代价" in block
    assert "阿婆：无章号条目" in block                       # chapter=None 无章号前缀
    assert "仅注入最近" not in block                        # 未超限不标注

    capped = wm.arc_block(arc_cap=1)
    assert "林晚（第6章）" in capped                        # 更新章倒序，最近活跃优先
    assert "沈砚" not in capped and "阿婆" not in capped
    assert "…（共 3 角色，仅注入最近更新 1 个）" in capped
    assert len(wm.arc_lines(arc_cap=0)) == 3                # 0 = 不截断
    assert len(wm.arc_lines(arc_cap=None)) == 3             # 命令侧全量


def test_snapshot_arc_and_foreshadow_coexist():
    """C7：snapshot 里弧光块与伏笔块同现；弧光空时回落「角色状态：无」。"""
    wm = WorkingMemory()
    wm.update_after_write(5, "风起想她", [{"desc": "怀表", "chapter": 5}])
    wm.update_character_states(
        [{"name": "林晚", "stage": "蒙冤受屈", "goal": "活下去",
          "conflict": "", "belief": "天理昭昭", "changed": True}], chapter_no=5)
    snap = wm.snapshot()
    assert "角色弧光（写作时保持各角色当前阶段与人设连续，不可无故突变）：" in snap
    assert "林晚（第5章）：蒙冤受屈" in snap
    assert "未回收伏笔（写作时应考虑推进或回收" in snap

    empty = WorkingMemory()
    empty.current_chapter = 5
    assert "角色状态：无" in empty.snapshot()


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
