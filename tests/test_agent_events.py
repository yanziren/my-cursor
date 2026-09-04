"""Day 7 · Agent 事件流单测（无需 Ollama / TUI）。"""

from dataclasses import dataclass

import pytest

from mycoder.agent import Agent
from mycoder.events import (
    TextDelta,
    ToolCallEnd,
    ToolCallStart,
    TurnEnd,
)
from mycoder.providers.ollama import ChatResponse
from mycoder.tools import DEFAULT_TOOLS
from mycoder.tools.registry import ToolRegistry


@dataclass
class FakeFunction:
    name: str
    arguments: str


@dataclass
class FakeToolCall:
    id: str
    function: FakeFunction


class FakeProvider:
    """模拟 stream_chat_with_tools，供 harness 单测。"""

    last_completion_tokens: int | None = 10
    last_usage = None

    def __init__(self, responses: list[ChatResponse]) -> None:
        self._responses = list(responses)

    def stream_chat_with_tools(self, messages: list[dict], tools: list[dict] | None = None):
        resp = self._responses.pop(0)
        if resp.content:
            for piece in resp.content.split():
                yield "content", piece + " "
        yield "complete", resp


def _assistant(content: str | None = None, *, tool_calls: list[FakeToolCall] | None = None) -> ChatResponse:
    message: dict = {"role": "assistant", "content": content or ""}
    if tool_calls:
        message["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.function.name,
                    "arguments": call.function.arguments,
                },
            }
            for call in tool_calls
        ]
    return ChatResponse(
        message=message,
        content=content,
        tool_calls=tool_calls,  # type: ignore[arg-type]
        finish_reason="stop" if not tool_calls else "tool_calls",
    )


@pytest.mark.asyncio
async def test_agent_yields_text_and_turn_end() -> None:
    provider = FakeProvider([_assistant("你好，世界")])
    agent = Agent(provider, ToolRegistry(DEFAULT_TOOLS), "test system")
    events = [event async for event in agent.run("hi")]

    assert any(isinstance(e, TextDelta) for e in events)
    assert isinstance(events[-1], TurnEnd)
    assert events[-1].content == "你好，世界"
    assert agent.messages[-1]["role"] == "assistant"


@pytest.mark.asyncio
async def test_agent_tool_roundtrip() -> None:
    provider = FakeProvider(
        [
            _assistant(
                tool_calls=[
                    FakeToolCall(
                        id="call_1",
                        function=FakeFunction(
                            name="calculator",
                            arguments='{"expression": "1+1"}',
                        ),
                    )
                ]
            ),
            _assistant("结果是 2"),
        ]
    )
    agent = Agent(provider, ToolRegistry(DEFAULT_TOOLS), "test system")
    events = [event async for event in agent.run("算 1+1")]

    assert any(isinstance(e, ToolCallStart) for e in events)
    assert any(isinstance(e, ToolCallEnd) for e in events)
    assert isinstance(events[-1], TurnEnd)
    assert "2" in events[-1].content
    assert agent.messages[-1]["role"] == "assistant"


def test_agent_module_has_no_print() -> None:
    import ast
    from pathlib import Path

    source = Path("src/mycoder/agent.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    prints = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(getattr(node.func, "id", None), str)
        and node.func.id == "print"
    ]
    assert prints == []
