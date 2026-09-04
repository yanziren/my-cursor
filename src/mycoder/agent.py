"""Day 7 · Agent Loop：事件流架构，引擎不依赖任何 UI。"""

from collections.abc import AsyncIterator

from mycoder.events import (
    AgentEvent,
    ErrorEvent,
    TextDelta,
    ThinkingDelta,
    ToolCallEnd,
    ToolCallStart,
    TurnEnd,
)
from mycoder.providers.ollama import ChatResponse, OllamaProvider
from mycoder.tool_summary import summarize_tool_result
from mycoder.tools.registry import ToolRegistry


class Agent:
    """Agent Loop：扁平 messages 史 + 事件流输出 + 自然/硬性停止。"""

    def __init__(
        self,
        provider: OllamaProvider,
        registry: ToolRegistry,
        system_prompt: str,
        max_turns: int = 20,
    ) -> None:
        self.provider = provider
        self.registry = registry
        self.max_turns = max_turns
        self.messages: list[dict] = [{"role": "system", "content": system_prompt}]

    @property
    def tool_schemas(self) -> list[dict]:
        return self.registry.schemas()

    async def run(self, user_input: str) -> AsyncIterator[AgentEvent]:
        """执行一轮用户任务，异步产出类型化事件。"""
        self.messages.append({"role": "user", "content": user_input})

        for turn in range(1, self.max_turns + 1):
            complete: ChatResponse | None = None
            try:
                for kind, payload in self.provider.stream_chat_with_tools(
                    self.messages,
                    tools=self.tool_schemas,
                ):
                    if kind == "reasoning" and isinstance(payload, str):
                        yield ThinkingDelta(payload)
                    elif kind == "content" and isinstance(payload, str):
                        yield TextDelta(payload)
                    elif kind == "complete" and isinstance(payload, ChatResponse):
                        complete = payload
            except Exception as exc:  # noqa: BLE001 — 向上游 UI 报告即可
                yield ErrorEvent(str(exc))
                return

            if complete is None:
                yield ErrorEvent("模型流式响应异常：未收到 complete 事件")
                return

            self.messages.append(complete.message)
            tool_calls = complete.tool_calls

            if not tool_calls:
                yield TurnEnd(
                    turn=turn,
                    content=complete.content or "",
                    completion_tokens=self.provider.last_completion_tokens,
                )
                return

            for call in tool_calls:
                name = call.function.name
                arguments = call.function.arguments
                yield ToolCallStart(call.id, name, arguments)
                result = await self.registry.dispatch(name, arguments)
                summary = summarize_tool_result(name, result)
                yield ToolCallEnd(call.id, name, result, summary)
                self.messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": result,
                    }
                )

        yield TurnEnd(
            turn=self.max_turns,
            content=f"已达到最大轮数限制 (max_turns={self.max_turns})，任务未完成。",
            completion_tokens=self.provider.last_completion_tokens,
        )
