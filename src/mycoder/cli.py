"""Day 10 · CLI 入口：默认 TUI，--repl 保留 print 模式，resume 恢复会话。"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime

from mycoder.session.store import (
    SessionSummary,
    default_sessions_dir,
    list_sessions,
    resolve_session_path,
)


def _format_time(ts: str) -> str:
    try:
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is not None:
            dt = dt.astimezone()
        return dt.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return ts[:16]


def print_session_table(summaries: list[SessionSummary]) -> None:
    folder = default_sessions_dir()
    print(f"mycoder 会话（{folder}）\n")
    if not summaries:
        print("（空）")
        return
    print(f"{'#':>3}  {'标题':<32}  {'更新时间':<16}  {'轮数':>4}  id")
    for i, item in enumerate(summaries, 1):
        title = item.title[:32]
        print(
            f"{i:3}  {title:<32}  {_format_time(item.updated_at):<16}  "
            f"{item.turns:>4}  {item.id[:8]}"
        )


def pick_session(summaries: list[SessionSummary]) -> str | None:
    if not summaries:
        print("没有可恢复的会话，请直接运行 mycoder 开始新会话。")
        return None
    print_session_table(summaries)
    try:
        raw = input("\n选择编号或会话 id（q 退出）: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return None
    if not raw or raw.lower() in {"q", "quit", "exit"}:
        return None
    if raw.isdigit():
        index = int(raw)
        if 1 <= index <= len(summaries):
            return summaries[index - 1].id
        print(f"编号超出范围: {raw}")
        return None
    try:
        return resolve_session_path(raw).stem
    except FileNotFoundError as exc:
        print(exc)
        return None


def _launch(*, session_id: str | None, repl: bool) -> None:
    if repl:
        from mycoder.repl import main as repl_main

        repl_main(session_id=session_id)
        return
    from mycoder.tui.app import main as tui_main

    tui_main(session_id=session_id)


def main() -> None:
    parser = argparse.ArgumentParser(description="mycoder 编程智能体 harness")
    parser.add_argument(
        "--repl",
        action="store_true",
        help="使用 Day 1-6 的 print REPL（非 TUI）",
    )
    parser.add_argument(
        "-l",
        "--list",
        action="store_true",
        help="列出历史会话后退出（配合 resume）",
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=["resume"],
        help="resume：列出/恢复历史会话",
    )
    parser.add_argument("session_id", nargs="?", help="会话 id 或唯一前缀")
    args = parser.parse_args()

    session_id: str | None = None
    if args.command == "resume":
        if args.list:
            print_session_table(list_sessions())
            return
        if args.session_id:
            try:
                session_id = resolve_session_path(args.session_id).stem
            except FileNotFoundError as exc:
                print(exc, file=sys.stderr)
                raise SystemExit(1) from exc
        else:
            session_id = pick_session(list_sessions())
            if session_id is None:
                return
    elif args.list:
        print_session_table(list_sessions())
        return

    _launch(session_id=session_id, repl=args.repl)


if __name__ == "__main__":
    main()
