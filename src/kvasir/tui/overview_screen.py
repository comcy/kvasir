"""Overview page (key `i`): my PRs, review requests, my pipeline runs over all registered GitHub Repos.

Dismisses with (repo row, entry index) when `c` jumps to a local Branch, else None. Read-only.
"""
from __future__ import annotations

import webbrowser
from typing import ClassVar

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Footer, OptionList, Static
from textual.widgets.option_list import Option

from kvasir.config import RepoConfig, load_repos
from kvasir.platform import Error
from kvasir.tui import overview_data as od
from kvasir.tui.data import RepoRow


class OverviewScreen(Screen["tuple[int, int] | None"]):
    DEFAULT_CSS = """
    OverviewScreen #ov-status { height: 1; padding: 0 1; color: $text-muted; }
    OverviewScreen OptionList { height: 1fr; padding: 0 1; }
    """
    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "back", "Back"),
        Binding("u", "refresh", "Refresh"),
        Binding("c", "jump", "Go to branch"),
    ]

    def __init__(self, rows: list[RepoRow]) -> None:
        super().__init__()
        self.rows = rows
        self.urls = [r.url for r in rows]
        self.repos = od.github_repos(self.urls)
        self.entries: list[od.Entry] = []
        self.error: Error | None = None
        self.busy = False

    def compose(self) -> ComposeResult:
        yield Static("", id="ov-status")
        yield OptionList(id="ov-list")
        yield Footer()

    def on_mount(self) -> None:
        cfgs = load_repos()
        minutes = min((max(1, cfgs.get(u, RepoConfig()).platform_interval) for u in self.repos.values()), default=10)
        self.query_one(OptionList).focus()
        self._draw()
        if od.is_stale(od.snapshot(self.urls), minutes):
            self.action_refresh()
        self.set_interval(minutes * 60, self.action_refresh)
        self.set_interval(30, self._draw)  # "aktualisiert vor ..." keeps ticking

    def on_resize(self) -> None:
        self._draw()

    def _draw(self) -> None:
        ov = od.snapshot(self.urls, self.error)
        status = od.status_text(ov, len(self.repos)) + ("  (lädt ...)" if self.busy else "")
        self.query_one("#ov-status", Static).update(status)
        lst = self.query_one(OptionList)
        keep = lst.highlighted
        self.entries = []
        lst.clear_options()
        for title, items in od.sections(ov, max(20, lst.scrollable_content_region.width - 2)):
            lst.add_option(Option(Text(f"{title} ({len(items)})", style="bold"), disabled=True))
            for e in items:
                lst.add_option(Option(Text(e.text, no_wrap=True, overflow="ellipsis"), id=str(len(self.entries))))
                self.entries.append(e)
            if not items:
                lst.add_option(Option(Text("  keine", style="dim"), disabled=True))
        if keep is not None and keep < lst.option_count:
            lst.highlighted = keep
        elif self.entries:
            lst.highlighted = next(i for i in range(lst.option_count) if not lst.get_option_at_index(i).disabled)

    def _current(self) -> od.Entry | None:
        lst = self.query_one(OptionList)
        h = lst.highlighted
        if h is None:
            return None
        oid = lst.get_option_at_index(h).id
        return self.entries[int(oid)] if oid is not None else None

    def action_back(self) -> None:
        self.dismiss(None)

    def action_refresh(self) -> None:
        if self.busy or not self.repos:
            return
        self.busy = True
        self._fetch()
        self._draw()

    @work(thread=True, group="overview")
    def _fetch(self) -> None:
        err = od.refresh(self.urls)  # network: never on the UI thread
        self.app.call_from_thread(self._fetched, err)

    def _fetched(self, err: Error | None) -> None:
        self.busy = False
        self.error = err
        if self.is_attached:
            self._draw()

    def on_option_list_option_selected(self, ev: OptionList.OptionSelected) -> None:
        if (e := self._current()) is not None:
            webbrowser.open(e.url)

    def action_jump(self) -> None:
        e = self._current()
        if e is None:
            return
        url = self.repos.get(e.repo.lower())
        found = od.find_local(self.rows, url, e.branch) if url else None
        if found is None:
            self.notify("Branch nicht lokal vorhanden", severity="warning")
            return
        self.dismiss(found)
