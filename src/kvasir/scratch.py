"""Scratch-Worktrees: detached view of a ref, never a branch. Same convention as scripts/git-scratch in comcy/dotfiles.

Starts nothing but git: no tests, linters, installs. No Textual.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from kvasir.worktrees import _git, _parse_worktree_list


def scratch_dir(cwd: Path) -> Path:
    """Bare-Layout: `<root>/.scratch`; normal clone: sibling `<repo>.scratch` (keeps `git status` clean)."""
    common = Path(_git(cwd, "rev-parse", "--path-format=absolute", "--git-common-dir").strip())
    if common.name == ".bare":
        return common.parent / ".scratch"
    if common.name == ".git":
        return common.parent.parent / f"{common.parent.name}.scratch"
    return common.parent / f"{common.name}.scratch"  # plain bare repo


def is_scratch(path: Path) -> bool:
    return path.parent.name == ".scratch" or path.parent.name.endswith(".scratch")


def slug(ref: str) -> str:
    return ref.replace("/", "--")


def _resolve(cwd: Path, ref: str) -> str:
    for cand in (f"refs/heads/{ref}", f"refs/remotes/origin/{ref}", ref):
        r = subprocess.run(["git", "-C", str(cwd), "rev-parse", "--verify", "--quiet", f"{cand}^{{commit}}"],
                           capture_output=True, check=False)
        if r.returncode == 0:
            return cand
    raise RuntimeError(f"unknown ref: {ref}")


def add(cwd: Path, ref: str) -> Path:
    """Path of the detached Scratch-Worktree for `ref` (created if missing). RuntimeError on failure."""
    target = scratch_dir(cwd) / slug(ref)
    if target.exists():
        return target
    subprocess.run(["git", "-C", str(cwd), "fetch", "--quiet"], capture_output=True, check=False)  # offline: only a warning
    cand = _resolve(cwd, ref)
    target.parent.mkdir(parents=True, exist_ok=True)
    _git(cwd, "worktree", "add", "--detach", str(target), cand)
    return target


def listing(cwd: Path) -> list[Path]:
    recs = _parse_worktree_list(_git(cwd, "worktree", "list", "--porcelain", "-z"))
    d = scratch_dir(cwd).resolve()
    return [p for p in (Path(r["worktree"]) for r in recs if "worktree" in r) if p.parent.resolve() == d]


def remove(cwd: Path, path: Path, force: bool = False) -> None:
    """Refuses a dirty Scratch-Worktree unless `force`. Never touches branches or remotes."""
    _git(cwd, "worktree", "remove", *(["--force"] if force else []), str(path))
    _git(cwd, "worktree", "prune")


def clean(cwd: Path, ref: str | None = None, force: bool = False) -> tuple[list[Path], list[str]]:
    """One (`ref`) or all Scratch-Worktrees -> (removed, errors); each is dirty-protected."""
    paths = [scratch_dir(cwd) / slug(ref)] if ref else listing(cwd)
    removed, errors = [], []
    for p in paths:
        try:
            remove(cwd, p, force)
            removed.append(p)
        except RuntimeError as e:
            errors.append(f"{p.name}: {e}")
    return removed, errors
