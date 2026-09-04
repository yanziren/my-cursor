"""Day 7 · Textual 终端界面：对话流 + 流式渲染 + 工具折叠。"""

import os
from typing import ClassVar

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header, Input, Static

from mycoder.agent import Agent
from mycoder.context.budget import format_meter
from mycoder.events import (
    ErrorEvent,
    TextDelta,
    ThinkingDelta,
    ToolCallEnd,
    ToolCallStart,
    TurnEnd,
    UsageUpdate,
)
from mycoder.prompts.system import build_system_prompt, estimate_tokens
from mycoder.providers.ollama import OllamaProvider
from mycoder.tools import DEFAULT_TOOLS, ToolRegistry
from mycoder.tools.files import workspace_root
from mycoder.tui.widgets import (
    AssistantBubble,
    ChatPane,
    ThinkingBubble,
    ToolBubble,
    UserBubble,
)


class MycoderApp(App):
    """mycoder Textual TUI。"""

    TITLE = "mycoder"
    CSS = """
    Screen {
        layout: vertical;
    }
    #status-bar {
        dock: bottom;
        height: 1;
        background: $panel;
        color: $text-muted;
        padding: 0 1;
    }
    #context-bar {
        dock: bottom;
        height: 1;
        background: $surface;
        color: $foreground;
        padding: 0 1;
    }
    Input {
        dock: bottom;
        margin: 0 1 1 1;
    }
    """

    BINDINGS: ClassVar[tuple[Binding, ...]] = (
        Binding("ctrl+c", "quit", "退出", show=True),
        Binding("ctrl+l", "clear_chat", "清屏", show=True),
    )

    def __init__(self) -> None:
        super().__init__()
        provider = OllamaProvider()
        registry = ToolRegistry(DEFAULT_TOOLS)
        ws = workspace_root()
        minimal = os.getenv("MYCODER_MINIMAL_PROMPT", "").lower() in {"1", "true", "yes"}
        system_prompt = build_system_prompt(
            DEFAULT_TOOLS,
            ws,
            include_agents=not os.getenv("MYCODER_SKIP_AGENTS"),
            minimal=minimal,
        )
        max_turns = int(os.getenv("MYCODER_MAX_TURNS", "20"))
        self.agent = Agent(provider, registry, system_prompt, max_turns=max_turns)
        self.provider = provider
        self.workspace = ws
        self.prompt_tokens = estimate_tokens(system_prompt)
        self._assistant: AssistantBubble | None = None
        self._thinking: ThinkingBubble | None = None
        self._open_tools: dict[str, ToolBubble] = {}

    def compose(self) -> ComposeResult:
        yield Header()
        yield ChatPane(id="chat")
        yield Static("", id="context-bar")
        yield Static("", id="status-bar")
        yield Input(placeholder="输入任务，Enter 发送 · Ctrl+L 清屏 · Ctrl+C 退出", id="prompt")
        yield Footer()

    def on_mount(self) -> None:
        self._update_context_meter(self.agent.budget.used, estimated=True)
        self._update_status("就绪")
        self.query_one(Input).focus()

    def _update_context_meter(self, used: int, *, estimated: bool) -> None:
        meter = format_meter(used, self.agent.budget.limit)
        suffix = " ~" if estimated else ""
        self.query_one("#context-bar", Static).update(f"上下文 {meter}{suffix}")

    def _update_status(self, hint: str) -> None:
        bar = self.query_one("#status-bar", Static)
        bar.update(
            f"{hint} · 模型 {self.provider.model} · 工作区 {self.workspace.name} "
            f"· 系统提示 ~{self.prompt_tokens} token"
        )

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return
        event.input.value = ""
        self.run_turn(text)

    @work(exclusive=True)
    async def run_turn(self, user_text: str) -> None:
        prompt = self.query_one(Input)
        prompt.disabled = True
        self._update_status("运行中…")
        self._assistant = None
        self._thinking = None
        self._open_tools = {}

        chat = self.query_one("#chat", ChatPane)
        chat.mount(UserBubble(user_text))

        async for event in self.agent.run(user_text):
            if isinstance(event, ThinkingDelta):
                if self._thinking is None:
                    self._thinking = ThinkingBubble()
                    chat.mount(self._thinking)
                self._thinking.append(event.text)
            elif isinstance(event, TextDelta):
                if self._assistant is None:
                    self._assistant = AssistantBubble()
                    chat.mount(self._assistant)
                self._assistant.append(event.text)
            elif isinstance(event, ToolCallStart):
                tool = ToolBubble(event)
                self._open_tools[event.call_id] = tool
                chat.mount(tool)
            elif isinstance(event, ToolCallEnd):
                tool = self._open_tools.get(event.call_id)
                if tool is not None:
                    tool.finish(event)
            elif isinstance(event, UsageUpdate):
                self._update_context_meter(event.used_tokens, estimated=event.estimated)
            elif isinstance(event, TurnEnd):
                if self._assistant is not None:
                    self._assistant.finalize()
                tokens = event.completion_tokens or len(event.content) // 3
                self._update_status(f"完成 · {event.turn} 轮 · ~{tokens} token")
                chat.scroll_end(animate=False)
            elif isinstance(event, ErrorEvent):
                chat.mount(Static(f"[red]错误: {event.message}[/red]"))
                self._update_status("出错")

        prompt.disabled = False
        prompt.focus()

    def action_clear_chat(self) -> None:
        chat = self.query_one("#chat", ChatPane)
        chat.remove_children()
        self.agent.messages = [self.agent.messages[0]]
        self.agent.budget.used = self.agent.budget.record_estimate(self.agent.messages)
        self._update_context_meter(self.agent.budget.used, estimated=True)
        self._update_status("已清屏")


def main() -> None:
    MycoderApp().run()


if __name__ == "__main__":
    main()
