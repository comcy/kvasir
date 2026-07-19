"""Built-in "auto" metrics — computed live from sessions.ndjson/commits.ndjson,
never persisted to metric_values.ndjson (CONTEXT.md's "Metric (auto)").
Always shown in the dashboard's Metrics panel alongside any manually defined
metrics — no `mimirlink metric define` required to see something useful."""
from __future__ import annotations

from datetime import date, datetime, timedelta


def _week_start() -> datetime:
    today = date.today()
    return datetime.combine(today - timedelta(days=today.weekday()), datetime.min.time())


def focus_time_seconds_this_week(sessions: list[dict]) -> float:
    """Total session duration since Monday, across every worktree/branch."""
    since = _week_start()
    total = 0.0
    for s in sessions:
        try:
            start = datetime.fromisoformat(s["start"])
        except Exception:
            continue
        end = datetime.fromisoformat(s["end"]) if s.get("end") else datetime.now()
        start = max(start, since)
        if end <= start:
            continue
        total += (end - start).total_seconds()
    return total


def commit_count_this_week(commits: list[dict]) -> int:
    """Number of tracked commits (any project) since Monday."""
    week_start = _week_start().date().isoformat()
    return sum(1 for c in commits if c.get("date", "") >= week_start)


def has_any_data(sessions: list[dict], commits: list[dict]) -> bool:
    """Whether there's anything at all to compute the auto metrics from."""
    return bool(sessions) or bool(commits)
