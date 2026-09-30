"""组装默认 Agent：系统提示词 + 工具 + 会话存储 + 权限管道 + 沙箱执行器。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from mycoder.agent import Agent
from mycoder.permissions.pipeline import PermissionPipeline
from mycoder.prompts.system import build_system_prompt, estimate_tokens
from mycoder.providers.ollama import OllamaProvider
from mycoder.sandbox.docker_exec import Executor, SandboxMode, load_sandbox_mode, make_executor
from mycoder.session.store import SessionStore
from mycoder.tools import ToolRegistry, build_default_tools
from mycoder.tools.files import workspace_root


@dataclass
class AgentBundle:
    """TUI / REPL 共用的运行时打包。"""

    agent: Agent
    provider: OllamaProvider
    workspace: Path
    prompt_tokens: int
    store: SessionStore
    executor: Executor
    sandbox_mode: SandboxMode


def create_agent(*, session_id: str | None = None) -> AgentBundle:
    store = SessionStore.open(session_id) if session_id else SessionStore.create()
    provider = OllamaProvider()
    ws = workspace_root()
    sandbox_mode = load_sandbox_mode(ws)
    executor = make_executor(sandbox_mode, ws)
    tools = build_default_tools(executor)
    registry = ToolRegistry(tools)
    minimal = os.getenv("MYCODER_MINIMAL_PROMPT", "").lower() in {"1", "true", "yes"}
    system_prompt = build_system_prompt(
        tools,
        ws,
        include_agents=not os.getenv("MYCODER_SKIP_AGENTS"),
        minimal=minimal,
        sandbox_mode=sandbox_mode,
    )
    max_turns = int(os.getenv("MYCODER_MAX_TURNS", "20"))
    agent = Agent(
        provider,
        registry,
        system_prompt,
        max_turns=max_turns,
        store=store,
        auto_title=True,
        permissions=PermissionPipeline.from_workspace(ws),
    )
    sys_content = agent.messages[0].get("content") if agent.messages else system_prompt
    prompt_tokens = estimate_tokens(
        sys_content if isinstance(sys_content, str) else system_prompt
    )
    store.ensure_workspace(str(ws))
    return AgentBundle(
        agent,
        provider,
        ws,
        prompt_tokens,
        store,
        executor,
        sandbox_mode,
    )
