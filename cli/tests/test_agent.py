"""agent 模块测试：状态机流程，用 fake LLM/RAG 不联网。"""
from novel_agent.agent import NovelAgent, parse_review, parse_review_full
from novel_agent.config import Settings
from novel_agent.memory import WorkingMemory
from novel_agent.state import PipelineState


# ---------- parse_review ----------
def test_parse_review_pass():
    assert parse_review('{"pass": true, "reason": "ok"}') == (True, "ok")


def test_parse_review_fail():
    assert parse_review('{"pass": false, "reason": "bad"}') == (False, "bad")


def test_parse_review_fallback_false():
    """非 JSON 且含"不通过" -> 不通过。"""
    ok, _ = parse_review("这段不通过，重写")
    assert ok is False


def test_parse_review_fallback_unparseable():
    """非 JSON 且无"不通过"字样 -> None（不可解析），不再默认通过（0.1 fail-open 修复）。"""
    ok, reason = parse_review("看不懂这段，无法判断")
    assert ok is None
    assert "不可解析" in reason


def test_parse_review_json_in_backticks():
    """reviewer 用 ```json 包裹 + 前后多余文字，仍能解析出 pass/issues。"""
    text = ('好的，审查结果如下：\n```json\n'
            '{"pass": false, "reason": "不够克制", "issues": ["称呼错了", "天气解释了"]}\n'
            '```\n以上。')
    ok, reason = parse_review(text)
    assert ok is False
    assert "不够克制" in reason
    assert "称呼错了" in reason  # issues 折进 reason


def test_parse_review_reason_with_brace():
    """reason 里含 } 不应被提前截断，取到最后一个 } 才能完整解析。"""
    text = '结论：{"pass": true, "reason": "ok，见 {附录}"}'
    ok, reason = parse_review(text)
    assert ok is True
    assert "附录" in reason


# ---------- parse_review_full（1.1 A5-A6）----------
def test_parse_review_full_new_schema():
    """新 schema 全字段：scores 八维分 + issues 结构化，reason 不折叠 issues。"""
    text = ('{"pass": false, "reason": "称呼错误", '
            '"scores": {"人物一致性": 4, "文风一致性": 2, "剧情连贯性": 5}, '
            '"issues": [{"quote": "许风走进来", "problem": "人物一致性：称呼错误", '
            '"fix": "改为林晚"}]}')
    r = parse_review_full(text)
    assert r.passed is False
    assert r.reason == "称呼错误"
    assert r.scores == {"人物一致性": 4, "文风一致性": 2, "剧情连贯性": 5}
    assert r.issues == [{"quote": "许风走进来", "problem": "人物一致性：称呼错误",
                          "fix": "改为林晚"}]


def test_parse_review_full_old_schema_string_issues_normalized():
    """旧 schema 字符串 issues 归一为三键 dict（D4 兼容）；无 scores -> 空。"""
    r = parse_review_full('{"pass": false, "reason": "不够克制", "issues": ["称呼错了", "天气解释了"]}')
    assert r.passed is False
    assert r.scores == {}
    assert r.issues == [
        {"quote": "", "problem": "称呼错了", "fix": ""},
        {"quote": "", "problem": "天气解释了", "fix": ""},
    ]


def test_parse_review_full_unparseable_returns_none():
    """不可解析 -> None（不可解析路径交 _confirm_unparseable，不动）。"""
    assert parse_review_full("看不懂这段，无法判断") is None
    assert parse_review_full("") is None


def test_parse_review_full_scores_validation():
    """scores 只收 1-5 整数：越界 / 浮点 / 字符串 / 布尔全丢弃（A6）。"""
    text = ('{"pass": true, "reason": "ok", "scores": '
            '{"人物一致性": 0, "文风一致性": 6, "剧情连贯性": 3, '
            '"环境一致性": 4.5, "伏笔一致性": true, "视角越界": "5"}}')
    r = parse_review_full(text)
    assert r.scores == {"剧情连贯性": 3}


def test_parse_review_full_json_in_backticks():
    """四级提取共享：```json 围栏 + 前后杂文字仍可解析。"""
    text = ('审查结果：\n```json\n'
            '{"pass": true, "reason": "通过", "scores": {"人物一致性": 5}, "issues": []}\n'
            '```\n以上。')
    r = parse_review_full(text)
    assert r.passed is True
    assert r.scores == {"人物一致性": 5}
    assert r.issues == []


# ---------- 完整流程（happy path）----------
def test_pipeline_happy_path(fake_llm, fake_rag, tmp_settings):
    agent = NovelAgent(
        llm=fake_llm, rag=fake_rag, exemplar="范文",
        settings=tmp_settings, working_memory=WorkingMemory(),
    )
    state, record = agent.run("写第5章：异乡风起")

    assert state.next_agent == "done"
    assert state.final_chapter  # 非空
    assert "风" in state.draft
    assert "通过" in state.feedback
    assert len(record["steps"]) == 4  # writer/polisher/checker/reviewer（1.1：checker 零 LLM 直通）
    assert record["run_id"].startswith("run_")
    assert record["config"]["model"] == "glm-5.2"


def test_pipeline_without_rag(fake_llm, tmp_settings):
    """RAG 为 None 时流程仍能跑（检索返回空）。"""
    agent = NovelAgent(
        llm=fake_llm, rag=None, exemplar="范文",
        settings=tmp_settings, working_memory=WorkingMemory(),
    )
    state, record = agent.run("写第5章：异乡风起")
    assert state.next_agent == "done" and state.final_chapter


# ---------- 打回场景 ----------
def test_pipeline_review_reject_then_pass(fake_llm, fake_rag, tmp_settings):
    """审稿先打回再通过：review_count 递增，打回进 fixer 精修问题段后复检（1.1 D9）。"""
    fake_llm.script = [
        "【初稿1】风起了。\n\n她低头。",         # writer #1
        "【润色1】风起了，林晚。\n\n她低头。",    # polisher #1
        '{"pass": false, "reason": "不够克制", "issues": '
        '[{"dimension": "文风", "problem": "太直白", "quote": "她低头", "suggestion": "更含蓄"}]}',  # reviewer #1 -> 打回 fixer
        "【第2段·修复后】她沉默地低下头。",       # fixer #1（writer_llm 回落 llm）
        '{"pass": true, "reason": "通过"}',      # reviewer #2 -> 通过
    ]
    agent = NovelAgent(
        llm=fake_llm, rag=fake_rag, exemplar="范文",
        settings=tmp_settings, working_memory=WorkingMemory(),
    )
    state, record = agent.run("写第5章：异乡风起")

    assert state.review_count == 1
    assert state.next_agent == "done"
    assert state.final_chapter == "【润色1】风起了，林晚。\n\n她沉默地低下头。"
    # A8：writer 仅一次，打回不重写全章，由 fixer 只修问题段
    assert len([c for c in fake_llm.calls if "写一段新章节" in c]) == 1
    agents_seq = [s["agent"] for s in record["steps"]]
    assert agents_seq == ["writer", "polisher", "checker", "reviewer", "fixer", "checker", "reviewer"]
    assert len(fake_llm.calls) == 5  # checker 两过均零 LLM


def test_pipeline_checker_reject_then_pass(fake_llm, fake_rag, tmp_settings):
    """1.1 规则门禁全链路：checker 命中 -> fixer 修复 -> checker 复检 -> reviewer。"""
    fake_llm.script = [
        "【初稿】她低头。",                # writer
        "【润色】她低头。",                # polisher（含黑名单词）
        "【第1段·修复后】她垂下目光。",      # fixer
        '{"pass": true, "reason": "通过"}',  # reviewer
    ]
    agent = NovelAgent(
        llm=fake_llm, rag=fake_rag, exemplar="范文",
        settings=tmp_settings, working_memory=WorkingMemory(),
        quality_rules={"blacklist": ["她低头"]},
    )
    state, record = agent.run("写第5章：异乡风起")

    assert state.review_count == 1          # checker 打回复用 review 预算（A14）
    assert state.final_chapter == "她垂下目光。"
    assert state.issues == []               # Z5：修复后清空，无陈旧意见
    agents_seq = [s["agent"] for s in record["steps"]]
    assert agents_seq == ["writer", "polisher", "checker", "fixer", "checker", "reviewer"]
    assert len(fake_llm.calls) == 4          # checker 两过均零 LLM
    assert record["config"]["quality_rules"] is True   # Z6：本 run 带规则
    fs = record["final_state"]
    assert "scores" in fs and "issues" in fs  # 富解析字段随 asdict 落 record（A4/A24）


def test_pipeline_max_reviews_cap(fake_llm, fake_rag, tmp_settings):
    """达到打回上限强制定稿，防死循环（打回进 fixer，第二次 reviewer 直接收口）。"""
    fake_llm.script = [
        "【初稿1】风起了。\n\n她低头。",         # writer #1
        "【润色1】风起了，林晚。\n\n她低头。",    # polisher #1
        '{"pass": false, "reason": "不好", "issues": '
        '[{"dimension": "文风", "problem": "太直白", "quote": "她低头", "suggestion": "更含蓄"}]}',  # reviewer #1 -> 打回 (review_count=1)
        "【第2段·修复后】她沉默地低下头。",       # fixer #1
        # reviewer #2 不再调 LLM：review_count(1) >= max_reviews(1) -> 强制定稿
    ]
    agent = NovelAgent(
        llm=fake_llm, rag=fake_rag, exemplar="范文",
        settings=tmp_settings, working_memory=WorkingMemory(), max_reviews=1,
    )
    state, _ = agent.run("写第5章：异乡风起")
    assert state.review_count == 1
    assert state.next_agent == "done"
    assert state.final_chapter == "【润色1】风起了，林晚。\n\n她沉默地低下头。"
    assert len(fake_llm.calls) == 4  # 第 2 次 reviewer 未调 LLM（逃生门收口）


def test_pipeline_max_reviews_forced_finalize_warns(fake_llm, fake_rag, tmp_settings, capsys):
    """0.1：强制定稿逃生门必须控制台显著警告 + run 日志留痕。"""
    fake_llm.script = [
        "【初稿1】风起了。\n\n她低头。",
        "【润色1】风起了，林晚。\n\n她低头。",
        '{"pass": false, "reason": "不好", "issues": '
        '[{"dimension": "文风", "problem": "太直白", "quote": "她低头", "suggestion": "更含蓄"}]}',
        "【第2段·修复后】她沉默地低下头。",
    ]
    agent = NovelAgent(
        llm=fake_llm, rag=fake_rag, exemplar="范文",
        settings=tmp_settings, working_memory=WorkingMemory(), max_reviews=1,
    )
    state, _ = agent.run("写第5章：异乡风起")
    out = capsys.readouterr().out
    assert "⚠️" in out and "强制定稿" in out
    assert any("强制定稿" in line for line in state.log)


# ---------- 审稿解析失败不静默放行（0.1）----------
def _unparseable_script():
    """writer/polisher 正常 + reviewer 返回散文（不可解析）。"""
    return [
        "【初稿】风起了。",
        "【润色】风起了。",
        "这段写得还行吧，情绪是有的，但我说不清楚。",  # 非 JSON 审稿
    ]


def test_review_unparseable_asks_human_confirm(fake_llm, fake_rag, tmp_settings, capsys):
    """审稿返回散文：稿件不静默过审，人工确认被询问；答 y -> 定稿且留痕。"""
    fake_llm.script = _unparseable_script()
    prompts = []

    def confirm(prompt):
        prompts.append(prompt)
        return "y"

    agent = NovelAgent(
        llm=fake_llm, rag=fake_rag, exemplar="范文",
        settings=tmp_settings, working_memory=WorkingMemory(),
        review_confirm=confirm,
    )
    state, _ = agent.run("写第5章：异乡风起")

    assert len(prompts) == 1          # 人工确认被询问（恰好一次，不打回循环）
    assert "存" in prompts[0] and "弃" in prompts[0]
    assert state.final_chapter       # y -> 定稿
    assert "人工确认存稿" in state.feedback
    assert any("人工确认：存" in line for line in state.log)
    out = capsys.readouterr().out
    assert "不可解析" in out          # 显著警告
    assert "说不清楚" in out          # 原始返回可见（前200字）


def test_review_unparseable_discard_no_chapter(fake_llm, fake_rag, tmp_settings, capsys):
    """答 n -> 弃：不定稿、流程结束（fail-closed），留痕。"""
    fake_llm.script = _unparseable_script()
    agent = NovelAgent(
        llm=fake_llm, rag=fake_rag, exemplar="范文",
        settings=tmp_settings, working_memory=WorkingMemory(),
        review_confirm=lambda prompt: "n",
    )
    state, _ = agent.run("写第5章：异乡风起")

    assert state.next_agent == "done"
    assert not state.final_chapter   # 未定稿 -> cli 不保存章节
    assert "人工确认弃稿" in state.feedback
    assert any("人工确认：弃" in line for line in state.log)
    assert state.review_count == 0   # 不可解析不构成打回


def test_review_unparseable_default_repl_input(fake_llm, fake_rag, tmp_settings, monkeypatch):
    """未注入 confirm 时走 REPL input；EOFError 视为弃（保守 fail-closed）。"""
    fake_llm.script = _unparseable_script()
    agent = NovelAgent(
        llm=fake_llm, rag=fake_rag, exemplar="范文",
        settings=tmp_settings, working_memory=WorkingMemory(),
    )

    def eof_input(prompt=""):
        raise EOFError

    monkeypatch.setattr("builtins.input", eof_input)
    state, _ = agent.run("写第5章：异乡风起")
    assert not state.final_chapter
    assert "人工确认弃稿" in state.feedback


def test_review_unparseable_refine_fail_closed(fake_llm, fake_rag, tmp_settings):
    """精修模式下同样 fail-closed：弃 -> final_chapter 为空（cli 不覆盖存回）。"""
    fake_llm.script = [
        "【润色】润色稿。",
        "散文审稿，看不懂。",  # reviewer 不可解析
    ]
    agent = NovelAgent(
        llm=fake_llm, rag=fake_rag, exemplar="范文",
        settings=tmp_settings, working_memory=WorkingMemory(),
        review_confirm=lambda prompt: "n",
    )
    state, _ = agent.refine("初稿", "精修：x.md")
    assert state.next_agent == "done"
    assert not state.final_chapter
    assert "人工确认弃稿" in state.feedback


# ---------- 工作记忆门控 ----------
def test_working_context_gating(fake_llm, fake_rag, tmp_settings):
    wm = WorkingMemory()
    agent = NovelAgent(
        llm=fake_llm, rag=fake_rag, exemplar="范文",
        settings=tmp_settings, working_memory=wm,
    )
    # 空：不注入工作记忆
    assert agent._working_context() == ""
    # 写过一章后：注入
    wm.update_after_write(5, "风起想她", ["伏笔A"])
    ctx = agent._working_context()
    assert "第5章" in ctx and "伏笔A" in ctx


# ---------- 精修（refine）----------
def test_refine_skips_writer(fake_llm, fake_rag, tmp_settings):
    """精修：跳过 writer，polisher->checker->reviewer，初稿=传入内容。"""
    agent = NovelAgent(
        llm=fake_llm, rag=fake_rag, exemplar="范文",
        settings=tmp_settings, working_memory=WorkingMemory(),
    )
    state, record = agent.refine("这是要精修的初稿。", "精修：第5章")
    assert state.next_agent == "done"
    assert state.final_chapter  # 非空
    assert state.draft == "这是要精修的初稿。"  # 初稿保留
    assert len(record["steps"]) == 3  # polisher + checker + reviewer（checker 无规则直通）
    assert record["run_id"].startswith("refine_")
    assert all("写一段新章节" not in c for c in fake_llm.calls)  # 未走 writer


def test_refine_reject_goes_to_fixer(fake_llm, fake_rag, tmp_settings):
    """精修模式下 reviewer 打回 -> 进 fixer 修复，不回 writer/polisher（1.1 D9）。"""
    fake_llm.script = [
        "【润色1】她低头。",                       # polisher #1
        '{"pass": false, "reason": "不够克制", "issues": '
        '[{"dimension": "文风", "problem": "太直白", "quote": "她低头", "suggestion": "更含蓄"}]}',  # reviewer #1 -> 打回 fixer
        "【第1段·修复后】她沉默地低下头。",          # fixer #1
        '{"pass": true, "reason": "通过"}',        # reviewer #2 -> 通过
    ]
    agent = NovelAgent(
        llm=fake_llm, rag=fake_rag, exemplar="范文",
        settings=tmp_settings, working_memory=WorkingMemory(),
    )
    state, record = agent.refine("她低头。", "精修：x")
    assert state.review_count == 1
    assert state.next_agent == "done"
    assert state.final_chapter == "她沉默地低下头。"
    agents_seq = [s["agent"] for s in record["steps"]]
    assert agents_seq == ["polisher", "checker", "reviewer", "fixer", "checker", "reviewer"]
    assert len(fake_llm.calls) == 4  # checker 两过均零 LLM
    assert all("写一段新章节" not in c for c in fake_llm.calls)
    assert "请润色" in fake_llm.calls[0]        # 第 1 次调用是 polisher
    assert "待修段落" in fake_llm.calls[2]      # 第 3 次调用是 fixer（打回不回 polisher 重润）


def test_writer_strips_construction_notes(fake_llm, fake_rag, tmp_settings):
    """writer 输出'构思 === 正文'时：draft 只留正文；构思存入 state.outline（0.8 保留传递）。"""
    fake_llm.script = [
        "构思：风起，他站在路口，林晚没回头。\n===\n风起了。他没说话。林晚没回头。",  # writer
        "【润色】风起了。",  # polisher
        '{"pass": true, "reason": "通过"}',  # reviewer
    ]
    agent = NovelAgent(
        llm=fake_llm, rag=fake_rag, exemplar="范文",
        settings=tmp_settings, working_memory=WorkingMemory(),
    )
    state, record = agent.run("写第5章：异乡风起")
    assert "构思" not in state.draft
    assert "===" not in state.draft
    assert "风起了。他没说话。" in state.draft
    # 0.8 A4/A6：构思不再丢弃，存入 outline 并进 run record
    assert state.outline == "构思：风起，他站在路口，林晚没回头。"
    assert record["final_state"]["outline"] == state.outline
    writer_step = next(s for s in record["steps"] if s["agent"] == "writer")
    assert writer_step["output_state"]["outline"] == state.outline


# ---------- 写作指令全文注入 ----------
def test_instruction_in_prompts():
    """instruction 非空时三 prompt 都注入【写作指令】块；空则不出现。"""
    from novel_agent.prompts import writer_system, polisher_system, reviewer_system
    inst = "这是写作指令全文。"
    assert "【写作指令】（必须遵守）" in writer_system("书", "设定", "范文", inst)
    assert "这是写作指令全文。" in writer_system("书", "设定", "范文", inst)
    assert "【写作指令】（必须遵守）" in polisher_system("书", "设定", inst)
    assert "【写作指令】（必须遵守）" in reviewer_system("书", "设定", inst)
    # 空 instruction 不注入
    assert "【写作指令】" not in writer_system("书", "设定", "范文", "")
    assert "【写作指令】" not in polisher_system("书", "设定", "")


# ---------- 写作铁律全文注入（0.2 外置到 NOVEL_DIR）----------
def test_rules_in_prompts():
    """rules 非空时三 prompt 都注入【写作铁律】块且逐字保留；空则不出现占位块。"""
    from novel_agent.prompts import writer_system, polisher_system, reviewer_system
    rules = "铁律一：短句为主。\n铁律二：不解释因果。"
    assert "【写作铁律】（绝对不能违反）" in writer_system("书", "设定", "范文", "", rules)
    assert "铁律一：短句为主。" in writer_system("书", "设定", "范文", "", rules)
    assert "【写作铁律】（绝对不能违反）" in polisher_system("书", "设定", "", rules=rules)
    assert "铁律二：不解释因果。" in polisher_system("书", "设定", "", rules=rules)
    assert "【写作铁律】（绝对不能违反）" in reviewer_system("书", "设定", "", rules)
    assert "铁律一：短句为主。" in reviewer_system("书", "设定", "", rules)
    # 空 rules 不注入（铁律缺失时不出现占位块）
    assert "【写作铁律】" not in writer_system("书", "设定", "范文")
    assert "【写作铁律】" not in polisher_system("书", "设定")
    assert "【写作铁律】" not in reviewer_system("书", "设定")


def test_agent_rules_reach_llm_system(fake_rag, tmp_settings):
    """NovelAgent(rules=...) 时铁律逐字进入 writer/polisher/reviewer 的 system prompt。"""
    systems = []

    class SpyLLM:
        """记录 system 的假 LLM：按 script 顺序返回，不联网。"""

        def __init__(self, script):
            self.script = list(script)

        def chat(self, system, user, **kw):
            systems.append(system)
            return self.script.pop(0) if self.script else '{"pass": true, "reason": "通过"}'

    llm = SpyLLM([
        "【初稿】风起了。",            # writer
        "【润色】风起了。",            # polisher
        '{"pass": true, "reason": "通过"}',  # reviewer
    ])
    agent = NovelAgent(
        llm=llm, rag=fake_rag, exemplar="范文", rules="铁律甲：只用短句。",
        settings=tmp_settings, working_memory=WorkingMemory(),
    )
    agent.run("写第5章：异乡风起")
    assert len(systems) == 3  # writer / polisher / reviewer
    assert all("铁律甲：只用短句。" in s for s in systems)


# ---------- polisher 清洗混入的标题/说明 ----------
def test_strip_polisher_meta():
    """截掉 polisher 混入的标题/说明，只留正文。"""
    from novel_agent.agent import _strip_polisher_meta
    # 有"## 润色说明"：截掉说明，去开头"## 润色后正文"标题（保留章节标题）
    text = "## 润色后正文\n\n## 第一章 相亲\n\n傍晚六点。\n\n## 润色说明\n\n改了开头。"
    assert _strip_polisher_meta(text) == "## 第一章 相亲\n\n傍晚六点。"
    # "---" 是场景分隔符，不触发截断（按它截会吃掉正文中段）
    assert _strip_polisher_meta("正文第一段。\n\n---\n\n这是说明。") == "正文第一段。\n\n---\n\n这是说明。"
    # 干净正文：原样返回
    assert _strip_polisher_meta("风起了。他没说话。") == "风起了。他没说话。"


# ---------- 局部精修 prompt（partial_prompt）----------
def test_partial_prompt_suffix_keeps_polisher_rules():
    """suffix 拼接在 polisher_system 之后，polisher 全部铁律文本完整保留。"""
    from novel_agent.prompts import PARTIAL_REFINE_SUFFIX, polisher_system
    system = polisher_system("书", "设定", "") + PARTIAL_REFINE_SUFFIX
    # polisher 铁律原文逐条仍在（拼接不改写、不清空）
    assert "只优化文字表达，严禁改动人物称呼" in system
    assert "严禁改动剧情、伏笔" in system
    assert "初稿里守住的设定，润色后必须原样保留" in system
    assert "只返回润色后的正文，不要加任何标题、说明、注释" in system


def test_partial_prompt_suffix_points():
    """suffix 自身覆盖四个要点：只润色片段/情节不动只改表达/只返回片段本身/勿改写返回上下文。"""
    from novel_agent.prompts import PARTIAL_REFINE_SUFFIX
    assert "只润色" in PARTIAL_REFINE_SUFFIX
    assert "情节不动" in PARTIAL_REFINE_SUFFIX
    assert "只改文字表达" in PARTIAL_REFINE_SUFFIX
    assert "只返回改写后的片段本身" in PARTIAL_REFINE_SUFFIX
    assert "不要用代码围栏" in PARTIAL_REFINE_SUFFIX
    assert "不要改写它们" in PARTIAL_REFINE_SUFFIX
    assert "也不要把它们包含在返回结果里" in PARTIAL_REFINE_SUFFIX


def test_partial_prompt_user_three_sections():
    """user 函数输出含三个标记段及各自内容。"""
    from novel_agent.prompts import partial_refine_user
    user = partial_refine_user("上文内容。", "选区内容。", "下文内容。")
    assert "【上文（勿改写，勿返回）】" in user
    assert "【待润色片段（只返回这段的改写结果）】" in user
    assert "【下文（勿改写，勿返回）】" in user
    assert "上文内容。" in user
    assert "选区内容。" in user
    assert "下文内容。" in user
    # 顺序：上文 -> 片段 -> 下文
    assert user.index("【上文") < user.index("【待润色片段") < user.index("【下文")


def test_partial_prompt_user_empty_context():
    """before/after 为空串时对应占位不出现，片段段始终在。"""
    from novel_agent.prompts import partial_refine_user
    user = partial_refine_user("", "选区内容。", "")
    assert "【待润色片段（只返回这段的改写结果）】" in user
    assert "选区内容。" in user
    assert "【上文" not in user
    assert "【下文" not in user
    # 仅前缺
    user2 = partial_refine_user("", "选区内容。", "下文内容。")
    assert "【上文" not in user2
    assert "【下文（勿改写，勿返回）】" in user2
    # 仅后缺
    user3 = partial_refine_user("上文内容。", "选区内容。", "")
    assert "【上文（勿改写，勿返回）】" in user3
    assert "【下文" not in user3


# ---------- 局部精修（partial_refine）----------
def _partial_blocks(text=None):
    """构造局部精修测试用的段落块（标题 + 多段正文）。"""
    from novel_agent.partial import split_paragraphs
    if text is None:
        text = (
            "## 第一章 相遇\n\n"
            "第一段风起。\n\n"
            "第二段路口。\n\n"
            "第三段林晚没回头。\n\n"
            "第四段他没说话。\n"
        )
    return split_paragraphs(text)


def test_partial_refine_prompt_content(fake_llm, fake_rag, tmp_settings):
    """user 含选区+上下文、不含选区外正文；三段式标记齐全。"""
    agent = NovelAgent(
        llm=fake_llm, rag=fake_rag, exemplar="范文",
        settings=tmp_settings, working_memory=WorkingMemory(),
    )
    blocks = _partial_blocks()
    fake_llm.script = ["改写后的第三段。"]
    results = agent.partial_refine(blocks, [(3, 3)], "局部精修：第03章.md")

    assert results == ["改写后的第三段。"]
    user = fake_llm.calls[0]
    assert "第三段林晚没回头。" in user   # 选区本体
    assert "第二段路口。" in user        # 上下文 before（物理前块）
    assert "第四段他没说话。" in user     # 上下文 after（物理后块）
    assert "第一段风起。" not in user    # 选区外更远段落不进 prompt
    assert "【待润色片段（只返回这段的改写结果）】" in user


def test_partial_refine_multi_span_two_calls(fake_llm, fake_rag, tmp_settings):
    """3,7 两个区间恰好 2 次调用，结果顺序与区间对应。"""
    agent = NovelAgent(
        llm=fake_llm, rag=fake_rag, exemplar="范文",
        settings=tmp_settings, working_memory=WorkingMemory(),
    )
    text = "\n\n".join(f"第{i}段内容。" for i in range(1, 8)) + "\n"
    blocks = _partial_blocks(text)
    fake_llm.script = ["改A", "改B"]
    results = agent.partial_refine(blocks, [(3, 3), (7, 7)], "局部精修：x.md")

    assert results == ["改A", "改B"]
    assert len(fake_llm.calls) == 2
    # 各区间的 user 只含自己的选区与相邻上下文
    assert "第3段内容。" in fake_llm.calls[0]
    assert "第7段内容。" in fake_llm.calls[1]
    assert "第5段内容。" not in fake_llm.calls[0]  # 选区外非上下文不出现


def test_partial_refine_cleans_fence_and_meta(fake_llm, fake_rag, tmp_settings):
    """围栏 + 润色说明被清洗，只留改写正文。"""
    agent = NovelAgent(
        llm=fake_llm, rag=fake_rag, exemplar="范文",
        settings=tmp_settings, working_memory=WorkingMemory(),
    )
    blocks = _partial_blocks()
    fake_llm.script = ["```markdown\n改写正文。\n```\n\n## 润色说明\n只改了措辞"]
    results = agent.partial_refine(blocks, [(2, 2)], "局部精修：x.md")
    assert results == ["改写正文。"]


def test_partial_refine_empty_reply_is_none(fake_llm, fake_rag, tmp_settings):
    """空回/纯空白返回 None 失败标记（该项记为失败）。"""
    agent = NovelAgent(
        llm=fake_llm, rag=fake_rag, exemplar="范文",
        settings=tmp_settings, working_memory=WorkingMemory(),
    )
    blocks = _partial_blocks()
    fake_llm.script = ["", "   "]
    results = agent.partial_refine(blocks, [(2, 2), (3, 3)], "局部精修：x.md")
    assert results == [None, None]


# ---------- 0.8 流水线数据流补漏 ----------
class _SysRecorder:
    """记录 system/user/kwargs 的假 LLM（SpyLLM 模式，断言 system 注入用）。"""

    def __init__(self, script=None):
        self.script = list(script or [])
        self.systems = []
        self.users = []
        self.kws = []

    def chat(self, system, user, **kw):
        self.systems.append(system)
        self.users.append(user)
        self.kws.append(kw)
        return self.script.pop(0) if self.script else '{"pass": true, "reason": "通过"}'


def test_split_writer_output_four_cases():
    """T3/A5：构思与正文按首个 === 切分。"""
    from novel_agent.agent import _split_writer_output
    # 含 ===：前后各自 strip
    assert _split_writer_output("构思甲。\n===\n正文乙。") == ("构思甲。", "正文乙。")
    # 不含：构思为空、正文为全文
    assert _split_writer_output("只有正文。") == ("", "只有正文。")
    # 空串
    assert _split_writer_output("") == ("", "")
    # 正文内再出现 ===：只按首个切，其余归正文
    outline, body = _split_writer_output("构思。\n===\n正文。\n===\n补充")
    assert outline == "构思。"
    assert body == "正文。\n===\n补充"


def test_polisher_consumes_outline(fake_llm, fake_rag, tmp_settings):
    """T4/A7：writer 构思进入 polisher 的 user 消息（润色不跑偏意图）。"""
    fake_llm.script = [
        "构思：风起，他站在路口。\n===\n风起了。",
        "【润色】风起了。",
        '{"pass": true, "reason": "通过"}',
    ]
    agent = NovelAgent(
        llm=fake_llm, rag=fake_rag, settings=tmp_settings,
        working_memory=WorkingMemory(),
    )
    agent.run("写第5章：异乡风起")
    assert "构思：风起，他站在路口。" in fake_llm.calls[1]  # calls[1] = polisher
    assert "writer 构思" in fake_llm.calls[1]


def test_reviewer_consumes_outline(fake_llm, fake_rag, tmp_settings):
    """T5/A8：writer 构思作为验收基准进入 reviewer 的 user 消息。"""
    fake_llm.script = [
        "构思：风起，他站在路口。\n===\n风起了。",
        "【润色】风起了。",
        '{"pass": true, "reason": "通过"}',
    ]
    agent = NovelAgent(
        llm=fake_llm, rag=fake_rag, settings=tmp_settings,
        working_memory=WorkingMemory(),
    )
    agent.run("写第5章：异乡风起")
    assert "构思：风起，他站在路口。" in fake_llm.calls[2]  # calls[2] = reviewer
    assert "验收基准" in fake_llm.calls[2]


def test_refine_no_empty_outline_hint(fake_llm, fake_rag, tmp_settings):
    """T4/A7 反例：outline 为空（refine 场景）不注入空构思块。"""
    agent = NovelAgent(
        llm=fake_llm, rag=fake_rag, settings=tmp_settings,
        working_memory=WorkingMemory(),
    )
    agent.refine("要精修的初稿。", "精修：x.md")
    assert all("构思" not in c for c in fake_llm.calls)


def test_working_context_reaches_polisher_reviewer(fake_rag, tmp_settings):
    """T5/D8/A9：工作记忆快照注入 writer/polisher/reviewer 三处 system。"""
    wm = WorkingMemory()
    wm.update_after_write(5, "风起想她", ["伏笔A"])
    llm = _SysRecorder(["【初稿】风起了。", "【润色】风起了。",
                        '{"pass": true, "reason": "通过"}'])
    agent = NovelAgent(llm=llm, rag=fake_rag, settings=tmp_settings, working_memory=wm)
    agent.run("写第6章：夜行")
    assert len(llm.systems) == 3
    assert all("当前写作状态" in s for s in llm.systems)
    assert all("伏笔A" in s for s in llm.systems)
    assert all("第5章" in s for s in llm.systems)


def test_empty_working_memory_not_injected(fake_rag, tmp_settings):
    """T5/A10：current_chapter=None 时不注入空快照噪音。"""
    llm = _SysRecorder(["【初稿】风起了。", "【润色】风起了。",
                        '{"pass": true, "reason": "通过"}'])
    agent = NovelAgent(
        llm=llm, rag=fake_rag, settings=tmp_settings, working_memory=WorkingMemory(),
    )
    agent.run("写第5章：异乡风起")
    assert all("当前写作状态" not in s for s in llm.systems)


def test_working_memory_none_still_runs(fake_llm, fake_rag, tmp_settings):
    """T5/A11：working_memory=None 时流程照常（既有保护不回退）。"""
    agent = NovelAgent(
        llm=fake_llm, rag=fake_rag, settings=tmp_settings, working_memory=None,
    )
    state, _ = agent.run("写第5章：异乡风起")
    assert state.next_agent == "done" and state.final_chapter


def test_target_words_in_writer_prompts(fake_llm, fake_rag, tmp_settings):
    """T6/A12/A15：run 与 rewrite 两分支 user 都用 target_words 口径；进 record config。"""
    agent = NovelAgent(
        llm=fake_llm, rag=fake_rag, settings=tmp_settings,
        working_memory=WorkingMemory(),
    )
    _, record = agent.run("写第5章：异乡风起")
    assert "目标约1500字" in fake_llm.calls[0]
    assert "约200字" not in fake_llm.calls[0]
    assert record["config"]["target_words"] == 1500  # A15

    fake_llm.calls.clear()
    agent.rewrite("旧正文。", "重写：第5章")
    assert "目标约1500字" in fake_llm.calls[0]
    assert "参考以下已有内容" in fake_llm.calls[0]  # rewrite 分支


def test_target_words_constructor_override(fake_llm, fake_rag, tmp_settings):
    """T6：构造参数 target_words 覆盖 settings 默认。"""
    agent = NovelAgent(
        llm=fake_llm, rag=fake_rag, settings=tmp_settings,
        working_memory=WorkingMemory(), target_words=800,
    )
    _, record = agent.run("写第5章：异乡风起")
    assert "目标约800字" in fake_llm.calls[0]
    assert record["config"]["target_words"] == 800


def test_target_words_in_polisher_system():
    """T7：polisher_system 直测 target_words 传参与默认值。"""
    from novel_agent.prompts import polisher_system
    assert "约1800字" in polisher_system("书", "", target_words=1800)
    assert "约1500字" in polisher_system("书", "")


def test_summarize_chapter_dedicated_call(tmp_settings):
    """T8/A16：摘要走 PLOT_SUMMARY_SYSTEM + max_tokens=1024。"""
    from novel_agent.prompts import PLOT_SUMMARY_SYSTEM
    llm = _SysRecorder(["风起，他离开小镇。"])
    agent = NovelAgent(llm=llm, settings=tmp_settings)
    assert agent.summarize_chapter("章节正文。") == "风起，他离开小镇。"
    assert llm.systems == [PLOT_SUMMARY_SYSTEM]
    assert llm.users == ["章节正文。"]
    assert llm.kws[0]["max_tokens"] == 1024
    assert llm.kws[0]["temperature"] == 0.3


def test_is_better_four_replies(fake_llm, tmp_settings):
    """T12/A16：JSON true / JSON false / 散文含 true / 空回 四态。"""
    agent = NovelAgent(llm=fake_llm, settings=tmp_settings)
    fake_llm.script = ['{"better": true}']
    assert agent.is_better("原文", "润色") is True
    fake_llm.script = ['{"better": false}']
    assert agent.is_better("原文", "润色") is False
    fake_llm.script = ["第二段整体更好，true"]  # 非 JSON 兜底：含 true 即 True
    assert agent.is_better("原文", "润色") is True
    fake_llm.script = [""]  # 空回
    assert agent.is_better("原文", "润色") is False


# ---------- 0.7 模型来源可换：writer_llm 注入与路由 ----------
def test_writer_llm_routing_generation_vs_review(fake_llm, fake_rag, tmp_settings):
    """A6-A8：生成类（writer/polisher）走 writer_llm，审稿类走 llm。"""
    writer_llm = _SysRecorder(["【初稿】风起了。", "【润色】风起了，林晚没说话。"])
    agent = NovelAgent(
        llm=fake_llm, rag=fake_rag, settings=tmp_settings,
        working_memory=WorkingMemory(), writer_llm=writer_llm,
    )
    state, _ = agent.run("写第5章：异乡风起")

    assert state.next_agent == "done" and state.final_chapter
    assert len(writer_llm.users) == 2        # writer + polisher 都在 writer_llm
    assert len(fake_llm.calls) == 1          # 仅 reviewer 在 llm
    assert "写一段新章节" in writer_llm.users[0]
    assert "请润色" in writer_llm.users[1]
    assert "请审查" in fake_llm.calls[0]
    assert state.final_chapter == "【润色】风起了，林晚没说话。"  # 定稿来自写作侧输出


def test_writer_llm_none_falls_back_to_llm(fake_llm, fake_rag, tmp_settings):
    """A9：writer_llm=None 时全部走 llm（存量构造零改动，回归保险）。"""
    agent = NovelAgent(
        llm=fake_llm, rag=fake_rag, settings=tmp_settings,
        working_memory=WorkingMemory(),
    )
    assert agent.writer_llm is fake_llm
    state, _ = agent.run("写第5章：异乡风起")
    assert state.next_agent == "done"
    assert len(fake_llm.calls) == 3           # 三调用全在同一个 llm


def test_partial_refine_routes_to_writer_llm(fake_llm, fake_rag, tmp_settings):
    """A6：局部精修也走 writer_llm。"""
    writer_llm = _SysRecorder(["改写后的第三段。"])
    agent = NovelAgent(
        llm=fake_llm, rag=fake_rag, settings=tmp_settings,
        working_memory=WorkingMemory(), writer_llm=writer_llm,
    )
    blocks = _partial_blocks()
    results = agent.partial_refine(blocks, [(3, 3)], "局部精修：第03章.md")

    assert results == ["改写后的第三段。"]
    assert len(writer_llm.users) == 1
    assert len(fake_llm.calls) == 0           # 审稿侧未被触碰


# ---------- 0.7 run 记录 config 新键（D3-a 扁平键）----------
def test_record_config_new_keys_unconfigured(fake_llm, fake_rag, tmp_settings):
    """A16：未配 WRITER_* 时 writer_model == model，llm_temperature 为 None。"""
    agent = NovelAgent(
        llm=fake_llm, rag=fake_rag, settings=tmp_settings,
        working_memory=WorkingMemory(),
    )
    _, record = agent.run("写第5章：异乡风起")
    cfg = record["config"]
    assert cfg["model"] == "glm-5.2"          # 既有断言口径保持
    assert cfg["writer_model"] == "glm-5.2"   # 未配回落同值
    assert cfg["llm_temperature"] is None     # 未配为 None（Z3）
    assert cfg["temperature"] == 0.9          # 既有键不动（run 级遗留语义）
    assert cfg["max_rounds"] == 10 and cfg["max_reviews"] == 6
    assert cfg["target_words"] == 1500


def test_record_config_new_keys_configured(fake_llm, fake_rag, tmp_settings):
    """A16-A18：配了 writer_model / llm_temperature 时新键如实落盘（同源重算）。"""
    settings = Settings(
        ark_api_key=tmp_settings.ark_api_key,
        repo_root=tmp_settings.repo_root,
        novel_dir=tmp_settings.novel_dir,
        writer_model="kimi-k3",
        llm_temperature=0.7,
    )
    agent = NovelAgent(
        llm=fake_llm, rag=fake_rag, settings=settings,
        working_memory=WorkingMemory(),
    )
    _, record = agent.run("写第5章：异乡风起")
    cfg = record["config"]
    assert cfg["model"] == "glm-5.2"          # 主配置未动
    assert cfg["writer_model"] == "kimi-k3"   # 写作侧独立可见
    assert cfg["llm_temperature"] == 0.7
    # 密钥/端点绝不落盘
    assert "api_key" not in cfg and "base_url" not in cfg


# ---------- 1.1 质量门禁：_checker / _fixer / reviewer 富解析（T6）----------
def _gate_state(polished: str, **kw):
    """方法级直调用的 state：填好 polished 与任意覆盖字段。"""
    s = PipelineState(task="测试章节")
    s.polished = polished
    for k, v in kw.items():
        setattr(s, k, v)
    return s


GATE_TEXT = (
    "他沿着河岸走了很久。\n\n"
    "风从北边来。\n\n"
    "她的眼眸里闪过一丝哀伤。\n\n"
    "狗在村口叫了两声。\n\n"
    "水开了。\n"
)


def test_checker_no_rules_passes_through(fake_llm, tmp_settings):
    """未注入 quality_rules -> checker 直通 reviewer，零 LLM 调用。"""
    agent = NovelAgent(llm=fake_llm, settings=tmp_settings)
    state = _gate_state("她的眼眸里闪过一丝哀伤。")
    agent._checker(state)
    assert state.next_agent == "reviewer"
    assert state.review_count == 0
    assert state.issues == []
    assert fake_llm.calls == []            # 纯代码零 LLM


def test_checker_hit_rejects_to_fixer(fake_llm, tmp_settings):
    """命中 -> 打回 fixer：review_count+1（A14）、issues 入 state、feedback 附摘要（Z2）。"""
    agent = NovelAgent(
        llm=fake_llm, settings=tmp_settings,
        quality_rules={"blacklist": ["眼眸"]},
    )
    state = _gate_state("她的眼眸里闪过一丝哀伤。")
    agent._checker(state)
    assert state.next_agent == "fixer"
    assert state.review_count == 1
    assert len(state.issues) == 1
    assert "黑名单词" in state.feedback and "规则检查不通过" in state.feedback
    assert fake_llm.calls == []


def test_checker_clean_text_passes(fake_llm, tmp_settings):
    """有规则但无命中 -> 放行 reviewer，issues / review_count 不动。"""
    agent = NovelAgent(
        llm=fake_llm, settings=tmp_settings,
        quality_rules={"blacklist": ["眼眸"]},
    )
    state = _gate_state("风从北边来。")
    agent._checker(state)
    assert state.next_agent == "reviewer"
    assert state.issues == [] and state.review_count == 0


def test_checker_at_cap_lets_through_with_log(fake_llm, tmp_settings):
    """达打回上限放行 reviewer（D7）：review_count 不再递增，log 留痕。"""
    agent = NovelAgent(
        llm=fake_llm, settings=tmp_settings, max_reviews=1,
        quality_rules={"blacklist": ["眼眸"]},
    )
    state = _gate_state("她的眼眸里闪过一丝哀伤。", review_count=1)
    agent._checker(state)
    assert state.next_agent == "reviewer"
    assert state.review_count == 1
    assert any("放行" in line for line in state.log)


def test_fixer_repairs_located_paragraph(fake_llm, tmp_settings):
    """quote 定位段落后按标记协议修复：仅该段变、区间外逐字节不变、issues 清空（Z5）。"""
    agent = NovelAgent(llm=fake_llm, settings=tmp_settings)
    state = _gate_state(GATE_TEXT)
    state.issues = [{"quote": "她的眼眸里闪过一丝哀伤", "problem": "黑名单词「眼眸」", "fix": "换成具体描写"}]
    fake_llm.script = ["【第3段·修复后】\n她低下头，没说话。"]
    agent._fixer(state)

    assert state.next_agent == "checker"
    assert state.issues == []                                  # Z5 清空
    assert len(fake_llm.calls) == 1                            # A11 单次调用
    assert state.polished == GATE_TEXT.replace(
        "她的眼眸里闪过一丝哀伤。", "她低下头，没说话。")
    assert state.polished.startswith("他沿着河岸走了很久。\n\n风从北边来。\n\n")
    assert state.polished.endswith("\n\n狗在村口叫了两声。\n\n水开了。\n")
    assert any("[fixer]" in line for line in state.log)


def test_fixer_multi_issue_single_call(fake_llm, tmp_settings):
    """多个问题段合并单次调用（A11）：一次调用 payload 含全部问题段与各自意见。"""
    agent = NovelAgent(llm=fake_llm, settings=tmp_settings)
    state = _gate_state(GATE_TEXT)
    state.issues = [
        {"quote": "他沿着河岸", "problem": "p1", "fix": "f1"},
        {"quote": "她的眼眸", "problem": "p2", "fix": "f2"},
    ]
    fake_llm.script = ["【第1段·修复后】\n他沿河走了很久。\n\n【第3段·修复后】\n她低下头。"]
    agent._fixer(state)

    assert len(fake_llm.calls) == 1
    payload = fake_llm.calls[0]
    assert "第1段" in payload and "第3段" in payload
    assert "他沿着河岸走了很久。" in payload    # 段落原文入 prompt
    assert "她的眼眸里闪过一丝哀伤。" in payload
    assert "p1" in payload and "p2" in payload  # 各段意见入 prompt
    assert "他沿河走了很久。" in state.polished
    assert "她低下头。" in state.polished
    assert "风从北边来。" in state.polished       # 非问题段不动


def test_fixer_adjacent_paragraphs_merged(fake_llm, tmp_settings):
    """相邻问题段（2、3）合并为一个 span 整块替换，段间空行结构保持。"""
    agent = NovelAgent(llm=fake_llm, settings=tmp_settings)
    state = _gate_state(GATE_TEXT)
    state.issues = [
        {"quote": "风从北边来", "problem": "p1", "fix": "f1"},
        {"quote": "她的眼眸", "problem": "p2", "fix": "f2"},
    ]
    fake_llm.script = ["【第2段·修复后】\n新二。\n\n【第3段·修复后】\n新三。"]
    agent._fixer(state)

    assert "新二。\n\n新三。" in state.polished
    assert state.polished.startswith("他沿着河岸走了很久。\n\n")
    assert "狗在村口叫了两声。" in state.polished


def test_fixer_unlocatable_quote_goes_whole(fake_llm, tmp_settings):
    """quote 为空（metaphor 风格）-> 整文降级（D12）：payload 含原稿全文。"""
    agent = NovelAgent(llm=fake_llm, settings=tmp_settings)
    state = _gate_state(GATE_TEXT)
    state.issues = [{"quote": "", "problem": "比喻密度过高", "fix": "删减比喻"}]
    whole = "整文修复后的稿子，风从北边来，他沿着河岸走了很久，狗也叫了。" * 2
    fake_llm.script = [whole]
    agent._fixer(state)

    assert "【原稿全文】" in fake_llm.calls[0]      # fixer_whole_user 渲染
    assert "他沿着河岸走了很久。" in fake_llm.calls[0]
    assert state.next_agent == "checker"
    assert state.issues == []
    assert state.polished == whole
    assert any("整文" in line for line in state.log)


def test_fixer_quote_not_substring_goes_whole(fake_llm, tmp_settings):
    """quote 非原文子串 -> 整组整文降级（D12，不做混合协议），仍单次调用。"""
    agent = NovelAgent(llm=fake_llm, settings=tmp_settings)
    state = _gate_state(GATE_TEXT)
    state.issues = [
        {"quote": "他沿着河岸", "problem": "p1", "fix": "f1"},
        {"quote": "这句引文不在原文中", "problem": "p2", "fix": "f2"},  # 任一不可定位
    ]
    fake_llm.script = ["整文修复后的稿子，风从北边来，他沿着河岸走了很久，狗也叫了。" * 2]
    agent._fixer(state)

    assert "【原稿全文】" in fake_llm.calls[0]
    assert len(fake_llm.calls) == 1
    assert state.next_agent == "checker"


def test_fixer_shrink_protection_keeps_original(fake_llm, tmp_settings):
    """段落级字数保护（A15）：修复缩水超 50% 保留原段 + log 留痕。"""
    long_para = ("她的眼眸里闪过一丝淡淡的哀伤，情绪如潮水般涌上心头，无可回避。"
                 "他蹲在门槛上抽烟，没说话，屋檐下的灯还亮着。")
    text = f"{long_para}\n\n狗在村口叫了两声。\n"
    agent = NovelAgent(llm=fake_llm, settings=tmp_settings)
    state = _gate_state(text)
    state.issues = [{"quote": "眼眸", "problem": "p", "fix": "f"}]
    fake_llm.script = ["【第1段·修复后】\n太短。"]
    agent._fixer(state)

    assert state.polished == text                  # 保留原段
    assert any("缩水" in line for line in state.log)
    assert state.next_agent == "checker"


def test_fixer_missing_paragraph_falls_back(fake_llm, tmp_settings):
    """未返回段保持原文（D11）；LLM 幻觉返回的额外段号被忽略。"""
    agent = NovelAgent(llm=fake_llm, settings=tmp_settings)
    state = _gate_state(GATE_TEXT)
    state.issues = [
        {"quote": "他沿着河岸", "problem": "p1", "fix": "f1"},
        {"quote": "她的眼眸", "problem": "p2", "fix": "f2"},
    ]
    fake_llm.script = ["【第1段·修复后】\n新段一。\n\n【第5段·修复后】\n幻觉段。"]
    agent._fixer(state)

    assert "新段一。" in state.polished                  # 段 1 已修
    assert "她的眼眸里闪过一丝哀伤。" in state.polished  # 段 3 未返回 -> 原文
    assert "水开了。" in state.polished                   # 段 5 未请求 -> 幻觉被忽略
    assert "幻觉段。" not in state.polished


def test_reviewer_rich_parse_reject_stores_scores_issues(fake_llm, tmp_settings):
    """reviewer 富解析：scores/issues 落 state；打回 feedback 含 problem 摘要（A3）。"""
    agent = NovelAgent(llm=fake_llm, settings=tmp_settings)
    state = _gate_state("风起了。")
    fake_llm.script = [
        '{"pass": false, "reason": "称呼错误", '
        '"scores": {"人物一致性": 4, "文风一致性": 2}, '
        '"issues": [{"quote": "许风走进来", "problem": "人物一致性：称呼错误", "fix": "改为林晚"}]}'
    ]
    agent._reviewer(state)

    assert state.scores == {"人物一致性": 4, "文风一致性": 2}
    assert state.issues == [{"quote": "许风走进来", "problem": "人物一致性：称呼错误", "fix": "改为林晚"}]
    assert state.review_count == 1
    assert "称呼错误" in state.feedback
    assert "人物一致性：称呼错误" in state.feedback    # problem 摘要进 feedback
    assert state.next_agent == "fixer"               # 1.1 D9：打回固定 fixer
    assert not state.final_chapter


def test_reviewer_rich_parse_pass_keeps_scores(fake_llm, tmp_settings):
    """通过路径：scores 落 state 且定稿。"""
    agent = NovelAgent(llm=fake_llm, settings=tmp_settings)
    state = _gate_state("风起了。")
    fake_llm.script = ['{"pass": true, "reason": "通过", "scores": {"人物一致性": 5}, "issues": []}']
    agent._reviewer(state)

    assert state.scores == {"人物一致性": 5}
    assert state.issues == []
    assert state.final_chapter == "风起了。"
    assert state.next_agent == "done"


def test_record_config_quality_rules_flag(fake_llm, tmp_settings):
    """Z6：config.quality_rules 布尔如实反映注入状态。"""
    agent = NovelAgent(llm=fake_llm, settings=tmp_settings)
    _, record = agent.run("写第5章：异乡风起")
    assert record["config"]["quality_rules"] is False

    agent2 = NovelAgent(llm=fake_llm, settings=tmp_settings, quality_rules={"blacklist": ["眼眸"]})
    _, record2 = agent2.run("写第5章：异乡风起")
    assert record2["config"]["quality_rules"] is True


# ---------------- 0.9：单代理温度（_temp 融合） ----------------


def _mk_agent_for_temp(**temp_kw) -> tuple:
    """构造最小 agent + 记录型 LLM，返回 (agent, recorder)。"""
    rec = _SysRecorder()
    s = Settings(ark_api_key="k", base_url="u", model="m", **temp_kw)
    agent = NovelAgent(llm=rec, settings=s, working_memory=WorkingMemory())
    return agent, rec


def test_temp_defaults_when_unset():
    """全不配：三个代理用调用点默认 0.8/0.6/0.2。"""
    agent, _ = _mk_agent_for_temp()
    assert agent._temp("writer", 0.8) == 0.8
    assert agent._temp("polisher", 0.6) == 0.6
    assert agent._temp("reviewer", 0.2) == 0.2


def test_temp_novel_temperature_writer_side_fallback():
    """只配 NOVEL_TEMPERATURE：writer/polisher 吃到，reviewer 不吃（只管写作侧）。"""
    agent, _ = _mk_agent_for_temp(llm_temperature=0.7)
    assert agent._temp("writer", 0.8) == 0.7
    assert agent._temp("polisher", 0.6) == 0.7
    assert agent._temp("reviewer", 0.2) == 0.2


def test_temp_per_agent_wins_over_fallback():
    """单代理配置赢过 NOVEL_TEMPERATURE（细粒度优先）。"""
    agent, _ = _mk_agent_for_temp(
        llm_temperature=0.7, writer_temperature=0.95
    )
    assert agent._temp("writer", 0.8) == 0.95
    assert agent._temp("polisher", 0.6) == 0.7   # 未单配，吃兜底


def test_temp_reviewer_independent():
    """reviewer 单配直接生效，与写作侧配置互不影响。"""
    agent, _ = _mk_agent_for_temp(
        llm_temperature=0.7, reviewer_temperature=0.5
    )
    assert agent._temp("reviewer", 0.2) == 0.5


def test_temp_aux_roles():
    """辅助角色（0.9 全量可配）：fixer 属写作侧吃 NOVEL_TEMPERATURE 兜底；
    judge/summarizer/router 只看自己的键，不吃写作侧兜底。"""
    agent, _ = _mk_agent_for_temp(
        llm_temperature=0.7, judge_temperature=0.4
    )
    assert agent._temp("fixer", 0.5) == 0.7      # 写作侧兜底
    assert agent._temp("judge", 0.2) == 0.4     # 自己的键
    assert agent._temp("summarizer", 0.3) == 0.3  # 无配置回默认
    assert agent._temp("router", 0.2) == 0.2


def test_temp_fixer_own_key_wins_over_fallback():
    """fixer 单配赢过 NOVEL_TEMPERATURE（细粒度优先，同三代理规则）。"""
    agent, _ = _mk_agent_for_temp(
        llm_temperature=0.7, fixer_temperature=0.9
    )
    assert agent._temp("fixer", 0.5) == 0.9


def test_run_uses_configured_temperatures(fake_rag, tmp_settings):
    """端到端：run 全流程各调用点的温度来自配置。"""
    rec = _SysRecorder(script=[
        "构思。\n===\n正文。",
        "【润色】正文。",
        '{"pass": true, "reason": "通过"}',
    ])
    from dataclasses import replace
    s = replace(
        tmp_settings,
        writer_temperature=0.9, polisher_temperature=0.5, reviewer_temperature=0.3,
    )
    agent = NovelAgent(
        llm=rec, rag=fake_rag, settings=s, working_memory=WorkingMemory()
    )
    agent.run("写第1章：测试")
    assert rec.kws[0]["temperature"] == 0.9   # writer
    assert rec.kws[1]["temperature"] == 0.5   # polisher
    assert rec.kws[2]["temperature"] == 0.3   # reviewer


# ---------------- 1.6 style-loop：deai_refine / _fix_spans ----------------
def test_deai_refine_rewrites_marked_paragraph(fake_llm, tmp_settings):
    """B12：标记协议重写问题段，区间外逐字节不变；单次调用。"""
    agent = NovelAgent(llm=fake_llm, settings=tmp_settings)
    fake_llm.script = ["【第3段·修复后】\n她低头，风把话吹散。"]
    issues = [{"quote": "她的眼眸里闪过一丝哀伤", "problem": "黑名单词「一丝」", "fix": "换成具体描写"}]
    new_text, n = agent.deai_refine(GATE_TEXT, issues)

    assert n == 1
    assert len(fake_llm.calls) == 1                      # 单次调用（A11 纪律）
    assert new_text == GATE_TEXT.replace(
        "她的眼眸里闪过一丝哀伤。", "她低头，风把话吹散。")
    assert new_text.startswith("他沿着河岸走了很久。\n\n风从北边来。\n\n")  # 区间外不动
    assert new_text.endswith("\n\n狗在村口叫了两声。\n\n水开了。\n")


def test_deai_refine_missing_paragraph_falls_back(fake_llm, tmp_settings):
    """D11：未返回段保持原文；幻觉段号被忽略。"""
    agent = NovelAgent(llm=fake_llm, settings=tmp_settings)
    fake_llm.script = ["【第1段·修复后】\n他沿河走。\n\n【第5段·修复后】\n幻觉段。"]
    issues = [
        {"quote": "他沿着河岸", "problem": "p1", "fix": "f1"},
        {"quote": "她的眼眸", "problem": "p2", "fix": "f2"},
    ]
    new_text, n = agent.deai_refine(GATE_TEXT, issues)

    assert n == 2
    assert "他沿河走。" in new_text                          # 段 1 已改
    assert "她的眼眸里闪过一丝哀伤。" in new_text           # 段 3 未返回 -> 原文
    assert "幻觉段。" not in new_text                        # 段 5 未请求 -> 幻觉被忽略


def test_deai_refine_shrink_protection_keeps_original(fake_llm, tmp_settings, capsys):
    """A15 同款：重写缩水超 50% 保留原段（打印提示）。"""
    long_para = ("她的眼眸里闪过一丝淡淡的哀伤，情绪如潮水般涌上心头，无可回避。"
                 "他蹲在门槛上抽烟，没说话，屋檐下的灯还亮着。")
    text = f"{long_para}\n\n狗在村口叫了两声。\n"
    agent = NovelAgent(llm=fake_llm, settings=tmp_settings)
    fake_llm.script = ["【第1段·修复后】\n太短。"]
    new_text, _ = agent.deai_refine(text, [{"quote": "眼眸", "problem": "p", "fix": "f"}])

    assert new_text == text                                  # 保留原段
    assert "字数保护" in capsys.readouterr().out


def test_deai_refine_empty_issues_no_llm(fake_llm, tmp_settings):
    """B17：空 issues 返回 (原文, 0)，零 LLM 调用。"""
    agent = NovelAgent(llm=fake_llm, settings=tmp_settings)
    new_text, n = agent.deai_refine(GATE_TEXT, [])
    assert new_text == GATE_TEXT and n == 0
    assert fake_llm.calls == []


def test_deai_refine_all_unlocatable_no_llm(fake_llm, tmp_settings):
    """B17/D8：全部不可定位（quote 空/非子串）-> 丢弃不降级，返回原文零调用。"""
    agent = NovelAgent(llm=fake_llm, settings=tmp_settings)
    issues = [
        {"quote": "", "problem": "比喻密度过高", "fix": "删减"},
        {"quote": "这句引文不在原文中", "problem": "p", "fix": "f"},
    ]
    new_text, n = agent.deai_refine(GATE_TEXT, issues)
    assert new_text == GATE_TEXT and n == 0
    assert fake_llm.calls == []


def test_deai_refine_drops_unlocatable_keeps_locatable(fake_llm, tmp_settings):
    """D8：混合输入 -> 不可定位丢弃、可定位照常重写（不整文降级）。"""
    agent = NovelAgent(llm=fake_llm, settings=tmp_settings)
    fake_llm.script = ["【第3段·修复后】\n她低头。"]
    issues = [
        {"quote": "", "problem": "比喻密度过高", "fix": "删减"},     # 丢弃
        {"quote": "她的眼眸", "problem": "黑名单词", "fix": "换具体"},  # 保留
    ]
    new_text, n = agent.deai_refine(GATE_TEXT, issues)

    assert n == 1
    assert new_text == GATE_TEXT.replace("她的眼眸里闪过一丝哀伤。", "她低头。")
    payload = fake_llm.calls[0]
    assert "她的眼眸里闪过一丝哀伤。" in payload        # 可定位段进 prompt
    assert "比喻密度过高" not in payload               # 不可定位 issue 不进 prompt
    assert "【原稿全文】" not in payload                # 不整文降级（与 fixer 的差异点）


def test_deai_refine_temperature_override():
    """deai 调用吃 NOVEL_FIXER_TEMPERATURE / NOVEL_TEMPERATURE 覆盖链。"""
    from dataclasses import replace

    class _Rec:
        def __init__(self):
            self.kws = []

        def chat(self, system, user, **kw):
            self.kws.append(kw)
            return "【第3段·修复后】\n她低头。"

    rec = _Rec()
    s = replace(Settings(ark_api_key="k"), fixer_temperature=0.9)
    agent = NovelAgent(llm=rec, settings=s)
    agent.deai_refine(GATE_TEXT, [{"quote": "她的眼眸", "problem": "p", "fix": "f"}])
    assert rec.kws[0]["temperature"] == 0.9


def test_fixer_behavior_unchanged_after_extraction(fake_llm, tmp_settings):
    """D2 回归护栏：_fix_spans 抽取后 fixer 打回路径行为不变（A8-A15 之外再补一条端到端）。"""
    agent = NovelAgent(llm=fake_llm, settings=tmp_settings)
    state = _gate_state(GATE_TEXT)
    state.issues = [{"quote": "她的眼眸里闪过一丝哀伤", "problem": "黑名单词「眼眸」", "fix": "换成具体描写"}]
    fake_llm.script = ["【第3段·修复后】\n她低下头，没说话。"]
    agent._fixer(state)

    assert state.next_agent == "checker"
    assert state.issues == []
    assert state.polished == GATE_TEXT.replace(
        "她的眼眸里闪过一丝哀伤。", "她低下头，没说话。")
    assert any("[fixer] 修复 1 段" in line for line in state.log)


def test_state_deai_field_defaults():
    """B14：PipelineState.deai 默认空 dict，asdict 自动落 record。"""
    from dataclasses import asdict
    s = PipelineState(task="x")
    assert s.deai == {}
    assert "deai" in asdict(s)


def test_writer_prompt_contains_recent_human(fake_rag, tmp_settings):
    """B5：滚动人工正文只进 writer 的 system prompt（构造器注入，novel_name 默认）。"""
    rec = _SysRecorder(script=["构思。\n===\n正文。"])
    agent = NovelAgent(
        llm=rec, rag=fake_rag, settings=tmp_settings,
        working_memory=WorkingMemory(), recent_human="人工正文片段",
    )
    state = PipelineState(task="写第1章：测试")
    agent._writer(state)
    assert "【近期人工正文】" in rec.systems[0]
    assert "人工正文片段" in rec.systems[0]

    # 对照：不注入时（B18 现状）prompt 无该分节
    rec2 = _SysRecorder(script=["构思。\n===\n正文。"])
    agent2 = NovelAgent(llm=rec2, rag=fake_rag, settings=tmp_settings, working_memory=WorkingMemory())
    agent2._writer(PipelineState(task="写第1章：测试"))
    assert "近期人工正文" not in rec2.systems[0]
