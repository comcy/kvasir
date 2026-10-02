"""kvasir CLI entry point."""
import sys
from pathlib import Path
from typing import Annotated

import typer

from kvasir import __version__
from kvasir.clone import clone_bare
from kvasir.config import (
    DEFAULT_FETCH_MINUTES,
    DEFAULT_PATTERNS,
    RepoConfig,
    config_dir,
    default_open_command,
    load_local,
    load_repos,
    save_local,
    save_repos,
)
from kvasir.gitinfo import repo_info
from kvasir.repo_settings import PRESETS, preset_key, update_repo, validate_patterns
from kvasir.repo_url import normalize

app = typer.Typer(name="kvasir", help="Manage Git worktrees across repos.", no_args_is_help=True)


@app.callback()
def main() -> None:
    """Manage Git worktrees across repos."""


@app.command()
def version() -> None:
    """Print the version."""
    print(__version__)


def _is_url(arg: str) -> bool:
    if Path(arg).exists():
        return False
    try:
        normalize(arg)
    except ValueError:
        return False
    return True


def _interactive() -> bool:
    return sys.stdin.isatty()


def _ask_patterns(current: list[str] | None = None) -> list[str]:
    typer.echo(
        "Branch name templates:\n"
        "  1) Conventional Commits  {type}/{slug}\n"
        "  2) Work item             features/{id}-{slug}, fixes/{id}-{slug}\n"
        "  3) Both\n"
        "  4) Custom (comma-separated)"
    )
    choice = ""
    default = (preset_key(current) or "4") if current else "1"
    while choice not in (*PRESETS, "4"):
        choice = typer.prompt("Preset [1-4]", default=default)
    if choice in PRESETS:
        return list(PRESETS[choice])
    while True:
        try:
            return validate_patterns(typer.prompt("Templates", default=", ".join(current or []) or None).split(","))
        except ValueError as e:
            typer.echo(str(e), err=True)


def _reconfigure(url, known, pattern, fetch_interval, platform_interval) -> None:
    """Change only this repo's repos.toml entry; local.toml stays untouched."""
    if not known:
        typer.echo(f"{url} is not registered; run `kvasir setup` without --reconfigure", err=True)
        raise typer.Exit(1)
    if pattern or fetch_interval is not None or platform_interval is not None:
        changes = {"patterns": pattern, "fetch_interval": fetch_interval, "platform_interval": platform_interval}
    elif _interactive():
        cur = load_repos()[url]
        changes = {
            "patterns": _ask_patterns(cur.branch_patterns),
            "fetch_interval": typer.prompt("Fetch interval (minutes)", type=int, default=cur.fetch_interval),
            "platform_interval": typer.prompt("Platform interval (minutes)", type=int, default=cur.platform_interval),
        }
    else:
        typer.echo("--reconfigure without a terminal needs -p, --fetch-interval or --platform-interval", err=True)
        raise typer.Exit(1)
    try:
        update_repo(url, **changes)
    except ValueError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1)
    typer.echo(f"Reconfigured {url}")


@app.command()
def setup(
    path: Annotated[str, typer.Argument(help="Repo URL to clone, or any path inside a repo to register")] = ".",
    target: Annotated[Path | None, typer.Argument(help="Clone target dir (URL mode; default: repo name)")] = None,
    pattern: Annotated[
        list[str] | None,
        typer.Option("--pattern", "-p", help="Branch name template, repeatable. Placeholders: {type} {id} {slug} {date}"),
    ] = None,
    fetch_interval: Annotated[int | None, typer.Option(help="Minutes between fetches")] = None,
    platform_interval: Annotated[int | None, typer.Option(help="Minutes between PR/issue/pipeline refreshes")] = None,
    reconfigure: Annotated[bool, typer.Option("--reconfigure", help="Change settings of a registered repo")] = False,
) -> None:
    """Clone a URL into the bare layout and register it, or register an existing repo."""
    try:
        if _is_url(path):
            path = str(clone_bare(path, target))
            typer.echo(f"Cloned into {path}")
        info = repo_info(Path(path))
    except ValueError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1)
    if not info.remote_url:
        typer.echo("repo has no 'origin' remote; not supported yet", err=True)
        raise typer.Exit(1)
    try:
        url = normalize(info.remote_url)
    except ValueError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1)

    repos = load_repos()
    known = url in repos
    cfg = repos.get(url) or RepoConfig(list(DEFAULT_PATTERNS), DEFAULT_FETCH_MINUTES)
    if reconfigure:
        _reconfigure(url, known, pattern, fetch_interval, platform_interval)
        return
    local = load_local()
    if not known and not pattern and fetch_interval is None and _interactive():
        cfg.branch_patterns = _ask_patterns()
        cfg.fetch_interval = typer.prompt("Fetch interval (minutes)", type=int, default=cfg.fetch_interval)
        if local.open_command is None:
            local.open_command = typer.prompt("Open command", default=default_open_command())
    if pattern:
        try:
            cfg.branch_patterns = validate_patterns(pattern)
        except ValueError as e:
            typer.echo(str(e), err=True)
            raise typer.Exit(1) from e
    if fetch_interval is not None:
        cfg.fetch_interval = fetch_interval
    if platform_interval is not None:
        cfg.platform_interval = platform_interval
    repos[url] = cfg
    save_repos(repos)

    local.paths[url] = str(info.root)
    save_local(local)

    layout = "bare layout" if info.bare_layout else "normal clone (overview only)"
    typer.echo(f"{'Updated' if known else 'Registered'} {url} [{layout}] at {info.root}")


@app.command()
def config(path: Annotated[bool, typer.Option("--path", help="Only print the config directory")] = False) -> None:
    """Show config directory and the contents of repos.toml and local.toml."""
    typer.echo(config_dir())
    if path:
        return
    for name in ("repos.toml", "local.toml"):
        f = config_dir() / name
        typer.echo(f"\n# {f}" + ("" if f.exists() else " (missing)"))
        if f.exists():
            typer.echo(f.read_text(encoding="utf-8").rstrip())


@app.command()
def tui() -> None:
    """Open the three-column overview (read-only)."""
    from kvasir.tui.app import KvasirApp

    KvasirApp().run()
