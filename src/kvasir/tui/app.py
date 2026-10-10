"""Three-column read-only overview: Repos -> Worktrees/Branches -> Details."""
from __future__ import annotations

import time
from functools import partial
from pathlib import Path
from typing import ClassVar

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.timer import Timer
from textual.widgets import Footer, OptionList, Static

from kvasir import daylog, notes
from kvasir.config import RepoConfig, load_local, load_repos
from kvasir.new_worktree import is_bare_layout
from kvasir.open_terminal import OpenTerminalError, open_terminal
from kvasir.platform import Error
from kvasir.repo_file import patterns_for
from kvasir.sync import fetch, pull
from kvasir.tui import platform_data, platform_view
from kvasir.tui.columns import DetailPanel, EntryList, RepoList
from kvasir.tui.data import RepoRow, load_rows
from kvasir.tui.layout import data_status, group_entries, header_text, short_name, tilde
from kvasir.tui.new_worktree_screen import NewWorktreeScreen
from kvasir.tui.note_screen import NoteScreen
from kvasir.worktrees import Worktree


class KvasirApp(App):
    CSS = """
    Horizontal { height: 1fr; }
    #header { height: 1; padding: 0 1; color: $text-muted; text-style: bold; }
    .col { height: 1fr; border: round $primary-darken-2; border-title-color: $text-muted; }
    .col:focus-within { border: round $accent; border-title-color: $accent; border-title-style: bold; }
    #repos-col { width: 1fr; min-width: 30; max-width: 42; }
    #entries-col { width: 4fr; min-width: 10; }
    #detail-col { width: 2fr; min-width: 8; }
    .narrow #detail-col { display: none; }
    .narrow #repos-col { min-width: 10; }
    RepoList, EntryList { height: 1fr; padding: 0 1; border: none; }
    DetailPanel { height: auto; padding: 0 1; }
    """
    BINDINGS: ClassVar[list[Binding]] = [
        Binding("q", "quit", "Quit"),
        Binding("r", "reload", "Reload"),
        Binding("n", "new_worktree", "New"),
        Binding("f", "fetch_all", "Fetch"),
        Binding("p", "pull", "Pull"),
        Binding("x", "remove_worktree", "Remove"),
        Binding("m", "note", "Note"),
        Binding("b", "toggle_remote", "Remote"),
        Binding("u", "refresh_platform", "Plattform"),
        Binding("i", "overview", "Overview"),
        Binding("e", "edit_repo", "Edit"),
        Binding("a", "ask", "Ask"),
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
        self.platform: dict[str, platform_data.Snapshot] = {}  # url -> cached platform data (only detected repos)
        self._platform_error: dict[str, Error | None] = {}
        self._platform_busy: set[str] = set()
        self._platform_started = False
        self._intervals: dict[tuple[str, str], Timer] = {}  # ("fetch"|"gh", url) -> interval timer, replaceable

    def compose(self) -> ComposeResult:
        yield Static("", id="header")
        with Horizontal():
            with Vertical(id="repos-col", classes="col"):
                yield RepoList(id="repos")
            with Vertical(id="entries-col", classes="col"):
                yield EntryList(id="entries")
            with VerticalScroll(id="detail-col", classes="col"):  # focusable: arrows/PgUp/PgDn scroll the stepper
                yield DetailPanel(id="detail")
        yield Footer(show_command_palette=False)  # the palette hint would cut the key labels at 100 columns

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        """Pages on top (Overview) have their own keys; hide the main view's from their footer."""
        return len(self.screen_stack) == 1 or action in ("quit", "focus_previous", "focus_next")

    def on_resize(self) -> None:
        self.set_class(self.size.width < 80, "narrow")  # no room for the Details column
        self._update_header()

    def _update_header(self) -> None:
        ri = self.query_one(RepoList).highlighted
        row = self.rows[ri] if ri is not None and ri < len(self.rows) else None
        snap = self.platform.get(row.url) if row else None
        gh = snap.fetched_at.timestamp() if snap and snap.fetched_at else None
        status = data_status(self.sync.get(row.url, (None, None))[0], gh, cli=snap.cli if snap else "gh") if row else ""
        text = header_text(short_name(row.url) if row else "", tilde(row.path) if row and row.path else "",
                           status, max(1, self.size.width - 2))
        self.query_one("#header", Static).update(Text(text, no_wrap=True, overflow="ellipsis"))

    def on_mount(self) -> None:
        for col, title in (("repos", "Repos"), ("entries", "Worktrees & Branches"), ("detail", "Details")):
            self.query_one(f"#{col}-col").border_title = title
        self.query_one(RepoList).focus()
        self.set_interval(30, self._update_header)  # "vor 3m" keeps ticking
        self.action_reload()
        paths = load_local().paths
        for url, cfg in load_repos().items():  # timers live only as long as the TUI
            if url in paths:
                self._timer("fetch", url, cfg.fetch_interval, partial(self._fetch_repo, url, Path(paths[url])))

    def _timer(self, kind: str, url: str, minutes: int, callback) -> None:
        if old := self._intervals.pop((kind, url), None):
            old.stop()
        self._intervals[(kind, url)] = self.set_interval(max(1, minutes) * 60, callback)

    def action_edit_repo(self) -> None:
        from kvasir.tui.settings_screen import SettingsScreen

        ri = self.query_one(RepoList).highlighted
        row = self.rows[ri] if ri is not None and ri < len(self.rows) else None
        if row is None:
            return self.notify("Select a repo first", severity="warning")
        try:
            cfg = load_repos().get(row.url)
        except (OSError, ValueError) as e:  # unreadable/invalid repos.toml: hint instead of crash
            return self.notify(f"repos.toml not readable: {e}", severity="error")
        if cfg is None:
            return self.notify("Repo not registered in repos.toml", severity="error")

        def done(saved: RepoConfig | None) -> None:
            if saved is None:
                return
            paths = load_local().paths
            if row.url in paths:
                self._timer("fetch", row.url, saved.fetch_interval, partial(self._fetch_repo, row.url, Path(paths[row.url])))
            if platform_data.platform_of(row.url):
                self._timer("gh", row.url, saved.platform_interval, partial(self._refresh_platform_url, row.url))
            self.action_reload()  # config is read per use; reload redraws with the new templates

        self.push_screen(SettingsScreen(row.url, tilde(row.path) if row.path else "", cfg), done)

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

    def _start_platform(self) -> None:
        """First load done: one refresh per repo with a platform now, then per `platform_interval`."""
        self._platform_started = True
        cfgs = load_repos()
        for row in self.rows:
            if platform_data.platform_of(row.url):
                self._refresh_platform_url(row.url)
                minutes = max(1, cfgs.get(row.url, RepoConfig()).platform_interval)
                self._timer("gh", row.url, minutes, partial(self._refresh_platform_url, row.url))

    def action_refresh_platform(self) -> None:
        urls = [r.url for r in self.rows if platform_data.platform_of(r.url)]
        for url in urls:
            self._refresh_platform_url(url)
        self.notify("refreshing platform data ..." if urls else "no GitHub/Azure DevOps repo registered")

    def _refresh_platform_url(self, url: str) -> None:
        row = next((r for r in self.rows if r.url == url), None)
        if row is None or row.view is None or url in self._platform_busy:
            return
        self._platform_busy.add(url)
        patterns = patterns_for(url)
        self._refresh_platform(url, patterns, platform_data.branch_names(row.view))

    @work(thread=True, group="platform")
    def _refresh_platform(self, url: str, patterns: list[str], branches: list[str]) -> None:
        err = platform_data.refresh(url, patterns, branches)  # network: never on the UI thread
        self.call_from_thread(self._platform_done, url, err)

    def _platform_done(self, url: str, err: Error | None) -> None:
        self._platform_busy.discard(url)
        self._platform_error[url] = err
        self._apply_platform()

    def _apply_platform(self) -> None:
        """Rebuild the snapshots from the cache (no network) and redraw."""
        self._log_snapshot()
        for row in self.rows:
            if row.view and platform_data.platform_of(row.url):
                patterns = patterns_for(row.url)
                self.platform[row.url] = platform_data.snapshot(
                    row.url, patterns, platform_data.branch_names(row.view), self._platform_error.get(row.url))
        self.query_one(RepoList).set_platform(
            {u: (platform_view.repo_line(s), s.error is not None) for u, s in self.platform.items()})
        self._show_entries(self.query_one(RepoList).highlighted, self.query_one(EntryList).current_entry() or 0)

    def _log_snapshot(self) -> None:
        daylog.snapshot({r.url: r.view.worktrees for r in self.rows if r.view})

    def on_unmount(self) -> None:
        self._log_snapshot()

    def action_overview(self) -> None:
        from kvasir.tui.overview_screen import OverviewScreen

        def done(target: tuple[int, int] | None) -> None:
            if target:  # `c` in the overview: show that Branch here
                ri, ei = target
                with self.query_one(RepoList).prevent(OptionList.OptionHighlighted):
                    self.query_one(RepoList).highlighted = ri
                self._show_entries(ri, ei)
                self.query_one(EntryList).focus()

        self.push_screen(OverviewScreen(self.rows), done)

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
        self.query_one("#repos-col").border_title = f"Repos ({len(rows)})"
        if rows:
            with repos.prevent(OptionList.OptionHighlighted):
                repos.highlighted = keep_repo
        self._show_entries(keep_repo if rows else None, keep_entry)
        self._mark = None
        self._apply_platform()  # cache only
        if not self._platform_started and rows:
            self._start_platform()

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
        self._update_header()
        if self.entries:
            keep = keep if keep < len(self.entries) else 0
            if self._mark:
                keep = next((i for i, e in enumerate(self.entries)
                             if getattr(e, "path", None) == self._mark[1]), keep)
        snap = self.platform.get(row.url) if row else None
        marks = platform_view.markers(snap, self.entries) if snap else {}
        self.query_one(EntryList).set_entries(groups, notes.latest_by_branch(row.url) if row else {}, keep, marks)
        self._show_detail(self.entries[keep] if self.entries else None)

    def _show_detail(self, item) -> None:
        ri = self.query_one(RepoList).highlighted
        url = self.rows[ri].url if ri is not None and ri < len(self.rows) else ""
        name = getattr(item, "branch", None) or getattr(item, "name", None)
        snap, branch = self.platform.get(url), platform_data.branch_of(item) if item else None
        extra = platform_view.detail_text(snap.info(branch), snap.error, cli=snap.cli) if snap and branch else ""
        self.query_one(DetailPanel).show(item, notes.latest(url, name) if name else None, extra)

    def action_toggle_remote(self) -> None:
        self.show_remote = not self.show_remote
        self._show_entries(self.query_one(RepoList).highlighted, self.query_one(EntryList).current_entry() or 0)

    def action_ask(self) -> None:
        from kvasir.tui.prompt_screen import PromptScreen

        self.push_screen(PromptScreen())

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
        patterns = patterns_for(row.url)

        def done(path: Path | None) -> None:
            if path:
                daylog.record({"type": "worktree_created", "url": row.url,
                               "branch": path.relative_to(row.path).as_posix()})
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
