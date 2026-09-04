"""Day 8 · 上下文预算与 token 计量单测。"""

from mycoder.context.budget import (
    ContextBudget,
    estimate_messages_tokens,
    format_meter,
    format_token_count,
    get_context_limit,
)


def test_format_meter_basic() -> None:
    assert format_meter(13200, 32000) == "▓▓░░░ 41% (13.2K/32.0K)"


def test_format_token_count() -> None:
    assert format_token_count(500) == "500"
    assert format_token_count(13200) == "13.2K"


def test_estimate_messages_tokens() -> None:
    messages = [
        {"role": "system", "content": "x" * 300},
        {"role": "user", "content": "hello"},
    ]
    est = estimate_messages_tokens(messages)
    assert est > 100


def test_context_budget_api_usage() -> None:
    budget = ContextBudget(limit=32000)
    budget.record_api_usage(1200, 300)
    assert budget.used == 1500
    assert budget.from_api is True
    assert budget.within_tolerance(1500)


def test_context_budget_estimate_fallback() -> None:
    budget = ContextBudget(limit=8192)
    messages = [{"role": "user", "content": "测试" * 50}]
    used = budget.record_estimate(messages)
    assert used == budget.used
    assert budget.from_api is False


def test_get_context_limit_env(monkeypatch) -> None:
    monkeypatch.setenv("MYCODER_CONTEXT_LENGTH", "16384")
    assert get_context_limit() == 16384
