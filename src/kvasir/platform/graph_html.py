"""Standalone HTML/SVG view of a Graph (lanes, nodes, edges, timeline). No network, no libraries, deterministic."""
from __future__ import annotations

from datetime import date, timedelta
from html import escape

from kvasir.platform.graph import _COLORS, _NAMES, Graph

W, H, GX, GY, PAD = 210, 62, 56, 12, 14  # node size, gaps, lane padding
_CSS = """
:root{--bg:#fff;--fg:#1f2328;--mute:#656d76;--lane:#f6f8fa;--line:#8c959f;--grid:#d0d7de;
--done:#2da44e;--dropped:#8c959f;--blocked:#cf222e;--in_review:#bf8700;--in_progress:#0969da;--open:#fff;--opentext:#1f2328}
@media(prefers-color-scheme:dark){:root{--bg:#0d1117;--fg:#e6edf3;--mute:#9198a1;--lane:#161b22;--line:#6e7681;--grid:#30363d;
--done:#238636;--dropped:#6e7681;--blocked:#da3633;--in_review:#9e6a03;--in_progress:#1f6feb;--open:#0d1117;--opentext:#e6edf3}}
body{margin:0;padding:16px;background:var(--bg);color:var(--fg);font:14px system-ui,sans-serif}
h1{font-size:18px;margin:0 0 12px}h2{font-size:15px;margin:20px 0 8px}svg{width:100%;height:auto;display:block}
text{fill:var(--fg);font-size:12px}.mute{fill:var(--mute)}.lane{fill:var(--lane)}.lanetitle{font-weight:600}
.edge{fill:none;stroke:var(--line);stroke-width:1.5}.grid{stroke:var(--grid);stroke-width:1}
.node rect{stroke:var(--line);stroke-width:1.5}.node text{fill:#fff}
.s-done rect{fill:var(--done)}.s-dropped rect{fill:var(--dropped)}.s-blocked rect{fill:var(--blocked)}
.s-in_review rect{fill:var(--in_review)}.s-in_progress rect{fill:var(--in_progress)}
.s-open rect{fill:var(--open)}.node.s-open text{fill:var(--opentext)}
.node.s-dimmed rect,.node.s-external rect{fill:var(--lane);stroke-dasharray:4 3}.node.s-dimmed text,.node.s-external text{fill:var(--mute)}
.warn{font-weight:700}.bar{stroke:var(--line)}.bar.s-open{fill:var(--open)}.bar.s-done{fill:var(--done)}
.bar.s-dropped{fill:var(--dropped)}.bar.s-blocked{fill:var(--blocked)}.bar.s-in_review{fill:var(--in_review)}
.bar.s-in_progress{fill:var(--in_progress)}.mark{fill:var(--blocked)}a:hover rect{stroke:var(--fg)}
.legend span{display:inline-block;margin-right:14px}.legend i{display:inline-block;width:12px;height:12px;
border:1px solid var(--line);margin-right:4px;vertical-align:-2px}
"""


def _cut(s: str, n: int) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1] + "…"


def _url(repo: str, n: int) -> str:
    return f"https://github.com/{repo}/issues/{n}"


def _layers(ids: list[str], edges: list[tuple[str, str]]) -> dict[str, int]:
    """Column = longest blocker chain before the node (bounded passes, so cycles cannot hang)."""
    col = dict.fromkeys(ids, 0)
    for _ in range(len(ids)):
        moved = False
        for a, b in edges:
            if a in col and b in col and col[b] <= col[a] and col[a] + 1 < len(ids):
                col[b], moved = col[a] + 1, True
        if not moved:
            break
    return col


def _node(x: int, y: int, cls: str, href: str | None, lines: list[str], tip: str, warn: bool) -> str:
    texts = "".join(
        f'<text x="{x + 8}" y="{y + 18 + 16 * k}"' + (' class="warn"' if warn and k == 2 else "") + f">{escape(t)}</text>"
        for k, t in enumerate(lines))
    g = f'<g class="node s-{cls}"><title>{escape(tip)}</title><rect x="{x}" y="{y}" width="{W}" height="{H}" rx="6"/>{texts}</g>'
    return f'<a href="{escape(href, quote=True)}">{g}</a>' if href else g


def _flow(g: Graph) -> str:
    rows = []  # (lane title, [(node id, class, lines, tooltip, href, warn)])
    for title, members in g.lanes:
        nodes = []
        for s in members:
            it = s.item
            name = _NAMES.get(s.status, s.status) + (" (laut Label)" if s.source == "label" else "")
            notes = (["Label widerspricht"] if s.hint else []) + list(s.notices)
            lines = [_cut(f"#{it.number} {it.title}", 30), name]
            if notes:
                lines.append("⚠ " + _cut(notes[0], 28) + (f" (+{len(notes) - 1})" if len(notes) > 1 else ""))
            tip = "\n".join([f"#{it.number} {it.title}", name, *([s.reason] if s.reason else []),
                             *([f"Label widerspricht: {s.hint}"] if s.hint else []), *s.notices])
            nodes.append((f"n{it.number}", s.status if s.status in _COLORS else "open", lines, tip,
                          _url(it.repo, it.number), bool(notes)))
        rows.append((title, nodes))
    if g.extra:
        rows.append(("Extern / älter", [(i, cls, [_cut(t, 30), sub], f"{t}\n{sub}", u, False)
                                         for i, (t, sub, cls, u) in sorted(g.extra.items())]))
    col = _layers([n[0] for _, ns in rows for n in ns], g.edges)
    width = PAD * 2 + (max(col.values(), default=0) + 1) * (W + GX) - GX
    pos: dict[str, tuple[int, int]] = {}
    lanes, y = [], 0
    for title, nodes in rows:
        stack: dict[int, int] = {}
        for nid, *_ in nodes:
            k = stack.get(col[nid], 0)
            stack[col[nid]] = k + 1
            pos[nid] = (PAD + col[nid] * (W + GX), y + 30 + k * (H + GY))
        h = 30 + max(stack.values(), default=0) * (H + GY) + PAD - GY
        lanes.append(f'<rect class="lane" x="0" y="{y}" width="{width}" height="{h}" rx="6"/>'
                     f'<text class="lanetitle" x="{PAD}" y="{y + 20}">{escape(_cut(title, 90))}</text>')
        y += h + 10
    edges = []
    for a, b in g.edges:
        (x1, y1), (x2, y2) = pos[a], pos[b]
        x1, y1, y2 = x1 + W, y1 + H // 2, y2 + H // 2
        dx = (x2 - x1) / 2 if x2 > x1 else 30  # same column / backwards: bow out to the sides
        edges.append(f'<path class="edge" d="M{x1} {y1}C{x1 + dx:g} {y1} {x2 - dx:g} {y2} {x2} {y2}" marker-end="url(#ar)"/>')
    nodes_svg = [_node(*pos[nid], cls, href, lines, tip, warn) for _, ns in rows for nid, cls, lines, tip, href, warn in ns]
    return (f'<svg viewBox="0 0 {width} {max(y, 1)}" role="img" aria-label="Graph"><defs>'
            '<marker id="ar" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">'
            '<path d="M0 0L10 5L0 10z" fill="var(--line)"/></marker></defs>'
            + "".join(lanes) + "".join(edges) + "".join(nodes_svg) + "</svg>")


def _timeline(g: Graph) -> str:
    items = [s for _, ms in g.lanes for s in ms
             if (s.item.schedule.planned_from and s.item.schedule.planned_to) or s.item.schedule.deadlines]
    if not items:
        return ""
    days: list[date] = []
    for s in items:
        sc = s.item.schedule
        days += [d.date for d in sc.deadlines] + [d for d in (sc.planned_from, sc.planned_to) if d]
    lo, hi = min(days) - timedelta(2), max(days) + timedelta(3)
    span, left, right, rh = (hi - lo).days or 1, 260, 900, 26

    def px(d: date) -> float:
        return left + (d - lo).days * (right - left) / span

    parts = []
    for k in range(0, span + 1, max(1, span // 12)):
        d = lo + timedelta(k)
        parts.append(f'<line class="grid" x1="{px(d):g}" y1="22" x2="{px(d):g}" y2="{22 + rh * len(items)}"/>'
                     f'<text class="mute" x="{px(d):g}" y="14" text-anchor="middle">{d.isoformat()[5:]}</text>')
    for r, s in enumerate(items):
        it, sc, y = s.item, s.item.schedule, 22 + r * rh
        notes = list(s.notices)
        tip = "\n".join([f"#{it.number} {it.title}", *notes])
        label = _cut(f"#{it.number} {it.title}", 34) + (" ⚠" if notes else "")
        parts.append(f'<a href="{_url(it.repo, it.number)}"><text x="0" y="{y + 17}">{escape(label)}'
                     f"<title>{escape(tip)}</title></text></a>")
        if sc.planned_from and sc.planned_to:
            x1, x2 = px(sc.planned_from), px(sc.planned_to + timedelta(1))
            parts.append(f'<rect class="bar s-{s.status if s.status in _COLORS else "open"}" x="{x1:g}" y="{y + 4}" '
                         f'width="{max(x2 - x1, 3):g}" height="{rh - 10}" rx="3">'
                         f"<title>{sc.planned_from} – {sc.planned_to}</title></rect>")
        for d in sc.deadlines:
            x, q = px(d.date), (rh - 6) // 2
            parts.append(f'<path class="mark" d="M{x:g} {y + 3}l7 {q}l-7 {q}l-7 -{q}z">'
                         f"<title>Frist {d.date}: {escape(d.label)}</title></path>")
    return (f'<h2>Zeitachse</h2><svg viewBox="0 0 {right + 20} {22 + rh * len(items) + 4}" role="img" '
            f'aria-label="Zeitachse">{"".join(parts)}</svg>')


def render(g: Graph) -> str:
    legend = "".join(f'<span><i style="background:var(--{k})"></i>{n}</span>' for k, n in _NAMES.items())
    return ('<!doctype html>\n<html lang="de"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="light dark">'
            f"<title>kvasir graph</title><style>{_CSS}</style></head><body><h1>kvasir graph</h1>"
            f'<p class="legend">{legend}<span>⚠ Hinweis (Label-Widerspruch, Termin)</span></p>'
            f"{_flow(g)}{_timeline(g)}</body></html>\n")
