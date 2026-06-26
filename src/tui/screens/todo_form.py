from __future__ import annotations

from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static
from textual.containers import Horizontal, Vertical


class TodoFormScreen(ModalScreen[dict | None]):
    DEFAULT_CSS = """
    TodoFormScreen {
        align: center middle;
    }
    #dialog {
        width: 62;
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
    """

    def __init__(
        self,
        todo: dict | None = None,
        tag_names: list[str] | None = None,
    ) -> None:
        super().__init__()
        self._todo = todo or {}
        self._tag_names = tag_names or []

    def compose(self) -> ComposeResult:
        verb = "Edit" if self._todo else "Add"
        with Vertical(id="dialog"):
            yield Static(f"[bold]{verb} Todo[/bold]")
            yield Label("Text", classes="field-label")
            yield Input(
                value=self._todo.get("text", ""),
                placeholder="What needs to be done?",
                id="inp-text",
            )
            yield Label("Assignee  (@name, optional — leave blank for yourself)", classes="field-label")
            yield Input(
                value=self._todo.get("assignee") or "",
                placeholder="@john",
                id="inp-assignee",
            )
            yield Label("Due date  (YYYY-MM-DD, optional)", classes="field-label")
            yield Input(
                value=self._todo.get("due_date") or "",
                placeholder="2026-06-30",
                id="inp-due",
            )
            yield Label("Tags  (comma-separated)", classes="field-label")
            yield Input(
                value=", ".join(self._tag_names),
                placeholder="dev, core, billing",
                id="inp-tags",
            )
            with Horizontal(id="btn-row"):
                yield Button("Save", variant="primary", id="btn-save")
                yield Button("Cancel", variant="default", id="btn-cancel")

    def on_mount(self) -> None:
        self.query_one("#inp-text", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-save":
            self._submit()
        else:
            self.dismiss(None)

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss(None)

    def _submit(self) -> None:
        text = self.query_one("#inp-text", Input).value.strip()
        if not text:
            self.notify("Text is required.", severity="error")
            return
        raw_assignee = self.query_one("#inp-assignee", Input).value.strip()
        assignee = raw_assignee.lstrip("@") or None
        due = self.query_one("#inp-due", Input).value.strip() or None
        raw_tags = self.query_one("#inp-tags", Input).value
        tags = [t.strip() for t in raw_tags.split(",") if t.strip()]
        self.dismiss({"text": text, "assignee": assignee, "due_date": due, "tags": tags})
