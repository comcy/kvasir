"""Data and text for the overview page (#29): my PRs, review requests, my pipeline runs. No Textual.

`refresh` talks to the platforms (blocking, run in a worker) and fills `platform_cache.json` under the pseudo
repo key `overview`; `snapshot` reads only the cache. Registered GitHub and Azure DevOps Repos are shown.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime

from kvasir.platform import Error, ErrorKind, PipelineRun, PlatformRepo, PullRequest, cache
from kvasir.tui import platform_data
from kvasir.tui.data import RepoRow, format_age
from kvasir.tui.layout import cut, fit, group_entries
from kvasir.tui.platform_view import CHECKS, hint

KEY = "overview"
MAX_ITEMS = 20  # per list
SEARCH_LIMIT = 100  # search spans all my repos; filtered to the registered ones afterwards
RUN_DAYS = 7
REVIEWS = {"approved": "approved", "changes_requested": "changes requested"}
HINTS = {
    ErrorKind.MISSING_CLI: "gh nicht gefunden: GitHub CLI installieren (https://cli.github.com)",
    ErrorKind.NOT_LOGGED_IN: "gh nicht angemeldet: `gh auth login` ausführen",
}
AZ_HINTS = {
    ErrorKind.MISSING_CLI: "az nicht gefunden: Azure CLI installieren (https://aka.ms/installazurecli)",
    ErrorKind.NOT_LOGGED_IN: "az nicht angemeldet: `az login` ausführen",
    ErrorKind.MISSING_EXTENSION: "Erweiterung azure-devops fehlt: `az extension add --name azure-devops`",
}
SECTIONS = ("Meine offenen PRs", "Zum Review angefragt", f"Meine Pipeline-Läufe (letzte {RUN_DAYS} Tage)")


@dataclass
class Overview:
    mine: list[PullRequest] = field(default_factory=list)
    reviews: list[PullRequest] = field(default_factory=list)
    runs: list[PipelineRun] = field(default_factory=list)
    fetched_at: datetime | None = None  # of the PR list; None = never fetched
    error: Error | None = None  # last refresh error; the lists are the old state


@dataclass(frozen=True)
class Entry:
    text: str
    url: str
    repo: str  # "owner/repo"
    branch: str | None


def platform_repos(urls: list[str]) -> dict[str, str]:
    """Registered Repo urls -> {lower-case slug (`owner/repo`, `org/project/repo`): url}; unknown hosts are left out."""
    return {p.slug.lower(): u for u in urls if (p := platform_data.platform_of(u))}


def _scope(plat: PlatformRepo) -> str:
    """One search covers a scope: GitHub searches all my repos, Azure DevOps one project (no org-wide search)."""
    return plat.kind if plat.kind == "github" else f"azure:{plat.org}/{plat.project}".lower()


def _only(items: list, slugs) -> list:
    return [i for i in items if (i.repo or "").lower() in slugs][:MAX_ITEMS]


def _cached(query: str, cls: type) -> tuple[list, datetime | None]:
    e = cache.read(KEY, query, cls)
    return (e.items, e.fetched_at) if e else ([], None)


def snapshot(urls: list[str], error: Error | None = None) -> Overview:
    """Cache-only view (no network)."""
    slugs = platform_repos(urls)
    mine, at = _cached("my_prs", PullRequest)
    reviews, _ = _cached("review_requests", PullRequest)
    runs, _ = _cached("pipeline_runs", PipelineRun)
    return Overview(_only(mine, slugs), _only(reviews, slugs), _only(runs, slugs), at, error)


def refresh(urls: list[str]) -> Error | None:
    """Fetch the three lists into the cache. Blocking; returns the first error (None = fine).

    `gh search prs` has no review decision/checks/branch, so every shown PR (max MAX_ITEMS per list) gets
    one `pull_request` call. A search fails -> that scope is skipped; all scopes failed or a fatal PR error
    keeps the old cache entry of that list."""
    slugs = platform_repos(urls)
    plats = {s: platform_data.platform_of(u) for s, u in slugs.items()}
    providers = {s: platform_data.provider_for(p) for s, p in plats.items()}
    if not providers:
        return None
    searchers = {}
    for s, prov in providers.items():
        searchers.setdefault(_scope(plats[s]), prov)  # first repo of a scope does the search
    err, seen = None, {}
    for query, name in (("my_prs", "my_pull_requests"), ("review_requests", "review_requests")):
        found, first_err, any_ok = [], None, False
        for prov in searchers.values():
            res = getattr(prov, name)(SEARCH_LIMIT)
            any_ok = any_ok or res.ok
            if res.ok:
                found += res.data
            else:
                first_err = first_err or res.error
        if not any_ok:
            return first_err  # every scope failed: keep the old list
        err = err or first_err
        if len(searchers) > 1:
            found.sort(key=lambda p: p.created_at or "", reverse=True)
        out = []
        for p in _only(found, slugs):
            key = (p.repo.lower(), p.number)
            if key not in seen:
                full = providers[key[0]].pull_request(p.number)
                if not full.ok and full.error.kind in platform_data.FATAL:
                    return full.error
                seen[key] = replace(full.data, created_at=full.data.created_at or p.created_at) if full.ok else p
                err = err or (None if full.ok else full.error)
            out.append(seen[key])
        cache.write(KEY, query, out)
    runs, failed = [], False
    for s in slugs:
        res = providers[s].pipeline_runs(RUN_DAYS, MAX_ITEMS)
        if not res.ok:
            failed, err = True, err or res.error
            continue
        runs += [replace(r, repo=plats[s].slug) for r in res.data]
    if failed and not runs:
        return err  # nothing fetched (e.g. not logged in): keep the old runs
    cache.write(KEY, "pipeline_runs", sorted(runs, key=lambda r: r.started_at or "", reverse=True)[:MAX_ITEMS])
    return err


def _ago(iso: str | None, now: float | None) -> str:
    try:
        return format_age(int(datetime.fromisoformat(iso).astimezone(UTC).timestamp()), now) if iso else "-"
    except ValueError:
        return "-"


def review_text(pr: PullRequest) -> str:
    if pr.state == "draft":
        return "draft"
    return REVIEWS.get(pr.review or "", "ausstehend")


def run_symbol(r: PipelineRun) -> str:
    if r.status != "completed":
        return "…"
    return "✓" if r.conclusion == "success" else "✗" if r.conclusion == "failure" else r.conclusion or "?"


def _dur(s: int | None) -> str:
    return "-" if s is None else f"{s // 60}m{s % 60:02d}s" if s >= 60 else f"{s}s"


def pr_entry(pr: PullRequest, repo_w: int, title_w: int, now: float | None = None, with_author: bool = False) -> Entry:
    who = f"  @{pr.author}" if with_author else ""
    text = (f"{fit(pr.repo or '', repo_w)}  {fit('#' + str(pr.number), 5)}  {fit(pr.title, title_w)}{who}  "
            f"{fit(review_text(pr), 17)}  {CHECKS.get(pr.checks or '', '-')}  {_ago(pr.created_at, now).rjust(4)}")
    return Entry(text, pr.url, pr.repo or "", pr.branch)


def run_entry(r: PipelineRun, repo_w: int, wf_w: int, branch_w: int, now: float | None = None) -> Entry:
    text = (f"{fit(r.repo or '', repo_w)}  {fit(r.workflow, wf_w)}  {fit(r.branch, branch_w)}  "
            f"{run_symbol(r)} {fit(r.status, 11)}  {_dur(r.duration_s).rjust(7)}  {_ago(r.started_at, now).rjust(4)}")
    return Entry(text, r.url, r.repo or "", r.branch)


def sections(ov: Overview, width: int, now: float | None = None) -> list[tuple[str, list[Entry]]]:
    """(heading, entries) for the three sections; text lines are cut to `width`."""
    def cutall(entries):
        return [replace(e, text=cut(e.text, width)) for e in entries]

    def prs(items, author):
        rw = max((len(p.repo or "") for p in items), default=0)
        title_w = max(10, width - rw - 5 - 17 - 4 - 14 - (14 if author else 0))
        return cutall(pr_entry(p, rw, title_w, now, author) for p in items)

    rw = max((len(r.repo or "") for r in ov.runs), default=0)
    wf = min(max((len(r.workflow) for r in ov.runs), default=0), 24)
    br = min(max((len(r.branch) for r in ov.runs), default=0), 30)
    runs = cutall(run_entry(r, rw, wf, br, now) for r in ov.runs)
    return [(SECTIONS[0], prs(ov.mine, False)), (SECTIONS[1], prs(ov.reviews, True)), (SECTIONS[2], runs)]


def status_text(ov: Overview, n_repos: int, now: float | None = None) -> str:
    """Line on top of the page: age of the data and/or what is wrong."""
    if n_repos == 0:
        return "Kein GitHub-/Azure-DevOps-Repo registriert."
    lines = ["noch nicht geladen" if ov.fetched_at is None
             else f"aktualisiert vor {format_age(int(ov.fetched_at.timestamp()), now)}"]
    if ov.error:
        lines.append("! " + (AZ_HINTS if ov.error.cli == "az" else HINTS).get(ov.error.kind, hint(ov.error)))
    return "  ".join(lines)


def find_local(rows: list[RepoRow], url: str, branch: str | None) -> tuple[int, int] | None:
    """(row index, entry index) of a local Worktree/Branch `branch` in Repo `url`, for jumping in the main view."""
    if not branch:
        return None
    for ri, row in enumerate(rows):
        if row.url == url and row.view:
            entries = [e for g in group_entries(row.view, False) for e in g.visible]  # remote Branches come last
            for ei, e in enumerate(entries):
                if platform_data.branch_of(e) == branch and not getattr(e, "remote", False):
                    return ri, ei
    return None


def is_stale(ov: Overview, minutes: int) -> bool:
    return ov.fetched_at is None or time.time() - ov.fetched_at.timestamp() > minutes * 60
