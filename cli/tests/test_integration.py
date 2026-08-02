"""集成测试：真实调用火山方舟 LLM + Chroma，写一章。

默认 skip（花钱、慢、需联网）。显式开启：

    INTEGRATION_TEST=1 NOVEL_DIR=/path/to/novel pytest -m integration

依赖：ARK_API_KEY、NOVEL_DIR 已配置（NOVEL_DIR 指向仓库外的小说内容根）。
"""
import os

import pytest

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _require_env():
    if not os.environ.get("INTEGRATION_TEST"):
        pytest.skip("set INTEGRATION_TEST=1 to run integration tests")
    if not os.environ.get("NOVEL_DIR"):
        pytest.skip("set NOVEL_DIR to run integration tests")


def test_write_one_chapter(tmp_path):
    """端到端：真实 LLM 写一章，产出非空、存盘、可回放。"""
    from pathlib import Path

    from novel_agent.config import Settings
    from novel_agent.storage import save_run  # noqa: F401  确保模块可用

    settings = Settings(
        ark_api_key=os.environ.get("ARK_API_KEY", ""),
        novel_dir=os.environ["NOVEL_DIR"],
        runs_dir=str(tmp_path / "runs"),  # run 日志落临时目录，不污染小说的 .agent
    )

    from novel_agent.agent import NovelAgent
    from novel_agent.llm import LLMClient
    from novel_agent.memory import WorkingMemory
    from novel_agent.prompts import load_exemplar
    from novel_agent.rag import RAGStore
    from novel_agent.storage import load_run

    exemplar = load_exemplar(settings.exemplar_full) if settings.exemplar_full.exists() else ""
    agent = NovelAgent(
        llm=LLMClient(settings=settings),
        rag=RAGStore(settings=settings),
        exemplar=exemplar,
        settings=settings,
        working_memory=WorkingMemory(),
    )
    state, record = agent.run("写第5章：异乡风起")
    save_run(record, settings)

    assert state.final_chapter, "最终章节为空"
    assert len(state.final_chapter) > 50
    assert "许风" not in state.final_chapter  # 铁律
    # 可回放
    d = load_run(record["run_id"], settings)
    assert d["task"] == "写第5章：异乡风起"
