"""state 模块测试。"""
from dataclasses import asdict

from novel_agent.state import PipelineState


def test_defaults():
    s = PipelineState()
    assert s.task == "" and s.draft == "" and s.final_chapter == ""
    assert s.next_agent == "director"
    assert s.round == 0 and s.review_count == 0
    assert s.log == []


def test_asdict_roundtrip():
    s = PipelineState(task="写第5章", draft="草稿", next_agent="writer")
    d = asdict(s)
    assert d["task"] == "写第5章" and d["draft"] == "草稿"
    assert d["next_agent"] == "writer"
    # 可序列化回同字段
    s2 = PipelineState(**d)
    assert s2.task == s.task and s2.draft == s.draft
