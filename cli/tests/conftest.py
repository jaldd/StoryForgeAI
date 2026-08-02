"""pytest 公共夹具。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

import pytest

from novel_agent.config import Settings
from novel_agent.llm import LLMClient
from novel_agent.rag import RAGStore
from novel_agent.storage import save_run


class FakeLLM(LLMClient):
    """按用户内容分流的假 LLM，不联网。

    - 传 script=[...] 则按顺序消费脚本（用于精确控制打回/通过）。
    - 否则按关键词分流：审查->审稿JSON，润色->润色稿，其它->初稿。
    """

    def __init__(self, script: Optional[List[str]] = None):
        self.script = list(script) if script else []
        self.calls: List[str] = []

    def chat(self, system, user, **kw):
        self.calls.append(user)
        if self.script:
            return self.script.pop(0)
        if "审查" in user:
            return '{"pass": true, "reason": "通过"}'
        if "润色" in user:
            return "【润色稿】风起了，云依没说话。"
        return "【初稿】风起了，他站在路口。云依没说话。"


class FakeRag:
    """假 RAG：retrieve 永远返回固定设定，不联网不依赖 Chroma。"""

    def retrieve(self, query, top_k=5, doc_type=None):
        return [("云依是在场的女主，不追问。", "docs/人物.md")] * min(top_k, 1)

    def search_knowledge(self, query, top_k=5):
        return "【出自 docs/人物.md】\n云依是在场的女主。"


@pytest.fixture
def tmp_settings(tmp_path):
    """临时小说目录的 Settings，写入不影响真实数据。novel_dir 指向临时目录。"""
    return Settings(
        ark_api_key="test-key",
        repo_root=tmp_path,
        novel_dir=str(tmp_path / "novel"),
    )


@pytest.fixture
def fake_llm():
    return FakeLLM()


@pytest.fixture
def fake_rag():
    return FakeRag()


@pytest.fixture
def sample_run(tmp_settings):
    """写一份样例 run JSON 到临时 runs 目录，返回 run_id。"""
    record = {
        "run_id": "run_20260801_222632",
        "task": "写第5章：异乡风起",
        "timestamp": "2026-08-01T22:28:12.101539",
        "config": {"model": "glm-5.2", "temperature": 0.9, "max_rounds": 10},
        "initial_state": {"task": "写第5章：异乡风起", "draft": "", "polished": "",
                          "feedback": "", "final_chapter": "", "round": 0,
                          "next_agent": "director", "review_count": 0, "log": []},
        "steps": [
            {"step_id": 1, "agent": "director", "round": 1,
             "input_state": {}, "output_state": {"next_agent": "writer"},
             "decision": "writer"},
            {"step_id": 2, "agent": "writer", "round": 2,
             "input_state": {}, "output_state": {"draft": "风起。", "polished": "", "next_agent": "polisher"},
             "decision": "polisher"},
            {"step_id": 3, "agent": "reviewer", "round": 3,
             "input_state": {}, "output_state": {"polished": "风起了。", "next_agent": "done"},
             "decision": "done"},
        ],
        "final_state": {
            "task": "写第5章：异乡风起", "draft": "风起。", "polished": "风起了，他站在路口。",
            "feedback": "审稿通过：ok", "final_chapter": "风起了，他站在路口。风不解释。",
            "round": 3, "next_agent": "done", "review_count": 0, "log": [],
        },
    }
    save_run(record, tmp_settings)
    return "run_20260801_222632"
