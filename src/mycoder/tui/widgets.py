"""Day 7 · Textual TUI 组件。"""

from textual.containers import VerticalScroll
from textual.widgets import Collapsible, Markdown, Static

from mycoder.events import CompactionEvent, ToolCallEnd, ToolCallStart
from mycoder.tool_summary import summarize_tool_start


class ChatPane(VerticalScroll):
    """可滚动的对话区。"""

    DEFAULT_CSS = """
    ChatPane {
        height: 1fr;
        padding: 0 1;
    }
    """


class CompactionNotice(Static):
    """压缩事件：不进入对话气泡，只提示视图已收窄。"""

    DEFAULT_CSS = """
    CompactionNotice {
        color: $text-muted;
        padding: 0 1;
        margin: 0 0 1 0;
    }
    """

    def __init__(self, event: CompactionEvent) -> None:
        super().__init__(
            f"[dim]已压缩 {event.compacted_count} 条早期消息 → "
            f"摘要 {event.summary_tokens} token[/dim]"
        )


class UserBubble(Static):
    """用户消息。"""

    DEFAULT_CSS = """
    UserBubble {
        background: $primary 15%;
        padding: 0 1;
        margin: 1 0;
        border: tall $primary 30%;
    }
    """

    def __init__(self, text: str) -> None:
        super().__init__()
        self._text = text

    def compose(self):
        yield Static(f"[bold]你[/bold]  {self._text}")


class ThinkingBubble(Static):
    """思考过程（流式，不写回历史）。"""

    DEFAULT_CSS = """
    ThinkingBubble {
        color: $text-muted;
        padding: 0 1;
        margin: 0 0 1 0;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._buffer = ""

    def append(self, text: str) -> None:
        self._buffer += text
        preview = self._buffer.replace("\n", " ")
        if len(preview) > 120:
            preview = preview[:117] + "..."
        self.update(f"[dim]思考 · {preview}[/dim]")


class AssistantBubble(Static):
    """助手消息：流式纯文本，完成后重渲 Markdown。"""

    DEFAULT_CSS = """
    AssistantBubble {
        padding: 0 1;
        margin: 0 0 1 0;
        border: tall $accent 20%;
    }
    """

    def __init__(self) -> None:
        super().__init__("[bold]助手[/bold]\n")
        self._buffer = ""
        self._header = "[bold]助手[/bold]\n"
        self._markdown: Markdown | None = None

    def append(self, text: str) -> None:
        self._buffer += text
        self.update(self._header + self._buffer)

    def finalize(self) -> None:
        if not self._buffer.strip() or self._markdown is not None:
            return
        self._markdown = Markdown(self._buffer)
        self.mount(self._markdown)
        self.update(self._header.rstrip())


class ToolBubble(Static):
    """工具调用：Collapsible 折叠，默认一行摘要。"""

    DEFAULT_CSS = """
    ToolBubble {
        margin: 0 0 1 0;
        padding: 0 1;
    }
    ToolBubble Collapsible {
        border: tall $warning 25%;
    }
    ToolBubble Static.tool-detail {
        max-height: 20;
        overflow-y: auto;
        padding: 0 1;
    }
    """

    def __init__(self, start: ToolCallStart) -> None:
        super().__init__()
        self._title = summarize_tool_start(start.name, start.arguments)
        self._finished = False

    def compose(self):
        yield Collapsible(
            Static("执行中…", classes="tool-detail"),
            title=self._title,
            collapsed=True,
        )

    def finish(self, end: ToolCallEnd) -> None:
        if self._finished:
            return
        self._finished = True
        collapsible = self.query_one(Collapsible)
        detail = self.query_one(".tool-detail", Static)
        collapsible.title = f"{self._title}  {end.summary}"
        preview = end.result
        if len(preview) > 4000:
            preview = preview[:4000] + "\n…（已截断）"
        detail.update(preview)
