"""0.5 exemplar 语料目录化测试：目录级加载 / 单文件兼容 / 超限截断 / 状态命令清单。

1.1 quality-gate T5：reviewer 八维 schema 演进与 fixer prompt 构造。
"""
from __future__ import annotations

from pathlib import Path

from novel_agent import cli
from novel_agent.prompts import (
    EXEMPLAR_MAX_CHARS,
    exemplar_info,
    fixer_system,
    fixer_user,
    fixer_whole_user,
    load_exemplar,
    reviewer_system,
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
def test_reviewer_system_eight_dimensions_and_schema():
    """reviewer_system 含八维名、scores/issues/quote 键名；旧三键保留（D4）。"""
    sys_prompt = reviewer_system("测试小说", "")
    for dim in ["人物一致性", "文风一致性", "剧情连贯性", "时间线一致性",
                "环境一致性", "伏笔一致性", "比喻密度", "视角越界"]:
        assert dim in sys_prompt, dim
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
