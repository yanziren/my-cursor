"""Day 9 · 上下文压缩与工具输出裁剪（无需 Ollama）。"""

from dataclasses import dataclass

import pytest

from mycoder.agent import Agent
from mycoder.context.budget import ContextBudget, estimate_messages_tokens
from mycoder.context.compaction import (
    CompactConfig,
    assemble_view,
    compact,
    compact_watermark,
    fallback_summary,
    model_view,
    prepare_context,
    prune_tool_results,
    should_compact,
    tool_placeholder,
)
from mycoder.events import CompactionEvent, TurnEnd
from mycoder.providers.ollama import ChatResponse
from mycoder.tools import DEFAULT_TOOLS
from mycoder.tools.registry import ToolRegistry


def _fake_summary(_transcript: str) -> str:
    return (
        "1) 任务目标\n逐个重构函数\n"
        "2) 关键决策\n先读文件再修改\n"
        "3) 读过的文件\nsrc/f0.py、src/f1.py\n"
        "4) 改过的文件\nsrc/f0.py\n"
        "5) 跑过的命令与结果\n（无）\n"
        "6) 未完成事项\n继续后续函数\n"
        "7) 风险与注意点\n压缩有损，旧内容请重新读取"
    )


def _read_turn(index: int, blob: str) -> list[dict]:
    path = f"src/f{index}.py"
    return [
        {"role": "user", "content": f"请处理文件 {path}"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": f"call_{index}",
                    "type": "function",
                    "function": {
                        "name": "read_file",
                        "arguments": f'{{"path": "{path}"}}',
                    },
                }
            ],
        },
        {"role": "tool", "tool_call_id": f"call_{index}", "content": blob},
        {"role": "assistant", "content": f"已看过 {path}"},
    ]


def _history(turns: int, blob: str) -> list[dict]:
    messages: list[dict] = [{"role": "system", "content": "sys"}]
    for i in range(turns):
        messages.extend(_read_turn(i, blob))
    return messages


def test_compact_watermark_matches_handbook() -> None:
    config = CompactConfig(threshold=0.80, reserve=8192)
    # 32K 窗口、8K 预留、80%：int((32768-8192)*0.8) == 19660
    assert compact_watermark(32768, config) == 19660
    assert should_compact(19661, 32768, config)
    assert not should_compact(19660, 32768, config)


def test_small_window_reserve_is_capped() -> None:
    config = CompactConfig(threshold=0.80, reserve=8192)
    # 2000 窗口不能按 8K 预留，否则阈值线为负
    assert compact_watermark(2000, config) == int((2000 - 500) * 0.80)


def test_prune_replaces_old_tool_output_with_recoverable_placeholder() -> None:
    blob = "def foo():\n    return 1\n" * 50
    messages = _history(4, blob)
    view, pruned = prune_tool_results(messages, prune_after_turns=1)
    assert pruned >= 1
    first_tool = next(m for m in view if m.get("role") == "tool")
    assert first_tool["content"] == tool_placeholder(
        "read_file",
        '{"path": "src/f0.py"}',
    )
    assert "src/f0.py" in first_tool["content"]
    assert "重新读取" in first_tool["content"]
    # 最近一轮工具输出仍保留原文
    last_tool = [m for m in view if m.get("role") == "tool"][-1]
    assert last_tool["content"] == blob
    # 原位只发生在视图副本上，完整历史不销毁
    original_tool = next(m for m in messages if m.get("role") == "tool")
    assert original_tool["content"] == blob


def test_compact_keeps_recent_turns_and_drops_early_user_text() -> None:
    blob = "x" * 1200
    messages = _history(6, blob)
    config = CompactConfig(keep_recent_turns=2, prune_after_turns=0)
    record = compact(messages, [], config, _fake_summary)
    assert record is not None
    view = assemble_view(messages, [record])
    assert any(
        isinstance(m.get("content"), str) and m["content"].startswith("<compaction>")
        for m in view
    )
    assert not any(m.get("content") == "请处理文件 src/f0.py" for m in view)
    assert any(m.get("content") == "请处理文件 src/f0.py" for m in messages)
    assert any(m.get("content") == "请处理文件 src/f4.py" for m in view)
    assert any(m.get("content") == "请处理文件 src/f5.py" for m in view)


def test_compact_reduces_tokens_by_at_least_60_percent() -> None:
    blob = "TOKEN_PAYLOAD " * 400  # 约 1800 token / 轮
    messages = _history(8, blob)
    before = estimate_messages_tokens(messages)
    config = CompactConfig(keep_recent_turns=2, prune_after_turns=0)
    record = compact(messages, [], config, _fake_summary)
    assert record is not None
    view = assemble_view(messages, [record])
    after = estimate_messages_tokens(view)
    assert before > 0
    assert after <= before * 0.4


def test_twenty_five_turns_stay_under_window() -> None:
    blob = "PAYLOAD " * 300
    messages: list[dict] = [{"role": "system", "content": "sys"}]
    records = []
    config = CompactConfig(
        threshold=0.50,
        reserve=512,
        keep_recent_turns=2,
        prune_after_turns=0,
    )
    limit = 8000
    compacted = False
    for i in range(25):
        messages.extend(_read_turn(i, blob))
        result = prepare_context(
            messages,
            records,
            limit=limit,
            config=config,
            summarizer=_fake_summary,
        )
        records = result.records
        if result.compacted is not None:
            compacted = True
        view, _pruned = model_view(messages, records, config)
        assert estimate_messages_tokens(view) < limit
    assert compacted


def test_fallback_summary_keeps_paths_and_headings() -> None:
    transcript = '[user]\n修 bug\n\ntool_calls: [{"function":{"arguments":"{\\"path\\": \\"src/app.py\\"}"}}]'
    text = fallback_summary(transcript)
    for heading in ("1) 任务目标", "3) 读过的文件", "6) 未完成事项", "7) 风险与注意点"):
        assert heading in text
    assert "src/app.py" in text


@dataclass
class _RecordingProvider:
    last_completion_tokens: int | None = 10
    last_usage = None

    def __init__(self, responses: list[ChatResponse]) -> None:
        self._responses = list(responses)
        self.seen: list[list[dict]] = []

    def stream_chat_with_tools(self, messages: list[dict], tools: list[dict] | None = None):
        self.seen.append(messages)
        resp = self._responses.pop(0)
        if resp.content:
            yield "content", resp.content
        yield "complete", resp


def _assistant(content: str) -> ChatResponse:
    return ChatResponse(
        message={"role": "assistant", "content": content},
        content=content,
        tool_calls=None,
        finish_reason="stop",
    )


@pytest.mark.asyncio
async def test_agent_emits_compaction_and_sends_view_not_full_history() -> None:
    blob = "LINE\n" * 400
    history = _history(6, blob)
    provider = _RecordingProvider([_assistant("最早是处理 src/f0.py")])
    agent = Agent(
        provider,  # type: ignore[arg-type]
        ToolRegistry(DEFAULT_TOOLS),
        "sys",
        budget=ContextBudget(limit=3000),
        compact_config=CompactConfig(
            threshold=0.50,
            reserve=256,
            keep_recent_turns=2,
            prune_after_turns=0,
        ),
        summarizer=_fake_summary,
    )
    agent.messages = history
    events = [event async for event in agent.run("最开始我让你做什么？")]

    compact_events = [e for e in events if isinstance(e, CompactionEvent)]
    assert compact_events
    assert compact_events[0].compacted_count > 0
    assert compact_events[0].summary_tokens > 0
    assert isinstance(events[-1], TurnEnd)

    assert any(m.get("content") == "请处理文件 src/f0.py" for m in agent.messages)
    sent = provider.seen[0]
    assert any(
        isinstance(m.get("content"), str) and m["content"].startswith("<compaction>")
        for m in sent
    )
    assert not any(m.get("content") == "请处理文件 src/f0.py" for m in sent)


def test_reset_conversation_clears_compaction_records() -> None:
    provider = _RecordingProvider([])
    agent = Agent(
        provider,  # type: ignore[arg-type]
        ToolRegistry(DEFAULT_TOOLS),
        "sys",
        summarizer=_fake_summary,
    )
    agent.messages.append({"role": "user", "content": "hi"})
    agent.compaction_records = []
    agent.reset_conversation()
    assert agent.messages == [{"role": "system", "content": "sys"}]
    assert agent.compaction_records == []
