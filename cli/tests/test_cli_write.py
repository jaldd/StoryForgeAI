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
from novel_agent.storage import load_run, load_working_memory


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
    assert "批量连写：第5-6章，共 2 章" in out and "6-9 次" in out  # T24 预算提示


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
