"""Day 11 · Textual 终端界面：对话流 + 会话恢复 + 权限审批。"""

from typing import ClassVar

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header, Input, Static

from mycoder.context.budget import format_meter
from mycoder.events import (
    CompactionEvent,
    ErrorEvent,
    TextDelta,
    ThinkingDelta,
    ToolCallEnd,
    ToolCallStart,
    TurnEnd,
    UsageUpdate,
)
from mycoder.permissions.pipeline import PermissionRequest, UserChoice
from mycoder.session.bootstrap import AgentBundle, create_agent
from mycoder.session.store import CompactionEntry, MessageEntry, SessionStore
from mycoder.tui.approval import ApprovalScreen
from mycoder.tui.widgets import (
    AssistantBubble,
    ChatPane,
    CompactionNotice,
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

    def __init__(self, bundle: AgentBundle | None = None) -> None:
        super().__init__()
        bundle = bundle or create_agent()
        self.agent = bundle.agent
        self.provider = bundle.provider
        self.workspace = bundle.workspace
        self.prompt_tokens = bundle.prompt_tokens
        self.store = bundle.store
        self._assistant: AssistantBubble | None = None
        self._thinking: ThinkingBubble | None = None
        self._open_tools: dict[str, ToolBubble] = {}
        self._restored = any(
            msg.get("role") == "user" for msg in self.agent.messages
        )
        self.agent.approver = self._approve

    def compose(self) -> ComposeResult:
        yield Header()
        yield ChatPane(id="chat")
        yield Static("", id="context-bar")
        yield Static("", id="status-bar")
        yield Input(placeholder="输入任务，Enter 发送 · Ctrl+L 清屏 · Ctrl+C 退出", id="prompt")
        yield Footer()

    def on_mount(self) -> None:
        self._update_context_meter(self.agent.budget.used, estimated=True)
        if self._restored:
            self._hydrate_from_session()
            turns = sum(1 for msg in self.agent.messages if msg.get("role") == "user")
            self._update_status(f"已恢复 · {turns} 轮")
        else:
            self._update_status("就绪")
        self.query_one(Input).focus()

    def _update_context_meter(self, used: int, *, estimated: bool) -> None:
        meter = format_meter(used, self.agent.budget.limit)
        suffix = " ~" if estimated else ""
        self.query_one("#context-bar", Static).update(f"上下文 {meter}{suffix}")

    async def _approve(self, request: PermissionRequest) -> UserChoice:
        """Agent 在 dispatch 前 await 这里；ModalScreen 让出事件环，按钮仍可点。"""
        self._update_status("等待审批…")
        tool = self._open_tools.get(request.call_id)
        if tool is not None:
            tool.mark_waiting()
        return await self.push_screen_wait(ApprovalScreen(request))

    def _update_status(self, hint: str) -> None:
        bar = self.query_one("#status-bar", Static)
        bar.update(
            f"{hint} · {self.store.short_id} · {self.store.title} · "
            f"模型 {self.provider.model} · 工作区 {self.workspace.name} "
            f"· 系统提示 ~{self.prompt_tokens} token"
        )

    def _hydrate_from_session(self) -> None:
        """把磁盘事件流画回聊天区，便于 resume 后接着看。"""
        chat = self.query_one("#chat", ChatPane)
        chat.mount(
            Static(
                f"[dim]已恢复会话 {self.store.short_id} · {self.store.title}[/dim]"
            )
        )
        snapshot = self.store.replay()
        for entry in snapshot.entries:
            if isinstance(entry, CompactionEntry):
                chat.mount(
                    CompactionNotice(
                        CompactionEvent(
                            compacted_count=entry.compacted_count,
                            summary_tokens=entry.summary_tokens,
                        )
                    )
                )
                continue
            if not isinstance(entry, MessageEntry):
                continue
            msg = entry.message
            role = msg.get("role")
            if role == "user":
                chat.mount(UserBubble(str(msg.get("content") or "")))
            elif role == "assistant":
                content = msg.get("content") or ""
                if isinstance(content, str) and content.strip():
                    bubble = AssistantBubble()
                    chat.mount(bubble)
                    bubble.append(content)
                for call in msg.get("tool_calls") or []:
                    if not isinstance(call, dict):
                        continue
                    fn = call.get("function") or {}
                    name = str(fn.get("name") or "tool")
                    chat.mount(Static(f"[dim]工具 {name}[/dim]"))
            elif role == "tool":
                preview = str(msg.get("content") or "").replace("\n", " ")
                if len(preview) > 120:
                    preview = preview[:117] + "..."
                chat.mount(Static(f"[dim]  → {preview}[/dim]"))
        chat.scroll_end(animate=False)

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
            elif isinstance(event, CompactionEvent):
                chat.mount(CompactionNotice(event))
                self._update_status(
                    f"已压缩 {event.compacted_count} 条早期消息 → 摘要 {event.summary_tokens} token"
                )
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
        self.store = SessionStore.create()
        self.agent.store = self.store
        self.agent.reset_conversation()
        self.store.ensure_workspace(str(self.workspace))
        self._update_context_meter(self.agent.budget.used, estimated=True)
        self._update_status("已清屏")


def main(session_id: str | None = None) -> None:
    bundle = create_agent(session_id=session_id)
    MycoderApp(bundle).run()


if __name__ == "__main__":
    main()
