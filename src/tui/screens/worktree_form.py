"""Worktree form: create a new worktree folder inside a project.

git worktree add is a local, fast operation — stays synchronous, unlike the
project clone/fetch which run in a background worker.
"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static

from src.data.projects import add_worktree


class WorktreeFormScreen(ModalScreen[dict | None]):
    DEFAULT_CSS = """
    WorktreeFormScreen {
        align: center middle;
    }
    #dialog {
        width: 66;
        height: auto;
        background: $surface;
        border: round $primary;
        padding: 1 2;
    }
    .field-label {
        color: $primary;
        margin-top: 1;
    }
    #btn-row {
        margin-top: 1;
        align-horizontal: right;
    }
    Button { margin-left: 1; }
    #error { color: $error; margin-top: 1; }
    """

    def __init__(self, project: dict) -> None:
        super().__init__()
        self._project = project
        self._error = ""

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(f"[bold]New Worktree[/bold]  [dim]in {self._project.get('name', '?')}[/dim]")
            yield Label("Branch  (created if it doesn't exist)", classes="field-label")
            yield Input(placeholder="feat/login", id="inp-branch")
            yield Label("From ref  (optional — new-branch start point)", classes="field-label")
            yield Input(placeholder="origin/main", id="inp-from")
            if self._error:
                yield Static(self._error, id="error")
            with Horizontal(id="btn-row"):
                yield Button("Create", variant="primary", id="btn-submit")
                yield Button("Cancel", id="btn-cancel")

    def on_mount(self) -> None:
        self.query_one("#inp-branch", Input).focus()

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        if bid == "btn-submit":
            self._submit()
        elif bid == "btn-cancel":
            self.dismiss(None)

    def _submit(self) -> None:
        branch = self.query_one("#inp-branch", Input).value.strip()
        if not branch:
            self._error = "Branch is required."
            self.refresh(recompose=True)
            return
        from_ref = self.query_one("#inp-from", Input).value.strip() or None

        try:
            dest = add_worktree(self._project["path"], branch, from_ref)
        except Exception as e:
            self._error = str(e)
            self.refresh(recompose=True)
            self.call_after_refresh(lambda: self.query_one("#inp-branch", Input).focus())
            return

        self.dismiss({"branch": branch, "path": str(dest)})
