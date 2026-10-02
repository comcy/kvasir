"""Plain-text rendering of platform data (markers, detail panel, repo status line). No Textual, no I/O."""
from __future__ import annotations

from datetime import UTC, datetime

from kvasir.platform import Error, ErrorKind, PipelineRun, PullRequest, WorkItem
from kvasir.tui.data import format_age
from kvasir.tui.layout import entry_name
from kvasir.tui.platform_data import BranchInfo, Snapshot, branch_of
from kvasir.worktrees import Branch, Worktree

CHECKS = {"success": "✓", "failure": "✗", "pending": "…"}
AZ_HINTS = {
    ErrorKind.MISSING_CLI: "az nicht gefunden",
    ErrorKind.NOT_LOGGED_IN: "az nicht angemeldet",
    ErrorKind.MISSING_EXTENSION: "Erweiterung azure-devops fehlt",
    ErrorKind.MISSING_SCOPE: "Berechtigung fehlt",
    ErrorKind.NETWORK: "Netz nicht erreichbar",
    ErrorKind.RATE_LIMIT: "Azure-DevOps-Rate-Limit erreicht",
    ErrorKind.OTHER: "az-Fehler",
}
HINTS = {
    ErrorKind.MISSING_CLI: "gh nicht gefunden",
    ErrorKind.NOT_LOGGED_IN: "gh nicht angemeldet",
    ErrorKind.MISSING_SCOPE: "read:project fehlt",
    ErrorKind.NETWORK: "Netz nicht erreichbar",
    ErrorKind.RATE_LIMIT: "GitHub-Rate-Limit erreicht",
    ErrorKind.OTHER: "gh-Fehler",
    ErrorKind.MISSING_EXTENSION: "gh-Erweiterung fehlt",  # not produced by gh
}


def hint(error: Error) -> str:
    return (AZ_HINTS if error.cli == "az" else HINTS)[error.kind]


def marker(pr: PullRequest | None) -> str:
    """`#12 ✓` / `#12 ✗` / `#12 …` (checks), `#12` (no checks), `draft`, `#12 merged`, `#12 closed`; "" = no PR."""
    if pr is None:
        return ""
    if pr.state == "draft":
        return "draft"
    if pr.state == "open":
        return f"#{pr.number} {CHECKS.get(pr.checks or '', '')}".strip()
    return f"#{pr.number} {pr.state}"


def markers(snap: Snapshot, entries: list[Worktree | Branch]) -> dict[str, str]:
    """entry name (as shown in the list) -> marker, only entries that have one."""
    out = {entry_name(e): marker(snap.info(b).pr) for e in entries if (b := branch_of(e))}
    return {n: m for n, m in out.items() if m}


def repo_line(snap: Snapshot, now: float | None = None) -> str:
    """Status for the Repo column: age of the data and/or the reason it is stale."""
    if snap.fetched_at is None:
        parts = [f"{snap.cli}: noch nicht geladen"]
    else:
        parts = [f"{snap.cli}: aktualisiert vor {format_age(int(snap.fetched_at.timestamp()), now)}"]
    if snap.error:
        parts.append(hint(snap.error))
    return "\n".join(parts)


def _pr(pr: PullRequest | None) -> list[str]:
    if pr is None:
        return ["PR: kein PR"]
    state = {"open": "offen", "draft": "Draft", "merged": "gemergt", "closed": "geschlossen"}.get(pr.state, pr.state)
    bits = [state]
    if pr.review:
        bits.append(f"Review: {pr.review}")
    bits.append(f"Checks: {CHECKS.get(pr.checks or '', 'keine')}")
    return [f"PR #{pr.number}  {pr.title}", "  " + " · ".join(bits)]


def _item(wi: WorkItem | None, number: int | None) -> list[str]:
    if wi is None:
        return ["Work Item: kein Work Item"] if number is None else [f"Work Item #{number}: nicht geladen"]
    bits = ["offen" if wi.state == "open" else "geschlossen"]
    if wi.labels:
        bits.append("Labels: " + ", ".join(wi.labels))
    if wi.assignees:
        bits.append("Zugewiesen: " + ", ".join(wi.assignees))
    if not wi.board_available:
        bits.append("Board-Status: nicht verfügbar (read:project fehlt)")
    elif wi.board_status:
        bits.append(f"Board: {wi.board_status}")
    return [f"Work Item #{wi.number}  {wi.title}", "  " + " · ".join(bits)]


def _run(r: PipelineRun, now: float | None) -> str:
    sym = ("…" if r.status != "completed" else "✓" if r.conclusion == "success"
           else "✗" if r.conclusion == "failure" else r.conclusion or "?")
    when = "-"
    if r.started_at:
        try:
            when = format_age(int(datetime.fromisoformat(r.started_at).astimezone(UTC).timestamp()), now)
        except ValueError:
            pass
    dur = f"  {r.duration_s}s" if r.duration_s is not None else ""
    return f"  {sym} {r.workflow}  {when}{dur}"


def detail_text(info: BranchInfo, error: Error | None = None, now: float | None = None) -> str:
    """Detail-panel block for one branch."""
    if not info.loaded:
        lines = ["Plattform: noch nicht geladen"]
    else:
        runs = [_run(r, now) for r in info.runs[:5]] or ["  keine Läufe"]
        lines = [*_pr(info.pr), "", *_item(info.work_item, info.work_item_number), "", "Pipelines:", *runs]
    if error:
        lines += ["", f"! {hint(error)}"]
    return "\n".join(lines)
