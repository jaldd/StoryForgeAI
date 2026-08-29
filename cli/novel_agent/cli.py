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
  help / quit
"""
from __future__ import annotations

import datetime
import difflib
import os
from pathlib import Path
from typing import Any, Dict, List, Tuple

try:  # macOS 自带；启用后 input() 支持上下键切换历史命令
    import readline
except ImportError:  # 未编译 readline 的环境：历史功能禁用，CLI 照常可用
    readline = None

from .agent import NovelAgent
from .checker import load_quality_rules
from .config import Settings, get_settings
from .harness import backtest_gate, compare, evaluate, replay, run_tests
from .llm import LLMClient, load_profiles
from .memory import WorkingMemory
from .partial import Block, apply_replacements, parse_selection, preview_line, split_paragraphs
from .prompts import exemplar_info, load_exemplar
from .rag import RAGStore
from .routing import parse_tag_lines, route_exemplars
from .state import PipelineState
from .storage import (
    list_runs,
    load_working_memory,
    parse_chapter_file,
    parse_chapter_task,
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
    try:
        route = route_exemplars(router_llm, task, tags)
    except Exception as e:
        print(f"(样文路由失败，回落全量加载：{e})")
        return None, None
    if route is None:
        print("(样文路由未返回有效结果，回落全量加载)")
        return None, None
    print(f"🧭 样文路由：{'、'.join(route.files)}（{route.reason}）")
    return route.files, route


def _build_agent(settings: Settings, task: str = ""):
    """构造 NovelAgent：加载文风金标准 + 写作指令 + 写作铁律 + 工作记忆，RAG 惰性。

    0.7：load_profiles 一次解析，双 LLMClient 注入（llm=default profile，
    writer_llm=writer profile）；未配 WRITER_* 时两 profile 逐字段相等，
    行为与改造前完全一致（A9 回归保险）。
    1.1：质量规则 JSON 在装配点加载注入（非法 JSON fail-fast，A23）。
    exemplar-routing：task 非空且标签文件存在时先路由（一次廉价调用），按选中
    样文加载；路由任何失败回落现状（清单/全量）加载，永不阻塞写作。
    """
    only_files = None
    route = None
    if task:
        only_files, route = _route_exemplar_files(settings, task)
    exemplar = ""
    # 0.5：exemplar 支持目录级（目录下全部 *.txt/*.md 按序拼接，超限截断）
    if settings.exemplar_subpath and settings.exemplar_full.exists():
        exemplar = load_exemplar(settings.exemplar_full, only_files=only_files)
    instruction = _load_instruction(settings)
    rules = _load_rules(settings)
    quality_rules = load_quality_rules(settings)
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


# ---------- 命令处理 ----------
def _do_write(task: str, settings: Settings) -> None:
    try:
        settings.require_novel_dir()
    except RuntimeError as e:
        print(f"❌ {e}")
        return
    print("🔧 构建 Agent（加载设定/文风基准/写作指令）...")
    try:
        agent, wm, route = _build_agent(settings, task=task)
    except RuntimeError as e:  # 1.1 A23：质量规则非法 JSON 等装配错误，命令层兜住不崩 REPL
        print(f"❌ {e}")
        return
    print(f"✍️  开始创作：{task}\n")
    try:
        state, record = agent.run(task)
    except Exception as e:
        print(f"❌ 创作失败：{e}")
        return

    # exemplar-routing：路由结果进 run 记录（replay 可见，A5）
    if route is not None:
        record["exemplar_route"] = {"files": list(route.files), "reason": route.reason}

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
        wm.update_after_write(num, summary or task)
        save_working_memory(wm, settings)

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
    # exemplar-routing：精修也按文件名路由样文（task=精修：文件名；路由失败回落）
    try:
        agent, wm, _route = _build_agent(settings, task=f"精修：{file_path}")
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
    try:
        agent, wm, _route = _build_agent(settings, task=f"重写：{file_path}")
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
    # A7：改（局部精修）不路由不注入 exemplar（polisher_system 本就不带），零新增 token
    try:
        agent, _, _ = _build_agent(settings)
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
            "temperature": 0.6,
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


def _do_status(settings: Settings) -> None:
    wm = load_working_memory(settings)
    print("=== 当前状态 ===")
    if wm.current_chapter is None:
        print("尚未创作任何章节。")
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
    # exemplar-routing：标签文件启用情况（不存在则不显示，不添噪音）
    tags = _load_exemplar_tags(settings)
    if tags:
        print(f"样文路由：启用（{len(tags)} 条标签 @ {settings.exemplar_tags_full}）")


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
    print("  精修 <文件路径>   精修已有正文（润色->审稿->存回->更新索引，不写新场景）")
    print("  重写 <文件路径>   重写已有正文（writer参考原文重写->润色->审稿->存回，能大幅扩写）")
    print("  改 <文件路径>     局部精修（列出段落->选段 3/3-5/3,7->只润色选区->diff 确认->逐字节存回）")
    print("  index            查看向量库；index rebuild 全量重建；index add/remove <路径> 单文件增删")
    print("  replay <run_id>  回放某次写作过程")
    print("  eval <run_id>    对某次写作打分")
    print("  compare <a> <b>  对比两次写作效果")
    print("  test <run_id>    规则断言测试")
    print("  回测门禁 [条数]  历史runs跑评委回测门禁阈值（分数有缓存，命中不重烧）")
    print("  状态             查看当前写到第几章、角色状态、未回收伏笔")
    print("  help / quit")


# ---------- 主循环 ----------
def main() -> None:
    settings = get_settings()
    history_file = os.path.expanduser("~/.novel_agent_history")
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

            # 写作命令：以"写"开头（如"写第5章：异乡风起"）
            if line.startswith("写"):
                _do_write(line, settings)
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
            elif cmd == "index":
                _do_index(args, settings)
            elif cmd in ("状态", "status"):
                _do_status(settings)
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
