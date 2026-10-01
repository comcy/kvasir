"""Create a Worktree in a Bare-Layout Repo via `git worktree add`. No TUI."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class NewWorktreeError(ValueError):
    """Readable reason why no Worktree was created."""


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=False)


def _ref_exists(root: Path, ref: str) -> bool:
    return _git(root, "show-ref", "--verify", "--quiet", ref).returncode == 0


def is_bare_layout(root: Path) -> bool:
    return (root / ".bare").is_dir() and (root / ".git").is_file()


def default_branch(root: Path) -> str:
    r = _git(root / ".bare", "symbolic-ref", "--short", "HEAD")
    if r.returncode != 0:
        raise NewWorktreeError(f"cannot determine default branch: {r.stderr.strip()}")
    return r.stdout.strip()


def _checked_out(root: Path) -> dict[str, str]:
    """branch -> worktree path."""
    out = _git(root, "worktree", "list", "--porcelain").stdout
    res, path = {}, ""
    for line in out.splitlines():
        if line.startswith("worktree "):
            path = line[9:]
        elif line.startswith("branch refs/heads/"):
            res[line[18:]] = path
    return res


def add_worktree(root: Path, branch: str, base: str | None = None) -> Path:
    """Add Worktree `<root>/<branch>`; returns its path. Raises NewWorktreeError, leaves nothing behind.

    base=None: `branch` is an existing Branch, local ("feat/x") or remote-only ("origin/feat/x",
    creates a local tracking Branch). base=<ref>: create new Branch `branch` from `base`.
    """
    if not is_bare_layout(root):
        raise NewWorktreeError(
            "Worktrees can only be added in a Bare-Layout Repo (.bare/ + .git file); "
            "this is a normal clone (see PLAN.md, 'Normaler Clone')"
        )
    if base is None and _ref_exists(root, f"refs/heads/{branch}"):
        args, name, commitish = [], branch, branch
    elif base is None and _ref_exists(root, f"refs/remotes/{branch}"):
        name = branch.partition("/")[2]
        if _ref_exists(root, f"refs/heads/{name}"):
            raise NewWorktreeError(f"local branch {name!r} already exists; pick it instead of {branch!r}")
        args, commitish = ["--track", "-b", name], branch
    elif base is None:
        raise NewWorktreeError(f"branch {branch!r} not found")
    else:
        name = branch
        if _git(root, "check-ref-format", "--branch", name).returncode != 0:
            raise NewWorktreeError(f"invalid branch name: {name!r}")
        if _ref_exists(root, f"refs/heads/{name}"):
            raise NewWorktreeError(f"branch {name!r} already exists")
        if _git(root, "rev-parse", "--verify", "--quiet", f"{base}^{{commit}}").returncode != 0:
            raise NewWorktreeError(f"base branch {base!r} not found")
        args, commitish = ["-b", name], base
    if (other := _checked_out(root).get(name)) is not None:
        raise NewWorktreeError(f"branch {name!r} is already checked out in {other}")
    path = root / name
    if path.exists():
        raise NewWorktreeError(f"directory already exists: {path}")
    missing = [p for p in reversed(path.parents) if root in p.parents and not p.exists()]
    r = _git(root, "worktree", "add", *args, "--", str(path), commitish)
    if r.returncode != 0:
        shutil.rmtree(path, ignore_errors=True)
        for p in reversed(missing):
            if p.is_dir() and not any(p.iterdir()):
                p.rmdir()
        if args and _ref_exists(root, f"refs/heads/{name}"):
            _git(root, "branch", "-D", "--", name)  # only reached for a Branch created by this call
        raise NewWorktreeError(r.stderr.strip() or "git worktree add failed")
    return path
