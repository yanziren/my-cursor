"""Day 8 · Ollama 上下文窗口实测脚本（8K / 16K / 32K）。"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

from mycoder.providers.ollama import OllamaProvider

# 固定短 prompt，便于对比不同 num_ctx 下的速度
PROMPT = "用一句话解释什么是 KV cache。"


def ollama_ps() -> str:
    try:
        result = subprocess.run(
            ["ollama", "ps"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        return result.stdout.strip() or result.stderr.strip() or "（无运行中模型）"
    except OSError as exc:
        return f"ollama ps 失败: {exc}"


def run_once(context_length: int) -> dict:
    provider = OllamaProvider()
    messages = [{"role": "user", "content": PROMPT}]
    start = time.monotonic()
    reply_parts: list[str] = []
    for kind, payload in provider.stream_chat_with_tools(messages, num_ctx=context_length):
        if kind == "content" and isinstance(payload, str):
            reply_parts.append(payload)
    elapsed = time.monotonic() - start
    usage = provider.last_usage
    completion = usage.completion_tokens if usage else len("".join(reply_parts)) // 3
    speed = completion / elapsed if elapsed > 0 else 0.0
    return {
        "context_length": context_length,
        "elapsed_s": round(elapsed, 2),
        "prompt_tokens": usage.prompt_tokens if usage else None,
        "completion_tokens": usage.completion_tokens if usage else None,
        "token_per_s": round(speed, 1),
        "ollama_ps": ollama_ps(),
    }


def main() -> None:
    sizes = [8192, 16384, 32768]
    if len(sys.argv) > 1:
        sizes = [int(x) for x in sys.argv[1:]]
    results = [run_once(n) for n in sizes]
    out = Path("docs/ollama_context_benchmark.json")
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False, indent=2))
    print(f"\n已写入 {out}")


if __name__ == "__main__":
    main()
