"""Day 10 · JSONL 会话持久化与断点恢复（无需 Ollama）。"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from mycoder.agent import Agent
from mycoder.context.budget import ContextBudget
from mycoder.context.compaction import CompactConfig, CompactionRecord, assemble_view
from mycoder.providers.ollama import ChatResponse
from mycoder.session.store import (
    SessionStore,
    fallback_title,
    list_sessions,
    repair_incomplete_tool_calls,
)
from mycoder.tools import DEFAULT_TOOLS
from mycoder.tools.registry import ToolRegistry

REPO_ROOT = Path(__file__).resolve().parents[1]


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

    model = "fake-model"
    last_completion_tokens: int | None = 10
    last_usage = None

    def __init__(self, responses: list[ChatResponse] | None = None) -> None:
        self._responses = list(responses or [])
        self.seen: list[list[dict]] = []

    def stream_chat_with_tools(self, messages: list[dict], tools: list[dict] | None = None):
        self.seen.append(messages)
        resp = self._responses.pop(0)
        if resp.content:
            yield "content", resp.content
        yield "complete", resp


def _assistant(
    content: str | None = None, *, tool_calls: list[FakeToolCall] | None = None
) -> ChatResponse:
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


def _fake_summary(_transcript: str) -> str:
    return (
        "1) 任务目标\n逐个处理文件\n"
        "2) 关键决策\n先读后改\n"
        "3) 读过的文件\nsrc/f0.py\n"
        "4) 改过的文件\n（无）\n"
        "5) 跑过的命令与结果\n（无）\n"
        "6) 未完成事项\n继续后续文件\n"
        "7) 风险与注意点\n压缩有损"
    )


def test_append_and_replay_roundtrip(tmp_path: Path) -> None:
    store = SessionStore.create(tmp_path)
    store.append_model_change("qwen3:8b")
    store.append_message({"role": "system", "content": "sys"})
    store.append_message({"role": "user", "content": "你好"})
    store.append_message({"role": "assistant", "content": "你好呀"})

    snapshot = SessionStore.open(store.session_id, tmp_path).replay()
    assert snapshot.model == "qwen3:8b"
    assert [m["role"] for m in snapshot.messages] == ["system", "user", "assistant"]
    assert snapshot.messages[1]["content"] == "你好"
    ids = [e.id for e in snapshot.entries]
    parents = [e.parent_id for e in snapshot.entries]
    assert parents[0] is None
    assert parents[1:] == ids[:-1]


def test_truncated_last_line_is_dropped_and_next_append_ok(tmp_path: Path) -> None:
    store = SessionStore.create(tmp_path)
    store.append_message({"role": "user", "content": "keep-me"})
    store.path.write_bytes(store.path.read_bytes() + b'{"type":"message","id":"partial"')

    snapshot = SessionStore.open(store.session_id, tmp_path).replay()
    assert snapshot.messages[-1]["content"] == "keep-me"

    restored = SessionStore.open(store.session_id, tmp_path)
    restored.append_message({"role": "assistant", "content": "after-crash"})
    again = restored.replay()
    assert again.messages[-1]["content"] == "after-crash"
    for line in restored.path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            json.loads(line)


def test_compaction_replay_rebuilds_view_without_old_originals(tmp_path: Path) -> None:
    store = SessionStore.create(tmp_path)
    store.append_model_change("fake-model")
    store.append_message({"role": "system", "content": "sys"})
    for i in range(6):
        store.append_message({"role": "user", "content": f"请处理文件 src/f{i}.py"})
        store.append_message({"role": "assistant", "content": f"已看过 src/f{i}.py"})
    # [sys, u0,a0, u1,a1, u2,a2, u3,a3, u4,a4, u5,a5]；保留最近 2 轮 → keep_from=9
    store.append_compaction(
        CompactionRecord(
            summary=_fake_summary(""),
            compacted_count=8,
            keep_from=9,
            summary_tokens=80,
        )
    )

    agent = Agent(
        FakeProvider(),  # type: ignore[arg-type]
        ToolRegistry(DEFAULT_TOOLS),
        "ignored-on-resume",
        store=SessionStore.open(store.session_id, tmp_path),
        summarizer=_fake_summary,
    )
    assert any(m.get("content") == "请处理文件 src/f0.py" for m in agent.messages)
    view = assemble_view(agent.messages, agent.compaction_records)
    assert any(
        isinstance(m.get("content"), str) and m["content"].startswith("<compaction>")
        for m in view
    )
    assert not any(m.get("content") == "请处理文件 src/f0.py" for m in view)
    assert any(m.get("content") == "请处理文件 src/f4.py" for m in view)


def test_session_file_is_grepable_for_tool_call(tmp_path: Path) -> None:
    store = SessionStore.create(tmp_path)
    store.append_message(
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": '{"path": "a.py"}'},
                }
            ],
        }
    )
    text = store.path.read_text(encoding="utf-8")
    assert "tool_call" in text
    grep = subprocess.run(
        ["grep", "tool_call", str(store.path)],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "read_file" in grep.stdout


@pytest.mark.asyncio
async def test_agent_persists_and_restores_after_simulated_crash(tmp_path: Path) -> None:
    store = SessionStore.create(tmp_path)
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
    agent = Agent(
        provider,  # type: ignore[arg-type]
        ToolRegistry(DEFAULT_TOOLS),
        "sys",
        store=store,
        title_generator=lambda _t: "计算器",
    )
    events = [event async for event in agent.run("算 1+1")]
    assert events
    assert store.title == "计算器"

    crashed = SessionStore.open(store.session_id, tmp_path)
    resumed = Agent(
        FakeProvider([_assistant("继续完成")]),  # type: ignore[arg-type]
        ToolRegistry(DEFAULT_TOOLS),
        "this-system-prompt-must-not-replace-history",
        store=crashed,
    )
    assert resumed.messages[0]["content"] == "sys"
    assert any(m.get("role") == "tool" for m in resumed.messages)
    assert resumed.messages[-1]["content"] == "结果是 2"

    [event async for event in resumed.run("再确认一下")]
    assert resumed.messages[-1]["content"] == "继续完成"


def test_dangling_tool_calls_are_repaired_on_resume(tmp_path: Path) -> None:
    store = SessionStore.create(tmp_path)
    store.append_model_change("fake-model")
    store.append_message({"role": "system", "content": "sys"})
    store.append_message({"role": "user", "content": "读文件"})
    store.append_message(
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_x",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": '{"path": "a.py"}'},
                }
            ],
        }
    )
    repaired = repair_incomplete_tool_calls(store.replay().messages)
    assert repaired[-1]["role"] == "tool"
    assert repaired[-1]["tool_call_id"] == "call_x"

    agent = Agent(
        FakeProvider(),  # type: ignore[arg-type]
        ToolRegistry(DEFAULT_TOOLS),
        "sys",
        store=SessionStore.open(store.session_id, tmp_path),
    )
    assert agent.messages[-1]["role"] == "tool"
    assert "会话中断" in agent.messages[-1]["content"]


def test_list_sessions_shows_title_time_turns(tmp_path: Path) -> None:
    store = SessionStore.create(tmp_path)
    store.append_message({"role": "user", "content": "修复计算器测试失败"})
    store.set_title("修复计算器测试")
    empty = SessionStore.create(tmp_path)
    empty.append_message({"role": "system", "content": "sys"})

    listed = list_sessions(tmp_path)
    assert [item.id for item in listed] == [store.session_id]
    assert listed[0].title == "修复计算器测试"
    assert listed[0].turns == 1

    all_rows = list_sessions(tmp_path, include_empty=True)
    assert len(all_rows) == 2


def test_fallback_title_truncates() -> None:
    assert fallback_title("  hello   world  ") == "hello world"
    long = "字" * 40
    assert fallback_title(long).endswith("…")
    assert len(fallback_title(long)) == 31


def test_replay_script_prints_message_sequence(tmp_path: Path) -> None:
    store = SessionStore.create(tmp_path)
    store.append_message({"role": "user", "content": "hello-session"})
    store.append_compaction(
        CompactionRecord(
            summary="摘要",
            compacted_count=2,
            keep_from=3,
            summary_tokens=4,
        )
    )
    store.append_message({"role": "assistant", "content": "ok"})
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "replay_session.py"), str(store.path)],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "[user] hello-session" in result.stdout
    assert "[compaction]" in result.stdout
    assert "[assistant] ok" in result.stdout


@pytest.mark.asyncio
async def test_resumed_agent_sends_compacted_view_not_full_history(tmp_path: Path) -> None:
    store = SessionStore.create(tmp_path)
    store.append_model_change("fake-model")
    store.append_message({"role": "system", "content": "sys"})
    for i in range(6):
        store.append_message({"role": "user", "content": f"请处理文件 src/f{i}.py"})
        store.append_message({"role": "assistant", "content": f"已看过 src/f{i}.py"})
    store.append_compaction(
        CompactionRecord(
            summary=_fake_summary(""),
            compacted_count=8,
            keep_from=9,
            summary_tokens=80,
        )
    )
    provider = FakeProvider([_assistant("最早是处理 src/f0.py")])
    agent = Agent(
        provider,  # type: ignore[arg-type]
        ToolRegistry(DEFAULT_TOOLS),
        "sys",
        store=SessionStore.open(store.session_id, tmp_path),
        budget=ContextBudget(limit=50_000),
        compact_config=CompactConfig(enabled=False, keep_recent_turns=2, prune_after_turns=0),
        summarizer=_fake_summary,
    )
    [event async for event in agent.run("最开始我让你做什么？")]
    sent = provider.seen[0]
    assert any(
        isinstance(m.get("content"), str) and m["content"].startswith("<compaction>")
        for m in sent
    )
    assert not any(m.get("content") == "请处理文件 src/f0.py" for m in sent)
