"""Platform data for the TUI: fetch (blocking, run in a worker) and merge with the cache. No Textual.

`refresh` talks to the provider and fills `platform_cache.json`; `snapshot` reads only the cache, so it
is cheap, works offline and is what the UI shows. Interfaces for the overview (#29): `refresh`,
`snapshot`, `Snapshot.info`, `branch_names`.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

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
from kvasir.worktrees import Branch, RepoView, Worktree

PR_LIMIT = 50
RUN_LIMIT = 50
RUN_DAYS = 7
MAX_ITEMS = 20  # ponytail: one `gh issue view` per id, capped; raise if repos with many branches need more
FATAL = (ErrorKind.MISSING_CLI, ErrorKind.NOT_LOGGED_IN, ErrorKind.NETWORK, ErrorKind.RATE_LIMIT)


@dataclass(frozen=True)
class BranchInfo:
    pr: PullRequest | None
    work_item: WorkItem | None
    work_item_number: int | None  # known id, even when the issue itself is not cached
    runs: tuple[PipelineRun, ...]
    loaded: bool  # False: nothing fetched yet (no cache), so "kein PR" would be a lie


@dataclass
class Snapshot:
    prs: list[PullRequest]
    runs: list[PipelineRun]
    items: dict[int, WorkItem]
    patterns: list[str]
    fetched_at: datetime | None  # of the PR list; None = never fetched
    error: Error | None = None  # last refresh error; the data above is the old state

    def info(self, branch: str) -> BranchInfo:
        mine = [p for p in self.prs if p.branch == branch]  # newest first
        pr = next((p for p in mine if p.state in ("open", "draft")), mine[0] if mine else None)
        n = work_item_for(branch, self.patterns, self.prs)
        runs = tuple(r for r in self.runs if r.branch == branch)
        return BranchInfo(pr, self.items.get(n) if n else None, n, runs, self.fetched_at is not None)


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
    items = {}
    for n in _numbers(branches, patterns, prs):
        if found := _cached(url, f"work_item:{n}", WorkItem):
            items[n] = found[0]
    return Snapshot(prs, _cached(url, "pipeline_runs", PipelineRun), items, patterns,
                    e.fetched_at if e else None, error)


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
        cache.write(url, "pull_requests", prs.data)
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
    for n in _numbers(branches, patterns, known):
        res = p.work_item(n)
        if res.ok:
            cache.write(url, f"work_item:{n}", [res.data])
        elif res.error.kind in FATAL:
            return err or res.error
    return err
