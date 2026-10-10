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
    pr = pr_ci_events(gh, since)
    return pr if not pr.ok else Result(data=out + pr.data)


# --- PR- und CI-Ereignisse (pr_duration, ci_red_before_merge) ---

def pr_ci_events(gh: GitHub, since: datetime) -> Result[list[Event]]:
    """Seit `since` gemergte PRs: pr_erstellt, pr_gemergt und je Lauf des PR-Branchs zwischen Erstellen und Merge
    ci_rot (failure) / ci_gruen (success). Item = PR-Nummer. Abgebrochene/andere Läufe und Nicht-PR-Läufe zählen nicht."""
    prs = gh.merged_prs()
    if not prs.ok:
        return prs
    runs = gh.runs_since((since - timedelta(days=1)).date().isoformat())  # PR kann vor `since` erstellt sein
    if not runs.ok:
        return runs
    out: list[Event] = []
    for p in prs.data:
        created, merged = _time(p["createdAt"]), _time(p["mergedAt"])
        if merged < since:
            continue
        out += [Event(p["number"], "pr_erstellt", created), Event(p["number"], "pr_gemergt", merged)]
        for r in runs.data:
            art = {"failure": "ci_rot", "success": "ci_gruen"}.get(r.get("conclusion"))
            if art and r.get("event") == "pull_request" and r.get("headBranch") == p["headRefName"] \
                    and created <= _time(r["createdAt"]) <= merged:
                out.append(Event(p["number"], art, _time(r["createdAt"])))
    return Result(data=out)


def pr_seconds(evs: list[Event]) -> list[float]:
    """Je PR: pr_erstellt bis pr_gemergt."""
    start = {e.item: e.zeit for e in evs if e.art == "pr_erstellt"}
    return [(e.zeit - start[e.item]).total_seconds() for e in evs if e.art == "pr_gemergt" and e.item in start]


def ci_red_share(evs: list[Event]) -> tuple[float, int] | None:
    """(Anteil gemergter PRs mit mindestens einem ci_rot in %, n) oder None ohne PRs."""
    merged = {e.item for e in evs if e.art == "pr_gemergt"}
    red = {e.item for e in evs if e.art == "ci_rot"} & merged
    return (100 * len(red) / len(merged), len(merged)) if merged else None


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


def _sized(n: int, value: str) -> str:
    return f"n={n} (zu klein)" if n < MIN_N else f"{value}, n={n}"


def _median_text(xs: list[float], unit: str) -> str:
    return _sized(len(xs), f"{_num(median(xs) / UNIT_SECONDS[unit])} {unit}") if xs else "keine Daten"


def report(rows: list[dict[str, str]], evs: list[Event]) -> list[Line]:
    out = []
    for r in rows:
        unit, target = r.get("unit", ""), r.get("target", "")
        if r.get("source") == "ticket_cycle_time" and unit in UNIT_SECONDS:
            text = _median_text(cycle_seconds(evs), unit)
        elif r.get("source") == "pr_duration" and unit in UNIT_SECONDS:
            text = _median_text(pr_seconds(evs), unit)
        elif r.get("source") == "ci_red_before_merge" and unit == "%":
            share = ci_red_share(evs)
            text = "keine Daten" if not share else _sized(share[1], f"{_num(share[0])} %")
        else:
            text = "unbekannt"
        out.append(Line(r.get("id", ""), r.get("name", ""), unit, target, text + (f", Ziel {target}" if target else "")))
    return out


def now() -> datetime:
    return datetime.now(UTC)
