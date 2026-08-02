"""交互式命令行入口。

命令：
  写第N章：标题     走完整流程（查设定->草稿->润色->审稿->存文件->打分）
  精修 <文件路径>   精修已有正文（润色->审稿->存回->更新索引，不写新场景）
  index            查看向量库；index rebuild 全量重建；index add/remove <路径> 单文件增删
  replay <run_id>  回放某次写作过程
  eval <run_id>    对某次写作打分
  compare <a> <b>  对比两次写作效果
  状态             查看当前写到第几章、角色状态、未回收伏笔
  help / quit
"""
from __future__ import annotations

import difflib
import os
from pathlib import Path
from typing import Any, Dict, List

try:  # macOS 自带；启用后 input() 支持上下键切换历史命令
    import readline
except ImportError:  # 未编译 readline 的环境：历史功能禁用，CLI 照常可用
    readline = None

from .agent import NovelAgent
from .config import Settings, get_settings
from .harness import compare, evaluate, replay, run_tests
from .llm import LLMClient
from .memory import WorkingMemory
from .prompts import load_exemplar, PLOT_SUMMARY_SYSTEM
from .rag import RAGStore
from .state import PipelineState
from .storage import (
    list_runs,
    load_working_memory,
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


def _is_better(llm, original: str, refined: str) -> bool:
    """让 LLM 对比原文和润色版本，判断润色后是否更好。"""
    import json as _json
    result = llm.chat(
        "你是小说编辑。对比两段文字，判断第二段（润色后）是否比第一段（原文）更好。"
        "只返回纯 JSON：{\"better\": true/false}",
        f"【原文】\n{original[:2000]}\n\n【润色后】\n{refined[:2000]}\n\n"
        f"润色后是否比原文更好？只返回 JSON。",
        max_tokens=256,
        temperature=0.2,
    )
    if not result:
        return False
    try:
        return _json.loads(result.strip()).get("better", False)
    except Exception:
        return "true" in result.lower()


def _build_agent(settings: Settings):
    """构造 NovelAgent：加载文风金标准 + 写作指令 + 工作记忆，RAG 惰性。"""
    exemplar = ""
    if settings.exemplar_subpath and settings.exemplar_full.is_file():
        exemplar = load_exemplar(settings.exemplar_full)
    instruction = _load_instruction(settings)
    wm = load_working_memory(settings)
    agent = NovelAgent(
        llm=LLMClient(settings=settings),
        rag=RAGStore(settings=settings),
        exemplar=exemplar,
        instruction=instruction,
        settings=settings,
        working_memory=wm,
    )
    return agent, wm


# ---------- 命令处理 ----------
def _do_write(task: str, settings: Settings) -> None:
    try:
        settings.require_novel_dir()
    except RuntimeError as e:
        print(f"❌ {e}")
        return
    print("🔧 构建 Agent（加载设定/文风基准/写作指令）...")
    agent, wm = _build_agent(settings)
    print(f"✍️  开始创作：{task}\n")
    try:
        state, record = agent.run(task)
    except Exception as e:
        print(f"❌ 创作失败：{e}")
        return

    print("💾 落盘运行记录...")
    # 运行日志落盘
    run_file = save_run(record, settings)

    # 章节落盘 + 工作记忆更新
    chapter_file = None
    if state.final_chapter:
        print("📖 保存章节 + 生成剧情摘要...")
        chapter_file = save_chapter(state.final_chapter, task, record["run_id"], settings)
        num, _ = parse_chapter_task(task)
        # 生成剧情摘要存入工作记忆，让后续章节记得前文（P1 连续性）
        try:
            summary = agent.llm.chat(
                PLOT_SUMMARY_SYSTEM, state.final_chapter,
                max_tokens=1024, temperature=0.3,
            )
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
    print(state.final_chapter or "(空)")

    # 自动评测打分（失败不阻断）
    print("\n--- 自动评测 ---")
    try:
        evaluate(record["run_id"], settings, instruction=agent.instruction)
    except Exception as e:
        print(f"(评测跳过：{e})")


def _refine_postprocess(
    path: Path,
    content: str,
    state: PipelineState,
    record: Dict[str, Any],
    settings: Settings,
    agent: NovelAgent,
    file_path: str,
    action: str = "精修",
) -> None:
    """精修/重写后的公共处理：落盘、存回、差异、评测。"""
    print("💾 落盘运行记录...")
    run_file = save_run(record, settings)

    forced = "强制定稿" in state.feedback
    passed = "审稿通过" in state.feedback and not forced
    if passed and state.final_chapter:
        path.write_text(state.final_chapter, encoding="utf-8")
        print(f"✅ 已覆盖存回：{path}")
        print("📚 更新向量库...")
        try:
            agent.rag.add_document(file_path)
        except Exception as e:
            print(f"(索引更新失败：{e})")
    elif forced and state.final_chapter:
        print(f"⚖️ 强制定稿，对比原文和{action}版本...")
        try:
            better = _is_better(agent.llm, content, state.final_chapter)
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
        else:
            print(f"⚠️ {action}版本未优于原文，原文件未改动。")
            print(f"   结果在运行日志中，可用 replay {record['run_id']} 查看")
    elif state.final_chapter:
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

    print("\n--- 自动评测 ---")
    try:
        evaluate(record["run_id"], settings, instruction=agent.instruction)
    except Exception as e:
        print(f"(评测跳过：{e})")


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
    agent, _ = _build_agent(settings)
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

    _refine_postprocess(path, content, state, record, settings, agent, file_path, action="精修")


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
    agent, _ = _build_agent(settings)
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

    _refine_postprocess(path, content, state, record, settings, agent, file_path, action="重写")


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


def _do_compare(args: List[str], settings: Settings) -> None:
    if len(args) < 2:
        print("用法：compare <run_id_a> <run_id_b>")
        return
    try:
        compare(args[0], args[1], settings)
    except FileNotFoundError as e:
        print(f"❌ 找不到运行记录：{e}")


def _do_test(args: List[str], settings: Settings) -> None:
    if not args:
        print("用法：test <run_id>")
        return
    try:
        run_tests(args[0], settings)
    except FileNotFoundError:
        print(f"❌ 找不到运行记录：{args[0]}")


def _print_help() -> None:
    print("命令：")
    print("  写第N章：标题     走完整流程写一章（查设定->草稿->润色->审稿->存文件->打分）")
    print("  精修 <文件路径>   精修已有正文（润色->审稿->存回->更新索引，不写新场景）")
    print("  重写 <文件路径>   重写已有正文（writer参考原文重写->润色->审稿->存回，能大幅扩写）")
    print("  index            查看向量库；index rebuild 全量重建；index add/remove <路径> 单文件增删")
    print("  replay <run_id>  回放某次写作过程")
    print("  eval <run_id>    对某次写作打分")
    print("  compare <a> <b>  对比两次写作效果")
    print("  test <run_id>    规则断言测试")
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
