"""mimirlink todo <sub-command>"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from src.workspace.manager import WorkspaceManager, WorkspaceError

app = typer.Typer(help="Manage todos.")
console = Console()


def _store():
    return WorkspaceManager().store()


@app.command("add")
def add(
    text: str = typer.Argument(..., help="Todo text"),
    due: Optional[str] = typer.Option(None, "--due", "-d", help="Due date (YYYY-MM-DD)"),
    tags: Optional[str] = typer.Option(None, "--tags", "-t", help="Comma-separated tag names"),
) -> None:
    """Add a new todo."""
    try:
        store = _store()
    except WorkspaceError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    now = datetime.now().isoformat()
    record = store.insert("todos", {
        "id": str(uuid.uuid4()),
        "text": text,
        "status": "open",
        "due_date": due,
        "created": now,
        "updated": now,
    })

    if tags:
        for tag_name in (t.strip() for t in tags.split(",") if t.strip()):
            existing = store.find("tags", name=tag_name)
            tag = existing[0] if existing else store.insert("tags", {"id": str(uuid.uuid4()), "name": tag_name})
            store.insert("todo_tags", {"todo_id": record["id"], "tag_id": tag["id"]})

    console.print(f"[green]Added[/green] [{record['id'][:8]}] {text}")


@app.command("list")
def list_todos(
    status: str = typer.Option("open", "--status", "-s", help="Filter by status: open/done/cancelled/all"),
    tag: Optional[str] = typer.Option(None, "--tag", "-t", help="Filter by tag name"),
) -> None:
    """List todos."""
    try:
        store = _store()
    except WorkspaceError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    todos = store.all("todos") if status == "all" else store.find("todos", status=status)

    if tag:
        tag_records = store.find("tags", name=tag)
        if not tag_records:
            console.print(f"[yellow]No tag '{tag}' found.[/yellow]")
            return
        tag_id = tag_records[0]["id"]
        mappings = {m["todo_id"] for m in store.find("todo_tags", tag_id=tag_id)}
        todos = [t for t in todos if t["id"] in mappings]

    if not todos:
        console.print("[dim]No todos found.[/dim]")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("ID", width=10)
    table.add_column("Text")
    table.add_column("Status", width=10)
    table.add_column("Due", width=12)

    status_colors = {"open": "yellow", "done": "green", "cancelled": "dim"}
    for t in todos:
        color = status_colors.get(t.get("status", ""), "white")
        table.add_row(
            t["id"][:8],
            t.get("text", ""),
            f"[{color}]{t.get('status', '')}[/{color}]",
            t.get("due_date") or "",
        )

    console.print(table)


@app.command("done")
def done(id_prefix: str = typer.Argument(..., help="Todo ID or prefix")) -> None:
    """Mark a todo as done."""
    try:
        store = _store()
    except WorkspaceError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    todos = [t for t in store.all("todos") if t["id"].startswith(id_prefix)]
    if not todos:
        console.print(f"[red]No todo found with prefix '{id_prefix}'.[/red]")
        raise typer.Exit(1)
    if len(todos) > 1:
        console.print(f"[red]Ambiguous prefix '{id_prefix}' matches {len(todos)} todos.[/red]")
        raise typer.Exit(1)

    store.update("todos", todos[0]["id"], status="done", updated=datetime.now().isoformat())
    console.print(f"[green]Done[/green] [{todos[0]['id'][:8]}] {todos[0].get('text', '')}")


@app.command("delete")
def delete(id_prefix: str = typer.Argument(..., help="Todo ID or prefix")) -> None:
    """Delete a todo and its tag mappings."""
    try:
        store = _store()
    except WorkspaceError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    todos = [t for t in store.all("todos") if t["id"].startswith(id_prefix)]
    if not todos:
        console.print(f"[red]No todo found with prefix '{id_prefix}'.[/red]")
        raise typer.Exit(1)

    store.delete_with_relations("todos", todos[0]["id"], [("todo_tags", "todo_id")])
    console.print(f"[yellow]Deleted[/yellow] [{todos[0]['id'][:8]}]")
