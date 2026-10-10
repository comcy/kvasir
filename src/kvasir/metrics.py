"""Metriken aus einem neutralen Ereignismodell `Event(item, art, zeit)`; Definition in workflow/metrics.tsv.

Erste Fassung: nur GitHub-Ticket-Ereignisse und `ticket_cycle_time`. Rein lesend.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import median

from kvasir.platform import GitHub, Result

METRICS_TSV = Path("workflow") / "metrics.tsv"
ARTEN = ("in_arbeit", "in_review", "geschlossen", "pr_erstellt", "pr_gemergt", "ci_rot", "ci_gruen")
MIN_N = 3
UNIT_SECONDS = {"h": 3600, "d": 86400}
IN_ARBEIT_LABEL = "status:in-progress"  # ponytail: fest; später aus workflow/states.tsv


@dataclass(frozen=True)
class Event:
    item: int
    art: str
    zeit: datetime


@dataclass(frozen=True)
class Line:
    id: str
    name: str
    unit: str
    target: str
    text: str  # Wert/Hinweis fürs Menschen


def parse_since(s: str) -> timedelta:
    m = re.fullmatch(r"(\d+)d", s)
    if not m or not int(m.group(1)):
        raise ValueError(f"--since: expected <n>d, got {s!r}")
    return timedelta(days=int(m.group(1)))


def _time(s: str) -> datetime:
    return datetime.fromisoformat(s)


def github_events(item: int, timeline: list[dict]) -> list[Event]:
    """REST-Timeline (`labeled` mit label.name, `closed`, jeweils created_at) -> neutrale Ereignisse."""
    out = []
    for e in timeline:
        if e.get("event") == "labeled" and (e.get("label") or {}).get("name") == IN_ARBEIT_LABEL:
            out.append(Event(item, "in_arbeit", _time(e["created_at"])))
        elif e.get("event") == "closed":
            out.append(Event(item, "geschlossen", _time(e["created_at"])))
    return out


def events(gh: GitHub, since: datetime) -> Result[list[Event]]:
    """Ereignisse der seit `since` geschlossenen Tickets. # ponytail: erste 100 geschlossene Issues, keine Seiten"""
    res = gh.issues("closed")
    if not res.ok:
        return res
    out: list[Event] = []
    for it in res.data:
        if not it.closed_at or it.closed_at < since.date().isoformat():  # closed_at = Datum (YYYY-MM-DD)
            continue
        tl = gh.timeline(it.number)
        if not tl.ok:
            return tl
        out += github_events(it.number, tl.data)
    return Result(data=out)


def cycle_seconds(evs: list[Event]) -> list[float]:
    """Je Ticket: erstes `in_arbeit` bis erstes folgendes `geschlossen`. Ohne `in_arbeit` zählt es nicht."""
    by: dict[int, list[Event]] = {}
    for e in evs:
        by.setdefault(e.item, []).append(e)
    out = []
    for es in by.values():
        start = min((e.zeit for e in es if e.art == "in_arbeit"), default=None)
        end = min((e.zeit for e in es if e.art == "geschlossen" and start and e.zeit >= start), default=None)
        if start and end:
            out.append((end - start).total_seconds())
    return out


def _num(x: float) -> str:
    return f"{x:.1f}".removesuffix(".0")


def report(rows: list[dict[str, str]], evs: list[Event]) -> list[Line]:
    out = []
    for r in rows:
        unit, target = r.get("unit", ""), r.get("target", "")
        if r.get("source") == "ticket_cycle_time" and unit in UNIT_SECONDS:
            xs = cycle_seconds(evs)
            if not xs:
                text = "keine Daten"
            elif len(xs) < MIN_N:
                text = f"n={len(xs)} (zu klein)"
            else:
                text = f"{_num(median(xs) / UNIT_SECONDS[unit])} {unit}, n={len(xs)}"
        else:
            text = "unbekannt"
        out.append(Line(r.get("id", ""), r.get("name", ""), unit, target, text + (f", Ziel {target}" if target else "")))
    return out


def now() -> datetime:
    return datetime.now(UTC)
