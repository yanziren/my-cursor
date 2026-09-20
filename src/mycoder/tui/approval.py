"""Day 11 · TUI 权限审批卡片。"""

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from mycoder.permissions.pipeline import PermissionRequest, UserChoice


class ApprovalScreen(ModalScreen[UserChoice]):
    """危险工具调用拦截：允许一次 / 本会话总是允许 / 拒绝。"""

    # 默认焦点在拒绝上，避免回车误放行
    AUTO_FOCUS = "#deny"

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("a", "allow_once", "允许一次", show=True),
        Binding("s", "allow_session", "本会话总是允许", show=True),
        Binding("d", "deny", "拒绝", show=True),
        Binding("escape", "deny", "拒绝", show=False),
    ]

    DEFAULT_CSS = """
    ApprovalScreen {
        align: center middle;
    }
    #approval-dialog {
        width: 72;
        max-width: 90%;
        height: auto;
        background: $surface;
        border: tall $warning;
        padding: 1 2;
    }
    #approval-title {
        text-style: bold;
        color: $warning;
        margin-bottom: 1;
    }
    #approval-preview {
        margin: 1 0;
    }
    #approval-reason {
        color: $text-muted;
        margin-bottom: 1;
    }
    #approval-buttons {
        height: auto;
        align: center middle;
    }
    #approval-buttons Button {
        margin: 0 1;
    }
    """

    def __init__(self, request: PermissionRequest) -> None:
        super().__init__()
        self.request = request

    def compose(self) -> ComposeResult:
        preview = self.request.preview or "（无参数）"
        if len(preview) > 500:
            preview = preview[:497] + "..."
        with Vertical(id="approval-dialog"):
            yield Static("权限审批", id="approval-title")
            yield Static(f"工具  {self.request.tool_name}")
            yield Static(preview, id="approval-preview")
            yield Static(self.request.reason, id="approval-reason")
            with Horizontal(id="approval-buttons"):
                yield Button("允许一次 [a]", id="allow_once", variant="success")
                yield Button("本会话总是允许 [s]", id="allow_session", variant="warning")
                yield Button("拒绝 [d]", id="deny", variant="error")

    def action_allow_once(self) -> None:
        self.dismiss(UserChoice("allow_once"))

    def action_allow_session(self) -> None:
        self.dismiss(UserChoice("allow_session"))

    def action_deny(self) -> None:
        self.dismiss(UserChoice("deny"))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        actions: dict[str, UserChoice] = {
            "allow_once": UserChoice("allow_once"),
            "allow_session": UserChoice("allow_session"),
            "deny": UserChoice("deny"),
        }
        choice = actions.get(event.button.id or "")
        if choice is not None:
            self.dismiss(choice)
