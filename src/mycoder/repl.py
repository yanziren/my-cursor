"""Day 1 · 流式对话 REPL：在终端与本地 Ollama 模型连续多轮对话。"""

import time

from mycoder.providers.ollama import OllamaProvider

SYSTEM_PROMPT = "你是一个简洁的中文助手。"
DIM, RESET = "\033[2m", "\033[0m"


def main() -> None:
    provider = OllamaProvider()
    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    print(f"mycoder · Day 1 流式 REPL · 模型 {provider.model} · 输入 /exit 退出")

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

        # 模型无状态：每轮把完整历史重新发送，这就是"多轮记忆"的全部真相
        messages.append({"role": "user", "content": user_input})
        reply_parts: list[str] = []
        thinking = False
        start = time.monotonic()
        print()
        for kind, delta in provider.stream_chat(messages):
            if kind == "reasoning" and not thinking:
                thinking = True
                print(DIM, end="")  # 思考过程降暗显示，与正式回复区分
            elif kind == "content" and thinking:
                thinking = False
                print(f"{RESET}\n")
            print(delta, end="", flush=True)
            if kind == "content":
                reply_parts.append(delta)
        if thinking:
            print(RESET, end="")
        elapsed = time.monotonic() - start

        # 思考过程不写回历史：它不是对话内容，还会白白吃掉上下文窗口
        reply = "".join(reply_parts)
        messages.append({"role": "assistant", "content": reply})

        # 生成速度是 Day 1 验收项：低于 15 token/s 应换低一档模型；无用量数据时按字符数/3 粗估
        tokens = provider.last_completion_tokens or len(reply) // 3
        speed = tokens / elapsed if elapsed > 0 else 0.0
        print(f"\n\n{DIM}[{tokens} token · {elapsed:.1f}s · {speed:.1f} token/s]{RESET}")
