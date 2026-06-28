"""QuickCaptureBar — dashboard widget for fast journal/todo capture."""
from __future__ import annotations

import re
import uuid
from datetime import date, datetime

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Input, Static

from src.workspace.manager import WorkspaceManager

_TODO_RE = re.compile(r'^-\s*\[[ xX]\]', re.IGNORECASE)


class QuickCaptureBar(Widget):

    class Captured(Message):
        """Posted after a capture was successfully written to the journal."""

    DEFAULT_CSS = """
    QuickCaptureBar {
        height: auto;
        background: $surface;
        border-bottom: solid $panel;
        padding: 0 1 1 1;
    }
    #qc-row {
        height: 3;
        align: left middle;
    }
    #qc-label {
        width: auto;
        color: $primary;
        text-style: bold;
        content-align: left middle;
        padding: 0 1 0 0;
    }
    #qc-input {
        width: 1fr;
    }
    #qc-hint {
        color: $foreground 30%;
        height: 1;
        padding: 0 0 0 1;
    }
    """

    def __init__(self, wm: WorkspaceManager) -> None:
        super().__init__()
        self._wm = wm

    def compose(self) -> ComposeResult:
        today = date.today().isoformat()
        with Horizontal(id="qc-row"):
            yield Static(f"⚡ {today}", id="qc-label")
            yield Input(
                placeholder="Quick capture — free text or  - [ ] todo …",
                id="qc-input",
            )
        yield Static(
            "  [dim]Enter: append to today's journal  ·  - [ ] …: also saves as todo[/dim]",
            id="qc-hint",
        )

    def focus_input(self) -> None:
        try:
            self.query_one("#qc-input", Input).focus()
        except Exception:
            pass

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return

        try:
            nd = self._wm.notes_dir()
        except Exception:
            self.notify("No active workspace.", severity="error")
            return

        from src.data.journal import append_to_journal

        try:
            append_to_journal(nd, text)
        except Exception as exc:
            self.notify(f"Could not write to journal: {exc}", severity="error", timeout=4)
            return

        is_todo = bool(_TODO_RE.match(text))
        if is_todo:
            self._save_todo(text)
            self.notify(f"Todo saved → journal {date.today().isoformat()}", timeout=2)
        else:
            self.notify(f"Captured → journal {date.today().isoformat()}", timeout=2)

        self.query_one("#qc-input", Input).clear()
        self.post_message(QuickCaptureBar.Captured())

    def _save_todo(self, text: str) -> None:
        from src.data.note_todos import parse_note_todos, save_todo_tags

        parsed = parse_note_todos(text, "quick-capture")
        if not parsed:
            return
        try:
            store = self._wm.store()
            now = datetime.now().isoformat()
            existing_hashes = {
                t["source_hash"] for t in store.all("todos") if t.get("source_hash")
            }
            for todo in parsed:
                if todo["source_hash"] in existing_hashes:
                    continue
                rec = store.insert("todos", {
                    "id": str(uuid.uuid4()),
                    "text": todo["text"],
                    "status": todo["status"],
                    "due_date": todo["due_date"],
                    "assignee": todo["assignee"],
                    "note_ref": todo["note_ref"],
                    "source_hash": todo["source_hash"],
                    "created": now,
                    "updated": now,
                })
                if todo.get("tags"):
                    save_todo_tags(store, rec["id"], todo["tags"])
        except Exception as exc:
            self.notify(
                f"Note saved, but todo DB error: {exc}", severity="warning", timeout=4
            )
