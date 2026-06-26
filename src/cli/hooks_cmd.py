"""Hook management: install git hooks + internal hook runners."""
from __future__ import annotations

import stat
import subprocess
import sys
import uuid
from pathlib import Path

import typer
from rich.console import Console

console = Console()

# ── public app ───────────────────────────────────────────────────────────────

app = typer.Typer(help="Git hook management.")

# ── internal app (called by installed shell scripts) ─────────────────────────

hook_app = typer.Typer(help="Internal runners — called by git hooks.", hidden=True)

# ── hook shell script template ────────────────────────────────────────────────

_HOOK_SCRIPT = """\
#!/bin/sh
# Installed by mimirlink install-hooks — do not edit this header.
if command -v mimirlink >/dev/null 2>&1; then
    mimirlink hook {name} "$@"
    exit $?
fi
exit 0
"""

_HOOKS = {
    "commit-msg": "commit-msg",
    "post-commit": "post-commit",
}


# ── install-hooks ─────────────────────────────────────────────────────────────

@app.command("install-hooks")
def install_hooks(
    repo: Path = typer.Option(
        Path("."),
        "--repo", "-r",
        help="Git repo root (default: current directory)",
    ),
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite existing hooks"),
) -> None:
    """Install mimirlink git hooks into a git repository."""
    repo = repo.resolve()
    hooks_dir = repo / ".git" / "hooks"

    if not hooks_dir.exists():
        console.print(f"[red]Not a git repository: {repo}[/red]")
        raise typer.Exit(1)

    installed: list[str] = []
    skipped: list[str] = []

    for hook_name in _HOOKS:
        dest = hooks_dir / hook_name
        if dest.exists() and not force:
            # Check if it's already ours
            content = dest.read_text()
            if "mimirlink install-hooks" in content:
                installed.append(f"{hook_name} (already installed)")
                continue
            skipped.append(hook_name)
            console.print(
                f"[yellow]Skipped[/yellow] {hook_name} — file exists. "
                "Use [bold]--force[/bold] to overwrite."
            )
            continue

        script = _HOOK_SCRIPT.format(name=hook_name)
        dest.write_text(script)
        dest.chmod(dest.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        installed.append(hook_name)
        console.print(f"[green]Installed[/green] {dest.relative_to(repo)}")

    if installed:
        console.print(f"\n[dim]Hooks active in:[/dim] {repo}")
    if skipped:
        console.print(f"\n[yellow]Run with --force to overwrite skipped hooks.[/yellow]")


# ── internal: commit-msg ──────────────────────────────────────────────────────

@hook_app.command("commit-msg")
def _run_commit_msg(msg_file: str = typer.Argument(...)) -> None:
    """Validate commit message (Conventional Commits). Called by git hook."""
    from src.hooks.commit_validator import parse, strip_comments

    raw = Path(msg_file).read_text(encoding="utf-8")
    msg = strip_comments(raw)
    first_line = msg.splitlines()[0].strip() if msg else ""

    parsed = parse(first_line)
    if parsed is not None:
        raise typer.Exit(0)

    # Soft-warn
    console.print(
        "\n[yellow]⚠  mimirlink:[/yellow] commit message does not follow "
        "[bold]Conventional Commits[/bold] format.",
        highlight=False,
    )
    console.print(f"   Expected : [dim]<type>[(scope)][!]: <subject>[/dim]")
    console.print(f"   Example  : [green]feat(auth): add OAuth2 login[/green]")
    console.print(f"   Got      : [red]{first_line}[/red]\n")

    try:
        answer = input("   Commit anyway? [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        answer = "n"

    raise typer.Exit(0 if answer == "y" else 1)


# ── internal: post-commit ─────────────────────────────────────────────────────

@hook_app.command("post-commit")
def _run_post_commit() -> None:
    """Record last commit into commits.ndjson. Called by git hook."""
    from src.hooks.commit_validator import parse, strip_comments
    from src.workspace.manager import WorkspaceManager

    try:
        commit_hash = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL
        ).decode().strip()
        raw_msg = subprocess.check_output(
            ["git", "log", "-1", "--pretty=%B"], stderr=subprocess.DEVNULL
        ).decode().strip()
        commit_date = subprocess.check_output(
            ["git", "log", "-1", "--pretty=%cs"], stderr=subprocess.DEVNULL
        ).decode().strip()
    except subprocess.CalledProcessError:
        raise typer.Exit(0)

    msg = strip_comments(raw_msg)
    lines = msg.splitlines()
    first_line = lines[0].strip() if lines else ""
    body = "\n".join(lines[2:]).strip() if len(lines) > 2 else ""

    parsed = parse(first_line)
    breaking = bool(parsed and parsed.breaking) or "BREAKING CHANGE:" in body

    if parsed:
        record = {
            "id": str(uuid.uuid4()),
            "hash": commit_hash[:7],
            "type": parsed.type,
            "scope": parsed.scope,
            "subject": parsed.subject,
            "breaking": breaking,
            "date": commit_date,
            "body": body,
        }
    else:
        record = {
            "id": str(uuid.uuid4()),
            "hash": commit_hash[:7],
            "type": "wip",
            "scope": None,
            "subject": first_line,
            "breaking": False,
            "date": commit_date,
            "body": body,
        }

    try:
        wm = WorkspaceManager()
        wm.store().insert("commits", record)
    except Exception:
        pass  # never block the workflow on NDJSON write errors

    raise typer.Exit(0)
