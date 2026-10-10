"""Platform data for the TUI: fetch (blocking, run in a worker) and merge with the cache. No Textual.

`refresh` talks to the provider and fills `platform_cache.json`; `snapshot` reads only the cache, so it
is cheap, works offline and is what the UI shows. Interfaces for the overview (#29): `refresh`,
`snapshot`, `Snapshot.info`, `branch_names`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from kvasir import daylog
from kvasir.platform import (
    Error,
    ErrorKind,
    PipelineRun,
    PlatformRepo,
    Provider,
    PullRequest,
    WorkItem,
    cache,
    detect_platform,
    provider_for,
    work_item_for,
)
from kvasir.platform.models import ItemStatus
from kvasir.platform.status import issue_status
from kvasir.worktrees import Branch, RepoView, Worktree

PR_LIMIT = 50
RUN_LIMIT = 50
RUN_DAYS = 7
MAX_ITEMS = 20  # ponytail: one work item call per id, capped; raise if repos with many branches need more
MAX_STATUS = 8  # ponytail: issue_status is ~5 gh calls per issue, so far fewer than MAX_ITEMS
FATAL = (ErrorKind.MISSING_CLI, ErrorKind.MISSING_EXTENSION, ErrorKind.NOT_LOGGED_IN, ErrorKind.NETWORK, ErrorKind.RATE_LIMIT)


@dataclass(frozen=True)
class StatusCard:
    """Flat, cacheable extract of `ItemStatus` (the `kvasir status` core) for the detail panel."""
    number: int
    status: str
    source: str
    reason: str | None = None
    hint: str | None = None
    blockers: tuple[str, ...] = ()  # "#13 (open)"
    notices: tuple[str, ...] = ()
    steps: tuple[str, ...] = ()  # "done|name", "current|name", "open|name"
    previous: tuple[int, ...] = ()


def card_of(st: ItemStatus) -> StatusCard:
    sp = st.stepper
    return StatusCard(st.item.number, st.status, st.source, st.reason, st.hint,
                      tuple(f"#{b.number} ({b.state})" for b in st.blocked_by), st.notices,
                      tuple(f"{x.state}|{x.name}" for x in sp.steps) if sp else (), sp.previous if sp else ())


@dataclass(frozen=True)
class BranchInfo:
    pr: PullRequest | None
    work_item: WorkItem | None
    work_item_number: int | None  # known id, even when the issue itself is not cached
    runs: tuple[PipelineRun, ...]
    loaded: bool  # False: nothing fetched yet (no cache), so "kein PR" would be a lie
    status: StatusCard | None = None


@dataclass
class Snapshot:
    prs: list[PullRequest]
    runs: list[PipelineRun]
    items: dict[int, WorkItem]
    patterns: list[str]
    fetched_at: datetime | None  # of the PR list; None = never fetched
    error: Error | None = None  # last refresh error; the data above is the old state
    cli: str = "gh"  # CLI of the repo's platform, for texts: "gh" | "az"
    cards: dict[int, StatusCard] = field(default_factory=dict)  # issue number -> status (GitHub only)

    def info(self, branch: str) -> BranchInfo:
        mine = [p for p in self.prs if p.branch == branch]  # newest first
        pr = next((p for p in mine if p.state in ("open", "draft")), mine[0] if mine else None)
        n = work_item_for(branch, self.patterns, self.prs)
        runs = tuple(r for r in self.runs if r.branch == branch)
        return BranchInfo(pr, self.items.get(n) if n else None, n, runs, self.fetched_at is not None,
                          self.cards.get(n) if n else None)


def platform_of(url: str) -> PlatformRepo | None:
    """Platform of a registered Repo (identity `github.com/o/r`, no scheme); None = not supported."""
    return detect_platform("https://" + url)


def branch_of(entry: Worktree | Branch) -> str | None:
    """Plain branch name of an entry (`origin/feat/x` -> `feat/x`); None for detached/broken/HEAD."""
    if isinstance(entry, Worktree):
        return None if entry.broken else entry.branch
    if entry.remote:
        name = entry.name.split("/", 1)[-1]
        return None if name == "HEAD" else name
    return entry.name


def branch_names(view: RepoView) -> list[str]:
    names = (branch_of(e) for e in [*view.worktrees, *view.branches])
    return sorted({n for n in names if n})


def _numbers(branches: list[str], patterns: list[str], prs: list[PullRequest]) -> list[int]:
    found = {work_item_for(b, patterns, prs) for b in branches}
    return sorted((n for n in found if n), reverse=True)[:MAX_ITEMS]


def _cached(url: str, query: str, cls: type) -> list:
    e = cache.read(url, query, cls)
    return e.items if e else []


def snapshot(url: str, patterns: list[str], branches: list[str], error: Error | None = None) -> Snapshot:
    """Cache-only view (no network)."""
    e = cache.read(url, "pull_requests", PullRequest)
    prs = e.items if e else []
    items, cards = {}, {}
    for n in _numbers(branches, patterns, prs):
        if found := _cached(url, f"work_item:{n}", WorkItem):
            items[n] = found[0]
        if found := _cached(url, f"status:{n}", StatusCard):
            cards[n] = found[0]
    plat = platform_of(url)
    return Snapshot(prs, _cached(url, "pipeline_runs", PipelineRun), items, patterns,
                    e.fetched_at if e else None, error, "az" if plat and plat.kind == "azure" else "gh", cards)


def _log_changes(url: str, kind: str, old: dict[int, str] | None, new: list) -> None:
    """Day log: new vs. cached state per number. `old` None (no baseline) = nothing known, nothing logged."""
    if old is None:
        return
    for x in new:
        if x.number not in old or old[x.number] != x.state:
            daylog.record({"type": kind, "url": url, "number": x.number, "title": x.title,
                           "old": old.get(x.number), "new": x.state})


def refresh(url: str, patterns: list[str], branches: list[str], provider: Provider | None = None) -> Error | None:
    """Fetch PR list, run list and the needed issues (one call each) into the cache. Blocking.

    Returns the first error that matters (None = all fine); whatever succeeded is cached, the rest keeps
    its old cache entry. A single unknown issue (kind OTHER) is skipped silently."""
    plat = platform_of(url)
    if plat is None:
        return None
    p = provider or provider_for(plat)
    err = None
    prs = p.pull_requests(PR_LIMIT)
    if prs.ok:
        old = cache.read(url, "pull_requests", PullRequest)
        cache.write(url, "pull_requests", prs.data)
        _log_changes(url, "pr_state", {x.number: x.state for x in old.items} if old else None, prs.data)
    elif prs.error.kind in FATAL:
        return prs.error  # runs/issues would fail the same way
    else:
        err = prs.error
    runs = p.pipeline_runs(RUN_DAYS, RUN_LIMIT)
    if runs.ok:
        cache.write(url, "pipeline_runs", runs.data)
    else:
        err = err or runs.error
    known = prs.data if prs.ok else _cached(url, "pull_requests", PullRequest)
    numbers = _numbers(branches, patterns, known)
    for n in numbers:
        res = p.work_item(n)
        if res.ok:
            old = cache.read(url, f"work_item:{n}", WorkItem)
            cache.write(url, f"work_item:{n}", [res.data])
            if old and old.items:
                _log_changes(url, "issue_state", {n: old.items[0].state}, [res.data])
        elif res.error.kind in FATAL:
            return err or res.error
    if plat.kind == "github" and hasattr(p, "sub_issues"):  # status = same core as `kvasir status`
        for n in numbers[:MAX_STATUS]:
            res = issue_status(p, n)
            if res.ok:
                cache.write(url, f"status:{n}", [card_of(res.data.issue)])
            elif res.error.kind in FATAL:
                return err or res.error
    return err
