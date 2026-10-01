"""Three-column read-only overview: Repos -> Worktrees/Branches -> Details."""
from __future__ import annotations

import time
from functools import partial
from pathlib import Path
from typing import ClassVar

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Footer, OptionList

from kvasir.config import load_local, load_repos
from kvasir.open_terminal import OpenTerminalError, open_terminal
from kvasir.sync import fetch, pull
from kvasir.tui.columns import DetailPanel, EntryList, RepoList
from kvasir.tui.data import RepoRow, load_rows
from kvasir.worktrees import Worktree


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
        Binding("f", "fetch_all", "Fetch"),
        Binding("p", "pull", "Pull"),
        Binding("x", "remove_worktree", "Remove"),
        Binding("h", "focus_previous", "Left", show=False),
        Binding("l", "focus_next", "Right", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[RepoRow] = []
        self.entries: list = []
        self.sync: dict[str, tuple[float | None, str | None]] = {}  # url -> (last fetch ts, error)

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield RepoList(id="repos")
            yield EntryList(id="entries")
            yield DetailPanel(id="detail")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one(RepoList).focus()
        self.action_reload()
        paths = load_local().paths
        for url, cfg in load_repos().items():  # timers live only as long as the TUI
            if url in paths:
                self.set_interval(max(1, cfg.fetch_interval) * 60, partial(self._fetch_repo, url, Path(paths[url])))

    def action_fetch_all(self) -> None:
        paths = load_local().paths
        for row in self.rows:
            if row.url in paths:
                self._fetch_repo(row.url, Path(paths[row.url]))
        self.notify("fetching ...")

    @work(thread=True, group="fetch")
    def _fetch_repo(self, url: str, root: Path) -> None:
        err = fetch(root)
        self.call_from_thread(self._fetched, url, err)

    def _fetched(self, url: str, err: str | None) -> None:
        prev_ts = self.sync.get(url, (None, None))[0]
        self.sync[url] = (prev_ts if err else time.time(), err)
        self.action_reload()  # ahead/behind and branches change after a fetch

    def action_pull(self) -> None:
        i = self.query_one(EntryList).highlighted
        wt = self.entries[i] if i is not None and i < len(self.entries) else None
        if not isinstance(wt, Worktree) or wt.broken:
            self.notify("select a worktree to pull", severity="warning")
            return
        self._pull(wt.path)

    @work(thread=True, group="pull")
    def _pull(self, path: Path) -> None:
        ok, msg = pull(path)
        self.call_from_thread(self.notify, msg, severity="information" if ok else "warning")
        if ok:
            self.call_from_thread(self.action_reload)

    def action_reload(self) -> None:
        self._load()

    @work(thread=True, exclusive=True)
    def _load(self) -> None:
        rows = load_rows()  # git calls: keep off the UI thread
        self.call_from_thread(self._loaded, rows)

    def _loaded(self, rows: list[RepoRow]) -> None:
        self.rows = rows
        repos, entries = self.query_one(RepoList), self.query_one(EntryList)
        keep_repo, keep_entry = repos.highlighted or 0, entries.highlighted or 0  # survive reloads
        keep_repo = keep_repo if keep_repo < len(rows) else 0
        repos.set_rows(rows, self.sync)
        if rows:
            with repos.prevent(OptionList.OptionHighlighted):
                repos.highlighted = keep_repo
        self._show_entries(keep_repo if rows else None, keep_entry)

    def action_remove_worktree(self) -> None:
        from kvasir.tui.remove_screen import RemoveScreen
        from kvasir.worktrees import Worktree

        ri, ei = self.query_one(RepoList).highlighted, self.query_one(EntryList).highlighted
        if ri is None or ei is None or ei >= len(self.entries) or not self.rows[ri].path:
            return
        wt = self.entries[ei]
        if isinstance(wt, Worktree):
            self.push_screen(RemoveScreen(self.rows[ri].path, wt), lambda changed: changed and self.action_reload())

    def _show_entries(self, idx: int | None, keep: int = 0) -> None:
        row = self.rows[idx] if idx is not None and idx < len(self.rows) else None
        self.entries = [*row.view.worktrees, *row.view.branches] if row and row.view else []
        lst = self.query_one(EntryList)
        lst.set_entries(self.entries)
        if self.entries:
            keep = keep if keep < len(self.entries) else 0
            with lst.prevent(OptionList.OptionHighlighted):
                lst.highlighted = keep
        self.query_one(DetailPanel).show(self.entries[keep] if self.entries else None)

    def on_option_list_option_highlighted(self, ev: OptionList.OptionHighlighted) -> None:
        if ev.option_list.id == "repos":
            self._show_entries(ev.option_index)
        elif ev.option_list.id == "entries":
            self.query_one(DetailPanel).show(self.entries[ev.option_index])

    def on_option_list_option_selected(self, ev: OptionList.OptionSelected) -> None:
        """Enter on an entry: open a terminal in the Worktree."""
        if ev.option_list.id != "entries":
            return
        entry = self.entries[ev.option_index]
        if not isinstance(entry, Worktree) or entry.broken:
            self.notify("Kein Worktree: neuen Worktree anlegen (n).", severity="warning")
            return
        try:
            open_terminal(entry.path, load_local().open_command)
        except OpenTerminalError as e:
            self.copy_to_clipboard(str(entry.path))
            self.notify(f"{e}\nPfad in Zwischenablage: {entry.path}", severity="error", timeout=15)
