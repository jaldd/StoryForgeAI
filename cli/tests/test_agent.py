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
