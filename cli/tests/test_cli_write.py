"""写 命令（_do_write）交互层测试：monkeypatch _build_agent + FakeAgent/FakeRag，不联网。

覆盖 0.3（写完自动入库）：章节保存后 rag.add_document 收到章节文件绝对路径；
索引失败不阻断写作流程。
"""
from __future__ import annotations

from novel_agent import cli
from novel_agent.memory import WorkingMemory
from novel_agent.state import PipelineState


class WriteAgent:
    """替身 agent：run() 返回已定稿的 state；llm 摘要返回固定文本。"""

    def __init__(self, rag, final="风起了。他没说话。"):
        self.rag = rag
        self.final = final
        self.instruction = ""
        self.llm = self  # 摘要用（agent.llm.chat）

    def run(self, task, run_id=None, temperature=0.9):
        state = PipelineState(task=task)
        state.final_chapter = self.final
        state.feedback = "审稿通过：ok"
        state.round = 3
        state.log = ["[reviewer] 审稿通过：ok"]
        record = {
            "run_id": "run_20260828_000001",
            "task": task,
            "timestamp": "2026-08-28T00:00:01",
            "config": {},
            "initial_state": {},
            "steps": [],
            "final_state": {},
        }
        return state, record

    def chat(self, system, user, **kw):
        return "摘要：风起。"


def _run_write(monkeypatch, tmp_settings, agent):
    """把 _build_agent / evaluate 替换掉后跑一次 _do_write。"""
    monkeypatch.setattr(cli, "_build_agent", lambda settings: (agent, WorkingMemory()))
    monkeypatch.setattr(cli, "evaluate", lambda *a, **kw: None)
    cli._do_write("写第5章：异乡风起", tmp_settings)


def test_write_auto_indexes_chapter(tmp_settings, fake_rag, monkeypatch, capsys):
    """0.3：写完自动入库--章节保存后 add_document 恰好一次，参数为章节文件绝对路径。"""
    agent = WriteAgent(fake_rag)
    _run_write(monkeypatch, tmp_settings, agent)

    chapters = list(tmp_settings.chapter_path.glob("*.md"))
    assert len(chapters) == 1                      # 章节已落盘
    assert fake_rag.add_calls == [str(chapters[0])]  # 自动入库，传章节文件路径
    out = capsys.readouterr().out
    assert "更新向量库" in out
    assert "章节已存" in out


def test_write_index_failure_not_fatal(tmp_settings, monkeypatch, capsys):
    """0.3：索引失败不阻断--章节仍保存，打印失败原因，流程走完。"""
    class BrokenRag:
        def add_document(self, file_path, progress=None):
            raise RuntimeError("boom")

    agent = WriteAgent(BrokenRag())
    _run_write(monkeypatch, tmp_settings, agent)

    assert len(list(tmp_settings.chapter_path.glob("*.md"))) == 1  # 章节仍保存
    out = capsys.readouterr().out
    assert "索引更新失败" in out and "boom" in out
    assert "最终章节" in out  # 流程未被阻断，走到结尾


def test_write_no_chapter_no_index(tmp_settings, fake_rag, monkeypatch, capsys):
    """未定稿（final_chapter 空）-> 不存章节也不入库（0.1 弃稿与 0.3 的边界）。"""
    agent = WriteAgent(fake_rag, final="")
    agent.run = lambda task, run_id=None, temperature=0.9: _empty_state(task)
    _run_write(monkeypatch, tmp_settings, agent)

    assert list(tmp_settings.chapter_path.glob("*.md")) == []
    assert fake_rag.add_calls == []


def _empty_state(task):
    state = PipelineState(task=task)
    state.feedback = "审稿不通过（审稿结果不可解析，人工确认弃稿，本章未定稿）"
    state.round = 3
    state.log = ["[reviewer] 人工确认：弃（本章未定稿，不存盘）"]
    record = {
        "run_id": "run_20260828_000002",
        "task": task,
        "timestamp": "2026-08-28T00:00:02",
        "config": {},
        "initial_state": {},
        "steps": [],
        "final_state": {},
    }
    return state, record
