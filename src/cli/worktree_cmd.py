"""Worktree commands: add/list/remove worktrees inside a project."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from src.workspace.manager import WorkspaceError, WorkspaceManager

app = typer.Typer(help="Manage git worktrees inside a project.")
console = Console()


def _duration(start: str, end: str | None) -> str:
    from src.data.sessions import format_duration

    try:
        s = datetime.fromisoformat(start)
        e = datetime.fromisoformat(end) if end else datetime.now()
        return format_duration((e - s).total_seconds())
    except Exception:
        return "?"


def _require_root() -> Path:
    from src.data.projects import project_root

    root = project_root(Path.cwd())
    if root is None:
        console.print("[red]Not inside a project (no git repo found from cwd).[/red]")
        raise typer.Exit(1)
    return root


@app.command("add")
def add(
    branch: str = typer.Argument(..., help="Branch to check out (created if missing)"),
    from_ref: Optional[str] = typer.Option(None, "--from", "-f", help="Start point for a new branch (default: current HEAD)"),
) -> None:
    """Create a worktree folder for BRANCH inside the current project."""
    from src.data.projects import ProjectOpError, add_worktree
    from src.data.sessions import last_session, open_session, repo_id

    root = _require_root()
    try:
        dest = add_worktree(root, branch, from_ref)
    except ProjectOpError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    console.print(f"[green]Worktree[/green] {dest}  [dim]({branch})[/dim]")

    try:
        store = WorkspaceManager().store()
        repo = repo_id(dest)
        prev = last_session(store, repo, branch)
        if prev and prev.get("start"):
            ts = prev["start"][:16].replace("T", " ")
            console.print(f"[dim]Last session on this branch: {ts}[/dim]")
        open_session(store, repo, branch, str(dest))
    except (WorkspaceError, Exception):
        pass  # session tracking must not fail the worktree operation


@app.command("list")
def list_worktrees_cmd() -> None:
    """List worktrees of the current project with WIP and session status."""
    from src.data.projects import list_worktrees, uncommitted_count
    from src.data.sessions import stale_branches, stale_threshold

    root = _require_root()
    worktrees = list_worktrees(root)
    if not worktrees:
        console.print("[dim]No worktrees found.[/dim]")
        return

    sessions: list[dict] = []
    try:
        sessions = WorkspaceManager().store().all("sessions")
    except (WorkspaceError, Exception):
        pass

    stale = dict(stale_branches(root, stale_threshold(root)))

    table = Table(show_header=True, header_style="bold")
    table.add_column("Folder")
    table.add_column("Branch")
    table.add_column("Uncommitted", justify="right")
    table.add_column("Session")
    table.add_column("", width=10)

    for w in worktrees:
        wt_path = w["path"]
        branch = w["branch"] or "[dim](detached)[/dim]"
        n = uncommitted_count(wt_path)
        wip = f"[yellow]{n}[/yellow]" if n else "[dim]0[/dim]"

        wt_sessions = [s for s in sessions if s.get("worktree_path") == wt_path]
        active = [s for s in wt_sessions if not s.get("end")]
        if active:
            sess = f"[green]● {_duration(active[0].get('start', ''), None)}[/green]"
        elif wt_sessions:
            latest = max(wt_sessions, key=lambda s: s.get("start", ""))
            sess = f"[dim]{latest.get('start', '')[:16].replace('T', ' ')}[/dim]"
        else:
            sess = "[dim]—[/dim]"

        marker = f"[red]stale {stale[w['branch']]}d[/red]" if w["branch"] in stale else ""
        table.add_row(Path(wt_path).name, branch, wip, sess, marker)

    console.print(table)


@app.command("remove")
def remove(
    target: str = typer.Argument(..., help="Worktree folder name or branch"),
    force: bool = typer.Option(False, "--force", help="Remove even with uncommitted changes"),
) -> None:
    """Remove a worktree and close its session. The branch itself is kept."""
    from src.data.projects import ProjectOpError, list_worktrees, remove_worktree
    from src.data.sessions import close_session_for_worktree

    root = _require_root()
    match = next(
        (w for w in list_worktrees(root)
         if Path(w["path"]).name == target or w["branch"] == target),
        None,
    )
    if match is None:
        console.print(f"[red]No worktree matching '{target}'.[/red]")
        raise typer.Exit(1)

    try:
        remove_worktree(root, match["path"], force=force)
    except ProjectOpError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    try:
        close_session_for_worktree(WorkspaceManager().store(), match["path"])
    except (WorkspaceError, Exception):
        pass

    console.print(f"[yellow]Removed[/yellow] {match['path']}  [dim](branch '{match['branch']}' kept)[/dim]")


@app.command("pull")
def pull() -> None:
    """Pull the current branch from its upstream. Run from inside a worktree folder."""
    from src.data.projects import ProjectOpError, pull_project

    _require_root()  # just validates we're inside a registered project
    try:
        pull_project(Path.cwd())
    except ProjectOpError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    console.print("[green]Pulled.[/green]")


@app.command("push")
def push() -> None:
    """Push the current branch to its upstream. Run from inside a worktree folder."""
    from src.data.projects import ProjectOpError, push_project

    _require_root()
    try:
        push_project(Path.cwd())
    except ProjectOpError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    console.print("[green]Pushed.[/green]")


@app.command("status")
def status() -> None:
    """Show `git status` for the current worktree."""
    from src.data.projects import git_status_text

    _require_root()
    console.print(git_status_text(Path.cwd()))


@app.command("log")
def log(
    limit: int = typer.Option(30, "--limit", "-n", help="Number of commits to show"),
) -> None:
    """Show `git log --oneline` for the current worktree."""
    from src.data.projects import git_log_text

    _require_root()
    console.print(git_log_text(Path.cwd(), limit=limit))
