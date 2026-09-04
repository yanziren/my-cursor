"""Day 7 · Agent 事件流：引擎与 UI 解耦的类型化事件。"""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class TextDelta:
    """助手正文增量（流式输出）。"""

    text: str


@dataclass(frozen=True)
class ThinkingDelta:
    """思考型模型的 reasoning 增量（不写回消息历史）。"""

    text: str


@dataclass(frozen=True)
class ToolCallStart:
    """模型发起工具调用。"""

    call_id: str
    name: str
    arguments: str


@dataclass(frozen=True)
class ToolCallEnd:
    """工具执行完成。"""

    call_id: str
    name: str
    result: str
    summary: str


@dataclass(frozen=True)
class TurnEnd:
    """一轮用户任务结束（自然停止或触达上限）。"""

    turn: int
    content: str
    completion_tokens: int | None = None
    prompt_tokens: int | None = None


@dataclass(frozen=True)
class UsageUpdate:
    """上下文 token 用量更新（每轮模型调用后发出）。"""

    used_tokens: int
    context_limit: int
    prompt_tokens: int
    completion_tokens: int
    estimated: bool = False


@dataclass(frozen=True)
class ErrorEvent:
    """不可恢复错误。"""

    message: str


AgentEvent = (
    TextDelta
    | ThinkingDelta
    | ToolCallStart
    | ToolCallEnd
    | TurnEnd
    | UsageUpdate
    | ErrorEvent
)

EventKind = Literal[
    "text_delta",
    "thinking_delta",
    "tool_call_start",
    "tool_call_end",
    "turn_end",
    "usage_update",
    "error",
]
