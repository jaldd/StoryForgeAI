"""写 命令（_do_write）交互层测试：monkeypatch _build_agent + FakeAgent/FakeRag，不联网。

覆盖 0.3（写完自动入库）：章节保存后 rag.add_document 收到章节文件绝对路径；
索引失败不阻断写作流程。
"""
from __future__ import annotations

from novel_agent import cli
from novel_agent.config import Settings
from novel_agent.llm import load_profiles
from novel_agent.memory import WorkingMemory
from novel_agent.state import PipelineState
from novel_agent.storage import load_working_memory


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

    def summarize_chapter(self, chapter_text, max_tokens=1024):
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


# ---------- 工作记忆刷新（0.8 T8/T11）----------
def test_write_updates_working_memory(tmp_settings, fake_rag, monkeypatch):
    """0.8：写完章节后工作记忆刷新并落盘（摘要来自 agent.summarize_chapter）。"""
    agent = WriteAgent(fake_rag)
    _run_write(monkeypatch, tmp_settings, agent)

    wm = load_working_memory(tmp_settings)
    assert wm.current_chapter == 5
    assert wm.last_plot_point == "摘要：风起。"


def test_write_summary_failure_falls_back_to_task(tmp_settings, fake_rag, monkeypatch, capsys):
    """A17：摘要异常 -> 回落 task 兜底，写作主流程不中断。"""
    agent = WriteAgent(fake_rag)

    def boom(chapter_text, max_tokens=1024):
        raise RuntimeError("summary boom")

    agent.summarize_chapter = boom
    _run_write(monkeypatch, tmp_settings, agent)

    assert len(list(tmp_settings.chapter_path.glob("*.md"))) == 1  # 章节仍保存
    out = capsys.readouterr().out
    assert "最终章节" in out  # 流程未中断
    wm = load_working_memory(tmp_settings)
    assert wm.current_chapter == 5
    assert wm.last_plot_point == "写第5章：异乡风起"  # task 兜底


def test_cli_no_longer_has_is_better():
    """T12：对比逻辑已收编为 NovelAgent.is_better，cli 不再内联。"""
    assert not hasattr(cli, "_is_better")


# ---------- _refresh_working_memory 直测（0.8 T11 / D9-b）----------
class _SummarizeStub:
    """只实现 summarize_chapter 的替身（_refresh_working_memory 仅用到它）。"""

    def __init__(self, summary="精修后的摘要。", error=False):
        self.summary = summary
        self.error = error

    def summarize_chapter(self, chapter_text, max_tokens=1024):
        if self.error:
            raise RuntimeError("boom")
        return self.summary


def _refresh(path, wm, agent, tmp_settings):
    state = PipelineState(task="精修：x.md")
    state.final_chapter = "精修后的正文。"
    cli._refresh_working_memory(path, state, agent, wm, tmp_settings)


def test_refresh_wm_first_chapter_none(tmp_path, tmp_settings):
    """D9-b 边界：current_chapter=None（首章）不 TypeError，正常刷新。"""
    wm = WorkingMemory()
    _refresh(tmp_path / "第01章-开端.md", wm, _SummarizeStub("首章摘要。"), tmp_settings)
    assert wm.current_chapter == 1
    assert wm.last_plot_point == "首章摘要。"


def test_refresh_wm_old_chapter_no_regression(tmp_path, tmp_settings):
    """D9-b：精修旧章（num < current_chapter）不回退进度指针。"""
    wm = WorkingMemory()
    wm.update_after_write(5, "第5章摘要。")
    _refresh(tmp_path / "第03章-旧.md", wm, _SummarizeStub("旧章摘要。"), tmp_settings)
    assert wm.current_chapter == 5
    assert wm.last_plot_point == "第5章摘要。"


def test_refresh_wm_newer_chapter_updates_and_persists(tmp_path, tmp_settings):
    """D9-b：精修最新章（num >= current_chapter）刷新且落盘。"""
    wm = WorkingMemory()
    wm.update_after_write(5, "第5章摘要。")
    _refresh(tmp_path / "第06章-夜行.md", wm, _SummarizeStub("第6章摘要。"), tmp_settings)
    assert wm.current_chapter == 6
    assert wm.last_plot_point == "第6章摘要。"
    wm2 = load_working_memory(tmp_settings)  # 已持久化，可跨进程重读
    assert wm2.current_chapter == 6
    assert wm2.last_plot_point == "第6章摘要。"


def test_refresh_wm_unmatched_filename_skips(tmp_path, tmp_settings):
    """A21：文件名解析不出章号 -> 跳过刷新，不阻断存回主流程。"""
    wm = WorkingMemory()
    wm.update_after_write(5, "第5章摘要。")
    _refresh(tmp_path / "随便.md", wm, _SummarizeStub(), tmp_settings)
    assert wm.current_chapter == 5
    assert wm.last_plot_point == "第5章摘要。"
    assert not tmp_settings.working_memory_path.exists()  # 未触发落盘


def test_refresh_wm_summary_failure_skips(tmp_path, tmp_settings):
    """A17：摘要抛异常 -> 跳过刷新（不更新不落盘）。"""
    wm = WorkingMemory()
    wm.update_after_write(5, "第5章摘要。")
    _refresh(tmp_path / "第06章-夜行.md", wm, _SummarizeStub(error=True), tmp_settings)
    assert wm.current_chapter == 5
    assert wm.last_plot_point == "第5章摘要。"
    assert not tmp_settings.working_memory_path.exists()


# ---------- 精修集成（0.8 T11/A18）----------
def test_refine_pass_refreshes_working_memory(tmp_settings, fake_rag, monkeypatch, capsys):
    """精修存回后 working_memory.json 刷新（章号取自文件名，摘要走收编方法）。"""
    novel = tmp_settings.novel_path
    novel.mkdir(parents=True, exist_ok=True)
    chap = novel / "第05章-异乡风起.md"
    chap.write_text("旧正文。", encoding="utf-8")

    class RefineAgent:
        def __init__(self, rag):
            self.rag = rag
            self.instruction = ""

        def refine(self, content, task, run_id=None, temperature=0.7):
            state = PipelineState(task=task)
            state.draft = content
            state.polished = "新正文。"
            state.final_chapter = "新正文。"
            state.feedback = "审稿通过：ok"
            state.round = 2
            state.log = ["[reviewer] 审稿通过：ok"]
            record = {
                "run_id": "refine_x", "task": task, "timestamp": "",
                "config": {}, "initial_state": {}, "steps": [], "final_state": {},
            }
            return state, record

        def summarize_chapter(self, chapter_text, max_tokens=1024):
            return "第5章精修后的摘要。"

    agent = RefineAgent(fake_rag)
    wm = WorkingMemory()
    monkeypatch.setattr(cli, "_build_agent", lambda settings: (agent, wm))
    monkeypatch.setattr(cli, "evaluate", lambda *a, **kw: None)
    cli._do_refine([str(chap)], tmp_settings)

    assert chap.read_text(encoding="utf-8") == "新正文。"  # 覆盖存回
    assert fake_rag.add_calls == [str(chap)]              # 索引更新
    wm2 = load_working_memory(tmp_settings)
    assert wm2.current_chapter == 5
    assert wm2.last_plot_point == "第5章精修后的摘要。"
    out = capsys.readouterr().out
    assert "已覆盖存回" in out


# ---------- 0.7 双 client 装配（T7）----------
def test_build_agent_injects_dual_clients(tmp_settings):
    """T7：_build_agent 用 load_profiles 一次解析，注入 default/writer 双 client。

    未配 WRITER_* 时两 profile 逐字段相等（A9 回归保险，行为与改造前一致）。
    """
    agent, _ = cli._build_agent(tmp_settings)
    assert agent.llm.profile == load_profiles(tmp_settings).default
    assert agent.writer_llm.profile == load_profiles(tmp_settings).writer
    assert agent.llm.profile == agent.writer_llm.profile   # 未配时同值
    assert agent.llm is not agent.writer_llm                # 但仍是两个独立实例


def test_build_agent_writer_model_configured(tmp_settings):
    """T7/A1-A8：配 WRITER_MODEL 后 writer_llm 的 profile 独立可见。"""
    settings = Settings(
        ark_api_key=tmp_settings.ark_api_key,
        repo_root=tmp_settings.repo_root,
        novel_dir=tmp_settings.novel_dir,
        writer_model="kimi-k3",
    )
    agent, _ = cli._build_agent(settings)
    assert agent.llm.profile.model == "glm-5.2"
    assert agent.writer_llm.profile.model == "kimi-k3"
