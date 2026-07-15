"""Wikilink graph across a workspace's notes — nodes are notes/journal
entries, edges are resolved `[[wikilink]]` references. Pure data/layout
logic, no Textual dependency, so it can be built and tested independently
of the TUI widget that renders it (`src/tui/widgets/note_graph.py`)."""
from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from pathlib import Path

import frontmatter

from src.data.journal import note_type

_WIKILINK_RE = re.compile(r'\[\[([^\]]+)\]\]')


def resolve_wikilink_target(name: str, existing_stems: set[str]) -> str | None:
    """Match a `[[name]]` reference against known note stems: exact name
    first, then a slugified fallback (spaces -> hyphens, lowercased) — the
    same two-step rule `notes_panel.py._resolve_wikilinks` applies."""
    slug = name.lower().replace(" ", "-")
    for candidate in (name, slug):
        if candidate in existing_stems:
            return candidate
    return None


@dataclass
class GraphNode:
    id: str
    title: str
    ntype: str  # "note" | "day" | "week" | "month" | "year"
    in_degree: int = 0   # notes that link TO this one — the "depended on" signal
    out_degree: int = 0  # links this note makes to others

    @property
    def degree(self) -> int:
        return self.in_degree + self.out_degree


@dataclass
class GraphData:
    nodes: dict[str, GraphNode] = field(default_factory=dict)
    edges: list[tuple[str, str]] = field(default_factory=list)  # directed (source, target)


def build_graph(notes_dir: Path) -> GraphData:
    """Scan every note once, resolve wikilinks, return nodes + deduped directed edges."""
    paths = sorted(notes_dir.glob("*.md"))
    stems = {p.stem for p in paths}

    nodes: dict[str, GraphNode] = {}
    edge_set: set[tuple[str, str]] = set()

    for p in paths:
        try:
            post = frontmatter.load(str(p))
            title = post.metadata.get("title", p.stem)
            content = post.content
        except Exception:
            title = p.stem
            content = p.read_text(encoding="utf-8", errors="replace")

        nodes[p.stem] = GraphNode(id=p.stem, title=title, ntype=note_type(p.stem))

        for m in _WIKILINK_RE.finditer(content):
            target = resolve_wikilink_target(m.group(1), stems)
            if target is None or target == p.stem:
                continue
            edge_set.add((p.stem, target))

    edges = sorted(edge_set)
    for source, target in edges:
        nodes[source].out_degree += 1
        nodes[target].in_degree += 1

    return GraphData(nodes=nodes, edges=edges)


_CELL_ASPECT = 2.0  # terminal character cells read ~twice as tall as wide


def layout_graph(
    graph: GraphData, width: int, height: int, iterations: int = 150,
) -> dict[str, tuple[float, float]]:
    """Fruchterman-Reingold-style force layout, returning positions in grid
    coordinates (0 <= x < width, 0 <= y < height). Deterministic (fixed seed)
    so a reload with unchanged notes doesn't visibly reshuffle the graph.

    Simulates in "visual" space (vertical axis stretched by `_CELL_ASPECT` to
    match how much taller a character cell reads than it is wide), then
    scales back to character coordinates uniformly on both axes at the end —
    scaling x/y independently would squash the layout toward a flat line on
    the wide-short canvases this widget actually renders into.
    """
    ids = list(graph.nodes)
    n = len(ids)
    if n == 0:
        return {}
    if n == 1:
        return {ids[0]: (width / 2, height / 2)}

    vw, vh = float(width), float(height) * _CELL_ASPECT

    rng = random.Random(0)
    pos = {i: [rng.uniform(0, vw), rng.uniform(0, vh)] for i in ids}
    k = (vw * vh / n) ** 0.5

    for step in range(iterations):
        temperature = max(vw, vh) * 0.1 * (1 - step / iterations)
        disp = {i: [0.0, 0.0] for i in ids}

        for i_idx, i in enumerate(ids):
            for j in ids[i_idx + 1:]:
                dx = pos[i][0] - pos[j][0]
                dy = pos[i][1] - pos[j][1]
                dist = max((dx * dx + dy * dy) ** 0.5, 1e-4)
                force = k * k / dist
                fx, fy = dx / dist * force, dy / dist * force
                disp[i][0] += fx
                disp[i][1] += fy
                disp[j][0] -= fx
                disp[j][1] -= fy

        for a, b in graph.edges:
            dx = pos[a][0] - pos[b][0]
            dy = pos[a][1] - pos[b][1]
            dist = max((dx * dx + dy * dy) ** 0.5, 1e-4)
            force = dist * dist / k
            fx, fy = dx / dist * force, dy / dist * force
            disp[a][0] -= fx
            disp[a][1] -= fy
            disp[b][0] += fx
            disp[b][1] += fy

        for i in ids:
            dx, dy = disp[i]
            dist = max((dx * dx + dy * dy) ** 0.5, 1e-4)
            capped = min(dist, temperature)
            pos[i][0] += dx / dist * capped
            pos[i][1] += dy / dist * capped

    xs = [p[0] for p in pos.values()]
    ys = [p[1] for p in pos.values()]
    min_x, min_y = min(xs), min(ys)
    span_x = max(max(xs) - min_x, 1e-6)
    span_y = max(max(ys) - min_y, 1e-6)

    margin = 1
    usable_w = max(width - 2 * margin, 1)
    usable_h = max(height - 2 * margin, 1)

    # Uniform scale on both axes (in visual units) — preserves shape.
    scale = min(usable_w / span_x, (usable_h * _CELL_ASPECT) / span_y)
    offset_x = margin + (usable_w - span_x * scale) / 2
    offset_y = margin + (usable_h - span_y * scale / _CELL_ASPECT) / 2

    return {
        i: (
            offset_x + (pos[i][0] - min_x) * scale,
            offset_y + (pos[i][1] - min_y) * scale / _CELL_ASPECT,
        )
        for i in ids
    }
