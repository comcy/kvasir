"""DevTrack TUI – main Textual application."""
from __future__ import annotations

from datetime import date

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import Footer, Header, Static, TabbedContent, TabPane

from devtrack.workspace.manager import WorkspaceManager, WorkspaceError
from devtrack.tui.themes import THEMES, THEME_NAMES
from devtrack.tui.widgets.todo_panel import TodoPanel
from devtrack.tui.widgets.metric_panel import MetricPanel
from devtrack.tui.widgets.commit_panel import CommitPanel
from devtrack.tui.widgets.session_panel import SessionPanel
from devtrack.tui.widgets.todo_manager import TodoManager
from devtrack.tui.widgets.notes_panel import NotesPanel
from devtrack.tui.widgets.search_panel import SearchPanel

APP_CSS = """
Screen { background: $background; }

Header {
    height: 3;
    background: $panel;
    color: $primary;
}

#workspace-bar {
    height: 1;
    background: $surface;
    padding: 0 2;
    color: $secondary;
    dock: top;
    margin-top: 3;
}

/* ── TabbedContent ── */
TabbedContent {
    height: 1fr;
    margin-top: 1;
}

/* ContentSwitcher defaults to height:auto — force it to fill remaining space */
ContentSwitcher {
    height: 1fr;
}

TabPane {
    padding: 0;
    height: 1fr;
}

/* ── Dashboard 3-col ── */
#dash-layout { height: 1fr; }

#dash-left  { width: 1fr;  height: 1fr; border: round $primary  50%; padding: 0 1; }
#dash-left:focus-within  { border: round $primary; }

#dash-center { width: 2fr; height: 1fr; border: round $secondary 50%; padding: 0 1; }
#dash-center:focus-within { border: round $secondary; }

#dash-right { width: 1fr;  height: 1fr; border: round $accent    50%; padding: 0 1; }
#dash-right:focus-within  { border: round $accent; }

.col-header {
    text-align: center; text-style: bold;
    color: $primary; background: $surface;
    padding: 0 1; margin-bottom: 1;
}
#dash-center .col-header { color: $secondary; }
#dash-right  .col-header { color: $accent; }

#center-top    { height: 1fr; border-bottom: solid $secondary 25%; }
#center-bottom { height: 1fr; }

/* ── Shared panel styles ── */
.panel-section-header { color: $foreground; text-style: bold; margin-top: 1; }

.todo-open      { color: $foreground; }
.todo-done      { color: $success;    text-style: dim; }
.todo-cancelled { color: $error;      text-style: dim strike; }

ListItem { background: transparent; padding: 0 1; }
ListItem:hover { background: $surface; }
ListView:focus > ListItem.--highlight { background: $surface; }

DataTable { height: auto; background: transparent; }
DataTable > .datatable--header { background: $surface; color: $primary; text-style: bold; }
DataTable > .datatable--even-row { background: $background; }
DataTable > .datatable--odd-row  { background: $surface 20%; }

.commit-row { margin: 0; padding: 0 1; }
.commit-row:hover { background: $surface; }

.session-active { padding: 0 1; margin-bottom: 1; }
.session-past   { padding: 0 1; color: $foreground 70%; }

.empty-hint { color: $foreground 50%; padding: 1 2; }

Footer { height: 1; background: $surface; color: $foreground 70%; }
"""


class DevTrackApp(App):
    TITLE = "devtrack"
    CSS = APP_CSS

    BINDINGS = [
        Binding("q",   "quit",              "Quit",      priority=True),
        Binding("t",   "next_theme",         "Theme"),
        Binding("r",   "reload_dashboard",   "Reload"),
        Binding("1",   "switch_tab('tab-dashboard')", "Dashboard"),
        Binding("2",   "switch_tab('tab-todos')",     "TODOs"),
        Binding("3",   "switch_tab('tab-notes')",     "Notes"),
        Binding("4",   "switch_tab('tab-search')",    "Search"),
        Binding("/",   "open_search",        "Search",   show=False),
    ]

    _theme_idx: reactive[int] = reactive(0)

    def __init__(self, theme_name: str = "dracula") -> None:
        super().__init__()
        self._wm = WorkspaceManager()
        self._initial_theme = theme_name
        for th in THEMES.values():
            self.register_theme(th)

    # ------------------------------------------------------------------ data

    def _load_dashboard(self):
        try:
            store = self._wm.store()
            return (
                store.all("todos"),
                store.all("metrics"),
                store.all("metric_values"),
                store.all("commits"),
                store.all("sessions"),
                self._wm.active().name,
            )
        except WorkspaceError:
            return [], [], [], [], [], "(no workspace)"

    # ---------------------------------------------------------------- compose

    def compose(self) -> ComposeResult:
        todos, metrics, mv, commits, sessions, ws = self._load_dashboard()
        today = date.today().isoformat()
        theme = THEME_NAMES[self._theme_idx % len(THEME_NAMES)]

        yield Header(show_clock=True)
        yield Static(
            f"  workspace: [bold]{ws}[/bold]  ·  {today}"
            f"  ·  theme: [italic]{theme}[/italic]"
            f"  ·  [dim]1-4=tabs  t=theme  /=search  q=quit[/dim]",
            id="workspace-bar",
        )

        with TabbedContent(id="tabs", initial="tab-dashboard"):
            # ── 1 – Dashboard ─────────────────────────────────────────────────
            with TabPane("Dashboard [dim][1][/dim]", id="tab-dashboard"):
                with Horizontal(id="dash-layout"):
                    with Vertical(id="dash-left"):
                        yield Static("  ○ TODOs",           classes="col-header")
                        yield TodoPanel(todos)
                    with Vertical(id="dash-center"):
                        with Vertical(id="center-top"):
                            yield Static("  ◈ Metrics",     classes="col-header")
                            yield MetricPanel(metrics, mv)
                        with Vertical(id="center-bottom"):
                            yield Static("  ⎇ Commits",     classes="col-header")
                            yield CommitPanel(commits)
                    with Vertical(id="dash-right"):
                        yield Static("  ⏱ Sessions / WIP",  classes="col-header")
                        yield SessionPanel(sessions)

            # ── 2 – TODOs ─────────────────────────────────────────────────────
            with TabPane("TODOs [dim][2][/dim]", id="tab-todos"):
                yield TodoManager(self._wm)

            # ── 3 – Notes ─────────────────────────────────────────────────────
            with TabPane("Notes [dim][3][/dim]", id="tab-notes"):
                yield NotesPanel(self._wm)

            # ── 4 – Search ────────────────────────────────────────────────────
            with TabPane("Search [dim][4][/dim]", id="tab-search"):
                yield SearchPanel(self._wm)

        yield Footer()

    # ----------------------------------------------------------------- lifecycle

    def on_mount(self) -> None:
        idx = THEME_NAMES.index(self._initial_theme) if self._initial_theme in THEME_NAMES else 0
        self._theme_idx = idx
        self.theme = THEME_NAMES[idx]
        # initial= on TabbedContent has no effect in context-manager compose mode
        self.call_after_refresh(lambda: setattr(
            self.query_one("#tabs", TabbedContent), "active", "tab-dashboard"
        ))

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        # Only focus widgets — never call action_switch_tab here (would override initial tab)
        tab_id = event.tab.id if event.tab else ""
        if tab_id == "tab-search":
            try:
                from textual.widgets import Input
                self.call_after_refresh(lambda: self.query_one("#search-box", Input).focus())
            except Exception:
                pass

    # ----------------------------------------------------------------- actions

    def action_switch_tab(self, tab_id: str) -> None:
        self.query_one("#tabs", TabbedContent).active = tab_id

    def action_open_search(self) -> None:
        self.action_switch_tab("tab-search")
        try:
            from textual.widgets import Input
            self.call_after_refresh(lambda: self.query_one("#search-box", Input).focus())
        except Exception:
            pass

    def action_next_theme(self) -> None:
        self._theme_idx = (self._theme_idx + 1) % len(THEME_NAMES)
        name = THEME_NAMES[self._theme_idx]
        self.theme = name
        self._update_bar()
        self.notify(f"Theme: {name}", timeout=1.5)

    def action_reload_dashboard(self) -> None:
        self.refresh(recompose=True)
        self.notify("Reloaded", timeout=1.0)

    def _update_bar(self) -> None:
        try:
            ws = self._wm.active().name
        except WorkspaceError:
            ws = "(no workspace)"
        today = date.today().isoformat()
        theme = THEME_NAMES[self._theme_idx % len(THEME_NAMES)]
        self.query_one("#workspace-bar", Static).update(
            f"  workspace: [bold]{ws}[/bold]  ·  {today}"
            f"  ·  theme: [italic]{theme}[/italic]"
            f"  ·  [dim]1-4=tabs  t=theme  /=search  q=quit[/dim]"
        )
