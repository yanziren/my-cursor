"""Day 7 · CLI 入口：默认 TUI，--repl 保留 print 模式。"""

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(description="mycoder 编程智能体 harness")
    parser.add_argument(
        "--repl",
        action="store_true",
        help="使用 Day 1-6 的 print REPL（非 TUI）",
    )
    args = parser.parse_args()

    if args.repl:
        from mycoder.repl import main as repl_main

        repl_main()
    else:
        from mycoder.tui.app import main as tui_main

        tui_main()
