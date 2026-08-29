"""写 命令（_do_write）交互层测试：monkeypatch _build_agent + FakeAgent/FakeRag，不联网。

覆盖 0.3（写完自动入库）：章节保存后 rag.add_document 收到章节文件绝对路径；
索引失败不阻断写作流程。
1.1 T8：质量门禁三路 / D8 豁免 / 规则未配置 / refine 同构 / _gate_ok 单测 / A23 命令层捕获。
"""
from __future__ import annotations

import json

from novel_agent import cli
from novel_agent.config import Settings
from novel_agent.llm import load_profiles
from novel_agent.memory import WorkingMemory
from novel_agent.state import PipelineState
from novel_agent.storage import load_working_memory


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
    monkeypatch.setattr(cli, "_build_agent", lambda settings, task="": (agent, WorkingMemory(), None))
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
    monkeypatch.setattr(cli, "_build_agent", lambda settings, task="": (agent, wm, route))
    monkeypatch.setattr(cli, "evaluate", lambda *a, **kw: None)
    cli._do_write("写第5章：异乡风起", tmp_settings)

    saved = load_run("run_20260828_000001", tmp_settings)
    assert saved["exemplar_route"] == {"files": ["1.txt", "2.txt"], "reason": "日常章"}


def test_do_write_no_route_no_key(tmp_settings, fake_rag, monkeypatch, capsys):
    """A5 边界：未路由（route=None）时 run 记录不含 exemplar_route 键。"""
    from novel_agent.storage import load_run

    agent = WriteAgent(fake_rag)
    monkeypatch.setattr(cli, "_build_agent", lambda settings, task="": (agent, WorkingMemory(), None))
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
    monkeypatch.setattr(cli, "_build_agent", lambda settings, task="": (agent, wm, None))
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
    monkeypatch.setattr(cli, "_build_agent", lambda settings, task="": (agent, WorkingMemory(), None))
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
    monkeypatch.setattr(cli, "_build_agent", lambda settings, task="": (agent, WorkingMemory(), None))
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
