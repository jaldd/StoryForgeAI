"""checker 模块测试（1.1 quality-gate T2 规则检查 + T3 AI 味量化）。"""
import dataclasses
import json
import math
from pathlib import Path

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


def test_check_monologue_straight_quote_breaks_run():
    """直引号 " 对话行同样中断独白区间（真实正文用直引号，Z 修复）。

    两段各 3 行 + 中间直引号对话：上限 5 行，识别直引号则两段各 3 行不
    命中；旧代码不识别直引号 -> 连成 7 行命中。
    """
    lines = ["他想了想。"] * 3 + ['"你来了。"她说。'] + ["他又想了想。"] * 3
    text = "\n".join(lines)
    rules = {"monologue": {"max_lines": 5}}
    assert run_checks(text, rules) == []


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
    _write(tmp_path, "正文/1.md", "水开了。")
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
    _write(tmp_path, "正文/ignored.md", "这段不应计入。")
    s = dataclasses.replace(tmp_settings, human_text_subpath="")
    base = load_baseline(s)
    assert base is not None
    full = "他走了很久。风停了。"
    assert base.total_chars == len(full)


# ---------- 1.7 跨章指纹（style-repeat T1：extract/normalize/load/compile）----------
from novel_agent.checker import (
    compile_syntax_patterns,
    extract_ending,
    load_recent_endings,
    normalize_ending,
    run_cross_checks,
    scan_style_report,
)


def test_extract_ending_basic():
    assert extract_ending("第一段。\n\n第二段。\n") == "第二段。"


def test_extract_ending_skips_separator_and_heading():
    """末行是分隔线/标题行时向上找正文（C2）。"""
    assert extract_ending("正文。\n\n---\n") == "正文。"
    assert extract_ending("正文。\n\n***\n\n## 尾注\n") == "正文。"
    assert extract_ending("正文。\n\n# 后记\n") == "正文。"


def test_extract_ending_quote_line():
    """引号行也是正文（对话收尾常见）。"""
    assert extract_ending("他走了。\n\n「风很轻。」") == "「风很轻。」"


def test_extract_ending_empty():
    assert extract_ending("") == ""
    assert extract_ending("\n\n---\n\n# 标题\n") == ""


def test_normalize_ending_strips_punct():
    assert normalize_ending("风很轻。") == "风很轻"
    assert normalize_ending("风很轻。。。") == "风很轻"
    assert normalize_ending("风很轻？！") == "风很轻"
    # 右引号剥掉、左引号保留（对话收尾与叙述收尾是不同形态）
    assert normalize_ending("「风很轻。」") == "「风很轻"
    assert normalize_ending("  风很轻  ") == "风很轻"
    assert normalize_ending("嗯。") == "嗯"


def test_normalize_ending_equality():
    """归一化后相等 = 同一收束句（C2 口径）。"""
    assert normalize_ending("风很轻。") == normalize_ending("风很轻")


def _mk_chapter(root, rel, ending):
    f = root / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(f"开头。\n\n中间。\n\n{ending}\n", encoding="utf-8")
    return f


def test_load_recent_endings_tail_lookback(tmp_path):
    """按章序取尾部 lookback 个（C7）。"""
    root = tmp_path / "正文"
    for i in range(1, 6):
        _mk_chapter(root, f"第一卷-{i:02d}.md", f"结尾{i}")
    endings = load_recent_endings(root, lookback=3)
    assert endings == ["结尾3", "结尾4", "结尾5"]


def test_load_recent_endings_cross_volume_order(tmp_path):
    """跨卷章序（Z7）：中文数字卷名字典序陷阱（一<三<二）必须被解析纠正。"""
    root = tmp_path / "正文"
    _mk_chapter(root, "第三卷/卷三-01.md", "三卷一章")
    _mk_chapter(root, "第一卷/卷一-01.md", "一卷一章")
    _mk_chapter(root, "第一卷/卷一-02.md", "一卷二章")
    _mk_chapter(root, "第二卷/卷二-01.md", "二卷一章")
    endings = load_recent_endings(root, lookback=10)
    assert endings == ["一卷一章", "一卷二章", "二卷一章", "三卷一章"]


def test_load_recent_endings_cn_volume_combination(tmp_path):
    """中文数字组合（「二十三」）与阿拉伯数字卷名（Z7 三态）。"""
    root = tmp_path / "正文"
    _mk_chapter(root, "第23卷/a-01.md", "二十三卷")
    _mk_chapter(root, "第二十三卷/b-01.md", "二十三卷中文")
    _mk_chapter(root, "第9卷/c-01.md", "九卷")
    endings = load_recent_endings(root, lookback=10)
    assert endings == ["九卷", "二十三卷", "二十三卷中文"]


def test_load_recent_endings_unparseable_falls_back(tmp_path):
    """不可解析卷名回退字典序且排在可解析之后（Z7）。"""
    root = tmp_path / "正文"
    _mk_chapter(root, "杂记/x-01.md", "杂记结尾")
    _mk_chapter(root, "第一卷/卷一-01.md", "一卷结尾")
    endings = load_recent_endings(root, lookback=10)
    assert endings == ["一卷结尾", "杂记结尾"]


def test_load_recent_endings_exclude(tmp_path):
    """exclude 排除被处理文件自身（C18 防自比）。"""
    root = tmp_path / "正文"
    f1 = _mk_chapter(root, "第一卷-01.md", "结尾一")
    f2 = _mk_chapter(root, "第一卷-02.md", "结尾二")
    endings = load_recent_endings(root, lookback=10, exclude=f2)
    assert endings == ["结尾一"]
    # exclude 相对路径同样生效
    endings2 = load_recent_endings(root, lookback=10, exclude=Path("第一卷-02.md"))
    assert endings2 == ["结尾一"]


def test_load_recent_endings_empty_and_missing(tmp_path):
    assert load_recent_endings(tmp_path / "不存在", lookback=10) == []
    root = tmp_path / "正文"
    root.mkdir()
    assert load_recent_endings(root, lookback=10) == []
    assert load_recent_endings(root, lookback=0) == []


def test_load_recent_endings_ignores_hidden(tmp_path):
    """点前缀目录与 .agent 不进参照集（Z6 同款）。"""
    root = tmp_path / "正文"
    _mk_chapter(root, ".agent/run-01.md", "隐藏结尾")
    _mk_chapter(root, ".drafts/x-01.md", "草稿结尾")
    _mk_chapter(root, "第一卷-01.md", "正常结尾")
    assert load_recent_endings(root, lookback=10) == ["正常结尾"]


def test_compile_syntax_patterns_ok():
    rules = {"syntax_patterns": {"patterns": ["像一个人", "不是[^，。]{1,12}"], "max_per_chapter": 1}}
    pats = compile_syntax_patterns(rules)
    assert len(pats) == 2


def test_compile_syntax_patterns_missing_key():
    assert compile_syntax_patterns({}) == []
    assert compile_syntax_patterns({"syntax_patterns": {}}) == []


def test_compile_syntax_patterns_invalid_regex():
    with pytest.raises(RuntimeError, match="合法正则"):
        compile_syntax_patterns({"syntax_patterns": {"patterns": ["(["]}})


def test_compile_syntax_patterns_zero_width_rejected():
    """可零宽匹配（pat.search("") 命中）加载期拒收（C4/Z2）。"""
    with pytest.raises(RuntimeError, match="零宽"):
        compile_syntax_patterns({"syntax_patterns": {"patterns": ["(像|仿佛)?"]}})


# ---------- 1.7 run_cross_checks（style-repeat T2）----------
END_RULES = {"ending": {"lookback": 10, "max_repeat": 2, "min_chars": 3}}
SYN_RULES = {"syntax_patterns": {"patterns": ["像一个人"], "max_per_chapter": 1}}


def test_cross_ending_hit():
    """参照窗内同结尾已 2 次 + 本章 = 3 > max_repeat 2 -> issue（C1）。"""
    text = "开头。\n\n风很轻。"
    issues = run_cross_checks(text, ["别的", "风很轻", "风很轻"], END_RULES)
    assert len(issues) == 1
    assert issues[0]["quote"] == "风很轻。"  # 原文子串（可定位）
    assert issues[0]["quote"] in text
    assert "收束句复读" in issues[0]["problem"]


def test_cross_ending_at_threshold_no_hit():
    """次数恰等于 max_repeat（含本章）不报（不误伤）。"""
    text = "开头。\n\n风很轻。"
    assert run_cross_checks(text, ["别的", "风很轻"], END_RULES) == []


def test_cross_ending_min_chars_exempt():
    """归一化后 < min_chars 的超短结尾豁免（「嗯。」）。"""
    text = "开头。\n\n嗯。"
    assert run_cross_checks(text, ["嗯", "嗯"], END_RULES) == []


def test_cross_ending_none_endings_skip():
    """recent_endings 为 None/[] -> ending 项跳过（C5）。"""
    text = "开头。\n\n风很轻。"
    assert run_cross_checks(text, None, END_RULES) == []
    assert run_cross_checks(text, [], END_RULES) == []


def test_cross_syntax_hit():
    """pattern 命中 2 次 > 配额 1 -> issue，quote 为原文子串（C3）。"""
    text = "他像一个人立在风里。\n\n她像一个人坐在门口。"
    issues = run_cross_checks(text, None, SYN_RULES)
    assert len(issues) == 1
    assert "句式模板超配额" in issues[0]["problem"]
    assert issues[0]["quote"] in text


def test_cross_syntax_at_quota_no_hit():
    text = "他像一个人立在风里。"
    assert run_cross_checks(text, None, SYN_RULES) == []


def test_cross_syntax_with_capture_group():
    """含捕获组的 pattern 用 group(0) 定位（Z5 finditer 统一口径）。"""
    rules = {"syntax_patterns": {"patterns": ["不是[^，。]{1,12}[。，][^。]{0,4}是"], "max_per_chapter": 1}}
    text = "这不是愤怒，是疲惫。\n\n那不是拒绝，是恐惧。"
    issues = run_cross_checks(text, None, rules)
    assert len(issues) == 1
    assert issues[0]["quote"] in text


def test_cross_syntax_cross_sentence_quote_locatable():
    """跨句命中（含句号+换行）quote 仍须落在单句内（真车 refine_20260919_201749
    4 轮不收敛的根因回归：group(0)='不是拨。\\n\\n是' 不落在任何单句，
    旧定位兜底返回命中串本身 -> fixer 段落定位失败 -> 整文降级死循环）。"""
    rules = {"syntax_patterns": {"patterns": ["不是[^，。]{1,12}[。，][^。]{0,4}是"], "max_per_chapter": 1}}
    text = (
        "开头一句。\n\n"
        "那年那天，不是拨。\n\n"
        "是他太想让它好。\n\n"
        "他不是不敢去。\n\n"
        "是那股劲先按住了他。\n\n"
        "结尾句。"
    )
    issues = run_cross_checks(text, None, rules)
    assert len(issues) == 1
    q = issues[0]["quote"]
    assert q in text                       # 原文子串（fixer 可定位）
    assert "\n" not in q                   # 单句（不含段落边界 -> 段落级修复可达）
    assert "不是" in q                     # 指向首个命中所在句


def test_cross_both_keys_missing():
    """两键全缺 -> []（C16 双降级）。"""
    text = "开头。\n\n风很轻。"
    assert run_cross_checks(text, ["风很轻"], {}) == []
    assert run_cross_checks(text, ["风很轻"], {"blacklist": ["x"]}) == []


def test_cross_issue_shape_same_as_run_checks():
    """issue 与 run_checks 同构 {quote, problem, fix}（C6）。"""
    issues = run_cross_checks("开头。\n\n风很轻。", ["风很轻", "风很轻"], END_RULES)
    assert set(issues[0].keys()) == {"quote", "problem", "fix"}


# ---------- 1.9 scan_style_report（style-repeat T5）----------
def test_scan_style_report_full(tmp_path):
    """三节报告形状与数值（C13）：复读榜/句式榜/字数分布。"""
    root = tmp_path / "正文"
    for i in range(1, 4):
        _mk_chapter(root, f"第一卷/卷一-{i:02d}.md", "风很轻。")
    _mk_chapter(root, "第二卷/卷二-01.md", "别的结尾。")
    (root / "第一卷/卷一-01.md").write_text(
        "他像一个人立在风里。\n\n像一个人坐着。\n\n风很轻。\n", encoding="utf-8")
    rules = {**END_RULES, **SYN_RULES}
    r = scan_style_report(root, rules)
    assert r["files_scanned"] == 4
    # 复读榜：风很轻 3 次（>= max_repeat+1=3）上榜，附文件清单
    assert len(r["endings"]) == 1
    assert r["endings"][0]["ending"] == "风很轻"
    assert r["endings"][0]["count"] == 3
    assert len(r["endings"][0]["files"]) == 3
    # 句式榜：像一个人 只在卷一-01 命中 2 次（其余章无该模板）
    assert len(r["patterns"]) == 1
    assert r["patterns"][0]["total"] == 2
    assert r["patterns"][0]["over"] == [{"file": "第一卷/卷一-01.md", "count": 2}]
    # 字数分布：两卷分组 + 全局行
    groups = [row["group"] for row in r["sizes"]]
    assert groups == ["第一卷", "第二卷", "全局"]
    vol1 = r["sizes"][0]
    assert vol1["n"] == 3 and vol1["min"] <= vol1["max"] and vol1["mean"] > 0


def test_scan_style_report_cv(tmp_path):
    """字数完全一致 -> cv=0（实测「45 章全落 5.8-6.0KB」的量化口径）。"""
    root = tmp_path / "正文"
    root.mkdir(parents=True)
    for i in range(1, 4):
        (root / f"第一卷-{i:02d}.md").write_text("x" * 100, encoding="utf-8")
    r = scan_style_report(root, {})
    assert r["sizes"][0]["cv"] == 0.0
    assert r["sizes"][0]["n"] == 3


def test_scan_style_report_empty_and_missing(tmp_path):
    """目录不存在/无文件 -> files_scanned=0（C15）。"""
    assert scan_style_report(tmp_path / "不存在", {})["files_scanned"] == 0
    empty = tmp_path / "空"
    empty.mkdir()
    assert scan_style_report(empty, {})["files_scanned"] == 0


def test_scan_style_report_ignores_hidden(tmp_path):
    """忽略 .agent 与点前缀目录（Z6）。"""
    root = tmp_path / "正文"
    _mk_chapter(root, ".agent/x.md", "隐藏")
    _mk_chapter(root, "第一卷-01.md", "正常。")
    r = scan_style_report(root, {})
    assert r["files_scanned"] == 1


def test_scan_style_report_rules_missing_sections_empty(tmp_path):
    """规则键缺失 -> 对应节为空列表（不误伤）。"""
    root = tmp_path / "正文"
    _mk_chapter(root, "第一卷-01.md", "风很轻。")
    r = scan_style_report(root, {})
    assert r["endings"] == [] and r["patterns"] == []
