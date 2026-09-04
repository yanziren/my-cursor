"""Day 8 · Agent Loop：事件流 + 上下文 token 计量。"""

from collections.abc import AsyncIterator

from mycoder.context.budget import ContextBudget
from mycoder.events import (
    AgentEvent,
    ErrorEvent,
    TextDelta,
    ThinkingDelta,
    ToolCallEnd,
    ToolCallStart,
    TurnEnd,
    UsageUpdate,
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
        budget: ContextBudget | None = None,
    ) -> None:
        self.provider = provider
        self.registry = registry
        self.max_turns = max_turns
        self.budget = budget or ContextBudget.from_env()
        self.messages: list[dict] = [{"role": "system", "content": system_prompt}]

    @property
    def tool_schemas(self) -> list[dict]:
        return self.registry.schemas()

    def _emit_usage(self, *, estimated: bool) -> UsageUpdate:
        usage = self.budget.last_usage
        prompt = usage.prompt_tokens if usage else 0
        completion = usage.completion_tokens if usage else 0
        return UsageUpdate(
            used_tokens=self.budget.used,
            context_limit=self.budget.limit,
            prompt_tokens=prompt,
            completion_tokens=completion,
            estimated=estimated,
        )

    def _sync_budget_from_provider(self) -> UsageUpdate:
        stats = getattr(self.provider, "last_usage", None)
        if stats is not None:
            self.budget.record_api_usage(stats.prompt_tokens, stats.completion_tokens)
            return self._emit_usage(estimated=False)
        self.budget.record_estimate(self.messages)
        return self._emit_usage(estimated=True)

    async def run(self, user_input: str) -> AsyncIterator[AgentEvent]:
        """执行一轮用户任务，异步产出类型化事件。"""
        self.messages.append({"role": "user", "content": user_input})
        self.budget.record_estimate(self.messages)
        yield self._emit_usage(estimated=True)

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
            yield self._sync_budget_from_provider()

            tool_calls = complete.tool_calls
            stats = getattr(self.provider, "last_usage", None)

            if not tool_calls:
                yield TurnEnd(
                    turn=turn,
                    content=complete.content or "",
                    completion_tokens=stats.completion_tokens if stats else None,
                    prompt_tokens=stats.prompt_tokens if stats else None,
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
            yield self._emit_usage(estimated=True)

        last_stats = getattr(self.provider, "last_usage", None)
        yield TurnEnd(
            turn=self.max_turns,
            content=f"已达到最大轮数限制 (max_turns={self.max_turns})，任务未完成。",
            completion_tokens=last_stats.completion_tokens if last_stats else None,
            prompt_tokens=last_stats.prompt_tokens if last_stats else None,
        )
