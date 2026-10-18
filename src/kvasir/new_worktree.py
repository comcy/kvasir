"""Create a Worktree in a Bare-Layout Repo via `git worktree add`. No TUI."""
from __future__ import annotations

import shutil
import subprocess
import uuid
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


def base_hint(root: Path, base: str) -> str:
    """`main (abc1234)` or `main (unknown ref)`."""
    r = _git(root, "rev-parse", "--short", "--verify", "--quiet", f"{base}^{{commit}}")
    return f"{base} ({r.stdout.strip()})" if r.returncode == 0 and base else f"{base or '?'} (unknown ref)"


def repo_root(path: Path) -> Path:
    """Bare-Layout root from any path inside the Repo (also from within a Worktree)."""
    r = _git(path, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if r.returncode != 0:
        raise NewWorktreeError(f"not a git repository: {path}")
    common = Path(r.stdout.strip())
    if common.name != ".bare" or not is_bare_layout(common.parent):
        raise NewWorktreeError(f"not a Bare-Layout Repo (.bare/ + .git file): {path}")
    return common.parent


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
            raise NewWorktreeError(f"base branch {base!r} not found (remote branch? run git fetch)")
        args, commitish = ["--no-track", "-b", name], base  # no upstream on the base: push must not target it
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


def add_worktree_moving_changes(root: Path, branch: str, base: str | None, source: Path) -> Path:
    """Like add_worktree, but moves the uncommitted changes (incl. untracked) of Worktree `source` into the new one.

    The own stash is addressed by commit hash (the stash stack is shared by all Worktrees). Any failure
    restores `source`, removes what was created and keeps the stash; the error names its hash.
    """
    tag = f"kvasir-move-{uuid.uuid4().hex}"
    r = _git(source, "stash", "push", "--include-untracked", "-m", tag)
    if r.returncode != 0:
        raise NewWorktreeError(f"stashing changes failed: {r.stderr.strip()}")
    sha = next((ln.split()[0] for ln in _git(source, "stash", "list", "--format=%H %gs").stdout.splitlines()
                if ln.endswith(tag)), None)
    if sha is None:
        return add_worktree(root, branch, base)  # nothing to move

    def restore(why: str) -> NewWorktreeError:
        back = _git(source, "stash", "apply", "--index", sha)
        if back.returncode != 0:
            return NewWorktreeError(f"{why}; could not restore {source} either, changes kept in stash commit {sha}")
        return NewWorktreeError(f"{why}; changes restored in {source} (stash commit {sha} kept)")

    branch_before = base is not None and _ref_exists(root, f"refs/heads/{branch}")
    try:
        path = add_worktree(root, branch, base)
    except NewWorktreeError as e:
        raise restore(str(e)) from e
    r = _git(path, "stash", "apply", "--index", sha)
    if r.returncode != 0:
        _git(root, "worktree", "remove", "--force", "--", str(path))
        shutil.rmtree(path, ignore_errors=True)
        if base is not None and not branch_before:
            _git(root, "branch", "-D", "--", branch)
        raise restore(f"applying changes in the new Worktree failed: {(r.stderr or r.stdout).strip()}")
    for i, ln in enumerate(_git(source, "stash", "list", "--format=%H").stdout.split()):
        if ln == sha:
            _git(source, "stash", "drop", f"stash@{{{i}}}")
            break
    return path
