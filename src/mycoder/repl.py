"""Day 10 · Agent Loop REPL：消费事件流（print 模式，--repl 备用）。"""

import asyncio
import json
import time

from mycoder.agent import Agent
from mycoder.context.budget import format_meter
from mycoder.events import (
    CompactionEvent,
    TextDelta,
    ThinkingDelta,
    ToolCallEnd,
    ToolCallStart,
    TurnEnd,
    UsageUpdate,
)
from mycoder.session.bootstrap import create_agent
from mycoder.session.store import SessionStore
from mycoder.tool_summary import summarize_tool_start

DIM, RESET = "\033[2m", "\033[0m"


def print_messages(messages: list[dict]) -> None:
    """打印完整消息序列，便于对照多轮 tool_calls 与 tool 消息。"""
    print(f"\n{DIM}--- 消息序列 ---{RESET}")
    print(json.dumps(messages, ensure_ascii=False, indent=2))
    print(f"{DIM}--- 结束 ---{RESET}\n")


async def run_turn(agent: Agent, user_input: str) -> None:
    start = time.monotonic()
    reply_parts: list[str] = []
    turns = 0
    tokens: int | None = None

    async for event in agent.run(user_input):
        if isinstance(event, ThinkingDelta):
            print(f"{DIM}{event.text}{RESET}", end="", flush=True)
        elif isinstance(event, TextDelta):
            print(event.text, end="", flush=True)
            reply_parts.append(event.text)
        elif isinstance(event, ToolCallStart):
            print(f"\n{DIM}{summarize_tool_start(event.name, event.arguments)}{RESET}")
        elif isinstance(event, ToolCallEnd):
            print(f"{DIM}  {event.summary}{RESET}")
        elif isinstance(event, CompactionEvent):
            print(
                f"{DIM}已压缩 {event.compacted_count} 条早期消息 → "
                f"摘要 {event.summary_tokens} token{RESET}"
            )
        elif isinstance(event, UsageUpdate):
            mark = "~" if event.estimated else ""
            print(f"{DIM}[上下文 {format_meter(event.used_tokens, event.context_limit)}{mark}]{RESET}")
        elif isinstance(event, TurnEnd):
            turns = event.turn
            tokens = event.completion_tokens
            if event.content and not reply_parts:
                print(event.content)
            print()

    elapsed = time.monotonic() - start
    token_count = tokens or sum(len(p) for p in reply_parts) // 3
    speed = token_count / elapsed if elapsed > 0 else 0.0
    print(
        f"\n{DIM}[{turns} 轮 · {token_count} token · {elapsed:.1f}s · {speed:.1f} token/s]"
        f"{RESET}"
    )
    print_messages(agent.messages)


def main(session_id: str | None = None) -> None:
    bundle = create_agent(session_id=session_id)
    agent = bundle.agent
    store = bundle.store
    restored = any(msg.get("role") == "user" for msg in agent.messages)
    user_turns = sum(1 for msg in agent.messages if msg.get("role") == "user")
    resume_line = (
        f"已恢复 · {user_turns} 轮 · {store.title}\n"
        if restored
        else "新会话\n"
    )

    print(
        f"mycoder · REPL 模式 · 模型 {bundle.provider.model} · "
        f"max_turns={agent.max_turns}\n"
        f"工作区: {bundle.workspace} · 系统提示词约 {bundle.prompt_tokens} token\n"
        f"会话: {store.session_id} · {store.path}\n"
        f"{resume_line}"
        "命令: /exit · /messages · /prompt · /session\n"
        "提示: 默认请用 TUI（uv run mycoder），本模式供调试"
    )

    while True:
        try:
            user_input = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not user_input:
            continue
        if user_input in {"/exit", "/quit"}:
            return
        if user_input == "/messages":
            print_messages(agent.messages)
            continue
        if user_input == "/prompt":
            system = agent.messages[0].get("content") if agent.messages else ""
            print(f"\n{DIM}--- 系统提示词 (~{bundle.prompt_tokens} token) ---{RESET}")
            print(system)
            print(f"{DIM}--- 结束 ---{RESET}\n")
            continue
        if user_input == "/session":
            print(
                f"\n{DIM}id={store.session_id}\n"
                f"title={store.title}\n"
                f"path={store.path}{RESET}\n"
            )
            continue
        if user_input == "/clear":
            store = SessionStore.create()
            agent.store = store
            agent.reset_conversation()
            store.ensure_workspace(str(bundle.workspace))
            print(f"{DIM}已开新会话 {store.session_id}{RESET}")
            continue

        asyncio.run(run_turn(agent, user_input))


if __name__ == "__main__":
    main()
