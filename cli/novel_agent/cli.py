"""交互式命令行入口。

T2 只放最小可用 REPL（help/quit），完整命令在 T10 补全。
"""

__all__ = ["main"]


def main() -> None:
    print("✦ Novel Agent v0.1.0 —— 《修仙不如陪她看云》创作助手")
    print("输入 help 查看命令，quit 退出。\n")

    while True:
        try:
            line = input(">>> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue

        cmd = line.lower()
        if cmd in ("quit", "exit", "q"):
            print("再见。")
            break
        if cmd in ("help", "h", "?"):
            _print_help()
            continue
        print(f"（尚未实现）收到：{line}")


def _print_help() -> None:
    print("命令：")
    print("  写第N章：标题     走完整流程写一章（查设定->草稿->润色->审稿->存文件->打分）")
    print("  index            建立设定向量库（首次必做）")
    print("  replay <run_id>  回放某次写作过程")
    print("  eval <run_id>    对某次写作打分")
    print("  compare <a> <b>  对比两次写作效果")
    print("  状态             查看当前写到第几章、角色状态、未回收伏笔")
    print("  help / quit")


if __name__ == "__main__":
    main()
