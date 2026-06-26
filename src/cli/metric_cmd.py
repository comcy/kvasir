"""mimirlink metric <sub-command>"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from src.workspace.manager import WorkspaceManager, WorkspaceError

app = typer.Typer(help="Track metrics (counters, durations, gauges).")
console = Console()


def _store():
    return WorkspaceManager().store()


@app.command("define")
def define(
    name: str = typer.Argument(..., help="Metric identifier, e.g. 'build_failures'"),
    label: str = typer.Option(..., "--label", "-l", help="Human label"),
    type: str = typer.Option("counter", "--type", "-t", help="counter | duration | gauge"),
    aggregation: str = typer.Option("weekly", "--agg", "-a", help="daily | weekly | monthly"),
) -> None:
    """Define a new metric."""
    try:
        store = _store()
    except WorkspaceError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    existing = store.find("metrics", name=name)
    if existing:
        console.print(f"[yellow]Metric '{name}' already exists.[/yellow]")
        return

    store.insert("metrics", {
        "id": str(uuid.uuid4()),
        "name": name,
        "label": label,
        "type": type,
        "aggregation": aggregation,
    })
    console.print(f"[green]Defined metric[/green] '{name}' ({type}, {aggregation})")


@app.command("record")
def record(
    name: str = typer.Argument(..., help="Metric name"),
    value: float = typer.Argument(..., help="Value to record (use +1 for counters)"),
) -> None:
    """Record a metric value."""
    try:
        store = _store()
    except WorkspaceError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    metrics = store.find("metrics", name=name)
    if not metrics:
        console.print(f"[red]Metric '{name}' not found. Define it first.[/red]")
        raise typer.Exit(1)

    store.insert("metric_values", {
        "id": str(uuid.uuid4()),
        "metric_id": metrics[0]["id"],
        "timestamp": datetime.now().isoformat(),
        "value": value,
    })
    console.print(f"[green]Recorded[/green] {name} = {value}")


@app.command("show")
def show(name: Optional[str] = typer.Argument(None, help="Metric name (all if omitted)")) -> None:
    """Show metric definitions and recent values."""
    try:
        store = _store()
    except WorkspaceError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    metrics = store.find("metrics", name=name) if name else store.all("metrics")
    if not metrics:
        console.print("[dim]No metrics defined.[/dim]")
        return

    values_all = store.all("metric_values")
    values_by_metric: dict[str, list] = {}
    for v in values_all:
        values_by_metric.setdefault(v["metric_id"], []).append(v)

    table = Table(show_header=True, header_style="bold")
    table.add_column("Name")
    table.add_column("Label")
    table.add_column("Type", width=10)
    table.add_column("Aggregation", width=10)
    table.add_column("Last value", width=12)
    table.add_column("Count", width=6)

    for m in metrics:
        vals = sorted(values_by_metric.get(m["id"], []), key=lambda v: v["timestamp"])
        last = vals[-1]["value"] if vals else "-"
        table.add_row(m["name"], m["label"], m["type"], m["aggregation"], str(last), str(len(vals)))

    console.print(table)
