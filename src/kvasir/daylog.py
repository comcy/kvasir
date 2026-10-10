"""Internal day log: `<config dir>/days/YYYY-MM-DD.ndjson`, one JSON line per event. No Textual.

Calendar day = local day. Events are appended (no duplicate of the previous event); the single
`snapshot` line of a day is replaced. Write errors never propagate: the log must not fail an action.
Commits are not stored (derivable from `git log`).
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import date, datetime
from pathlib import Path

from kvasir.config import config_dir


def _path(day: date) -> Path:
    return config_dir() / "days" / f"{day.isoformat()}.ndjson"


def read(day: date) -> list[dict]:
    """All valid events of a day in file order; broken or foreign lines are skipped."""
    try:
        text = _path(day).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    out = []
    for line in text.splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if isinstance(r, dict) and isinstance(r.get("ts"), str) and isinstance(r.get("type"), str):
            out.append(r)
    return out


def _line(event: dict) -> str:
    return json.dumps(event, ensure_ascii=False) + "\n"


def _stamp(event: dict) -> tuple[date, dict]:
    now = datetime.now().astimezone()
    return now.date(), {"ts": now.isoformat(timespec="seconds"), **event}


def record(event: dict) -> None:
    """Append `event` (needs `type`) to today's log; skipped if it equals the last event. Never raises."""
    try:
        day, rec = _stamp(event)
        last = next((e for e in reversed(read(day)) if e["type"] != "snapshot"), None)
        if last and {k: v for k, v in last.items() if k != "ts"} == event:
            return
        p = _path(day)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8", newline="\n") as f:
            f.write(_line(rec))  # one write call, so concurrent appends do not interleave
    except Exception:  # noqa: BLE001, S110 - logging must never fail an action
        pass


def snapshot(repos: dict[str, list]) -> None:
    """Replace today's snapshot: Worktrees with uncommitted changes per repo URL. Never raises.

    `repos`: URL -> Worktree objects (duck-typed: branch, path, staged, unstaged, untracked, last_active_ts).
    """
    try:
        day, rec = _stamp({"type": "snapshot", "worktrees": [
            {"url": url, "branch": w.branch or w.path.name, "staged": w.staged, "unstaged": w.unstaged,
             "untracked": w.untracked,
             "last_active": datetime.fromtimestamp(w.last_active_ts).astimezone().isoformat(timespec="seconds")
             if w.last_active_ts is not None else None}
            for url, wts in repos.items() for w in wts if w.staged or w.unstaged or w.untracked]})
        p = _path(day)
        p.parent.mkdir(parents=True, exist_ok=True)
        keep = [e for e in read(day) if e["type"] != "snapshot"]
        fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".day.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                f.writelines(_line(e) for e in [*keep, rec])
            os.replace(tmp, p)
        except BaseException:
            os.unlink(tmp)
            raise
    except Exception:  # noqa: BLE001, S110
        pass
