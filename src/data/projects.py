"""Project helpers: root detection, registration lookup, worktree enumeration,
and the repo-mutating operations (clone/add/remove/fetch) shared by the CLI
(`project_cmd.py`/`worktree_cmd.py`) and the TUI (`projects_manager.py`).

A Project is a named, registered repo path within a workspace. The recommended
layout is a bare clone in `<root>/.bare` plus a `.git` file (`gitdir: ./.bare`)
so the project folder itself acts as the repo and worktrees are plain subfolders.
Plain (non-bare) repos are supported the same way.
"""
from __future__ import annotations

import subprocess
import uuid
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.data.store import NdjsonStore


class ProjectOpError(Exception):
    """A git/project operation failed; message is safe to show to the user."""


def _git(args: list[str], cwd: Path | str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=str(cwd), stderr=subprocess.DEVNULL
    ).decode().strip()


def _git_checked(args: list[str], cwd: Path | str, error: str) -> None:
    """Run a mutating git command; raise ProjectOpError with stderr on failure."""
    try:
        subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        detail = e.stderr.decode(errors="replace").strip() if e.stderr else str(e)
        raise ProjectOpError(f"{error}: {detail}")


def _register(store: "NdjsonStore", name: str, path: Path, remote: str) -> dict:
    return store.insert("projects", {
        "id": str(uuid.uuid4()),
        "name": name,
        "path": str(path.resolve()),
        "remote": remote,
        "created": datetime.now().isoformat(),
    })


def _branch_exists(root: Path | str, branch: str) -> bool:
    return subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
        cwd=str(root),
    ).returncode == 0


# ── read-only lookups ─────────────────────────────────────────────────────────

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


# ── mutating operations (shared by CLI + TUI) ─────────────────────────────────

def clone_project(store: "NdjsonStore", url: str, name: str, dest_dir: Path | str) -> dict:
    """Bare-repo worktree clone + fetch-refspec fix + default-branch worktree
    + hook install + registration. Raises ProjectOpError on any hard failure."""
    if store.find("projects", name=name):
        raise ProjectOpError(f"Project '{name}' is already registered.")

    root = (Path(dest_dir) / name).resolve()
    if root.exists():
        raise ProjectOpError(f"Directory already exists: {root}")

    _git_checked(["clone", "--bare", url, str(root / ".bare")], Path.cwd(), "git clone failed")
    (root / ".git").write_text("gitdir: ./.bare\n", encoding="utf-8")

    # Bare clones have no fetch refspec — without it, fetch/pull won't update
    # remote-tracking branches.
    _git_checked(
        ["config", "remote.origin.fetch", "+refs/heads/*:refs/remotes/origin/*"],
        root, "git config failed",
    )
    _git_checked(["fetch", "origin"], root, "git fetch failed")

    try:
        default_branch = _git(["symbolic-ref", "--short", "HEAD"], root)
    except subprocess.CalledProcessError:
        default_branch = "main"

    try:
        _git_checked(
            ["worktree", "add", f"./{default_branch}", default_branch], root,
            "worktree add failed",
        )
    except ProjectOpError:
        pass  # non-fatal — project is registered either way, worktree can be added later

    from src.cli.hooks_cmd import HooksError, install_hooks_into
    try:
        install_hooks_into(root, force=False)
    except HooksError:
        pass  # hook install issues must not fail the clone

    return _register(store, name, root, url)


def register_existing(store: "NdjsonStore", name: str, path: Path | str) -> dict:
    """Register an existing repo/directory as a project. Raises ProjectOpError."""
    from src.data.sessions import repo_id

    if store.find("projects", name=name):
        raise ProjectOpError(f"Project '{name}' is already registered.")

    root = project_root(path) or Path(path).resolve()
    if not root.exists():
        raise ProjectOpError(f"Directory not found: {root}")

    existing = next((p for p in store.all("projects") if p.get("path") == str(root)), None)
    if existing:
        raise ProjectOpError(f"Path already registered as '{existing['name']}'.")

    try:
        remote = repo_id(root)
    except Exception:
        remote = ""

    return _register(store, name, root, remote if remote != str(root) else "")


def add_worktree(root: Path | str, branch: str, from_ref: str | None = None) -> Path:
    """Create a worktree folder for *branch* inside the project at *root*."""
    root = Path(root)
    dirname = branch.replace("/", "-")
    dest = root / dirname
    if dest.exists():
        raise ProjectOpError(f"Directory already exists: {dest}")

    if _branch_exists(root, branch):
        args = ["worktree", "add", str(dest), branch]
    else:
        args = ["worktree", "add", "-b", branch, str(dest)]
        if from_ref:
            args.append(from_ref)

    _git_checked(args, root, "git worktree add failed")
    return dest


def remove_worktree(root: Path | str, worktree_path: Path | str, force: bool = False) -> None:
    """Remove a worktree. The branch itself is kept."""
    args = ["worktree", "remove", str(worktree_path)]
    if force:
        args.insert(2, "--force")
    _git_checked(args, root, "git worktree remove failed (uncommitted changes? use force)")


def fetch_project(root: Path | str) -> None:
    """Fetch the project's origin remote."""
    _git_checked(["fetch", "origin"], root, "git fetch failed")
