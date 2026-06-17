"""Full-text search across todos and notes."""
from __future__ import annotations

from pathlib import Path

import frontmatter
from textual.app import ComposeResult
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Input, Label, ListItem, ListView, Static
from textual.containers import Vertical

from devtrack.workspace.manager import WorkspaceManager


class ResultItem(ListItem):
    def __init__(self, result: dict) -> None:
        super().__init__()
        self.result = result

    def compose(self) -> ComposeResult:
        kind = self.result.get("kind", "todo")
        icon = "○" if kind == "todo" else "◎"
        color = "$primary" if kind == "todo" else "$secondary"
        title = self.result.get("title", "")
        snippet = self.result.get("snippet", "")
        yield Label(
            f"  [{color}]{icon}[/{color}]  [bold]{title}[/bold]"
            + (f"  [dim]{snippet}[/dim]" if snippet else "")
        )


class SearchPanel(Widget):
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
        margin-bottom: 1;
    }
    #results-scroll { height: 1fr; }

    ListView { background: transparent; height: auto; }
    ListItem { background: transparent; padding: 0; }
    ListItem:hover { background: $surface; }
    ListView:focus > ListItem.--highlight { background: $surface; }

    #hint { padding: 2 4; color: $foreground 45%; }
    """

    BINDINGS = [
        ("escape", "clear_search", "Clear"),
    ]

    _query: reactive[str] = reactive("")

    def __init__(self, wm: WorkspaceManager) -> None:
        super().__init__()
        self._wm = wm

    def compose(self) -> ComposeResult:
        yield Input(placeholder="Search todos and notes…", id="search-box")
        yield Static("", id="search-stats")
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
        stats = self.query_one("#search-stats", Static)
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

        # ── todos ──
        try:
            store = self._wm.store()
            tag_by_id = {t["id"]: t["name"] for t in store.all("tags")}
            tag_map: dict[str, list[str]] = {}
            for tt in store.all("todo_tags"):
                name = tag_by_id.get(tt.get("tag_id", ""))
                if name:
                    tag_map.setdefault(tt["todo_id"], []).append(name)

            for todo in store.all("todos"):
                text = todo.get("text", "").lower()
                tags = tag_map.get(todo["id"], [])
                if q in text or any(q in tg.lower() for tg in tags):
                    status = todo.get("status", "open")
                    tags_str = "  ".join(f"[{t}]" for t in tags)
                    results.append({
                        "kind": "todo",
                        "title": todo.get("text", ""),
                        "snippet": f"[{status}]  {tags_str}".strip(),
                    })
        except Exception:
            pass

        # ── notes ──
        try:
            nd = self._wm.notes_dir()
            for p in sorted(nd.glob("*.md"), key=lambda f: f.stat().st_mtime, reverse=True):
                try:
                    post = frontmatter.load(str(p))
                    title_lc = str(post.metadata.get("title", p.stem)).lower()
                    tags_lc = [str(t).lower() for t in post.metadata.get("tags", [])]
                    content_lc = post.content.lower()

                    if q in title_lc or any(q in tg for tg in tags_lc) or q in content_lc:
                        snippet = ""
                        if q in content_lc:
                            idx = content_lc.find(q)
                            s, e = max(0, idx - 30), min(len(post.content), idx + 60)
                            snippet = "…" + post.content[s:e].replace("\n", " ").strip() + "…"
                        results.append({
                            "kind": "note",
                            "title": post.metadata.get("title", p.stem),
                            "snippet": snippet or ", ".join(tags_lc),
                            "path": str(p),
                        })
                except Exception:
                    pass
        except Exception:
            pass

        return results

    def action_clear_search(self) -> None:
        inp = self.query_one("#search-box", Input)
        inp.clear()
        inp.focus()
