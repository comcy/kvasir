"""Reusable Yes/No confirmation modal."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static


class ConfirmScreen(ModalScreen[bool]):
    DEFAULT_CSS = """
    ConfirmScreen {
        align: center middle;
    }
    #dialog {
        width: 60;
        height: auto;
        background: $surface;
        border: round $warning;
        padding: 1 2;
    }
    #message {
        margin-bottom: 1;
    }
    #btn-row {
        align-horizontal: right;
    }
    Button { margin-left: 1; }
    """

    def __init__(self, message: str, confirm_label: str = "Yes") -> None:
        super().__init__()
        self._message = message
        self._confirm_label = confirm_label

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(self._message, id="message")
            with Horizontal(id="btn-row"):
                yield Button(self._confirm_label, variant="error", id="btn-yes")
                yield Button("Cancel", variant="default", id="btn-no")

    def on_mount(self) -> None:
        self.query_one("#btn-no", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "btn-yes")

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss(False)
