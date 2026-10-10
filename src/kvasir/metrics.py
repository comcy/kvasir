"""Metriken aus einem neutralen Ereignismodell `Event(item, art, zeit)`; Definition in workflow/metrics.tsv.

Erste Fassung: nur GitHub-Ticket-Ereignisse und `ticket_cycle_time`. Rein lesend.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import median

from kvasir import repo_file
from kvasir.platform import Azure, GitHub, Result
from kvasir.platform.az import _CLOSED as AZ_CLOSED

METRICS_TSV = Path("workflow") / "metrics.tsv"
ARTEN = ("in_arbeit", "in_review", "geschlossen", "pr_erstellt", "pr_gemergt", "ci_rot", "ci_gruen")
MIN_N = 3
UNIT_SECONDS = {"h": 3600, "d": 86400}
STATES_TSV = Path("workflow") / "states.tsv"
SOURCES_TSV = Path("workflow") / "metric-sources.tsv"
IN_ARBEIT_LABEL = "status:in-progress"  # Rückfall, wenn workflow/states.tsv fehlt
IN_REVIEW_LABEL = "status:in-review"  # bei Azure DevOps steht der Status in System.Tags, gleiche Namen
LABELS = (IN_ARBEIT_LABEL, IN_REVIEW_LABEL)
SOURCES = ("ticket_cycle_time", "pr_duration", "ci_red_before_merge", "rework_fixes_per_change", "eval_pass_rate")
REQUIRED = ("id", "art", "name", "unit", "source")
ARTEN_METRIK = ("leading", "lagging")
UNITS = ("h", "d", "%", "n")


def status_labels(root: Path) -> tuple[str, str]:
    """(in_arbeit, in_review)-Label aus den Zeilen `kind=status` von workflow/states.tsv (Id endet auf `in-progress` /
    `in-review`); je fehlend oder ohne Datei der feste Name."""
    try:
        ids = [r.get("id", "") for r in repo_file._tsv(root, STATES_TSV) if r.get("kind") == "status"]
    except OSError:
        ids = []
    return tuple(next((i for i in ids if i.endswith(suffix)), default)
                 for suffix, default in (("in-progress", IN_ARBEIT_LABEL), ("in-review", IN_REVIEW_LABEL)))


def problems(root: Path) -> list[str]:
    """Dateifehler von workflow/metrics.tsv und Quellen, die kvasir nicht auswertet (auch wenn sie in metric-sources.tsv stehen)."""
    out: list[str] = []
    try:
        rows = repo_file._tsv(root, METRICS_TSV)
        head = (root / METRICS_TSV).read_text(encoding="utf-8").splitlines()
    except OSError as e:
        return [f"{METRICS_TSV}: {e.strerror or e}"]
    cols = next((x.split("\t") for x in head if x.strip() and not x.startswith("#")), [])
    out += [f"{METRICS_TSV}: required column {c} missing" for c in REQUIRED if c not in cols]
    listed = None
    try:
        if (root / SOURCES_TSV).exists():
            listed = {r.get("name") for r in repo_file._tsv(root, SOURCES_TSV)}
            out += [f"{SOURCES_TSV}: source {n} is not evaluated by kvasir (shown as unknown)" for n in sorted(listed - {None, *SOURCES})]
    except OSError as e:
        out.append(f"{SOURCES_TSV}: {e.strerror or e}")
    seen: set[str] = set()
    for i, r in enumerate(rows, 1):
        label = f"{METRICS_TSV}: metric {r.get('id') or i}"
        out += [f"{label}: required field {c} empty" for c in REQUIRED if c in cols and not r.get(c)]
        if r.get("id") in seen:
            out.append(f"{label}: duplicate id {r['id']}")
        seen.add(r.get("id", ""))
        if r.get("art") and r["art"] not in ARTEN_METRIK:
            out.append(f"{label}: invalid art {r['art']} (leading|lagging)")
        if r.get("unit") and r["unit"] not in UNITS:
            out.append(f"{label}: invalid unit {r['unit']} (h|d|%|n)")
        if (src := r.get("source")) and src not in SOURCES:
            out.append(f"{label}: source {src} is not evaluated by kvasir (shown as unknown)")
        elif src and listed is not None and src not in listed:
            out.append(f"{label}: source {src} is not in {SOURCES_TSV}")
    return out


@dataclass(frozen=True)
class Event:
    item: int
    art: str
    zeit: datetime


@dataclass(frozen=True)
class Line:
    id: str
    art: str
    name: str
    unit: str
    target: str
    text: str  # Wert/Hinweis fürs Menschen
    value: float | None = None  # nur bei status ok
    n: int | None = None  # None = unbekannt
    status: str = "ok"  # ok | zu_klein | keine_daten | unbekannt
    note: str = ""


def parse_since(s: str) -> timedelta:
    m = re.fullmatch(r"(\d+)d", s)
    if not m or not int(m.group(1)):
        raise ValueError(f"--since: expected <n>d, got {s!r}")
    return timedelta(days=int(m.group(1)))


def _time(s: str) -> datetime:
    t = datetime.fromisoformat(s)
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def github_events(item: int, timeline: list[dict], labels: tuple[str, str] = LABELS) -> list[Event]:
    """REST-Timeline (`labeled` mit label.name, `closed`, jeweils created_at) -> neutrale Ereignisse."""
    out = []
    for e in timeline:
        if e.get("event") == "labeled" and (e.get("label") or {}).get("name") == labels[0]:
            out.append(Event(item, "in_arbeit", _time(e["created_at"])))
        elif e.get("event") == "labeled" and (e.get("label") or {}).get("name") == labels[1]:
            out.append(Event(item, "in_review", _time(e["created_at"])))
        elif e.get("event") == "closed":
            out.append(Event(item, "geschlossen", _time(e["created_at"])))
    return out


def azure_events(item: int, revisions: list[dict], labels: tuple[str, str] = LABELS) -> list[Event]:
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
            for label, art in ((labels[0].lower(), "in_arbeit"), (labels[1].lower(), "in_review")):
                if label in new - tags:
                    out.append(Event(item, art, _time(when)))
            if now_closed and not closed:
                out.append(Event(item, "geschlossen", _time(when)))
        tags, closed = new, now_closed
    return out


def azure_ticket_events(az: Azure, since: datetime, labels: tuple[str, str] = LABELS) -> Result[list[Event]]:
    """Ereignisse der seit `since` geschlossenen Work Items. # ponytail: eine Revisionsabfrage je Work Item"""
    ids = az.closed_item_ids(since.date().isoformat())
    if not ids.ok:
        return ids
    out: list[Event] = []
    for n in ids.data:
        revs = az.revisions(n)
        if not revs.ok:
            return revs
        evs = azure_events(n, revs.data, labels)
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


def events(gh: GitHub | Azure, since: datetime, srcs: set[str], labels: tuple[str, str] = LABELS) -> Result[list[Event]]:
    """Ereignisse der seit `since` geschlossenen Tickets und gemergten PRs, nur für die Quellen `srcs` (aus metrics.tsv).
    # ponytail: erste 100 geschlossene Issues, keine Seiten"""
    if isinstance(gh, Azure):
        out = azure_ticket_events(gh, since, labels) if "ticket_cycle_time" in srcs else Result(data=[])
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
        out += github_events(it.number, tl.data, labels)
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


def _median(xs: list[float], unit: str) -> tuple[float, int] | None:
    return (median(xs) / UNIT_SECONDS[unit], len(xs)) if xs else None


def report(rows: list[dict[str, str]], evs: list[Event], evals: list[bool] | None = None,
           rework: list[int] | None = None) -> list[Line]:
    out = []
    for r in rows:
        unit, target, src = r.get("unit", ""), r.get("target", ""), r.get("source")
        note, shown = "", f" {unit}"
        if src == "eval_pass_rate" and evals is not None:
            res = (100 * sum(evals) / len(evals), len(evals)) if evals else None
        elif src == "rework_fixes_per_change" and rework is not None:
            res = (sum(rework) / len(rework), len(rework)) if rework else None
            note, shown = " (Heuristik: fix(...) + Refs/Closes)", ""
        elif src == "ticket_cycle_time" and unit in UNIT_SECONDS:
            res = _median(cycle_seconds(evs), unit)
        elif src == "pr_duration" and unit in UNIT_SECONDS:
            res = _median(pr_seconds(evs), unit)
        elif src == "ci_red_before_merge" and unit == "%":
            res = ci_red_share(evs)
        else:
            res = ()  # unbekannt
        if res == ():
            status, value, n, text = "unbekannt", None, None, "unbekannt"
        elif res is None:
            status, value, n, text = "keine_daten", None, 0, "keine Daten"
        elif res[1] < MIN_N:
            status, value, n, text = "zu_klein", None, res[1], f"n={res[1]} (zu klein)"
        else:
            status, value, n = "ok", round(res[0], 1), res[1]
            text = f"{_num(value)}{shown}, n={n}"
        out.append(Line(r.get("id", ""), r.get("art", ""), r.get("name", ""), unit, target,
                        text + (note if status != "unbekannt" else "") + (f", Ziel {target}" if target else ""),
                        value, n, status, note))
    return out


def _target(t: str) -> float | None:
    try:
        return float(t)
    except ValueError:
        return None


def _int(x: float | None):
    return None if x is None else int(x) if x == int(x) else x


def to_json(lines: list[Line]) -> str:
    """Feste Schlüssel; value/n/target `null`, wo es nichts Gemessenes gibt (nichts Erfundenes)."""
    return json.dumps([{"id": ln.id, "art": ln.art, "name": ln.name, "unit": ln.unit, "value": _int(ln.value),
                        "n": ln.n, "target": _int(_target(ln.target)), "status": ln.status} for ln in lines],
                      ensure_ascii=False, indent=2) + "\n"


def to_markdown(lines: list[Line]) -> str:
    """Tabelle zum Einfügen in Berichte; `|` in Zellen maskiert."""
    esc = lambda x: (str(x).replace("|", "\\|")) or "-"
    out = ["| Id | Art | Metrik | Wert | n | Ziel | Status |", "| --- | --- | --- | ---: | ---: | ---: | --- |"]
    for ln in lines:
        wert = "-"
        if ln.value is not None:
            wert = _num(ln.value) + (f" {ln.unit}" if ln.unit in UNIT_SECONDS or ln.unit == "%" else "") \
                + (" (Heuristik)" if ln.note else "")
        t = _target(ln.target)
        cells = (ln.id, ln.art, ln.name or ln.id, wert, "-" if ln.n is None else ln.n,
                 "-" if t is None else _num(t), ln.status.replace("_", " "))
        out.append("| " + " | ".join(esc(c) for c in cells) + " |")
    return "\n".join(out) + "\n"


def now() -> datetime:
    return datetime.now(UTC)
