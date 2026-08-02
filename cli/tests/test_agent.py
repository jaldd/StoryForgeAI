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


def test_parse_review_fallback_true():
    """非 JSON 且不含'不通过' -> 默认通过。"""
    ok, _ = parse_review("看不懂这段，无法判断")
    assert ok is True


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
        "【润色1】风起了，云依。",                  # polisher #1
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
        "构思：风起，他站在路口，云依没回头。\n===\n风起了。他没说话。云依没回头。",  # writer
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
