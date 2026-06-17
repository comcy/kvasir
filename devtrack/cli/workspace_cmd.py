"""devtrack workspace <sub-command>"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from devtrack.workspace.manager import WorkspaceManager, WorkspaceError

app = typer.Typer(help="Manage workspaces (create / list / use / delete).")
console = Console()
_wm = WorkspaceManager()


@app.command("create")
def create(
    name: str = typer.Argument(..., help="Workspace name, e.g. 'work' or 'private'"),
    path: Optional[Path] = typer.Option(None, "--path", "-p", help="Custom directory"),
    sync_target: str = typer.Option("", "--sync", "-s", help="Sync target description"),
    description: str = typer.Option("", "--desc", "-d", help="Short description"),
) -> None:
    """Create a new workspace."""
    try:
        ws = _wm.create(name, path=path, sync_target=sync_target, description=description)
        console.print(f"[green]Created workspace[/green] '[bold]{ws.name}[/bold]' at {ws.path}")
    except WorkspaceError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)


@app.command("list")
def list_workspaces() -> None:
    """List all workspaces."""
    active = ""
    try:
        active = _wm.config.active_workspace
    except Exception:
        pass

    workspaces = _wm.list()
    if not workspaces:
        console.print("No workspaces yet. Run: devtrack workspace create <name>")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("", width=2)
    table.add_column("Name")
    table.add_column("Path")
    table.add_column("Sync target")
    table.add_column("Description")

    for ws in workspaces:
        marker = "[green]*[/green]" if ws.name == active else ""
        table.add_row(marker, ws.name, ws.path, ws.sync_target, ws.description)

    console.print(table)


@app.command("use")
def use(name: str = typer.Argument(..., help="Workspace to activate")) -> None:
    """Switch the active workspace."""
    try:
        ws = _wm.use(name)
        console.print(f"[green]Active workspace set to[/green] '[bold]{ws.name}[/bold]'")
    except WorkspaceError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)


@app.command("delete")
def delete(
    name: str = typer.Argument(..., help="Workspace to remove from config"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Remove a workspace from the config (data files are not deleted)."""
    if not yes:
        typer.confirm(f"Remove workspace '{name}' from config?", abort=True)
    try:
        _wm.delete(name)
        console.print(f"[yellow]Removed workspace[/yellow] '{name}' from config.")
        console.print("[dim]Data files were not deleted.[/dim]")
    except WorkspaceError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
