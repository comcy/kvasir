"""Fetch and pull via the git CLI. No Textual; blocking, run it in a worker. Never merges or rebases."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

TIMEOUT = 120  # seconds
_ENV = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}  # never ask for credentials


def _run(path: Path, *args: str, timeout: int = TIMEOUT) -> tuple[int, str]:
    """(returncode, stdout or stderr text). Timeout/OS errors become returncode -1."""
    try:
        r = subprocess.run(
            ["git", "-C", str(path), *args], capture_output=True, check=False, env=_ENV, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return -1, f"git {args[0]} timed out after {timeout}s"
    except OSError as e:
        return -1, str(e)
    out, err = r.stdout.decode(errors="replace").strip(), r.stderr.decode(errors="replace").strip()
    return r.returncode, out if r.returncode == 0 else (err or out or f"git {args[0]} failed")


def fetch(root: Path) -> str | None:
    """`git fetch --prune`. None = ok, else the error text. Never raises."""
    code, msg = _run(root, "fetch", "--prune")
    return None if code == 0 else msg


def pull(worktree: Path) -> tuple[bool, str]:
    """`git pull --ff-only` in a Worktree. (ok, message). Refuses without changing anything when
    the Worktree has tracked changes, has no upstream, or diverged."""
    code, msg = _run(worktree, "status", "--porcelain", "-uno")
    if code != 0:
        return False, msg
    if msg:
        return False, "uncommitted changes: commit or stash first"
    code, msg = _run(worktree, "rev-list", "--left-right", "--count", "@{u}...HEAD")
    if code != 0:
        return False, "no upstream branch configured"
    behind, ahead = (int(n) for n in msg.split())
    if behind and ahead:
        return False, f"diverged (ahead {ahead}, behind {behind}): resolve manually"
    if not behind:
        return True, "already up to date" if not ahead else f"nothing to pull (ahead {ahead})"
    code, msg = _run(worktree, "pull", "--ff-only")
    return code == 0, msg if code else f"pulled {behind} commit(s)"
