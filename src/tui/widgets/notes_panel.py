"""Notes panel: Journal calendar view + Notes list view, edit via $EDITOR."""
from __future__ import annotations

import os
import re
import subprocess
from datetime import date, datetime
from pathlib import Path

import frontmatter
from textual.app import ComposeResult
from textual.message import Message
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Input, Label, ListItem, ListView, Markdown, Static
from textual.containers import Horizontal, Vertical, VerticalScroll

from src.workspace.manager import WorkspaceManager
from src.data.query import render_query_blocks
from src.data.journal import (
    journal_dates, note_type, slug_for, ensure_note,
)
from src.tui.widgets.journal_calendar import JournalCalendar

_WIKILINK_RE = re.compile(r'\[\[([^\]]+)\]\]')
_IMG_RE = re.compile(r'!\[([^\]]*)\]\(([^)]+)\)')


# ─────────────────────── shared pill ─────────────────────────────────────────

class FilterPill(Static):
    """Compact single-row clickable filter toggle."""

    class Pressed(Message):
        def __init__(self, pill: "FilterPill") -> None:
            super().__init__()
            self.pill = pill

    def __init__(self, label: str, pill_id: str = "", classes: str = "") -> None:
        super().__init__(label, id=pill_id, classes=classes)

    def on_click(self) -> None:
        self.post_message(FilterPill.Pressed(self))


# ─────────────────────── modals ──────────────────────────────────────────────

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
        from textual.widgets import Button
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

    def on_button_pressed(self, event) -> None:
        from textual.widgets import Button
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


class _WikiItem(ListItem):
    def __init__(self, label: str, slug: str) -> None:
        super().__init__()
        self.slug = slug
        self._label = label

    def compose(self) -> ComposeResult:
        yield Label(self._label)


class WikilinkScreen(ModalScreen[str | None]):
    DEFAULT_CSS = """
    WikilinkScreen { align: center middle; }
    #wl-dialog {
        width: 60; height: auto; max-height: 28;
        background: $surface; border: round $secondary; padding: 1 2;
    }
    #wl-title { color: $secondary; text-style: bold; margin-bottom: 1; }
    #wl-list { height: auto; max-height: 14; }
    ListItem { background: transparent; }
    ListItem:hover { background: $surface; }
    ListView:focus > ListItem.--highlight { background: $surface; }
    #wl-hint { color: $foreground 40%; margin-top: 1; }
    """

    BINDINGS = [("escape", "dismiss(None)", "Cancel")]

    def __init__(self, notes: list[dict]) -> None:
        super().__init__()
        self._notes = notes

    def compose(self) -> ComposeResult:
        with Vertical(id="wl-dialog"):
            yield Static("  Insert wikilink", id="wl-title")
            yield Input(placeholder="Search notes…", id="wl-input")
            yield ListView(id="wl-list")
            yield Static(
                "  [dim]↑↓ navigate  ·  Enter: copy link  ·  Escape: cancel[/dim]",
                id="wl-hint",
            )

    def on_mount(self) -> None:
        self.query_one("#wl-input", Input).focus()
        self._update_list("")

    def _update_list(self, query: str) -> None:
        lv = self.query_one("#wl-list", ListView)
        lv.clear()
        q = query.lower().strip()
        matches = [
            n for n in self._notes
            if not q or q in n["title"].lower() or q in n["path"].stem.lower()
        ]
        for note in matches[:15]:
            slug = note["path"].stem
            lv.append(_WikiItem(f"  [[{slug}]]  [dim]{note['title']}[/dim]", slug))
        if not matches and q:
            lv.append(_WikiItem(
                f"  [[{q}]]  [italic dim]· create new note[/italic dim]",
                f"__new__{q}",
            ))

    def on_input_changed(self, event: Input.Changed) -> None:
        self._update_list(event.value)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if isinstance(event.item, _WikiItem):
            self.dismiss(event.item.slug)


# ─────────────────────── list item ───────────────────────────────────────────

class NoteItem(ListItem):
    def __init__(self, info: dict) -> None:
        super().__init__()
        self.info = info

    def compose(self) -> ComposeResult:
        title  = self.info.get("title", "Untitled")
        tags   = self.info.get("tags", [])
        ntype  = self.info.get("ntype", "note")
        edited = (self.info.get("editedAt") or "")[:16].replace("T", " ")
        created = (self.info.get("created") or "")[:10]

        # Type prefix for journal notes
        type_prefix = {
            "day":   "[dim]日[/dim] ",
            "week":  "[dim]W [/dim] ",
            "month": "[dim]月[/dim] ",
            "year":  "[dim]年[/dim] ",
        }.get(ntype, "")

        tags_str = "  " + " ".join(f"[dim][{t}][/dim]" for t in tags) if tags else ""
        meta_parts = []
        if edited:  meta_parts.append(f"✎ {edited}")
        if created: meta_parts.append(f"+ {created}")
        meta_str = "  [dim]" + "  ·  ".join(meta_parts) + "[/dim]" if meta_parts else ""
        yield Label(f"  {type_prefix}[bold]{title}[/bold]{meta_str}{tags_str}")


# ─────────────────────── main panel ──────────────────────────────────────────

class NotesPanel(Widget):
    DEFAULT_CSS = """
    NotesPanel { height: 100%; }

    /* ── mode tab bar ── */
    #mode-bar {
        height: 1;
        background: $surface;
        padding: 0 1;
        border-bottom: solid $panel;
    }
    FilterPill.mode-pill {
        height: 1;
        width: auto;
        padding: 0 2;
        margin-right: 1;
        background: $panel;
        color: $foreground 45%;
    }
    FilterPill.mode-pill:hover { color: $foreground; }
    FilterPill.mode-pill.active {
        background: $secondary 25%;
        color: $secondary;
        text-style: bold;
    }

    /* ── journal mode ── */
    #journal-split { height: 1fr; }

    #cal-col {
        width: 26;
        border-right: solid $panel;
        padding: 1 1 0 1;
    }
    #cal-ctx {
        height: 1;
        margin-top: 1;
        align: left middle;
    }
    FilterPill.ctx-pill {
        height: 1;
        width: auto;
        padding: 0 1;
        margin-right: 1;
        background: $surface;
        color: $foreground 40%;
    }
    FilterPill.ctx-pill:hover {
        background: $surface-lighten-1;
        color: $foreground 70%;
    }
    #cal-hint {
        color: $foreground 28%;
        margin-top: 1;
        padding: 0;
    }

    /* ── notes mode ── */
    #tag-bar {
        height: 1;
        background: $surface;
        padding: 0 1;
        border-bottom: solid $panel;
        align: left middle;
    }
    FilterPill.tag-pill {
        height: 1;
        width: auto;
        padding: 0 1;
        margin-right: 1;
        background: $panel;
        color: $foreground 45%;
    }
    FilterPill.tag-pill:hover { background: $panel-lighten-1; color: $foreground 70%; }
    FilterPill.tag-pill.active {
        background: $accent 20%;
        color: $accent;
        text-style: bold;
    }
    .tag-filter-label {
        color: $foreground 35%;
        width: 6;
        content-align: left middle;
    }

    /* ── shared list + viewer ── */
    #split { height: 1fr; }

    #list-col {
        width: 38;
        border-right: solid $panel;
    }
    #list-header {
        background: $surface; padding: 0 1;
        color: $secondary; text-style: bold; height: 1;
    }
    #notes-lv { height: 1fr; background: transparent; }

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
        ("n", "new_note",        "New"),
        ("e", "edit_note",       "Edit ($EDITOR)"),
        ("x", "delete_note",     "Delete"),
        ("p", "paste_image",     "Paste image"),
        ("l", "insert_wikilink", "Link [[]]"),
        ("r", "reload",          "Reload"),
        ("tab", "toggle_mode",   "Switch view"),
    ]

    _mode: reactive[str] = reactive("notes")        # "journal" | "notes"
    _selected_path: reactive[Path | None] = reactive(None)
    _tag_filters: reactive[frozenset] = reactive(frozenset())

    def __init__(self, wm: WorkspaceManager) -> None:
        super().__init__()
        self._wm = wm

    # ------------------------------------------------------------------- data

    def _load(self) -> list[dict]:
        nd = self._wm.notes_dir()
        notes = []
        for p in nd.glob("*.md"):
            try:
                post = frontmatter.load(str(p))
                edited = str(post.metadata.get("editedAt", ""))
                notes.append({
                    "path":    p,
                    "title":   post.metadata.get("title", p.stem),
                    "tags":    post.metadata.get("tags", []),
                    "ntype":   post.metadata.get("type") or note_type(p.stem),
                    "created": str(post.metadata.get("created", ""))[:10],
                    "editedAt": edited,
                    "content": post.content,
                })
            except Exception:
                notes.append({
                    "path":    p,
                    "title":   p.stem,
                    "tags":    [],
                    "ntype":   note_type(p.stem),
                    "created": "",
                    "editedAt": datetime.fromtimestamp(p.stat().st_mtime).isoformat(),
                    "content": p.read_text(encoding="utf-8", errors="replace"),
                })

        def _sort_key(n: dict) -> str:
            edited = n.get("editedAt", "")
            if edited: return edited
            try: return datetime.fromtimestamp(n["path"].stat().st_mtime).isoformat()
            except: return ""

        return sorted(notes, key=_sort_key, reverse=True)

    def _all_tags(self, notes: list[dict]) -> list[str]:
        tags: set[str] = set()
        for n in notes:
            tags.update(n.get("tags", []))
        return sorted(tags)

    def _filtered_notes(self, notes: list[dict]) -> list[dict]:
        if not self._tag_filters:
            return notes
        return [n for n in notes if any(t in n.get("tags", []) for t in self._tag_filters)]

    # ---------------------------------------------------------------- content

    def _rendered_content(self, raw: str) -> str:
        try:
            store = self._wm.store()
            content = render_query_blocks(raw, store)
        except Exception:
            content = raw
        content = self._resolve_wikilinks(content)
        content = self._fix_images(content)
        return content

    def _resolve_wikilinks(self, content: str) -> str:
        try:
            nd = self._wm.notes_dir()
        except Exception:
            return content

        def replace(m: re.Match) -> str:
            name = m.group(1)
            slug = name.lower().replace(" ", "-")
            for candidate in [name, slug]:
                if (nd / f"{candidate}.md").exists():
                    return f"[\\[\\[{name}\\]\\]](note:{candidate})"
            return f"[\\[\\[{name}\\]\\]](note:{slug})"

        return _WIKILINK_RE.sub(replace, content)

    def _fix_images(self, content: str) -> str:
        try:
            nd = self._wm.notes_dir()
        except Exception:
            return content

        def fix(m: re.Match) -> str:
            alt = m.group(1)
            src = m.group(2).strip()
            path = Path(src)
            if not path.is_absolute():
                path = nd / src
            return f"![{alt or path.name}]({path})"

        return _IMG_RE.sub(fix, content)

    def _navigate_to_note(self, path: Path) -> None:
        self._selected_path = path
        try:
            post = frontmatter.load(str(path))
            content = self._rendered_content(post.content)
            title = post.metadata.get("title", path.stem)
        except Exception:
            content = path.read_text(encoding="utf-8", errors="replace")
            title = path.stem
        try:
            self.query_one("#viewer-header", Static).update(f"  {title}")
            self.query_one("#md", Markdown).update(content)
        except Exception:
            pass
        try:
            lv = self.query_one("#notes-lv", ListView)
            for i, item in enumerate(lv.children):
                if isinstance(item, NoteItem) and item.info["path"] == path:
                    lv.index = i
                    break
        except Exception:
            pass

    # --------------------------------------------------------------- compose

    def compose(self) -> ComposeResult:
        notes = self._load()
        all_tags = self._all_tags(notes)
        try:
            entry_dates = journal_dates(self._wm.notes_dir())
        except Exception:
            entry_dates = set()

        today = date.today()
        iso = today.isocalendar()

        with Vertical():
            # ── Mode tab bar ────────────────────────────────────────────────
            with Horizontal(id="mode-bar"):
                for mode_id, label in [("mode-journal", "Journal"), ("mode-notes", "Notes")]:
                    active = self._mode == mode_id[5:]  # "journal" or "notes"
                    cls = "mode-pill active" if active else "mode-pill"
                    yield FilterPill(label, pill_id=mode_id, classes=cls)

            # ── Journal mode ─────────────────────────────────────────────────
            if self._mode == "journal":
                with Horizontal(id="journal-split"):
                    with Vertical(id="cal-col"):
                        yield JournalCalendar(entry_dates, id="calendar")
                        with Horizontal(id="cal-ctx"):
                            yield FilterPill(
                                f"W{iso.week:02d}", pill_id="ctx-week", classes="ctx-pill"
                            )
                            yield FilterPill(
                                today.strftime("%b %Y"), pill_id="ctx-month", classes="ctx-pill"
                            )
                            yield FilterPill(
                                str(today.year), pill_id="ctx-year", classes="ctx-pill"
                            )
                        yield Static(
                            "[dim]Enter·day  W·week  M·month  Y·year[/dim]",
                            id="cal-hint",
                        )

                    with Vertical(id="viewer-col"):
                        yield Static("  Journal", id="viewer-header")
                        with VerticalScroll(id="md-scroll"):
                            yield Markdown(
                                "*Navigate to a day and press Enter to open.*",
                                id="md",
                                open_links=False,
                            )

            # ── Notes mode ───────────────────────────────────────────────────
            else:
                filtered = self._filtered_notes(notes)

                if all_tags:
                    with Horizontal(id="tag-bar"):
                        yield Label("Tags", classes="tag-filter-label")
                        for tag in all_tags:
                            cls = "tag-pill active" if tag in self._tag_filters else "tag-pill"
                            yield FilterPill(f"#{tag}", pill_id=f"ntg-{tag}", classes=cls)

                with Horizontal(id="split"):
                    with Vertical(id="list-col"):
                        yield Static(f"  Notes ({len(filtered)})", id="list-header")
                        if filtered:
                            yield ListView(*[NoteItem(n) for n in filtered], id="notes-lv")
                        else:
                            yield Static(
                                "  No notes yet.\n  [dim]Press [bold]n[/bold] to create one.[/dim]",
                                id="notes-empty",
                            )

                    with Vertical(id="viewer-col"):
                        yield Static("  Preview", id="viewer-header")
                        with VerticalScroll(id="md-scroll"):
                            yield Markdown(
                                "*Select a note from the list.*",
                                id="md",
                                open_links=False,
                            )

    # ─────────────────────────────────────────── reactive watchers

    def watch__mode(self) -> None:
        self.refresh(recompose=True)

    def watch__tag_filters(self) -> None:
        self.refresh(recompose=True)

    # ─────────────────────────────────────────── events

    def on_filter_pill_pressed(self, event: FilterPill.Pressed) -> None:
        pid = event.pill.id or ""

        # Mode toggle
        if pid == "mode-journal":
            self._mode = "journal"
            return
        if pid == "mode-notes":
            self._mode = "notes"
            return

        # Calendar context quick-open
        if pid in ("ctx-week", "ctx-month", "ctx-year"):
            ntype = pid[4:]  # "week" | "month" | "year"
            try:
                cal = self.query_one("#calendar", JournalCalendar)
                d = cal.cursor
            except Exception:
                d = date.today()
            self._open_journal_note(d, ntype)
            return

        # Tag filter
        if pid.startswith("ntg-"):
            tag = pid[4:]
            cur = set(self._tag_filters)
            cur.discard(tag) if tag in cur else cur.add(tag)
            self._tag_filters = frozenset(cur)
            return

    def on_journal_calendar_cursor_changed(self, event: JournalCalendar.CursorChanged) -> None:
        """Update context pills + preview when calendar cursor moves."""
        d = event.date
        iso = d.isocalendar()
        try:
            self.query_one("#ctx-week",  Static).update(f"W{iso.week:02d}")
            self.query_one("#ctx-month", Static).update(d.strftime("%b %Y"))
            self.query_one("#ctx-year",  Static).update(str(d.year))
        except Exception:
            pass

        # Update preview if a day note exists
        try:
            nd = self._wm.notes_dir()
            slug = slug_for(d, "day")
            path = nd / f"{slug}.md"
            if path.exists():
                post = frontmatter.load(str(path))
                content = self._rendered_content(post.content)
                title = post.metadata.get("title", path.stem)
                self.query_one("#viewer-header", Static).update(f"  {title}")
                self.query_one("#md", Markdown).update(content)
                self._selected_path = path
            else:
                self.query_one("#viewer-header", Static).update(
                    f"  {d.isoformat()}  [dim](no entry)[/dim]"
                )
                self.query_one("#md", Markdown).update(
                    f"*No journal entry for {d.isoformat()}.*\n\n"
                    "[dim]Press **Enter** to create and open.[/dim]"
                )
                self._selected_path = None
        except Exception:
            pass

    def on_journal_calendar_activated(self, event: JournalCalendar.Activated) -> None:
        self._open_journal_note(event.date, event.note_type)

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if not isinstance(event.item, NoteItem):
            return
        self._selected_path = event.item.info["path"]
        try:
            self.query_one("#viewer-header", Static).update(
                f"  {event.item.info.get('title', '')}"
            )
        except Exception:
            pass
        content = self._rendered_content(event.item.info.get("content", ""))
        self.query_one("#md", Markdown).update(content)

    def on_markdown_link_clicked(self, event: Markdown.LinkClicked) -> None:
        event.stop()
        href = event.href

        if Path(href).suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}:
            try:
                subprocess.Popen(["xdg-open", href])
            except Exception:
                self.notify("Could not open image — xdg-open not available.", severity="warning")
            return

        if not href.startswith("note:"):
            return
        slug = href[5:]
        nd = self._wm.notes_dir()
        path: Path | None = None
        for candidate in [slug, slug.lower().replace(" ", "-")]:
            p = nd / f"{candidate}.md"
            if p.exists():
                path = p
                break
        if path is None:
            path = nd / f"{slug}.md"
            now = datetime.now().isoformat()
            post = frontmatter.Post(
                "",
                title=slug.replace("-", " ").title(),
                created=now, editedAt=now, tags=[],
            )
            path.write_text(frontmatter.dumps(post), encoding="utf-8")
            self.notify(f"Created '{path.stem}' — opening editor…", timeout=2)
            editor = os.environ.get("EDITOR", "nano")
            with self.app.suspend():
                subprocess.call([editor, str(path)])
            self._update_editedAt(path)
            self.refresh(recompose=True)
            return
        self._navigate_to_note(path)

    # ─────────────────────────────────────────── helpers

    def _open_journal_note(self, d: date, ntype: str) -> None:
        """Ensure journal note exists, open in editor, then update preview."""
        try:
            nd = self._wm.notes_dir()
        except Exception:
            self.notify("No workspace active.", severity="error")
            return
        slug = slug_for(d, ntype)
        path = ensure_note(nd, slug, ntype)
        editor = os.environ.get("EDITOR", "nano")
        with self.app.suspend():
            subprocess.call([editor, str(path)])
        self._update_editedAt(path)
        self._extract_note_todos(path)
        self._selected_path = path
        # Refresh entry dates in calendar
        try:
            cal = self.query_one("#calendar", JournalCalendar)
            cal.update_entries(journal_dates(nd))
        except Exception:
            pass
        # Update preview
        try:
            post = frontmatter.load(str(path))
            content = self._rendered_content(post.content)
            title = post.metadata.get("title", path.stem)
            self.query_one("#viewer-header", Static).update(f"  {title}")
            self.query_one("#md", Markdown).update(content)
        except Exception:
            pass

    def _update_editedAt(self, path: Path) -> None:
        try:
            post = frontmatter.load(str(path))
            post.metadata["editedAt"] = datetime.now().isoformat()
            path.write_text(frontmatter.dumps(post), encoding="utf-8")
        except Exception:
            pass

    def _extract_note_todos(self, path: Path) -> None:
        from src.data.note_todos import parse_note_todos, save_todo_tags
        import uuid as _uuid
        try:
            post = frontmatter.load(str(path))
            parsed = parse_note_todos(post.content, path.stem)
            if not parsed:
                return
            store = self._wm.store()
            existing_hashes = {
                t["source_hash"] for t in store.all("todos") if t.get("source_hash")
            }
            now = datetime.now().isoformat()
            new_count = 0
            for todo in parsed:
                if todo["source_hash"] in existing_hashes:
                    continue
                rec = store.insert("todos", {
                    "id": str(_uuid.uuid4()),
                    "text": todo["text"],
                    "status": todo["status"],
                    "due_date": todo["due_date"],
                    "assignee": todo["assignee"],
                    "note_ref": todo["note_ref"],
                    "source_hash": todo["source_hash"],
                    "created": now,
                    "updated": now,
                })
                if todo["tags"]:
                    save_todo_tags(store, rec["id"], todo["tags"])
                new_count += 1
            if new_count:
                self.notify(f"Extracted {new_count} task(s) from '{path.stem}'.", timeout=4)
        except Exception:
            pass

    def _refresh_preview(self) -> None:
        path = self._selected_path
        if not path or not path.exists():
            return
        try:
            post = frontmatter.load(str(path))
            content = self._rendered_content(post.content)
        except Exception:
            content = path.read_text(encoding="utf-8", errors="replace")
        try:
            self.query_one("#md", Markdown).update(content)
        except Exception:
            pass

    def _clipboard_paste_image(self) -> bytes | None:
        if os.environ.get("WAYLAND_DISPLAY"):
            result = subprocess.run(["wl-paste", "--type", "image/png"], capture_output=True)
        else:
            result = subprocess.run(
                ["xclip", "-selection", "clipboard", "-t", "image/png", "-o"],
                capture_output=True,
            )
        return result.stdout if result.returncode == 0 and result.stdout else None

    def _clipboard_copy_text(self, text: str) -> None:
        try:
            if os.environ.get("WAYLAND_DISPLAY"):
                subprocess.run(["wl-copy"], input=text.encode(), check=True)
            else:
                subprocess.run(
                    ["xclip", "-selection", "clipboard"], input=text.encode(), check=True
                )
        except Exception:
            pass

    # ─────────────────────────────────────────── actions

    def action_toggle_mode(self) -> None:
        self._mode = "notes" if self._mode == "journal" else "journal"

    def action_new_note(self) -> None:
        def cb(result: dict | None) -> None:
            if not result:
                return
            nd = self._wm.notes_dir()
            title = result["title"]
            slug = title.lower().replace(" ", "-").replace("/", "-")
            path = nd / f"{slug}.md"
            now = datetime.now().isoformat()
            post = frontmatter.Post(
                "\n\n", title=title, created=now, editedAt=now, tags=result.get("tags", []),
            )
            path.write_text(frontmatter.dumps(post), encoding="utf-8")
            editor = os.environ.get("EDITOR", "nano")
            with self.app.suspend():
                subprocess.call([editor, str(path)])
            self._update_editedAt(path)
            self._extract_note_todos(path)
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
        self._update_editedAt(path)
        self._extract_note_todos(path)
        self._refresh_preview()
        self.refresh(recompose=True)

    def action_delete_note(self) -> None:
        path = self._selected_path
        if not path:
            self.notify("Select a note first.", severity="warning")
            return
        path.unlink(missing_ok=True)
        self._selected_path = None
        try:
            self.query_one("#md", Markdown).update("*Select a note from the list.*")
        except Exception:
            pass
        self.refresh(recompose=True)
        self.notify("Note deleted.", timeout=1.5)

    def action_paste_image(self) -> None:
        assets_dir = self._wm.notes_dir() / "assets"
        assets_dir.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        dest = assets_dir / f"img-{timestamp}.png"
        try:
            data = self._clipboard_paste_image()
        except FileNotFoundError:
            tool = "wl-paste" if os.environ.get("WAYLAND_DISPLAY") else "xclip"
            self.notify(f"{tool} not found — install it to enable image paste.", severity="error", timeout=4)
            return
        if not data:
            self.notify("No image found in clipboard.", severity="warning")
            return
        dest.write_bytes(data)
        md_link = f"![]({dest})"
        self._clipboard_copy_text(md_link)
        self.notify(f"Saved  assets/{dest.name}\nMarkdown link copied to clipboard.", timeout=5)

    def action_insert_wikilink(self) -> None:
        notes = self._load()

        def cb(slug: str | None) -> None:
            if not slug:
                return
            if slug.startswith("__new__"):
                new_name = slug[7:]
                nd = self._wm.notes_dir()
                file_slug = new_name.lower().replace(" ", "-").replace("/", "-")
                path = nd / f"{file_slug}.md"
                if not path.exists():
                    now = datetime.now().isoformat()
                    post = frontmatter.Post(
                        "", title=new_name, created=now, editedAt=now, tags=[],
                    )
                    path.write_text(frontmatter.dumps(post), encoding="utf-8")
                wikilink = f"[[{file_slug}]]"
                self.refresh(recompose=True)
            else:
                wikilink = f"[[{slug}]]"
            self._clipboard_copy_text(wikilink)
            self.notify(f"Copied  {wikilink}  to clipboard — paste into your editor.", timeout=4)

        self.app.push_screen(WikilinkScreen(notes), cb)

    def action_reload(self) -> None:
        self.refresh(recompose=True)
