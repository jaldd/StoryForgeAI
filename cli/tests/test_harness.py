"""harness 模块测试：回放/评测/规则测试/对比，用 fixture run + fake LLM。"""
from novel_agent.harness import compare, evaluate, replay, run_tests


def test_replay(sample_run, tmp_settings):
    lines = []
    d = replay(sample_run, tmp_settings, out=lines.append)
    assert d["run_id"] == sample_run
    text = "\n".join(lines)
    assert "回放" in text and "共 3 步" in text
    assert "风起了" in text  # 最终章节打印


def test_run_tests_pass(sample_run, tmp_settings):
    """样例 run 守住铁律（含'风'、不含'许风'、审稿通过且 done）-> 全通过。"""
    lines = []
    ok = run_tests(sample_run, tmp_settings, out=lines.append)
    assert ok is True
    assert "全部通过" in "\n".join(lines)


def test_run_tests_fail_on_rule_violation(tmp_settings):
    """违反铁律（含'许风'）-> FAIL。"""
    from novel_agent.storage import save_run
    record = {
        "run_id": "run_bad", "task": "x", "timestamp": "", "config": {},
        "initial_state": {}, "steps": [],
        "final_state": {
            "task": "x", "draft": "", "polished": "",
            "feedback": "审稿通过：ok", "final_chapter": "许风走在风里",
            "round": 1, "next_agent": "done", "review_count": 0, "log": [],
        },
    }
    save_run(record, tmp_settings)
    ok = run_tests("run_bad", tmp_settings, out=lambda s: None)
    assert ok is False


def test_evaluate_with_fake_llm(sample_run, tmp_settings, fake_llm):
    fake_llm.script = ['{"连贯性":4,"人物一致性":5,"剧情合理性":4,"理由":"稳"}']
    score = evaluate(sample_run, tmp_settings, llm=fake_llm, out=lambda s: None)
    assert score["连贯性"] == 4 and score["人物一致性"] == 5
    assert score["理由"] == "稳"


def test_compare(sample_run, tmp_settings):
    """两个 run 并排对比不报错。"""
    from novel_agent.storage import save_run
    record_b = {
        "run_id": "run_b", "task": "写第5章：异乡风起", "timestamp": "",
        "config": {"temperature": 0.5},
        "initial_state": {}, "steps": [],
        "final_state": {
            "task": "x", "draft": "", "polished": "",
            "feedback": "审稿不通过", "final_chapter": "小镇的雨刚歇。",
            "round": 1, "next_agent": "done", "review_count": 0, "log": [],
        },
    }
    save_run(record_b, tmp_settings)
    lines = []
    compare(sample_run, "run_b", tmp_settings, out=lines.append)
    text = "\n".join(lines)
    assert "A/B 对比" in text
    assert "0.9" in text and "0.5" in text  # 两个 temperature
