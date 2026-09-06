"""写 命令（_do_write）交互层测试：monkeypatch _build_agent + FakeAgent/FakeRag，不联网。

覆盖 0.3（写完自动入库）：章节保存后 rag.add_document 收到章节文件绝对路径；
索引失败不阻断写作流程。
1.1 T8：质量门禁三路 / D8 豁免 / 规则未配置 / refine 同构 / _gate_ok 单测 / A23 命令层捕获。
"""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from novel_agent import cli
from novel_agent.config import Settings
from novel_agent.llm import load_profiles
from novel_agent.memory import WorkingMemory
from novel_agent.state import PipelineState
from novel_agent.storage import load_run, load_working_memory, save_working_memory


class WriteAgent:
    """替身 agent：run() 返回已定稿的 state；llm 摘要返回固定文本。"""

    def __init__(self, rag, final="风起了。他没说话。", feedback="审稿通过：ok"):
        self.rag = rag
        self.final = final
        self.feedback = feedback
        self.instruction = ""
        self.llm = self  # 摘要用（agent.llm.chat）

    def run(self, task, run_id=None, temperature=0.9):
        state = PipelineState(task=task)
        state.final_chapter = self.final
        state.feedback = self.feedback
        state.round = 3
        state.log = ["[reviewer] " + self.feedback]
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
    monkeypatch.setattr(cli, "_build_agent", lambda settings, task="", need_style=True: (agent, WorkingMemory(), None))
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


# ---------- exemplar-routing：_build_agent 路由接线 ----------
def _mk_route_env(tmp_settings):
    """小说目录 + 文风基准（说明 + 两篇样文 + 标签文件），返回样文内容常量。"""
    d = tmp_settings.exemplar_full
    d.mkdir(parents=True)
    (d / "00-使用说明.md").write_text("使用说明", encoding="utf-8")
    (d / "1.txt").write_text("甲", encoding="utf-8")
    (d / "2.txt").write_text("乙", encoding="utf-8")
    tags = tmp_settings.exemplar_tags_full
    tags.write_text("# 样文标签\n\n- 1.txt: 天气感\n- 2.txt: 日常\n", encoding="utf-8")


def test_build_agent_routes_exemplars(tmp_settings, monkeypatch, capsys):
    """A2：标签存在 + 路由成功 -> agent.exemplar 只含说明 + 选中样文（未选中的不进）。"""
    _mk_route_env(tmp_settings)
    from tests.conftest import FakeLLM

    router_llm = FakeLLM(script=['{"files": ["1.txt"], "reason": "天气章"}'])
    captured: dict = {}

    class _Agent:
        def __init__(self, **kw):
            captured.update(kw)

    monkeypatch.setattr(cli, "LLMClient", lambda settings=None, profile=None: router_llm)
    monkeypatch.setattr(cli, "RAGStore", lambda settings=None: None)
    monkeypatch.setattr(cli, "NovelAgent", _Agent)
    agent, _wm, route = cli._build_agent(tmp_settings, task="写第1章：风起")

    assert captured["exemplar"] == "使用说明\n\n甲"   # 2.txt 未被路由选中，不注入
    assert route is not None and route.files == ["1.txt"]
    out = capsys.readouterr().out
    assert "样文路由：1.txt" in out


def test_build_agent_route_failure_falls_back(tmp_settings, monkeypatch, capsys):
    """A3/A4：路由返回坏 JSON -> 回落全量加载（说明 + 全部样文），写作不中断。"""
    _mk_route_env(tmp_settings)
    from tests.conftest import FakeLLM

    router_llm = FakeLLM(script=["模型抽风，不是 JSON"])
    captured: dict = {}

    class _Agent:
        def __init__(self, **kw):
            captured.update(kw)

    monkeypatch.setattr(cli, "LLMClient", lambda settings=None, profile=None: router_llm)
    monkeypatch.setattr(cli, "RAGStore", lambda settings=None: None)
    monkeypatch.setattr(cli, "NovelAgent", _Agent)
    agent, _wm, route = cli._build_agent(tmp_settings, task="写第1章：风起")

    assert captured["exemplar"] == "使用说明\n\n甲\n\n乙"  # 现状全量
    assert route is None
    assert "回落" in capsys.readouterr().out


def test_do_write_records_route(tmp_settings, fake_rag, monkeypatch, capsys):
    """A5：路由结果进 run 记录落盘，可 load_run 读回。"""
    from novel_agent.routing import RouteResult
    from novel_agent.storage import load_run

    agent = WriteAgent(fake_rag)
    wm = WorkingMemory()
    route = RouteResult(files=["1.txt", "2.txt"], reason="日常章")
    monkeypatch.setattr(cli, "_build_agent", lambda settings, task="", need_style=True: (agent, wm, route))
    monkeypatch.setattr(cli, "evaluate", lambda *a, **kw: None)
    cli._do_write("写第5章：异乡风起", tmp_settings)

    saved = load_run("run_20260828_000001", tmp_settings)
    assert saved["exemplar_route"] == {"files": ["1.txt", "2.txt"], "reason": "日常章"}


def test_do_write_no_route_no_key(tmp_settings, fake_rag, monkeypatch, capsys):
    """A5 边界：未路由（route=None）时 run 记录不含 exemplar_route 键。"""
    from novel_agent.storage import load_run

    agent = WriteAgent(fake_rag)
    monkeypatch.setattr(cli, "_build_agent", lambda settings, task="", need_style=True: (agent, WorkingMemory(), None))
    monkeypatch.setattr(cli, "evaluate", lambda *a, **kw: None)
    cli._do_write("写第5章：异乡风起", tmp_settings)

    saved = load_run("run_20260828_000001", tmp_settings)
    assert "exemplar_route" not in saved


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
    monkeypatch.setattr(cli, "_build_agent", lambda settings, task="", need_style=True: (agent, wm, None))
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
    agent, _, _ = cli._build_agent(tmp_settings)
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
    agent, _, _ = cli._build_agent(settings)
    assert agent.llm.profile.model == "glm-5.2"
    assert agent.writer_llm.profile.model == "kimi-k3"


# ---------- 质量门禁（1.1 T8 / A30-A34）----------
def _write_gate_rules(tmp_settings, threshold=4.0):
    """往临时小说目录写只含 eval_gate 的质量规则 JSON（配权维度故意取低分可拦）。"""
    novel = tmp_settings.novel_path
    novel.mkdir(parents=True, exist_ok=True)
    (novel / "质量规则.json").write_text(json.dumps({
        "eval_gate": {"enabled": True, "threshold": threshold,
                      "weights": {"连贯性": 1.0, "人物一致性": 1.0}},
    }), encoding="utf-8")


def _patch_write(monkeypatch, tmp_settings, agent, score):
    """门禁测试公共注入：假 agent + 假评委返回固定分。"""
    monkeypatch.setattr(cli, "_build_agent", lambda settings, task="", need_style=True: (agent, WorkingMemory(), None))
    monkeypatch.setattr(cli, "evaluate", lambda *a, **kw: score)


def test_write_gate_low_score_confirm_discard(tmp_settings, fake_rag, monkeypatch, capsys):
    """A30/A31：低分 + 确认弃 -> 章节文件未写、未入库，run record 已落（弃而不失数据）。"""
    _write_gate_rules(tmp_settings)
    agent = WriteAgent(fake_rag)
    _patch_write(monkeypatch, tmp_settings, agent, {"连贯性": 2.0, "人物一致性": 2.0})
    monkeypatch.setattr(cli, "_gate_confirm", lambda prompt: "n")
    cli._do_write("写第5章：异乡风起", tmp_settings)

    assert list(tmp_settings.chapter_path.glob("*.md")) == []
    assert fake_rag.add_calls == []
    assert (tmp_settings.runs_path / "run_20260828_000001.json").exists()
    out = capsys.readouterr().out
    assert "已放弃保存本章" in out
    assert "本章未保存" in out


def test_write_gate_low_score_confirm_keep(tmp_settings, fake_rag, monkeypatch, capsys):
    """A30：低分 + 确认存 -> 章节照常写入并入库。"""
    _write_gate_rules(tmp_settings)
    agent = WriteAgent(fake_rag)
    _patch_write(monkeypatch, tmp_settings, agent, {"连贯性": 2.0, "人物一致性": 2.0})
    monkeypatch.setattr(cli, "_gate_confirm", lambda prompt: "y")
    cli._do_write("写第5章：异乡风起", tmp_settings)

    chapters = list(tmp_settings.chapter_path.glob("*.md"))
    assert len(chapters) == 1
    assert fake_rag.add_calls == [str(chapters[0])]
    out = capsys.readouterr().out
    assert "章节已存" in out


def test_write_gate_score_none_skips_gate(tmp_settings, fake_rag, monkeypatch):
    """A33：evaluate 失败/返回 None -> 无从判，跳过门禁照常存，不弹确认。"""
    _write_gate_rules(tmp_settings)
    agent = WriteAgent(fake_rag)
    _patch_write(monkeypatch, tmp_settings, agent, None)
    confirms = []
    monkeypatch.setattr(cli, "_gate_confirm", lambda prompt: confirms.append(prompt) or "n")
    cli._do_write("写第5章：异乡风起", tmp_settings)

    assert confirms == []
    assert len(list(tmp_settings.chapter_path.glob("*.md"))) == 1


def test_write_gate_exempt_forced_finalize(tmp_settings, fake_rag, monkeypatch):
    """D8：强制定稿豁免 -> 不弹确认直存，向量库照入。"""
    _write_gate_rules(tmp_settings)
    agent = WriteAgent(fake_rag, feedback="已达最大审稿次数，强制定稿")
    _patch_write(monkeypatch, tmp_settings, agent, {"连贯性": 2.0, "人物一致性": 2.0})
    confirms = []
    monkeypatch.setattr(cli, "_gate_confirm", lambda prompt: confirms.append(prompt) or "n")
    cli._do_write("写第5章：异乡风起", tmp_settings)

    assert confirms == []
    chapters = list(tmp_settings.chapter_path.glob("*.md"))
    assert len(chapters) == 1
    assert fake_rag.add_calls == [str(chapters[0])]


def test_write_gate_exempt_human_confirm(tmp_settings, fake_rag, monkeypatch):
    """D8：人工确认豁免 -> 不弹确认直存，向量库照入。"""
    _write_gate_rules(tmp_settings)
    agent = WriteAgent(fake_rag, feedback="审稿结果不可解析，人工确认：存")
    _patch_write(monkeypatch, tmp_settings, agent, {"连贯性": 2.0, "人物一致性": 2.0})
    confirms = []
    monkeypatch.setattr(cli, "_gate_confirm", lambda prompt: confirms.append(prompt) or "n")
    cli._do_write("写第5章：异乡风起", tmp_settings)

    assert confirms == []
    chapters = list(tmp_settings.chapter_path.glob("*.md"))
    assert len(chapters) == 1
    assert fake_rag.add_calls == [str(chapters[0])]


def test_write_gate_rules_not_configured(tmp_settings, fake_rag, monkeypatch):
    """规则未配置 -> 门禁全程不生效（低分也不弹确认，照常存）。"""
    agent = WriteAgent(fake_rag)
    _patch_write(monkeypatch, tmp_settings, agent, {"连贯性": 2.0, "人物一致性": 2.0})
    confirms = []
    monkeypatch.setattr(cli, "_gate_confirm", lambda prompt: confirms.append(prompt) or "n")
    cli._do_write("写第5章：异乡风起", tmp_settings)

    assert confirms == []
    assert len(list(tmp_settings.chapter_path.glob("*.md"))) == 1


def test_gate_ok_title_excluded_and_weighted():
    """A32：标题评分从 weights 硬排除；A30：加权分 Σw·s / Σw >= threshold 判定。"""
    rules = {"eval_gate": {"enabled": True, "threshold": 3.5,
                           "weights": {"连贯性": 1.0, "人物一致性": 2.0, "标题评分": 5.0}}}
    # 只有标题分 -> 无配权维度命中，放行（A32 + A33）
    assert cli._gate_ok({"标题评分": 1.0}, rules) is True
    # 标题再低也不拉低门禁：(3*1+3*2)/3=3.0 < 3.5 -> 拦
    assert cli._gate_ok({"连贯性": 3.0, "人物一致性": 3.0, "标题评分": 1.0}, rules) is False
    # (4*1+3*2)/3≈3.33 < 3.5 -> 拦；标题 5 分不参与拉分
    assert cli._gate_ok({"连贯性": 4.0, "人物一致性": 3.0, "标题评分": 5.0}, rules) is False
    # (4*1+4*2)/3=4.0 >= 3.5 -> 过
    assert cli._gate_ok({"连贯性": 4.0, "人物一致性": 4.0}, rules) is True


def test_gate_ok_degenerate_inputs():
    """缺规则 / 未启用 / 无阈值 / score None / 无配权维命中 -> 一律放行（A33）。"""
    rules = {"eval_gate": {"enabled": True, "threshold": 3.5, "weights": {"连贯性": 1.0}}}
    assert cli._gate_ok({"连贯性": 1.0}, None) is True            # 未配置
    assert cli._gate_ok({"连贯性": 1.0}, {}) is True               # 无 eval_gate 节
    assert cli._gate_ok({"连贯性": 1.0},
                        {"eval_gate": {"enabled": False, "threshold": 3.5}}) is True
    assert cli._gate_ok({"连贯性": 1.0},
                        {"eval_gate": {"enabled": True, "weights": {"连贯性": 1.0}}}) is True
    assert cli._gate_ok(None, rules) is True                       # 评测缝（evaluate None）
    assert cli._gate_ok({"节奏": 1.0}, rules) is True             # 无配权维命中
    assert cli._gate_ok({"连贯性": 1.0}, rules) is False           # 对照：低分确实拦


# ---------- refine 门禁同构（1.1 T8 / D8）----------
class GateRefineAgent:
    """精修替身：refine() 返回 passed 定稿（final/feedback 可配）。"""

    def __init__(self, rag, final="新正文。", feedback="审稿通过：ok"):
        self.rag = rag
        self.instruction = ""
        self.final = final
        self.feedback = feedback

    def refine(self, content, task, run_id=None, temperature=0.7):
        state = PipelineState(task=task)
        state.draft = content
        state.polished = self.final
        state.final_chapter = self.final
        state.feedback = self.feedback
        state.round = 2
        state.log = ["[reviewer] " + self.feedback]
        record = {
            "run_id": "refine_gate", "task": task, "timestamp": "",
            "config": {}, "initial_state": {}, "steps": [], "final_state": {},
        }
        return state, record

    def summarize_chapter(self, chapter_text, max_tokens=1024):
        return "第5章精修后的摘要。"


def _run_refine_gated(monkeypatch, tmp_settings, fake_rag, agent, score, confirm):
    """建目标文件 + 注入替身后跑一次 _do_refine，返回章节路径。"""
    novel = tmp_settings.novel_path
    novel.mkdir(parents=True, exist_ok=True)
    chap = novel / "第05章-异乡风起.md"
    chap.write_text("旧正文。", encoding="utf-8")
    monkeypatch.setattr(cli, "_build_agent", lambda settings, task="", need_style=True: (agent, WorkingMemory(), None))
    monkeypatch.setattr(cli, "evaluate", lambda *a, **kw: score)
    monkeypatch.setattr(cli, "_gate_confirm", lambda prompt: confirm)
    cli._do_refine([str(chap)], tmp_settings)
    return chap


def test_refine_gate_low_score_discard(tmp_settings, fake_rag, monkeypatch, capsys):
    """refine passed 分支同构：低分 + 弃 -> 原文件未动、不入库。"""
    _write_gate_rules(tmp_settings)
    chap = _run_refine_gated(monkeypatch, tmp_settings, fake_rag, GateRefineAgent(fake_rag),
                             {"连贯性": 2.0, "人物一致性": 2.0}, "n")
    assert chap.read_text(encoding="utf-8") == "旧正文。"
    assert fake_rag.add_calls == []
    out = capsys.readouterr().out
    assert "已放弃存回" in out


def test_refine_gate_low_score_keep(tmp_settings, fake_rag, monkeypatch):
    """refine passed 分支同构：低分 + 确认存 -> 照常覆盖存回并入库。"""
    _write_gate_rules(tmp_settings)
    chap = _run_refine_gated(monkeypatch, tmp_settings, fake_rag, GateRefineAgent(fake_rag),
                             {"连贯性": 2.0, "人物一致性": 2.0}, "y")
    assert chap.read_text(encoding="utf-8") == "新正文。"
    assert fake_rag.add_calls == [str(chap)]


def test_refine_gate_forced_not_gated(tmp_settings, fake_rag, monkeypatch):
    """D8：refine 强制定稿走 is_better 判优，不进门禁不弹确认。"""
    _write_gate_rules(tmp_settings)
    agent = GateRefineAgent(fake_rag, feedback="已达最大审稿次数，强制定稿")
    agent.is_better = lambda old, new, **kw: True
    chap = _run_refine_gated(monkeypatch, tmp_settings, fake_rag, agent,
                             {"连贯性": 2.0, "人物一致性": 2.0}, "n")  # 若弹确认会被拒
    assert chap.read_text(encoding="utf-8") == "新正文。"  # is_better=True 直存
    assert fake_rag.add_calls == [str(chap)]


# ---------- A23 命令层捕获 + Z7 状态行 ----------
def test_write_invalid_rules_json_caught(tmp_settings, fake_rag, monkeypatch, capsys):
    """A23：非法规则 JSON 在装配点 fail-fast，命令层捕获打印，REPL 不崩。"""
    novel = tmp_settings.novel_path
    novel.mkdir(parents=True, exist_ok=True)
    (novel / "质量规则.json").write_text("{不是json", encoding="utf-8")
    monkeypatch.setattr(cli, "evaluate", lambda *a, **kw: None)
    cli._do_write("写第5章：异乡风起", tmp_settings)  # 不应抛异常

    out = capsys.readouterr().out
    assert "不是合法 JSON" in out
    assert list(tmp_settings.chapter_path.glob("*.md")) == []


def test_status_shows_quality_lines(tmp_settings, capsys):
    """Z7：状态命令展示质量规则 / 人工语料两行（未配置给提示，已配置给词数）。"""
    cli._do_status(tmp_settings)
    out = capsys.readouterr().out
    assert "质量规则：未找到" in out
    assert "人工语料：未找到" in out

    _write_gate_rules(tmp_settings)
    (tmp_settings.novel_path / "质量规则.json").write_text(json.dumps(
        {"blacklist": ["一丝", "不禁"], "naming_redlines": {"forbidden": ["许风"]}}
    ), encoding="utf-8")
    cli._do_status(tmp_settings)
    out = capsys.readouterr().out
    assert "黑名单 3 词" in out


# ---------- 1.5 滚动注入（style-loop T3）----------
def test_build_agent_injects_recent_human(tmp_settings, monkeypatch):
    """B1：_build_agent 注入人工正文尾部 N 章进 agent.recent_human（目录为空 -> 空串）。"""
    d = tmp_settings.human_text_full
    d.mkdir(parents=True)
    (d / "第01章-风起.txt").write_text("第一章正文", encoding="utf-8")
    (d / "第02章-夜行.txt").write_text("第二章正文", encoding="utf-8")
    (d / "第03章-旧约.md").write_text("第三章正文", encoding="utf-8")

    captured: dict = {}

    class _Agent:
        def __init__(self, **kw):
            captured.update(kw)

    monkeypatch.setattr(cli, "LLMClient", lambda settings=None, profile=None: None)
    monkeypatch.setattr(cli, "RAGStore", lambda settings=None: None)
    monkeypatch.setattr(cli, "NovelAgent", _Agent)
    cli._build_agent(tmp_settings)
    assert captured["recent_human"] == "第一章正文\n\n第二章正文\n\n第三章正文"

    # B2 降级：目录不存在 -> 空串（writer prompt 与现状一致）
    s2 = Settings(
        ark_api_key="k",
        repo_root=tmp_settings.repo_root,
        novel_dir=str(tmp_settings.repo_root / "novel2"),
    )
    cli._build_agent(s2)
    assert captured["recent_human"] == ""


def test_status_shows_style_injection_lines(tmp_settings, capsys):
    """B6：状态命令展示滚动注入行（空目录/生效/禁用三态）。"""
    cli._do_status(tmp_settings)  # 目录不存在
    out = capsys.readouterr().out
    assert "滚动注入：人工语料为空，本次不注入" in out

    d = tmp_settings.human_text_full
    d.mkdir(parents=True)
    (d / "第01章-风起.txt").write_text("第一章正文", encoding="utf-8")
    cli._do_status(tmp_settings)
    out = capsys.readouterr().out
    assert "滚动注入：最近 3 章 · 每章 1000 字" in out

    s0 = Settings(
        ark_api_key="k",
        repo_root=tmp_settings.repo_root,
        novel_dir=tmp_settings.novel_dir,
        style_recent_n=0,
    )
    cli._do_status(s0)
    out = capsys.readouterr().out
    assert "滚动注入：已禁用" in out


# ---------- 1.6 de-AI pass（style-loop T6）----------
def _write_deai_rules(tmp_settings, threshold=60):
    """往临时小说目录写只含 deai 键的质量规则 JSON。"""
    novel = tmp_settings.novel_path
    novel.mkdir(parents=True, exist_ok=True)
    (novel / "质量规则.json").write_text(json.dumps(
        {"deai": {"enabled": True, "threshold": threshold}}
    ), encoding="utf-8")


class DeaiAgent(WriteAgent):
    """带 deai_refine 的替身：返回固定改后稿，记录调用。"""

    def __init__(self, rag, final="AI味重的稿子，一丝哀伤。", new_text="人味重的稿子。"):
        super().__init__(rag, final=final)
        self.deai_calls = []
        self.new_text = new_text

    def deai_refine(self, text, issues):
        self.deai_calls.append((text, issues))
        return self.new_text, len(issues)


def _patch_deai(monkeypatch, final, new_text, before, after, issues):
    """de-AI 测试缝：固定 AI 味分（按文本分流）与机械 issue（design §6）。"""
    monkeypatch.setattr(cli, "load_baseline", lambda settings: None)

    def fake_score(text, rules, baseline=None):
        return {"score": before if text == final else after}

    monkeypatch.setattr(cli, "ai_flavor_score", fake_score)
    monkeypatch.setattr(cli, "run_checks", lambda text, rules: issues)


def _run_deai_write(monkeypatch, tmp_settings, agent):
    """_do_write 的 de-AI 测试公共注入：替身 agent + 跳过评测（同 _patch_write 模式）。"""
    monkeypatch.setattr(cli, "_build_agent", lambda settings, task="", need_style=True: (agent, WorkingMemory(), None))
    monkeypatch.setattr(cli, "evaluate", lambda *a, **kw: None)
    cli._do_write("写第5章：异乡风起", tmp_settings)


def test_write_deai_accepted(tmp_settings, fake_rag, monkeypatch):
    """B9/B13/B14：超阈值+分降 -> final_chapter 为改后稿，record 留痕 accepted。"""
    _write_deai_rules(tmp_settings)
    agent = DeaiAgent(fake_rag)
    issues = [{"quote": "AI味重的稿子", "problem": "黑名单词「一丝」", "fix": "换成具体描写"}]
    _patch_deai(monkeypatch, agent.final, agent.new_text, 80, 50, issues)
    _run_deai_write(monkeypatch, tmp_settings, agent)

    assert agent.deai_calls == [(agent.final, issues)]      # 恰一次，只传可定位
    chapters = list(tmp_settings.chapter_path.glob("*.md"))
    assert len(chapters) == 1
    assert chapters[0].read_text(encoding="utf-8").endswith(agent.new_text)  # 存的是改后稿
    saved = load_run("run_20260828_000001", tmp_settings)
    assert saved["final_state"]["deai"] == {
        "before": 80, "after": 50, "spans": 1, "accepted": True}
    assert saved["final_state"]["final_chapter"] == agent.new_text


def test_write_deai_not_lowered_rejected(tmp_settings, fake_rag, monkeypatch, capsys):
    """B13/D5：分不降（after>=before）-> 回退保留原稿，accepted=False 留痕。"""
    _write_deai_rules(tmp_settings)
    agent = DeaiAgent(fake_rag)
    issues = [{"quote": "AI味重的稿子", "problem": "p", "fix": "f"}]
    _patch_deai(monkeypatch, agent.final, agent.new_text, 80, 85, issues)
    _run_deai_write(monkeypatch, tmp_settings, agent)

    assert len(agent.deai_calls) == 1                        # pass 跑了
    chapters = list(tmp_settings.chapter_path.glob("*.md"))
    assert chapters[0].read_text(encoding="utf-8").endswith(agent.final)  # 原稿保留
    saved = load_run("run_20260828_000001", tmp_settings)
    assert saved["final_state"]["deai"]["accepted"] is False
    assert saved["final_state"]["final_chapter"] == agent.final
    assert "未降分" in capsys.readouterr().out


def test_write_deai_below_threshold_skipped(tmp_settings, fake_rag, monkeypatch):
    """B17：未超阈值 -> deai_refine 零调用、record 无 deai 键。"""
    _write_deai_rules(tmp_settings)
    agent = DeaiAgent(fake_rag)
    _patch_deai(monkeypatch, agent.final, agent.new_text, 50, 10,
                [{"quote": "AI味重的稿子", "problem": "p", "fix": "f"}])
    _run_deai_write(monkeypatch, tmp_settings, agent)

    assert agent.deai_calls == []
    saved = load_run("run_20260828_000001", tmp_settings)
    assert "deai" not in saved["final_state"]
    chapters = list(tmp_settings.chapter_path.glob("*.md"))
    assert chapters[0].read_text(encoding="utf-8").endswith(agent.final)


def test_write_deai_no_key_current_behavior(tmp_settings, fake_rag, monkeypatch):
    """B18：规则无 deai 键 -> 零行为（与 quality-gate 完成态一致）。"""
    _write_gate_rules(tmp_settings)  # 只有 eval_gate，无 deai 键
    agent = DeaiAgent(fake_rag)
    _patch_deai(monkeypatch, agent.final, agent.new_text, 90, 10,
                [{"quote": "AI味重的稿子", "problem": "p", "fix": "f"}])
    _run_deai_write(monkeypatch, tmp_settings, agent)

    assert agent.deai_calls == []
    saved = load_run("run_20260828_000001", tmp_settings)
    assert "deai" not in saved["final_state"]
    assert len(list(tmp_settings.chapter_path.glob("*.md"))) == 1


def test_write_deai_no_locatable_issues_skipped(tmp_settings, fake_rag, monkeypatch, capsys):
    """B17：超阈值但无可定位句 -> skipped 留痕零 LLM。"""
    _write_deai_rules(tmp_settings)
    agent = DeaiAgent(fake_rag)
    # quote 为空（metaphor 风格）与非子串 -> 全部不可定位
    _patch_deai(monkeypatch, agent.final, agent.new_text, 80, 50,
                [{"quote": "", "problem": "比喻密度过高", "fix": "删减"},
                 {"quote": "不在原文的句子", "problem": "p", "fix": "f"}])
    _run_deai_write(monkeypatch, tmp_settings, agent)

    assert agent.deai_calls == []
    saved = load_run("run_20260828_000001", tmp_settings)
    assert saved["final_state"]["deai"]["skipped"] == "无可定位问题句"
    chapters = list(tmp_settings.chapter_path.glob("*.md"))
    assert chapters[0].read_text(encoding="utf-8").endswith(agent.final)
    assert "无可定位问题句" in capsys.readouterr().out


# ---------- 1.6 去AI 手动命令（style-loop T7）----------
def _mk_deai_chapter(tmp_settings):
    """建一个含黑名单词的目标章节文件，返回路径。"""
    novel = tmp_settings.novel_path
    novel.mkdir(parents=True, exist_ok=True)
    chap = novel / "第05章-异乡风起.md"
    chap.write_text("AI味重的稿子，一丝哀伤。\n\n他走了。\n", encoding="utf-8")
    return chap


def _run_deai_cmd(monkeypatch, tmp_settings, agent, confirm, before=80, after=50):
    """注入替身与固定分后跑一次 去AI 命令。"""
    chap = _mk_deai_chapter(tmp_settings)
    issues = [{"quote": "AI味重的稿子", "problem": "黑名单词「一丝」", "fix": "换成具体描写"}]
    _patch_deai(monkeypatch, "AI味重的稿子，一丝哀伤。\n\n他走了。\n",
                agent.new_text, before, after, issues)
    monkeypatch.setattr(cli, "_build_agent", lambda settings, task="", need_style=True: (agent, WorkingMemory(), None))
    monkeypatch.setattr(cli, "_deai_confirm", lambda prompt: confirm)
    cli._do_deai([str(chap)], tmp_settings)
    return chap


def test_deai_cmd_confirm_y_saves_and_indexes(tmp_settings, fake_rag, monkeypatch, capsys):
    """B15/D7：confirm y -> 存回改后稿 + 索引更新，不落 run record。"""
    _write_deai_rules(tmp_settings)
    agent = DeaiAgent(fake_rag)
    chap = _run_deai_cmd(monkeypatch, tmp_settings, agent, "y")

    assert chap.read_text(encoding="utf-8") == agent.new_text   # 覆盖存回
    assert fake_rag.add_calls == [str(chap)]                     # 索引更新
    out = capsys.readouterr().out
    assert "AI味分：80 -> 50（下降）" in out
    assert "已存回" in out
    assert list(tmp_settings.runs_path.glob("*.json")) == []      # D8：不落 run record


def test_deai_cmd_confirm_n_keeps_file(tmp_settings, fake_rag, monkeypatch, capsys):
    """B15：confirm n / EOF -> 原文件不动、不入库。"""
    _write_deai_rules(tmp_settings)
    agent = DeaiAgent(fake_rag)
    original = "AI味重的稿子，一丝哀伤。\n\n他走了。\n"
    chap = _run_deai_cmd(monkeypatch, tmp_settings, agent, "n")

    assert chap.read_text(encoding="utf-8") == original
    assert fake_rag.add_calls == []
    assert "已放弃" in capsys.readouterr().out


def test_deai_cmd_score_not_lowered_shown_honestly(tmp_settings, fake_rag, monkeypatch, capsys):
    """Z3：分不降也如实展示（人不被阈值绑架），confirm y 仍可存回。"""
    _write_deai_rules(tmp_settings)
    agent = DeaiAgent(fake_rag)
    chap = _run_deai_cmd(monkeypatch, tmp_settings, agent, "y", before=50, after=70)

    out = capsys.readouterr().out
    assert "AI味分：50 -> 70" in out
    assert "未下降" in out
    assert chap.read_text(encoding="utf-8") == agent.new_text   # 人拍板可存


def test_deai_cmd_no_locatable_issues_exits(tmp_settings, fake_rag, monkeypatch, capsys):
    """B17：无可定位问题句 -> 提示退出，不空烧 LLM。"""
    chap = _mk_deai_chapter(tmp_settings)
    agent = DeaiAgent(fake_rag)
    _patch_deai(monkeypatch, "x", "y", 80, 50, [{"quote": "", "problem": "p", "fix": "f"}])
    monkeypatch.setattr(cli, "_build_agent", lambda settings, task="", need_style=True: (agent, WorkingMemory(), None))
    cli._do_deai([str(chap)], tmp_settings)

    assert agent.deai_calls == []
    assert "无可定位问题句" in capsys.readouterr().out
    assert chap.read_text(encoding="utf-8") == "AI味重的稿子，一丝哀伤。\n\n他走了。\n"


def test_deai_cmd_file_not_found(tmp_settings, fake_rag, monkeypatch, capsys):
    """文件不存在 -> 报错退出。"""
    agent = DeaiAgent(fake_rag)
    monkeypatch.setattr(cli, "_build_agent", lambda settings, task="", need_style=True: (agent, WorkingMemory(), None))
    cli._do_deai([str(tmp_settings.novel_path / "不存在.md")], tmp_settings)
    assert "找不到文件" in capsys.readouterr().out


# ---------- 2.2 _write_one 拆层（throughput W5，D9/T7/T17/T27）----------
def _write_one_with(monkeypatch, tmp_settings, agent, task="写第5章：异乡风起", plan=""):
    """替换 _build_agent / evaluate 后跑一次 _write_one，返回结局。"""
    monkeypatch.setattr(cli, "_build_agent", lambda settings, task="", need_style=True: (agent, WorkingMemory(), None))
    monkeypatch.setattr(cli, "evaluate", lambda *a, **kw: None)
    return cli._write_one(task, tmp_settings, plan=plan)


def test_write_one_outcome_saved(tmp_settings, fake_rag, monkeypatch):
    """结局枚举：正常定稿存盘 -> saved。"""
    agent = WriteAgent(fake_rag)
    assert _write_one_with(monkeypatch, tmp_settings, agent) == "saved"
    assert len(list(tmp_settings.chapter_path.glob("*.md"))) == 1


def test_write_one_outcome_rejected(tmp_settings, fake_rag, monkeypatch, capsys):
    """结局枚举：未定稿（final_chapter 空）-> rejected（无存盘）。"""
    agent = WriteAgent(fake_rag, final="", feedback="审稿不通过：弃")
    assert _write_one_with(monkeypatch, tmp_settings, agent) == "rejected"
    assert list(tmp_settings.chapter_path.glob("*.md")) == []


def test_write_one_outcome_failed(tmp_settings, monkeypatch, capsys):
    """结局枚举：agent.run 抛异常 -> failed（命令层兜住不崩）。"""
    class BoomAgent(WriteAgent):
        def run(self, task, run_id=None, temperature=0.9):
            raise RuntimeError("网关 500")

    assert _write_one_with(monkeypatch, tmp_settings, BoomAgent(None)) == "failed"
    assert "创作失败" in capsys.readouterr().out


def test_write_one_interrupted_no_save_no_wm(tmp_settings, fake_rag, monkeypatch, capsys):
    """T7：Ctrl-C 落在 agent.run -> interrupted，不存盘不更新 wm。"""
    class InterruptAgent(WriteAgent):
        def run(self, task, run_id=None, temperature=0.9):
            raise KeyboardInterrupt

    wm = WorkingMemory()
    monkeypatch.setattr(cli, "_build_agent", lambda settings, task="", need_style=True: (InterruptAgent(fake_rag), wm, None))
    monkeypatch.setattr(cli, "evaluate", lambda *a, **kw: None)
    assert cli._write_one("写第5章：异乡风起", tmp_settings) == "interrupted"
    assert list(tmp_settings.chapter_path.glob("*.md")) == []  # 未存盘
    assert wm.current_chapter is None  # 工作记忆未推进
    out = capsys.readouterr().out
    assert "已打断" in out


def test_write_one_interrupted_in_post_run_stages(tmp_settings, fake_rag, monkeypatch, capsys):
    """T7（D5 修订）：打断落在 agent.run 之后的评测阶段同样被整体兜住。"""
    agent = WriteAgent(fake_rag)

    def boom(*a, **kw):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "_build_agent", lambda settings, task="", need_style=True: (agent, WorkingMemory(), None))
    monkeypatch.setattr(cli, "evaluate", boom)
    assert cli._write_one("写第5章：异乡风起", tmp_settings) == "interrupted"
    assert list(tmp_settings.chapter_path.glob("*.md")) == []  # 未走到存盘


def test_write_one_gate_reject_by_answer_n(tmp_settings, fake_rag, monkeypatch, capsys):
    """门禁弃 -> rejected（结局口径含审稿人工弃之后的门禁弃）。"""
    agent = WriteAgent(fake_rag)
    monkeypatch.setattr(cli, "load_quality_rules", lambda settings: {"eval_gate": {"enabled": True, "threshold": 3.5, "weights": {"剧情": 1}}})
    monkeypatch.setattr(cli, "evaluate", lambda *a, **kw: {"剧情": 1})  # 低于阈值
    monkeypatch.setattr(cli, "_gate_confirm", lambda prompt: "n")
    monkeypatch.setattr(cli, "_build_agent", lambda settings, task="", need_style=True: (agent, WorkingMemory(), None))
    assert cli._write_one("写第5章：异乡风起", tmp_settings) == "rejected"
    assert list(tmp_settings.chapter_path.glob("*.md")) == []


def test_write_one_passes_plan_to_run(tmp_settings, fake_rag, monkeypatch):
    """T12/T17：plan 透传进 agent.run。"""
    seen = {}

    class PlanAgent(WriteAgent):
        def run(self, task, run_id=None, temperature=0.9, plan=""):
            seen["plan"] = plan
            return super().run(task, run_id, temperature)

    _write_one_with(monkeypatch, tmp_settings, PlanAgent(fake_rag), plan="核心事件：X")
    assert seen["plan"] == "核心事件：X"


def test_do_write_thin_shell_unchanged(tmp_settings, fake_rag, monkeypatch, capsys):
    """T27：_do_write 薄壳 -- 行为与拆层前一致（存盘 + 尾部展示照常打印）。"""
    agent = WriteAgent(fake_rag)
    monkeypatch.setattr(cli, "_build_agent", lambda settings, task="", need_style=True: (agent, WorkingMemory(), None))
    monkeypatch.setattr(cli, "evaluate", lambda *a, **kw: None)
    cli._do_write("写第5章：异乡风起", tmp_settings)
    out = capsys.readouterr().out
    assert "章节已存" in out and "=== 最终章节 ===" in out
    assert len(list(tmp_settings.chapter_path.glob("*.md"))) == 1


# ---------- 2.2 批量连写 + 分发（throughput W6，D10/D11/T13-T25）----------
_BATCH_PLAN_MD = """# 每章规划

| 章 | 标题 | 核心事件 | 天气 |
| --- | --- | --- | --- |
| 5 | 风起 | 主角遇袭 | 雨 |
| 6 | 云涌 | 追查线索 | 晴 |
| 7 | 山雨 | 入山 | 阴 |
"""


class _RecordingAgent(WriteAgent):
    """替身 agent：记录 run(task, plan) 调用序（批量任务串与规划注入断言用）。"""

    def __init__(self, rag):
        super().__init__(rag)
        self.runs = []

    def run(self, task, run_id=None, temperature=0.9, plan=""):
        self.runs.append((task, plan))
        return super().run(task, run_id, temperature)


def _mk_plan_file(tmp_settings, text=_BATCH_PLAN_MD):
    tmp_settings.novel_path.mkdir(parents=True, exist_ok=True)
    tmp_settings.plan_full.write_text(text, encoding="utf-8")


def test_batch_plan_driven_titles_plans_continuity(tmp_settings, fake_rag, monkeypatch, capsys):
    """无标题主路径：章纲供标题+规划；章间 wm.current_chapter 递增、每章入库各一次（T21）。"""
    _mk_plan_file(tmp_settings)
    wm = WorkingMemory()
    agent = _RecordingAgent(fake_rag)
    monkeypatch.setattr(cli, "_build_agent", lambda settings, task="", need_style=True: (agent, wm, None))
    monkeypatch.setattr(cli, "evaluate", lambda *a, **kw: None)
    monkeypatch.setattr(cli, "_gate_confirm", lambda prompt: "y")
    cli._do_write_batch("写第5-6章", tmp_settings, auto=False)

    assert agent.runs == [
        ("写第5章：风起", "核心事件：主角遇袭\n天气：雨"),
        ("写第6章：云涌", "核心事件：追查线索\n天气：晴"),
    ]
    assert len(list(tmp_settings.chapter_path.glob("*.md"))) == 2  # 每章落盘
    assert wm.current_chapter == 6  # 工作记忆章间推进（T21）
    assert len(fake_rag.add_calls) == 2  # 每章 rag.add_document 各一次（T21）
    out = capsys.readouterr().out
    # T24 预算提示（C13：口径含伏笔+弧光抽取调用，7-10 -> 8-11）
    assert "批量连写：第5-6章，共 2 章" in out and "8-11 次" in out


def test_batch_missing_chapter_zero_calls(tmp_settings, monkeypatch, capsys):
    """T14：无标题主路径缺章报错，零 _write_one 调用。"""
    _mk_plan_file(tmp_settings)  # 只有 5-7 章
    called = []
    monkeypatch.setattr(cli, "_write_one", lambda *a, **kw: called.append(a) or "saved")
    cli._do_write_batch("写第5-9章", tmp_settings, auto=False)
    assert called == []
    assert "缺章" in capsys.readouterr().out


def test_batch_template_fallback_ordinal_suffix(tmp_settings, fake_rag, monkeypatch):
    """T13：带模板回落 = 模板+中文序数后缀；章纲存在该章则规划照注入。"""
    _mk_plan_file(tmp_settings)
    agent = _RecordingAgent(fake_rag)
    monkeypatch.setattr(cli, "_build_agent", lambda settings, task="", need_style=True: (agent, WorkingMemory(), None))
    monkeypatch.setattr(cli, "evaluate", lambda *a, **kw: None)
    cli._do_write_batch("写第5-6章：夜行", tmp_settings, auto=True)

    assert agent.runs == [
        ("写第5章：夜行（一）", "核心事件：主角遇袭\n天气：雨"),
        ("写第6章：夜行（二）", "核心事件：追查线索\n天气：晴"),
    ]


def test_batch_default_confirm_n_stops(tmp_settings, monkeypatch, capsys):
    """T18：默认模式章间确认 n -> 停止，已完成章保留（第二章零调用）。"""
    _mk_plan_file(tmp_settings)
    called = []
    monkeypatch.setattr(cli, "_write_one", lambda task, settings, plan="": called.append(task) or "saved")
    monkeypatch.setattr(cli, "_gate_confirm", lambda prompt: "n")
    cli._do_write_batch("写第5-7章", tmp_settings, auto=False)
    assert called == ["写第5章：风起"]
    out = capsys.readouterr().out
    assert "已停止批量，已完成章节保留" in out


def test_batch_default_confirm_y_continues(tmp_settings, monkeypatch):
    """T18：默认模式 y 连写全部章。"""
    _mk_plan_file(tmp_settings)
    called = []
    monkeypatch.setattr(cli, "_write_one", lambda task, settings, plan="": called.append(task) or "saved")
    monkeypatch.setattr(cli, "_gate_confirm", lambda prompt: "y")
    cli._do_write_batch("写第5-7章", tmp_settings, auto=False)
    assert len(called) == 3


def test_batch_auto_rejected_interrupts(tmp_settings, monkeypatch, capsys):
    """T19：--auto 下 rejected -> 中断批量（fail-closed），后续章零调用。"""
    _mk_plan_file(tmp_settings)
    called = []
    monkeypatch.setattr(cli, "_write_one", lambda task, settings, plan="": called.append(task) or "rejected")
    cli._do_write_batch("写第5-7章", tmp_settings, auto=True)
    assert called == ["写第5章：风起"]
    out = capsys.readouterr().out
    assert "--auto 模式中断批量" in out and "已完成 0 章" in out


def test_batch_failed_interrupts(tmp_settings, monkeypatch):
    """T20：failed -> 中断批量（两模式同语义）。"""
    _mk_plan_file(tmp_settings)
    called = []
    monkeypatch.setattr(cli, "_write_one", lambda task, settings, plan="": called.append(task) or "failed")
    cli._do_write_batch("写第5-7章", tmp_settings, auto=False)
    assert len(called) == 1


def test_batch_interrupted_interrupts(tmp_settings, monkeypatch, capsys):
    """T22：interrupted -> 停止批量，已完成章节保留。"""
    _mk_plan_file(tmp_settings)
    called = []
    monkeypatch.setattr(cli, "_write_one", lambda task, settings, plan="": called.append(task) or "interrupted")
    cli._do_write_batch("写第5-7章", tmp_settings, auto=True)
    assert len(called) == 1
    assert "已完成章节保留" in capsys.readouterr().out


def test_batch_invalid_range_zero_calls(tmp_settings, monkeypatch, capsys):
    """T23：起>止 / 跨度超 batch_max 报错零调用。"""
    called = []
    monkeypatch.setattr(cli, "_write_one", lambda task, settings, plan="": called.append(task) or "saved")
    cli._do_write_batch("写第7-5章", tmp_settings, auto=False)
    cli._do_write_batch("写第5-20章", tmp_settings, auto=False)  # 16 章 > 默认 10
    assert called == []
    out = capsys.readouterr().out
    assert "大于结束章号" in out
    assert "NOVEL_BATCH_MAX" in out


def test_batch_single_chapter_range_degenerates(tmp_settings, monkeypatch):
    """T25：单章区间（5-5）退化为一次 _write_one（走章纲主路径）。"""
    _mk_plan_file(tmp_settings)
    called = []
    monkeypatch.setattr(cli, "_write_one", lambda task, settings, plan="": called.append((task, plan)) or "saved")
    cli._do_write_batch("写第5-5章", tmp_settings, auto=False)
    assert called == [("写第5章：风起", "核心事件：主角遇袭\n天气：雨")]


# ---------- 写作命令分发（D7/T15/互斥性）----------
def _capture_dispatch(monkeypatch, tmp_settings):
    """替换 _do_write/_do_write_batch，捕获分发去向。"""
    got = {"one": [], "batch": []}
    monkeypatch.setattr(cli, "_do_write", lambda task, settings, plan="": got["one"].append((task, plan)))
    monkeypatch.setattr(cli, "_do_write_batch", lambda task, settings, auto: got["batch"].append((task, auto)))
    return got


def test_dispatch_range_goes_batch(tmp_settings, monkeypatch):
    got = _capture_dispatch(monkeypatch, tmp_settings)
    cli._dispatch_write("写第5-10章", tmp_settings)
    assert got["batch"] == [("写第5-10章", False)]
    assert got["one"] == []


def test_dispatch_range_auto_suffix_stripped(tmp_settings, monkeypatch):
    got = _capture_dispatch(monkeypatch, tmp_settings)
    cli._dispatch_write("写第5-10章 --auto", tmp_settings)
    assert got["batch"] == [("写第5-10章", True)]


def test_dispatch_single_no_title_uses_plan(tmp_settings, monkeypatch):
    """T15：写第6章 -> 章纲取标题与规划，等价于敲了带标题命令。"""
    _mk_plan_file(tmp_settings)
    got = _capture_dispatch(monkeypatch, tmp_settings)
    cli._dispatch_write("写第6章", tmp_settings)
    assert got["one"] == [("写第6章：云涌", "核心事件：追查线索\n天气：晴")]
    assert got["batch"] == []


def test_dispatch_single_no_title_missing_plan(tmp_settings, monkeypatch, capsys):
    """T15：无标题且章纲缺章 -> 报错提示补标题，零调用。"""
    _mk_plan_file(tmp_settings)  # 只有 5-7
    got = _capture_dispatch(monkeypatch, tmp_settings)
    cli._dispatch_write("写第9章", tmp_settings)
    assert got["one"] == [] and got["batch"] == []
    assert "无标题" in capsys.readouterr().out


def test_dispatch_titled_single_never_batch(tmp_settings, monkeypatch):
    """互斥护栏：写第5章：标题 不进批量、无章纲时零变化（现状 _do_write 直达）。"""
    got = _capture_dispatch(monkeypatch, tmp_settings)
    cli._dispatch_write("写第5章：异乡风起", tmp_settings)
    assert got["batch"] == []
    assert got["one"] == [("写第5章：异乡风起", "")]


def test_dispatch_single_range_beats_no_title(tmp_settings, monkeypatch):
    """分发序护栏：写第5-5章 走区间（退化单章），不被单章无标题分支截走。"""
    _mk_plan_file(tmp_settings)
    got = _capture_dispatch(monkeypatch, tmp_settings)
    cli._dispatch_write("写第5-5章", tmp_settings)
    assert got["batch"] == [("写第5-5章", False)]
    assert got["one"] == []


# ---------- 伏笔抽取回路（3.1 foreshadow，F2/F3/F4/F13/F16/Z8）----------
class ForeshadowAgent(_RecordingAgent):
    """替身 agent：extract_foreshadowing 按 result 返回或抛错，并记录调用入参。

    继承 _RecordingAgent：run() 收 plan 关键字（批量路径会传）。
    """

    def __init__(self, rag, result=None):
        super().__init__(rag)
        self.result = result if result is not None else {"new": [], "resolved": []}
        self.extract_calls = []

    def extract_foreshadowing(self, chapter_text, unresolved, chapter_no=None):
        self.extract_calls.append({
            "chapter_no": chapter_no,
            "descs": [e.get("desc") if isinstance(e, dict) else e for e in (unresolved or [])],
        })
        if isinstance(self.result, Exception):
            raise self.result
        return dict(self.result)


def _run_extract(monkeypatch, tmp_settings, agent, wm, task="写第5章：异乡风起"):
    monkeypatch.setattr(cli, "_build_agent", lambda settings, task="", need_style=True: (agent, wm, None))
    monkeypatch.setattr(cli, "evaluate", lambda *a, **kw: None)
    cli._do_write(task, tmp_settings)


def test_write_extracts_and_records(tmp_settings, fake_rag, monkeypatch, capsys):
    """F1/F2/F4：抽取成功 -> new 入 wm / resolved 出列入归档 / record 留痕且落盘可查。"""
    wm = WorkingMemory()
    wm.unresolved_foreshadowing = [{"desc": "怀表停在十点", "chapter": 3}]
    agent = ForeshadowAgent(fake_rag, {"new": [{"desc": "林晚没拆那封信"}], "resolved": [1]})
    _run_extract(monkeypatch, tmp_settings, agent, wm)

    assert wm.unresolved_foreshadowing == [{"desc": "林晚没拆那封信", "chapter": 5}]
    # F15：回收不是物理删除，而是进归档（可人工找回）
    assert wm.resolved_foreshadowing == [
        {"desc": "怀表停在十点", "chapter": 3, "resolved_chapter": 5}
    ]
    assert agent.extract_calls[0]["chapter_no"] == 5
    assert agent.extract_calls[0]["descs"] == ["怀表停在十点"]   # 抽取拿全量清单

    saved = load_run("run_20260828_000001", tmp_settings)         # A1：补写后真读得到
    # 留痕为抽取原始返回（替身直返，未经真实解析；真实调用的新条目会带 chapter）
    assert saved["foreshadow"]["new"] == [{"desc": "林晚没拆那封信"}]
    assert saved["foreshadow"]["resolved"] == [1]
    assert saved["foreshadow"]["unresolved_after"] == 1
    assert "🧵 伏笔：+1 回收 1（未回收 1）" in capsys.readouterr().out


def test_write_extract_failure_keeps_progress(tmp_settings, fake_rag, monkeypatch, capsys):
    """F3/A2/Z8：抽取抛异常 -> 伏笔不变、进度与摘要照常落盘、record 留 error 键。"""
    wm = WorkingMemory()
    wm.unresolved_foreshadowing = [{"desc": "怀表停在十点", "chapter": 3}]
    agent = ForeshadowAgent(fake_rag, RuntimeError("网关 502"))
    _run_extract(monkeypatch, tmp_settings, agent, wm)

    assert wm.unresolved_foreshadowing == [{"desc": "怀表停在十点", "chapter": 3}]
    assert wm.resolved_foreshadowing == []
    assert wm.current_chapter == 5 and wm.last_plot_point == "摘要：风起。"  # A2：进度未被吞
    assert load_working_memory(tmp_settings).current_chapter == 5            # 且已落盘

    saved = load_run("run_20260828_000001", tmp_settings)
    assert saved["foreshadow"] == {"error": "网关 502"}          # Z8：分得清「没埋」与「挂了」
    out = capsys.readouterr().out
    assert "伏笔抽取跳过：网关 502" in out


def test_write_foreshadow_disabled_zero_calls(tmp_settings, fake_rag, monkeypatch):
    """F12：NOVEL_FORESHADOW=0 -> 零抽取调用，record 不留 foreshadow 键。"""
    settings = dataclasses.replace(tmp_settings, foreshadow_enabled=False)
    agent = ForeshadowAgent(fake_rag)
    _run_extract(monkeypatch, settings, agent, WorkingMemory())

    assert agent.extract_calls == []
    assert "foreshadow" not in load_run("run_20260828_000001", settings)
    assert load_working_memory(settings).current_chapter == 5     # 写作主流程不受影响


def test_write_same_chapter_rerun_overwrites(tmp_settings, fake_rag, monkeypatch):
    """F16：同章重写覆盖该章旧条目；manual 人工条目不被清洗。"""
    wm = WorkingMemory()
    agent = ForeshadowAgent(fake_rag, {"new": [{"desc": "A"}, {"desc": "B"}], "resolved": []})
    _run_extract(monkeypatch, tmp_settings, agent, wm)
    assert [e["desc"] for e in wm.unresolved_foreshadowing] == ["A", "B"]
    wm.add_foreshadowing("人工补的线", chapter=5, manual=True)

    agent.result = {"new": [{"desc": "A2"}], "resolved": []}       # 重跑第 5 章
    _run_extract(monkeypatch, tmp_settings, agent, wm)
    assert [e["desc"] for e in wm.unresolved_foreshadowing] == ["人工补的线", "A2"]


def test_write_num_none_keeps_untagged_entries(tmp_settings, fake_rag, monkeypatch):
    """F16 守卫：任务串解析不出章号（num=None）时不清洗，无章号旧条目不被抹掉。"""
    wm = WorkingMemory()
    wm.unresolved_foreshadowing = [{"desc": "旧版字符串数据", "chapter": None}]
    agent = ForeshadowAgent(fake_rag, {"new": [{"desc": "番外新线"}], "resolved": []})
    _run_extract(monkeypatch, tmp_settings, agent, wm, task="写一段番外")

    descs = [e["desc"] for e in wm.unresolved_foreshadowing]
    assert descs == ["旧版字符串数据", "番外新线"]       # 追加，不清洗
    assert agent.extract_calls[0]["chapter_no"] is None


def test_batch_foreshadow_continuity(tmp_settings, fake_rag, monkeypatch):
    """C1/F2：批量两章走「落盘 -> 再读回」链，第二章抽取输入含第一章新增的伏笔。"""
    _mk_plan_file(tmp_settings)
    agent = ForeshadowAgent(fake_rag, {"new": [{"desc": "第一章埋的线"}], "resolved": []})
    # 同真实 _build_agent：每章重建 agent、wm 重新读盘（非同实例传递）
    monkeypatch.setattr(
        cli, "_build_agent",
        lambda settings, task="", need_style=True: (agent, load_working_memory(settings), None),
    )
    monkeypatch.setattr(cli, "evaluate", lambda *a, **kw: None)
    monkeypatch.setattr(cli, "_gate_confirm", lambda prompt: "y")
    cli._do_write_batch("写第5-6章", tmp_settings, auto=False)

    assert len(agent.extract_calls) == 2
    assert agent.extract_calls[0]["descs"] == []                       # 首章清单空
    assert agent.extract_calls[1]["descs"] == ["第一章埋的线"]           # 章间连续性
    wm = load_working_memory(tmp_settings)
    assert [e["chapter"] for e in wm.unresolved_foreshadowing] == [5, 6]  # 埋设章号逐章记录


# ---------- 伏笔 REPL 命令（3.1 F9/F10/F15/F17/D6/Z4）----------
def test_foreshadow_command_lists_and_adds(tmp_settings, capsys):
    """F9/F10：列表 -> 加（manual 标记 + 落盘）-> 再列表可见。"""
    cli._do_foreshadow([], tmp_settings)
    assert "未回收伏笔：无" in capsys.readouterr().out

    cli._do_foreshadow(["加", "抽屉里的怀表停在十点"], tmp_settings)
    out = capsys.readouterr().out
    assert "已补录 1 条" in out and "抽屉里的怀表停在十点" in out

    wm = load_working_memory(tmp_settings)
    assert wm.unresolved_foreshadowing == [
        {"desc": "抽屉里的怀表停在十点", "chapter": None, "manual": True}  # 首章前 current_chapter 为空
    ]
    cli._do_foreshadow([], tmp_settings)
    listed = capsys.readouterr().out
    assert "未回收伏笔（共 1 条）：" in listed and "1.抽屉里的怀表停在十点" in listed


def test_foreshadow_delete_archives(tmp_settings, capsys):
    """F15：删 = 出列入归档（不物理删除）；多编号一次给全不错位。"""
    wm = WorkingMemory()
    wm.current_chapter = 5
    wm.unresolved_foreshadowing = [{"desc": f"v{i}", "chapter": i} for i in range(1, 5)]
    save_working_memory(wm, tmp_settings)

    cli._do_foreshadow(["删", "2", "4"], tmp_settings)
    assert "已标记回收 2 条" in capsys.readouterr().out

    wm2 = load_working_memory(tmp_settings)
    assert [e["desc"] for e in wm2.unresolved_foreshadowing] == ["v1", "v3"]  # 一次结算不错位
    assert [e["desc"] for e in wm2.resolved_foreshadowing] == ["v2", "v4"]
    assert all(e["resolved_chapter"] == 5 for e in wm2.resolved_foreshadowing)

    cli._do_foreshadow(["已回收"], tmp_settings)
    out = capsys.readouterr().out
    assert "已回收伏笔（共 2 条）：" in out and "（第2章埋，第5章收）v2" in out


def test_foreshadow_delete_invalid_input(tmp_settings, capsys):
    """F9 边界：非数字编号与越界编号都不改数据，只提示。"""
    wm = WorkingMemory()
    wm.unresolved_foreshadowing = [{"desc": "v1", "chapter": 1}]
    save_working_memory(wm, tmp_settings)

    cli._do_foreshadow(["删", "abc"], tmp_settings)
    assert "编号必须是数字" in capsys.readouterr().out
    cli._do_foreshadow(["删", "99"], tmp_settings)
    assert "没有有效编号" in capsys.readouterr().out
    assert load_working_memory(tmp_settings).unresolved_foreshadowing == [
        {"desc": "v1", "chapter": 1}]


def test_foreshadow_command_requires_novel_dir(capsys):
    """F9：NOVEL_DIR 未配置 -> 报错不崩。"""
    cli._do_foreshadow([], Settings(ark_api_key="k", repo_root=Path(".")))
    assert "NOVEL_DIR" in capsys.readouterr().out


def test_foreshadow_unknown_subcommand(tmp_settings, capsys):
    """F9：未知子命令给用法提示，不改数据。"""
    cli._do_foreshadow(["乱敲"], tmp_settings)
    assert "未知子命令" in capsys.readouterr().out


def test_status_shows_foreshadow_before_first_chapter(tmp_settings, capsys):
    """F17：首章前（current_chapter 为空）手工补录的伏笔在 `状态` 可见，且无「第None章」噪音。"""
    wm = WorkingMemory()
    wm.add_foreshadowing("人工补的线", chapter=None, manual=True)
    save_working_memory(wm, tmp_settings)

    cli._do_status(tmp_settings)
    out = capsys.readouterr().out
    assert "尚未创作任何章节。" in out
    assert "人工补的线" in out
    assert "第None章" not in out                 # 只补伏笔块，不打整份 snapshot


def test_help_lists_foreshadow_commands(capsys):
    """F9：help 增行（列表/删/加/已回收）。"""
    cli._print_help()
    out = capsys.readouterr().out
    assert "伏笔             查看未回收伏笔" in out
    assert "伏笔 删 <编号>" in out and "伏笔 加 <描述>" in out and "伏笔 已回收" in out


def test_main_loop_dispatches_foreshadow(tmp_settings, monkeypatch, capsys):
    """F9：主循环把「伏笔 ...」分发到 _do_foreshadow（args 原样透传）。"""
    got = []
    monkeypatch.setattr(cli, "_do_foreshadow", lambda args, settings: got.append(list(args)))
    replies = iter(["伏笔 加 一条新线", "quit"])
    monkeypatch.setattr("builtins.input", lambda *a: next(replies))
    cli.main()
    assert got == [["加", "一条新线"]]


# ---------- 角色弧光抽取回路（3.2 character-arc，C2/C3/C4/C12/C13/C15）----------
class ArcAgent(_RecordingAgent):
    """替身 agent：extract_character_arc 按 result 返回或抛错，并记录调用入参。

    继承 _RecordingAgent：run() 收 plan 关键字（批量路径会传）。
    """

    def __init__(self, rag, result=None):
        super().__init__(rag)
        self.result = result if result is not None else {"characters": []}
        self.extract_calls = []

    def extract_character_arc(self, chapter_text, character_states, chapter_no=None):
        self.extract_calls.append({
            "chapter_no": chapter_no,
            "names": list((character_states or {}).keys()),
        })
        if isinstance(self.result, Exception):
            raise self.result
        return dict(self.result)


def _run_arc(monkeypatch, tmp_settings, agent, wm, task="写第5章：异乡风起"):
    monkeypatch.setattr(cli, "_build_agent", lambda settings, task="", need_style=True: (agent, wm, None))
    monkeypatch.setattr(cli, "evaluate", lambda *a, **kw: None)
    cli._do_write(task, tmp_settings)


def test_write_arc_extracts_and_records(tmp_settings, fake_rag, monkeypatch, capsys):
    """C2/C4：抽取成功 -> 状态入 wm / record 留痕且落盘可查 / 🎭 行。"""
    wm = WorkingMemory()
    agent = ArcAgent(fake_rag, {"characters": [
        {"name": "林晚", "stage": "复仇决心初动摇", "goal": "查清真相",
         "conflict": "复仇与良知", "belief": "真相值得代价", "changed": True},
    ]})
    _run_arc(monkeypatch, tmp_settings, agent, wm)

    assert agent.extract_calls[0]["chapter_no"] == 5
    assert agent.extract_calls[0]["names"] == []                  # 首章清单空
    lin = wm.character_states["林晚"]
    assert lin["stage"] == "复仇决心初动摇" and lin["chapter"] == 5
    assert lin["history"] == [{"chapter": 5, "stage": "复仇决心初动摇"}]

    saved = load_run("run_20260828_000001", tmp_settings)          # C4：补写后真读得到
    assert saved["arc"]["updated"] == ["林晚"]
    assert saved["arc"]["changed"] == ["林晚"]
    assert saved["arc"]["total"] == 1
    assert "🎭 弧光：更新 1 角色（跟踪 1）" in capsys.readouterr().out


def test_write_arc_failure_keeps_everything(tmp_settings, fake_rag, monkeypatch, capsys):
    """C3/Z8：弧光抛异常 -> 状态不变、进度照常落盘、record 留 error 键、主流程走完。"""
    wm = WorkingMemory()
    wm.update_character_states(
        [{"name": "林晚", "stage": "蒙冤受屈", "changed": False}], chapter_no=3)
    agent = ArcAgent(fake_rag, RuntimeError("网关 502"))
    _run_arc(monkeypatch, tmp_settings, agent, wm)

    assert wm.character_states["林晚"]["stage"] == "蒙冤受屈"      # 状态未被吞
    assert wm.current_chapter == 5 and wm.last_plot_point == "摘要：风起。"
    assert load_working_memory(tmp_settings).current_chapter == 5  # 且已落盘

    saved = load_run("run_20260828_000001", tmp_settings)
    assert saved["arc"] == {"error": "网关 502"}                   # Z8：分得清「没动」与「挂了」
    out = capsys.readouterr().out
    assert "弧光抽取跳过：网关 502" in out
    assert "章节已存" in out                                       # 写作主流程不受影响


def test_write_arc_failure_does_not_break_foreshadow(tmp_settings, fake_rag, monkeypatch, capsys):
    """C3：两回路独立 try/except--弧光挂了，伏笔照常抽取且落盘。"""
    wm = WorkingMemory()

    class BothAgent(ArcAgent):
        def __init__(self, rag):
            super().__init__(rag, RuntimeError("弧光挂了"))
            self.fo_calls = []

        def extract_foreshadowing(self, chapter_text, unresolved, chapter_no=None):
            self.fo_calls.append(chapter_no)
            return {"new": [{"desc": "怀表"}], "resolved": []}

    agent = BothAgent(fake_rag)
    _run_arc(monkeypatch, tmp_settings, agent, wm)

    assert agent.fo_calls == [5]                                  # 伏笔照常
    assert [e["desc"] for e in wm.unresolved_foreshadowing] == ["怀表"]
    saved = load_run("run_20260828_000001", tmp_settings)
    assert "foreshadow" in saved and saved["arc"] == {"error": "弧光挂了"}


def test_write_arc_disabled_zero_calls(tmp_settings, fake_rag, monkeypatch):
    """C12：NOVEL_ARC=0 -> 零抽取调用，record 不留 arc 键。"""
    settings = dataclasses.replace(tmp_settings, arc_enabled=False)
    agent = ArcAgent(fake_rag)
    _run_arc(monkeypatch, settings, agent, WorkingMemory())

    assert agent.extract_calls == []
    assert "arc" not in load_run("run_20260828_000001", settings)
    assert load_working_memory(settings).current_chapter == 5      # 写作主流程不受影响


def test_write_arc_same_chapter_rerun_overwrites(tmp_settings, fake_rag, monkeypatch):
    """C15：同章重写覆盖该章旧 history 条目，不产生「同一章两个阶段」。"""
    wm = WorkingMemory()
    agent = ArcAgent(fake_rag, {"characters": [
        {"name": "林晚", "stage": "阶段A", "changed": True}]})
    _run_arc(monkeypatch, tmp_settings, agent, wm)
    agent.result = {"characters": [
        {"name": "林晚", "stage": "阶段A2", "changed": True}]}     # 重跑第 5 章
    _run_arc(monkeypatch, tmp_settings, agent, wm)

    lin = wm.character_states["林晚"]
    assert [h["chapter"] for h in lin["history"]] == [5]           # 无重复条目
    assert lin["history"][0]["stage"] == "阶段A2"
    assert lin["stage"] == "阶段A2"


def test_write_arc_num_none_keeps_untagged_history(tmp_settings, fake_rag, monkeypatch):
    """C15 守卫：任务串解析不出章号（num=None）时不清洗，无章号 history 不被抹掉。"""
    wm = WorkingMemory()
    wm.update_character_states(
        [{"name": "林晚", "stage": "番外态", "changed": True}], chapter_no=None)
    agent = ArcAgent(fake_rag, {"characters": [
        {"name": "林晚", "stage": "番外态2", "changed": True}]})
    _run_arc(monkeypatch, tmp_settings, agent, wm, task="写一段番外")

    history = wm.character_states["林晚"]["history"]
    assert [h["stage"] for h in history] == ["番外态", "番外态2"]  # 追加，不清洗
    assert agent.extract_calls[0]["chapter_no"] is None


def test_batch_arc_continuity(tmp_settings, fake_rag, monkeypatch):
    """C2：批量两章走「落盘 -> 再读回」链，第二章抽取输入含第一章的角色状态。"""
    _mk_plan_file(tmp_settings)
    agent = ArcAgent(fake_rag, {"characters": [
        {"name": "林晚", "stage": "蒙冤受屈", "changed": True}]})
    monkeypatch.setattr(
        cli, "_build_agent",
        lambda settings, task="", need_style=True: (agent, load_working_memory(settings), None),
    )
    monkeypatch.setattr(cli, "evaluate", lambda *a, **kw: None)
    monkeypatch.setattr(cli, "_gate_confirm", lambda prompt: "y")
    cli._do_write_batch("写第5-6章", tmp_settings, auto=False)

    assert len(agent.extract_calls) == 2
    assert agent.extract_calls[0]["names"] == []                   # 首章清单空
    assert agent.extract_calls[1]["names"] == ["林晚"]             # 章间连续性
    wm = load_working_memory(tmp_settings)
    assert wm.character_states["林晚"]["chapter"] == 6             # 状态推进到第二章


# ---------- 角色 REPL 命令（3.2 C9/C10/D9/Z4）----------
def test_character_command_lists(tmp_settings, capsys):
    """C9：列表形态（空提示 / 非空全量含目标冲突信念与历史）。"""
    cli._do_character([], tmp_settings)
    assert "跟踪角色：无" in capsys.readouterr().out

    wm = WorkingMemory()
    wm.update_character_states(
        [{"name": "林晚", "stage": "蒙冤受屈", "goal": "活下去",
          "conflict": "复仇与良知", "belief": "天理昭昭", "changed": True}], chapter_no=3)
    save_working_memory(wm, tmp_settings)
    cli._do_character([], tmp_settings)
    out = capsys.readouterr().out
    assert "跟踪角色（共 1 个）：" in out
    assert "林晚（第3章）：蒙冤受屈" in out
    assert "目标：活下去｜冲突：复仇与良知｜信念：天理昭昭" in out
    assert "历史变化 1 次：蒙冤受屈" in out


def test_character_delete_removes(tmp_settings, capsys):
    """C9/Z4：删 = 直接移除（不归档）；未命中提示不改数据。"""
    wm = WorkingMemory()
    wm.update_character_states(
        [{"name": "林晚", "stage": "蒙冤受屈", "changed": False}], chapter_no=3)
    save_working_memory(wm, tmp_settings)

    cli._do_character(["删", "林晚"], tmp_settings)
    assert "已停止跟踪：林晚" in capsys.readouterr().out
    assert load_working_memory(tmp_settings).character_states == {}

    cli._do_character(["删", "查无此人"], tmp_settings)
    assert "没有这个角色" in capsys.readouterr().out


def test_character_revise_persists(tmp_settings, capsys):
    """C10：改 = 修正 stage 且落盘 roundtrip；未命中提示。"""
    wm = WorkingMemory()
    wm.current_chapter = 5
    wm.update_character_states(
        [{"name": "林晚", "stage": "蒙冤受屈", "goal": "活下去",
          "conflict": "", "belief": "天理昭昭", "changed": True}], chapter_no=3)
    save_working_memory(wm, tmp_settings)

    cli._do_character(["改", "林晚", "复仇决心已崩溃"], tmp_settings)
    assert "已修正 林晚 的当前阶段" in capsys.readouterr().out
    wm2 = load_working_memory(tmp_settings)
    assert wm2.character_states["林晚"]["stage"] == "复仇决心已崩溃"
    assert wm2.character_states["林晚"]["chapter"] == 5           # 更新章取当前章
    assert wm2.character_states["林晚"]["goal"] == "活下去"        # 其余字段保留

    cli._do_character(["改", "查无此人", "新阶段"], tmp_settings)
    assert "没有这个角色" in capsys.readouterr().out
    cli._do_character(["改"], tmp_settings)
    assert "用法" in capsys.readouterr().out


def test_character_command_requires_novel_dir(capsys):
    """C9：NOVEL_DIR 未配置 -> 报错不崩。"""
    cli._do_character([], Settings(ark_api_key="k", repo_root=Path(".")))
    assert "NOVEL_DIR" in capsys.readouterr().out


def test_character_unknown_subcommand(tmp_settings, capsys):
    """C9：未知子命令给用法提示，不改数据。"""
    cli._do_character(["乱敲"], tmp_settings)
    assert "未知子命令" in capsys.readouterr().out


def test_help_lists_character_commands(capsys):
    """C9：help 增行（列表/删/改）。"""
    cli._print_help()
    out = capsys.readouterr().out
    assert "角色             查看跟踪角色" in out
    assert "角色 删 <名字>" in out and "角色 改 <名字> <新阶段>" in out


def test_main_loop_dispatches_character(tmp_settings, monkeypatch, capsys):
    """C9：主循环把「角色 ...」分发到 _do_character（args 原样透传）。"""
    got = []
    monkeypatch.setattr(cli, "_do_character", lambda args, settings: got.append(list(args)))
    replies = iter(["角色 改 林晚 复仇决心已崩溃", "quit"])
    monkeypatch.setattr("builtins.input", lambda *a: next(replies))
    cli.main()
    assert got == [["改", "林晚", "复仇决心已崩溃"]]


# ---------- 卷对齐落盘集成（volume-align，V1/V3/V8）----------
def _vol_align_settings(tmp_settings):
    """卷对齐集成配置：subdir 指到第一卷目录。"""
    return dataclasses.replace(tmp_settings, volume_align=True, chapter_subdir="正文/第一卷")


def test_write_volume_align_lands_in_volume(tmp_settings, fake_rag, monkeypatch):
    """V1：对齐模式下章节落卷路径、头行 ## 第{中文}章、RAG 入库收卷路径。"""
    settings = _vol_align_settings(tmp_settings)
    agent = WriteAgent(fake_rag)
    monkeypatch.setattr(cli, "_build_agent", lambda settings, task="", need_style=True: (agent, WorkingMemory(), None))
    monkeypatch.setattr(cli, "evaluate", lambda *a, **kw: None)
    cli._do_write("写第38章：空", settings)

    vol_file = settings.novel_path / "正文" / "第一卷" / "第一卷-38.md"
    assert vol_file.exists()
    assert vol_file.read_text(encoding="utf-8").startswith("## 第三十八章 空\n\n")
    assert fake_rag.add_calls == [str(vol_file)]        # V8：入库路径随落盘走


def test_write_volume_align_overwrites_original(tmp_settings, fake_rag, monkeypatch):
    """V3：预置人工原稿被同文件覆盖（git diff 即比对），目录内仅 1 个 md。"""
    settings = _vol_align_settings(tmp_settings)
    vol_dir = settings.novel_path / "正文" / "第一卷"
    vol_dir.mkdir(parents=True, exist_ok=True)
    original = vol_dir / "第一卷-38.md"
    original.write_text("## 第三十八章 空\n\n人工原稿正文。", encoding="utf-8")

    agent = WriteAgent(fake_rag)
    monkeypatch.setattr(cli, "_build_agent", lambda settings, task="", need_style=True: (agent, WorkingMemory(), None))
    monkeypatch.setattr(cli, "evaluate", lambda *a, **kw: None)
    cli._do_write("写第38章：空", settings)

    text = original.read_text(encoding="utf-8")
    assert text.startswith("## 第三十八章 空\n\n")     # 头行格式保持
    assert "人工原稿正文。" not in text                  # 原稿被覆盖
    assert "风起了。" in text                            # AI 定稿已写入
    assert len(list(vol_dir.glob("*.md"))) == 1          # 无 run_id 后缀副本


# ---------- planner 集成（3.3 P1/P4/P11/P12）----------
class PlannerAgent(WriteAgent):
    """替身 agent：run() 模拟 planner 开启时的行为（steps[0]=planner、outline=节拍）。"""

    BEATS = "【场景序列】\n1. 山道/黄昏/相遇/克制/600字\n【结尾钩子】灯亮了"

    def run(self, task, run_id=None, temperature=0.9, plan=""):
        state, record = super().run(task, run_id, temperature)
        state.outline = self.BEATS
        record["steps"] = [{"step_id": 1, "agent": "planner", "round": 1,
                            "input_state": {}, "output_state": {"outline": self.BEATS},
                            "decision": "writer"}]
        record["final_state"] = {"outline": self.BEATS}
        return state, record


def test_write_planner_on_full_chain(tmp_settings, fake_rag, monkeypatch, capsys):
    """P1/P6 集成：planner 开启时 run record 首步是 planner、节拍进 final_state。"""
    settings = dataclasses.replace(tmp_settings, planner_enabled=True)
    agent = PlannerAgent(fake_rag)
    monkeypatch.setattr(cli, "_build_agent", lambda settings, task="", need_style=True: (agent, WorkingMemory(), None))
    monkeypatch.setattr(cli, "evaluate", lambda *a, **kw: None)
    cli._do_write("写第5章：异乡风起", settings)

    from novel_agent.storage import load_run
    record = load_run("run_20260828_000001", settings)
    assert record["steps"][0]["agent"] == "planner"
    assert record["final_state"]["outline"] == PlannerAgent.BEATS
    out = capsys.readouterr().out
    assert "章节已存" in out                                # 写作流程照常走完


def test_write_planner_off_no_planner_step(tmp_settings, fake_rag, monkeypatch):
    """P4 集成：默认关时 run record 无 planner 步骤（现状零变化）。"""
    agent = WriteAgent(fake_rag)
    monkeypatch.setattr(cli, "_build_agent", lambda settings, task="", need_style=True: (agent, WorkingMemory(), None))
    monkeypatch.setattr(cli, "evaluate", lambda *a, **kw: None)
    cli._do_write("写第5章：异乡风起", tmp_settings)

    from novel_agent.storage import load_run
    record = load_run("run_20260828_000001", tmp_settings)
    assert all(s.get("agent") != "planner" for s in record["steps"])


def test_batch_budget_text_planner_on_off(tmp_settings, fake_rag, monkeypatch, capsys):
    """P11/Z2：批量预算文案按开关二态（off 8-11 / on 9-12）。"""
    _mk_plan_file(tmp_settings)
    agent = _RecordingAgent(fake_rag)
    monkeypatch.setattr(cli, "_build_agent", lambda settings, task="", need_style=True: (agent, WorkingMemory(), None))
    monkeypatch.setattr(cli, "evaluate", lambda *a, **kw: None)
    monkeypatch.setattr(cli, "_gate_confirm", lambda prompt: "y")

    cli._do_write_batch("写第5-6章", tmp_settings, auto=False)
    assert "8-11 次" in capsys.readouterr().out            # 默认关：既有口径

    settings_on = dataclasses.replace(tmp_settings, planner_enabled=True)
    cli._do_write_batch("写第5-6章", settings_on, auto=False)
    assert "9-12 次" in capsys.readouterr().out            # 开：口径诚实


def test_status_shows_planner_switch(tmp_settings, capsys):
    """P12：状态命令显示 planner 开关行（两态）。"""
    cli._do_status(tmp_settings)
    assert "planner：关" in capsys.readouterr().out

    settings_on = dataclasses.replace(tmp_settings, planner_enabled=True)
    cli._do_status(settings_on)
    assert "planner：开" in capsys.readouterr().out
