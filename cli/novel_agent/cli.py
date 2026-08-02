"""交互式命令行入口。

命令：
  写第N章：标题     走完整流程（查设定->草稿->润色->审稿->存文件->打分）
  index            建立/重建设定向量库
  replay <run_id>  回放某次写作过程
  eval <run_id>    对某次写作打分
  compare <a> <b>  对比两次写作效果
  状态             查看当前写到第几章、角色状态、未回收伏笔
  help / quit
"""
from __future__ import annotations

from pathlib import Path
from typing import List

from .agent import NovelAgent
from .config import Settings, get_settings
from .harness import compare, evaluate, replay, run_tests
from .llm import LLMClient
from .memory import WorkingMemory
from .prompts import load_exemplar, PLOT_SUMMARY_SYSTEM
from .rag import RAGStore
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
def _build_agent(settings: Settings):
    """构造 NovelAgent：加载文风金标准 + 工作记忆，RAG 惰性。"""
    exemplar = ""
    if settings.exemplar_subpath and settings.exemplar_full.is_file():
        exemplar = load_exemplar(settings.exemplar_full)
    wm = load_working_memory(settings)
    agent = NovelAgent(
        llm=LLMClient(settings=settings),
        rag=RAGStore(settings=settings),
        exemplar=exemplar,
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
    agent, wm = _build_agent(settings)
    print(f"✍️  开始创作：{task}\n")
    try:
        state, record = agent.run(task)
    except Exception as e:
        print(f"❌ 创作失败：{e}")
        return

    # 运行日志落盘
    run_file = save_run(record, settings)

    # 章节落盘 + 工作记忆更新
    chapter_file = None
    if state.final_chapter:
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
        evaluate(record["run_id"], settings)
    except Exception as e:
        print(f"(评测跳过：{e})")


def _do_index(settings: Settings, force: bool = False) -> None:
    try:
        settings.require_novel_dir()
    except RuntimeError as e:
        print(f"❌ {e}")
        return
    rag = RAGStore(settings=settings)
    if rag.count > 0 and not force:
        print(f"向量库已有 {rag.count} 块。输入 `index rebuild` 可强制重建。")
        return
    print("🔧 开始向量化建库（稍候）...")
    rag.build_index()


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
        evaluate(args[0], settings)
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
    print("  index            查看向量库；index rebuild 强制重建")
    print("  replay <run_id>  回放某次写作过程")
    print("  eval <run_id>    对某次写作打分")
    print("  compare <a> <b>  对比两次写作效果")
    print("  test <run_id>    规则断言测试")
    print("  状态             查看当前写到第几章、角色状态、未回收伏笔")
    print("  help / quit")


# ---------- 主循环 ----------
def main() -> None:
    settings = get_settings()
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
        elif cmd == "index":
            _do_index(settings, force="rebuild" in args)
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


if __name__ == "__main__":
    main()
