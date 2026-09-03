"""Day 2 · 工具调用 REPL：模型请求工具 → 本地执行 → 结果回传 → 模型总结。"""

import asyncio
import json
import time

from mycoder.providers.ollama import OllamaProvider
from mycoder.tools import DEFAULT_TOOLS, ToolRegistry

SYSTEM_PROMPT = (
    "你是一个简洁的中文助手，可以调用工具获取真实时间或做数学计算。"
    "需要真实时间或精确计算时用工具；问候和闲聊直接回答，不要滥用工具。"
)
DIM, RESET = "\033[2m", "\033[0m"


def print_messages(messages: list[dict]) -> None:
    """打印完整消息序列，便于对照 assistant(tool_calls) 与 tool 消息结构。"""
    print(f"\n{DIM}--- 消息序列 ---{RESET}")
    print(json.dumps(messages, ensure_ascii=False, indent=2))
    print(f"{DIM}--- 结束 ---{RESET}\n")


async def run_turn(
    provider: OllamaProvider,
    registry: ToolRegistry,
    messages: list[dict],
    user_input: str,
) -> None:
    messages.append({"role": "user", "content": user_input})
    tool_schemas = registry.schemas()
    start = time.monotonic()

    # 第一次调用：模型决定是否请求工具
    response = provider.chat(messages, tools=tool_schemas)
    messages.append(response.message)

    if response.tool_calls:
        print(f"{DIM}[模型请求 {len(response.tool_calls)} 个工具调用]{RESET}")
        for call in response.tool_calls:
            name = call.function.name
            args = call.function.arguments
            print(f"{DIM}  → {name}({args}){RESET}")
            result = await registry.dispatch(name, args)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": result,
                }
            )

        print_messages(messages)

        # 第二次调用：模型根据工具结果生成最终回答
        final = provider.chat(messages, tools=tool_schemas)
        messages.append(final.message)
        reply = final.content or ""
    else:
        reply = response.content or ""

    print(reply)
    elapsed = time.monotonic() - start
    tokens = provider.last_completion_tokens or len(reply) // 3
    speed = tokens / elapsed if elapsed > 0 else 0.0
    print(f"\n{DIM}[{tokens} token · {elapsed:.1f}s · {speed:.1f} token/s]{RESET}")
    print_messages(messages)


def main() -> None:
    provider = OllamaProvider()
    registry = ToolRegistry(DEFAULT_TOOLS)
    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    print(
        f"mycoder · Day 2 工具调用 REPL · 模型 {provider.model} · "
        "输入 /exit 退出 · /messages 查看历史"
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
            print_messages(messages)
            continue

        asyncio.run(run_turn(provider, registry, messages, user_input))


if __name__ == "__main__":
    main()
