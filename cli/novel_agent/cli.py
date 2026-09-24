"""交互式命令行入口。

命令：
  写第N章：标题     走完整流程（查设定->草稿->润色->审稿->打分->门禁->存文件）
  精修 <文件路径>   精修已有正文（润色->审稿->存回->更新索引，不写新场景）
  改 <文件路径>     局部精修（列出段落->选段->只润色选区->diff 确认->逐字节存回）
  index            查看向量库；index rebuild 全量重建；index add/remove <路径> 单文件增删
  replay <run_id>  回放某次写作过程
  eval <run_id>    对某次写作打分
  compare <a> <b>  对比两次写作效果
  状态             查看当前写到第几章、角色状态、未回收伏笔
  伏笔             查看未回收伏笔；伏笔 删 N（标记回收）/ 伏笔 加 <描述> / 伏笔 已回收
  help / quit
"""
from __future__ import annotations

import datetime
import difflib
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .agent import NovelAgent
from .checker import (
    ai_flavor_score,
    load_baseline,
    load_quality_rules,
    load_recent_endings,
    run_checks,
    run_cross_checks,
    scan_style_report,
)
from .config import Settings, get_settings
from .harness import backtest_gate, compare, evaluate, replay, run_tests
from .llm import LLMClient, load_profiles
from .memory import WorkingMemory
from .partial import Block, apply_replacements, parse_selection, preview_line, split_paragraphs
from .prompts import build_style_taboos, exemplar_info, load_exemplar, load_recent_human
from .rag import RAGStore
from .routing import parse_tag_lines, route_exemplars
from .state import PipelineState
from .storage import (
    cn_numeral,
    list_runs,
    load_working_memory,
    parse_chapter_file,
    parse_chapter_plan,
    parse_chapter_range,
    parse_chapter_task,
    preserve_leading_title,
    save_chapter,
    save_run,
    save_working_memory,
)

__all__ = ["main"]


# ---------- 依赖构造 ----------
def _load_instruction(settings: Settings) -> str:
    """读写作指令全文（NOVEL_INSTRUCTION）；不存在则返回空串。"""
    if settings.instruction_subpath and settings.instruction_full.is_file():
        return settings.instruction_full.read_text(encoding="utf-8")
    return ""


def _load_rules(settings: Settings) -> str:
    """读写作铁律全文（NOVEL_RULES，0.2 外置到 NOVEL_DIR 下「写作铁律.md」）；不存在则返回空串。"""
    if settings.rules_subpath and settings.rules_full.is_file():
        return settings.rules_full.read_text(encoding="utf-8")
    return ""


def _refresh_working_memory(
    path: Path,
    state: PipelineState,
    agent: NovelAgent,
    wm: WorkingMemory,
    settings: Settings,
) -> None:
    """精修/重写存回后刷新工作记忆（0.8 T11）。

    - 章号取自文件名（parse_chapter_file，匹配 save_chapter 落盘格式）；
    - 摘要失败 / 文件名不匹配 -> 静默跳过，不阻断存回主流程（A17/A21）；
    - D9-b：精修旧章不回退进度指针（num < current_chapter 时不更新）；
      current_chapter 为 None（首章）时裸 >= 会 TypeError，须补 None 判断。
    """
    num, _ = parse_chapter_file(path)
    try:
        summary = agent.summarize_chapter(state.final_chapter)
    except Exception:
        summary = None
    if num is not None and summary and (wm.current_chapter is None or num >= wm.current_chapter):
        wm.update_after_write(num, summary)
        save_working_memory(wm, settings)


def _load_exemplar_tags(settings: Settings) -> list:
    """读样文标签文件（exemplar-routing）；不存在/禁用/解析为空返回 []。"""
    if not settings.exemplar_tags_subpath:
        return []
    tags_path = settings.exemplar_tags_full
    if not tags_path.is_file():
        return []
    try:
        text = tags_path.read_text(encoding="utf-8")
    except OSError as e:
        print(f"(样文标签文件不可读，跳过路由：{e})")
        return []
    return parse_tag_lines(text)


def _route_exemplar_files(settings: Settings, task: str):
    """按本章任务路由样文（exemplar-routing）；返回 (only_files 或 None, route 或 None)。

    - 标签为空 -> (None, None)（不路由，走现状加载）；
    - 路由成功 -> (选中文件名列表, RouteResult)；
    - 失败/异常 -> (None, None) + 一行提示，写作不中断（A3/A4）。
    - 走主 profile（路由要稳，不用可能便宜的 writer_llm；design.md §3.2）。
    """
    tags = _load_exemplar_tags(settings)
    if not tags:
        return None, None
    profiles = load_profiles(settings)
    router_llm = LLMClient(settings=settings, profile=profiles.default)
    temp = (
        settings.router_temperature
        if settings.router_temperature is not None else 0.2
    )
    try:
        route = route_exemplars(router_llm, task, tags, temperature=temp)
    except Exception as e:
        print(f"(样文路由失败，回落全量加载：{e})")
        return None, None
    if route is None:
        print("(样文路由未返回有效结果，回落全量加载)")
        return None, None
    print(f"🧭 样文路由：{'、'.join(route.files)}（{route.reason}）")
    return route.files, route


def _build_agent(settings: Settings, task: str = "", need_style: bool = True, active_file: str = ""):
    """构造 NovelAgent：加载文风金标准 + 写作指令 + 写作铁律 + 工作记忆，RAG 惰性。

    0.7：load_profiles 一次解析，双 LLMClient 注入（llm=default profile，
    writer_llm=writer profile）；未配 WRITER_* 时两 profile 逐字段相等，
    行为与改造前完全一致（A9 回归保险）。
    1.1：质量规则 JSON 在装配点加载注入（非法 JSON fail-fast，A23）。
    exemplar-routing：task 非空且标签文件存在时先路由（一次廉价调用），按选中
    样文加载；路由任何失败回落现状（清单/全量）加载，永不阻塞写作。
    1.5 滚动注入：exemplar 之后加载人工正文尾部 N 章（仅当 human_text_subpath
    已配置；目录不存在/空返回空串，B2 零误伤），只传 writer（B5）。
    1.7 跨章禁则：质量规则含 ending/syntax_patterns 时现算参照章结尾
    （load_recent_endings，D1 章节文件即真源）+ 构造 writer 禁则分节；
    active_file = 精修/重写/去AI 被处理文件（C18 防自比，从参照集排除）；
    两键全缺时 recent_endings=None、taboos=""，行为与现状逐字节一致（C16）。
    need_style=False：exemplar/滚动语料/样文路由只被 writer 消费，精修/改/去AI
    不走 writer，跳过加载省一次路由调用与文件 IO（行为零变化，纯省）。
    """
    only_files = None
    route = None
    exemplar = ""
    if need_style:
        if task:
            only_files, route = _route_exemplar_files(settings, task)
        # 0.5：exemplar 支持目录级（目录下全部 *.txt/*.md 按序拼接，超限截断）
        if settings.exemplar_subpath and settings.exemplar_full.exists():
            exemplar = load_exemplar(settings.exemplar_full, only_files=only_files)
    recent_human = ""
    if need_style and settings.human_text_subpath:
        recent_human = load_recent_human(
            settings.human_text_full,
            n=settings.style_recent_n,
            slice_chars=settings.style_slice_chars,
        )
    instruction = _load_instruction(settings)
    rules = _load_rules(settings)
    quality_rules = load_quality_rules(settings)
    # 1.7：参照章现算 + 禁则构造（Z4：compile_syntax_patterns 的 RuntimeError
    # 在此抛出，命令层既有 RuntimeError 捕获兜住不崩 REPL）
    recent_endings = None
    style_taboos = ""
    if quality_rules and (quality_rules.get("ending") or quality_rules.get("syntax_patterns")):
        ending_cfg = quality_rules.get("ending") or {}
        if ending_cfg:
            # C18：active_file 按 rag._resolve_source 同口径解析（相对 NOVEL_DIR），
            # 用户敲相对路径时 exclude 才能命中（否则自比双计、阈值实际 -1）
            exclude = None
            if active_file:
                p = Path(active_file).expanduser()
                if not p.is_absolute():
                    p = settings.novel_path / p
                exclude = p
            recent_endings = load_recent_endings(
                settings.human_text_full,
                ending_cfg.get("lookback", 10),
                exclude=exclude,
            )
        style_taboos = build_style_taboos(recent_endings, quality_rules)
    wm = load_working_memory(settings)
    profiles = load_profiles(settings)
    agent = NovelAgent(
        llm=LLMClient(settings=settings, profile=profiles.default),
        writer_llm=LLMClient(settings=settings, profile=profiles.writer),
        rag=RAGStore(settings=settings),
        exemplar=exemplar,
        instruction=instruction,
        settings=settings,
        working_memory=wm,
        rules=rules,
        quality_rules=quality_rules,
        recent_human=recent_human,
        stream=settings.stream,  # 2.1（T26）：NOVEL_STREAM 驱动 writer/polisher 流式
        recent_endings=recent_endings,
        style_taboos=style_taboos,
    )
    return agent, wm, route


# ---------- 质量门禁（1.1 A30-A34，design §3.6）----------
def _gate_confirm(prompt: str) -> str:
    """门禁人工确认缝（模块级，测试可替换，同 agent.review_confirm 的 0.1 模式）。

    EOF / Ctrl-C -> 返回 "n" 保守弃（A34，门禁默认不放过）。
    """
    try:
        return input(prompt)
    except (EOFError, KeyboardInterrupt):
        return "n"


def _gate_ok(score, rules) -> bool:
    """eval_gate 判定：门禁是否放行。

    - rules 未配置 / eval_gate 缺失或 enabled falsy / threshold 缺失 -> True（不过门禁）；
    - score 非 dict（含 None）或无任何配权维度命中 -> True（A33：evaluate 失败/被替换的测试缝）；
    - 标题评分从 weights 硬排除（A32）；其余维度加权分 Σw·s / Σw >= threshold 才放行。
    """
    if not isinstance(rules, dict):
        return True
    gate = rules.get("eval_gate")
    if not isinstance(gate, dict) or not gate.get("enabled"):
        return True
    threshold = gate.get("threshold")
    if not isinstance(threshold, (int, float)):
        return True
    if not isinstance(score, dict):
        return True
    weights = {
        k: w for k, w in (gate.get("weights") or {}).items()
        if k != "标题评分" and isinstance(w, (int, float))
    }
    hits = [(w, score[k]) for k, w in weights.items() if k in score]
    if not hits:  # A33：评委没给出任何配权维度的分 -> 无从判，放行
        return True
    wsum = sum(w for w, _ in hits)
    if wsum <= 0:
        return True
    return sum(w * s for w, s in hits) / wsum >= threshold


# ---------- 去AI 判定链（1.6 style-loop，design §3.2）----------
def _deai_pass(agent, state: PipelineState, record: Dict[str, Any], settings: Settings) -> None:
    """de-AI 人味重写 pass（B9-B17）：超阈值 -> 重写 -> 复检分降才接受。

    - 触发：质量规则 deai.enabled 且 AI 味分超 deai.threshold（默认 60）；
      阈值未配置 -> 整段短路零行为变更（B18/Z2）；
    - 输入：只取可定位 issue（quote 非空且为原文子串，B10；全部不可定位
      -> skipped 留痕不空跑 LLM，B17）；
    - 接受：after < before 严格小于（D5）；否则回退保留原稿（B13）；
    - 留痕：state.deai {before, after, spans, accepted} 或 {before, skipped}（B14），
      record.final_state 同步终态（D4：record 落盘即终态，评委评的就是改后稿）。
    """
    rules = load_quality_rules(settings)
    deai_cfg = (rules or {}).get("deai") or {}
    if not (deai_cfg.get("enabled") and state.final_chapter):
        return
    baseline = load_baseline(settings)
    before = ai_flavor_score(state.final_chapter, rules, baseline)["score"]
    if before <= deai_cfg.get("threshold", 60):
        return  # 未超阈值：不留痕不空跑（B17）
    issues = [
        i for i in run_checks(state.final_chapter, rules)
        if i.get("quote") and i["quote"] in state.final_chapter  # 只取可定位（B10/B17）
    ]
    if not issues:
        state.deai = {"before": before, "skipped": "无可定位问题句"}
        record["final_state"]["deai"] = state.deai
        print(f"(AI味分 {before} 超阈值但无可定位问题句，跳过去AI重写)")
        return
    new_text, n_spans = agent.deai_refine(state.final_chapter, issues)
    after = ai_flavor_score(new_text, rules, baseline)["score"]
    accepted = after < before  # D5：严格小于才接受
    if accepted:
        state.final_chapter = new_text
        print(f"✅ 去AI重写：AI味分 {before} -> {after}（已接受，改 {n_spans} 段）")
    else:
        print(f"⚠️ 去AI重写未降分（{before} -> {after}），保留原稿")
    state.deai = {"before": before, "after": after, "spans": n_spans, "accepted": accepted}
    record["final_state"]["final_chapter"] = state.final_chapter
    record["final_state"]["deai"] = state.deai


# ---------- 章纲加载与渲染（2.2，D6/D12）----------
def _load_chapter_plan(settings: Settings) -> Dict[int, Dict[str, Any]]:
    """读章纲（NOVEL_CHAPTER_PLAN 指向的 markdown）并解析成 {章号: entry}。

    未配置 / 文件不存在 / 读失败 -> 返回 {}（静默降级，对齐写作铁律缺失回落
    空串的既有纪律；章纲解析一次、批量全程复用，不是每章重读文件）。
    """
    if not settings.chapter_plan_subpath:
        return {}
    try:
        text = settings.plan_full.read_text(encoding="utf-8")
    except OSError:
        return {}
    return parse_chapter_plan(text)


def _render_notes(entry: Dict[str, Any]) -> str:
    """notes (列名, 值) 对 -> 「列名：值」逐行（【本章规划】块正文，D12 渲染）。

    空值列不占行（章纲里留空的格子不进 prompt 占位）。
    """
    return "\n".join(f"{name}：{value}" for name, value in entry.get("notes", []) if value)


# ---------- 命令处理 ----------
def _write_one(task: str, settings: Settings, plan: str = "") -> str:
    """单章写作一条龙（2.2，D9 拆层）：返回结局枚举，单章/批量共用。

    - "saved"：章节已存盘（工作记忆/向量库已更新）；
    - "rejected"：门禁弃 / 审稿人工弃（未存盘，运行日志已落）；
    - "failed"：agent.run 抛异常 / 装配失败（批量侧应中断）；
    - "interrupted"：Ctrl-C（D5 修订：整体兜底覆盖流式/评测/存盘全部阶段，
      打断 = 本命令作废，不存盘不更新 wm；_gate_confirm/_confirm_unparseable
      内已消化的 "n" 语义先于外层捕获，不受影响）。
    """
    try:
        try:
            settings.require_novel_dir()
        except RuntimeError as e:
            print(f"❌ {e}")
            return "failed"
        print("🔧 构建 Agent（加载设定/文风基准/写作指令）...")
        try:
            agent, wm, route = _build_agent(settings, task=task)
        except RuntimeError as e:  # 1.1 A23：质量规则非法 JSON 等装配错误，命令层兜住不崩 REPL
            print(f"❌ {e}")
            return "failed"
        print(f"✍️  开始创作：{task}\n")
        try:
            # plan 非空才传：既有 FakeAgent（run(task) 签名）与真实 run 的 plan=""
            # 缺省路径行为一致（W5 回归护栏：既有用例零改动）
            if plan:
                state, record = agent.run(task, plan=plan)
            else:
                state, record = agent.run(task)
        except Exception as e:
            print(f"❌ 创作失败：{e}")
            return "failed"

        # exemplar-routing：路由结果进 run 记录（replay 可见，A5）
        if route is not None:
            record["exemplar_route"] = {"files": list(route.files), "reason": route.reason}

        # ---- 1.6 de-AI 人味重写 pass（D4 时序：流水线 done 后、save_run/evaluate 前）----
        # 无 deai 键 / enabled falsy -> 整段短路零行为变更（B18）；pass 是优化器：
        # 任何异常 catch 打印后保留原稿继续走（失败不阻断主流程，design §6）。
        try:
            _deai_pass(agent, state, record, settings)
        except Exception as e:
            print(f"(去AI重写跳过：{e})")

        print("💾 落盘运行记录...")
        # 运行日志落盘（1.1：先落 run record，弃而不失数据，design §3.6）
        run_file = save_run(record, settings)

        # 自动评测（1.1：从存盘后移到存盘前--门禁要用分；失败不阻断，豁免路径同样照跑留报告）
        print("\n--- 自动评测 ---")
        score = None
        try:
            score = evaluate(record["run_id"], settings, instruction=agent.instruction)
        except Exception as e:
            print(f"(评测跳过：{e})")

        # 1.1 D8 豁免口径：强制定稿 / 人工确认 -> 跳过门禁判定直存（向量库/摘要照常）
        exempt = "强制定稿" in state.feedback or "人工确认" in state.feedback
        # 1.1 A30-A34：未豁免且已定稿且门禁不过 -> 人工确认，应答弃则不写章节文件
        save = bool(state.final_chapter)
        if save and not exempt and not _gate_ok(score, load_quality_rules(settings)):
            answer = _gate_confirm("\n⚠️ 评测低于门禁阈值，仍保存本章？(y/n)：").strip().lower()
            if answer != "y":
                save = False
                print("已放弃保存本章（运行日志已落，可 replay 查看）")

        # 章节落盘 + 工作记忆更新
        chapter_file = None
        if save:
            print("📖 保存章节 + 生成剧情摘要...")
            chapter_file = save_chapter(state.final_chapter, task, record["run_id"], settings)
            # 0.3：写完自动入库（新章立即进 RAG，后续章节检索得到前文，不靠手动 index add）
            print("📚 更新向量库...")
            try:
                agent.rag.add_document(str(chapter_file))
            except Exception as e:
                print(f"(索引更新失败：{e})")
            num, _ = parse_chapter_task(task)
            # 生成剧情摘要存入工作记忆，让后续章节记得前文（P1 连续性）
            # 0.8：摘要调 agent.summarize_chapter（收编自裸调 agent.llm.chat），兜底仍留 UI 层
            try:
                summary = agent.summarize_chapter(state.final_chapter)
            except Exception:
                summary = task
            wm.update_after_write(num, summary or task)   # 既有：无条件在 try 外（A2）
            # ---- 3.1 伏笔抽取回路（F12 开关；失败不更新列表、不阻断主流程，F3）----
            if settings.foreshadow_enabled:
                try:
                    fo = agent.extract_foreshadowing(
                        state.final_chapter, wm.unresolved_foreshadowing, chapter_no=num)
                    wm.resolve_foreshadowing(fo["resolved"], num)   # 出列 -> 归档（A3/D8）
                    # F16 同章重写覆盖：先清该章旧条目（两道守卫：num 为 None 不清洗、
                    # manual 人工条目跳过），再追加本次抽取结果
                    if num is not None:
                        wm.unresolved_foreshadowing = [
                            e for e in wm.unresolved_foreshadowing
                            if e.get("chapter") != num or e.get("manual")
                        ]
                    for item in fo["new"]:
                        wm.unresolved_foreshadowing.append(
                            {"desc": item["desc"], "chapter": num})
                    record["foreshadow"] = {
                        "new": fo["new"], "resolved": fo["resolved"],
                        "unresolved_after": len(wm.unresolved_foreshadowing)}
                    save_run(record, settings)   # A1：抽取前已落盘过，补写一次留痕
                    print(f"🧵 伏笔：+{len(fo['new'])} 回收 {len(fo['resolved'])}"
                          f"（未回收 {len(wm.unresolved_foreshadowing)}）")
                except Exception as e:
                    print(f"(伏笔抽取跳过：{e})")
                    # F4/Z8：失败也留痕，replay 分得清「这章没埋」与「抽取挂了」
                    record["foreshadow"] = {"error": str(e)}
                    try:
                        save_run(record, settings)
                    except Exception:
                        pass                      # 补写失败仅吞掉，不反噬主流程
            # ---- 3.2 角色弧光抽取回路（C12 开关；失败不更新状态、不阻断主流程，C3）----
            # 与伏笔回路各自独立 try/except：一个失败不影响另一个已落的结果
            if settings.arc_enabled:
                try:
                    ar = agent.extract_character_arc(
                        state.final_chapter, wm.character_states, chapter_no=num)
                    wm.update_character_states(ar["characters"], num)
                    record["arc"] = {
                        "updated": [c["name"] for c in ar["characters"]],
                        "changed": [c["name"] for c in ar["characters"] if c.get("changed")],
                        "total": len(wm.character_states)}
                    save_run(record, settings)   # C4：补写一次留痕（同 run_id 覆盖）
                    print(f"🎭 弧光：更新 {len(ar['characters'])} 角色"
                          f"（跟踪 {len(wm.character_states)}）")
                except Exception as e:
                    print(f"(弧光抽取跳过：{e})")
                    # C4/Z8：失败也留痕，replay 分得清「没动角色状态」与「抽取挂了」
                    record["arc"] = {"error": str(e)}
                    try:
                        save_run(record, settings)
                    except Exception:
                        pass
            save_working_memory(wm, settings)      # 既有：无条件在 try 外（A2）

        # 打印流程日志
        print("--- 流程日志 ---")
        for line in state.log:
            print(line)
        print(f"\n运行日志：{run_file}")
        if chapter_file:
            print(f"章节已存：{chapter_file}")
        print(f"共 {state.round} 轮，审稿：{state.feedback}")

        print("\n=== 最终章节 ===")
        # 0.1：弃稿/未定稿时明确提示未保存，而非只打印"(空)"；
        # 1.1 A31：门禁弃同样展示内容但明示未保存
        if chapter_file:
            print(state.final_chapter)
        elif state.final_chapter:
            print(state.final_chapter)
            print("（本章未保存，运行日志已落）")
        else:
            print("（本章未定稿，未保存）")
        return "saved" if save else "rejected"
    except KeyboardInterrupt:
        print("\n⚠️ 已打断，本章未保存")
        return "interrupted"


def _do_write(task: str, settings: Settings, plan: str = "") -> None:
    """单章写作命令（薄壳）：对外行为与拆层前一致（plan 透传是唯一增量，T27）。"""
    _write_one(task, settings, plan=plan)


def _do_write_batch(task: str, settings: Settings, auto: bool) -> None:
    """批量连写（2.2，D10/D11，design §4.4）：区间章逐个走 _write_one。

    - 无标题主路径：章纲逐章供标题 + 规划；缺章报错零 LLM 调用（T14）；
    - 带模板回落：模板 + 中文序数后缀；章纲存在该章则规划照注入（T13）；
    - 起止倒置 / 跨度超 batch_max：报错零调用（T23）；
    - 默认章间 _gate_confirm 确认（y/n，T18）；--auto 下 rejected 即中断
      （T19 fail-closed），failed/interrupted 两模式均中断（T20/T22）；
    - 章间连续性零新逻辑（T21）：wm 更新 + rag.add_document 都在 _write_one
      既有路径里，每章 _build_agent 重建（Z4：章间状态依赖要求重建）。
    """
    parsed = parse_chapter_range(task)
    if parsed is None:
        print(f"❌ 非法区间命令：{task}（示例：写第5-10章 / 写第5-10章：模板）")
        return
    start, end, base = parsed
    if start > end:
        print(f"❌ 区间无效：起始章号（{start}）大于结束章号（{end}）")
        return
    n = end - start + 1
    if n > settings.batch_max:
        print(f"❌ 跨度超上限：共 {n} 章 > NOVEL_BATCH_MAX={settings.batch_max}，请拆分命令")
        return

    plan_map = _load_chapter_plan(settings)
    titles: Dict[int, str] = {}
    plans: Dict[int, str] = {}
    if base is None:
        missing = [num for num in range(start, end + 1) if num not in plan_map]
        if missing:
            print(f"❌ 每章规划缺章：{missing}"
                  f"（补齐 {settings.chapter_plan_subpath} 或命令带标题模板）")
            return  # T14：缺章零 LLM 调用
    for num in range(start, end + 1):
        if base is None:
            titles[num] = plan_map[num]["title"]
            plans[num] = _render_notes(plan_map[num])
        else:
            titles[num] = f"{base}（{cn_numeral(num - start + 1)}）"  # T13 回落
            if num in plan_map:
                plans[num] = _render_notes(plan_map[num])  # 显式标题不豁免规划注入

    mode = "，--auto 免确认" if auto else ""
    # 3.3 Z2：planner 开启时每章 +1 次规划调用（口径诚实；默认关 = 既有 8-11 不变）
    calls = "9-12" if settings.planner_enabled else "8-11"
    print(f"📦 批量连写：第{start}-{end}章，共 {n} 章{mode}"
          f"（每章约 {calls} 次 LLM 调用，注意 token 预算）")  # T24（C13：含伏笔+弧光抽取调用）
    try:
        for i, num in enumerate(range(start, end + 1), 1):
            print(f"\n━━━ [批量 {i}/{n}] 第{num}章：{titles[num]} ━━━")
            outcome = _write_one(f"写第{num}章：{titles[num]}", settings, plan=plans.get(num, ""))
            if outcome in ("failed", "interrupted"):
                if outcome == "interrupted":
                    print("已停止批量，已完成章节保留。")
                break  # T20/T22
            if outcome == "rejected" and auto:
                print(f"⛔ 第{num}章未过门禁，--auto 模式中断批量（已完成 {i - 1} 章）")
                break  # T19 fail-closed
            if i < n and not auto:
                if _gate_confirm(f"\n继续写第{num + 1}章？(y/n)：").strip().lower() != "y":
                    print("已停止批量，已完成章节保留。")  # T18
                    break
    except KeyboardInterrupt:
        print("\n已停止批量，已完成章节保留。")


# 单章无标题形态：写第N章（无冒号无标题，靠章纲供标题与规划，T15）
_SINGLE_NO_TITLE_RE = re.compile(r"^写\s*第\s*(\d+)\s*章$")


def _dispatch_write(line: str, settings: Settings) -> None:
    """写作命令分发（2.2，D7 分发序）：

    1. 剥 --auto 尾缀（一次性行为标志，非配置）；
    2. 区间命令（含单章区间 5-5，退化 T25）-> _do_write_batch；
    3. 单章无标题形态 -> 章纲取标题与规划，等价于敲了「写第N章：{章纲标题}」（T15）；
    4. 其余 -> _do_write 现状零改动（含「写第5章：标题」带标题单章，不进批量）。
    互斥性靠「先区间后单章」：单章带标题命令不匹配区间正则（无第二数字）。
    """
    task = line.strip()
    auto = False
    if task.endswith("--auto"):
        auto = True
        task = task[: -len("--auto")].strip()
    if not task:
        print("❌ 空命令（--auto 需跟在写作命令后，如：写第5-10章 --auto）")
        return
    if parse_chapter_range(task) is not None:
        _do_write_batch(task, settings, auto)
        return
    m = _SINGLE_NO_TITLE_RE.match(task)
    if m:
        num = int(m.group(1))
        entry = _load_chapter_plan(settings).get(num)
        if entry is None:
            print(f"❌ 第{num}章无标题：每章规划（{settings.chapter_plan_subpath}）缺该章，"
                  f"或用「写第{num}章：标题」直接给标题")
            return
        _do_write(f"写第{num}章：{entry['title']}", settings, plan=_render_notes(entry))
        return
    _do_write(task, settings)


def _refine_postprocess(
    path: Path,
    content: str,
    state: PipelineState,
    record: Dict[str, Any],
    settings: Settings,
    agent: NovelAgent,
    wm: WorkingMemory,
    file_path: str,
    action: str = "精修",
) -> None:
    """精修/重写后的公共处理：落盘、评测、门禁、存回、差异。"""
    # 章标题保真（存回/评测/diff 三处一致）：polisher/writer 常不回显标题行
    # （真车 2026-09-19 精修第一卷-04 丢「## 第四章 余温」），落盘前以原文标题补回
    if state.final_chapter:
        state.final_chapter = preserve_leading_title(content, state.final_chapter)
        record["final_state"]["final_chapter"] = state.final_chapter
    print("💾 落盘运行记录...")
    run_file = save_run(record, settings)

    # 自动评测（1.1：从尾部提前到分支判定前--门禁要用分；每命令仍恰一次评委调用）
    print("\n--- 自动评测 ---")
    score = None
    try:
        score = evaluate(record["run_id"], settings, instruction=agent.instruction)
    except Exception as e:
        print(f"(评测跳过：{e})")

    forced = "强制定稿" in state.feedback
    passed = "审稿通过" in state.feedback and not forced

    # 1.1 A30-A34：仅 passed 自动存回分支过门禁（D8）；forced 走 is_better 判优、
    # 人工确认豁免，未通过分支本就不存回，均不叠加门禁。
    gate_rejected = False
    if passed and state.final_chapter and "人工确认" not in state.feedback:
        if not _gate_ok(score, load_quality_rules(settings)):
            answer = _gate_confirm(f"\n⚠️ 评测低于门禁阈值，仍存回{action}结果？(y/n)：").strip().lower()
            if answer != "y":
                gate_rejected = True
                print(f"⚠️ 已放弃存回，原文件未改动。")
                print(f"   结果在运行日志中，可用 replay {record['run_id']} 查看")

    if passed and state.final_chapter and not gate_rejected:
        path.write_text(state.final_chapter, encoding="utf-8")
        print(f"✅ 已覆盖存回：{path}")
        print("📚 更新向量库...")
        try:
            agent.rag.add_document(file_path)
        except Exception as e:
            print(f"(索引更新失败：{e})")
        # 0.8 T11：存回后刷新工作记忆（精修不回退进度，D9-b）
        _refresh_working_memory(path, state, agent, wm, settings)
    elif forced and state.final_chapter:
        print(f"⚖️ 强制定稿，对比原文和{action}版本...")
        try:
            better = agent.is_better(content, state.final_chapter)
        except Exception:
            better = False
        if better:
            path.write_text(state.final_chapter, encoding="utf-8")
            print(f"✅ {action}版本优于原文，已覆盖存回：{path}")
            print("📚 更新向量库...")
            try:
                agent.rag.add_document(file_path)
            except Exception as e:
                print(f"(索引更新失败：{e})")
            # 0.8 T11：存回后刷新工作记忆（精修不回退进度，D9-b）
            _refresh_working_memory(path, state, agent, wm, settings)
        else:
            print(f"⚠️ {action}版本未优于原文，原文件未改动。")
            print(f"   结果在运行日志中，可用 replay {record['run_id']} 查看")
    elif state.final_chapter and not gate_rejected:
        print(f"⚠️ 审稿未通过（{state.feedback}），原文件未改动，结果未入库。")

    print("--- 流程日志 ---")
    for line in state.log:
        print(line)
    print(f"\n运行日志：{run_file}")
    print(f"共 {state.round} 轮，审稿：{state.feedback}")

    print(f"\n=== {action}差异（原文 -> {action}后）===")
    refined = state.final_chapter or ""
    if not refined:
        print(f"({action}结果为空)")
    elif refined == content:
        print("（无变化）")
    else:
        diff = difflib.unified_diff(
            content.splitlines(keepends=True),
            refined.splitlines(keepends=True),
            fromfile="原文", tofile=f"{action}后", n=1,
        )
        diff_text = "".join(diff)
        print(diff_text if diff_text else "（无变化）")


def _do_refine(args: List[str], settings: Settings) -> None:
    """精修 <文件路径>：读文件 -> polisher->reviewer -> 覆盖存回 -> 更新索引 -> 评测。"""
    if not args:
        print("用法：精修 <文件路径>（相对 NOVEL_DIR 或绝对路径）")
        return
    try:
        settings.require_novel_dir()
    except RuntimeError as e:
        print(f"❌ {e}")
        return

    file_path = " ".join(args)
    print("🔧 构建 Agent...")
    # 精修从 polisher 起，不走 writer -> 跳过 exemplar/滚动语料/路由（纯省，行为零变化）
    # active_file：C18 防自比（被精修章从参照集排除）
    try:
        agent, wm, _route = _build_agent(
            settings, task=f"精修：{file_path}", need_style=False, active_file=file_path)
    except RuntimeError as e:  # 1.1 A23：装配错误命令层兜住，不崩 REPL
        print(f"❌ {e}")
        return
    rag = agent.rag
    abs_path = rag._resolve_source(file_path)
    path = Path(abs_path)
    if not path.is_file():
        print(f"❌ 找不到文件：{file_path}")
        return
    content = path.read_text(encoding="utf-8")
    if not content.strip():
        print(f"⚠️ 文件为空，跳过：{file_path}")
        return

    task = f"精修：{path.name}"
    print(f"🔧 开始精修：{path.name}（{len(content)} 字）\n")
    try:
        state, record = agent.refine(content, task)
    except Exception as e:
        print(f"❌ 精修失败：{e}")
        return

    _refine_postprocess(path, content, state, record, settings, agent, wm, file_path, action="精修")


def _do_rewrite(args: List[str], settings: Settings) -> None:
    """重写 <文件路径>：读文件 -> writer->polisher->reviewer -> 覆盖存回 -> 更新索引 -> 评测。"""
    if not args:
        print("用法：重写 <文件路径>（相对 NOVEL_DIR 或绝对路径）")
        return
    try:
        settings.require_novel_dir()
    except RuntimeError as e:
        print(f"❌ {e}")
        return

    file_path = " ".join(args)
    print("🔧 构建 Agent...")
    # exemplar-routing：重写按文件名路由样文（task=重写：文件名；路由失败回落）
    # active_file：C18 防自比（被重写章从参照集排除）
    try:
        agent, wm, _route = _build_agent(
            settings, task=f"重写：{file_path}", active_file=file_path)
    except RuntimeError as e:  # 1.1 A23：装配错误命令层兜住，不崩 REPL
        print(f"❌ {e}")
        return
    rag = agent.rag
    abs_path = rag._resolve_source(file_path)
    path = Path(abs_path)
    if not path.is_file():
        print(f"❌ 找不到文件：{file_path}")
        return
    content = path.read_text(encoding="utf-8")
    if not content.strip():
        print(f"⚠️ 文件为空，跳过：{file_path}")
        return

    task = f"重写：{path.name}"
    print(f"🔧 开始重写：{path.name}（参考原文 {len(content)} 字）\n")
    try:
        state, record = agent.rewrite(content, task)
    except Exception as e:
        print(f"❌ 重写失败：{e}")
        return

    _refine_postprocess(path, content, state, record, settings, agent, wm, file_path, action="重写")


# ---------- 去AI 手动命令（1.6 style-loop，B15/D7/D8）----------
def _deai_confirm(prompt: str) -> str:
    """去AI确认缝（模块级，测试可替换，同 _gate_confirm 的 0.1 模式）。

    EOF / Ctrl-C -> 返回 "n" 保守不存回。
    """
    try:
        return input(prompt)
    except (EOFError, KeyboardInterrupt):
        return "n"


def _do_deai(args: List[str], settings: Settings) -> None:
    """去AI <文件路径>：对已存章节手动跑人味重写（B15）。

    - 读文件 -> run_checks 定位（可定位 issue 为空 -> 提示退出，不空烧，B17）；
    - agent.deai_refine 重写 -> 前后 AI 味分对比展示（分不降也如实展示，
      人不被阈值绑架，Z3；不设阈值门槛，与自动 pass 两口径分家）-> y/n 确认
      -> 存回 + rag.add_document 更新索引（同 refine 尾处理）；
    - 不落 run record（D8：非流水线 run，人是标尺当场拍板，
      留痕 = 文件本身 + REPL 输出）。
    """
    if not args:
        print("用法：去AI <文件路径>（相对 NOVEL_DIR 或绝对路径）")
        return
    try:
        settings.require_novel_dir()
    except RuntimeError as e:
        print(f"❌ {e}")
        return

    file_path = " ".join(args)
    print("🔧 构建 Agent...")
    # 不路由不传 task（去AI 用不到 exemplar/滚动语料，构造副作用只是读文件，design §6）
    # active_file：C18 防自比（被去AI 章从参照集排除）
    try:
        agent, _wm, _route = _build_agent(settings, need_style=False, active_file=file_path)
    except RuntimeError as e:  # A23：装配错误命令层兜住，不崩 REPL
        print(f"❌ {e}")
        return
    abs_path = agent.rag._resolve_source(file_path)
    path = Path(abs_path)
    if not path.is_file():
        print(f"❌ 找不到文件：{file_path}")
        return
    # 逐字节保真：读 bytes 手动 decode（同 改 命令，防 universal newline 破坏 \r\n/BOM）
    content = path.read_bytes().decode("utf-8")
    if not content.strip():
        print(f"⚠️ 文件为空，跳过：{file_path}")
        return

    rules = load_quality_rules(settings)
    # 1.7：去AI 不经 agent 流水线，cross checks 在此直调（design §3.3 直调例外；
    # 参照集已在 _build_agent 构造，exclude=本文件，C18 语义落地）
    issues = [
        i for i in run_checks(content, rules) + run_cross_checks(content, agent.recent_endings, rules)
        if i.get("quote") and i["quote"] in content  # 只取可定位（B10）
    ]
    if not issues:
        print("无可定位问题句（质量规则未配置或无命中），跳过去AI。")
        return

    baseline = load_baseline(settings)
    before = ai_flavor_score(content, rules, baseline)["score"]
    print(f"🔧 开始去AI重写：{path.name}（AI味分 {before}/100，{len(issues)} 项可定位问题）\n")
    try:
        new_content, n_spans = agent.deai_refine(content, issues)
    except Exception as e:
        print(f"❌ 去AI重写失败：{e}")
        return
    after = ai_flavor_score(new_content, rules, baseline)["score"]
    verdict = "（下降）" if after < before else "（未下降，请自行判断是否保留）"
    print(f"\nAI味分：{before} -> {after}{verdict}（重写 {n_spans} 段）")

    if new_content != content:
        print("\n=== 去AI差异（原文 -> 重写后）===")
        diff_text = "".join(difflib.unified_diff(
            content.splitlines(keepends=True),
            new_content.splitlines(keepends=True),
            fromfile="原文", tofile="重写后", n=1,
        ))
        print(diff_text if diff_text else "（无变化）")

    answer = _deai_confirm("\n确认存回？(y/n)：").strip().lower()
    if answer != "y":
        print("已放弃，原文件未改动。")
        return
    path.write_bytes(new_content.encode("utf-8"))
    print(f"✅ 已存回：{path}")
    print("📚 更新向量库...")
    try:
        agent.rag.add_document(file_path)
    except Exception as e:
        print(f"(索引更新失败：{e})")


def _span_text(blocks: List[Block], span: Tuple[int, int]) -> str:
    """区间覆盖的全部块的 body 拼接（块间空行），与 agent.partial_refine 的选区一致。"""
    index_of = {b.no: i for i, b in enumerate(blocks) if b.no is not None}
    lo, hi = span
    return "\n\n".join(b.body for b in blocks[index_of[lo]:index_of[hi] + 1])


def _do_partial(args: List[str], settings: Settings) -> None:
    """改 <文件路径>：列出段落 -> 选段 -> 逐区间局部润色 -> diff 确认 -> 逐字节存回。

    只改选区，选区外字节逐字节不变；确认 y 前不落盘。
    任一环节 Ctrl-C/Ctrl-D（含 LLM 生成中途）视为取消，文件不动（R1）。
    """
    if not args:
        print("用法：改 <文件路径>（相对 NOVEL_DIR 或绝对路径）")
        return
    try:
        settings.require_novel_dir()
    except RuntimeError as e:
        print(f"❌ {e}")
        return
    try:
        _do_partial_flow(args, settings)
    except (KeyboardInterrupt, EOFError):
        # R1：整体兜底（覆盖 LLM 生成中途的 Ctrl-C），取消时文件必然未动
        print("\n已取消，文件未改动。")


def _do_partial_flow(args: List[str], settings: Settings) -> None:
    """_do_partial 主体（参数与目录校验之后）。"""
    file_path = " ".join(args)  # 容忍路径含空格（同精修/重写）
    print("🔧 构建 Agent...")
    # A7：改（局部精修）不走 writer -> 跳过 exemplar/滚动语料/路由（零新增 token）
    try:
        agent, _, _ = _build_agent(settings, need_style=False)
    except RuntimeError as e:  # 1.1 A23：装配错误命令层兜住，不崩 REPL
        print(f"❌ {e}")
        return
    abs_path = agent.rag._resolve_source(file_path)
    path = Path(abs_path)
    if not path.is_file():
        print(f"❌ 找不到文件：{file_path}")
        return

    # 逐字节保真：读 bytes 手动 decode（不用 read_text，防 universal newline 破坏 \r\n/BOM）
    text = path.read_bytes().decode("utf-8")
    if not text.strip():
        print(f"⚠️ 文件为空，跳过：{file_path}")
        return

    blocks = split_paragraphs(text)
    paras = [b for b in blocks if b.no is not None]
    print(f"\n共 {len(blocks)} 个块，{len(paras)} 段可编号：")
    for b in blocks:
        line = preview_line(b)
        if line:
            print(line)
    if not paras:
        print("无可选段落。")
        return
    max_no = max(b.no for b in paras)

    # ---- 选段（非法重输；空回车/q 取消）----
    while True:
        try:
            spec = input("\n选段（如 3 / 3-5 / 3,7；回车或 q 取消）：").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n已取消。")
            return
        if not spec or spec.lower() == "q":
            print("已取消。")
            return
        try:
            spans = parse_selection(spec, max_no)
            break
        except ValueError as e:
            print(f"❌ {e}")

    old_texts = [_span_text(blocks, s) for s in spans]
    total_paras = sum(hi - lo + 1 for lo, hi in spans)
    total_chars = sum(len(t) for t in old_texts)
    span_labels = "、".join(
        f"第{lo}段" if lo == hi else f"第{lo}-{hi}段" for lo, hi in spans
    )
    print(f"\n已选 {total_paras} 段（{span_labels}），共 {total_chars} 字。")

    # ---- 逐区间调用 LLM ----
    task = f"局部精修：{path.name}"
    results = agent.partial_refine(blocks, spans, task)
    if any(r is None for r in results):
        print("❌ 模型未返回内容，未改动。")
        return

    # 长度突变警告（D6：>3×/⅓ 警告不拦截；len(old)>=50 前置避免短选区噪音）
    for (lo, hi), old, new in zip(spans, old_texts, results):
        if len(old) >= 50 and (len(new) > 3 * len(old) or len(new) < len(old) / 3):
            print(f"  ⚠️ 第{lo}-{hi}段长度异常：{len(old)} 字 -> {len(new)} 字"
                  "（疑似返回整章/内容坍缩），请仔细核对 diff。")

    # ---- diff（多区间按区间分段展示，R2）----
    print("\n=== 局部精修差异（选区原文 -> 改后）===")
    for (lo, hi), old, new in zip(spans, old_texts, results):
        tag = f"第{lo}段" if lo == hi else f"第{lo}-{hi}段"
        print(f"\n--- {tag} ---")
        if new == old:
            print("（无变化）")
            continue
        diff_text = "".join(difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile="原文", tofile="改后", n=1,
        ))
        print(diff_text if diff_text else "（无变化）")

    # ---- 确认存回 ----
    try:
        answer = input("\n确认存回？(y/n)：").strip().lower()
    except (KeyboardInterrupt, EOFError):
        print("\n已取消。")
        return
    if answer != "y":
        print("已放弃，原文件未改动。")
        return

    new_content = apply_replacements(text, blocks, spans, results)
    # 逐字节保真：write_bytes（不用 write_text，防 \n 翻译成 os.linesep）
    path.write_bytes(new_content.encode("utf-8"))
    print(f"✅ 已存回：{path}")

    # ---- P1 run 留痕（确认 y 之后才落盘，取消不留痕，见 design.md §5.6）----
    run_id = "partial_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    record = {
        # replay 直读的必需键（harness.replay 无缺键容错，缺任一 KeyError）
        "run_id": run_id,
        "task": task,
        "timestamp": datetime.datetime.now().isoformat(),
        "config": {
            "mode": "partial-refine",
            "model": settings.model,
            # 局部精修实际走 polisher 温度（agent._temp 同款回落链），记录真值
            "temperature": (
                settings.polisher_temperature
                if settings.polisher_temperature is not None
                else settings.llm_temperature
                if settings.llm_temperature is not None
                else 0.6
            ),
            "max_tokens": 4096,
        },
        "initial_state": {"task": task},
        "steps": [],  # 局部精修不走状态机，replay 打印「共 0 步」
        "final_state": {"final_chapter": new_content},  # 回填后全文
        # partial 特有：mode/文件路径/选区区间/各区间原文改后/确认结果
        "mode": "partial-refine",
        "file": str(path),
        "spans": [[lo, hi] for lo, hi in spans],
        "changes": [
            {"span": [lo, hi], "old": old, "new": new}
            for (lo, hi), old, new in zip(spans, old_texts, results)
        ],
        "confirmed": True,
    }
    try:
        run_file = save_run(record, settings)
        print(f"📝 运行日志：{run_file}")
    except Exception as e:
        print(f"(运行日志写入失败：{e})")

    print("📚 更新向量库...")
    try:
        agent.rag.add_document(file_path)
    except Exception as e:
        print(f"(索引更新失败：{e})")


def _do_index(args: List[str], settings: Settings) -> None:
    """index 子命令：无参=状态+帮助；rebuild=全量重建；add/remove <路径>=单文件增删。"""
    try:
        settings.require_novel_dir()
    except RuntimeError as e:
        print(f"❌ {e}")
        return
    rag = RAGStore(settings=settings)
    sub = args[0] if args else ""

    if sub == "rebuild":
        print("🔧 开始全量重建（遵守 NOVEL_INDEX_EXCLUDE，不索引正文）...")
        rag.build_index()
    elif sub == "add":
        if len(args) < 2:
            print("用法：index add <文件路径>（相对 NOVEL_DIR 或绝对路径）")
            return
        path = " ".join(args[1:])  # 容忍路径含空格
        try:
            rag.add_document(path)
        except FileNotFoundError:
            print(f"❌ 找不到文件：{path}")
        except Exception as e:
            print(f"❌ 添加失败：{e}")
    elif sub == "remove":
        if len(args) < 2:
            print("用法：index remove <文件路径>（相对 NOVEL_DIR 或绝对路径）")
            return
        path = " ".join(args[1:])
        try:
            n = rag.remove_document(path)
            print(f"✅ 已删除 {n} 块" if n else f"⚠️ 向量库中没有该文件的块：{path}")
        except Exception as e:
            print(f"❌ 删除失败：{e}")
    elif sub == "clear-chapters":
        # 手改大量正文后一键清陈块（设定/文风基准块不动；前文连贯靠工作记忆+滚动注入）
        try:
            n = rag.remove_chapters()
            print(f"✅ 已清空全部正文块（{n} 块）" if n else "⚠️ 向量库中没有正文块")
        except Exception as e:
            print(f"❌ 清空失败：{e}")
    else:
        # 无参或未知子命令：显示状态 + 帮助
        try:
            n = rag.count
        except Exception:
            n = 0
        print(f"向量库现有 {n} 块 @ {settings.chroma_path}")
        print("子命令：")
        print("  index rebuild         全量重建（遵守 NOVEL_INDEX_EXCLUDE，不索引正文）")
        print("  index add <路径>      手动加单文件（相对 NOVEL_DIR 或绝对路径；不受排除限制）")
        print("  index remove <路径>   手动删某文件的所有块")
        print("  index clear-chapters  清空全部正文块（手改大量正文后一键清陈块）")


def _print_unresolved(wm: WorkingMemory) -> None:
    """打印未回收伏笔全量（`伏笔` 列表形态，F8：命令侧不截断）。"""
    lines = wm.foreshadow_lines()
    if not lines:
        print("未回收伏笔：无（可 `伏笔 加 <描述>` 手动补录）")
        return
    print(f"未回收伏笔（共 {len(lines)} 条）：")
    print("\n".join(lines))


def _print_resolved(wm: WorkingMemory) -> None:
    """打印已回收归档（`伏笔 已回收`，F15：误判可人工抄回）。"""
    items = wm.resolved_foreshadowing
    if not items:
        print("已回收伏笔：无")
        return
    print(f"已回收伏笔（共 {len(items)} 条）：")
    for i, entry in enumerate(items, 1):
        chapter = entry.get("chapter")
        resolved = entry.get("resolved_chapter")
        buried = f"第{chapter}章埋" if isinstance(chapter, int) else "埋设章号未知"
        paid = f"第{resolved}章收" if isinstance(resolved, int) else "回收章号未知"
        print(f"  {i}.（{buried}，{paid}）{entry.get('desc', '')}")


def _foreshadow_delete(wm: WorkingMemory, tokens: List[str], settings: Settings) -> None:
    """`伏笔 删 N...`：出列入归档（与模型回收同路径），一次算索引集再删（Z4 防错位）。"""
    if not tokens:
        print("用法：伏笔 删 <编号>（多个编号空格分隔，如 `伏笔 删 2 5`）")
        return
    indices: List[int] = []
    for token in tokens:
        try:
            indices.append(int(token))
        except ValueError:
            print(f"❌ 编号必须是数字：{token}")
            return
    moved = wm.resolve_foreshadowing(indices, wm.current_chapter)
    if not moved:
        print(f"⚠️ 没有有效编号，未作改动（当前共 {len(wm.unresolved_foreshadowing)} 条）")
        return
    save_working_memory(wm, settings)
    print(f"✅ 已标记回收 {len(moved)} 条"
          f"（`伏笔 已回收` 可查；误删可用 `伏笔 加 <描述>` 补回）")


def _foreshadow_add(wm: WorkingMemory, tokens: List[str], settings: Settings) -> None:
    """`伏笔 加 <描述>`：人工补录（manual 标记，不被同章覆盖清洗清掉，F16 守卫）。"""
    desc = " ".join(tokens).strip()
    if not desc:
        print("用法：伏笔 加 <描述>")
        return
    wm.add_foreshadowing(desc, chapter=wm.current_chapter, manual=True)
    save_working_memory(wm, settings)
    where = f"（第{wm.current_chapter}章埋）" if wm.current_chapter is not None else "（章号未知）"
    print(f"✅ 已补录 1 条{where}：{desc}")


def _do_foreshadow(args: List[str], settings: Settings) -> None:
    """伏笔命令（3.1 F9/F10/F15）：列表 / 删 N... / 加 <描述> / 已回收。

    编号 = 列表序号（1 起）；删不是物理删除而是归档（一切「从清单消失」都可恢复）。
    """
    try:
        settings.require_novel_dir()
    except RuntimeError as e:
        print(f"❌ {e}")
        return
    wm = load_working_memory(settings)
    if not args:
        _print_unresolved(wm)
        return
    sub, rest = args[0], args[1:]
    if sub == "已回收":
        _print_resolved(wm)
    elif sub == "删":
        _foreshadow_delete(wm, rest, settings)
    elif sub == "加":
        _foreshadow_add(wm, rest, settings)
    else:
        print(f"未知子命令：{sub}"
              f"（用法：伏笔 / 伏笔 删 <编号> / 伏笔 加 <描述> / 伏笔 已回收）")


def _print_characters(wm: WorkingMemory) -> None:
    """打印跟踪角色全量（`角色` 列表形态，C8：命令侧不截断）。"""
    if not wm.character_states:
        print("跟踪角色：无（写一章后自动抽取出场主要角色）")
        return
    print(f"跟踪角色（共 {len(wm.character_states)} 个）：")
    for name, entry in wm.character_states.items():
        chapter = entry.get("chapter")
        where = f"第{chapter}章" if isinstance(chapter, int) else "章号未知"
        print(f"  {name}（{where}）：{entry.get('stage', '')}")
        detail = "｜".join(
            f"{label}：{entry[key]}"
            for key, label in (("goal", "目标"), ("conflict", "冲突"), ("belief", "信念"))
            if entry.get(key)
        )
        if detail:
            print(f"    {detail}")
        history = entry.get("history") or []
        if history:
            print(f"    历史变化 {len(history)} 次：{' -> '.join(h.get('stage', '') for h in history)}")


def _character_delete(wm: WorkingMemory, args: List[str], settings: Settings) -> None:
    """`角色 删 <名字>`：停止跟踪（直接移除不归档，Z4；再出场会被抽取重新发现）。"""
    name = " ".join(args).strip()
    if not name:
        print("用法：角色 删 <名字>")
        return
    if wm.remove_character(name):
        save_working_memory(wm, settings)
        print(f"✅ 已停止跟踪：{name}（该角色再出场会被抽取重新发现）")
    else:
        print(f"⚠️ 没有这个角色：{name}（`角色` 可查看当前跟踪名单）")


def _character_revise(wm: WorkingMemory, args: List[str], settings: Settings) -> None:
    """`角色 改 <名字> <新阶段>`：人工修正当前阶段（D9：不打 manual，下章抽取在其基础上演进）。"""
    if len(args) < 2:
        print("用法：角色 改 <名字> <新阶段>")
        return
    name, stage = args[0], " ".join(args[1:]).strip()
    if not stage:
        print("用法：角色 改 <名字> <新阶段>")
        return
    if wm.revise_character_stage(name, stage, chapter=wm.current_chapter):
        save_working_memory(wm, settings)
        print(f"✅ 已修正 {name} 的当前阶段：{stage}")
    else:
        print(f"⚠️ 没有这个角色：{name}（`角色` 可查看当前跟踪名单）")


def _do_character(args: List[str], settings: Settings) -> None:
    """角色命令（3.2 C9/C10）：列表 / 删 <名字> / 改 <名字> <新阶段>。"""
    try:
        settings.require_novel_dir()
    except RuntimeError as e:
        print(f"❌ {e}")
        return
    wm = load_working_memory(settings)
    if not args:
        _print_characters(wm)
        return
    sub, rest = args[0], args[1:]
    if sub == "删":
        _character_delete(wm, rest, settings)
    elif sub == "改":
        _character_revise(wm, rest, settings)
    else:
        print(f"未知子命令：{sub}"
              f"（用法：角色 / 角色 删 <名字> / 角色 改 <名字> <新阶段>）")


def _do_status(settings: Settings) -> None:
    wm = load_working_memory(settings)
    print("=== 当前状态 ===")
    if wm.current_chapter is None:
        print("尚未创作任何章节。")
        # F17：首章前手工补录的伏笔也要可见（只补伏笔块，不打整份 snapshot 免「第None章」噪音）
        if wm.unresolved_foreshadowing:
            _print_unresolved(wm)
    else:
        print(wm.snapshot())
    runs = list_runs(settings)
    print(f"\n运行记录：{len(runs)} 次，最近 {runs[:3]}")
    if settings.chapter_path.exists():
        chapters = list(settings.chapter_path.glob("*.md"))
        print(f"已生成章节文件：{len(chapters)} 个 @ {settings.chapter_path}")
    # 0.5：文风基准语料清单（文件数/总字数，截断前的真实体量）
    if settings.exemplar_subpath and settings.exemplar_full.exists():
        files, chars = exemplar_info(settings.exemplar_full)
        print(f"文风基准：{files} 个文件，共 {chars} 字 @ {settings.exemplar_full}")
    # 1.1 Z7：质量规则 / 人工语料状态行（防静默失效）
    if settings.quality_rules_subpath:
        try:
            rules = load_quality_rules(settings)
        except RuntimeError as e:
            print(f"质量规则：❌ {e}")
        else:
            if rules is None:
                print(f"质量规则：未找到 {settings.quality_rules_full}（checker 与门禁不启用）")
            else:
                n_words = len(rules.get("blacklist") or []) + len(
                    (rules.get("naming_redlines") or {}).get("forbidden") or [])
                print(f"质量规则：黑名单 {n_words} 词 @ {settings.quality_rules_full}")
    else:
        print("质量规则：未配置（NOVEL_QUALITY_RULES 为空，checker 与门禁不启用）")
    if settings.human_text_subpath:
        if settings.human_text_full.is_dir():
            n_files = sum(
                1 for q in settings.human_text_full.iterdir()
                if q.is_file() and q.suffix.lower() in (".txt", ".md")
            )
            print(f"人工语料：{n_files} 个文件 @ {settings.human_text_full}")
        else:
            print(f"人工语料：未找到 {settings.human_text_full}（AI 味基准不含人工语料）")
    else:
        print("人工语料：未配置（NOVEL_HUMAN_TEXT 为空）")
    # 1.5 滚动注入状态行（B6/Z7：配置静默失效必须可发现）
    if settings.style_recent_n <= 0:
        print(f"滚动注入：已禁用（NOVEL_STYLE_RECENT_N=0）")
    elif not settings.human_text_subpath:
        print("滚动注入：未配置（NOVEL_HUMAN_TEXT 为空，本次不注入）")
    elif settings.human_text_full.is_dir() and any(
        q.is_file() and q.suffix.lower() in (".txt", ".md")
        for q in settings.human_text_full.iterdir()
    ):
        print(
            f"滚动注入：最近 {settings.style_recent_n} 章 · "
            f"每章 {settings.style_slice_chars} 字"
        )
    else:
        print("滚动注入：人工语料为空，本次不注入")
    # exemplar-routing：标签文件启用情况（不存在则不显示，不添噪音）
    tags = _load_exemplar_tags(settings)
    if tags:
        print(f"样文路由：启用（{len(tags)} 条标签 @ {settings.exemplar_tags_full}）")
    # 3.3 planner：开关状态行（P12 可发现性）
    if settings.planner_enabled:
        print("planner：开（先规划节拍再写，reviewer 拿节拍当验收基准）")
    else:
        print("planner：关（writer 自行构思；NOVEL_PLANNER=1 开启）")
    # 1.7 跨章禁则状态行（C12：配置静默失效必须可发现）
    try:
        rules = load_quality_rules(settings)
    except RuntimeError as e:
        print(f"跨章禁则：❌ {e}")
    else:
        end_cfg = (rules or {}).get("ending") or {}
        syn_cfg = (rules or {}).get("syntax_patterns") or {}
        if not (end_cfg or syn_cfg):
            print("跨章禁则：未配置（质量规则.json 缺 ending / syntax_patterns 键）")
        else:
            parts = []
            if end_cfg:
                endings = load_recent_endings(
                    settings.human_text_full, end_cfg.get("lookback", 10))
                taboos = build_style_taboos(endings, rules)
                n_ban = len([ln for ln in taboos.splitlines() if ln.startswith("- 收束句")])
                parts.append(f"参照最近 {end_cfg.get('lookback', 10)} 章（实得 {len(endings)} 章）"
                             f" · 禁用收束句 {n_ban} 条")
            if syn_cfg:
                parts.append(f"句式配额 {len(syn_cfg.get('patterns') or [])} 条")
            print("跨章禁则：" + " · ".join(parts))


def _do_style_scan(args: List[str], settings: Settings) -> None:
    """风格体检 [目录]（1.9 诊断，C13-C15）：纯代码扫描，零 LLM 调用。

    - 目录参数可选（相对 NOVEL_DIR 解析或绝对），默认人工正文目录；
    - 三节报告：收束句复读榜 / 句式命中榜 / 分卷字数分布（服务人工改稿决策）；
    - 不落 run record（D9：诊断工具，人是标尺，同去AI 命令先例）；
    - 目录不存在 / 无可扫描文件 -> 提示后正常退出（C15，不崩 REPL）。
    """
    try:
        settings.require_novel_dir()
    except RuntimeError as e:
        print(f"❌ {e}")
        return
    target = " ".join(args) if args else ""
    if target:
        p = Path(target).expanduser()
        dir_path = p if p.is_absolute() else settings.novel_path / p
    else:
        dir_path = settings.human_text_full
    if not dir_path.is_dir():
        print(f"❌ 目录不存在：{dir_path}")
        return
    try:
        rules = load_quality_rules(settings)
    except RuntimeError as e:  # A23：非法 pattern 等，命令层兜住
        print(f"❌ {e}")
        return
    report = scan_style_report(dir_path, rules)
    if not report["files_scanned"]:
        print(f"无可扫描的 .md/.txt 文件 @ {dir_path}")
        return

    print(f"=== 风格体检 @ {dir_path}（{report['files_scanned']} 个文件，零 LLM）===\n")

    print("--- 收束句复读榜（归一化结尾按出现次数降序）---")
    if report["endings"]:
        for row in report["endings"]:
            print(f"\n「{row['ending']}」× {row['count']} 次")
            for f in row["files"]:
                print(f"    {f}")
    else:
        print("（无达到阈值的复读结尾）")

    print("\n--- 句式命中榜（各模板总次数 + 超配额章清单）---")
    if report["patterns"]:
        for row in report["patterns"]:
            print(f"\n「{row['pattern']}」共 {row['total']} 次")
            for over in row["over"]:
                print(f"    超配额：{over['file']}（{over['count']} 次）")
    else:
        print("（未配置 syntax_patterns 或无命中）")

    print("\n--- 字数分布（按顶层子目录分组）---")
    print(f"{'分组':<10}{'章数':>5}{'最小':>8}{'最大':>8}{'均值':>9}{'变异系数':>9}")
    for row in report["sizes"]:
        print(f"{row['group']:<10}{row['n']:>5}{row['min']:>8}{row['max']:>8}"
              f"{row['mean']:>9}{row['cv']:>9}")

    # event-anchor E9：第四节「状态章嫌疑榜」（纯代码零 LLM）。
    # E9/E12 拍板（2026-09-20）：未配置也固定输出提示行（与句式命中榜节同作风）。
    print("\n--- 状态章嫌疑榜（嫌疑分=状态词命中/有效行−对话行/有效行×2，降序 Top 20）---")
    rows = report["state_chapters"]
    if rows is None:
        print("状态章嫌疑榜：未配置 chapter_structure.state_words，跳过")
    elif not rows:
        print("（已配置 state_words，但无可计算的章节）")
    else:
        print(f"{'文件':<28}{'嫌疑分':>8}{'行数':>6}{'对话行':>7}{'状态词':>7}")
        for row in rows[:20]:
            print(f"{row['file']:<28}{row['score']:>8}{row['lines']:>6}"
                  f"{row['dialogue']:>7}{row['state_hits']:>7}")
        if len(rows) > 20:
            print(f"…（共{len(rows)}章，仅列 Top 20）")


def _do_replay(args: List[str], settings: Settings) -> None:
    if not args:
        print("用法：replay <run_id>")
        return
    try:
        replay(args[0], settings)
    except FileNotFoundError:
        print(f"❌ 找不到运行记录：{args[0]}")

def _do_eval(args: List[str], settings: Settings) -> None:
    if not args:
        print("用法：eval <run_id>")
        return
    try:
        evaluate(args[0], settings, instruction=_load_instruction(settings))
    except FileNotFoundError:
        print(f"❌ 找不到运行记录：{args[0]}")
    except RuntimeError as e:  # 1.1 A23：质量规则非法 JSON 等，命令层兜住不崩 REPL
        print(f"❌ {e}")


def _do_compare(args: List[str], settings: Settings) -> None:
    if len(args) < 2:
        print("用法：compare <run_id_a> <run_id_b>")
        return
    try:
        compare(args[0], args[1], settings)
    except FileNotFoundError as e:
        print(f"❌ 找不到运行记录：{e}")
    except RuntimeError as e:  # 1.1 A23：质量规则非法 JSON 等，命令层兜住不崩 REPL
        print(f"❌ {e}")


def _do_test(args: List[str], settings: Settings) -> None:
    if not args:
        print("用法：test <run_id>")
        return
    try:
        run_tests(args[0], settings)
    except FileNotFoundError:
        print(f"❌ 找不到运行记录：{args[0]}")
    except RuntimeError as e:  # 1.1 A23：质量规则非法 JSON 等，命令层兜住不崩 REPL
        print(f"❌ {e}")


def _do_backtest(args: List[str], settings: Settings) -> None:
    """回测门禁 [条数]：历史 runs 逐条跑评委，输出加权分分布与候选阈值拦截面。"""
    limit = None
    if args:
        try:
            limit = int(args[0])
        except ValueError:
            print("用法：回测门禁 [条数]（条数为正整数，可省略）")
            return
    try:
        backtest_gate(settings, limit=limit)
    except RuntimeError as e:  # 1.1 A23：质量规则非法 JSON 等，命令层兜住不崩 REPL
        print(f"❌ {e}")


def _print_help() -> None:
    print("命令：")
    print("  写第N章：标题     走完整流程写一章（查设定->草稿->润色->审稿->打分门禁->存文件）")
    print("  写第N章           无标题形态：从每章规划（NOVEL_CHAPTER_PLAN）取标题与本章规划")
    print("  写第A-B章         批量连写区间章（章纲逐章供标题与规划，章间 y/n 确认）")
    print("  写第A-B章 --auto  批量免确认连写（门禁不过/失败自动停，fail-closed）")
    print("  写第A-B章：模板   批量回落：模板+中文序数后缀作标题，章纲规划照注入")
    print("  精修 <文件路径>   精修已有正文（润色->审稿->存回->更新索引，不写新场景）")
    print("  重写 <文件路径>   重写已有正文（writer参考原文重写->润色->审稿->存回，能大幅扩写）")
    print("  改 <文件路径>     局部精修（列出段落->选段 3/3-5/3,7->只润色选区->diff 确认->逐字节存回）")
    print("  去AI <文件路径>   人味重写（定位问题句->重写->AI味分对比->y/n 确认->存回+更新索引）")
    print("  index            查看向量库；index rebuild 全量重建；index add/remove <路径> 单文件增删")
    print("  replay <run_id>  回放某次写作过程")
    print("  eval <run_id>    对某次写作打分")
    print("  compare <a> <b>  对比两次写作效果")
    print("  test <run_id>    规则断言测试")
    print("  回测门禁 [条数]  历史runs跑评委回测门禁阈值（分数有缓存，命中不重烧）")
    print("  状态             查看当前写到第几章、角色状态、未回收伏笔")
    print("  风格体检 [目录]  文风复读诊断（收束句复读榜/句式命中榜/字数分布/状态章嫌疑榜，零 LLM）")
    print("  伏笔             查看未回收伏笔（编号+埋设章+描述）")
    print("  伏笔 删 <编号>    标记已回收（出列入归档，`伏笔 已回收` 可查可找回；多个编号空格分隔）")
    print("  伏笔 加 <描述>    手动补录一条（埋设章号取当前章，不被同章重写覆盖）")
    print("  伏笔 已回收       查看已回收归档（描述 + 埋设章 + 回收章）")
    print("  角色             查看跟踪角色（更新章+阶段+目标/冲突/信念+历史变化）")
    print("  角色 删 <名字>    停止跟踪一个角色（再出场会被抽取重新发现）")
    print("  角色 改 <名字> <新阶段>  人工修正当前阶段（下章抽取在其基础上演进）")
    print("  help / quit")


# ---------- 主循环 ----------
def main() -> None:
    settings = get_settings()
    history_file = os.path.expanduser("~/.novel_agent_history")
    # 懒加载 readline（macOS 自带；启用后 input() 支持上下键切换历史命令）：
    # 无 tty 环境（sandbox/CI/管道）import readline 会无限阻塞，故不能放模块顶部
    # ——测试只 import 本模块不进 REPL，懒加载后无 tty 环境也能安全 import cli。
    try:
        import readline
    except ImportError:  # 未编译 readline 的环境：历史功能禁用，CLI 照常可用
        readline = None
    if readline:
        readline.set_history_length(1000)
        try:
            readline.read_history_file(history_file)
        except FileNotFoundError:
            pass

    try:
        print(f"✦ Novel Agent v0.1.0 -- 《{settings.novel_name}》创作助手")
        print("输入 help 查看命令，quit 退出。\n")

        while True:
            try:
                line = input(">>> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not line:
                continue

            # 写作命令：以"写"开头（单章/区间批量/章纲单章，分发序见 _dispatch_write）
            if line.startswith("写"):
                _dispatch_write(line, settings)
                continue

            parts = line.split()
            cmd = parts[0].lower()
            args = parts[1:]

            if cmd in ("quit", "exit", "q"):
                print("再见。")
                break
            elif cmd in ("help", "h", "?"):
                _print_help()
            elif cmd == "精修":
                _do_refine(args, settings)
            elif cmd == "重写":
                _do_rewrite(args, settings)
            elif cmd == "改":
                _do_partial(args, settings)
            elif cmd in ("去ai", "去AI"):
                _do_deai(args, settings)
            elif cmd == "index":
                _do_index(args, settings)
            elif cmd in ("状态", "status"):
                _do_status(settings)
            elif cmd == "风格体检":
                _do_style_scan(args, settings)
            elif cmd == "伏笔":
                _do_foreshadow(args, settings)
            elif cmd == "角色":
                _do_character(args, settings)
            elif cmd == "replay":
                _do_replay(args, settings)
            elif cmd == "eval":
                _do_eval(args, settings)
            elif cmd == "compare":
                _do_compare(args, settings)
            elif cmd == "test":
                _do_test(args, settings)
            elif cmd == "回测门禁":
                _do_backtest(args, settings)
            else:
                print(f"未知命令：{cmd}（输入 help 查看命令）")
    finally:
        # 退出时保存历史（quit / Ctrl-D / Ctrl-C / 异常 都会走到这里）
        if readline:
            try:
                readline.write_history_file(history_file)
            except OSError:
                pass


if __name__ == "__main__":
    main()
