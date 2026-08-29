"""state 模块测试。"""
from dataclasses import asdict

from novel_agent.state import PipelineState


def test_defaults():
    s = PipelineState()
    assert s.task == "" and s.draft == "" and s.final_chapter == ""
    assert s.next_agent == "writer"  # 0.8：删 director，run 起点直接是 writer
    assert s.outline == ""           # 0.8：构思字段，无 === 分隔时为空
    assert s.round == 0 and s.review_count == 0
    assert s.log == []
    # 1.1 审核维度化：独立默认值，互不共享（default_factory）
    assert s.scores == {}
    assert s.issues == []


def test_asdict_roundtrip():
    s = PipelineState(task="写第5章", draft="草稿", next_agent="writer")
    d = asdict(s)
    assert d["task"] == "写第5章" and d["draft"] == "草稿"
    assert d["next_agent"] == "writer"
    # 可序列化回同字段
    s2 = PipelineState(**d)
    assert s2.task == s.task and s2.draft == s.draft


def test_scores_issues_fields():
    """scores/issues 可写并进 asdict（run record 的 steps/final_state，A4/A24）。"""
    s = PipelineState(task="写第5章")
    s.scores = {"人物一致性": 4}
    s.issues = [{"quote": "许风进来", "problem": "称呼错误", "fix": "改为林晚"}]
    d = asdict(s)
    assert d["scores"] == {"人物一致性": 4}
    assert d["issues"] == [{"quote": "许风进来", "problem": "称呼错误", "fix": "改为林晚"}]
