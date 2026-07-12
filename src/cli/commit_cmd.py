"""Interactive Conventional Commit generator."""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import typer
from rich.console import Console
from rich.prompt import Confirm, Prompt


def _staged_files(root: Path) -> list[str]:
    out = subprocess.check_output(
        ["git", "diff", "--staged", "--name-only"], cwd=str(root),
    ).decode()
    return [line for line in out.splitlines() if line.strip()]


def _require_root(console: Console) -> Path:
    from src.data.projects import project_root

    root = project_root(Path.cwd())
    if root is None:
        console.print("[red]Not inside a project (no git repo found from cwd).[/red]")
        raise typer.Exit(1)
    return root


def _read_body(console: Console) -> str:
    console.print(
        "[bold]Body[/bold] — optional, one line per point "
        "(blank line to finish, blank immediately = skip)"
    )
    lines: list[str] = []
    while True:
        line = console.input("  ")
        if not line.strip():
            break
        lines.append(line)
    return "\n".join(lines)


def run_commit(console: Console) -> None:
    """Compose and run a Conventional Commit for the staged changes."""
    from src.data.scopes import detect_scope, suggest_type
    from src.hooks.commit_validator import TYPES, parse

    root = _require_root(console)
    staged = _staged_files(root)
    if not staged:
        console.print("[red]Nothing staged — use `git add` first.[/red]")
        raise typer.Exit(1)

    dominant_scope, breakdown = detect_scope(root, staged)
    if len(breakdown) > 1:
        parts = ", ".join(f"{s}({n})" for s, n in sorted(breakdown.items(), key=lambda kv: -kv[1]))
        console.print(f"[yellow]Changes span multiple scopes:[/yellow] {parts} — using [bold]{dominant_scope}[/bold]")

    suggested_type = suggest_type(staged)
    console.print(f"\n[bold]{len(staged)}[/bold] file(s) staged.\n")

    while True:
        ctype = Prompt.ask("Type", choices=list(TYPES), default=suggested_type or "feat")
        scope = Prompt.ask("Scope", default=dominant_scope or "").strip()
        breaking = Confirm.ask("Breaking change?", default=False)
        subject = Prompt.ask("Subject").strip()
        if not subject:
            console.print("[red]Subject is required.[/red]\n")
            continue

        scope_part = f"({scope})" if scope else ""
        bang = "!" if breaking else ""
        first_line = f"{ctype}{scope_part}{bang}: {subject}"

        if parse(first_line) is None:
            console.print(f"[red]Not a valid Conventional Commit:[/red] {first_line}\n")
            continue
        break

    body = _read_body(console)
    message = first_line if not body.strip() else f"{first_line}\n\n{body}"

    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write(message)
        msg_path = f.name

    try:
        subprocess.run(["git", "commit", "-F", msg_path], cwd=str(root), check=True)
    except subprocess.CalledProcessError:
        console.print("[red]git commit failed.[/red]")
        raise typer.Exit(1)
    finally:
        Path(msg_path).unlink(missing_ok=True)

    console.print(f"\n[green]Committed:[/green] {first_line}")
