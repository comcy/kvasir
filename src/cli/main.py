"""mimirlink CLI – entry point. Sub-commands are registered as Typer apps."""
from __future__ import annotations

import typer
from rich.console import Console

from .workspace_cmd import app as workspace_app
from .todo_cmd import app as todo_app
from .metric_cmd import app as metric_app
from .hooks_cmd import app as hooks_app, hook_app
from .note_cmd import app as note_app

console = Console()
app = typer.Typer(
    name="mimirlink",
    help="Local, offline-first developer workflow & journaling tool.",
    no_args_is_help=True,
)

app.add_typer(workspace_app, name="workspace")
app.add_typer(todo_app, name="todo")
app.add_typer(metric_app, name="metric")
app.add_typer(hooks_app, name="hooks")
app.add_typer(hook_app, name="hook")
app.add_typer(note_app, name="note")


@app.command()
def tui(
    theme: str = typer.Option("dracula", "--theme", "-t", help="Starting theme: dracula|nord|tokyo-night|gruvbox|catppuccin|solarized"),
) -> None:
    """Launch the interactive TUI dashboard."""
    from src.tui.app import DevTrackApp
    from src.tui.themes import THEME_NAMES

    if theme not in THEME_NAMES:
        console.print(f"[red]Unknown theme '{theme}'. Choose from: {', '.join(THEME_NAMES)}[/red]")
        raise typer.Exit(1)

    DevTrackApp(theme_name=theme).run()


@app.command()
def today() -> None:
    """Show a summary of today's work: sessions, commits, todos."""
    from src.workspace.manager import WorkspaceManager
    from datetime import date

    wm = WorkspaceManager()
    try:
        ws = wm.active()
        store = wm.store()
    except Exception as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    today_str = date.today().isoformat()
    sessions = [
        s for s in store.all("sessions")
        if s.get("start", "").startswith(today_str)
    ]
    todos_open = store.find("todos", status="open")

    console.print(f"\n[bold]Today – {today_str}[/bold]  (workspace: [cyan]{ws.name}[/cyan])\n")
    console.print(f"  Sessions today : [yellow]{len(sessions)}[/yellow]")
    console.print(f"  Open todos     : [yellow]{len(todos_open)}[/yellow]\n")


@app.command()
def summary() -> None:
    """Weekly summary: todos done, commits, metric values."""
    from src.workspace.manager import WorkspaceManager
    from datetime import date, timedelta

    wm = WorkspaceManager()
    try:
        ws = wm.active()
        store = wm.store()
    except Exception as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    week_start = (date.today() - timedelta(days=date.today().weekday())).isoformat()
    done = [t for t in store.all("todos") if t.get("status") == "done" and t.get("updated", "") >= week_start]
    commits = [c for c in store.all("commits") if c.get("date", "") >= week_start]

    console.print(f"\n[bold]Week summary[/bold]  (since {week_start}, workspace: [cyan]{ws.name}[/cyan])\n")
    console.print(f"  Todos done this week : [green]{len(done)}[/green]")
    console.print(f"  Commits tracked      : [green]{len(commits)}[/green]\n")
