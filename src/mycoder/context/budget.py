"""Day 8 · Token 计量与上下文预算：API usage 为准，本地估算兜底。"""

import json
import os
from dataclasses import dataclass


def get_context_limit() -> int:
    """上下文窗口上限；优先 MYCODER_CONTEXT_LENGTH，其次 OLLAMA_CONTEXT_LENGTH。"""
    for key in ("MYCODER_CONTEXT_LENGTH", "OLLAMA_CONTEXT_LENGTH"):
        raw = os.getenv(key)
        if raw:
            try:
                return max(512, int(raw))
            except ValueError:
                pass
    return 32768


@dataclass(frozen=True)
class TokenUsage:
    """单次 API 调用的 token 用量（与 OpenAI usage 字段对齐）。"""

    prompt_tokens: int
    completion_tokens: int

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


def estimate_text_tokens(text: str) -> int:
    """Day 8 之前粗估：字符数 / 3（发送前预检用）。"""
    return max(0, len(text) // 3)


def estimate_messages_tokens(messages: list[dict]) -> int:
    """估算 messages 列表 token 数（含 role 与 tool_calls 结构开销）。"""
    total = 0
    for msg in messages:
        total += 4  # role / 结构开销粗估
        content = msg.get("content")
        if isinstance(content, str):
            total += estimate_text_tokens(content)
        tool_calls = msg.get("tool_calls")
        if tool_calls:
            total += estimate_text_tokens(json.dumps(tool_calls, ensure_ascii=False))
    return total


def format_token_count(value: int) -> str:
    """人类可读 token 数：13200 → 13.2K。"""
    if value >= 10_000:
        return f"{value / 1000:.1f}K"
    if value >= 1000:
        return f"{value / 1000:.1f}K"
    return str(value)


def format_meter(used: int, limit: int, *, bar_width: int = 5) -> str:
    """渲染上下文仪表：▓▓▓░░ 41% (13.2K/32K)。"""
    if limit <= 0:
        return "░░░░░ 0% (0/0)"
    ratio = min(1.0, used / limit)
    percent = int(ratio * 100)
    filled = round(ratio * bar_width)
    filled = min(bar_width, max(0, filled))
    bar = "▓" * filled + "░" * (bar_width - filled)
    return f"{bar} {percent}% ({format_token_count(used)}/{format_token_count(limit)})"


@dataclass
class ContextBudget:
    """对话级上下文预算：优先 API usage，无 usage 时回退本地估算。"""

    limit: int
    used: int = 0
    last_usage: TokenUsage | None = None
    from_api: bool = False

    @classmethod
    def from_env(cls) -> "ContextBudget":
        return cls(limit=get_context_limit())

    def record_api_usage(self, prompt_tokens: int, completion_tokens: int) -> TokenUsage:
        """以 API 返回的 usage 更新当前占用（prompt + completion = 本轮后上下文体积）。"""
        usage = TokenUsage(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
        self.last_usage = usage
        self.used = usage.total_tokens
        self.from_api = True
        return usage

    def record_estimate(self, messages: list[dict]) -> int:
        """本地估算 messages 占用（发送前预检或无 usage 兜底）。"""
        self.used = estimate_messages_tokens(messages)
        self.from_api = False
        return self.used

    def meter(self) -> str:
        return format_meter(self.used, self.limit)

    def percent(self) -> float:
        if self.limit <= 0:
            return 0.0
        return min(100.0, self.used * 100.0 / self.limit)

    def within_tolerance(self, api_total: int, *, tolerance: float = 0.05) -> bool:
        """仪表与 API total 对账是否在误差范围内。"""
        if api_total <= 0:
            return True
        return abs(self.used - api_total) / api_total <= tolerance
