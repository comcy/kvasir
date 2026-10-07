"""Termine eines Items: Meilenstein-Fälligkeit, Zeilen `Geplant:` / `Frist:` im Issue-Text. Pure, kein I/O."""
from __future__ import annotations

import re
from calendar import monthrange
from datetime import date

from kvasir.platform.models import Deadline, Schedule

_LINE = re.compile(r"^[ \t]*(Geplant|Frist):[ \t]*(.*?)[ \t]*$", re.IGNORECASE | re.MULTILINE)
_ISO = r"(\d{4})-(\d{2})-(\d{2})"


def _iso(s: str) -> date | None:
    m = re.fullmatch(_ISO, s.strip())
    try:
        return date(*map(int, m.groups())) if m else None
    except ValueError:
        return None


def resolve(text: str) -> date | None:
    """ISO-Datum, `Ende Q<n> <jahr>`, `Ende <jahr>-<monat>`, `Ende <jahr>`; sonst None."""
    t = text.strip()
    if d := _iso(t):
        return d
    try:
        if m := re.fullmatch(r"Ende Q([1-4]) (\d{4})", t, re.IGNORECASE):
            mon, y = int(m[1]) * 3, int(m[2])
        elif m := re.fullmatch(r"Ende (\d{4})-(\d{1,2})", t, re.IGNORECASE):
            mon, y = int(m[2]), int(m[1])
        elif m := re.fullmatch(r"Ende (\d{4})", t, re.IGNORECASE):
            mon, y = 12, int(m[1])
        else:
            return None
        return date(y, mon, monthrange(y, mon)[1])
    except ValueError:  # Monat 13, Jahr 0
        return None


def parse(body: str | None, milestone: dict | None) -> Schedule:
    """`milestone` = REST-Objekt (`title`, `due_on`) oder None. Nichts Erfundenes: fehlt eine Quelle, bleibt das Feld leer."""
    deadlines: list[Deadline] = []
    notes: list[str] = []
    von = bis = None
    if milestone and (due := _iso((milestone.get("due_on") or "")[:10])):
        deadlines.append(Deadline(due, milestone["title"]))
    seen: set[str] = set()
    for kind, text in _LINE.findall(body or ""):
        kind = kind.lower()
        if kind in seen:  # erste Zeile gilt
            continue
        seen.add(kind)
        if kind == "frist":
            if d := resolve(text):
                deadlines.append(Deadline(d, f"Frist: {text}"))
            else:
                notes.append(f"Frist nicht verstanden: {text!r}")
        else:
            parts = re.split(r"\s*[–—-]\s*(?=\d{4}-\d{2}-\d{2}$)", text) if text else []
            ds = [_iso(p) for p in parts]
            if len(ds) == 2 and all(ds):
                von, bis = ds
                if bis < von:
                    notes.append(f"Geplant: Ende {bis} liegt vor Start {von}")
            else:
                notes.append(f"Geplant nicht verstanden: {text!r}")
    return Schedule(tuple(sorted(deadlines, key=lambda x: x.date)), von, bis, tuple(notes))
