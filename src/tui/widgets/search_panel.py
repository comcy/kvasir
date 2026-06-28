"""Full-text search across todos and notes — navigate or edit on Enter/e."""
from __future__ import annotations

from pathlib import Path

import frontmatter
from textual.app import ComposeResult
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Input, Label, ListItem, ListView, Static
from textual.containers import Vertical

from src.workspace.manager import WorkspaceManager
from src.data.journal import note_type

_STATUS_ICON  = {"open": "○", "done": "●", "cancelled": "⊘"}
_STATUS_CSS   = {"open": "todo-open", "done": "todo-done", "cancelled": "todo-cancelled"}
_PRIO_MARKUP  = {3: "[bold red]!!![/bold red]", 2: "[yellow]!![/yellow]", 1: "[dim]![/dim]"}
_NTYPE_BADGE  = {"day": " D", "week": " W", "month": " M", "year": " Y"}


class ResultItem(ListItem):
    def __init__(self, result: dict) -> None:
        super().__init__()
        self.result = result

    def watch_highlighted(self, _: bool) -> None:
        self.refresh(recompose=True)

    def compose(self) -> ComposeResult:
        kind    = self.result.get("kind", "todo")
        title   = self.result.get("title", "")
        sel     = self.highlighted
        arrow   = "[bold bright_cyan]▶[/bold bright_cyan]" if sel else " "
        t_bold  = f"[bold]{title}[/bold]" if sel else title

        if kind == "todo":
            todo     = self.result.get("_todo", {})
            status   = todo.get("status", "open")
            priority = int(todo.get("priority") or 0)
            due      = todo.get("due_date") or ""
            assignee = todo.get("assignee") or ""
            tags     = self.result.get("_tags", [])
            icon     = _STATUS_ICON.get(status, "○")
            css      = _STATUS_CSS.get(status, "")

            yield Label(f" {arrow} {icon}  [{css}]{t_bold}[/{css}]")

            meta: list[str] = []
            if priority in _PRIO_MARKUP:
                meta.append(_PRIO_MARKUP[priority])
            if due:
                meta.append(f"[dim]{due}[/dim]")
            if assignee:
                meta.append(f"[dim]→ @{assignee}[/dim]")
            if tags:
                meta.append("[dim]" + "  ".join(f"#{t}" for t in tags) + "[/dim]")
            if meta:
                yield Label("        " + "  ·  ".join(meta))

        else:
            ntype   = self.result.get("ntype", "note")
            badge   = _NTYPE_BADGE.get(ntype, "  ")
            snippet = self.result.get("snippet", "")

            yield Label(f" {arrow} ◎  [dim]{badge}[/dim]  {t_bold}")
            if snippet:
                trunc = snippet[:90].replace("\n", " ")
                yield Label(f"        [dim]{trunc}[/dim]")


class SearchPanel(Widget):
    class ItemActivated(Message):
        """Posted when the user activates a search result."""
        def __init__(self, result: dict, action: str = "navigate") -> None:
            super().__init__()
            self.result = result
            self.action = action  # "navigate" | "edit"

    DEFAULT_CSS = """
    SearchPanel { height: 100%; }

    #search-box {
        margin: 1 2 0 2;
        height: 3;
    }
    #search-stats {
        padding: 0 2;
        color: $foreground 55%;
        height: 1;
    }
    #search-hint {
        padding: 0 2 1 2;
        color: $foreground 30%;
        height: 1;
    }
    #results-scroll { height: 1fr; }

    ListView { background: transparent; height: auto; }
    ListItem { background: transparent; padding: 0; }
    ListItem:hover { background: $surface; }
    ListView:focus > ListItem.--highlight { background: $primary 20%; }

    ResultItem { height: auto; padding: 1 0 0 0; }

    .todo-open      { color: $foreground; }
    .todo-done      { color: $success; text-style: dim; }
    .todo-cancelled { color: $error; text-style: dim strike; }

    #hint { padding: 2 4; color: $foreground 45%; }
    """

    BINDINGS = [
        ("escape", "clear_search", "Clear"),
        ("e",      "edit_result",  "Edit"),
    ]

    _query: reactive[str] = reactive("")

    def __init__(self, wm: WorkspaceManager) -> None:
        super().__init__()
        self._wm = wm

    def compose(self) -> ComposeResult:
        yield Input(placeholder="Search todos and notes…", id="search-box")
        yield Static("", id="search-stats")
        yield Static(
            "  [dim]Enter: jump to tab  ·  e: open for editing[/dim]",
            id="search-hint",
        )
        with Vertical(id="results-scroll"):
            yield Static("  Type to search across todos and notes.", id="hint")

    def on_mount(self) -> None:
        self.query_one("#search-box", Input).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "search-box":
            q = event.value.strip().lower()
            self._query = q
            self._rebuild(q)

    def _rebuild(self, q: str) -> None:
        scroll = self.query_one("#results-scroll", Vertical)
        stats  = self.query_one("#search-stats", Static)
        scroll.remove_children()

        if not q:
            stats.update("")
            scroll.mount(Static("  Type to search across todos and notes.", id="hint"))
            return

        results = self._search(q)
        stats.update(f"  {len(results)} result(s) for '[bold]{q}[/bold]'")

        if not results:
            scroll.mount(Static(f"  [dim]No results for '{q}'[/dim]"))
        else:
            scroll.mount(ListView(*[ResultItem(r) for r in results]))

    def _search(self, q: str) -> list[dict]:
        results: list[dict] = []

        # ── todos ──────────────────────────────────────────────────────────────
        try:
            store = self._wm.store()
            tag_by_id: dict[str, str] = {t["id"]: t["name"] for t in store.all("tags")}
            tag_map: dict[str, list[str]] = {}
            for tt in store.all("todo_tags"):
                name = tag_by_id.get(tt.get("tag_id", ""))
                if name:
                    tag_map.setdefault(tt["todo_id"], []).append(name)

            for todo in store.all("todos"):
                text  = todo.get("text", "").lower()
                tags  = sorted(tag_map.get(todo["id"], []))
                if q in text or any(q in tg.lower() for tg in tags):
                    todo["_tags"] = tags
                    results.append({
                        "kind":  "todo",
                        "_id":   todo["id"],
                        "_todo": todo,
                        "_tags": tags,
                        "title": todo.get("text", ""),
                    })
        except Exception:
            pass

        # ── notes ──────────────────────────────────────────────────────────────
        try:
            nd = self._wm.notes_dir()
            for p in sorted(nd.glob("*.md"), key=lambda f: f.stat().st_mtime, reverse=True):
                try:
                    post = frontmatter.load(str(p))
                    title_lc   = str(post.metadata.get("title", p.stem)).lower()
                    tags_lc    = [str(t).lower() for t in post.metadata.get("tags", [])]
                    content_lc = post.content.lower()

                    if q in title_lc or any(q in tg for tg in tags_lc) or q in content_lc:
                        snippet = ""
                        if q in content_lc:
                            idx = content_lc.find(q)
                            s, e = max(0, idx - 30), min(len(post.content), idx + 60)
                            snippet = "…" + post.content[s:e].replace("\n", " ").strip() + "…"

                        ntype = (
                            post.metadata.get("type")
                            or note_type(p.stem)
                        )
                        results.append({
                            "kind":    "note",
                            "title":   post.metadata.get("title", p.stem),
                            "snippet": snippet or ", ".join(tags_lc),
                            "path":    str(p),
                            "ntype":   ntype,
                        })
                except Exception:
                    pass
        except Exception:
            pass

        return results

    # ── events ─────────────────────────────────────────────────────────────────

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Enter key on a result → navigate to its tab."""
        if isinstance(event.item, ResultItem):
            self.post_message(SearchPanel.ItemActivated(event.item.result, action="navigate"))

    # ── actions ────────────────────────────────────────────────────────────────

    def action_clear_search(self) -> None:
        inp = self.query_one("#search-box", Input)
        inp.clear()
        inp.focus()

    def action_edit_result(self) -> None:
        """e key on a result → jump to tab and open for editing."""
        try:
            lv = self.query_one(ListView)
            idx = lv.index
            if idx is None:
                return
            children = list(lv.children)
            if idx < len(children) and isinstance(children[idx], ResultItem):
                self.post_message(
                    SearchPanel.ItemActivated(children[idx].result, action="edit")
                )
        except Exception:
            pass
