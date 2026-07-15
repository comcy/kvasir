"""Notes panel: Journal calendar view + Notes list view, edit via $EDITOR."""
from __future__ import annotations

import re
import subprocess
import uuid
from datetime import date, datetime
from pathlib import Path

import frontmatter
from textual.app import ComposeResult
from textual.message import Message
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Input, Label, ListItem, ListView, Markdown, Static, Tab, Tabs
from textual.containers import Horizontal, Vertical, VerticalScroll

from src.workspace.manager import WorkspaceManager
from src.data.query import render_query_blocks
from src.data.journal import (
    journal_dates, note_type, slug_for, ensure_note,
)
from src.platform_utils import default_editor, open_file
from src.tui.widgets.journal_calendar import JournalCalendar

_WIKILINK_RE = re.compile(r'\[\[([^\]]+)\]\]')
_IMG_RE = re.compile(r'!\[([^\]]*)\]\(([^)]+)\)')
# Matches YYYY-Wnn, YYYY-MM-DD, YYYY-MM — in that priority order.
# Negative lookahead (?![-\d]) prevents matching the YYYY-MM part of a full YYYY-MM-DD.
_DATE_RE = re.compile(r'\b(\d{4}-W\d{2}|\d{4}-\d{2}-\d{2}|\d{4}-\d{2})(?![-\d])')
# Splits content into code-block / non-code-block alternating segments.
_CODE_FENCE_RE = re.compile(r'(```[\s\S]*?```|`[^`\n]+`)')


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
    ListView:focus > ListItem.--highlight { background: $primary 20%; }
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


# ─────────────────────── list items ──────────────────────────────────────────

_JOURNAL_TYPES = {"day", "week", "month", "year"}
_JOURNAL_INDENT = {"year": 0, "month": 1, "week": 2, "day": 3}


class NoteItem(ListItem):
    def __init__(self, info: dict) -> None:
        super().__init__()
        self.info = info

    def watch_highlighted(self, _: bool) -> None:
        self.refresh(recompose=True)

    def compose(self) -> ComposeResult:
        title  = self.info.get("title", "Untitled")
        tags   = self.info.get("tags", [])
        ntype  = self.info.get("ntype", "note")
        stem   = self.info["path"].stem
        edited = (self.info.get("editedAt") or "")[:16].replace("T", " ")
        sel    = self.highlighted

        today_slug = date.today().isoformat()
        if ntype == "day":
            badge = "[bold]*D[/bold]" if stem == today_slug else "[dim] D[/dim]"
        elif ntype == "week":  badge = "[dim] W[/dim]"
        elif ntype == "month": badge = "[dim] M[/dim]"
        elif ntype == "year":  badge = "[dim] Y[/dim]"
        else:                  badge = "  "

        # 2 spaces per hierarchy level (year=0, month=1, week=2, day=3)
        pad = "  " * _JOURNAL_INDENT.get(ntype, 0)

        tags_str = "  " + " ".join(f"[dim][{t}][/dim]" for t in tags) if tags else ""
        arrow    = "[bold bright_cyan]▶[/bold bright_cyan]" if sel else " "
        title_markup = f"[bold]{title}[/bold]"

        # Line 1: arrow + hierarchy indent + badge │ title  tags
        yield Label(f"{arrow} {pad}{badge} [dim]│[/dim] {title_markup}{tags_str}")
        # Line 2: align │ under line 1's │ (arrow col = 1 char + 1 space = same as before)
        if edited:
            yield Label(f"  {pad}     [dim]│ ✎ {edited}[/dim]")


# ─────────────────────── main panel ──────────────────────────────────────────

class NotesPanel(Widget):
    DEFAULT_CSS = """
    NotesPanel { height: 100%; }

    /* ── journal mode ── */
    #journal-split { height: 1fr; }

    #cal-col {
        width: 38;
        height: 100%;
        border-right: solid $panel;
        padding: 1 1 0 1;
    }
    #journal-tree-label {
        color: $foreground 40%;
        text-style: bold;
        margin-top: 1;
    }
    #journal-tree-scroll {
        height: 1fr;
        margin-top: 1;
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
    ListView:focus > ListItem.--highlight { background: $primary 20%; }

    NoteItem { height: auto; padding: 1 0 0 0; }

    #notes-empty { padding: 2 4; color: $foreground 45%; }
    """

    BINDINGS = [
        ("n", "new_note",        "New"),
        ("e", "edit_note",       "Edit ($EDITOR)"),
        ("x", "delete_note",     "Delete"),
        ("p", "paste_image",     "Paste image"),
        ("l", "insert_wikilink", "Link [[]]"),
        ("r", "reload",          "Reload"),
        ("ctrl+w", "close_tab",  "Close tab"),
        ("P", "toggle_pin",      "Pin tab"),
    ]

    _mode: reactive[str] = reactive("notes")        # "journal" | "notes"
    _selected_path: reactive[Path | None] = reactive(None)
    _tag_filters: reactive[frozenset] = reactive(frozenset())
    _open_tabs: reactive[list] = reactive(list)     # list[Path] — explicitly opened notes

    def __init__(self, wm: WorkspaceManager) -> None:
        super().__init__()
        self._wm = wm
        self._tab_ids: dict[Path, str] = {}   # Path -> stable "nt-N" id, never reused
        self._tab_counter = 0
        self._cal_tab_timer = None            # debounced tab-open while browsing the calendar

        self._pinned: set[Path] = set()
        pinned_paths: list[Path] = []
        try:
            records = sorted(wm.store().all("pinned_notes"), key=lambda r: r.get("pinned_at", ""))
            for r in records:
                p = Path(r["path"])
                if p.exists():
                    pinned_paths.append(p)
            self._pinned = set(pinned_paths)
        except Exception:
            pass
        self._open_tabs = pinned_paths  # pinned notes are already open on launch

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

    def _sort_journal_entries(self, notes: list[dict]) -> list[dict]:
        """
        Return journal notes in hierarchical order:
          current-year → (current-month → (current-week → days desc) → past weeks) → past months
          → past years

        Each "parent" note (year/month/week) appears before its children.
        Current period at each level always floats to the top.
        """
        today = date.today()
        iso_today  = today.isocalendar()
        cur_year   = today.year
        cur_month  = today.strftime("%Y-%m")
        cur_week   = f"{iso_today.year}-W{iso_today.week:02d}"

        year_map:  dict[str, dict] = {}
        month_map: dict[str, dict] = {}
        week_map:  dict[str, dict] = {}
        day_map:   dict[str, dict] = {}
        for n in notes:
            s = n["path"].stem
            t = n.get("ntype")
            if   t == "year":  year_map[s]  = n
            elif t == "month": month_map[s] = n
            elif t == "week":  week_map[s]  = n
            elif t == "day":   day_map[s]   = n

        def _week_month(w: str) -> str:
            """YYYY-MM of the Thursday of ISO week w (= the month this week belongs to)."""
            wy, wn = int(w[:4]), int(w[6:])
            return date.fromisocalendar(wy, wn, 4).strftime("%Y-%m")

        def _day_week(d: str) -> str:
            iso = date.fromisoformat(d).isocalendar()
            return f"{iso.year}-W{iso.week:02d}"

        # ── collect all year buckets ─────────────────────────────────────
        all_years: set[int] = set()
        for s in year_map:  all_years.add(int(s))
        for s in month_map: all_years.add(int(s[:4]))
        for s in week_map:  all_years.add(int(_week_month(s)[:4]))
        for s in day_map:   all_years.add(date.fromisoformat(s).year)

        sorted_years = sorted(all_years,
            key=lambda y: (0 if y == cur_year else 1, -y))

        result: list[dict] = []

        for year_int in sorted_years:
            year_str = str(year_int)
            if year_str in year_map:
                result.append(year_map[year_str])

            # ── collect all month buckets for this year ───────────────────
            months: set[str] = set()
            for s in month_map:
                if s[:4] == year_str: months.add(s)
            for s in week_map:
                m = _week_month(s)
                if m[:4] == year_str: months.add(m)
            for s in day_map:
                if date.fromisoformat(s).year == year_int:
                    months.add(date.fromisoformat(s).strftime("%Y-%m"))

            sorted_months = sorted(months,
                key=lambda m: (0 if m == cur_month else 1, -int(m[5:7])))

            for month_str in sorted_months:
                if month_str in month_map:
                    result.append(month_map[month_str])

                # ── collect all week buckets for this month ───────────────
                weeks: set[str] = set()
                for s in week_map:
                    if _week_month(s) == month_str: weeks.add(s)
                for s in day_map:
                    w = _day_week(s)
                    if _week_month(w) == month_str: weeks.add(w)

                sorted_weeks = sorted(weeks,
                    key=lambda w: (0 if w == cur_week else 1, -int(w[6:])))

                for week_str in sorted_weeks:
                    if week_str in week_map:
                        result.append(week_map[week_str])

                    # days in this week, descending
                    week_days = sorted(
                        [day_map[s] for s in day_map if _day_week(s) == week_str],
                        key=lambda n: n["path"].stem,
                        reverse=True,
                    )
                    result.extend(week_days)

        return result

    # ---------------------------------------------------------------- content

    def _rendered_content(self, raw: str) -> str:
        try:
            store = self._wm.store()
            content = render_query_blocks(raw, store)
        except Exception:
            content = raw
        content = self._resolve_wikilinks(content)
        content = self._linkify_dates(content)
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

    def _linkify_dates(self, content: str) -> str:
        """Convert bare ISO dates to date: links, skipping code blocks."""
        parts = _CODE_FENCE_RE.split(content)
        out = []
        for i, part in enumerate(parts):
            if i % 2 == 1:      # inside a code span / fence — leave untouched
                out.append(part)
            else:
                out.append(_DATE_RE.sub(
                    lambda m: f"[📅 {m.group(1)}](date:{m.group(1)})",
                    part,
                ))
        return "".join(out)

    def _backlinks_section(self, path: Path) -> str:
        """Return a Markdown backlinks block for journal notes, or '' for regular notes."""
        ntype = note_type(path.stem)
        if ntype == "note":
            return ""
        slug = path.stem
        try:
            nd = self._wm.notes_dir()
        except Exception:
            return ""
        refs: list[str] = []
        for p in sorted(nd.glob("*.md")):
            if p == path:
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
                if slug not in text:
                    continue
                try:
                    post = frontmatter.load(str(p))
                    title = post.metadata.get("title", p.stem)
                except Exception:
                    title = p.stem
                refs.append(f"- [\\[\\[{p.stem}\\]\\]](note:{p.stem}) — {title}")
            except Exception:
                continue
        if not refs:
            return ""
        lines = "\n".join(refs)
        return f"\n\n---\n**Referenced in** ({len(refs)})\n\n{lines}\n"

    def _show_note(self, path: Path) -> None:
        """Render *path* into the preview pane. Does not open a tab — used for
        both passive browsing and tab activation."""
        self._selected_path = path
        try:
            post = frontmatter.load(str(path))
            content = self._rendered_content(post.content) + self._backlinks_section(path)
            title = post.metadata.get("title", path.stem)
        except Exception:
            content = path.read_text(encoding="utf-8", errors="replace")
            title = path.stem
        try:
            self.query_one("#viewer-header", Static).update(f"  {title}")
            self.query_one("#md", Markdown).update(content)
        except Exception:
            pass

    def _tab_label(self, path: Path) -> str:
        return f"📌{path.stem}" if path in self._pinned else path.stem

    def _add_tab(self, path: Path) -> None:
        """Open *path* as an editor tab: explicit-open sites (edit/create/
        wikilink) call this directly; calendar browsing calls it after a
        short debounce (see on_journal_calendar_cursor_changed). Mutates the
        mounted Tabs widget in place rather than recomposing the panel — a
        full recompose would reset the JournalCalendar's cursor back to
        today, since it has no persisted-cursor constructor argument."""
        is_new = path not in self._open_tabs
        if is_new:
            self._open_tabs = [*self._open_tabs, path]
            self._tab_ids[path] = f"nt-{self._tab_counter}"
            self._tab_counter += 1
        self._show_note(path)

        try:
            tabs_widget = self.query_one("#note-tabs", Tabs)
        except Exception:
            return  # not mounted yet — the next compose() will pick up _open_tabs
        if is_new:
            tabs_widget.add_tab(Tab(self._tab_label(path), id=self._tab_ids[path]))
        tabs_widget.display = True
        tabs_widget.active = self._tab_ids[path]

    def _navigate_to_note(self, path: Path) -> None:
        self._show_note(path)
        try:
            lv = self.query_one("#notes-lv", ListView)
            for i, item in enumerate(lv.children):
                if isinstance(item, NoteItem) and item.info["path"] == path:
                    lv.index = i
                    break
        except Exception:
            pass

    # --------------------------------------------------------------- compose

    def _compose_note_tabs(self) -> ComposeResult:
        """Editor-tab strip: one tab per explicitly-opened note, shared across
        Journal/Notes mode. Always mounted (hidden via display=False when
        empty) so _add_tab/action_close_tab can mutate it in place afterward
        instead of recomposing the panel."""
        for path in self._open_tabs:
            if path not in self._tab_ids:
                self._tab_ids[path] = f"nt-{self._tab_counter}"
                self._tab_counter += 1

        active_id = self._tab_ids.get(self._selected_path) if self._selected_path in self._open_tabs else None
        tabs = [Tab(self._tab_label(path), id=self._tab_ids[path]) for path in self._open_tabs]
        tabs_widget = Tabs(*tabs, active=active_id, id="note-tabs")
        tabs_widget.display = bool(self._open_tabs)
        yield tabs_widget

    def on_mount(self) -> None:
        # Pinned tabs are already open (seeded in __init__) but compose()'s
        # initial Markdown/Static widgets are static placeholders — show the
        # first one so there's something in the preview right on launch.
        if self._open_tabs and self._selected_path is None:
            path = self._open_tabs[0]
            self._show_note(path)
            try:
                self.query_one("#note-tabs", Tabs).active = self._tab_ids.get(path, "")
            except Exception:
                pass

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
            # ── Mode tab bar (Textual Tabs — arrow keys to switch) ───────────
            active_tab = "tab-journal" if self._mode == "journal" else "tab-notes"
            yield Tabs(
                Tab("Journal", id="tab-journal"),
                Tab("Notes",   id="tab-notes"),
                active=active_tab,
            )

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
                        yield Static("Journal", id="journal-tree-label")
                        journal_notes = self._sort_journal_entries(
                            [n for n in notes if n.get("ntype") in _JOURNAL_TYPES]
                        )
                        with VerticalScroll(id="journal-tree-scroll"):
                            if journal_notes:
                                yield ListView(
                                    *[NoteItem(n) for n in journal_notes], id="journal-tree",
                                    initial_index=None,
                                )
                            else:
                                yield Static("  [dim]No entries yet.[/dim]")

                    with Vertical(id="viewer-col"):
                        yield from self._compose_note_tabs()
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
                # Journal entries live in the Journal tab's tree now — only
                # regular notes show up here.
                regular = [n for n in filtered if n.get("ntype") not in _JOURNAL_TYPES]

                if all_tags:
                    with Horizontal(id="tag-bar"):
                        yield Label("Tags", classes="tag-filter-label")
                        for tag in all_tags:
                            cls = "tag-pill active" if tag in self._tag_filters else "tag-pill"
                            yield FilterPill(f"#{tag}", pill_id=f"ntg-{tag}", classes=cls)

                with Horizontal(id="split"):
                    with Vertical(id="list-col"):
                        yield Static(
                            f"  {len(regular)} note{'s' if len(regular) != 1 else ''}",
                            id="list-header",
                        )
                        if regular:
                            yield ListView(
                                *[NoteItem(n) for n in regular], id="notes-lv", initial_index=None,
                            )
                        else:
                            yield Static(
                                "  No notes yet.\n  [dim]Press [bold]n[/bold] to create one.[/dim]",
                                id="notes-empty",
                            )

                    with Vertical(id="viewer-col"):
                        yield from self._compose_note_tabs()
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

    def on_tabs_tab_activated(self, event: Tabs.TabActivated) -> None:
        if event.tab is None:
            return
        tid = event.tab.id or ""
        if tid.startswith("nt-"):
            path = next((p for p, i in self._tab_ids.items() if i == tid), None)
            if path is not None:
                self._show_note(path)
            return
        self._mode = "journal" if tid == "tab-journal" else "notes"

    def on_filter_pill_pressed(self, event: FilterPill.Pressed) -> None:
        pid = event.pill.id or ""

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
                content = (
                    self._rendered_content(post.content)
                    + self._backlinks_section(path)
                )
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

        # Debounced tab-open: only the day the cursor settles on (briefly
        # stops moving) gets a tab, so fast arrow-key browsing doesn't spam
        # the strip the way opening a tab on every single keypress would.
        if self._cal_tab_timer is not None:
            self._cal_tab_timer.stop()
            self._cal_tab_timer = None
        if self._selected_path is not None:
            settled_path = self._selected_path
            self._cal_tab_timer = self.set_timer(0.6, lambda: self._add_tab(settled_path))

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
                open_file(href)
            except Exception:
                self.notify("Could not open image — no default app handler found.", severity="warning")
            return

        # date: link — navigate to journal note, auto-create if missing
        if href.startswith("date:"):
            slug = href[5:]
            ntype = note_type(slug)
            try:
                nd = self._wm.notes_dir()
                path = nd / f"{slug}.md"
                if not path.exists():
                    path = ensure_note(nd, slug, ntype)
                    self.notify(f"Created {ntype} entry for {slug}", timeout=2)
                self._add_tab(path)
            except Exception:
                pass
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
            editor = default_editor()
            with self.app.suspend():
                subprocess.call([editor, str(path)])
            self._update_editedAt(path)
            self._add_tab(path)
            if self._mode == "notes":
                self.refresh(recompose=True)
            return
        self._navigate_to_note(path)

    # ─────────────────────────────────────────── helpers

    def _open_journal_note(self, d: date, ntype: str) -> None:
        """Ensure journal note exists, open in editor, then update preview."""
        if self._cal_tab_timer is not None:
            self._cal_tab_timer.stop()
            self._cal_tab_timer = None
        try:
            nd = self._wm.notes_dir()
        except Exception:
            self.notify("No workspace active.", severity="error")
            return
        slug = slug_for(d, ntype)
        path = ensure_note(nd, slug, ntype)
        editor = default_editor()
        with self.app.suspend():
            subprocess.call([editor, str(path)])
        self._update_editedAt(path)
        self._extract_note_todos(path)
        # Refresh entry dates in calendar
        try:
            cal = self.query_one("#calendar", JournalCalendar)
            cal.update_entries(journal_dates(nd))
        except Exception:
            pass
        self._add_tab(path)

    def _update_editedAt(self, path: Path) -> None:
        try:
            post = frontmatter.load(str(path))
            post.metadata["editedAt"] = datetime.now().isoformat()
            path.write_text(frontmatter.dumps(post), encoding="utf-8")
        except Exception:
            pass

    def _extract_note_todos(self, path: Path) -> None:
        from src.data.note_todos import sync_note_todos
        try:
            store = self._wm.store()
            created, updated = sync_note_todos(store, path, path.stem)
            parts: list[str] = []
            if created:
                parts.append(f"{created} new")
            if updated:
                parts.append(f"{updated} updated")
            if parts:
                self.notify(
                    f"Synced {' · '.join(parts)} task(s) from '{path.stem}'.", timeout=4
                )
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

    # ─────────────────────────────────────────── public API (called from search)

    def navigate_to(self, path: Path) -> None:
        """Switch to the right mode (if needed) and select a note in its list."""
        target_mode = "journal" if note_type(path.stem) in _JOURNAL_TYPES else "notes"
        if self._mode != target_mode:
            self._mode = target_mode  # triggers watch__mode → recompose
            self.call_after_refresh(lambda: self._do_navigate_note(path))
        else:
            self._do_navigate_note(path)

    def _do_navigate_note(self, path: Path) -> None:
        # Both ListViews are built with initial_index=None: ListView's own
        # _on_mount() forces .index back to its (default 0) initial_index
        # after mounting, which can race with — and silently overwrite — the
        # explicit `lv.index = i` below whenever this runs right after a mode
        # switch (a fresh ListView is mounted then).
        list_id = "#journal-tree" if note_type(path.stem) in _JOURNAL_TYPES else "#notes-lv"
        try:
            lv = self.query_one(list_id, ListView)
            for i, child in enumerate(lv.children):
                if isinstance(child, NoteItem) and child.info.get("path") == path:
                    lv.index = i
                    lv.focus()
                    self._selected_path = path
                    rendered = self._rendered_content(child.info.get("content", ""))
                    self.query_one("#md", Markdown).update(rendered)
                    break
        except Exception:
            pass

    def open_note(self, path: Path) -> None:
        """Open $EDITOR for a specific note path (called from search edit action)."""
        editor = default_editor()
        with self.app.suspend():
            subprocess.call([editor, str(path)])
        self._update_editedAt(path)
        self._extract_note_todos(path)
        self._add_tab(path)
        self.refresh(recompose=True)

    def _clipboard_paste_image(self) -> bytes | None:
        """PNG bytes currently on the clipboard, or None if it's not an image.

        Goes through Pillow's ImageGrab, which is native on Windows/macOS and
        shells out to wl-paste/xclip on Linux (same runtime requirement as
        before, just no hand-rolled per-OS branching here anymore)."""
        from io import BytesIO
        from PIL import ImageGrab

        img = ImageGrab.grabclipboard()
        if img is None or isinstance(img, list):  # list: clipboard held file paths, not image data
            return None
        buf = BytesIO()
        img.save(buf, "PNG")
        return buf.getvalue()

    def _clipboard_copy_text(self, text: str) -> None:
        try:
            import pyperclip
            pyperclip.copy(text)
        except Exception:
            pass

    # ─────────────────────────────────────────── actions

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
            editor = default_editor()
            with self.app.suspend():
                subprocess.call([editor, str(path)])
            self._update_editedAt(path)
            self._extract_note_todos(path)
            self._add_tab(path)
            # Only the Notes-mode list needs to reflect the new entry — a full
            # recompose while in Journal mode would reset the calendar cursor.
            if self._mode == "notes":
                self.refresh(recompose=True)
            self.notify(f"Created '{title}'", timeout=2)

        self.app.push_screen(NewNoteScreen(), cb)

    def action_edit_note(self) -> None:
        path = self._selected_path
        if not path:
            self.notify("Select a note first.", severity="warning")
            return
        editor = default_editor()
        with self.app.suspend():
            subprocess.call([editor, str(path)])
        self._update_editedAt(path)
        self._extract_note_todos(path)
        self._add_tab(path)
        if self._mode == "notes":
            self.refresh(recompose=True)

    def action_delete_note(self) -> None:
        path = self._selected_path
        if not path:
            self.notify("Select a note first.", severity="warning")
            return
        path.unlink(missing_ok=True)

        if path in self._open_tabs:
            tab_id = self._tab_ids.pop(path, None)
            self._open_tabs = [p for p in self._open_tabs if p != path]
            try:
                tabs_widget = self.query_one("#note-tabs", Tabs)
                if tab_id:
                    tabs_widget.remove_tab(tab_id)
                if not self._open_tabs:
                    tabs_widget.display = False
            except Exception:
                pass

        self._selected_path = None
        try:
            self.query_one("#viewer-header", Static).update("  Preview")
            self.query_one("#md", Markdown).update("*Select a note from the list.*")
        except Exception:
            pass
        if self._mode == "notes":
            self.refresh(recompose=True)
        self.notify("Note deleted.", timeout=1.5)

    def action_paste_image(self) -> None:
        assets_dir = self._wm.notes_dir() / "assets"
        assets_dir.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        dest = assets_dir / f"img-{timestamp}.png"
        try:
            data = self._clipboard_paste_image()
        except Exception as e:
            self.notify(f"Could not read clipboard: {e}", severity="error", timeout=5)
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

    def action_close_tab(self) -> None:
        path = self._selected_path
        if path is None or path not in self._open_tabs:
            return
        if path in self._pinned:
            self.notify("Pinned — unpin with P first.", severity="warning")
            return
        tab_id = self._tab_ids.pop(path, None)
        tabs = list(self._open_tabs)
        idx = tabs.index(path)
        tabs.pop(idx)
        self._open_tabs = tabs

        try:
            tabs_widget = self.query_one("#note-tabs", Tabs)
        except Exception:
            tabs_widget = None
        if tabs_widget is not None and tab_id:
            tabs_widget.remove_tab(tab_id)

        if tabs:
            next_path = tabs[min(idx, len(tabs) - 1)]
            self._show_note(next_path)
            if tabs_widget is not None:
                tabs_widget.active = self._tab_ids.get(next_path, "")
        else:
            self._selected_path = None
            try:
                self.query_one("#viewer-header", Static).update("  Preview")
                self.query_one("#md", Markdown).update("*Select a note from the list.*")
            except Exception:
                pass
            if tabs_widget is not None:
                tabs_widget.display = False

    def action_toggle_pin(self) -> None:
        path = self._selected_path
        if path is None or path not in self._open_tabs:
            self.notify("Select an open tab first.", severity="warning")
            return

        store = self._wm.store()
        if path in self._pinned:
            for rec in store.find("pinned_notes", path=str(path)):
                store.delete("pinned_notes", rec["id"])
            self._pinned.discard(path)
            self.notify("Unpinned.", timeout=1.5)
        else:
            store.insert("pinned_notes", {
                "id": str(uuid.uuid4()),
                "path": str(path),
                "pinned_at": datetime.now().isoformat(),
            })
            self._pinned.add(path)
            self.notify("Pinned.", timeout=1.5)

        tab_id = self._tab_ids.get(path)
        if tab_id:
            try:
                self.query_one("#note-tabs", Tabs).get_tab(tab_id).label = self._tab_label(path)
            except Exception:
                pass
