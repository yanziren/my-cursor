"""Day 10 · Agent Loop：事件流 + 压缩视图 + JSONL 会话落盘。"""

import os
from collections.abc import AsyncIterator, Callable

from mycoder.context.budget import ContextBudget
from mycoder.context.compaction import (
    SUMMARY_SYSTEM_PROMPT,
    CompactConfig,
    CompactionRecord,
    model_view,
    prepare_context,
)
from mycoder.events import (
    AgentEvent,
    CompactionEvent,
    ErrorEvent,
    TextDelta,
    ThinkingDelta,
    ToolCallEnd,
    ToolCallStart,
    TurnEnd,
    UsageUpdate,
)
from mycoder.providers.ollama import ChatResponse, OllamaProvider
from mycoder.session.store import (
    TITLE_SYSTEM_PROMPT,
    SessionStore,
    clean_generated_title,
    fallback_title,
    repair_incomplete_tool_calls,
)
from mycoder.tool_summary import summarize_tool_result
from mycoder.tools.registry import ToolRegistry

DEFAULT_COMPACT_MODEL = "qwen3:4b"


class Agent:
    """Agent Loop：扁平 messages 史 + 事件流输出 + 自然/硬性停止。"""

    def __init__(
        self,
        provider: OllamaProvider,
        registry: ToolRegistry,
        system_prompt: str,
        max_turns: int = 20,
        budget: ContextBudget | None = None,
        compact_config: CompactConfig | None = None,
        summarizer: Callable[[str], str] | None = None,
        store: SessionStore | None = None,
        title_generator: Callable[[str], str] | None = None,
        auto_title: bool = False,
    ) -> None:
        self.provider = provider
        self.registry = registry
        self.max_turns = max_turns
        self.budget = budget or ContextBudget.from_env()
        self.compact_config = compact_config or CompactConfig.from_env()
        self._summarizer = summarizer
        self._title_generator = title_generator
        self.auto_title = auto_title
        self._title_attempted = False
        self._compact_provider: OllamaProvider | None = None
        self.store = store
        self.compaction_records: list[CompactionRecord] = []
        self.messages: list[dict] = [{"role": "system", "content": system_prompt}]
        if store is not None:
            self._restore_or_seed(system_prompt)

    @property
    def tool_schemas(self) -> list[dict]:
        return self.registry.schemas()

    def reset_conversation(self) -> None:
        """清屏/新会话：保留系统提示，丢掉压缩记录。

        调用方若要另起一份磁盘日志，必须先把 `self.store` 换成空的新 SessionStore。
        """
        system = self.messages[0]
        self.messages = [system]
        self.compaction_records = []
        self._title_attempted = False
        self.budget.record_estimate(self.messages)
        if self.store is not None and not self.store.read_entries():
            self.store.append_model_change(self.provider.model)
            self.store.append_message(system)

    def _restore_or_seed(self, system_prompt: str) -> None:
        """有历史则重放（含压缩指针）；空文件则写入系统提示与当前模型。"""
        assert self.store is not None
        snapshot = self.store.replay()
        if snapshot.messages:
            self.messages = snapshot.messages
            self.compaction_records = snapshot.records
            repaired = repair_incomplete_tool_calls(self.messages)
            if len(repaired) > len(self.messages):
                for extra in repaired[len(self.messages) :]:
                    self.store.append_message(extra)
                self.messages = repaired
            if snapshot.model != self.provider.model:
                self.store.append_model_change(self.provider.model)
        else:
            self.messages = [{"role": "system", "content": system_prompt}]
            self.compaction_records = []
            self.store.append_model_change(self.provider.model)
            self.store.append_message(self.messages[0])
        self.budget.record_estimate(self._view())

    def _persist_message(self, message: dict) -> None:
        self.messages.append(message)
        if self.store is not None:
            self.store.append_message(message)

    def _view(self) -> list[dict]:
        view, _pruned = model_view(self.messages, self.compaction_records, self.compact_config)
        return view

    def _summarize(self, transcript: str) -> str:
        if self._summarizer is not None:
            return self._summarizer(transcript)
        # 独立 Provider，避免摘要调用覆盖主模型 last_usage
        if self._compact_provider is None:
            model = os.getenv("MYCODER_COMPACT_MODEL", DEFAULT_COMPACT_MODEL)
            self._compact_provider = OllamaProvider(model=model)
        response = self._compact_provider.chat(
            [
                {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
                {"role": "user", "content": transcript},
            ]
        )
        return (response.content or "").strip()

    def _generate_title(self, user_text: str) -> str:
        if self._title_generator is not None:
            return self._title_generator(user_text)
        if self._compact_provider is None:
            model = os.getenv("MYCODER_COMPACT_MODEL", DEFAULT_COMPACT_MODEL)
            self._compact_provider = OllamaProvider(model=model)
        response = self._compact_provider.chat(
            [
                {"role": "system", "content": TITLE_SYSTEM_PROMPT},
                {"role": "user", "content": user_text[:500]},
            ]
        )
        return (response.content or "").strip()

    def _maybe_generate_title(self) -> None:
        """首轮结束后用小模型写标题；不阻塞主循环的首 token（等本轮收尾再调）。"""
        if self.store is None or self.store.titled_by_model or self._title_attempted:
            return
        if not self.auto_title and self._title_generator is None:
            return
        self._title_attempted = True
        first = next(
            (
                msg.get("content")
                for msg in self.messages
                if msg.get("role") == "user" and isinstance(msg.get("content"), str)
            ),
            None,
        )
        if not isinstance(first, str) or not first.strip():
            return
        try:
            raw = self._generate_title(first)
        except Exception:  # noqa: BLE001 — 标题失败不影响任务
            return
        self.store.set_title(clean_generated_title(raw, fallback_title(first)), by_model=True)

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
        self.budget.record_estimate(self._view())
        return self._emit_usage(estimated=True)

    def _prepare_user_turn(self) -> CompactionEvent | None:
        result = prepare_context(
            self.messages,
            self.compaction_records,
            limit=self.budget.limit,
            config=self.compact_config,
            summarizer=self._summarize,
        )
        self.compaction_records = result.records
        if result.compacted is None:
            return None
        if self.store is not None:
            self.store.append_compaction(result.compacted)
        return CompactionEvent(
            compacted_count=result.compacted.compacted_count,
            summary_tokens=result.compacted.summary_tokens,
            pruned_tools=result.pruned_tools,
        )

    async def run(self, user_input: str) -> AsyncIterator[AgentEvent]:
        """执行一轮用户任务，异步产出类型化事件。"""
        self._persist_message({"role": "user", "content": user_input})
        if self.store is not None and self.store.is_default_title():
            self.store.set_title(fallback_title(user_input))
        try:
            # 检查点在用户轮开始前：先裁剪再按需压缩，不走进 tool loop
            compaction = self._prepare_user_turn()
            if compaction is not None:
                yield compaction
            self.budget.record_estimate(self._view())
            yield self._emit_usage(estimated=True)

            for turn in range(1, self.max_turns + 1):
                complete: ChatResponse | None = None
                try:
                    for kind, payload in self.provider.stream_chat_with_tools(
                        self._view(),
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

                self._persist_message(complete.message)
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
                    yield ToolCallEnd(
                        call.id, name, result, summarize_tool_result(name, result)
                    )
                    self._persist_message(
                        {
                            "role": "tool",
                            "tool_call_id": call.id,
                            "content": result,
                        }
                    )
                self.budget.record_estimate(self._view())
                yield self._emit_usage(estimated=True)

            last_stats = getattr(self.provider, "last_usage", None)
            yield TurnEnd(
                turn=self.max_turns,
                content=f"已达到最大轮数限制 (max_turns={self.max_turns})，任务未完成。",
                completion_tokens=last_stats.completion_tokens if last_stats else None,
                prompt_tokens=last_stats.prompt_tokens if last_stats else None,
            )
        finally:
            self._maybe_generate_title()
