"""Data helpers for the `mimirlink morning` routine: todo triage + journal gap-fill."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path
    from src.data.store import NdjsonStore


def due_or_overdue_todos(store: "NdjsonStore") -> list[dict]:
    """Open todos whose due_date is today or in the past, oldest first."""
    today = date.today().isoformat()
    todos = [
        t for t in store.all("todos")
        if t.get("status") == "open" and t.get("due_date") and t["due_date"] <= today
    ]
    return sorted(todos, key=lambda t: t["due_date"])


def undated_todos(store: "NdjsonStore") -> list[dict]:
    """Open todos with no due_date at all — candidates for manual day assignment.

    Assigning a due_date is the only "link" to a journal day; once set, the
    todo naturally surfaces via that day's auto-embedded due_date query and
    drops out of this list on the next run. No separate tracking needed.
    """
    return [t for t in store.all("todos") if t.get("status") == "open" and not t.get("due_date")]


def missing_journal_days(notes_dir: "Path", store: "NdjsonStore", lookback_days: int = 7) -> list[date]:
    """Days in the last *lookback_days* (excluding today) with no day-journal note
    and not explicitly skipped via mark_journal_day_skipped()."""
    from src.data.journal import journal_dates

    existing = journal_dates(notes_dir)
    skipped = {s["date"] for s in store.all("journal_skips")}
    today = date.today()
    candidates = (today - timedelta(days=n) for n in range(1, lookback_days + 1))
    return sorted(
        d for d in candidates if d not in existing and d.isoformat() not in skipped
    )


def mark_journal_day_skipped(store: "NdjsonStore", d: date) -> None:
    """Persist that the user does not want a journal entry for day *d*."""
    store.insert("journal_skips", {
        "id": str(uuid.uuid4()),
        "date": d.isoformat(),
        "created": datetime.now().isoformat(),
    })
