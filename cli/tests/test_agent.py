"""agent 模块测试：状态机流程，用 fake LLM/RAG 不联网。"""
from novel_agent.agent import NovelAgent, parse_review
from novel_agent.memory import WorkingMemory


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
    assert len(record["steps"]) == 4  # director/writer/polisher/reviewer
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
    """审稿先打回再通过：review_count 递增，回到 writer 重写。"""
    fake_llm.script = [
        "【初稿1】风起了。",                       # writer #1
        "【润色1】风起了，林晚。",                  # polisher #1
        '{"pass": false, "reason": "不够克制"}',  # reviewer #1 -> 打回
        "【初稿2】风又起了。",                      # writer #2
        "【润色2】风又起了，她在。",                # polisher #2
        '{"pass": true, "reason": "通过"}',       # reviewer #2 -> 通过
    ]
    agent = NovelAgent(
        llm=fake_llm, rag=fake_rag, exemplar="范文",
        settings=tmp_settings, working_memory=WorkingMemory(),
    )
    state, record = agent.run("写第5章：异乡风起")

    assert state.review_count == 1
    assert state.next_agent == "done"
    assert state.final_chapter == "【润色2】风又起了，她在。"
    assert len(record["steps"]) == 7  # 4 + 打回多出的 writer/polisher/reviewer
    assert len(fake_llm.calls) == 6


def test_pipeline_max_reviews_cap(fake_llm, fake_rag, tmp_settings):
    """达到打回上限强制定稿，防死循环。"""
    fake_llm.script = [
        "【初稿1】",                  # writer #1
        "【润色1】",                  # polisher #1
        '{"pass": false, "reason": "不好"}',  # reviewer #1 -> 打回 (review_count=1)
        "【初稿2】",                  # writer #2
        "【润色2】最终稿",            # polisher #2
        # reviewer #2 不再调 LLM：review_count(1) >= max_reviews(1) -> 强制定稿
    ]
    agent = NovelAgent(
        llm=fake_llm, rag=fake_rag, exemplar="范文",
        settings=tmp_settings, working_memory=WorkingMemory(), max_reviews=1,
    )
    state, _ = agent.run("写第5章：异乡风起")
    assert state.review_count == 1
    assert state.next_agent == "done"
    assert state.final_chapter == "【润色2】最终稿"
    assert len(fake_llm.calls) == 5  # 第 2 次 reviewer 未调 LLM


def test_pipeline_max_reviews_forced_finalize_warns(fake_llm, fake_rag, tmp_settings, capsys):
    """0.1：强制定稿逃生门必须控制台显著警告 + run 日志留痕。"""
    fake_llm.script = [
        "【初稿1】", "【润色1】", '{"pass": false, "reason": "不好"}',
        "【初稿2】", "【润色2】最终稿",
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
    """精修：跳过 director/writer，polisher->reviewer，初稿=传入内容。"""
    agent = NovelAgent(
        llm=fake_llm, rag=fake_rag, exemplar="范文",
        settings=tmp_settings, working_memory=WorkingMemory(),
    )
    state, record = agent.refine("这是要精修的初稿。", "精修：第5章")
    assert state.next_agent == "done"
    assert state.final_chapter  # 非空
    assert state.draft == "这是要精修的初稿。"  # 初稿保留
    assert len(record["steps"]) == 2  # 只有 polisher + reviewer
    assert record["run_id"].startswith("refine_")
    assert all("写一段新章节" not in c for c in fake_llm.calls)  # 未走 writer


def test_refine_reject_goes_to_polisher(fake_llm, fake_rag, tmp_settings):
    """精修模式下 reviewer 打回 -> 回 polisher，不回 writer。"""
    fake_llm.script = [
        "【润色1】",                              # polisher #1
        '{"pass": false, "reason": "不够克制"}',  # reviewer #1 -> 打回 polisher
        "【润色2】最终",                          # polisher #2
        '{"pass": true, "reason": "通过"}',       # reviewer #2 -> 通过
    ]
    agent = NovelAgent(
        llm=fake_llm, rag=fake_rag, exemplar="范文",
        settings=tmp_settings, working_memory=WorkingMemory(),
    )
    state, record = agent.refine("初稿", "精修：x")
    assert state.review_count == 1
    assert state.next_agent == "done"
    assert state.final_chapter == "【润色2】最终"
    assert len(record["steps"]) == 4  # polisher,reviewer,polisher,reviewer
    assert len(fake_llm.calls) == 4
    assert all("写一段新章节" not in c for c in fake_llm.calls)
    # refine 跑完应复位打回目标，不影响后续 run()
    assert agent._reject_target == "writer"


def test_writer_strips_construction_notes(fake_llm, fake_rag, tmp_settings):
    """writer 输出'构思 === 正文'时，state.draft 只保留正文，丢弃构思与分隔符。"""
    fake_llm.script = [
        "构思：风起，他站在路口，林晚没回头。\n===\n风起了。他没说话。林晚没回头。",  # writer
        "【润色】风起了。",  # polisher
        '{"pass": true, "reason": "通过"}',  # reviewer
    ]
    agent = NovelAgent(
        llm=fake_llm, rag=fake_rag, exemplar="范文",
        settings=tmp_settings, working_memory=WorkingMemory(),
    )
    state, _ = agent.run("写第5章：异乡风起")
    assert "构思" not in state.draft
    assert "===" not in state.draft
    assert "风起了。他没说话。" in state.draft


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
    # "---" 分隔正文与说明
    assert _strip_polisher_meta("正文第一段。\n\n---\n\n这是说明。") == "正文第一段。"
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
