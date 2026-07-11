"""Session tracking + branch staleness helpers. Sessions are opened/closed by
the post-checkout hook and the worktree commands — never manually in normal use."""
from __future__ import annotations

import subprocess
import time
import uuid
from datetime import date, datetime, time as _time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.data.store import NdjsonStore

DEFAULT_STALE_DAYS = 14


def format_duration(total_seconds: float) -> str:
    """Human-readable duration: "2h 05m" or "45m" for under an hour."""
    h, rem = divmod(int(max(total_seconds, 0)), 3600)
    m = rem // 60
    return f"{h}h {m:02d}m" if h else f"{m}m"


def format_ago(ts: str) -> str:
    """Human-readable relative time: "just now" / "5m ago" / "2h ago" / "3d ago"."""
    try:
        d = datetime.fromisoformat(ts)
        s = int((datetime.now() - d).total_seconds())
    except Exception:
        return "?"
    if s < 60:
        return "just now"
    if s < 3600:
        return f"{s // 60}m ago"
    if s < 86400:
        return f"{s // 3600}h ago"
    return f"{s // 86400}d ago"


def _git(args: list[str], cwd: Path | str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=str(cwd), stderr=subprocess.DEVNULL
    ).decode().strip()


def repo_id(worktree_dir: Path | str) -> str:
    """Canonical repo identifier: remote URL, falling back to the toplevel path."""
    try:
        return _git(["remote", "get-url", "origin"], worktree_dir)
    except subprocess.CalledProcessError:
        return _git(["rev-parse", "--show-toplevel"], worktree_dir)


def open_session(store: "NdjsonStore", repo: str, branch: str, worktree_path: str) -> dict:
    """Open a session for *worktree_path*, closing any still-active one there first.

    A branch switch within the same worktree therefore ends the previous session.
    Re-checkout of the same branch in the same worktree keeps the running session.
    """
    now = datetime.now().isoformat()
    for s in store.find("sessions", worktree_path=worktree_path, end=None):
        if s.get("branch") == branch:
            return s
        store.update("sessions", s["id"], end=now)
    return store.insert("sessions", {
        "id": str(uuid.uuid4()),
        "repo": repo,
        "branch": branch,
        "worktree_path": worktree_path,
        "start": now,
        "end": None,
    })


def close_session_for_worktree(store: "NdjsonStore", worktree_path: str) -> int:
    """Close all active sessions on *worktree_path*; returns count closed."""
    now = datetime.now().isoformat()
    closed = 0
    for s in store.find("sessions", worktree_path=worktree_path, end=None):
        store.update("sessions", s["id"], end=now)
        closed += 1
    return closed


def last_session(store: "NdjsonStore", repo: str, branch: str) -> dict | None:
    """Most recent session (by start) for *branch* in *repo*, active or ended."""
    sessions = [
        s for s in store.all("sessions")
        if s.get("repo") == repo and s.get("branch") == branch
    ]
    return max(sessions, key=lambda s: s.get("start", "")) if sessions else None


def worktree_seconds(store: "NdjsonStore", worktree_path: str, since: datetime | None = None) -> float:
    """Total seconds spent on *worktree_path* across all its sessions.

    If *since* is given, each session is clipped to it (e.g. pass midnight
    today for a "time spent today" total) — sessions entirely before *since*
    contribute 0.
    """
    total = 0.0
    for s in store.find("sessions", worktree_path=worktree_path):
        try:
            start = datetime.fromisoformat(s["start"])
        except Exception:
            continue
        end = datetime.fromisoformat(s["end"]) if s.get("end") else datetime.now()
        if since is not None:
            start = max(start, since)
        if end <= start:
            continue
        total += (end - start).total_seconds()
    return total


def today_start() -> datetime:
    """Midnight of the current day, for use as `worktree_seconds(..., since=...)`."""
    return datetime.combine(date.today(), _time.min)


def most_recent_session(store: "NdjsonStore") -> dict | None:
    """The session with the latest start across all worktrees, active or ended —
    answers "where was I last working" independent of project/worktree."""
    sessions = store.all("sessions")
    return max(sessions, key=lambda s: s.get("start", "")) if sessions else None


def stale_branches(repo_dir: Path | str, threshold_days: int) -> list[tuple[str, int]]:
    """Local branches with no commit for more than *threshold_days*, most stale first.

    Detected purely from git metadata (committerdate) — no tracking required.
    """
    try:
        out = _git(
            ["for-each-ref", "--sort=-committerdate", "refs/heads",
             "--format=%(refname:short)|%(committerdate:unix)"],
            repo_dir,
        )
    except subprocess.CalledProcessError:
        return []

    now = time.time()
    stale: list[tuple[str, int]] = []
    for line in out.splitlines():
        name, _, ts = line.partition("|")
        if not ts.isdigit():
            continue
        days = int((now - int(ts)) // 86400)
        if days > threshold_days:
            stale.append((name, days))
    return sorted(stale, key=lambda x: -x[1])


def stale_threshold(repo_dir: Path | str) -> int:
    """Stale-branch threshold in days: `[git] stale_days` from the project-root
    .mimirlink.toml, falling back to DEFAULT_STALE_DAYS."""
    import tomllib

    cfg = Path(repo_dir) / ".mimirlink.toml"
    if cfg.exists():
        try:
            with cfg.open("rb") as f:
                raw = tomllib.load(f)
            value = raw.get("git", {}).get("stale_days")
            if isinstance(value, int) and value > 0:
                return value
        except Exception:
            pass
    return DEFAULT_STALE_DAYS
