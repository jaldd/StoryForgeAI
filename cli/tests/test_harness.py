"""harness 模块测试：回放/评测/规则测试/对比，用 fixture run + fake LLM。

1.1 T9 覆盖：run_tests 规则驱动断言（forbidden/intent_words/八维分/规则缺失降级）、
evaluate AI 味行与返回键、compare 规则词行与 AI 味浓度行。
1.1 T10 覆盖：backtest_gate 缓存命中不重烧、无 final_chapter 跳过、
分布与拦截面输出、eval_gate 未配置降级、cli 回测门禁命令冒烟。
"""
import json

from novel_agent.harness import backtest_gate, compare, evaluate, replay, run_tests


def _write_rules(tmp_settings, forbidden=None, intent_words=None):
    """写质量规则 JSON 到 tmp 小说目录（naming_redlines.forbidden / intent_words）。"""
    novel = tmp_settings.novel_path
    novel.mkdir(parents=True, exist_ok=True)
    rules = {}
    if forbidden is not None:
        rules["naming_redlines"] = {"forbidden": forbidden}
    if intent_words is not None:
        rules["intent_words"] = intent_words
    (novel / "质量规则.json").write_text(json.dumps(rules), encoding="utf-8")


def test_replay(sample_run, tmp_settings):
    lines = []
    d = replay(sample_run, tmp_settings, out=lines.append)
    assert d["run_id"] == sample_run
    text = "\n".join(lines)
    assert "回放" in text and "共 3 步" in text
    assert "风起了" in text  # 最终章节打印
    assert "构思：" not in text  # A20：旧记录无 outline 键，不显示空构思行


def test_replay_shows_outline(tmp_settings):
    """T13：writer 步含 outline 时回放展示构思行（前 60 字）。"""
    from novel_agent.storage import save_run
    record = {
        "run_id": "run_outline", "task": "写第5章：异乡风起", "timestamp": "",
        "config": {},
        "initial_state": {},
        "steps": [
            {"step_id": 1, "agent": "writer", "round": 1,
             "input_state": {},
             "output_state": {"outline": "风起，他站在路口，林晚没回头。",
                              "draft": "风起了。", "next_agent": "polisher"},
             "decision": "polisher"},
        ],
        "final_state": {"final_chapter": "风起了。"},
    }
    save_run(record, tmp_settings)
    lines = []
    replay("run_outline", tmp_settings, out=lines.append)
    text = "\n".join(lines)
    assert "构思：风起，他站在路口，林晚没回头。" in text


def test_run_tests_pass(sample_run, tmp_settings):
    """样例 run 守住铁律（含'风'、不含'许风'、审稿通过且 done）-> 全通过。"""
    lines = []
    ok = run_tests(sample_run, tmp_settings, out=lines.append)
    assert ok is True
    assert "全部通过" in "\n".join(lines)


def test_run_tests_fail_on_rule_violation(tmp_settings):
    """违反称呼红线（规则 forbidden 含'许风'且正文出现）-> FAIL。"""
    from novel_agent.storage import save_run
    _write_rules(tmp_settings, forbidden=["许风"])
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
    lines = []
    ok = run_tests("run_bad", tmp_settings, out=lines.append)
    assert ok is False
    assert "称呼红线：不含'许风'" in "\n".join(lines)


def test_run_tests_with_rules_pass(sample_run, tmp_settings):
    """规则驱动断言：forbidden 不出现 + intent_words 出现 -> 全通过。"""
    _write_rules(tmp_settings, forbidden=["许风"], intent_words=["风"])
    lines = []
    ok = run_tests(sample_run, tmp_settings, out=lines.append)
    text = "\n".join(lines)
    assert ok is True
    assert "称呼红线：不含'许风'" in text
    assert "意图：含'风'" in text
    assert "全部通过" in text


def test_run_tests_missing_intent_word_fails(tmp_settings):
    """意图词缺失（规则要求含'雨'但正文没有）-> FAIL。"""
    from novel_agent.storage import save_run
    _write_rules(tmp_settings, intent_words=["雨"])
    record = {
        "run_id": "run_norain", "task": "x", "timestamp": "", "config": {},
        "initial_state": {}, "steps": [],
        "final_state": {
            "task": "x", "draft": "", "polished": "",
            "feedback": "审稿通过：ok", "final_chapter": "风起了。",
            "round": 1, "next_agent": "done", "review_count": 0, "log": [],
        },
    }
    save_run(record, tmp_settings)
    lines = []
    ok = run_tests("run_norain", tmp_settings, out=lines.append)
    assert ok is False
    assert "意图：含'雨'" in "\n".join(lines)


def test_run_tests_no_rules_only_flow(tmp_settings):
    """规则缺失 -> 只剩流程断言（A36 不误伤：含'许风'的旧稿也通过）。"""
    from novel_agent.storage import save_run
    record = {
        "run_id": "run_norules", "task": "x", "timestamp": "", "config": {},
        "initial_state": {}, "steps": [],
        "final_state": {
            "task": "x", "draft": "", "polished": "",
            "feedback": "审稿通过：ok", "final_chapter": "许风走在风里",
            "round": 1, "next_agent": "done", "review_count": 0, "log": [],
        },
    }
    save_run(record, tmp_settings)
    lines = []
    ok = run_tests("run_norules", tmp_settings, out=lines.append)
    text = "\n".join(lines)
    assert ok is True
    assert "称呼红线" not in text
    assert "意图：" not in text


_SCORES_OK = {"人物一致性": 4, "文风一致性": 3, "剧情连贯性": 4, "时间线一致性": 5,
              "环境一致性": 4, "伏笔一致性": 5, "比喻密度": 4, "视角越界": 5}


def _scored_run(run_id, scores):
    """final_state 带 scores 的 run 记录（新格式）。"""
    return {
        "run_id": run_id, "task": "x", "timestamp": "", "config": {},
        "initial_state": {}, "steps": [],
        "final_state": {
            "task": "x", "draft": "", "polished": "",
            "feedback": "审稿通过：ok", "final_chapter": "风起了。",
            "round": 1, "next_agent": "done", "review_count": 0, "log": [],
            "scores": scores,
        },
    }


def test_run_tests_scores_all_dims_pass(tmp_settings):
    """新记录八维齐全且各分 1-5 整数 -> 维度分断言 PASS。"""
    from novel_agent.storage import save_run
    save_run(_scored_run("run_scores_ok", dict(_SCORES_OK)), tmp_settings)
    lines = []
    ok = run_tests("run_scores_ok", tmp_settings, out=lines.append)
    text = "\n".join(lines)
    assert ok is True
    assert "[PASS] 维度分：八维齐全且各分 1-5 整数" in text


def test_run_tests_scores_missing_dim_fails(tmp_settings):
    """八维缺一（无'比喻密度'）-> FAIL。"""
    from novel_agent.storage import save_run
    bad = dict(_SCORES_OK)
    del bad["比喻密度"]
    save_run(_scored_run("run_scores_missing", bad), tmp_settings)
    lines = []
    ok = run_tests("run_scores_missing", tmp_settings, out=lines.append)
    assert ok is False
    assert "缺失=['比喻密度']" in "\n".join(lines)


def test_run_tests_scores_out_of_range_fails(tmp_settings):
    """越界分（6）-> FAIL。"""
    from novel_agent.storage import save_run
    bad = dict(_SCORES_OK)
    bad["视角越界"] = 6
    save_run(_scored_run("run_scores_range", bad), tmp_settings)
    ok = run_tests("run_scores_range", tmp_settings, out=lambda s: None)
    assert ok is False


def test_run_tests_old_record_without_scores_skips(sample_run, tmp_settings):
    """旧记录无 scores 键 -> 维度分断言跳过（A37），不 FAIL。"""
    lines = []
    ok = run_tests(sample_run, tmp_settings, out=lines.append)
    assert ok is True
    assert "维度分" not in "\n".join(lines)


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


def test_evaluate_ai_flavor_line(sample_run, tmp_settings, fake_llm, monkeypatch):
    """T9：评分后追加 AI 味行（design §3.8 样例格式），返回 dict 增 AI味浓度键。"""
    import novel_agent.harness as harness
    monkeypatch.setattr(harness, "ai_flavor_score", lambda text, rules, baseline: {
        "score": 62, "components": {"blacklist": 45, "sentence": 70, "freq": 55},
        "degraded": False})
    fake_llm.script = ['{"连贯性":4,"人物一致性":5,"剧情合理性":4,"理由":"稳"}']
    lines = []
    score = evaluate(sample_run, tmp_settings, llm=fake_llm, out=lines.append)
    text = "\n".join(lines)
    assert "AI 味浓度: 62/100（越高越AI） 组件：黑名单 45 · 句长 70 · 词频 55" in text
    assert "降级" not in text
    assert score["AI味浓度"] == 62


def test_evaluate_ai_flavor_degraded_line(sample_run, tmp_settings, fake_llm, monkeypatch):
    """T9：降级（基准语料不足）-> 附提示行，AI 味行仍打印。"""
    import novel_agent.harness as harness
    monkeypatch.setattr(harness, "ai_flavor_score", lambda text, rules, baseline: {
        "score": 40, "components": {"blacklist": 40, "sentence": 40}, "degraded": True})
    fake_llm.script = ['{"连贯性":4,"人物一致性":5,"剧情合理性":4,"理由":"稳"}']
    lines = []
    score = evaluate(sample_run, tmp_settings, llm=fake_llm, out=lines.append)
    text = "\n".join(lines)
    assert "AI 味浓度: 40/100" in text
    assert "（降级：基准语料不足，词频组件未参与）" in text
    assert score["AI味浓度"] == 40


def test_evaluate_ai_flavor_real_no_baseline(sample_run, tmp_settings, fake_llm):
    """T9 真实路径：tmp 环境无基准语料 -> 降级行照打、返回键为整数、不崩。"""
    fake_llm.script = ['{"连贯性":4,"人物一致性":5,"剧情合理性":4,"理由":"稳"}']
    lines = []
    score = evaluate(sample_run, tmp_settings, llm=fake_llm, out=lines.append)
    text = "\n".join(lines)
    assert "AI 味浓度:" in text
    assert "（降级：基准语料不足，词频组件未参与）" in text
    assert isinstance(score["AI味浓度"], int)


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


def _new_format_record(run_id, writer_model):
    """0.7 新格式 run：config 含 model / writer_model / llm_temperature 键。"""
    return {
        "run_id": run_id, "task": "写第5章：异乡风起", "timestamp": "",
        "config": {"model": "glm-5.2", "temperature": 0.9,
                   "writer_model": writer_model, "llm_temperature": None},
        "initial_state": {}, "steps": [],
        "final_state": {
            "task": "x", "draft": "", "polished": "",
            "feedback": "审稿通过", "final_chapter": "风起了，他站在路口。",
            "round": 1, "next_agent": "done", "review_count": 0, "log": [],
        },
    }


def test_compare_new_records_show_model_lines(tmp_settings):
    """T10：两条新记录对比展示 model / writer_model 两行。"""
    from novel_agent.storage import save_run
    save_run(_new_format_record("run_new_a", "kimi-k3"), tmp_settings)
    save_run(_new_format_record("run_new_b", "glm-5.2"), tmp_settings)
    lines = []
    compare("run_new_a", "run_new_b", tmp_settings, out=lines.append)
    text = "\n".join(lines)
    assert "glm-5.2" in text  # model 行
    assert "kimi-k3" in text  # writer_model 行


def test_compare_mixed_old_new_records(sample_run, tmp_settings):
    """T10：新旧记录混排对比不崩；旧记录缺 writer_model 时打印 None。"""
    from novel_agent.storage import save_run
    save_run(_new_format_record("run_new_c", "kimi-k3"), tmp_settings)
    lines = []
    compare(sample_run, "run_new_c", tmp_settings, out=lines.append)
    text = "\n".join(lines)
    assert "A/B 对比" in text
    assert "kimi-k3" in text


def test_compare_old_records_skip_writer_model_line(sample_run, tmp_settings):
    """T10：两条旧记录（均无 writer_model）对比时跳过 writer_model 行。"""
    from novel_agent.storage import save_run
    record_b = {
        "run_id": "run_old_b", "task": "写第5章：异乡风起", "timestamp": "",
        "config": {"model": "glm-5.2", "temperature": 0.5},
        "initial_state": {}, "steps": [],
        "final_state": {
            "task": "x", "draft": "", "polished": "",
            "feedback": "审稿通过", "final_chapter": "小镇的雨刚歇。",
            "round": 1, "next_agent": "done", "review_count": 0, "log": [],
        },
    }
    save_run(record_b, tmp_settings)
    lines = []
    compare(sample_run, "run_old_b", tmp_settings, out=lines.append)
    text = "\n".join(lines)
    assert "writer_model" not in text


def test_compare_with_rules_shows_word_lines(sample_run, tmp_settings):
    """T9：规则配置后展示 含'许风' 与 含'风次数' 行 + AI 味浓度行。"""
    from novel_agent.storage import save_run
    _write_rules(tmp_settings, forbidden=["许风"], intent_words=["风"])
    save_run(_new_format_record("run_rule_b", "glm-5.2"), tmp_settings)
    lines = []
    compare(sample_run, "run_rule_b", tmp_settings, out=lines.append)
    text = "\n".join(lines)
    assert "含许风" in text
    assert "含风次数" in text
    assert "AI味浓度" in text


def test_compare_without_rules_shows_ai_line_only(sample_run, tmp_settings):
    """T9 Z1：规则未配置 -> 无规则词行，AI 味浓度行仍展示（旧记录混排不崩）。"""
    from novel_agent.storage import save_run
    save_run(_new_format_record("run_norule_b", "glm-5.2"), tmp_settings)
    lines = []
    compare(sample_run, "run_norule_b", tmp_settings, out=lines.append)
    text = "\n".join(lines)
    assert "含许风" not in text
    assert "含风次数" not in text
    assert "AI味浓度" in text  # 无规则/无基准也现算（降级路径），行必出


def test_compare_ai_flavor_values_differ(sample_run, tmp_settings):
    """T9：AI 味双方现算且区分度可见（黑名单重稿 vs 普通稿分数不同）。"""
    from novel_agent.storage import save_run
    _write_rules(tmp_settings)  # 先建目录 + 占位规则
    (tmp_settings.novel_path / "质量规则.json").write_text(
        json.dumps({"blacklist": ["缓缓地"]}), encoding="utf-8")
    record_b = {
        "run_id": "run_ai_b", "task": "x", "timestamp": "", "config": {},
        "initial_state": {}, "steps": [],
        "final_state": {
            "task": "x", "draft": "", "polished": "",
            "feedback": "审稿通过", "final_chapter": "他缓缓地走。风缓缓地停。夜缓缓地深。",
            "round": 1, "next_agent": "done", "review_count": 0, "log": [],
        },
    }
    save_run(record_b, tmp_settings)
    lines = []
    compare(sample_run, "run_ai_b", tmp_settings, out=lines.append)
    ai_lines = [ln for ln in lines if "AI味浓度" in ln]
    assert ai_lines, "AI 味浓度行必须输出"
    # B 黑名单命中密度高 -> AI 味分高于 A
    row = ai_lines[0]
    a_val = int(row[14:].split()[0])
    b_val = int(row.split()[-1])
    assert b_val > a_val


# ---------- T10：回测门禁（A35）----------
def _write_gate_rules(tmp_settings, threshold=3.5):
    """写含 eval_gate 的质量规则（weights 单维连贯性，便于手算加权分）。"""
    novel = tmp_settings.novel_path
    novel.mkdir(parents=True, exist_ok=True)
    (novel / "质量规则.json").write_text(json.dumps({
        "eval_gate": {"enabled": True, "threshold": threshold,
                      "weights": {"连贯性": 1.0}},
    }), encoding="utf-8")


def _bt_run(run_id, final_chapter="风起了。"):
    return {
        "run_id": run_id, "task": "x", "timestamp": "", "config": {},
        "initial_state": {}, "steps": [],
        "final_state": {
            "task": "x", "draft": "", "polished": "",
            "feedback": "审稿通过", "final_chapter": final_chapter,
            "round": 1, "next_agent": "done", "review_count": 0, "log": [],
        },
    }


def _spy_evaluate(monkeypatch, scores_by_run):
    """替换 harness.evaluate：按 run_id 返回固定分，记录调用。"""
    import novel_agent.harness as harness
    calls = []

    def fake(run_id, settings=None, llm=None, out=print, instruction=""):
        calls.append(run_id)
        return scores_by_run[run_id]

    monkeypatch.setattr(harness, "evaluate", fake)
    return calls


def test_backtest_distribution_and_thresholds(tmp_settings, monkeypatch):
    """分布低->高 + 三档候选阈值拦截面（3.0/3.5/4.0）run_id 清单。"""
    from novel_agent.storage import save_run
    _write_gate_rules(tmp_settings)
    save_run(_bt_run("run_bt_low"), tmp_settings)
    save_run(_bt_run("run_bt_high"), tmp_settings)
    _spy_evaluate(monkeypatch, {
        "run_bt_low": {"连贯性": 3, "人物一致性": 5},
        "run_bt_high": {"连贯性": 4, "人物一致性": 5},
    })
    lines = []
    result = backtest_gate(tmp_settings, out=lines.append)
    text = "\n".join(lines)
    assert result == {"run_bt_low": 3.0, "run_bt_high": 4.0}
    assert "加权分分布（低->高" in text
    assert "3.00  run_bt_low" in text and "4.00  run_bt_high" in text
    assert "threshold 3.0: 拦截 0 条" in text
    assert "threshold 3.5: 拦截 1 条 -> run_bt_low" in text
    # 4.00 >= 4.0 放行（>=threshold 过，与 _gate_ok 同口径），只拦 3.00
    assert "threshold 4.0: 拦截 1 条 -> run_bt_low" in text


def test_backtest_cache_hit_no_re_evaluate(tmp_settings, monkeypatch):
    """Z10：第二次回测命中缓存 -> evaluate 不再被调；缓存文件落盘。"""
    from novel_agent.storage import save_run
    _write_gate_rules(tmp_settings)
    save_run(_bt_run("run_bt_c1"), tmp_settings)
    calls = _spy_evaluate(monkeypatch, {"run_bt_c1": {"连贯性": 4}})
    backtest_gate(tmp_settings, out=lambda s: None)
    assert calls == ["run_bt_c1"]
    cache_path = tmp_settings.runs_path.parent / "gate_backtest.json"
    assert cache_path.is_file()
    # 第二次：全命中缓存，evaluate 零调用
    backtest_gate(tmp_settings, out=lambda s: None)
    assert calls == ["run_bt_c1"]


def test_backtest_skips_no_final_chapter(tmp_settings, monkeypatch):
    """无 final_chapter 的记录跳过（不烧评委、不进结果）。"""
    from novel_agent.storage import save_run
    _write_gate_rules(tmp_settings)
    empty = _bt_run("run_bt_empty", final_chapter="")
    save_run(empty, tmp_settings)
    save_run(_bt_run("run_bt_ok"), tmp_settings)
    calls = _spy_evaluate(monkeypatch, {"run_bt_ok": {"连贯性": 4}})
    lines = []
    result = backtest_gate(tmp_settings, out=lines.append)
    assert calls == ["run_bt_ok"]  # empty 未被评测
    assert "run_bt_empty" not in result
    assert result == {"run_bt_ok": 4.0}


def test_backtest_no_gate_config_returns_none(tmp_settings):
    """eval_gate 未配置（规则缺失/未启用）-> 提示并返回 None。"""
    _write_rules(tmp_settings, forbidden=["许风"])  # 有规则但无 eval_gate
    lines = []
    result = backtest_gate(tmp_settings, out=lines.append)
    assert result is None
    assert "未配置 eval_gate" in "\n".join(lines)


def test_backtest_limit_controls_count(tmp_settings, monkeypatch):
    """limit 只取最新的 N 条。"""
    from novel_agent.storage import save_run
    _write_gate_rules(tmp_settings)
    save_run(_bt_run("run_bt_m1"), tmp_settings)
    save_run(_bt_run("run_bt_m2"), tmp_settings)
    calls = _spy_evaluate(monkeypatch, {
        "run_bt_m1": {"连贯性": 4}, "run_bt_m2": {"连贯性": 3}})
    result = backtest_gate(tmp_settings, out=lambda s: None, limit=1)
    # list_runs 倒序（新在前）-> 只跑 run_bt_m2
    assert calls == ["run_bt_m2"]
    assert result == {"run_bt_m2": 3.0}


def test_backtest_cli_command_smoke(tmp_settings, monkeypatch, capsys):
    """cli 命令冒烟：回测门禁 <条数> 透传 limit，输出可见。"""
    from novel_agent import cli
    from novel_agent.storage import save_run
    _write_gate_rules(tmp_settings)
    save_run(_bt_run("run_bt_cli1"), tmp_settings)
    save_run(_bt_run("run_bt_cli2"), tmp_settings)
    _spy_evaluate(monkeypatch, {
        "run_bt_cli1": {"连贯性": 4}, "run_bt_cli2": {"连贯性": 3}})
    cli._do_backtest(["1"], tmp_settings)
    out = capsys.readouterr().out
    assert "门禁回测" in out
    assert "threshold 3.5: 拦截 1 条 -> run_bt_cli2" in out


def test_backtest_cli_bad_limit_hint(tmp_settings, capsys):
    """条数非整数 -> 用法提示，不跑。"""
    from novel_agent import cli
    cli._do_backtest(["abc"], tmp_settings)
    out = capsys.readouterr().out
    assert "用法：回测门禁" in out
