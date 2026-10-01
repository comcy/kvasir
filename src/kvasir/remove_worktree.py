"""Safely remove a Worktree via the git CLI. No state, no TUI."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from kvasir.worktrees import Worktree, _git


@dataclass
class Risks:
    staged: int = 0
    unstaged: int = 0
    untracked: int = 0
    unpushed: int = 0            # commits reachable from HEAD but from no remote branch
    blocked: str | None = None   # reason the Worktree must never be removed

    @property
    def dangerous(self) -> bool:
        return bool(self.staged or self.unstaged or self.untracked or self.unpushed)

    def describe(self) -> list[str]:
        parts = [
            (self.staged, "staged change(s)"),
            (self.unstaged, "unstaged change(s)"),
            (self.untracked, "untracked file(s)"),
            (self.unpushed, "commit(s) on no remote"),
        ]
        return [f"{n} {label}" for n, label in parts if n]


def default_branch(root: Path) -> str | None:
    """origin/HEAD if known, else the HEAD of the repo (bare layout: its default branch)."""
    for args in (("symbolic-ref", "--short", "refs/remotes/origin/HEAD"), ("symbolic-ref", "--short", "HEAD")):
        try:
            return _git(root, *args).strip().removeprefix("origin/") or None
        except RuntimeError:
            continue
    return None


def blocked_reason(wt: Worktree, root: Path, cwd: Path | None = None) -> str | None:
    root, path = root.resolve(), wt.path.resolve()
    if (root / ".git").is_dir() and path == root:
        return "main checkout cannot be removed"
    if wt.branch and wt.branch == default_branch(root):
        return "default worktree cannot be removed"
    here = (cwd or Path.cwd()).resolve()
    if here == path or path in here.parents:
        return "worktree is open in this TUI"
    return None


def assess(wt: Worktree, root: Path, cwd: Path | None = None) -> Risks:
    r = Risks(wt.staged, wt.unstaged, wt.untracked, blocked=blocked_reason(wt, root, cwd))
    if not wt.broken:
        # ponytail: also covers "ahead" and "no upstream"; commits already on any remote branch are safe
        r.unpushed = int(_git(wt.path, "rev-list", "--count", "HEAD", "--not", "--remotes").strip() or 0)
    return r


def remove(root: Path, path: Path, force: bool = False) -> None:
    """Raises RuntimeError if git refuses. `force` only after explicit user confirmation."""
    _git(root, "worktree", "remove", *(["--force"] if force else []), str(path))


def is_merged(root: Path, branch: str, base: str) -> bool:
    out = _git(root, "branch", "--merged", base, "--format=%(refname:short)")
    return branch in out.splitlines()


def delete_branch(root: Path, branch: str) -> None:
    _git(root, "branch", "-d", branch)  # never -D


def prune(root: Path) -> None:
    _git(root, "worktree", "prune")
