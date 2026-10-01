"""Three-column read-only overview: Repos -> Worktrees/Branches -> Details."""
from __future__ import annotations

from typing import ClassVar

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Footer, OptionList

from kvasir.tui.columns import DetailPanel, EntryList, RepoList
from kvasir.tui.data import RepoRow, load_rows


class KvasirApp(App):
    CSS = """
    Horizontal { height: 1fr; }
    RepoList { width: 1fr; min-width: 12; }
    EntryList { width: 2fr; min-width: 12; }
    DetailPanel { width: 1fr; min-width: 12; padding: 0 1; border-left: solid $primary; }
    """
    BINDINGS: ClassVar[list[Binding]] = [
        Binding("q", "quit", "Quit"),
        Binding("r", "reload", "Reload"),
        Binding("h", "focus_previous", "Left", show=False),
        Binding("l", "focus_next", "Right", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[RepoRow] = []
        self.entries: list = []

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield RepoList(id="repos")
            yield EntryList(id="entries")
            yield DetailPanel(id="detail")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one(RepoList).focus()
        self.action_reload()

    def action_reload(self) -> None:
        self._load()

    @work(thread=True, exclusive=True)
    def _load(self) -> None:
        rows = load_rows()  # git calls: keep off the UI thread
        self.call_from_thread(self._loaded, rows)

    def _loaded(self, rows: list[RepoRow]) -> None:
        self.rows = rows
        repos = self.query_one(RepoList)
        repos.set_rows(rows)
        if rows:
            repos.highlighted = 0
        self._show_entries(0 if rows else None)

    def _show_entries(self, idx: int | None) -> None:
        row = self.rows[idx] if idx is not None and idx < len(self.rows) else None
        self.entries = [*row.view.worktrees, *row.view.branches] if row and row.view else []
        lst = self.query_one(EntryList)
        lst.set_entries(self.entries)
        if self.entries:
            lst.highlighted = 0
        self.query_one(DetailPanel).show(self.entries[0] if self.entries else None)

    def on_option_list_option_highlighted(self, ev: OptionList.OptionHighlighted) -> None:
        if ev.option_list.id == "repos":
            self._show_entries(ev.option_index)
        elif ev.option_list.id == "entries":
            self.query_one(DetailPanel).show(self.entries[ev.option_index])
