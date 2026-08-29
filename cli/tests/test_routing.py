"""exemplar-routing 测试：标签解析纯函数 + 路由调用（FakeLLM，不联网）。"""
from __future__ import annotations

from novel_agent.prompts import exemplar_router_user
from novel_agent.routing import RouteResult, parse_tag_lines, route_exemplars

from tests.conftest import FakeLLM

TAGS_TEXT = """# 样文标签

说明文字，解析只取列表行。

- 1.txt: 天气感强，内在拉扯，风与身体感受同写
- 5.txt: 她在场时他慢慢落下来；风停
- 10.txt: 日常靠近感，小事里的默契
* 13.txt: 人多的场合，他的退缩

- 2.txt 没有冒号描述的行
随便一行散文
"""

TAGS = parse_tag_lines(TAGS_TEXT)


# ---------- T1：parse_tag_lines ----------
def test_parse_tag_lines_basic():
    """正常列表行（-/* 前缀、全半角冒号）按序解析；标题/说明/无冒号行跳过。"""
    assert TAGS == [
        ("1.txt", "天气感强，内在拉扯，风与身体感受同写"),
        ("5.txt", "她在场时他慢慢落下来；风停"),
        ("10.txt", "日常靠近感，小事里的默契"),
        ("13.txt", "人多的场合，他的退缩"),
    ]


def test_parse_tag_lines_empty():
    """空文本/纯说明文本 -> 空列表。"""
    assert parse_tag_lines("") == []
    assert parse_tag_lines("# 标题\n\n只有说明。\n") == []


def test_router_user_contains_task_and_tags():
    """exemplar_router_user：任务与标签行都进 user 消息（纯函数）。"""
    user = exemplar_router_user("写第21章：上山看云", TAGS)
    assert "写第21章：上山看云" in user
    assert "- 5.txt: 她在场时他慢慢落下来；风停" in user


# ---------- T2：route_exemplars ----------
def test_route_success():
    """路由成功：files 保序返回，reason 透传。"""
    llm = FakeLLM(script=['{"files": ["5.txt", "10.txt", "13.txt"], "reason": "日常+退缩"}'])
    route = route_exemplars(llm, "写第21章：上山", TAGS)
    assert route == RouteResult(files=["5.txt", "10.txt", "13.txt"], reason="日常+退缩")


def test_route_fenced_json_and_dedup():
    """模型输出带 ``` 围栏 -> 剥掉再解析；files 重复去重保序。"""
    llm = FakeLLM(script=['```json\n{"files": ["1.txt", "1.txt", "5.txt"], "reason": "r"}\n```'])
    route = route_exemplars(llm, "task", TAGS)
    assert route is not None and route.files == ["1.txt", "5.txt"]


def test_route_bad_json_returns_none():
    """输出不可解析 -> None（回落由调用方处理，A3）。"""
    llm = FakeLLM(script=["这不是 JSON，模型抽风了。"])
    assert route_exemplars(llm, "task", TAGS) is None


def test_route_fabricated_files_filtered():
    """编造的文件名被过滤，只留标签集合内的（A4）。"""
    llm = FakeLLM(script=['{"files": ["5.txt", "99.txt", "1.txt"], "reason": "r"}'])
    route = route_exemplars(llm, "task", TAGS)
    assert route is not None and route.files == ["5.txt", "1.txt"]


def test_route_all_fabricated_returns_none():
    """files 全部不在标签集合（全落空）-> None，回落现状加载（A4）。"""
    llm = FakeLLM(script=['{"files": ["a.txt", "b.txt"], "reason": "r"}'])
    assert route_exemplars(llm, "task", TAGS) is None


def test_route_empty_files_list_returns_none():
    """files 为空列表 / 非 list -> None。"""
    assert route_exemplars(FakeLLM(script=['{"files": [], "reason": "r"}']), "task", TAGS) is None
    assert route_exemplars(FakeLLM(script=['{"files": "5.txt", "reason": "r"}']), "task", TAGS) is None


def test_route_empty_tags_returns_none():
    """tags 为空直接 None（防御性，不发起 LLM 调用）。"""
    llm = FakeLLM(script=["不该被调用"])
    assert route_exemplars(llm, "task", []) is None
    assert llm.calls == []
