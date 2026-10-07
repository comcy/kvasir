"""Mermaid output (flowchart with lanes + optional gantt) for the issues of a repo. Read-only, deterministic."""
from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta

from kvasir.platform.gh import GitHub
from kvasir.platform.models import Error, ErrorKind, ItemStatus, Result
from kvasir.platform.status import derive

RECENT_DAYS = 14
WARN_NODES = 40
_COLORS = {  # status -> (fill, stroke)
    "done": ("#2da44e", "#1a7f37"), "dropped": ("#8c959f", "#57606a"), "blocked": ("#cf222e", "#a40e26"),
    "in_review": ("#bf8700", "#7d4e00"), "in_progress": ("#0969da", "#0550ae"), "open": ("#ffffff", "#57606a"),
}
_NAMES = {"done": "erledigt", "dropped": "verworfen", "blocked": "blockiert", "in_review": "in Review",
          "in_progress": "in Arbeit", "open": "offen"}
_GANTT = {"done": "done, ", "in_progress": "active, ", "in_review": "active, ", "blocked": "crit, "}


def _t(s: str) -> str:
    return re.sub(r"\s+", " ", s).replace('"', "#quot;").replace("<", "#lt;").replace(">", "#gt;").strip()


def _g(s: str) -> str:  # gantt task names: no ':' or ';'
    return re.sub(r"[:;\s]+", " ", s).strip()


def _node(s: ItemStatus) -> tuple[str, str]:
    """(node line, class)."""
    known = s.status in _COLORS
    name = _NAMES.get(s.status, s.status) + (" (laut Label)" if s.source == "label" else "")
    mark = " ⚠ Label widerspricht" if s.hint else ""
    cls = s.status if known else "open"
    return f'n{s.item.number}["#{s.item.number} {_t(s.item.title)}<br/>{name}{mark}"]', cls


def _gantt(lanes: list[tuple[str, list[ItemStatus]]]) -> list[str]:
    out = []
    for title, members in lanes:
        rows = []
        for s in members:
            sc, n = s.item.schedule, s.item.number
            label = _g(f"#{n} {s.item.title}")
            if sc.planned_from and sc.planned_to:
                rows.append(f"    {label} :{_GANTT.get(s.status, '')}n{n}, {sc.planned_from}, {sc.planned_to}")
            rows += [f"    {_g(f'Frist #{n} {d.label}')} :milestone, {d.date}, 0d" for d in sc.deadlines]
        if rows:
            out += [f"    section {_g(title)}", *rows]
    return ["gantt", "    dateFormat YYYY-MM-DD", *out] if out else []


def issue_graph(gh: GitHub, number: int | None = None, milestone: str | None = None,
                today: date | None = None) -> Result[tuple[str, int]]:
    """(markdown with mermaid blocks, node count). `number` = one feature (issue + sub-issues)."""
    today = today or datetime.now(UTC).date()
    if number is not None:
        root, subs = gh.item(number), gh.sub_issues(number)
        res = root if not root.ok else subs if not subs.ok else Result(data=[root.data, *subs.data])
    else:
        ms = None
        if milestone is not None:
            m = gh.milestone_number(milestone)
            if not m.ok or m.data is None:
                return m if not m.ok else Result(error=Error(ErrorKind.OTHER, f"milestone not found: {milestone}"))
            ms = m.data
        opened = gh.issues("open", ms)
        closed = gh.issues("closed", ms) if opened.ok else opened
        res = opened if not opened.ok else closed if not closed.ok else Result(data=[
            *opened.data, *(i for i in closed.data
                            if i.closed_at and i.closed_at >= (today - timedelta(RECENT_DAYS)).isoformat())])
    if not res.ok:
        return res
    prs = gh.pull_requests(limit=100, state="all")
    branches = gh.branch_names() if prs.ok else prs
    for r in (prs, branches):
        if not r.ok:
            return r
    items = {i.number: i for i in res.data}
    live = [p for p in prs.data if p.state in ("open", "draft")]
    stats: dict[int, ItemStatus] = {}
    edges: set[tuple[str, str]] = set()
    extra: dict[str, str] = {}  # node id -> node line (dimmed / external blockers)
    links: list[str] = []
    for n in sorted(items):
        it = items[n]
        bl = gh.blocked_by(n)
        if not bl.ok:
            return bl
        stats[n] = derive(it, bl.data, live, branches.data)
        for b in bl.data:
            if b.repo == gh.slug and b.number in items:
                edges.add((f"n{b.number}", f"n{n}"))
            elif it.state == "open":  # old closed items only show up when an open item depends on them
                if b.repo == gh.slug:
                    bid = f"n{b.number}"
                    extra[bid] = f'{bid}["#{b.number} {_t(b.title)}<br/>{b.state}"]:::dimmed'
                else:
                    bid = "ext_" + re.sub(r"\W", "_", b.repo) + f"_{b.number}"
                    extra[bid] = f'{bid}["{b.repo}#{b.number}<br/>extern"]:::external'
                    links.append(f'    click {bid} "https://github.com/{b.repo}/issues/{b.number}"')
                edges.add((bid, f"n{n}"))
    # lanes: parent issue = feature; an item with sub-issues is its own feature
    parents = {i.parent for i in items.values() if i.parent}
    lane_of = {n: (i.parent or (n if n in parents else None)) for n, i in items.items()}
    titles = {}
    for p in sorted(parents):
        if p in items:
            titles[p] = items[p].title
        else:
            r = gh.item(p)
            if not r.ok:
                return r
            titles[p] = r.data.title
    lanes: list[tuple[str, list[ItemStatus]]] = [
        (f"#{p} {titles[p]}", [stats[n] for n in sorted(stats) if lane_of[n] == p]) for p in sorted(parents)]
    if loose := [stats[n] for n in sorted(stats) if lane_of[n] is None]:
        lanes.append(("Ohne Feature", loose))
    flow = ["flowchart LR"]
    for k, (title, members) in enumerate(lanes):
        flow.append(f'    subgraph lane{k}["{_t(title)}"]')
        for s in members:
            line, cls = _node(s)
            flow.append(f"        {line}:::{cls}")
        flow.append("    end")
    flow += [f"    {line}" for _, line in sorted(extra.items())]
    flow += [f"    {a} --> {b}" for a, b in sorted(edges)]
    flow += sorted(links)
    for st, (fill, stroke) in _COLORS.items():
        flow.append(f"    classDef {st} fill:{fill},stroke:{stroke},color:{'#000' if st == 'open' else '#fff'}")
    flow.append("    classDef dimmed fill:#f6f8fa,stroke:#d0d7de,color:#8c959f,stroke-dasharray:3 3")
    flow.append("    classDef external fill:#d0d7de,stroke:#8c959f,color:#24292f")
    blocks = [flow]
    if g := _gantt(lanes):
        blocks.append(g)
    text = "\n\n".join("```mermaid\n" + "\n".join(b) + "\n```" for b in blocks) + "\n"
    return Result(data=(text, len(stats) + len(extra)))
