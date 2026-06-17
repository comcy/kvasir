"""Notes panel: file list (left) + Markdown preview (right), edit via $EDITOR."""
from __future__ import annotations

import os
import subprocess
from datetime import datetime
from pathlib import Path

import frontmatter
from textual.app import ComposeResult
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Button, Input, Label, ListItem, ListView, Markdown, Static
from textual.containers import Horizontal, Vertical, VerticalScroll

from devtrack.workspace.manager import WorkspaceManager


# ─────────────────────── new-note modal ──────────────────────────────────────

class NewNoteScreen(ModalScreen[dict | None]):
    DEFAULT_CSS = """
    NewNoteScreen { align: center middle; }
    #dialog {
        width: 56; height: auto;
        background: $surface; border: round $secondary; padding: 1 2;
    }
    .field-label { color: $secondary; margin-top: 1; }
    #btn-row { margin-top: 1; align-horizontal: right; }
    Button { margin-left: 1; }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static("[bold]New Note[/bold]")
            yield Label("Title", classes="field-label")
            yield Input(placeholder="e.g. standup-2026-06-15", id="inp-title")
            yield Label("Tags  (comma-separated, optional)", classes="field-label")
            yield Input(placeholder="dev, planning", id="inp-tags")
            with Horizontal(id="btn-row"):
                yield Button("Create & Edit", variant="primary", id="btn-ok")
                yield Button("Cancel", id="btn-cancel")

    def on_mount(self) -> None:
        self.query_one("#inp-title", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-ok":
            title = self.query_one("#inp-title", Input).value.strip()
            if not title:
                self.notify("Title is required.", severity="error")
                return
            raw_tags = self.query_one("#inp-tags", Input).value
            tags = [t.strip() for t in raw_tags.split(",") if t.strip()]
            self.dismiss({"title": title, "tags": tags})
        else:
            self.dismiss(None)

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss(None)


# ─────────────────────── list item ───────────────────────────────────────────

class NoteItem(ListItem):
    def __init__(self, info: dict) -> None:
        super().__init__()
        self.info = info

    def compose(self) -> ComposeResult:
        title = self.info.get("title", "Untitled")
        date = (self.info.get("created") or "")[:10]
        tags = self.info.get("tags", [])
        tags_str = "  " + " ".join(f"[dim][{t}][/dim]" for t in tags) if tags else ""
        date_str = f"  [dim]{date}[/dim]" if date else ""
        yield Label(f"  [bold]{title}[/bold]{date_str}{tags_str}")


# ─────────────────────── main panel ──────────────────────────────────────────

class NotesPanel(Widget):
    DEFAULT_CSS = """
    NotesPanel { height: 100%; }

    #split { height: 100%; }

    #list-col {
        width: 38;
        border-right: solid $panel;
    }
    #list-header {
        background: $surface; padding: 0 1;
        color: $secondary; text-style: bold; height: 1;
    }
    #notes-lv {
        height: 1fr;
        background: transparent;
    }

    #viewer-col { width: 1fr; }
    #viewer-header {
        background: $surface; padding: 0 1;
        color: $accent; text-style: bold; height: 1;
    }
    #md-scroll { height: 1fr; padding: 0 2; }

    ListItem { background: transparent; padding: 0; }
    ListItem:hover { background: $surface; }
    ListView:focus > ListItem.--highlight { background: $surface; }

    #notes-empty { padding: 2 4; color: $foreground 45%; }
    """

    BINDINGS = [
        ("n", "new_note",    "New"),
        ("e", "edit_note",   "Edit ($EDITOR)"),
        ("x", "delete_note", "Delete"),
        ("r", "reload",      "Reload"),
    ]

    _selected_path: reactive[Path | None] = reactive(None)

    def __init__(self, wm: WorkspaceManager) -> None:
        super().__init__()
        self._wm = wm

    def _load(self) -> list[dict]:
        nd = self._wm.notes_dir()
        notes = []
        for p in sorted(nd.glob("*.md"), key=lambda f: f.stat().st_mtime, reverse=True):
            try:
                post = frontmatter.load(str(p))
                notes.append({
                    "path": p,
                    "title": post.metadata.get("title", p.stem),
                    "tags": post.metadata.get("tags", []),
                    "created": str(post.metadata.get("created", ""))[:10],
                    "content": post.content,
                })
            except Exception:
                notes.append({
                    "path": p,
                    "title": p.stem,
                    "tags": [],
                    "created": "",
                    "content": p.read_text(encoding="utf-8", errors="replace"),
                })
        return notes

    def compose(self) -> ComposeResult:
        notes = self._load()

        with Horizontal(id="split"):
            with Vertical(id="list-col"):
                yield Static(f"  Notes ({len(notes)})", id="list-header")
                if notes:
                    yield ListView(*[NoteItem(n) for n in notes], id="notes-lv")
                else:
                    yield Static(
                        "  No notes yet.\n  [dim]Press [bold]n[/bold] to create one.[/dim]",
                        id="notes-empty",
                    )

            with Vertical(id="viewer-col"):
                yield Static("  Preview", id="viewer-header")
                with VerticalScroll(id="md-scroll"):
                    yield Markdown("*Select a note from the list.*", id="md")

    # ----------------------------------------------------------------- events

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if isinstance(event.item, NoteItem):
            self._selected_path = event.item.info["path"]
            # update preview header
            title = event.item.info.get("title", "")
            try:
                self.query_one("#viewer-header", Static).update(f"  {title}")
            except Exception:
                pass
            # update markdown – AwaitComplete is fine to call without await
            content = event.item.info.get("content", "")
            self.query_one("#md", Markdown).update(content)

    # ----------------------------------------------------------------- actions

    def action_new_note(self) -> None:
        def cb(result: dict | None) -> None:
            if not result:
                return
            nd = self._wm.notes_dir()
            title = result["title"]
            slug = title.lower().replace(" ", "-").replace("/", "-")
            path = nd / f"{slug}.md"

            post = frontmatter.Post(
                "\n\n",
                title=title,
                created=datetime.now().isoformat(),
                tags=result.get("tags", []),
            )
            path.write_text(frontmatter.dumps(post), encoding="utf-8")

            editor = os.environ.get("EDITOR", "nano")
            with self.app.suspend():
                subprocess.call([editor, str(path)])

            self._selected_path = path
            self.refresh(recompose=True)
            self.notify(f"Created '{title}'", timeout=2)

        self.app.push_screen(NewNoteScreen(), cb)

    def action_edit_note(self) -> None:
        path = self._selected_path
        if not path:
            self.notify("Select a note first.", severity="warning")
            return
        editor = os.environ.get("EDITOR", "nano")
        with self.app.suspend():
            subprocess.call([editor, str(path)])
        self.refresh(recompose=True)

    def action_delete_note(self) -> None:
        path = self._selected_path
        if not path:
            self.notify("Select a note first.", severity="warning")
            return
        path.unlink(missing_ok=True)
        self._selected_path = None
        self.query_one("#md", Markdown).update("*Select a note from the list.*")
        self.refresh(recompose=True)
        self.notify("Note deleted.", timeout=1.5)

    def action_reload(self) -> None:
        self.refresh(recompose=True)
