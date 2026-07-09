"""Project management: registered repo paths, bare-repo clone layout."""
from __future__ import annotations

import subprocess
import uuid
from datetime import datetime
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


def _git(args: list[str], cwd: Path | str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=str(cwd), stderr=subprocess.DEVNULL
    ).decode().strip()


def _register(store, name: str, path: Path, remote: str) -> dict:
    return store.insert("projects", {
        "id": str(uuid.uuid4()),
        "name": name,
        "path": str(path.resolve()),
        "remote": remote,
        "created": datetime.now().isoformat(),
    })


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
    try:
        store = _store()
    except WorkspaceError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    if name is None:
        name = url.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git")

    if store.find("projects", name=name):
        console.print(f"[red]Project '{name}' is already registered.[/red]")
        raise typer.Exit(1)

    root = ((dir or Path.cwd()) / name).resolve()
    if root.exists():
        console.print(f"[red]Directory already exists: {root}[/red]")
        raise typer.Exit(1)

    console.print(f"Cloning [bold]{url}[/bold] → {root} [dim](bare layout)[/dim]")
    try:
        subprocess.run(["git", "clone", "--bare", url, str(root / ".bare")], check=True)
    except subprocess.CalledProcessError:
        console.print("[red]git clone failed.[/red]")
        raise typer.Exit(1)

    (root / ".git").write_text("gitdir: ./.bare\n", encoding="utf-8")

    # Bare clones have no fetch refspec — without it, fetch/pull won't update
    # remote-tracking branches.
    subprocess.run(
        ["git", "config", "remote.origin.fetch", "+refs/heads/*:refs/remotes/origin/*"],
        cwd=str(root), check=True,
    )
    subprocess.run(["git", "fetch", "origin"], cwd=str(root), check=True)

    try:
        default_branch = _git(["symbolic-ref", "--short", "HEAD"], root)
    except subprocess.CalledProcessError:
        default_branch = "main"

    try:
        subprocess.run(
            ["git", "worktree", "add", f"./{default_branch}", default_branch],
            cwd=str(root), check=True,
        )
        console.print(f"[green]Worktree[/green] {root / default_branch}")
    except subprocess.CalledProcessError:
        console.print(f"[yellow]Could not create worktree for '{default_branch}'.[/yellow]")

    from src.cli.hooks_cmd import install_hooks
    try:
        install_hooks(repo=root, force=False)
    except SystemExit:
        pass  # hook install issues must not fail the clone

    record = _register(store, name, root, url)
    console.print(f"\n[green]Registered project[/green] [bold]{record['name']}[/bold] → {record['path']}")


@app.command("add")
def add(
    name: str = typer.Argument(..., help="Project name"),
    path: Path = typer.Option(Path("."), "--path", "-p", help="Project directory (default: cwd)"),
) -> None:
    """Register an existing repo/directory as a project."""
    from src.data.projects import project_root
    from src.data.sessions import repo_id

    try:
        store = _store()
    except WorkspaceError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    if store.find("projects", name=name):
        console.print(f"[red]Project '{name}' is already registered.[/red]")
        raise typer.Exit(1)

    root = project_root(path) or path.resolve()
    if not root.exists():
        console.print(f"[red]Directory not found: {root}[/red]")
        raise typer.Exit(1)

    existing = [p for p in store.all("projects") if p.get("path") == str(root)]
    if existing:
        console.print(f"[red]Path already registered as '{existing[0]['name']}'.[/red]")
        raise typer.Exit(1)

    try:
        remote = repo_id(root)
    except Exception:
        remote = ""

    record = _register(store, name, root, remote if remote != str(root) else "")
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
