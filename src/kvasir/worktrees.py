"""Read Worktrees and Branches of a Repo via the git CLI. No state, no TUI."""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Worktree:
    path: Path
    branch: str | None = None           # None = detached HEAD
    commit_ts: int | None = None        # last commit, unix seconds (None = no commits)
    subject: str = ""
    staged: int = 0
    unstaged: int = 0
    untracked: int = 0
    last_active_ts: int | None = None   # max(last commit, newest uncommitted file mtime)
    ahead: int | None = None            # None = no upstream
    behind: int | None = None
    broken: str | None = None           # reason, if the Worktree could not be read


@dataclass
class Branch:
    name: str                           # local: "feat/x"; remote: "origin/feat/x"
    remote: bool
    commit_ts: int | None
    subject: str


@dataclass
class RepoView:
    worktrees: list[Worktree] = field(default_factory=list)
    branches: list[Branch] = field(default_factory=list)  # without Worktree


def _git(path: Path, *args: str) -> str:
    """Stdout; raises RuntimeError on failure."""
    r = subprocess.run(["git", "-C", str(path), *args], capture_output=True, check=False)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode(errors="replace").strip() or f"git {args[0]} failed")
    return r.stdout.decode(errors="replace")


def _parse_worktree_list(out: str) -> list[dict[str, str]]:
    """`git worktree list --porcelain -z` -> one dict per record (needs git >= 2.36)."""
    records: list[dict[str, str]] = []
    cur: dict[str, str] = {}
    for item in out.split("\0"):
        if not item:
            if cur:
                records.append(cur)
            cur = {}
            continue
        key, _, val = item.partition(" ")
        cur[key] = val
    if cur:
        records.append(cur)
    return records


def _parse_status(out: str) -> tuple[int, int, int, list[str]]:
    """`git status --porcelain=v1 -z -uall` -> (staged, unstaged, untracked, paths)."""
    staged = unstaged = untracked = 0
    paths: list[str] = []
    parts = out.split("\0")
    i = 0
    while i < len(parts):
        e = parts[i]
        i += 1
        if len(e) < 4:
            continue
        x, y, p = e[0], e[1], e[3:]
        if x in "RC":
            i += 1  # skip the "from" path of a rename/copy
        if x == "?":
            untracked += 1
        elif x == "!":
            continue
        else:
            staged += x != " "
            unstaged += y != " "
        paths.append(p)
    return staged, unstaged, untracked, paths


def _read_worktree(rec: dict[str, str]) -> Worktree:
    path = Path(rec["worktree"])
    branch = rec.get("branch", "").removeprefix("refs/heads/") or None
    wt = Worktree(path=path, branch=branch)
    if not path.is_dir():
        wt.broken = "directory missing"
        return wt
    try:
        wt.staged, wt.unstaged, wt.untracked, paths = _parse_status(
            _git(path, "status", "--porcelain=v1", "-z", "-uall")
        )
        try:
            ts, _, wt.subject = _git(path, "log", "-1", "--format=%ct%x00%s").strip().partition("\0")
            wt.commit_ts = int(ts)
        except RuntimeError:
            pass  # no commits yet
        stamps = [wt.commit_ts] if wt.commit_ts is not None else []
        for p in paths:
            try:
                stamps.append(int((path / p).stat().st_mtime))
            except OSError:
                pass  # deleted file
        wt.last_active_ts = max(stamps, default=None)
        if branch:
            try:
                counts = _git(path, "rev-list", "--left-right", "--count", "@{u}...HEAD").split()
                wt.behind, wt.ahead = int(counts[0]), int(counts[1])
            except (RuntimeError, ValueError, IndexError):
                pass  # no upstream
    except RuntimeError as e:
        wt.broken = str(e)
    return wt


def _read_branches(root: Path, checked_out: set[str]) -> list[Branch]:
    out = _git(
        root, "for-each-ref", "--format=%(refname)%00%(committerdate:unix)%00%(subject)",
        "refs/heads", "refs/remotes",
    )
    local: list[Branch] = []
    remote: list[Branch] = []
    for line in out.splitlines():
        ref, ts, subject = (line.split("\0") + ["", ""])[:3]
        if ref.startswith("refs/heads/"):
            local.append(Branch(ref.removeprefix("refs/heads/"), False, int(ts or 0) or None, subject))
        elif ref.startswith("refs/remotes/") and not ref.endswith("/HEAD"):
            remote.append(Branch(ref.removeprefix("refs/remotes/"), True, int(ts or 0) or None, subject))
    local_names = {b.name for b in local}
    # a remote branch with a same-named local branch is redundant
    return [b for b in local if b.name not in checked_out] + [
        b for b in remote if b.name.partition("/")[2] not in local_names
    ]


def read_repo(root: Path) -> RepoView:
    """Worktrees and Branches without Worktree of the Repo at `root` (Bare-Layout or normal clone).

    Raises ValueError if `root` is not a git repo. A broken Worktree is marked, not fatal.
    """
    try:
        recs = _parse_worktree_list(_git(root, "worktree", "list", "--porcelain", "-z"))
    except RuntimeError as e:
        raise ValueError(f"not a git repository: {root}") from e
    wts = [_read_worktree(r) for r in recs if "bare" not in r and "worktree" in r]
    checked_out = {w.branch for w in wts if w.branch}
    return RepoView(wts, _read_branches(root, checked_out))
