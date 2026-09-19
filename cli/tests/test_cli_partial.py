"""改 命令（局部精修）交互层测试：monkeypatch input + FakeAgent/FakeRag，不联网。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from novel_agent import cli
from novel_agent.harness import replay

# 样例章节：章节头 + 4 段正文，--- 夹在 3/4 段之间（选区外保真覆盖 title/sep/para）
CHAPTER = (
    "## 第5章 异乡风起\n\n"
    "第一段内容，风起了。\n\n"
    "第二段内容，路口。\n\n"
    "第三段内容，林晚没回头。\n\n"
    "---\n\n"
    "第四段内容，他没说话。\n"
)


class FakeAgent:
    """替身 agent：partial_refine 返回固定文本；可注入异常/空回。"""

    def __init__(self, rag, results=None):
        self.rag = rag
        self.results = list(results) if results is not None else ["改写后的第二段。"]
        self.error = None
        self.calls = []  # 记录 (spans, task)

    def partial_refine(self, blocks, spans, task, run_id=None):
        if self.error is not None:
            raise self.error
        self.calls.append((list(spans), task))
        return list(self.results)


@pytest.fixture
def env(tmp_path, tmp_settings, fake_rag, monkeypatch):
    """小说目录 + 章节文件 + monkeypatch _build_agent。返回 (path, agent, rag)。"""
    novel_dir = tmp_path / "novel"
    novel_dir.mkdir()
    path = novel_dir / "第05章.md"
    path.write_bytes(CHAPTER.encode("utf-8"))
    agent = FakeAgent(fake_rag)
    monkeypatch.setattr(cli, "_build_agent", lambda settings, task="", need_style=True, active_file="": (agent, None, None))
    return path, agent, fake_rag


def _feed_inputs(monkeypatch, answers):
    """按序喂 input；耗尽后再被调用视为测试失败。"""
    remaining = list(answers)

    def fake_input(prompt=""):
        assert remaining, "多余的 input 调用"
        return remaining.pop(0)

    monkeypatch.setattr("builtins.input", fake_input)


# ---------- 全流程 / 取消 ----------
def test_partial_y_full_flow(env, tmp_settings, monkeypatch, capsys):
    """y 全流程：选区被替换、选区外字节逐字节不变、add_document 被调、task 正确。"""
    path, agent, rag = env
    _feed_inputs(monkeypatch, ["2", "y"])
    cli._do_partial([str(path)], tmp_settings)

    new_text = path.read_bytes().decode("utf-8")
    # 选区（第2段）被替换
    assert "改写后的第二段。" in new_text
    assert "第二段内容，路口。" not in new_text
    # 选区外前缀/后缀逐字节不变（含章节头与 ---）
    assert new_text.startswith("## 第5章 异乡风起\n\n第一段内容，风起了。\n\n")
    assert new_text.endswith("第三段内容，林晚没回头。\n\n---\n\n第四段内容，他没说话。\n")
    # 重索引被调
    assert rag.add_calls == [str(path)]
    # task 形如「局部精修：<文件名>」
    assert agent.calls == [([(2, 2)], "局部精修：第05章.md")]


def test_partial_n_cancel(env, tmp_settings, monkeypatch, capsys):
    """n 取消：原文件字节不变、无 add 调用。"""
    path, agent, rag = env
    before = path.read_bytes()
    _feed_inputs(monkeypatch, ["2", "n"])
    cli._do_partial([str(path)], tmp_settings)
    assert path.read_bytes() == before
    assert rag.add_calls == []
    assert "未改动" in capsys.readouterr().out


def test_partial_invalid_then_cancel(env, tmp_settings, monkeypatch, capsys):
    """非法选段（超界/非数字）重输后 q 取消：文件不动、未调 LLM。"""
    path, agent, rag = env
    before = path.read_bytes()
    _feed_inputs(monkeypatch, ["99", "abc", "q"])
    cli._do_partial([str(path)], tmp_settings)
    assert path.read_bytes() == before
    assert rag.add_calls == []
    assert agent.calls == []
    out = capsys.readouterr().out
    assert out.count("❌") >= 2  # 两次非法输入都打印了原因


# ---------- 取消与异常（R1）----------
def test_partial_ctrlc_at_selection(env, tmp_settings, monkeypatch, capsys):
    """选段 input 抛 KeyboardInterrupt -> 取消，文件不动。"""
    path, agent, rag = env
    before = path.read_bytes()

    def fake_input(prompt=""):
        raise KeyboardInterrupt

    monkeypatch.setattr("builtins.input", fake_input)
    cli._do_partial([str(path)], tmp_settings)
    assert path.read_bytes() == before
    assert rag.add_calls == []


def test_partial_ctrlc_during_llm(env, tmp_settings, monkeypatch, capsys):
    """LLM 生成中途 Ctrl-C（partial_refine 抛 KeyboardInterrupt）-> 取消，文件不动。"""
    path, agent, rag = env
    agent.error = KeyboardInterrupt()
    before = path.read_bytes()
    _feed_inputs(monkeypatch, ["2"])
    cli._do_partial([str(path)], tmp_settings)
    assert path.read_bytes() == before
    assert rag.add_calls == []
    assert "已取消" in capsys.readouterr().out


# ---------- 失败路径（A14/A15/A2/A3）----------
def test_partial_llm_empty_reply(env, tmp_settings, monkeypatch, capsys):
    """LLM 空回（None 项）-> 提示未改动，文件不动、无 add。"""
    path, agent, rag = env
    agent.results = [None]
    before = path.read_bytes()
    _feed_inputs(monkeypatch, ["2"])
    cli._do_partial([str(path)], tmp_settings)
    assert path.read_bytes() == before
    assert rag.add_calls == []
    assert "模型未返回内容" in capsys.readouterr().out


def test_partial_length_warning(env, tmp_settings, monkeypatch, capsys):
    """选区 >=50 字且改后坍缩 <1/3 -> ⚠️ 长度异常警告（不拦截，仍进 diff）。"""
    path, agent, rag = env
    long_para = "风从巷口过来，掠过修车铺的帆布棚，他站在路灯下没动，林晚也没回头，两个人隔着半条街谁都没先开口。" * 2
    path.write_bytes(f"{long_para}\n\n尾段。\n".encode("utf-8"))
    agent.results = ["短。"]
    _feed_inputs(monkeypatch, ["1", "n"])
    cli._do_partial([str(path)], tmp_settings)
    out = capsys.readouterr().out
    assert "长度异常" in out
    assert "局部精修差异" in out  # 警告不拦截，仍展示 diff


def test_partial_file_not_found(tmp_path, tmp_settings, monkeypatch, fake_rag, capsys):
    """文件不存在 -> 提示后退出。"""
    agent = FakeAgent(fake_rag)
    monkeypatch.setattr(cli, "_build_agent", lambda settings, task="", need_style=True, active_file="": (agent, None, None))
    cli._do_partial([str(tmp_path / "不存在.md")], tmp_settings)
    assert "找不到文件" in capsys.readouterr().out


def test_partial_no_args(tmp_settings, capsys):
    """未带参数 -> 打印用法。"""
    cli._do_partial([], tmp_settings)
    assert "用法" in capsys.readouterr().out


# ---------- 写作铁律加载（0.2 外置到 NOVEL_DIR）----------
def test_load_rules_reads_file(tmp_settings):
    """铁律文件存在 -> 读全文；不存在 -> 空串（不报错不占位）。"""
    rules_path = tmp_settings.novel_path / "写作铁律.md"
    rules_path.parent.mkdir(parents=True, exist_ok=True)
    rules_path.write_text("铁律一：短句为主。", encoding="utf-8")
    assert cli._load_rules(tmp_settings) == "铁律一：短句为主。"
    # 文件不存在 -> 空串
    rules_path.unlink()
    assert cli._load_rules(tmp_settings) == ""


def test_partial_no_numbered_paragraphs(tmp_path, tmp_settings, monkeypatch, fake_rag, capsys):
    """无可编号段落（仅标题/---）-> 提示后退出，不调 LLM。"""
    novel_dir = tmp_path / "novel"
    novel_dir.mkdir()
    path = novel_dir / "纯标题.md"
    path.write_bytes("## 第5章\n\n---\n\n".encode("utf-8"))
    agent = FakeAgent(fake_rag)
    monkeypatch.setattr(cli, "_build_agent", lambda settings, task="", need_style=True, active_file="": (agent, None, None))
    cli._do_partial([str(path)], tmp_settings)
    assert "无可选段落" in capsys.readouterr().out
    assert agent.calls == []


# ---------- 多区间（R2）----------
def test_partial_multi_span_diff_sections(env, tmp_settings, monkeypatch, capsys):
    """多区间（1,3）各自独立调用、diff 按区间分段展示。"""
    path, agent, rag = env
    agent.results = ["改写一。", "改写三。"]
    _feed_inputs(monkeypatch, ["1,3", "n"])
    cli._do_partial([str(path)], tmp_settings)
    out = capsys.readouterr().out
    assert "--- 第1段 ---" in out
    assert "--- 第3段 ---" in out
    assert agent.calls == [([(1, 1), (3, 3)], "局部精修：第05章.md")]


# ---------- run 留痕（T9/A17）----------
def _partial_run_files(tmp_settings):
    """runs 目录下 partial_*.json 文件列表（目录不存在视为空）。"""
    runs_dir = tmp_settings.runs_path
    return sorted(runs_dir.glob("partial_*.json")) if runs_dir.exists() else []


def test_partial_run_log_saved(env, tmp_settings, monkeypatch):
    """y 流程后 runs 目录出现 partial_*.json：键齐全、final_chapter=回填后全文。"""
    path, agent, rag = env
    _feed_inputs(monkeypatch, ["2", "y"])
    cli._do_partial([str(path)], tmp_settings)

    files = _partial_run_files(tmp_settings)
    assert len(files) == 1
    record = json.loads(files[0].read_text(encoding="utf-8"))
    # replay 直读的全部键都在（harness.replay 无缺键容错）
    for key in ("run_id", "task", "timestamp", "config",
                "initial_state", "steps", "final_state"):
        assert key in record
    assert record["run_id"].startswith("partial_")
    assert record["task"] == "局部精修：第05章.md"
    assert record["mode"] == "partial-refine"
    assert Path(record["file"]) == path
    assert record["spans"] == [[2, 2]]
    assert record["steps"] == []
    assert record["confirmed"] is True
    # final_chapter = 回填后全文（与磁盘字节一致）
    assert record["final_state"]["final_chapter"] == path.read_bytes().decode("utf-8")
    # 各区间原文/改后文本
    assert record["changes"] == [
        {"span": [2, 2], "old": "第二段内容，路口。", "new": "改写后的第二段。"},
    ]


def test_partial_run_log_replay(env, tmp_settings, monkeypatch):
    """replay 能读 partial run：打印「共 0 步」与改写结果（最终章节=回填后全文）。"""
    path, agent, rag = env
    _feed_inputs(monkeypatch, ["2", "y"])
    cli._do_partial([str(path)], tmp_settings)

    files = _partial_run_files(tmp_settings)
    assert len(files) == 1
    run_id = files[0].stem
    lines: list = []
    replay(run_id, tmp_settings, out=lines.append)
    out = "\n".join(lines)
    assert f"=== 回放 {run_id} ===" in out
    assert "共 0 步" in out
    # 最终章节 = 回填后全文（含改写文本）
    assert "改写后的第二段。" in out
    assert out.rstrip().endswith("第四段内容，他没说话。")  # 全文末段也在（未截断）


def test_partial_run_log_not_saved_on_cancel(env, tmp_settings, monkeypatch):
    """n 取消不留痕（「未发生」语义一致）。"""
    path, agent, rag = env
    _feed_inputs(monkeypatch, ["2", "n"])
    cli._do_partial([str(path)], tmp_settings)
    assert _partial_run_files(tmp_settings) == []
