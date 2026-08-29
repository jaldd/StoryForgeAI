"""checker 模块测试（1.1 quality-gate T2 规则检查 + T3 AI 味量化）。"""
import dataclasses
import json
import math

import pytest

from novel_agent.checker import (
    Baseline,
    _freq_vector,
    ai_flavor_score,
    load_baseline,
    load_quality_rules,
    run_checks,
    split_sentences,
)


# ---------- load_quality_rules 三态 ----------
def test_load_rules_unset_subpath(tmp_settings):
    """subpath 留空 = 禁用 -> None（A23：不误伤）。"""
    s = type(tmp_settings)(
        ark_api_key="k", repo_root=tmp_settings.repo_root,
        novel_dir=tmp_settings.novel_dir, quality_rules_subpath="",
    )
    assert load_quality_rules(s) is None


def test_load_rules_missing_file(tmp_settings):
    """文件不存在 -> None（checker 与门禁全跳过）。"""
    assert load_quality_rules(tmp_settings) is None


def test_load_rules_invalid_json_fail_fast(tmp_settings, tmp_path):
    """非法 JSON -> RuntimeError 且报错含路径（A23 fail-fast）。"""
    f = tmp_path / "novel" / "质量规则.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("{not json", encoding="utf-8")
    with pytest.raises(RuntimeError, match="质量规则"):
        load_quality_rules(tmp_settings)


def test_load_rules_non_object_fail_fast(tmp_settings, tmp_path):
    """顶层非 dict -> RuntimeError（A23）。"""
    f = tmp_path / "novel" / "质量规则.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(RuntimeError, match="JSON 对象"):
        load_quality_rules(tmp_settings)


def test_load_rules_ok(tmp_settings, tmp_path):
    """正常 JSON -> dict。"""
    f = tmp_path / "novel" / "质量规则.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"blacklist": ["一丝"], "sentence": {"max_len": 80}}),
                 encoding="utf-8")
    assert load_quality_rules(tmp_settings) == {
        "blacklist": ["一丝"], "sentence": {"max_len": 80}}


# ---------- split_sentences ----------
def test_split_sentences_empty():
    assert split_sentences("") == []
    assert split_sentences("   \n  ") == []


def test_split_sentences_delims():
    """按中英标点与换行切分；连续标点不产生空句。"""
    assert split_sentences("你好。世界！") == ["你好", "世界"]
    assert split_sentences("他说：走了？？") == ["他说：走了"]
    assert split_sentences("第一行\n第二行；第三") == ["第一行", "第二行", "第三"]


def test_split_sentences_no_delim():
    """无标点单句原样返回（strip 后）。"""
    assert split_sentences("  一整句  ") == ["一整句"]


def test_split_sentences_quote_inner_terminator():
    """引号内的终止符同样切分（词法代理的已知简化，锁定行为）。"""
    assert split_sentences("「你好。」她说。") == ["「你好", "」她说"]


# ---------- 五项检查 ----------
CLEAN = "他推门进来。「你来了。」她说。\n窗外下着雨。\n他把伞收好。"


def test_check_blacklist_hit():
    text = "她嘴角勾起一抹弧度。他沉默地走了。"
    rules = {"blacklist": ["嘴角勾起一抹弧度", "眼眸"]}
    issues = run_checks(text, rules)
    assert len(issues) == 1
    assert issues[0]["problem"] == "黑名单词「嘴角勾起一抹弧度」出现1次"
    assert issues[0]["quote"] in text  # quote 是原文子串（D12 可定位）


def test_check_forbidden_name_hit():
    text = "许风站在门口。她看了他一眼。"
    rules = {"naming_redlines": {"forbidden": ["许风"]}}
    issues = run_checks(text, rules)
    assert len(issues) == 1
    assert "禁用称呼「许风」" in issues[0]["problem"]
    assert issues[0]["quote"] in text


def test_check_sentence_len_hit():
    long_sent = "这一句话" + "很长" * 50  # > 100 字无内部标点
    text = f"短句。{long_sent}。结尾。"
    rules = {"sentence": {"max_len": 80}}
    issues = run_checks(text, rules)
    assert len(issues) == 1
    assert "超长句" in issues[0]["problem"]
    assert issues[0]["quote"] in text


def test_check_monologue_hit():
    lines = ["他想起了很多事。"] + ["他又想了一件事。"] * 12 + ["「来了。」她说。"]
    text = "\n".join(lines)
    rules = {"monologue": {"max_lines": 12}}
    issues = run_checks(text, rules)
    assert len(issues) == 1
    assert "连续独白13行" in issues[0]["problem"]
    assert issues[0]["quote"] in text  # 首行前缀子串（D12 可定位）


def test_check_monologue_blank_lines_not_counted():
    """空行不计独白长度也不中断区间。"""
    text = "\n\n".join(["他在想事情。"] * 6)
    rules = {"monologue": {"max_lines": 5}}
    assert len(run_checks(text, rules)) == 1


def test_check_metaphor_rate_hit():
    sents = ["像风一样快。"] * 10 + ["他停下了。"] * 10
    text = "\n".join(sents)
    rules = {"metaphor": {"markers": ["像"], "max_rate": 0.2}}
    issues = run_checks(text, rules)
    assert len(issues) == 1
    assert issues[0]["quote"] == ""  # 全文属性，quote 置空（D12）
    assert "比喻密度" in issues[0]["problem"]
    assert "10/20句" in issues[0]["problem"]


def test_check_metaphor_adjacent_pairs_hit():
    sents = ["像风。", "像雨。", "他停了。"] + ["他走了。"] * 7
    text = "\n".join(sents)
    rules = {"metaphor": {"markers": ["像"], "max_rate": 0.9, "max_adjacent_pairs": 1}}
    issues = run_checks(text, rules)  # rate=0.2 未超 0.9；相邻对=1 对未超 1
    assert issues == []
    rules["metaphor"]["max_adjacent_pairs"] = 0  # 相邻对超 0 -> 违规
    issues = run_checks(text, rules)
    assert len(issues) == 1
    assert "相邻比喻对1对" in issues[0]["problem"]


def test_check_clean_text_no_issues():
    """干净文本零 issue（A22 不误伤）。"""
    assert run_checks(CLEAN, {
        "blacklist": ["一丝", "眼眸"],
        "naming_redlines": {"forbidden": ["许风"]},
        "sentence": {"max_len": 20},
        "monologue": {"max_lines": 3},
        "metaphor": {"markers": ["像", "仿佛"], "max_rate": 0.2},
    }) == []


def test_check_missing_rule_keys_skipped():
    """规则键缺失跳过对应项（A16/A21：只查配置了的）。"""
    text = "她一丝不苟。" + "长句" * 60 + "。"
    assert run_checks(text, {}) == []
    assert run_checks(text, None) == []
    # 只配黑名单：超长句不查
    issues = run_checks(text, {"blacklist": ["一丝"]})
    assert len(issues) == 1 and "黑名单" in issues[0]["problem"]


def test_check_multiple_blacklist_words():
    text = "她一丝微笑，眼眸清亮。"
    rules = {"blacklist": ["一丝", "眼眸"]}
    issues = run_checks(text, rules)
    assert len(issues) == 2
    assert all(i["quote"] in text for i in issues)


# ---------- AI 味量化（T3，A25-A27 / D6）----------
HUMAN = (
    "他沿着河岸走了很久。\n"
    "风从北边来，吹得人睁不开眼。\n"
    "狗在村口叫了两声，又停了。\n"
    "屋檐下的灯还亮着。\n"
    "她把门闩好，坐在灶前，往里添了两块柴。\n"
    "水开了。\n"
    "他蹲在门槛上抽烟，没说话。\n"
)
AI_TEXT = "她的眼眸里闪过一丝淡淡的哀伤，情绪如潮水般涌上心头。\n" * 20


def _mk_baseline(text: str, total_chars: int | None = None) -> Baseline:
    """由文本构造 Baseline（total_chars 可覆盖，用于阈值测试）。"""
    sents = split_sentences(text)
    lengths = [len(s) for s in sents]
    mean = sum(lengths) / len(lengths)
    std = math.sqrt(sum((n - mean) ** 2 for n in lengths) / len(lengths))
    return Baseline(
        total_chars=len(text) if total_chars is None else total_chars,
        sent_mean=mean, sent_std=std, freq=_freq_vector(text),
    )


def _score(text, rules, baseline):
    return ai_flavor_score(text, rules, baseline)


def test_ai_score_deterministic():
    """同输入两次调用结果完全相等（A25 纯函数、确定性）。"""
    base = _mk_baseline(HUMAN)
    rules = {"blacklist": ["眼眸", "一丝", "淡淡"],
             "ai_score": {"anchors": {"min_baseline_chars": 10}}}
    assert _score(AI_TEXT, rules, base) == _score(AI_TEXT, rules, base)
    assert _score(HUMAN, rules, base) == _score(HUMAN, rules, base)


def test_ai_score_discriminates_ai_vs_human():
    """区分度：黑名单词堆 AI 稿显著高于与基准同源的人稿。"""
    base = _mk_baseline(HUMAN)
    rules = {"blacklist": ["眼眸", "一丝", "淡淡"],
             "ai_score": {"anchors": {"min_baseline_chars": 10}}}
    ai = _score(AI_TEXT, rules, base)
    human = _score(HUMAN, rules, base)
    assert ai["score"] > 60
    assert human["score"] < 10
    assert all(0 <= v <= 100 for v in ai["components"].values())


def test_ai_score_degraded_without_baseline():
    """baseline=None -> degraded 且 freq 不可用；sentence 用内置 μ=35/σ=15（Z4）。"""
    rules = {"blacklist": ["眼眸"]}
    long_sents = "。".join(["字" * 35] * 10) + "。"   # 每句 35 字 -> 组件 0
    short_sents = "。".join(["字" * 5] * 10) + "。"    # 每句 5 字 -> |5-35|/15/2 -> 满格
    for text, expect in [(long_sents, 0), (short_sents, 100)]:
        res = _score(text, rules, None)
        assert res["degraded"] is True
        assert "freq" not in res["components"]
        assert res["components"]["sentence"] == expect


def test_ai_score_min_baseline_chars_configurable():
    """min_baseline_chars 可配覆盖：total_chars 低于阈值即降级（D6）。"""
    base = _mk_baseline(HUMAN, total_chars=10000)
    default_rules = {"blacklist": ["眼眸"]}
    assert _score(HUMAN, default_rules, base)["degraded"] is False  # 10000 不低于默认 10000
    strict_rules = {"blacklist": ["眼眸"],
                    "ai_score": {"anchors": {"min_baseline_chars": 20000}}}
    assert _score(HUMAN, strict_rules, base)["degraded"] is True


def test_ai_score_weights_renormalized():
    """blacklist 未配置 -> 权重重归一：sentence+freq 各满格时总分仍 100（D6）。"""
    base = _mk_baseline(HUMAN)
    rules = {"ai_score": {"anchors": {"min_baseline_chars": 10}}}  # 无 blacklist
    # 与基准字符近乎零交集 -> cos≈0 -> freq 满格；20 字长句远超 μ+2σ -> sentence 满格
    alien = "。".join(["哦" * 20] * 5) + "。"
    res = _score(alien, rules, base)
    assert "blacklist" not in res["components"]
    assert res["components"]["freq"] == 100
    assert res["score"] == 100  # 不重归一的话会得 0.3*100+0.3*100=60


def test_ai_score_blacklist_density_component():
    """blacklist 密度满格（3 次/千字锚点）；干净文本组件 0。"""
    base = _mk_baseline(HUMAN)
    rules = {"blacklist": ["眼眸"],
             "ai_score": {"anchors": {"min_baseline_chars": 10}}}
    dirty = "眼眸眼眸眼眸。"  # 3 次 / 7 字 -> 远超锚点 -> 100
    assert _score(dirty, rules, base)["components"]["blacklist"] == 100
    assert _score(HUMAN, rules, base)["components"]["blacklist"] == 0


def test_ai_score_empty_text_zero():
    """空文本 -> 无可用组件 -> 0 分不崩。"""
    res = _score("", {"blacklist": ["眼眸"]}, _mk_baseline(HUMAN))
    assert res["score"] == 0 and res["components"] == {}


# ---------- load_baseline（T3）----------
def _write(tmp_path, rel: str, content: str):
    f = tmp_path / "novel" / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content, encoding="utf-8")
    return f


def test_load_baseline_combines_exemplar_and_human(tmp_settings, tmp_path):
    """exemplar 目录全量 + 人工正文目录（Z8）。"""
    _write(tmp_path, "文风基准/a.md", "他走了很久。风停了。")
    _write(tmp_path, "文风基准/b.txt", "她回来了。")
    _write(tmp_path, "正文/新/1.md", "水开了。")
    _write(tmp_path, "文风基准/c.json", "不该被读取")
    base = load_baseline(tmp_settings)
    assert base is not None
    full = "他走了很久。风停了。\n\n她回来了。\n\n水开了。"  # \n\n 只在文件之间
    assert base.total_chars == len(full)
    sents = split_sentences(full)
    lengths = [len(s) for s in sents]
    assert base.sent_mean == sum(lengths) / len(lengths)
    assert base.freq == _freq_vector(full)


def test_load_baseline_empty_corpus_returns_none(tmp_settings, tmp_path):
    """目录存在但无 txt/md 语料 -> None。"""
    _write(tmp_path, "文风基准/a.json", "x")
    assert load_baseline(tmp_settings) is None


def test_load_baseline_missing_dirs_returns_none(tmp_settings):
    """目录不存在 -> None（不误伤）。"""
    assert load_baseline(tmp_settings) is None


def test_load_baseline_human_text_empty_reads_exemplar_only(tmp_settings, tmp_path):
    """human_text_subpath 留空 -> 只读 exemplar（不误扫 novel 根目录）。"""
    _write(tmp_path, "文风基准/a.md", "他走了很久。风停了。")
    _write(tmp_path, "正文/新/ignored.md", "这段不应计入。")
    s = dataclasses.replace(tmp_settings, human_text_subpath="")
    base = load_baseline(s)
    assert base is not None
    full = "他走了很久。风停了。"
    assert base.total_chars == len(full)
