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
    out: Optional[Path] = typer.Option(None, "--out", "-o", help="Output file (default: auto)"),
    pdf: bool = typer.Option(False, "--pdf", help="Export as PDF into the workspace export/ folder"),
) -> None:
    """Export a note — Markdown (default) or PDF (--pdf)."""
    from src.workspace.manager import WorkspaceManager
    from src.data.query import render_query_blocks

    wm = WorkspaceManager()
    note_path = Path(file)

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
        title = post.metadata.get("title", note_path.stem)
        raw_content = post.content
    except Exception:
        post = None
        title = note_path.stem
        raw_content = note_path.read_text(encoding="utf-8", errors="replace")

    try:
        store = wm.store()
        rendered_md = render_query_blocks(raw_content, store)
    except Exception:
        rendered_md = raw_content

    if not pdf:
        # ── Markdown export ───────────────────────────────────────────────
        if post is not None:
            post.content = rendered_md
            output = frontmatter.dumps(post)
        else:
            output = rendered_md
        if out:
            out.write_text(output, encoding="utf-8")
            console.print(f"[green]Exported:[/green] {out}")
        else:
            console.print(output, markup=False, highlight=False)
        return

    # ── PDF export ────────────────────────────────────────────────────────
    try:
        import mistune
        from weasyprint import HTML as _HTML
    except ImportError as e:
        console.print(f"[red]PDF export requires weasyprint: pip install weasyprint ({e})[/red]")
        raise typer.Exit(1)

    # Determine output path: workspace/export/<stem>.pdf
    if out:
        pdf_path = out
    else:
        try:
            ws_path = Path(wm.active().path)
        except Exception:
            ws_path = Path.cwd()
        export_dir = ws_path / "export"
        export_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = export_dir / f"{note_path.stem}.pdf"

    # Markdown → HTML
    md_renderer = mistune.create_markdown(plugins=["table", "strikethrough", "task_lists"])
    html_body = md_renderer(rendered_md)

    html = f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
  body {{
    font-family: "Segoe UI", Arial, sans-serif;
    max-width: 820px; margin: 40px auto;
    line-height: 1.7; color: #1a1a1a; font-size: 14px;
  }}
  h1 {{ font-size: 2em; border-bottom: 2px solid #555; padding-bottom: .3em; }}
  h2 {{ font-size: 1.4em; border-bottom: 1px solid #ccc; padding-bottom: .2em; margin-top: 1.8em; }}
  h3 {{ font-size: 1.1em; margin-top: 1.4em; }}
  code {{ background: #f3f3f3; padding: 2px 5px; border-radius: 3px; font-size: .9em; }}
  pre  {{ background: #f3f3f3; padding: 14px; border-radius: 5px; overflow-x: auto; }}
  pre code {{ background: none; padding: 0; }}
  table {{ border-collapse: collapse; width: 100%; margin: 1em 0; }}
  th, td {{ border: 1px solid #ccc; padding: 7px 12px; text-align: left; }}
  th {{ background: #f0f0f0; font-weight: 600; }}
  blockquote {{ border-left: 3px solid #aaa; margin: 0; padding: 0 1em; color: #555; }}
  ul, ol {{ padding-left: 1.5em; }}
  a {{ color: #0066cc; }}
  @page {{ margin: 2cm; }}
</style>
</head>
<body>
{html_body}
</body>
</html>"""

    try:
        _HTML(string=html).write_pdf(str(pdf_path))
        console.print(f"[green]PDF exported:[/green] {pdf_path}")
    except Exception as e:
        console.print(f"[red]PDF generation failed: {e}[/red]")
        raise typer.Exit(1)


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
