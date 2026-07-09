"""Project helpers: root detection, registration lookup, worktree enumeration.

A Project is a named, registered repo path within a workspace. The recommended
layout is a bare clone in `<root>/.bare` plus a `.git` file (`gitdir: ./.bare`)
so the project folder itself acts as the repo and worktrees are plain subfolders.
Plain (non-bare) repos are supported the same way.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.data.store import NdjsonStore


def _git(args: list[str], cwd: Path | str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=str(cwd), stderr=subprocess.DEVNULL
    ).decode().strip()


def project_root(cwd: Path | str = ".") -> Path | None:
    """Root folder of the project containing *cwd*, or None outside a repo.

    Resolved via the git common dir (shared by all worktrees): for the bare
    layout that is `<root>/.bare`, for a plain repo `<root>/.git` — the parent
    is the project root in both cases.
    """
    try:
        common = _git(["rev-parse", "--path-format=absolute", "--git-common-dir"], cwd)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    return Path(common).parent


def find_project(store: "NdjsonStore", path: Path | str) -> dict | None:
    """Registered project whose path contains *path* (longest prefix wins)."""
    resolved = Path(path).resolve()
    best: dict | None = None
    for p in store.all("projects"):
        proj_path = Path(p.get("path", "")).resolve()
        if resolved == proj_path or proj_path in resolved.parents:
            if best is None or len(str(proj_path)) > len(best["path"]):
                best = p
    return best


def list_worktrees(root: Path | str) -> list[dict]:
    """Worktrees of the project at *root*: [{path, branch, head}].

    Detached worktrees get branch "" ; the bare entry itself is excluded.
    """
    try:
        out = _git(["worktree", "list", "--porcelain"], root)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []

    worktrees: list[dict] = []
    current: dict = {}
    for line in out.splitlines():
        if line.startswith("worktree "):
            current = {"path": line[len("worktree "):], "branch": "", "head": ""}
        elif line.startswith("HEAD "):
            current["head"] = line[len("HEAD "):]
        elif line.startswith("branch "):
            current["branch"] = line[len("branch "):].removeprefix("refs/heads/")
        elif line == "bare":
            current["bare"] = True
        elif not line and current:
            if not current.get("bare"):
                worktrees.append(current)
            current = {}
    if current and not current.get("bare"):
        worktrees.append(current)
    return worktrees


def uncommitted_count(worktree_dir: Path | str) -> int:
    """Number of changed/untracked files in *worktree_dir* (git status lines)."""
    try:
        out = _git(["status", "--porcelain"], worktree_dir)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return 0
    return len([line for line in out.splitlines() if line.strip()])
