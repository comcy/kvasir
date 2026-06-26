"""Journal note helpers — type detection, slug generation, auto-creation."""
from __future__ import annotations

import calendar
import re
from datetime import date
from pathlib import Path

_DAY_RE   = re.compile(r'^\d{4}-\d{2}-\d{2}$')
_WEEK_RE  = re.compile(r'^\d{4}-W\d{2}$')
_MONTH_RE = re.compile(r'^\d{4}-\d{2}$')
_YEAR_RE  = re.compile(r'^\d{4}$')


def note_type(stem: str) -> str:
    """Detect journal note type from filename stem."""
    if _DAY_RE.match(stem):   return "day"
    if _WEEK_RE.match(stem):  return "week"
    if _MONTH_RE.match(stem): return "month"
    if _YEAR_RE.match(stem):  return "year"
    return "note"


def slug_for(d: date, ntype: str) -> str:
    if ntype == "day":   return d.isoformat()
    if ntype == "week":
        iso = d.isocalendar()
        return f"{iso.year}-W{iso.week:02d}"
    if ntype == "month": return d.strftime("%Y-%m")
    if ntype == "year":  return str(d.year)
    raise ValueError(f"Unknown ntype: {ntype}")


def _title(slug: str, ntype: str) -> str:
    return {
        "day":   f"Journal — {slug}",
        "week":  f"Week {slug}",
        "month": f"Month {slug}",
        "year":  f"Year {slug}",
    }.get(ntype, slug)


def ensure_note(notes_dir: Path, slug: str, ntype: str) -> Path:
    """Return path to journal note; create with frontmatter stub if absent."""
    from datetime import datetime
    import frontmatter

    path = notes_dir / f"{slug}.md"
    if path.exists():
        return path

    now = datetime.now().isoformat()
    post = frontmatter.Post(
        "\n\n",
        title=_title(slug, ntype),
        type=ntype,
        created=now,
        editedAt=now,
        tags=[f"journal-{ntype}"],
    )
    path.write_text(frontmatter.dumps(post), encoding="utf-8")
    return path


def journal_dates(notes_dir: Path) -> set[date]:
    """Return the set of dates that have a day-journal note."""
    dates: set[date] = set()
    for p in notes_dir.glob("????-??-??.md"):
        try:
            dates.add(date.fromisoformat(p.stem))
        except ValueError:
            pass
    return dates
