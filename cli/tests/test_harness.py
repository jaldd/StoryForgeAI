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


def test_evaluate_empty(sample_run, tmp_settings, fake_llm):
    """评测模型空回 -> 打印'未返回内容'，返回 error dict。"""
    fake_llm.script = [""]
    lines = []
    score = evaluate(sample_run, tmp_settings, llm=fake_llm, out=lines.append)
    assert "error" in score
    assert "未返回内容" in "\n".join(lines)


def test_evaluate_parse_failure(sample_run, tmp_settings, fake_llm):
    """评测返回非 JSON -> 打印'解析失败' + 原始返回前500字。"""
    fake_llm.script = ["这不是JSON，评委随便说了几句话。"]
    lines = []
    score = evaluate(sample_run, tmp_settings, llm=fake_llm, out=lines.append)
    assert "error" in score
    text = "\n".join(lines)
    assert "解析失败" in text
    assert "这不是JSON" in text  # 原始返回前500字被打印


def test_evaluate_truncated_append_brace(sample_run, tmp_settings, fake_llm):
    """JSON 仅缺结尾 }（字符串已闭合）-> 补 } 解析成功。"""
    fake_llm.script = ['{"连贯性":3,"人物一致性":4,"剧情合理性":3,"理由":"可以"']
    score = evaluate(sample_run, tmp_settings, llm=fake_llm, out=lambda s: None)
    assert score.get("连贯性") == 3
    assert score.get("理由") == "可以"


def test_evaluate_truncated_extract_fields(sample_run, tmp_settings, fake_llm):
    """JSON 被截断（连字符串都没闭合）-> 正则提取分数仍能拿到。"""
    fake_llm.script = ['{"连贯性":4,"人物一致性":5,"剧情合理性":4,"理由":"整体稳，节奏好']
    lines = []
    score = evaluate(sample_run, tmp_settings, llm=fake_llm, out=lines.append)
    assert score.get("连贯性") == 4
    assert score.get("人物一致性") == 5
    assert score.get("理由") == "整体稳，节奏好"


def test_eval_system_prompt_with_instruction():
    """非空 instruction 时 system prompt 前置写作规则；空则原样返回 rubric。"""
    from novel_agent.harness import _eval_system_prompt
    from novel_agent.prompts import EVALUATOR_RUBRIC
    p = _eval_system_prompt("男主前4章不取名")
    assert "【写作规则】" in p
    assert "男主前4章不取名" in p
    assert "不扣分" in p
    assert EVALUATOR_RUBRIC in p  # 原 rubric 完整保留
    assert _eval_system_prompt("") == EVALUATOR_RUBRIC


def test_evaluate_passes_instruction_to_system(sample_run, tmp_settings):
    """evaluate 把 instruction 注入 system prompt（用捕获 system 的假 LLM）。"""
    captured = {}

    class SysLLM:
        def chat(self, system, user, **kw):
            captured["system"] = system
            return '{"连贯性":4,"人物一致性":4,"剧情合理性":4,"理由":"ok"}'

    evaluate(sample_run, tmp_settings, llm=SysLLM(), out=lambda s: None,
             instruction="男主前4章不取名")
    assert "【写作规则】" in captured["system"]
    assert "男主前4章不取名" in captured["system"]


def test_evaluate_title_dimension(sample_run, tmp_settings, fake_llm):
    """评测结果含标题维度 -> 报告打印标题评分/建议标题/标题理由。"""
    fake_llm.script = ['{"连贯性":4,"人物一致性":5,"剧情合理性":4,"标题评分":3,"理由":"稳","建议标题":"风起路口","标题理由":"现标题平淡"}']
    lines = []
    score = evaluate(sample_run, tmp_settings, llm=fake_llm, out=lines.append)
    assert score["标题评分"] == 3
    assert score["建议标题"] == "风起路口"
    text = "\n".join(lines)
    assert "标题评分: 3/5" in text
    assert "建议标题" in text and "风起路口" in text and "仅建议" in text
    assert "标题理由" in text and "现标题平淡" in text


def test_evaluate_title_keep(sample_run, tmp_settings, fake_llm):
    """建议标题为'保留'时不打印建议行；标题评分与标题理由仍打印。"""
    fake_llm.script = ['{"连贯性":4,"人物一致性":5,"剧情合理性":4,"标题评分":5,"理由":"好","建议标题":"保留","标题理由":"贴切"}']
    lines = []
    score = evaluate(sample_run, tmp_settings, llm=fake_llm, out=lines.append)
    text = "\n".join(lines)
    assert "标题评分: 5/5" in text
    assert "建议标题" not in text  # 保留 -> 不打印建议行
    assert "贴切" in text  # 标题理由仍打印


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
