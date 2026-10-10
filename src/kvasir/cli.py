"""kvasir CLI entry point."""
import json
import sys
from pathlib import Path
from typing import Annotated

import typer

from kvasir import __version__, repo_file, report_out
from kvasir import doctor as doctor_mod
from kvasir import metrics as metrics_mod
from kvasir import report as report_mod
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
from kvasir.platform import GitHub, PlatformRepo, detect_platform, provider_for
from kvasir.platform.graph import WARN_NODES, issue_graph
from kvasir.platform.status import issue_status, open_features
from kvasir.platform.stepper import check_detector
from kvasir.repo_settings import PRESETS, preset_key, update_repo, validate_patterns
from kvasir.repo_url import normalize
from kvasir.status_view import render, schedule_lines, status_name

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
    shared = not known and not pattern and repo_file.repo_patterns(info.root)
    if shared:  # kvasir.toml decides until the user sets a local override
        cfg.patterns_set = False
        typer.echo(f"Branch templates from {repo_file.FILE}: {', '.join(shared)}")
    if not known and not pattern and fetch_interval is None and _interactive():
        if not shared:
            cfg.branch_patterns = _ask_patterns()
        cfg.fetch_interval = typer.prompt("Fetch interval (minutes)", type=int, default=cfg.fetch_interval)
        if local.open_command is None:
            local.open_command = typer.prompt("Open command", default=default_open_command())
    if pattern:
        try:
            cfg.branch_patterns = validate_patterns(pattern)
            cfg.patterns_set = True
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


def _ask_phases(current) -> list:
    """Per phase: keep, change done_when, or drop. Only known detectors are accepted."""
    out = []
    for name, specs in current:
        while True:
            ans = typer.prompt(f"{name}: done_when (Komma = UND, '-' = nicht erkennbar, 'skip' = Phase streichen)",
                               default=", ".join(specs) or "-").strip()
            if ans == "skip":
                break
            new = tuple(x.strip() for x in ans.split(",") if x.strip() not in ("", "-"))
            if errs := [e for x in new if (e := check_detector(x))]:
                typer.echo("; ".join(errs), err=True)
                continue
            out.append((name, new))
            break
    return out


@app.command()
def init(
    pattern: Annotated[list[str] | None, typer.Option("--pattern", "-p", help="Branch template, repeatable")] = None,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Write without asking (the diff is still printed)")] = False,
) -> None:
    """Create or update kvasir.toml in the repo root: shows the diff first, never overwrites silently."""
    import difflib
    root = repo_file.checkout_root(Path.cwd())
    try:
        old_data = repo_file.load(root)
    except ValueError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1)
    cur = repo_file.repo_patterns(root)
    try:
        patterns = validate_patterns(pattern) if pattern else _ask_patterns(cur) if _interactive() else cur
    except ValueError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1)
    phases = None
    if _interactive() and not typer.confirm("Standardprozess übernehmen (Phasen aus workflow/phases.tsv bzw. eingebaut)?",
                                            default=True):
        phases = _ask_phases(repo_file.load_phases(root))
    elif "phases" in old_data and not _interactive():
        phases = repo_file.load_phases(root)  # keep existing overrides when not asking
    target = root / repo_file.FILE
    old = target.read_text(encoding="utf-8") if target.exists() else ""
    new = repo_file.render(patterns, phases)
    if new == old:
        typer.echo(f"{repo_file.FILE} unchanged")
        return
    typer.echo("".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True),
                                            f"a/{repo_file.FILE}", f"b/{repo_file.FILE}")), nl=False)
    if not (yes or (_interactive() and typer.confirm(f"Write {target}?", default=False))):
        typer.echo("not written (use --yes to write)", err=True)
        raise typer.Exit(1)
    target.write_text(new, encoding="utf-8")
    typer.echo(f"Wrote {target}")


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


def _schedule_json(sc) -> dict:
    iso = lambda d: d.isoformat() if d else None
    return {"deadline": iso(sc.deadline),
            "deadlines": [{"date": iso(d.date), "label": d.label} for d in sc.deadlines],
            "planned_from": iso(sc.planned_from), "planned_to": iso(sc.planned_to)}


def _item_json(s) -> dict:
    i = s.item
    return {"number": i.number, "title": i.title, "state": i.state, "state_reason": i.state_reason,
            "labels": list(i.labels), "status": s.status, "status_source": s.source, "reason": s.reason,
            "hint": s.hint, "schedule": _schedule_json(i.schedule), "notices": list(s.notices),
            "blocked_by": [{"repo": b.repo, "number": b.number, "state": b.state} for b in s.blocked_by],
            "parent": i.parent, "children": list(s.children), "prio": i.prio, "succ": list(s.succ),
            "prev": [{"repo": b.repo, "number": b.number, "state": b.state} for b in s.blocked_by],
            **({"stepper": _stepper_json(s.stepper)} if s.stepper else {})}


def _stepper_json(sp) -> dict:
    return {"level": sp.level, "steps": [{"name": x.name, "state": x.state} for x in sp.steps],
            **({"previous": list(sp.previous)} if sp.previous else {})}


def _item_text(s, indent: str) -> list[str]:
    lines = [f"{indent}#{s.item.number} [{status_name(s)}] {s.item.title}"]
    if s.blocked_by:
        lines.append(f"{indent}    blockiert von: " + ", ".join(f"#{b.number} ({b.state})" for b in s.blocked_by))
    lines += [f"{indent}    {x}" for x in schedule_lines(s.item.schedule)]
    if s.hint:
        lines.append(f"{indent}    ! {s.hint}")
    lines += [f"{indent}    ! {n}" for n in s.notices]
    if s.stepper and s.stepper.steps:
        mark = {"done": "x", "current": ">", "open": " "}
        lines.append(f"{indent}    Schritte: " + " -> ".join(f"[{mark[x.state]}] {x.name}" for x in s.stepper.steps))
    if s.stepper and s.stepper.previous:
        lines.append(f"{indent}    Vorgänger: " + ", ".join(f"#{n}" for n in s.stepper.previous))
    return lines


FEATURE_WARN = 10


def _status_json(st) -> dict:
    return {"repo": st.repo, "issue": _item_json(st.issue), "sub_issues": [_item_json(s) for s in st.sub_issues]}


@app.command()
def status(
    issue: Annotated[str | None, typer.Argument(help="Issue number, e.g. #13; without: all open features")] = None,
    repo: Annotated[str | None, typer.Option(help="owner/repo (default: origin of the current directory)")] = None,
    format: Annotated[str, typer.Option(help="table | text | json")] = "table",
    layout: Annotated[str, typer.Option(help="tree | split (table only)")] = "tree",
    limit: Annotated[int | None, typer.Option(help="without issue: show at most N features")] = None,
) -> None:
    """Sub-issue tree, blockers (prev/succ), priority and status (from facts) of a GitHub issue or Azure DevOps work item. Read-only."""
    if format not in ("table", "text", "json") or layout not in ("tree", "split") or (
            issue is not None and not issue.lstrip("#").isdigit()):
        typer.echo("usage: kvasir status [#<nr>] [--repo owner/repo] [--format table|text|json] "
                   "[--layout tree|split] [--limit N]", err=True)
        raise typer.Exit(2)
    if repo is None:
        try:
            pr = detect_platform(repo_info(Path.cwd()).remote_url or "")
        except ValueError:
            pr = None
        if pr is None:
            typer.echo("no GitHub/Azure DevOps repo here; pass --repo owner/repo", err=True)
            raise typer.Exit(2)
    else:
        pr = PlatformRepo("github", repo)
    phases = repo_file.load_phases(repo_file.checkout_root(Path.cwd()))
    gh = provider_for(pr)
    if issue is not None:
        numbers = [int(issue.lstrip("#"))]
    else:
        if not hasattr(gh, "issues"):
            typer.echo("without an issue number only GitHub is supported", err=True)
            raise typer.Exit(2)
        feats = open_features(gh)
        if not feats.ok:
            typer.echo(f"{feats.error.kind.value}: {feats.error.message}", err=True)
            raise typer.Exit(1)
        numbers = feats.data
        if limit is None and len(numbers) >= FEATURE_WARN:
            typer.echo(f"Warnung: {len(numbers)} offene Features; mit --limit N begrenzen", err=True)
        numbers = numbers[:limit]
    sts = []
    for n in numbers:  # ponytail: je Feature eigene Aufrufe; geteilte PR-/Branch-Abfrage erst bei Bedarf
        res = issue_status(gh, n, phases)
        if not res.ok:
            typer.echo(f"{res.error.kind.value}: {res.error.message}", err=True)
            raise typer.Exit(1)
        sts.append(res.data)
    if format == "json":
        data = _status_json(sts[0]) if issue is not None else {"features": [_status_json(x) for x in sts]}
        typer.echo(json.dumps(data, ensure_ascii=False, indent=2))
        return
    if format == "table":
        typer.echo("\n\n".join(render(x, layout) for x in sts) or "keine offenen Features")
        return
    lines = []
    for st in sts:
        lines += _item_text(st.issue, "")
        if st.sub_issues:
            lines.append("Sub-Issues:")
            for s in st.sub_issues:
                lines += _item_text(s, "  ")
    typer.echo("\n".join(lines))


@app.command()
def graph(
    issue: Annotated[str | None, typer.Argument(help="Limit to one feature, e.g. #13")] = None,
    repo: Annotated[str | None, typer.Option(help="owner/repo (default: origin of the current directory)")] = None,
    milestone: Annotated[str | None, typer.Option(help="Limit to a milestone (title)")] = None,
    format: Annotated[str, typer.Option(help="mermaid | html")] = "mermaid",
    out: Annotated[Path | None, typer.Option(help="Write to file instead of stdout")] = None,
) -> None:
    """Mermaid or standalone HTML graph of open issues (+14 days of closed ones): lanes per feature, blockers, status colours. Read-only."""
    if format not in ("mermaid", "html") or (issue is not None and not issue.lstrip("#").isdigit()):
        typer.echo("usage: kvasir graph [#<nr>] [--milestone <name>] [--repo owner/repo] [--out file]", err=True)
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
    res = issue_graph(GitHub(repo), int(issue.lstrip("#")) if issue else None, milestone, fmt=format)
    if not res.ok:
        typer.echo(f"{res.error.kind.value}: {res.error.message}", err=True)
        raise typer.Exit(1)
    text, nodes = res.data
    if nodes >= WARN_NODES:
        typer.echo(f"warning: {nodes} nodes; narrow down with #<nr> or --milestone <name>", err=True)
    if out:
        out.write_text(text, encoding="utf-8")
    else:
        typer.echo(text, nl=False)


@app.command()
def metrics(
    since: Annotated[str, typer.Option(help="Zeitraum, z. B. 30d")] = "30d",
    repo: Annotated[str | None, typer.Option(help="owner/repo (default: origin of the current directory)")] = None,
    evals: Annotated[Path | None, typer.Option(help="Ordner mit Eval-Berichten (default: evals/reports/ des Checkouts)")] = None,
    format: Annotated[str, typer.Option(help="text | json | markdown")] = "text",
) -> None:
    """Kennzahlen aus workflow/metrics.tsv (text, json, markdown). Read-only; GitHub oder Azure DevOps (wie status), lokale Eval-Berichte."""
    if format not in ("text", "json", "markdown"):
        typer.echo("--format: expected text | json | markdown", err=True)
        raise typer.Exit(2)
    try:
        span = metrics_mod.parse_since(since)
    except ValueError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(2) from e
    try:
        pr = PlatformRepo("github", repo) if repo else detect_platform(repo_info(Path.cwd()).remote_url or "")
    except ValueError:
        pr = None
    if pr is None:
        typer.echo("no GitHub/Azure DevOps repo here; pass --repo owner/repo", err=True)
        raise typer.Exit(2)
    root = repo_file.checkout_root(Path.cwd())
    try:
        rows = repo_file._tsv(root, metrics_mod.METRICS_TSV)
    except OSError as e:
        typer.echo(f"{metrics_mod.METRICS_TSV}: {e.strerror or e}", err=True)
        raise typer.Exit(1) from e
    gh, since_dt = provider_for(pr), metrics_mod.now() - span
    srcs = {r.get("source") for r in rows}
    res = metrics_mod.events(gh, since_dt, srcs, metrics_mod.status_labels(root))
    rework = metrics_mod.rework_counts(gh, since_dt) if "rework_fixes_per_change" in srcs and isinstance(gh, GitHub) else None  # Azure: unbekannt
    for r in (res, rework):
        if r is not None and not r.ok:
            typer.echo(f"{r.error.kind.value}: {r.error.message}", err=True)
            raise typer.Exit(1)
    pass_list = metrics_mod.eval_results(evals or root / metrics_mod.EVALS_DIR) if "eval_pass_rate" in srcs else None
    lines = metrics_mod.report(rows, res.data, pass_list, rework.data if rework else None)
    if format == "json":
        typer.echo(metrics_mod.to_json(lines), nl=False)
    elif format == "markdown":
        typer.echo(metrics_mod.to_markdown(lines), nl=False)
    else:
        for ln in lines:
            typer.echo(f"{ln.name or ln.id}: {ln.text}")


@app.command()
def today(
    date: Annotated[str | None, typer.Option(help="Tag YYYY-MM-DD (default: heute)")] = None,
    format: Annotated[str, typer.Option(help="md | json")] = "md",
    out: Annotated[Path | None, typer.Option(help="Write to file instead of stdout; {date} is replaced; default: [report] output")] = None,
    stdout: Annotated[bool, typer.Option("--stdout", help="Only print to stdout, ignore --out and [report]")] = False,
) -> None:
    """Bericht eines Tages: Commits, Notizen, Statuswechsel, uncommittete Arbeit je Repo. Schreibt nur den Snapshot ins Tageslog und --out."""
    from datetime import date as date_cls
    try:
        day = date_cls.fromisoformat(date) if date else date_cls.today()
    except ValueError:
        typer.echo("--date: expected YYYY-MM-DD", err=True)
        raise typer.Exit(2) from None
    if format not in ("md", "json"):
        typer.echo("--format: expected md | json", err=True)
        raise typer.Exit(2)
    if day == date_cls.today():
        report_mod.snapshot_today()
    rep = report_mod.build(day)
    text = json.dumps(rep, ensure_ascii=False, indent=2) + "\n" if format == "json" else report_mod.to_markdown(rep)
    raw = load_local().report
    try:
        rcfg = report_out.parse(raw) if raw else None
    except ValueError as e:
        if not stdout:
            typer.echo(f"[report] invalid: {e}", err=True)
            raise typer.Exit(2) from None
        rcfg = None
    dest = None if stdout else (out or (rcfg.output if rcfg else None))
    if dest:
        mode, heading = (rcfg.mode, rcfg.heading) if rcfg else ("overwrite", report_out.DEFAULT_HEADING)
        try:
            report_out.write(report_out.target(dest, day), text, "overwrite" if format == "json" else mode, heading)
        except (ValueError, OSError) as e:
            typer.echo(str(e), err=True)
            raise typer.Exit(1) from None
    else:
        typer.echo(text, nl=False)
