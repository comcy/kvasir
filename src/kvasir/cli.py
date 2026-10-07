"""kvasir CLI entry point."""
import json
import sys
from pathlib import Path
from typing import Annotated

import typer

from kvasir import __version__
from kvasir import doctor as doctor_mod
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
from kvasir.platform import GitHub, detect_platform
from kvasir.platform.status import issue_status
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
    no_cli_check: Annotated[bool, typer.Option("--no-cli-check", help="Skip the gh check after registering")] = False,
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
    if _interactive() and not no_cli_check:  # a failed or declined check never undoes the registration
        doctor_mod.report(lambda: doctor_mod.repo_checks(url), True, _confirm, typer.echo)


def _confirm(question: str) -> bool:
    return typer.confirm(question, default=False)


@app.command()
def doctor() -> None:
    """Check prerequisites (git, gh, login, config) and offer to install a missing CLI."""
    raise typer.Exit(doctor_mod.report(doctor_mod.all_checks, _interactive(), _confirm, typer.echo))


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


_LABELS = {"done": "erledigt", "dropped": "verworfen", "blocked": "blockiert", "in_review": "in Review",
           "in_progress": "in Arbeit", "open": "offen"}


def _schedule_json(sc) -> dict:
    iso = lambda d: d.isoformat() if d else None
    return {"deadline": iso(sc.deadline),
            "deadlines": [{"date": iso(d.date), "label": d.label} for d in sc.deadlines],
            "planned_from": iso(sc.planned_from), "planned_to": iso(sc.planned_to)}


def _schedule_text(sc, indent: str) -> list[str]:
    lines = []
    if sc.deadlines:
        lines.append(f"{indent}    Frist: " + ", ".join(f"{d.date} ({d.label})" for d in sc.deadlines))
    if sc.planned_from:
        lines.append(f"{indent}    Geplant: {sc.planned_from} – {sc.planned_to}")
    return lines


def _item_json(s) -> dict:
    i = s.item
    return {"number": i.number, "title": i.title, "state": i.state, "state_reason": i.state_reason,
            "labels": list(i.labels), "status": s.status, "status_source": s.source, "reason": s.reason,
            "hint": s.hint, "schedule": _schedule_json(i.schedule), "notices": list(s.notices),
            "blocked_by": [{"repo": b.repo, "number": b.number, "state": b.state} for b in s.blocked_by],
            **({"stepper": _stepper_json(s.stepper)} if s.stepper else {})}


def _stepper_json(sp) -> dict:
    return {"level": sp.level, "steps": [{"name": x.name, "state": x.state} for x in sp.steps],
            **({"previous": list(sp.previous)} if sp.previous else {})}


def _item_text(s, indent: str) -> list[str]:
    name = _LABELS.get(s.status, s.status) + (" (laut Label)" if s.source == "label" else "")
    lines = [f"{indent}#{s.item.number} [{name}] {s.item.title}"]
    if s.blocked_by:
        lines.append(f"{indent}    blockiert von: " + ", ".join(f"#{b.number} ({b.state})" for b in s.blocked_by))
    lines += _schedule_text(s.item.schedule, indent)
    if s.hint:
        lines.append(f"{indent}    ! {s.hint}")
    lines += [f"{indent}    ! {n}" for n in s.notices]
    if s.stepper and s.stepper.steps:
        mark = {"done": "x", "current": ">", "open": " "}
        lines.append(f"{indent}    Schritte: " + " -> ".join(f"[{mark[x.state]}] {x.name}" for x in s.stepper.steps))
    if s.stepper and s.stepper.previous:
        lines.append(f"{indent}    Vorgänger: " + ", ".join(f"#{n}" for n in s.stepper.previous))
    return lines


@app.command()
def status(
    issue: Annotated[str, typer.Argument(help="Issue number, e.g. #13")],
    repo: Annotated[str | None, typer.Option(help="owner/repo (default: origin of the current directory)")] = None,
    format: Annotated[str, typer.Option(help="text | json")] = "text",
) -> None:
    """Sub-issues, blockers and status (from facts) of a GitHub issue. Read-only."""
    if format not in ("text", "json") or not issue.lstrip("#").isdigit():
        typer.echo("usage: kvasir status #<nr> [--repo owner/repo] [--format text|json]", err=True)
        raise typer.Exit(2)
    if repo is None:
        try:
            pr = detect_platform(repo_info(Path.cwd()).remote_url or "")
        except ValueError:
            pr = None
        if pr is None or pr.kind != "github":
            typer.echo("no GitHub repo here; pass --repo owner/repo", err=True)
            raise typer.Exit(2)
        repo = pr.slug
    res = issue_status(GitHub(repo), int(issue.lstrip("#")))
    if not res.ok:
        typer.echo(f"{res.error.kind.value}: {res.error.message}", err=True)
        raise typer.Exit(1)
    st = res.data
    if format == "json":
        typer.echo(json.dumps({"repo": st.repo, "issue": _item_json(st.issue),
                               "sub_issues": [_item_json(s) for s in st.sub_issues]}, ensure_ascii=False, indent=2))
        return
    lines = _item_text(st.issue, "")
    if st.sub_issues:
        lines.append("Sub-Issues:")
        for s in st.sub_issues:
            lines += _item_text(s, "  ")
    typer.echo("\n".join(lines))
