"""Metriken aus einem neutralen Ereignismodell `Event(item, art, zeit)`; Definition in workflow/metrics.tsv.

Erste Fassung: nur GitHub-Ticket-Ereignisse und `ticket_cycle_time`. Rein lesend.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import median

from kvasir.platform import Azure, GitHub, Result
from kvasir.platform.az import _CLOSED as AZ_CLOSED

METRICS_TSV = Path("workflow") / "metrics.tsv"
ARTEN = ("in_arbeit", "in_review", "geschlossen", "pr_erstellt", "pr_gemergt", "ci_rot", "ci_gruen")
MIN_N = 3
UNIT_SECONDS = {"h": 3600, "d": 86400}
IN_ARBEIT_LABEL = "status:in-progress"  # ponytail: fest; später aus workflow/states.tsv
IN_REVIEW_LABEL = "status:in-review"  # bei Azure DevOps steht der Status in System.Tags, gleiche Namen


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
    t = datetime.fromisoformat(s)
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def github_events(item: int, timeline: list[dict]) -> list[Event]:
    """REST-Timeline (`labeled` mit label.name, `closed`, jeweils created_at) -> neutrale Ereignisse."""
    out = []
    for e in timeline:
        if e.get("event") == "labeled" and (e.get("label") or {}).get("name") == IN_ARBEIT_LABEL:
            out.append(Event(item, "in_arbeit", _time(e["created_at"])))
        elif e.get("event") == "labeled" and (e.get("label") or {}).get("name") == IN_REVIEW_LABEL:
            out.append(Event(item, "in_review", _time(e["created_at"])))
        elif e.get("event") == "closed":
            out.append(Event(item, "geschlossen", _time(e["created_at"])))
    return out


def azure_events(item: int, revisions: list[dict]) -> list[Event]:
    """Work-Item-Revisionen -> Ereignisse beim Wechsel: Tag `status:in-progress`/`status:in-review` neu (Tags `;`-getrennt),
    Zustand in einen geschlossenen Zustand. Form UNVERIFIZIERT: tolerant (fehlende Felder erben von der Vorrevision,
    Revisionen ohne `System.ChangedDate` zählen nicht)."""
    out, tags, closed = [], set(), False
    for r in sorted((r for r in revisions if isinstance(r, dict)), key=lambda r: r.get("rev") or 0):
        f = r.get("fields") or {}
        if "System.Tags" in f:
            new = {t.strip().lower() for t in (f["System.Tags"] or "").split(";") if t.strip()}
        else:
            new = tags
        now_closed = (f["System.State"] or "").lower() in AZ_CLOSED if "System.State" in f else closed
        when = f.get("System.ChangedDate") or r.get("changedDate")
        if when:
            for label, art in ((IN_ARBEIT_LABEL, "in_arbeit"), (IN_REVIEW_LABEL, "in_review")):
                if label in new - tags:
                    out.append(Event(item, art, _time(when)))
            if now_closed and not closed:
                out.append(Event(item, "geschlossen", _time(when)))
        tags, closed = new, now_closed
    return out


def azure_ticket_events(az: Azure, since: datetime) -> Result[list[Event]]:
    """Ereignisse der seit `since` geschlossenen Work Items. # ponytail: eine Revisionsabfrage je Work Item"""
    ids = az.closed_item_ids(since.date().isoformat())
    if not ids.ok:
        return ids
    out: list[Event] = []
    for n in ids.data:
        revs = az.revisions(n)
        if not revs.ok:
            return revs
        evs = azure_events(n, revs.data)
        if any(e.art == "geschlossen" and e.zeit >= since for e in evs):
            out += evs
    return Result(data=out)


def azure_pr_ci_events(az: Azure, since: datetime) -> Result[list[Event]]:
    """Wie `pr_ci_events`: `az repos pr list --status completed` (creationDate, closedDate) und `az pipelines runs list`
    (reason `pullRequest`, result succeeded/failed, queueTime; PR über `refs/pull/<id>/merge` oder Quell-Branch)."""
    prs, runs = az.completed_prs(), az.runs()
    for r in (prs, runs):
        if not r.ok:
            return r
    ps = [(d["pullRequestId"], _time(d["creationDate"]), _time(d.get("closedDate") or d["closeDate"]),
           (d.get("sourceRefName") or "").removeprefix("refs/heads/"))
          for d in prs.data if d.get("closedDate") or d.get("closeDate")]
    rs = []
    for d in runs.data:
        art = {"failed": "ci_rot", "succeeded": "ci_gruen"}.get(d.get("result"))
        if art and d.get("reason") == "pullRequest" and d.get("queueTime"):
            ref = d.get("sourceBranch") or ""
            m = re.fullmatch(r"refs/pull/(\d+)/.*", ref)
            rs.append((art, _time(d["queueTime"]), ref.removeprefix("refs/heads/"), int(m[1]) if m else None))
    return Result(data=_pr_events(ps, rs, since))


def events(gh: GitHub | Azure, since: datetime, srcs: set[str]) -> Result[list[Event]]:
    """Ereignisse der seit `since` geschlossenen Tickets und gemergten PRs, nur für die Quellen `srcs` (aus metrics.tsv).
    # ponytail: erste 100 geschlossene Issues, keine Seiten"""
    if isinstance(gh, Azure):
        out = azure_ticket_events(gh, since) if "ticket_cycle_time" in srcs else Result(data=[])
        if not out.ok or not srcs & {"pr_duration", "ci_red_before_merge"}:
            return out
        pr = azure_pr_ci_events(gh, since)
        return pr if not pr.ok else Result(data=out.data + pr.data)
    out = []
    res = gh.issues("closed") if "ticket_cycle_time" in srcs else Result(data=[])
    if not res.ok:
        return res
    for it in res.data:
        if not it.closed_at or it.closed_at < since.date().isoformat():  # closed_at = Datum (YYYY-MM-DD)
            continue
        tl = gh.timeline(it.number)
        if not tl.ok:
            return tl
        out += github_events(it.number, tl.data)
    if not srcs & {"pr_duration", "ci_red_before_merge"}:
        return Result(data=out)
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
    ps = [(p["number"], _time(p["createdAt"]), _time(p["mergedAt"]), p["headRefName"]) for p in prs.data]
    rs = [(art, _time(r["createdAt"]), r["headBranch"], None) for r in runs.data
          if (art := {"failure": "ci_rot", "success": "ci_gruen"}.get(r.get("conclusion"))) and r.get("event") == "pull_request"]
    return Result(data=_pr_events(ps, rs, since))


def _pr_events(prs: list[tuple[int, datetime, datetime, str]], runs: list[tuple[str, datetime, str, int | None]],
               since: datetime) -> list[Event]:
    """prs: (Nummer, erstellt, gemergt, Branch); runs: (Art, Zeit, Branch, PR-Nummer oder None = per Branch zuordnen)."""
    out: list[Event] = []
    for n, created, merged, branch in prs:
        if merged < since:
            continue
        out += [Event(n, "pr_erstellt", created), Event(n, "pr_gemergt", merged)]
        out += [Event(n, art, when) for art, when, b, pn in runs
                if (pn == n if pn else b == branch) and created <= when <= merged]
    return out


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


# --- eval_pass_rate: lokale Berichte, keine Plattform ---
EVALS_DIR = Path("evals") / "reports"
ANMERKUNG = "## Anmerkung (nachträglich)"


def eval_results(reports: Path) -> list[bool]:
    """Je Aufgabe des neuesten Berichts (`*.md`, Name = Zeitstempel) ohne Abschnitt `## Anmerkung (nachträglich)`: bestanden?.
    `nicht prüfbar` zählt nicht.

    Spalten nach Namen (`Aufgabe`, `Ergebnis`), daher auch das Altformat ohne Kosten-Spalte.
    """
    files = sorted(reports.glob("*.md")) if reports.is_dir() else []
    texts = [t for f in files if ANMERKUNG not in (t := f.read_text(encoding="utf-8"))]  # nachträglich entwertet
    if not texts:
        return []
    head, out = [], []
    for line in texts[-1].splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if "Aufgabe" in cells:
            head = cells
        elif head and "Ergebnis" in head and len(cells) == len(head):
            res = cells[head.index("Ergebnis")]
            if res in ("bestanden", "durchgefallen"):
                out.append(res == "bestanden")
    return out


# --- rework_fixes_per_change: PR-Titel `fix(...)` + `Refs/Closes #N` auf dasselbe Feature ---
_REF = re.compile(r"\b(?:refs|closes)\s+#(\d+)", re.IGNORECASE)
_FIX = re.compile(r"^fix(\(.*?\))?!?:")


def rework_counts(gh: GitHub, since: datetime) -> Result[list[int]]:
    """Gemergte Fix-PRs je Feature (Feature = Parent des bezogenen Issues, sonst das Issue selbst).

    Grundmenge: Features der seit `since` geschlossenen Tickets, mit 0 wenn ohne Fix-PR.
    # ponytail: erste 100 PRs/Issues; Heuristik über Titel und Bezug, Fehltreffer möglich
    """
    closed = gh.issues("closed")
    prs = gh.pull_requests(100, "merged")
    for r in (closed, prs):
        if not r.ok:
            return r
    parent = {i.number: i.parent for i in closed.data}
    feature = {i.number: i.parent or i.number
               for i in closed.data if i.closed_at and i.closed_at >= since.date().isoformat()}
    counts = dict.fromkeys(set(feature.values()), 0)
    for p in prs.data:
        if not (p.state == "merged" and _FIX.match(p.title) and p.created_at and _time(p.created_at) >= since):
            continue
        for n in {int(x) for x in _REF.findall(p.body or "")}:
            if n not in parent:  # offenes Issue: Parent nachschlagen
                it = gh.item(n)
                if not it.ok:
                    return it
                parent[n] = it.data.parent
            if (f := parent[n] or n) in counts:
                counts[f] += 1
    return Result(data=list(counts.values()))


def _num(x: float) -> str:
    return f"{x:.1f}".removesuffix(".0")


def _sized(n: int, value: str) -> str:
    return f"n={n} (zu klein)" if n < MIN_N else f"{value}, n={n}"


def _median_text(xs: list[float], unit: str) -> str:
    return _sized(len(xs), f"{_num(median(xs) / UNIT_SECONDS[unit])} {unit}") if xs else "keine Daten"


def report(rows: list[dict[str, str]], evs: list[Event], evals: list[bool] | None = None,
           rework: list[int] | None = None) -> list[Line]:
    out = []
    for r in rows:
        unit, target = r.get("unit", ""), r.get("target", "")
        if r.get("source") == "eval_pass_rate" and evals is not None:
            text = _sized(len(evals), f"{_num(round(100 * sum(evals) / len(evals), 1))} {unit}".strip()) if evals else "keine Daten"
        elif r.get("source") == "rework_fixes_per_change" and rework is not None:
            text = (_sized(len(rework), _num(sum(rework) / len(rework))) if rework else "keine Daten") \
                + " (Heuristik: fix(...) + Refs/Closes)"
        elif r.get("source") == "ticket_cycle_time" and unit in UNIT_SECONDS:
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
