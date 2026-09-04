"""Day 7 · Agent Loop REPL：消费事件流（print 模式，--repl 备用）。"""

import asyncio
import json
import os
import time

from mycoder.agent import Agent
from mycoder.events import (
    TextDelta,
    ThinkingDelta,
    ToolCallEnd,
    ToolCallStart,
    TurnEnd,
)
from mycoder.prompts.system import build_system_prompt, estimate_tokens
from mycoder.providers.ollama import OllamaProvider
from mycoder.tool_summary import summarize_tool_start
from mycoder.tools import DEFAULT_TOOLS, ToolRegistry
from mycoder.tools.files import workspace_root

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


def main() -> None:
    provider = OllamaProvider()
    registry = ToolRegistry(DEFAULT_TOOLS)
    ws = workspace_root()
    minimal = os.getenv("MYCODER_MINIMAL_PROMPT", "").lower() in {"1", "true", "yes"}
    system_prompt = build_system_prompt(
        DEFAULT_TOOLS,
        ws,
        include_agents=not os.getenv("MYCODER_SKIP_AGENTS"),
        minimal=minimal,
    )
    max_turns = int(os.getenv("MYCODER_MAX_TURNS", "20"))
    agent = Agent(provider, registry, system_prompt, max_turns=max_turns)
    prompt_tokens = estimate_tokens(system_prompt)

    print(
        f"mycoder · REPL 模式 · 模型 {provider.model} · max_turns={max_turns}\n"
        f"工作区: {ws} · 系统提示词约 {prompt_tokens} token"
        f"{' (minimal)' if minimal else ''}\n"
        "命令: /exit · /messages · /prompt\n"
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
            print(f"\n{DIM}--- 系统提示词 (~{prompt_tokens} token) ---{RESET}")
            print(system_prompt)
            print(f"{DIM}--- 结束 ---{RESET}\n")
            continue

        asyncio.run(run_turn(agent, user_input))


if __name__ == "__main__":
    main()
