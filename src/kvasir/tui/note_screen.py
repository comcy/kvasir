"""Modal input for a note (key `m`). Dismisses with the text, or None if cancelled/empty."""
from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input


class NoteScreen(ModalScreen["str | None"]):
    DEFAULT_CSS = """
    NoteScreen { align: center middle; }
    NoteScreen > Vertical { width: 70%; min-width: 30; height: auto; border: round $accent; border-title-color: $accent; border-title-style: bold; padding: 1 2; background: $surface; }
    """
    BINDINGS: ClassVar[list[Binding]] = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, branch: str, text: str = "") -> None:
        super().__init__()
        self.branch, self.text = branch, text

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Input(self.text, placeholder="note (enter to save, esc to cancel)")

    def on_mount(self) -> None:
        self.query_one(Vertical).border_title = f"Note · {self.branch}"

    def on_input_submitted(self, ev: Input.Submitted) -> None:
        self.dismiss(ev.value.strip() or None)

    def action_cancel(self) -> None:
        self.dismiss(None)
