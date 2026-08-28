"""0.5 exemplar 语料目录化测试：目录级加载 / 单文件兼容 / 超限截断 / 状态命令清单。"""
from __future__ import annotations

from pathlib import Path

from novel_agent import cli
from novel_agent.prompts import EXEMPLAR_MAX_CHARS, exemplar_info, load_exemplar


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

    monkeypatch.setattr(cli, "LLMClient", lambda settings=None: None)
    monkeypatch.setattr(cli, "RAGStore", lambda settings=None: None)
    monkeypatch.setattr(cli, "NovelAgent", _Agent)
    cli._build_agent(tmp_settings)
    assert captured["exemplar"] == "甲\n\n乙"
