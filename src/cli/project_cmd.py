"""Project management: registered repo paths, bare-repo clone layout."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from src.workspace.manager import WorkspaceError, WorkspaceManager

app = typer.Typer(help="Manage projects (registered repos with worktree support).")
console = Console()


def _store():
    return WorkspaceManager().store()


@app.command("clone")
def clone(
    url: str = typer.Argument(..., help="Repository URL to clone"),
    name: Optional[str] = typer.Argument(None, help="Project name (default: from URL)"),
    dir: Optional[Path] = typer.Option(None, "--dir", "-d", help="Parent directory (default: cwd)"),
) -> None:
    """Clone a repo in the bare-repo worktree layout and register it as a project.

    Layout: <name>/.bare (bare clone) + <name>/.git (gitdir file) — the project
    folder acts as the repo, worktrees are plain subfolders. A worktree for the
    default branch is checked out and mimirlink hooks are installed.
    """
    from src.data.projects import ProjectOpError, clone_project

    try:
        store = _store()
    except WorkspaceError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    if name is None:
        name = url.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git")

    console.print(f"Cloning [bold]{url}[/bold] → {(dir or Path.cwd()) / name} [dim](bare layout)[/dim]")
    try:
        record = clone_project(store, url, name, dir or Path.cwd())
    except ProjectOpError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    console.print(f"\n[green]Registered project[/green] [bold]{record['name']}[/bold] → {record['path']}")


@app.command("add")
def add(
    name: str = typer.Argument(..., help="Project name"),
    path: Path = typer.Option(Path("."), "--path", "-p", help="Project directory (default: cwd)"),
) -> None:
    """Register an existing repo/directory as a project."""
    from src.data.projects import ProjectOpError, register_existing

    try:
        store = _store()
    except WorkspaceError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    try:
        record = register_existing(store, name, path)
    except ProjectOpError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    console.print(f"[green]Registered project[/green] [bold]{record['name']}[/bold] → {record['path']}")


@app.command("list")
def list_projects() -> None:
    """List registered projects with worktree and session status."""
    from src.data.projects import list_worktrees

    try:
        store = _store()
    except WorkspaceError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    projects = store.all("projects")
    if not projects:
        console.print("[dim]No projects registered. Use: mimirlink project add/clone[/dim]")
        return

    active_paths = {
        s.get("worktree_path") for s in store.all("sessions") if not s.get("end")
    }

    table = Table(show_header=True, header_style="bold")
    table.add_column("Name")
    table.add_column("Path")
    table.add_column("Remote")
    table.add_column("Worktrees", justify="right")
    table.add_column("Active", justify="center")

    for p in sorted(projects, key=lambda x: x.get("name", "")):
        worktrees = list_worktrees(p.get("path", ""))
        has_active = any(w["path"] in active_paths for w in worktrees)
        table.add_row(
            p.get("name", ""),
            p.get("path", ""),
            p.get("remote", "") or "[dim]—[/dim]",
            str(len(worktrees)),
            "[green]●[/green]" if has_active else "[dim]○[/dim]",
        )
    console.print(table)


@app.command("remove")
def remove(name: str = typer.Argument(..., help="Project name")) -> None:
    """Unregister a project. Files on disk are never touched."""
    try:
        store = _store()
    except WorkspaceError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    hits = store.find("projects", name=name)
    if not hits:
        console.print(f"[red]No project named '{name}'.[/red]")
        raise typer.Exit(1)

    store.delete("projects", hits[0]["id"])
    console.print(f"[yellow]Unregistered[/yellow] '{name}' [dim](files kept on disk)[/dim]")
