"""Full Projects/Worktrees manager: register/clone, add/remove worktrees,
drop into a shell, fetch — the interactive counterpart to the passive
SessionPanel dashboard widget (same split as TodoPanel vs TodoManager)."""
from __future__ import annotations

import os
import subprocess
from datetime import datetime
from pathlib import Path

from textual import work
from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.widget import Widget
from textual.widgets import Label, ListItem, ListView, Static

from src.data.projects import (
    fetch_project,
    git_log_text,
    git_status_text,
    list_worktrees,
    pull_project,
    push_project,
    remove_worktree,
    uncommitted_count,
)
from src.data.sessions import (
    close_session_for_worktree,
    format_ago,
    format_duration,
    open_session,
    repo_id,
    stale_branches,
    stale_threshold,
    today_start,
    worktree_seconds,
)
from src.data.diff import current_branch, default_branch, list_branches
from src.tui.screens.commit_form import CommitFormScreen
from src.tui.screens.confirm import ConfirmScreen
from src.tui.screens.diff_view import DiffScreen
from src.tui.screens.git_output import GitOutputScreen
from src.tui.screens.project_form import ProjectFormScreen
from src.tui.screens.worktree_form import WorktreeFormScreen
from src.workspace.manager import WorkspaceManager


def _duration(start: str, end: str | None) -> str:
    try:
        s = datetime.fromisoformat(start)
        e = datetime.fromisoformat(end) if end else datetime.now()
        return format_duration((e - s).total_seconds())
    except Exception:
        return "?"


class _ProjectRow(ListItem):
    def __init__(self, project: dict) -> None:
        super().__init__()
        self.project = project

    def watch_highlighted(self, _: bool) -> None:
        self.refresh(recompose=True)

    def compose(self) -> ComposeResult:
        arrow = "[bold bright_cyan]▶[/bold bright_cyan]" if self.highlighted else " "
        name = self.project.get("name", "?")
        yield Label(f" {arrow} ⌂ [bold]{name}[/bold]")
        remote = self.project.get("remote") or ""
        if remote:
            yield Label(f"     [dim]{remote}[/dim]")


class _WorktreeRow(ListItem):
    def __init__(
        self, project: dict, worktree: dict, *,
        uncommitted: int, active: dict | None, stale_days: int | None,
        today_seconds: float, total_seconds: float, last_active: str | None,
    ) -> None:
        super().__init__()
        self.project = project
        self.worktree = worktree
        self._uncommitted = uncommitted
        self._active = active
        self._stale_days = stale_days
        self._today_seconds = today_seconds
        self._total_seconds = total_seconds
        self._last_active = last_active

    def watch_highlighted(self, _: bool) -> None:
        self.refresh(recompose=True)

    def compose(self) -> ComposeResult:
        arrow = "[bold bright_cyan]▶[/bold bright_cyan]" if self.highlighted else " "
        branch = self.worktree.get("branch") or "(detached)"
        folder = Path(self.worktree.get("path", "")).name

        if self._active:
            dur = _duration(self._active.get("start", ""), None)
            mark = f"[green]►[/green] [bold]{branch}[/bold]  [green]{dur}[/green]"
        else:
            mark = f"[dim]○[/dim] {branch}"

        meta = ["[green]clean[/green]" if not self._uncommitted else f"[yellow]±{self._uncommitted}[/yellow]"]
        meta.append(f"today {format_duration(self._today_seconds)}")
        meta.append(f"total {format_duration(self._total_seconds)}")
        if not self._active and self._last_active:
            meta.append(f"last: {format_ago(self._last_active)}")
        if self._stale_days:
            meta.append(f"[red]stale {self._stale_days}d[/red]")

        yield Label(f"     {arrow} {mark}")
        yield Label(f"       [dim]{folder}/[/dim]  " + "  ·  ".join(meta))


class ProjectsManager(Widget):
    DEFAULT_CSS = """
    ProjectsManager { height: 100%; }
    #pm-scroll { height: 1fr; }

    ListView { background: transparent; height: auto; }
    ListItem { background: transparent; padding: 0; }
    ListItem:hover { background: $surface; }
    ListView:focus > ListItem.--highlight { background: $primary 20%; }

    _ProjectRow   { height: auto; padding: 1 0 0 0; }
    _WorktreeRow  { height: auto; padding: 0; }

    #empty { padding: 2 4; color: $foreground 45%; }
    """

    BINDINGS = [
        ("n", "new_project",  "New project"),
        ("a", "add_worktree", "Add worktree"),
        ("c", "commit",       "Commit"),
        ("x", "remove",       "Remove"),
        ("o", "open_shell",   "Open shell"),
        ("f", "fetch",        "Fetch"),
        ("u", "pull",         "Pull"),
        ("p", "push",         "Push"),
        ("s", "status",       "Status"),
        ("v", "log",          "Log"),
        ("d", "diff",         "Diff"),
        ("b", "compare_branches", "Compare branches"),
        ("r", "reload",       "Reload"),
    ]

    def __init__(self, wm: WorkspaceManager) -> None:
        super().__init__()
        self._wm = wm

    # ----------------------------------------------------------------- compose

    def compose(self) -> ComposeResult:
        try:
            store = self._wm.store()
            projects = store.all("projects")
            sessions = store.all("sessions")
        except Exception:
            projects, sessions = [], []

        with Vertical():
            if not projects:
                yield Static(
                    "  No projects registered.\n  [dim]Press [bold]n[/bold] to clone or register one.[/dim]",
                    id="empty",
                )
                return
            with VerticalScroll(id="pm-scroll"):
                yield ListView(*self._build_rows(projects, sessions), id="pm-lv")

    def _build_rows(self, projects: list[dict], sessions: list[dict]) -> list[ListItem]:
        store = self._wm.store()
        active_by_path = {s.get("worktree_path"): s for s in sessions if not s.get("end")}
        last_start_by_path: dict[str, str] = {}
        for s in sessions:
            path = s.get("worktree_path")
            if path and s.get("start", "") > last_start_by_path.get(path, ""):
                last_start_by_path[path] = s["start"]

        rows: list[ListItem] = []
        since_today = today_start()

        for p in sorted(projects, key=lambda x: x.get("name", "")):
            rows.append(_ProjectRow(p))
            try:
                worktrees = list_worktrees(p.get("path", ""))
            except Exception:
                worktrees = []
            try:
                stale = dict(stale_branches(p["path"], stale_threshold(p["path"])))
            except Exception:
                stale = {}

            # Most recently active worktree first — falls back to branch name
            # for worktrees that have never had a session.
            worktrees = sorted(
                worktrees,
                key=lambda w: (last_start_by_path.get(w["path"], ""), w.get("branch", "")),
                reverse=True,
            )

            for w in worktrees:
                try:
                    n = uncommitted_count(w["path"])
                except Exception:
                    n = 0
                rows.append(_WorktreeRow(
                    p, w,
                    uncommitted=n,
                    active=active_by_path.get(w["path"]),
                    stale_days=stale.get(w["branch"]),
                    today_seconds=worktree_seconds(store, w["path"], since=since_today),
                    total_seconds=worktree_seconds(store, w["path"]),
                    last_active=last_start_by_path.get(w["path"]),
                ))
        return rows

    # ------------------------------------------------------------------ helpers

    def _reload(self) -> None:
        self.refresh(recompose=True)
        self.call_after_refresh(self._focus_list)

    def _focus_list(self) -> None:
        try:
            self.query_one("#pm-lv", ListView).focus()
        except Exception:
            pass

    def _selected(self) -> ListItem | None:
        try:
            lv = self.query_one("#pm-lv", ListView)
            idx = lv.index
            if idx is None:
                return None
            children = list(lv.children)
            if idx >= len(children):
                return None
            return children[idx]
        except Exception:
            return None

    # ----------------------------------------------------------------- actions

    def action_new_project(self) -> None:
        def cb(result: dict | None) -> None:
            if not result:
                return
            self._reload()
            self.notify(f"Project '{result.get('name')}' registered.", timeout=2)

        self.app.push_screen(ProjectFormScreen(self._wm), cb)

    def action_add_worktree(self) -> None:
        row = self._selected()
        if row is None or not isinstance(row, (_ProjectRow, _WorktreeRow)):
            self.notify("Select a project first.", severity="warning")
            return
        project = row.project

        def cb(result: dict | None) -> None:
            if not result:
                return
            try:
                store = self._wm.store()
                repo = repo_id(result["path"])
                open_session(store, repo, result["branch"], result["path"])
            except Exception:
                pass
            self._reload()
            self.notify(f"Worktree '{result['branch']}' created.", timeout=2)

        self.app.push_screen(WorktreeFormScreen(project), cb)

    def action_commit(self) -> None:
        row = self._selected()
        if not isinstance(row, _WorktreeRow):
            self.notify("Select a worktree first.", severity="warning")
            return

        from src.data.projects import staged_files
        from src.data.scopes import detect_scope, suggest_type

        path = row.worktree["path"]
        staged = staged_files(path)
        if not staged:
            self.notify("Nothing staged.", severity="warning")
            return

        dominant_scope, breakdown = detect_scope(path, staged)
        suggested_type = suggest_type(staged)

        def cb(committed: bool) -> None:
            if not committed:
                return
            self._reload()
            self.notify("Committed.", timeout=2)

        self.app.push_screen(
            CommitFormScreen(path, len(staged), dominant_scope, breakdown, suggested_type),
            cb,
        )

    def action_remove(self) -> None:
        row = self._selected()
        if row is None:
            self.notify("Select a row first.", severity="warning")
            return

        if isinstance(row, _WorktreeRow):
            branch = row.worktree.get("branch") or "(detached)"

            def cb(confirmed: bool) -> None:
                if not confirmed:
                    return
                try:
                    remove_worktree(row.project["path"], row.worktree["path"], force=True)
                    close_session_for_worktree(self._wm.store(), row.worktree["path"])
                except Exception as e:
                    self.notify(str(e), severity="error", timeout=4)
                    return
                self._reload()
                self.notify("Worktree removed.", timeout=2)

            self.app.push_screen(
                ConfirmScreen(f"Remove worktree '{branch}'? Uncommitted changes (if any) are discarded.", "Remove"),
                cb,
            )
        elif isinstance(row, _ProjectRow):
            def cb(confirmed: bool) -> None:
                if not confirmed:
                    return
                self._wm.store().delete("projects", row.project["id"])
                self._reload()
                self.notify("Project unregistered (files kept on disk).", timeout=2)

            self.app.push_screen(
                ConfirmScreen(f"Unregister project '{row.project.get('name')}'? Files are kept on disk.", "Unregister"),
                cb,
            )

    def action_open_shell(self) -> None:
        row = self._selected()
        if row is None:
            self.notify("Select a row first.", severity="warning")
            return
        path = row.worktree["path"] if isinstance(row, _WorktreeRow) else row.project["path"]
        shell = os.environ.get("SHELL") or os.environ.get("COMSPEC", "/bin/sh")
        with self.app.suspend():
            subprocess.call([shell], cwd=path)
        self._reload()

    def _selected_worktree(self) -> "_WorktreeRow | None":
        row = self._selected()
        if not isinstance(row, _WorktreeRow):
            self.notify("Select a worktree first.", severity="warning")
            return None
        return row

    def action_pull(self) -> None:
        row = self._selected_worktree()
        if row is None:
            return
        self.notify(f"Pulling {row.worktree.get('branch')}…", timeout=2)
        self._pull_worker(row.worktree["path"])

    @work(thread=True)
    def _pull_worker(self, path: str) -> None:
        try:
            pull_project(path)
        except Exception as e:
            self.app.call_from_thread(self.notify, str(e), severity="error", timeout=4)
            return
        self.app.call_from_thread(self._reload)
        self.app.call_from_thread(self.notify, "Pulled.", timeout=2)

    def action_push(self) -> None:
        row = self._selected_worktree()
        if row is None:
            return
        self.notify(f"Pushing {row.worktree.get('branch')}…", timeout=2)
        self._push_worker(row.worktree["path"])

    @work(thread=True)
    def _push_worker(self, path: str) -> None:
        try:
            push_project(path)
        except Exception as e:
            self.app.call_from_thread(self.notify, str(e), severity="error", timeout=4)
            return
        self.app.call_from_thread(self._reload)
        self.app.call_from_thread(self.notify, "Pushed.", timeout=2)

    def action_status(self) -> None:
        row = self._selected_worktree()
        if row is None:
            return
        branch = row.worktree.get("branch") or "(detached)"
        text = git_status_text(row.worktree["path"])
        self.app.push_screen(GitOutputScreen(f"git status — {branch}", text))

    def action_log(self) -> None:
        row = self._selected_worktree()
        if row is None:
            return
        branch = row.worktree.get("branch") or "(detached)"
        text = git_log_text(row.worktree["path"])
        self.app.push_screen(GitOutputScreen(f"git log — {branch}", text))

    def action_diff(self) -> None:
        row = self._selected_worktree()
        if row is None:
            return
        self.app.push_screen(DiffScreen(row.worktree["path"]))

    def action_compare_branches(self) -> None:
        row = self._selected()
        if row is None or not isinstance(row, (_ProjectRow, _WorktreeRow)):
            self.notify("Select a project or worktree first.", severity="warning")
            return
        path = row.worktree["path"] if isinstance(row, _WorktreeRow) else row.project["path"]
        branches = list_branches(path)
        if not branches:
            self.notify("No local branches found.", severity="warning")
            return
        target = default_branch(path)
        source = current_branch(path) or target
        self.app.push_screen(DiffScreen(path, target_branch=target, source_branch=source))

    def action_fetch(self) -> None:
        row = self._selected()
        if row is None or not isinstance(row, (_ProjectRow, _WorktreeRow)):
            self.notify("Select a project first.", severity="warning")
            return
        project = row.project
        self.notify(f"Fetching {project.get('name')}…", timeout=2)
        self._fetch_worker(project["path"])

    @work(thread=True)
    def _fetch_worker(self, root: str) -> None:
        try:
            fetch_project(root)
        except Exception as e:
            self.app.call_from_thread(self.notify, str(e), severity="error", timeout=4)
            return
        self.app.call_from_thread(self._reload)
        self.app.call_from_thread(self.notify, "Fetched.", timeout=2)

    def action_reload(self) -> None:
        self._reload()
