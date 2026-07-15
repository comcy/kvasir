"""Read-only modal for showing preformatted git output (status, log, ...)."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static


class GitOutputScreen(ModalScreen[None]):
    DEFAULT_CSS = """
    GitOutputScreen {
        align: center middle;
    }
    #dialog {
        width: 90%;
        max-width: 120;
        height: 80%;
        background: $surface;
        border: round $secondary;
        padding: 1 2;
    }
    #title {
        color: $secondary;
        text-style: bold;
        margin-bottom: 1;
    }
    #output-scroll {
        height: 1fr;
        border: solid $panel;
        padding: 0 1;
    }
    #btn-row {
        margin-top: 1;
        align-horizontal: right;
    }
    """

    def __init__(self, title: str, text: str) -> None:
        super().__init__()
        self._title = title
        self._text = text or "(no output)"

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(f"[bold]{self._title}[/bold]", id="title")
            with VerticalScroll(id="output-scroll"):
                yield Static(self._text, markup=False)
            with Vertical(id="btn-row"):
                yield Button("Close", variant="primary", id="btn-close")

    def on_mount(self) -> None:
        self.query_one("#btn-close", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(None)

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss(None)
