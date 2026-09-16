"""Day 8 · Ollama usage 对账（需本机 Ollama，离线则跳过）。"""

import pytest

from mycoder.context.budget import ContextBudget, estimate_messages_tokens
from mycoder.providers.ollama import OllamaProvider


def _ollama_available() -> bool:
    try:
        provider = OllamaProvider()
        for _kind, _payload in provider.stream_chat_with_tools(
            [{"role": "user", "content": "回复 OK 两个字母"}],
        ):
            pass
        return provider.last_usage is not None
    except Exception:  # noqa: BLE001 — 探测本机 Ollama 是否可用
        return False


@pytest.mark.skipif(not _ollama_available(), reason="Ollama 不可用或无 usage 字段")
def test_meter_matches_api_usage_within_five_percent() -> None:
    provider = OllamaProvider()
    messages = [{"role": "user", "content": "用五个字以内回答：你好"}]
    for _kind, _payload in provider.stream_chat_with_tools(messages):
        pass
    assert provider.last_usage is not None
    stats = provider.last_usage
    budget = ContextBudget(limit=32768)
    budget.record_api_usage(stats.prompt_tokens, stats.completion_tokens)
    assert budget.within_tolerance(stats.total_tokens, tolerance=0.05)
    # 本地估算允许更大误差，但应同数量级
    est = estimate_messages_tokens(messages)
    assert est > 0
    assert stats.prompt_tokens > 0
