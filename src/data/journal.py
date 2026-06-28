"""Journal note helpers — type detection, slug generation, templated auto-creation."""
from __future__ import annotations

import calendar as _cal
import re
from datetime import date, timedelta
from pathlib import Path

_DAY_RE   = re.compile(r'^\d{4}-\d{2}-\d{2}$')
_WEEK_RE  = re.compile(r'^\d{4}-W\d{2}$')
_MONTH_RE = re.compile(r'^\d{4}-\d{2}$')
_YEAR_RE  = re.compile(r'^\d{4}$')

_MONTHS_DE = [
    "", "Januar", "Februar", "März", "April", "Mai", "Juni",
    "Juli", "August", "September", "Oktober", "November", "Dezember",
]
_DAYS_DE = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]


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


def _parent(slug: str, ntype: str) -> tuple[str, str] | None:
    """Return (parent_slug, parent_ntype) for the enclosing hierarchy level, or None for year."""
    if ntype == "day":
        d = date.fromisoformat(slug)
        iso = d.isocalendar()
        return f"{iso.year}-W{iso.week:02d}", "week"
    if ntype == "week":
        year, week = int(slug[:4]), int(slug[6:])
        thursday = date.fromisocalendar(year, week, 4)  # Thursday rule
        return thursday.strftime("%Y-%m"), "month"
    if ntype == "month":
        return slug[:4], "year"
    return None


def _title(slug: str, ntype: str) -> str:
    return {
        "day":   f"Journal — {slug}",
        "week":  f"Week {slug}",
        "month": f"Month {slug}",
        "year":  f"Year {slug}",
    }.get(ntype, slug)


# ─────────────────────── templates ───────────────────────────────────────────

def _year_template(slug: str) -> str:
    year = int(slug)
    sections = []
    for m in range(1, 13):
        month_slug = f"{year}-{m:02d}"
        sections.append(f"## {_MONTHS_DE[m]} · {month_slug}\n\n")
    body = "\n".join(sections)
    return f"# Year {year}\n\n{body}"


def _month_template(slug: str) -> str:
    year, month = int(slug[:4]), int(slug[5:7])
    month_name = _MONTHS_DE[month]

    rows = [
        "| KW | Tag | Privat | Geschäftlich |",
        "|:---|:----|:-------|:-------------|",
    ]
    cur = date(year, month, 1)
    while cur.month == month:
        iso = cur.isocalendar()
        kw_cell = f"W{iso.week:02d}" if cur.weekday() == 0 else ""
        # Day cell: weekday abbrev + date as auto-link target
        day_cell = f"{_DAYS_DE[cur.weekday()]} · {cur.isoformat()}"
        # Weekend rows get a subtle separator via empty cell marker
        rows.append(f"| {kw_cell} | {day_cell} | | |")
        cur += timedelta(days=1)

    table = "\n".join(rows)
    return f"# {month_name} {year}\n\n{table}\n"


def _week_template(slug: str) -> str:
    year, week = int(slug[:4]), int(slug[6:])
    sections = []
    for wd in range(1, 8):          # Mon=1 … Sun=7
        d = date.fromisocalendar(year, week, wd)
        label = _DAYS_DE[wd - 1]
        sections.append(f"## {label} — {d.isoformat()}\n\n")
    body = "\n".join(sections)
    return f"# Week {slug}\n\n{body}"


def _day_template(slug: str) -> str:
    d = date.fromisoformat(slug)
    label = _DAYS_DE[d.weekday()]
    return f"# {label}, {slug}\n\n## Log\n\n## Aufgaben\n\n"


_TEMPLATE_FN = {
    "year":  _year_template,
    "month": _month_template,
    "week":  _week_template,
    "day":   _day_template,
}


# ─────────────────────── public API ──────────────────────────────────────────

def ensure_note(notes_dir: Path, slug: str, ntype: str) -> Path:
    """Return path to journal note; create with frontmatter + template if absent.

    Always cascades upward: creating a day also ensures its week, month, and year
    entries exist, so the visual hierarchy in the note list is always complete.
    """
    from datetime import datetime
    import frontmatter

    # Cascade: ensure parent hierarchy exists first (week → month → year)
    parent = _parent(slug, ntype)
    if parent:
        ensure_note(notes_dir, *parent)

    path = notes_dir / f"{slug}.md"
    if path.exists():
        return path

    template_fn = _TEMPLATE_FN.get(ntype)
    content = template_fn(slug) if template_fn else "\n\n"

    now = datetime.now().isoformat()
    post = frontmatter.Post(
        content,
        title=_title(slug, ntype),
        type=ntype,
        created=now,
        editedAt=now,
        tags=[f"journal-{ntype}"],
    )
    path.write_text(frontmatter.dumps(post), encoding="utf-8")
    return path


def append_to_journal(notes_dir: Path, text: str) -> Path:
    """Append *text* as a timestamped bullet to today's daily ## Log section.

    Creates the day entry (and its parent week/month/year cascade) if absent.
    Returns the path of the modified file.
    """
    import re as _re
    from datetime import datetime
    import frontmatter

    today = date.today()
    slug = slug_for(today, "day")
    path = ensure_note(notes_dir, slug, "day")

    now = datetime.now()
    timestamp = now.strftime("%H:%M")

    text = text.strip()
    is_todo = bool(_re.match(r'-\s*\[[ xX]\]', text))
    bullet = text if is_todo else f"- {timestamp}  {text}"

    post = frontmatter.load(str(path))
    content = post.content

    # Insert at the start of the ## Log section body (newest-first within the section)
    m = _re.search(r'(##\s+Log\s*\n\n?)', content, _re.IGNORECASE)
    if m:
        pos = m.end()
        content = content[:pos] + bullet + "\n" + content[pos:]
    else:
        content = content.rstrip("\n") + f"\n\n## Log\n\n{bullet}\n"

    post.content = content
    post.metadata["editedAt"] = now.isoformat()
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
