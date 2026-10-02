"""Three-column read-only overview: Repos -> Worktrees/Branches -> Details."""
from __future__ import annotations

import time
from functools import partial
from pathlib import Path
from typing import ClassVar

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, OptionList, Static

from kvasir import notes
from kvasir.config import RepoConfig, load_local, load_repos
from kvasir.new_worktree import is_bare_layout
from kvasir.open_terminal import OpenTerminalError, open_terminal
from kvasir.sync import fetch, pull
from kvasir.tui.columns import DetailPanel, EntryList, RepoList
from kvasir.tui.data import RepoRow, load_rows
from kvasir.tui.layout import group_entries, tilde
from kvasir.tui.new_worktree_screen import NewWorktreeScreen
from kvasir.tui.note_screen import NoteScreen
from kvasir.worktrees import Worktree


class KvasirApp(App):
    CSS = """
    Horizontal { height: 1fr; }
    #pathbar { height: 1; padding: 0 1; color: $text-muted; }
    .col { height: 1fr; }
    #repos-col { width: 1fr; min-width: 30; max-width: 40; }
    #entries-col { width: 4fr; min-width: 10; border-left: solid $primary; }
    #detail-col { width: 2fr; min-width: 8; border-left: solid $primary; }
    .narrow #detail-col { display: none; }
    .narrow #repos-col { min-width: 10; }
    .colhead { height: 1; padding: 0 1; text-style: bold; background: $boost; }
    RepoList, EntryList { height: 1fr; padding: 0 1; }
    DetailPanel { height: 1fr; padding: 0 1; }
    """
    BINDINGS: ClassVar[list[Binding]] = [
        Binding("q", "quit", "Quit"),
        Binding("r", "reload", "Reload"),
        Binding("n", "new_worktree", "New worktree"),
        Binding("f", "fetch_all", "Fetch"),
        Binding("p", "pull", "Pull"),
        Binding("x", "remove_worktree", "Remove"),
        Binding("m", "note", "Note"),
        Binding("b", "toggle_remote", "Remote branches"),
        Binding("h", "focus_previous", "Left", show=False),
        Binding("l", "focus_next", "Right", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[RepoRow] = []
        self.entries: list = []  # visible entries, flat, without headings
        self.show_remote = False  # Remote-Branches collapsed by default; survives reloads
        self._mark: tuple[str, Path] | None = None  # (repo url, new worktree path) to highlight after reload
        self.sync: dict[str, tuple[float | None, str | None]] = {}  # url -> (last fetch ts, error)

    def compose(self) -> ComposeResult:
        yield Static("", id="pathbar")
        with Horizontal():
            with Vertical(id="repos-col", classes="col"):
                yield Static("Repos", classes="colhead")
                yield RepoList(id="repos")
            with Vertical(id="entries-col", classes="col"):
                yield Static("Worktrees & Branches", classes="colhead")
                yield EntryList(id="entries")
            with Vertical(id="detail-col", classes="col"):
                yield Static("Details", classes="colhead")
                yield DetailPanel(id="detail")
        yield Footer()

    def on_resize(self) -> None:
        self.set_class(self.size.width < 80, "narrow")  # no room for the Details column

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
        i = self.query_one(EntryList).current_entry()
        wt = self.entries[i] if i is not None else None
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
        keep_repo, keep_entry = repos.highlighted or 0, entries.current_entry() or 0  # survive reloads
        keep_repo = keep_repo if keep_repo < len(rows) else 0
        if self._mark:  # a new worktree was just created: jump to it
            keep_repo = next((i for i, r in enumerate(rows) if r.url == self._mark[0]), keep_repo)
        repos.set_rows(rows, self.sync)
        if rows:
            with repos.prevent(OptionList.OptionHighlighted):
                repos.highlighted = keep_repo
        self._show_entries(keep_repo if rows else None, keep_entry)
        self._mark = None

    def action_remove_worktree(self) -> None:
        from kvasir.tui.remove_screen import RemoveScreen
        from kvasir.worktrees import Worktree

        ri, ei = self.query_one(RepoList).highlighted, self.query_one(EntryList).current_entry()
        if ri is None or ei is None or not self.rows[ri].path:
            return
        wt = self.entries[ei]
        if isinstance(wt, Worktree):
            self.push_screen(RemoveScreen(self.rows[ri].path, wt, self.rows[ri].url), lambda changed: changed and self.action_reload())

    def _show_entries(self, idx: int | None, keep: int = 0) -> None:
        row = self.rows[idx] if idx is not None and idx < len(self.rows) else None
        groups = group_entries(row.view, self.show_remote) if row and row.view else []
        self.entries = [e for g in groups for e in g.visible]
        self.query_one("#pathbar", Static).update(tilde(row.path) if row and row.path else "")
        if self.entries:
            keep = keep if keep < len(self.entries) else 0
            if self._mark:
                keep = next((i for i, e in enumerate(self.entries)
                             if getattr(e, "path", None) == self._mark[1]), keep)
        self.query_one(EntryList).set_entries(groups, notes.latest_by_branch(row.url) if row else {}, keep)
        self._show_detail(self.entries[keep] if self.entries else None)

    def _show_detail(self, item) -> None:
        ri = self.query_one(RepoList).highlighted
        url = self.rows[ri].url if ri is not None and ri < len(self.rows) else ""
        name = getattr(item, "branch", None) or getattr(item, "name", None)
        self.query_one(DetailPanel).show(item, notes.latest(url, name) if name else None)

    def action_toggle_remote(self) -> None:
        self.show_remote = not self.show_remote
        self._show_entries(self.query_one(RepoList).highlighted, self.query_one(EntryList).current_entry() or 0)

    def action_note(self) -> None:
        ri, ei = self.query_one(RepoList).highlighted, self.query_one(EntryList).current_entry()
        if ri is None or ei is None:
            return
        url, item = self.rows[ri].url, self.entries[ei]
        name = getattr(item, "branch", None) or getattr(item, "name", None)
        if not name:
            return self.notify("no branch to note", severity="warning")
        old = notes.latest(url, name)

        def done(text: str | None) -> None:
            if text:
                notes.add(url, name, text)
                self._show_entries(ri, ei)

        self.push_screen(NoteScreen(name, old["text"] if old else ""), done)

    def action_new_worktree(self) -> None:
        idx = self.query_one(RepoList).highlighted
        row = self.rows[idx] if idx is not None and idx < len(self.rows) else None
        if row is None or row.path is None or row.view is None:
            return self.notify("Select a readable repo first", severity="error")
        if not is_bare_layout(row.path):
            return self.notify("Worktrees need the Bare-Layout (.bare/); this is a normal clone", severity="error")
        patterns = load_repos().get(row.url, RepoConfig()).branch_patterns

        def done(path: Path | None) -> None:
            if path:
                self._mark = (row.url, path)
                self.action_reload()

        self.push_screen(NewWorktreeScreen(row.path, patterns, row.view.branches), done)

    def on_option_list_option_highlighted(self, ev: OptionList.OptionHighlighted) -> None:
        if ev.option_list.id == "repos":
            self._show_entries(ev.option_index)
        elif ev.option_list.id == "entries":
            i = ev.option_list.index_map[ev.option_index]
            if i is not None:
                self._show_detail(self.entries[i])

    def on_option_list_option_selected(self, ev: OptionList.OptionSelected) -> None:
        """Enter on an entry: open a terminal in the Worktree."""
        if ev.option_list.id != "entries":
            return
        i = ev.option_list.index_map[ev.option_index]
        if i is None:
            return
        entry = self.entries[i]
        if not isinstance(entry, Worktree) or entry.broken:
            self.notify("Kein Worktree: neuen Worktree anlegen (n).", severity="warning")
            return
        try:
            open_terminal(entry.path, load_local().open_command)
        except OpenTerminalError as e:
            self.copy_to_clipboard(str(entry.path))
            self.notify(f"{e}\nPfad in Zwischenablage: {entry.path}", severity="error", timeout=15)
