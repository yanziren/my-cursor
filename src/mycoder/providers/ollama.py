"""Ollama Provider：通过 OpenAI 兼容接口调用本地模型（Day 1 雏形，Day 21 抽象为多 Provider 层）。"""

import os
from collections.abc import Iterator
from dataclasses import dataclass

import httpx2
from openai import OpenAI
from openai.types.chat import ChatCompletionMessageToolCall

DEFAULT_BASE_URL = "http://localhost:11434/v1"
DEFAULT_MODEL = "qwen3.8:27b"


@dataclass
class ChatResponse:
    """非流式 chat 返回值：assistant 历史消息 + 便于 harness 消费的字段。"""

    message: dict
    content: str | None
    tool_calls: list[ChatCompletionMessageToolCall] | None
    finish_reason: str | None


class OllamaProvider:
    """封装对本地 Ollama 的流式对话调用，逐 chunk 产出文本增量。"""

    def __init__(self, model: str | None = None, temperature: float = 0.2) -> None:
        self.model = model or os.getenv("MYCODER_MODEL", DEFAULT_MODEL)
        self.temperature = temperature
        # 本机推理服务必须直连：httpx 默认信任系统代理（macOS 开代理时会把
        # localhost 请求也转给代理，返回 502），trust_env=False 关闭该行为。
        # api_key 随意填即可，Ollama 不校验，但 openai SDK 要求非空。
        self.client = OpenAI(
            base_url=DEFAULT_BASE_URL,
            api_key="ollama",
            http_client=httpx2.Client(trust_env=False),
        )
        self.last_completion_tokens: int | None = None

    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> ChatResponse:
        """非流式对话；Day 2 起用于工具调用往返（解析 tool_calls 比流式简单）。"""
        self.last_completion_tokens = None
        kwargs: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
        }
        if tools:
            kwargs["tools"] = tools

        response = self.client.chat.completions.create(**kwargs)
        if response.usage:
            self.last_completion_tokens = response.usage.completion_tokens

        choice = response.choices[0]
        msg = choice.message
        tool_calls = msg.tool_calls or None

        # 思考型模型：有 tool_calls 时 content 留空，不要把 reasoning 写进历史
        content = msg.content if not tool_calls else (msg.content or "")
        assistant_message: dict = {"role": "assistant", "content": content}
        if tool_calls:
            assistant_message["tool_calls"] = [
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
            message=assistant_message,
            content=msg.content,
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason,
        )

    def stream_chat(self, messages: list[dict]) -> Iterator[tuple[str, str]]:
        """把完整消息历史发给模型，流式产出 (类型, 文本增量) 二元组。

        类型为 "reasoning"（思考型模型的思考过程，不应写回历史）或 "content"（正式回复）。
        LLM API 是无状态的：所谓"多轮对话"，就是每轮把 messages 全量重发。
        """
        self.last_completion_tokens = None
        stream = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=self.temperature,
            stream=True,
            # 让最后一个 chunk 携带 token 用量，用于统计生成速度
            stream_options={"include_usage": True},
        )
        for chunk in stream:
            if chunk.usage:
                self.last_completion_tokens = chunk.usage.completion_tokens
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            # reasoning 是 Ollama 对思考型模型的扩展字段，openai SDK 未定义类型
            reasoning = getattr(delta, "reasoning", None)
            if reasoning:
                yield "reasoning", reasoning
            if delta.content:
                yield "content", delta.content
