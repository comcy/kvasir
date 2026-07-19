"""DevTrack TUI – main Textual application."""
from __future__ import annotations

import shlex
import subprocess
from datetime import date

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import Footer, Header, Input, ListItem, ListView, RichLog, Static, TabbedContent, TabPane

from src.workspace.manager import WorkspaceManager, WorkspaceError
from src.tui.themes import THEMES, THEME_NAMES
from src.tui.widgets.todo_panel import TodoPanel
from src.tui.widgets.metric_panel import MetricPanel
from src.tui.widgets.commit_panel import CommitPanel
from src.tui.widgets.session_panel import SessionPanel
from src.tui.widgets.todo_manager import TodoManager
from src.tui.widgets.notes_panel import NotesPanel
from src.tui.widgets.search_panel import SearchPanel
from src.tui.widgets.quick_capture import QuickCaptureBar
from src.tui.widgets.projects_manager import ProjectsManager
from src.tui.screens.morning_wizard import MorningWizardScreen
from src.tui.screens.agent_settings import AgentSettingsScreen

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
ListView:focus > ListItem.--highlight { background: $primary 20%; }

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


_CMD_SUGGESTIONS = [
    "todo add \"Task text\"",
    "todo add \"Task text\" --due 2026-07-01 --tags dev",
    "todo list",
    "todo list --status done",
    "todo list --status all --tag dev",
    "todo done <id>",
    "todo delete <id>",
    "note export <note.md>",
    "note export <note.md> --pdf",
    "note extract-todos <note.md>",
    "note extract-todos <note.md> --dry-run",
    "metric show",
    "metric record <name> <value>",
    "metric define <name> --label \"Label\" --type counter --agg daily",
    "workspace list",
    "workspace create <name>",
    "workspace use <name>",
    "project list",
    "project add <name>",
    "project clone <url>",
    "wt list",
    "wt add <branch>",
    "wt remove <folder>",
    "wt pull",
    "wt push",
    "wt status",
    "wt log",
    "today",
    "summary",
    "hooks install-hooks",
    "agent show",
    "agent set --provider cli --cli-command \"claude -p\"",
    "agent set --provider anthropic --model claude-sonnet-5",
    "agent set --provider none",
    "commit -g",
]


class _SuggestionItem(ListItem):
    def __init__(self, cmd: str) -> None:
        super().__init__()
        self._cmd = cmd

    def compose(self) -> ComposeResult:
        yield Static(f"  [dim]›[/dim]  {self._cmd}")


class CommandBarScreen(ModalScreen[None]):
    """Quick command bar with auto-suggestions."""

    DEFAULT_CSS = """
    CommandBarScreen { align: center middle; }
    #cmd-dialog {
        width: 90; height: 30;
        background: $surface; border: round $secondary; padding: 1 2;
    }
    #cmd-title { color: $secondary; text-style: bold; margin-bottom: 1; }
    #cmd-suggestions {
        height: auto; max-height: 10;
        border: solid $panel; margin-bottom: 1;
        background: $background;
    }
    #cmd-suggestions ListItem  { background: transparent; padding: 0 1; }
    #cmd-suggestions ListItem:hover { background: $surface; }
    #cmd-suggestions ListView:focus > ListItem.--highlight { background: $primary 20%; }
    #cmd-output { height: 1fr; border: solid $panel; margin: 1 0; padding: 0 1; }
    #cmd-hint { color: $foreground 40%; }
    """

    BINDINGS = [("escape", "dismiss", "Close")]

    def compose(self) -> ComposeResult:
        with Vertical(id="cmd-dialog"):
            yield Static("  mimirlink — command bar", id="cmd-title")
            yield Input(
                placeholder="type a command or pick a suggestion below…",
                id="cmd-input",
            )
            yield ListView(*[_SuggestionItem(c) for c in _CMD_SUGGESTIONS], id="cmd-suggestions")
            yield RichLog(id="cmd-output", markup=True, highlight=False)
            yield Static(
                "  [dim]Enter: run  ·  ↑↓ or Tab: suggestions  ·  Escape: close[/dim]",
                id="cmd-hint",
            )

    def on_mount(self) -> None:
        self.query_one("#cmd-input", Input).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        q = event.value.strip().lower()
        lv = self.query_one("#cmd-suggestions", ListView)
        lv.clear()
        matches = [c for c in _CMD_SUGGESTIONS if not q or q in c.lower()]
        for cmd in matches:
            lv.append(_SuggestionItem(cmd))

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if isinstance(event.item, _SuggestionItem):
            inp = self.query_one("#cmd-input", Input)
            inp.value = event.item._cmd
            inp.cursor_position = len(inp.value)
            inp.focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        cmd_str = event.value.strip()
        if not cmd_str:
            return
        log = self.query_one("#cmd-output", RichLog)
        log.write(f"[dim]$ mimirlink {cmd_str}[/dim]")
        try:
            result = subprocess.run(
                ["mimirlink"] + shlex.split(cmd_str),
                capture_output=True, text=True, timeout=30,
            )
            if result.stdout:
                log.write(result.stdout.rstrip())
            if result.stderr:
                log.write(f"[yellow]{result.stderr.rstrip()}[/yellow]")
            if result.returncode != 0 and not result.stdout and not result.stderr:
                log.write(f"[red]Exit code: {result.returncode}[/red]")
        except FileNotFoundError:
            log.write("[red]mimirlink not found in PATH[/red]")
        except subprocess.TimeoutExpired:
            log.write("[red]Command timed out after 30s[/red]")
        except Exception as exc:
            log.write(f"[red]{exc}[/red]")
        self.query_one("#cmd-input", Input).clear()


class DevTrackApp(App):
    TITLE = "mimirlink"
    CSS = APP_CSS
    # mimirlink has its own Command Bar (ctrl+p, see CommandBarScreen below) —
    # Textual's built-in command palette shares the same key by default and
    # would show up as a second, redundant "ctrl+p" entry in the footer.
    ENABLE_COMMAND_PALETTE = False

    BINDINGS = [
        Binding("q",      "quit",              "Quit",        priority=True),
        Binding("t",      "next_theme",         "Theme"),
        Binding("r",      "reload_dashboard",   "Reload"),
        Binding("m",      "morning_routine",    "Morning"),
        Binding("ctrl+g", "agent_settings",     "Agent"),
        Binding("1",      "switch_tab('tab-dashboard')", "Dashboard"),
        Binding("2",      "switch_tab('tab-todos')",     "TODOs"),
        Binding("3",      "switch_tab('tab-notes')",     "Notes"),
        Binding("4",      "switch_tab('tab-search')",    "Search"),
        Binding("5",      "switch_tab('tab-projects')",  "Projects"),
        Binding("/",      "open_search",        "Search",     show=False),
        Binding("ctrl+p", "command_bar",        "Command bar", priority=True),
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
            f"  ·  [dim]1-5=tabs  t=theme  /=search  m=morning  ctrl+g=agent  ctrl+p=cmd  q=quit[/dim]",
            id="workspace-bar",
        )

        # Empty panels are skipped entirely (not just shown with a hint) so
        # a fresh workspace doesn't waste half the screen on "nothing yet"
        # columns — the remaining panels' 1fr/2fr CSS widths fill the gap
        # automatically since they're relative to however many siblings
        # Horizontal/Vertical actually end up with.
        show_todos = bool(todos)
        show_metrics = MetricPanel.has_content(metrics, sessions, commits)
        show_commits = bool(commits)
        show_sessions = SessionPanel.has_content(self._wm)

        with TabbedContent(id="tabs", initial="tab-dashboard"):
            # ── 1 – Dashboard ─────────────────────────────────────────────────
            with TabPane("Dashboard [dim][1][/dim]", id="tab-dashboard"):
                yield QuickCaptureBar(self._wm)
                if not any((show_todos, show_metrics, show_commits, show_sessions)):
                    yield Static(
                        "  [dim]Nothing to show yet — add a project, a todo, "
                        "or make a commit to get started.[/dim]",
                        classes="empty-hint",
                    )
                else:
                    with Horizontal(id="dash-layout"):
                        if show_todos:
                            with Vertical(id="dash-left"):
                                yield Static("  ○ TODOs", classes="col-header")
                                yield TodoPanel(self._wm)
                        if show_metrics or show_commits:
                            with Vertical(id="dash-center"):
                                if show_metrics:
                                    with Vertical(id="center-top"):
                                        yield Static("  ◈ Metrics", classes="col-header")
                                        yield MetricPanel(metrics, mv, sessions, commits)
                                if show_commits:
                                    with Vertical(id="center-bottom"):
                                        yield Static("  ⎇ Commits", classes="col-header")
                                        yield CommitPanel(commits)
                        if show_sessions:
                            with Vertical(id="dash-right"):
                                yield Static("  ⏱ Sessions / WIP", classes="col-header")
                                yield SessionPanel(self._wm)

            # ── 2 – TODOs ─────────────────────────────────────────────────────
            with TabPane("TODOs [dim][2][/dim]", id="tab-todos"):
                yield TodoManager(self._wm)

            # ── 3 – Notes ─────────────────────────────────────────────────────
            with TabPane("Notes [dim][3][/dim]", id="tab-notes"):
                yield NotesPanel(self._wm)

            # ── 4 – Search ────────────────────────────────────────────────────
            with TabPane("Search [dim][4][/dim]", id="tab-search"):
                yield SearchPanel(self._wm)

            # ── 5 – Projects ──────────────────────────────────────────────────
            with TabPane("Projects [dim][5][/dim]", id="tab-projects"):
                yield ProjectsManager(self._wm)

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
        elif tab_id == "tab-dashboard":
            try:
                self.call_after_refresh(
                    lambda: self.query_one(QuickCaptureBar).focus_input()
                )
            except Exception:
                pass
        elif tab_id == "tab-notes":
            try:
                self.call_after_refresh(
                    lambda: self.query_one("#notes-lv", ListView).focus()
                )
            except Exception:
                pass
        elif tab_id == "tab-todos":
            try:
                self.call_after_refresh(
                    lambda: self.query_one("#lv", ListView).focus()
                )
            except Exception:
                pass
        elif tab_id == "tab-projects":
            try:
                self.call_after_refresh(
                    lambda: self.query_one("#pm-lv", ListView).focus()
                )
            except Exception:
                pass

    def on_search_panel_item_activated(self, event) -> None:
        from pathlib import Path
        from src.tui.widgets.search_panel import SearchPanel
        result = event.result
        action = event.action  # "navigate" | "edit"

        if result.get("kind") == "todo":
            todo_id  = result.get("_id", "")
            todo     = result.get("_todo", {})
            tags     = result.get("_tags", [])
            self.action_switch_tab("tab-todos")
            if action == "edit":
                self.call_after_refresh(
                    lambda: self.query_one(TodoManager).edit_todo_direct(todo, tags)
                )
            else:
                self.call_after_refresh(
                    lambda: self.query_one(TodoManager).navigate_to(todo_id)
                )

        elif result.get("kind") == "note":
            path = Path(result["path"])
            self.action_switch_tab("tab-notes")
            if action == "edit":
                self.call_after_refresh(
                    lambda: self.query_one(NotesPanel).open_note(path)
                )
            else:
                self.call_after_refresh(
                    lambda: self.query_one(NotesPanel).navigate_to(path)
                )

    def on_quick_capture_bar_captured(self, event: QuickCaptureBar.Captured) -> None:
        try:
            self.query_one(NotesPanel).refresh(recompose=True)
        except Exception:
            pass
        try:
            self.query_one(TodoPanel).reload()
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

    def action_command_bar(self) -> None:
        self.push_screen(CommandBarScreen())

    def action_agent_settings(self) -> None:
        def cb(cfg) -> None:
            if cfg is not None:
                self.notify(f"Agent provider: {cfg.provider}", timeout=2)

        self.push_screen(AgentSettingsScreen(self._wm), cb)

    def action_morning_routine(self) -> None:
        try:
            self._wm.active()
        except WorkspaceError:
            self.notify("No active workspace.", severity="error")
            return

        def cb(_: None) -> None:
            try:
                self.query_one(TodoPanel).reload()
            except Exception:
                pass
            try:
                self.query_one(NotesPanel).refresh(recompose=True)
            except Exception:
                pass

        self.push_screen(MorningWizardScreen(self._wm), cb)

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
            f"  ·  [dim]1-5=tabs  t=theme  /=search  m=morning  ctrl+p=cmd  q=quit[/dim]"
        )
