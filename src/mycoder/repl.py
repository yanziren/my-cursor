"""Day 5 · Agent Loop REPL：bash 自我验证 + glob/grep 搜索。"""

import asyncio
import json
import os
import time

from mycoder.agent import Agent
from mycoder.providers.ollama import OllamaProvider
from mycoder.tools import DEFAULT_TOOLS, ToolRegistry

SYSTEM_PROMPT = (
    "你是一个简洁的中文编程助手，可以 read/write/edit 文件，用 bash 跑测试与命令，"
    "用 glob/grep 搜索代码。"
    "修改代码后必须用 bash 运行测试或相关命令验证；大仓库先用 grep/glob 定位再 read_file。"
    "改文件前必须先 read_file；局部修改用 edit_file，新建用 write_file。"
    "问候和闲聊直接回答，不要滥用工具。"
)
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
    max_turns = int(os.getenv("MYCODER_MAX_TURNS", "20"))
    agent = Agent(provider, registry, SYSTEM_PROMPT, max_turns=max_turns, verbose=True)
    ws = os.getenv("MYCODER_WORKSPACE", os.getcwd())
    print(
        f"mycoder · Day 5 bash/搜索 REPL · 模型 {provider.model} · max_turns={max_turns}\n"
        f"工作区: {ws}\n"
        "工具：read/write/edit/bash/glob/grep · /exit · /messages · MYCODER_MAX_TURNS"
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

        asyncio.run(run_turn(agent, user_input))


if __name__ == "__main__":
    main()
