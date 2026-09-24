"""0.5 exemplar 语料目录化测试：目录级加载 / 单文件兼容 / 超限截断 / 状态命令清单。

1.1 quality-gate T5：reviewer 八维 schema 演进与 fixer prompt 构造。
"""
from __future__ import annotations

from pathlib import Path

from novel_agent import cli
from novel_agent.prompts import (
    EXEMPLAR_MAX_CHARS,
    build_style_taboos,
    deai_system,
    deai_user,
    exemplar_info,
    fixer_system,
    fixer_user,
    fixer_whole_user,
    load_exemplar,
    load_recent_human,
    reviewer_system,
    writer_system,
)


def _quiet(*_a, **_kw):
    """吞掉 progress 日志的替身。"""


# ---------- load_exemplar：目录级 ----------
def test_load_exemplar_dir_reads_all_sorted(tmp_path):
    """目录下多个语料文件全部读入，按文件名排序拼接；非 txt/md 后缀忽略。"""
    d = tmp_path / "文风基准"
    d.mkdir()
    (d / "2.txt").write_text("第二", encoding="utf-8")
    (d / "1.md").write_text("第一", encoding="utf-8")
    (d / "插图.png").write_bytes(b"\x89PNG")  # 非语料后缀，不应读入
    assert load_exemplar(d, progress=_quiet) == "第一\n\n第二"


def test_load_exemplar_single_file(tmp_path):
    """单文件路径向后兼容：就读它自己。"""
    f = tmp_path / "基准.txt"
    f.write_text("单文件正文", encoding="utf-8")
    assert load_exemplar(f) == "单文件正文"
    assert exemplar_info(f) == (1, len("单文件正文"))


def test_load_exemplar_missing_returns_empty(tmp_path):
    """路径不存在返回空串（写作指令/铁律同款约定）。"""
    assert load_exemplar(tmp_path / "不存在", progress=_quiet) == ""


def test_load_exemplar_truncates_with_log(tmp_path):
    """超限按文件序截断（排序靠前优先保住），progress 打日志说明保留情况。"""
    d = tmp_path / "文风基准"
    d.mkdir()
    (d / "1.txt").write_text("甲" * 20, encoding="utf-8")
    (d / "2.txt").write_text("乙" * 20, encoding="utf-8")
    logs: list[str] = []
    text = load_exemplar(d, max_chars=25, progress=logs.append)
    assert len(text) == 25
    assert text.startswith("甲" * 20)  # 第一个文件完整保留
    assert "乙" * 3 in text            # 第二个文件只装进剩余预算
    assert len("".join(logs)) > 0 and any("超过注入上限" in m and "截断" in m for m in logs)


def test_load_exemplar_default_limit(tmp_path):
    """默认上限 EXEMPLAR_MAX_CHARS 生效（不传 max_chars 时也截断）。"""
    assert EXEMPLAR_MAX_CHARS == 30000
    d = tmp_path / "文风基准"
    d.mkdir()
    (d / "1.txt").write_text("丙" * (EXEMPLAR_MAX_CHARS + 100), encoding="utf-8")
    text = load_exemplar(d, progress=_quiet)
    assert len(text) == EXEMPLAR_MAX_CHARS


def test_load_exemplar_skips_unreadable_file(tmp_path, monkeypatch):
    """单个文件读失败提示后跳过，不阻断其余语料。"""
    d = tmp_path / "文风基准"
    d.mkdir()
    (d / "1.txt").write_text("甲" * 5, encoding="utf-8")
    (d / "2.txt").write_text("乙" * 5, encoding="utf-8")
    real_read = Path.read_text

    def fake_read(self, *a, **kw):
        if self.name == "2.txt":
            raise OSError("boom")
        return real_read(self, *a, **kw)

    monkeypatch.setattr(Path, "read_text", fake_read)
    logs: list[str] = []
    assert load_exemplar(d, progress=logs.append) == "甲" * 5
    assert any("跳过" in m for m in logs)


# ---------- exemplar-routing：only_files 过滤 ----------
def _mk_dir_with_usage(tmp_path):
    """带使用说明 + 两篇样文的目录（0.5b 目录结构）。"""
    d = tmp_path / "文风基准"
    d.mkdir()
    (d / "00-使用说明.md").write_text("使用说明全文", encoding="utf-8")
    (d / "1.txt").write_text("甲" * 5, encoding="utf-8")
    (d / "2.txt").write_text("乙" * 5, encoding="utf-8")
    return d


def test_load_exemplar_only_files_filters_and_orders(tmp_path):
    """A2：only_files 按清单序过滤（顺序遵 only_files，不按文件名排序）。"""
    d = _mk_dir_with_usage(tmp_path)
    text = load_exemplar(d, progress=_quiet, only_files=["2.txt", "1.txt"])
    # 使用说明仍作首块，样文按 only_files 序
    assert text == "使用说明全文\n\n" + "乙" * 5 + "\n\n" + "甲" * 5


def test_load_exemplar_only_files_skips_missing(tmp_path):
    """A4：only_files 中不存在的名字跳过并提示，其余照常。"""
    d = _mk_dir_with_usage(tmp_path)
    logs: list[str] = []
    text = load_exemplar(d, progress=logs.append, only_files=["99.txt", "1.txt"])
    assert text == "使用说明全文\n\n" + "甲" * 5
    assert any("99.txt" in m and "跳过" in m for m in logs)


def test_load_exemplar_only_files_empty_keeps_manifest(tmp_path):
    """only_files 过滤后样文为空：仍返回说明全文（说明照常注入）。"""
    d = _mk_dir_with_usage(tmp_path)
    text = load_exemplar(d, progress=_quiet, only_files=["不存在.txt"])
    assert text == "使用说明全文"


def test_load_exemplar_only_files_none_is_status_quo(tmp_path):
    """A1：only_files=None（默认）行为与现状完全一致。"""
    d = _mk_dir_with_usage(tmp_path)
    assert load_exemplar(d, progress=_quiet) == "使用说明全文\n\n" + "甲" * 5 + "\n\n" + "乙" * 5
    assert load_exemplar(d, progress=_quiet, only_files=None) == load_exemplar(d, progress=_quiet)


def test_load_exemplar_only_files_with_truncation(tmp_path):
    """A6：only_files 与截断叠加——超限时按（过滤后的）序截断。"""
    d = tmp_path / "文风基准"
    d.mkdir()
    (d / "00-使用说明.md").write_text("说明", encoding="utf-8")
    (d / "1.txt").write_text("甲" * 20, encoding="utf-8")
    (d / "2.txt").write_text("乙" * 20, encoding="utf-8")
    text = load_exemplar(d, max_chars=25, progress=_quiet, only_files=["2.txt", "1.txt"])
    # 说明(2)+分隔(2)+乙*20=24 装满预算；1.txt 的剩余预算为负，整体不进
    assert len(text) == 24
    assert text.startswith("说明\n\n" + "乙" * 20)


def test_tags_file_not_a_sample(tmp_path):
    """exemplar-routing：样文标签.md 是路由元数据，不算样文、不注入（含 info 统计）。"""
    d = tmp_path / "文风基准"
    d.mkdir()
    (d / "00-使用说明.md").write_text("使用说明", encoding="utf-8")
    (d / "1.txt").write_text("甲", encoding="utf-8")
    (d / "样文标签.md").write_text("# 样文标签\n\n- 1.txt: 天气感\n", encoding="utf-8")
    assert load_exemplar(d, progress=_quiet) == "使用说明\n\n甲"
    assert exemplar_info(d) == (1, 5)  # 1 篇样文（标签文件不计）


# ---------- 0.5b 精选清单（00-使用说明.md：说明全文注入 + 清单选样文） ----------
def test_manifest_selects_subset_in_list_order(tmp_path):
    """有清单：说明全文作首块 + 清单内样文（清单序即注入序）；说明不算样文。"""
    d = tmp_path / "文风基准"
    d.mkdir()
    (d / "1.txt").write_text("甲", encoding="utf-8")
    (d / "2.txt").write_text("乙", encoding="utf-8")
    (d / "3.txt").write_text("丙", encoding="utf-8")
    manifest = "## 使用说明\n给人看的喂法指导。\n\n## 注入清单\n- 3.txt（对话范本）\n- 1.txt\n"
    (d / "00-使用说明.md").write_text(manifest, encoding="utf-8")
    assert load_exemplar(d, progress=_quiet) == manifest + "\n\n丙\n\n甲"  # 清单序：3 先于 1
    assert exemplar_info(d) == (2, len(manifest) + 2)


def test_manifest_missing_or_no_list_falls_back_all(tmp_path):
    """无说明文件 -> 全量样文（0.5 现状）；有说明无清单节 -> 说明 + 全量样文。"""
    d = tmp_path / "文风基准"
    d.mkdir()
    (d / "1.txt").write_text("甲", encoding="utf-8")
    (d / "2.txt").write_text("乙", encoding="utf-8")
    assert load_exemplar(d, progress=_quiet) == "甲\n\n乙"  # 无说明文件

    manifest = "## 使用说明\n只有备注没有清单"
    (d / "00-使用说明.md").write_text(manifest, encoding="utf-8")
    assert load_exemplar(d, progress=_quiet) == manifest + "\n\n甲\n\n乙"  # 说明 + 全量
    assert exemplar_info(d) == (2, len(manifest) + 2)  # 甲+乙 各 1 字，分隔符不计


def test_manifest_unknown_name_warns_and_skips(tmp_path):
    """清单引用不存在的文件：progress 提示后跳过，其余正常注入。"""
    d = tmp_path / "文风基准"
    d.mkdir()
    (d / "1.txt").write_text("甲", encoding="utf-8")
    manifest = "## 注入清单\n- 1.txt\n- 不存在.txt\n"
    (d / "00-使用说明.md").write_text(manifest, encoding="utf-8")
    logs: list[str] = []
    assert load_exemplar(d, progress=logs.append) == manifest + "\n\n甲"
    assert any("不存在.txt" in m and "跳过" in m for m in logs)


def test_manifest_all_miss_falls_back_all(tmp_path):
    """清单全落空 -> 说明 + 全量样文兜底（不给空语料）。"""
    d = tmp_path / "文风基准"
    d.mkdir()
    (d / "1.txt").write_text("甲", encoding="utf-8")
    manifest = "## 注入清单\n- 忘了写什么.txt\n"
    (d / "00-使用说明.md").write_text(manifest, encoding="utf-8")
    assert load_exemplar(d, progress=_quiet) == manifest + "\n\n甲"


# ---------- exemplar_info ----------
def test_exemplar_info_counts(tmp_path):
    """清单返回 (文件数, 总字数)；路径不存在返回 (0, 0)。"""
    d = tmp_path / "文风基准"
    d.mkdir()
    (d / "1.txt").write_text("甲" * 10, encoding="utf-8")
    (d / "2.md").write_text("乙" * 4, encoding="utf-8")
    (d / "3.jpg").write_bytes(b"x")  # 非语料不计
    assert exemplar_info(d) == (2, 14)
    assert exemplar_info(tmp_path / "不存在") == (0, 0)


# ---------- CLI 集成 ----------
def test_status_shows_exemplar_info(tmp_settings, capsys):
    """状态命令输出语料清单（文件数/总字数，截断前的真实体量）；无语料时不打印该行。"""
    cli._do_status(tmp_settings)  # 目录不存在
    assert "文风基准" not in capsys.readouterr().out

    d = tmp_settings.exemplar_full
    d.mkdir(parents=True)
    (d / "1.txt").write_text("甲" * 10, encoding="utf-8")
    (d / "2.txt").write_text("乙" * 5, encoding="utf-8")
    cli._do_status(tmp_settings)
    out = capsys.readouterr().out
    assert "文风基准：2 个文件，共 15 字" in out
    assert str(d) in out


def test_build_agent_loads_exemplar_dir(tmp_settings, monkeypatch):
    """_build_agent 对目录级 exemplar 生效：目录内容拼接后注入 agent。"""
    d = tmp_settings.exemplar_full
    d.mkdir(parents=True)
    (d / "1.txt").write_text("甲", encoding="utf-8")
    (d / "2.txt").write_text("乙", encoding="utf-8")

    captured: dict = {}

    class _Agent:
        def __init__(self, **kw):
            captured.update(kw)

    monkeypatch.setattr(cli, "LLMClient", lambda settings=None, profile=None: None)  # 0.7：_build_agent 注入 profile
    monkeypatch.setattr(cli, "RAGStore", lambda settings=None: None)
    monkeypatch.setattr(cli, "NovelAgent", _Agent)
    cli._build_agent(tmp_settings)
    assert captured["exemplar"] == "甲\n\n乙"


# ---------- reviewer schema 演进与 fixer prompt（1.1 T5）----------
def test_reviewer_system_nine_dimensions_and_schema():
    """reviewer_system 含九维名（8 既有 + 事件锚）、scores 示例含事件锚键；旧三键保留（D4/E7/E14）。"""
    sys_prompt = reviewer_system("测试小说", "")
    for dim in ["人物一致性", "文风一致性", "剧情连贯性", "时间线一致性",
                "环境一致性", "伏笔一致性", "比喻密度", "视角越界", "事件锚"]:
        assert dim in sys_prompt, dim
    assert '"事件锚": 4' in sys_prompt  # scores 示例 JSON 增键（E7）
    assert "删掉天气描写、身体感受、心理描写" in sys_prompt  # 第 9 维文案（design §3.3）
    assert '"scores"' in sys_prompt
    assert '"issues"' in sys_prompt
    for key in ("quote", "problem", "fix"):
        assert f'"{key}"' in sys_prompt
    # D4 兼容：pass/reason/issues 三键保留
    assert '"pass"' in sys_prompt and '"reason"' in sys_prompt


def test_reviewer_system_rules_and_instruction_injected():
    """铁律与写作指令照旧注入（维度演进不动注入位）。"""
    sys_prompt = reviewer_system("测试小说", "", instruction="指令内容", rules="铁律内容")
    assert "铁律内容" in sys_prompt
    assert "指令内容" in sys_prompt


def test_fixer_system_contract():
    """fixer_system：修稿师定位 + 只改问题处铁律 + 【第N段·修复后】标记协议。"""
    sys_prompt = fixer_system("测试小说", rules="铁律内容")
    assert "修稿师" in sys_prompt
    assert "只改问题处" in sys_prompt
    assert "【第N段·修复后】" in sys_prompt
    assert "铁律内容" in sys_prompt


def test_fixer_user_renders_spans_and_issues():
    """fixer_user：段号/上下文/原文/意见全渲染；空上下文不出现占位块。"""
    spans_data = [
        {"no": 3, "before": "上文。", "text": "第三段原文。", "after": "下文。",
         "issues": [{"quote": "第三段原文", "problem": "称呼错误", "fix": "改为林晚"}]},
        {"no": 7, "before": "", "text": "第七段原文。", "after": "",
         "issues": [{"quote": "第七段原文", "problem": "超长句", "fix": "拆分"}]},
    ]
    user_prompt = fixer_user(spans_data)
    assert "第3段" in user_prompt and "第7段" in user_prompt
    assert "第三段原文。" in user_prompt and "第七段原文。" in user_prompt
    assert "上文。" in user_prompt and "下文。" in user_prompt
    assert "称呼错误" in user_prompt and "改为林晚" in user_prompt
    assert "超长句" in user_prompt and "拆分" in user_prompt
    # 第 7 段 before/after 均空 -> 其渲染区不含上下文占位块
    seg7 = user_prompt.split("第7段 ━━")[1]
    assert "【上文" not in seg7 and "【下文" not in seg7


def test_fixer_whole_user_renders_text_and_issues():
    """fixer_whole_user：原稿全文 + 意见清单逐条渲染（A12 整文降级）。"""
    issues = [
        {"quote": "", "problem": "比喻密度：10/20句含标记", "fix": "删减比喻"},
        {"quote": "", "problem": "独白过长", "fix": "压缩"},
    ]
    user_prompt = fixer_whole_user("原稿全文内容。", issues)
    assert "原稿全文内容。" in user_prompt
    assert "比喻密度" in user_prompt and "删减比喻" in user_prompt
    assert "独白过长" in user_prompt and "压缩" in user_prompt


def test_build_agent_no_tag_file_no_route(tmp_settings, monkeypatch):
    """exemplar-routing A1：标签文件不存在时 _build_agent 不路由，行为与现状一致。

    _route_exemplar_files 在标签为空时直接 (None, None)，不构造 LLMClient。
    """
    called = []

    def _boom(*a, **kw):
        called.append(1)
        raise AssertionError("不应发起路由调用")

    monkeypatch.setattr(cli, "LLMClient", _boom)
    only, route = cli._route_exemplar_files(tmp_settings, "写第1章：风起")
    assert only is None and route is None
    assert not called


# ---------- 1.5 滚动注入（style-loop T2）----------
def test_load_recent_human_takes_tail_n(tmp_path):
    """B3/Z1：按文件名序取尾部 N 个（4 文件取 3 = 后 3 个），章间 \\n\\n 拼接。"""
    d = tmp_path / "正文"
    d.mkdir()
    (d / "第01章-风起.txt").write_text("第一章正文", encoding="utf-8")
    (d / "第02章-夜行.txt").write_text("第二章正文", encoding="utf-8")
    (d / "第03章-旧约.txt").write_text("第三章正文", encoding="utf-8")
    (d / "第04章-新雨.txt").write_text("第四章正文", encoding="utf-8")
    text = load_recent_human(d, n=3, progress=_quiet)
    assert text == "第二章正文\n\n第三章正文\n\n第四章正文"  # 最早一章被滚出窗口


def test_load_recent_human_truncates_each_file(tmp_path):
    """B4：逐文件截前 slice_chars（不是拼接后截断，每章都有头部内容）。"""
    d = tmp_path / "正文"
    d.mkdir()
    (d / "1.txt").write_text("甲" * 30, encoding="utf-8")
    (d / "2.txt").write_text("乙" * 30, encoding="utf-8")
    logs: list[str] = []
    text = load_recent_human(d, n=2, slice_chars=10, progress=logs.append)
    assert text == "甲" * 10 + "\n\n" + "乙" * 10
    assert any("超过单章注入上限" in m and "只注入前" in m for m in logs)  # 留痕不静默


def test_load_recent_human_degraded_states(tmp_path):
    """B2：n=0 / 目录不存在 / 空目录均返回空串，不报错（零误伤）。"""
    d = tmp_path / "正文"
    d.mkdir()
    (d / "1.txt").write_text("甲", encoding="utf-8")
    assert load_recent_human(d, n=0) == ""                      # 0 = 禁用
    assert load_recent_human(tmp_path / "不存在") == ""          # 目录不存在
    empty = tmp_path / "空目录"
    empty.mkdir()
    assert load_recent_human(empty, progress=_quiet) == ""      # 无语料文件


def test_load_recent_human_filters_suffix(tmp_path):
    """混合后缀过滤：只认 .txt/.md。"""
    d = tmp_path / "正文"
    d.mkdir()
    (d / "1.txt").write_text("甲", encoding="utf-8")
    (d / "2.md").write_text("乙", encoding="utf-8")
    (d / "3.jpg").write_bytes(b"x")
    assert load_recent_human(d, n=5, progress=_quiet) == "甲\n\n乙"


def test_load_recent_human_skips_unreadable_file(tmp_path, monkeypatch):
    """不可读文件提示后跳过，窗口照常推进（load_exemplar 同款纪律）。"""
    d = tmp_path / "正文"
    d.mkdir()
    (d / "1.txt").write_text("甲" * 5, encoding="utf-8")
    (d / "2.txt").write_text("乙" * 5, encoding="utf-8")
    real_read = Path.read_text

    def fake_read(self, *a, **kw):
        if self.name == "1.txt":
            raise OSError("boom")
        return real_read(self, *a, **kw)

    monkeypatch.setattr(Path, "read_text", fake_read)
    logs: list[str] = []
    assert load_recent_human(d, n=2, progress=logs.append) == "乙" * 5
    assert any("跳过" in m and "1.txt" in m for m in logs)


# ---------- 1.5 writer prompt 注入（style-loop T3）----------
def test_writer_system_recent_human_block():
    """B8：recent_human 非空 -> 分节标题 + 防混淆文案；空串整块不占位（B18）。"""
    base = writer_system("测试小说", "", "范例")
    assert "近期人工正文" not in base  # 空串不占位，与现状逐字节一致
    with_block = writer_system("测试小说", "", "范例", recent_human="人工正文片段")
    assert "【近期人工正文】" in with_block
    assert "不是情节指令" in with_block
    assert "人工正文片段" in with_block
    assert with_block.startswith(base)  # 既有分节零改动，追加在风格范例之后


# ---------- 1.6 去 AI prompt（style-loop T4）----------
def test_deai_system_contract():
    """B11：人味重写师 + 情节不动铁律 + 风格指令四条 + 标记协议（D11 同协议）。"""
    sys_prompt = deai_system("测试小说", rules="铁律内容")
    assert "人味重写师" in sys_prompt
    assert "情节、人物人称、称呼、伏笔、段落结构" in sys_prompt
    for kw in ("短句为主", "克制", "不解释因果", "具体物象"):
        assert kw in sys_prompt, kw
    assert "【第N段·修复后】" in sys_prompt
    assert "铁律内容" in sys_prompt


def test_deai_user_renders_spans_and_issues():
    """B10：与 fixer_user 同构（段号/上下文/原文/意见全渲染），文案为人味重写。"""
    spans_data = [
        {"no": 3, "before": "上文。", "text": "第三段原文。", "after": "下文。",
         "issues": [{"quote": "第三段原文", "problem": "黑名单词「一丝」", "fix": "换成具体描写"}]},
        {"no": 7, "before": "", "text": "第七段原文。", "after": "",
         "issues": [{"quote": "第七段原文", "problem": "超长句", "fix": "拆分"}]},
    ]
    user_prompt = deai_user(spans_data)
    assert "第3段" in user_prompt and "第7段" in user_prompt
    assert "第三段原文。" in user_prompt and "第七段原文。" in user_prompt
    assert "上文。" in user_prompt and "下文。" in user_prompt
    assert "人味重写" in user_prompt
    assert "黑名单词" in user_prompt and "拆分" in user_prompt
    # 第 7 段 before/after 均空 -> 其渲染区不含上下文占位块
    seg7 = user_prompt.split("第7段 ━━")[1]
    assert "【上文" not in seg7 and "【下文" not in seg7


# ---------- 3.2 角色弧光抽取 prompt（character-arc T3）----------
def test_arc_system_contract():
    """C5/D2/D7：审计员角色 + 原名回报 + ≤6 软上限 + changed 语义 + 自包含要求。"""
    from novel_agent.prompts import ARC_SYSTEM

    assert "角色弧光审计员" in ARC_SYSTEM
    assert "清单原名" in ARC_SYSTEM                    # D2：防命名分裂
    assert "不超过 6 个" in ARC_SYSTEM                 # C5：软上限
    assert "changed" in ARC_SYSTEM and "实质变化" in ARC_SYSTEM  # D7：语义判定
    assert "自包含" in ARC_SYSTEM                      # C5：脱离上下文能看懂
    assert "结束时" in ARC_SYSTEM                      # 快照语义：以本章末状态为准
    assert '"characters"' in ARC_SYSTEM                # 输出协议
    assert "测试小说" not in ARC_SYSTEM                # 宪法 §1：不硬编码书名


def test_arc_user_renders_list_and_chapter():
    """C1：既有清单 + 本章正文两段式；空清单回落「（无）」。"""
    from novel_agent.prompts import arc_user

    user_prompt = arc_user("本章正文内容。", ["林晚（第3章）：蒙冤受屈", "沈砚：暗中观察"])
    assert "【既有角色弧光清单】" in user_prompt
    assert "林晚（第3章）：蒙冤受屈" in user_prompt
    assert "【本章正文】" in user_prompt and "本章正文内容。" in user_prompt

    empty = arc_user("正文。", [])
    assert "（无）" in empty


# ---------- 1.7/1.8 文风禁则注入（style-repeat T4）----------
TABOO_RULES = {
    "ending": {"lookback": 10, "max_repeat": 2, "min_chars": 3},
    "syntax_patterns": {"patterns": ["像一个人"], "max_per_chapter": 1},
}


def test_build_style_taboos_deterministic():
    """C11：同输入两次构造结果相同（纯函数）。"""
    endings = ["风很轻", "风很轻", "别的"]
    assert build_style_taboos(endings, TABOO_RULES) == build_style_taboos(endings, TABOO_RULES)


def test_build_style_taboos_content():
    """C9：超配额收束句 + 句式配额都进分节，含「禁」语义。"""
    taboos = build_style_taboos(["风很轻", "风很轻", "别的"], TABOO_RULES)
    assert "【近期文风禁则】" in taboos
    assert "收束句「风很轻」" in taboos
    assert "已用2次" in taboos
    assert "禁止再用" in taboos
    assert "句式模板「像一个人」" in taboos
    assert "每章最多1次" in taboos


def test_build_style_taboos_empty_inputs():
    """无内容 -> ""（整块不占位）。"""
    assert build_style_taboos(None, {}) == ""
    assert build_style_taboos([], {}) == ""
    # 无参照章：句式配额仍注入（预防优先），但无收束句列表项
    taboos = build_style_taboos(None, TABOO_RULES)
    assert "句式模板" in taboos and "- 收束句" not in taboos
    # 参照窗内无超配额结尾且无句式键 -> ""
    assert build_style_taboos(["别的"], {"ending": {"max_repeat": 2}}) == ""


def test_build_style_taboos_cap_five():
    """护栏：收束句最多列 5 条（防分节膨胀）。"""
    endings = [f"结尾{i}" for i in range(8)] * 2  # 8 种各 2 次，全超配额
    taboos = build_style_taboos(endings, TABOO_RULES)
    n_endings = len([ln for ln in taboos.splitlines() if ln.startswith("- 收束句")])
    assert n_endings == 5


def test_build_style_taboos_min_chars_exempt():
    """min_chars 以下超短结尾不进禁则（与检查口径一致）。"""
    taboos = build_style_taboos(["嗯", "嗯"], TABOO_RULES)
    assert "「嗯」" not in taboos


def test_writer_system_style_taboos_block():
    """C9/C16：禁则分节落在近期人工正文之后；空串不占位。"""
    base = writer_system("测试小说", "", "范例", recent_human="人工正文片段")
    assert "近期文风禁则" not in base
    with_block = writer_system(
        "测试小说", "", "范例", recent_human="人工正文片段",
        style_taboos="【近期文风禁则】（测试）\n- 收束句「风很轻」：禁止再用")
    assert "【近期文风禁则】" in with_block
    assert with_block.startswith(base)  # 既有分节零改动，追加在最后
    # 空串与不传参逐字节一致（既有调用零改动）
    assert writer_system("测试小说", "", "范例") == writer_system(
        "测试小说", "", "范例", style_taboos="")
