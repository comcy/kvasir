"""Note management commands."""
from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

import frontmatter
import typer
from rich.console import Console

app = typer.Typer(help="Note management.")
console = Console()


@app.command("export")
def export_note(
    file: str = typer.Argument(..., help="Note filename or path (e.g. my-note.md)"),
    out: Optional[Path] = typer.Option(None, "--out", "-o", help="Output file (default: stdout)"),
) -> None:
    """Export a note with query blocks rendered to static Markdown."""
    from src.workspace.manager import WorkspaceManager
    from src.data.query import render_query_blocks

    wm = WorkspaceManager()
    note_path = Path(file)

    # If not an absolute path that exists, look in the active workspace notes dir
    if not note_path.is_absolute() and not note_path.exists():
        try:
            nd = wm.notes_dir()
            candidate = nd / file
            if candidate.exists():
                note_path = candidate
        except Exception as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(1)

    if not note_path.exists():
        console.print(f"[red]Note not found: {file}[/red]")
        raise typer.Exit(1)

    try:
        post = frontmatter.load(str(note_path))
        raw_content = post.content
    except Exception:
        post = None
        raw_content = note_path.read_text(encoding="utf-8", errors="replace")

    try:
        store = wm.store()
        rendered = render_query_blocks(raw_content, store)
    except Exception:
        rendered = raw_content

    if post is not None:
        post.content = rendered
        output = frontmatter.dumps(post)
    else:
        output = rendered

    if out:
        out.write_text(output, encoding="utf-8")
        console.print(f"[green]Exported:[/green] {out}")
    else:
        console.print(output, markup=False, highlight=False)


@app.command("extract-todos")
def extract_todos_cmd(
    file: str = typer.Argument(..., help="Note filename or path"),
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Preview without writing"),
) -> None:
    """Extract checkbox todos from a note into todos.ndjson."""
    from src.workspace.manager import WorkspaceManager
    from src.data.note_todos import parse_note_todos, save_todo_tags

    wm = WorkspaceManager()
    note_path = Path(file)
    if not note_path.is_absolute() and not note_path.exists():
        try:
            candidate = wm.notes_dir() / file
            if candidate.exists():
                note_path = candidate
        except Exception as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(1)

    if not note_path.exists():
        console.print(f"[red]Note not found: {file}[/red]")
        raise typer.Exit(1)

    try:
        post = frontmatter.load(str(note_path))
        parsed = parse_note_todos(post.content, note_path.stem)
    except Exception as e:
        console.print(f"[red]Failed to parse note: {e}[/red]")
        raise typer.Exit(1)

    if not parsed:
        console.print("[dim]No checkbox todos found in this note.[/dim]")
        return

    if dry_run:
        console.print(f"[bold]Dry run — {len(parsed)} todo(s) found:[/bold]\n")
        for t in parsed:
            prefix = "✓" if t["status"] == "done" else "○"
            assign = f"  [dim]→ @{t['assignee']}[/dim]" if t["assignee"] else ""
            tags = "  " + " ".join(f"[dim][{tg}][/dim]" for tg in t["tags"]) if t["tags"] else ""
            due = f"  [dim]{t['due_date']}[/dim]" if t["due_date"] else ""
            console.print(f"  {prefix}  {t['text']}{assign}{tags}{due}")
        return

    try:
        store = wm.store()
    except Exception as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    existing_hashes = {
        t["source_hash"] for t in store.all("todos") if t.get("source_hash")
    }
    now = datetime.now().isoformat()
    new_count = 0
    for todo in parsed:
        if todo["source_hash"] in existing_hashes:
            console.print(f"  [dim]skip (exists):[/dim] {todo['text']}")
            continue
        rec = store.insert("todos", {
            "id": str(uuid.uuid4()),
            "text": todo["text"],
            "status": todo["status"],
            "due_date": todo["due_date"],
            "assignee": todo["assignee"],
            "note_ref": todo["note_ref"],
            "source_hash": todo["source_hash"],
            "created": now,
            "updated": now,
        })
        if todo["tags"]:
            save_todo_tags(store, rec["id"], todo["tags"])
        assign_str = f" → @{todo['assignee']}" if todo["assignee"] else ""
        console.print(f"  [green]created:[/green] {todo['text']}{assign_str}")
        new_count += 1

    console.print(f"\n[bold]{new_count}[/bold] new todo(s) created.")
