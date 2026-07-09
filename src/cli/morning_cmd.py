"""Interactive `mimirlink morning` routine: todo triage, journal gap-fill, plan today."""
from __future__ import annotations

import os
import subprocess
from datetime import date, datetime

import typer
from rich.console import Console
from rich.prompt import Prompt

from src.workspace.manager import WorkspaceError, WorkspaceManager
from src.data.journal import append_plan, ensure_note, slug_for
from src.data.morning import (
    due_or_overdue_todos,
    mark_journal_day_skipped,
    missing_journal_days,
    undated_todos,
)


def _triage_todos(console: Console, store) -> None:
    todos = due_or_overdue_todos(store)
    if not todos:
        console.print("[dim]No overdue or due-today todos.[/dim]\n")
        return

    console.print(f"[bold]Todo triage[/bold] — {len(todos)} due or overdue\n")
    now = datetime.now().isoformat()
    for t in todos:
        priority = int(t.get("priority") or 0)
        console.print(f"  {t['text']}  [dim](due {t['due_date']}, priority {priority})[/dim]")
        action = Prompt.ask(
            r"  \[d]one / \[r]eschedule / \[p]riority+ / \[s]kip",
            choices=["d", "r", "p", "s"], default="s", show_choices=False,
        )
        if action == "d":
            store.update("todos", t["id"], status="done", updated=now)
            console.print("  [green]done[/green]\n")
        elif action == "r":
            new_due = Prompt.ask("  New due date (YYYY-MM-DD)", default="").strip()
            if new_due:
                store.update("todos", t["id"], due_date=new_due, updated=now)
                console.print(f"  [yellow]rescheduled → {new_due}[/yellow]\n")
            else:
                console.print("  [dim]left unchanged[/dim]\n")
        elif action == "p":
            new_priority = min(priority + 1, 3)
            store.update("todos", t["id"], priority=new_priority, updated=now)
            console.print(f"  [yellow]priority → {new_priority}[/yellow]\n")
        else:
            console.print("  [dim]left unchanged[/dim]\n")


def _assign_undated_todos(console: Console, store) -> None:
    todos = undated_todos(store)
    if not todos:
        console.print("[dim]No undated open todos.[/dim]\n")
        return

    console.print(f"[bold]Undated todos[/bold] — {len(todos)} without a due date\n")
    now = datetime.now().isoformat()
    for t in todos:
        console.print(f"  {t['text']}")
        due = Prompt.ask("  Assign due date (YYYY-MM-DD, leer = überspringen)", default="").strip()
        if due:
            store.update("todos", t["id"], due_date=due, updated=now)
            console.print(f"  [green]due → {due}[/green]\n")
        else:
            console.print("  [dim]left undated[/dim]\n")


def _fill_journal_gaps(console: Console, notes_dir, store, lookback: int) -> None:
    days = missing_journal_days(notes_dir, store, lookback)
    if not days:
        console.print(f"[dim]No missing journal entries in the last {lookback} days.[/dim]\n")
        return

    console.print(f"[bold]Journal gap-fill[/bold] — {len(days)} day(s) missing an entry\n")
    for d in days:
        console.print(f"  {d.isoformat()}")
        action = Prompt.ask(
            r"  \[o]pen in editor / \[s]kip permanently / \[n]ot now",
            choices=["o", "s", "n"], default="n", show_choices=False,
        )
        if action == "o":
            path = ensure_note(notes_dir, slug_for(d, "day"), "day")
            editor = os.environ.get("EDITOR", "nano")
            subprocess.call([editor, str(path)])
            console.print("  [green]entry updated[/green]\n")
        elif action == "s":
            mark_journal_day_skipped(store, d)
            console.print("  [yellow]skipped permanently[/yellow]\n")
        else:
            console.print("  [dim]deferred[/dim]\n")


def _plan_today(console: Console, notes_dir) -> None:
    console.print(
        "[bold]Plan today[/bold] — Vorhaben, eine Zeile pro Punkt "
        "(leere Zeile zum Abschließen, direkt leer = überspringen)"
    )
    lines: list[str] = []
    while True:
        line = console.input("  ")
        if not line.strip():
            break
        lines.append(line)

    text = "\n".join(lines)
    if text.strip():
        append_plan(notes_dir, text)
        console.print("[green]Added to today's plan.[/green]\n")
    else:
        console.print("[dim]Skipped.[/dim]\n")


def run_morning(console: Console, wm: WorkspaceManager, lookback: int = 7) -> None:
    try:
        store = wm.store()
        notes_dir = wm.notes_dir()
    except WorkspaceError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    console.print(f"\n[bold]Good morning[/bold] — {date.today().isoformat()}\n")
    _triage_todos(console, store)
    _assign_undated_todos(console, store)
    _fill_journal_gaps(console, notes_dir, store, lookback)
    _plan_today(console, notes_dir)
