"""Day 6 · Agent Loop REPL：结构化系统提示词 + AGENTS.md。"""

import asyncio
import json
import os
import time

from mycoder.agent import Agent
from mycoder.prompts.system import build_system_prompt, estimate_tokens
from mycoder.providers.ollama import OllamaProvider
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
    reply, turns = await agent.run(user_input)
    elapsed = time.monotonic() - start

    print(reply)
    tokens = agent.provider.last_completion_tokens or len(reply) // 3
    speed = tokens / elapsed if elapsed > 0 else 0.0
    print(
        f"\n{DIM}[{turns} 轮 · {tokens} token · {elapsed:.1f}s · {speed:.1f} token/s]"
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
    agent = Agent(provider, registry, system_prompt, max_turns=max_turns, verbose=True)
    prompt_tokens = estimate_tokens(system_prompt)

    print(
        f"mycoder · Day 6 系统提示词 REPL · 模型 {provider.model} · max_turns={max_turns}\n"
        f"工作区: {ws} · 系统提示词约 {prompt_tokens} token"
        f"{' (minimal)' if minimal else ''}\n"
        "命令: /exit · /messages · /prompt\n"
        "环境: MYCODER_MAX_TURNS · MYCODER_MINIMAL_PROMPT=1（对比实验）"
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
