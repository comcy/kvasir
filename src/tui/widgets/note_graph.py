"""TUI-native wikilink graph — a character-grid rendering of the note/journal
link graph (`src/data/links.py`), navigable without a mouse. Not a pixel
graph like Obsidian's, but the same mental model: node size/weight signals
importance (in-degree = "how many notes depend on this one"), spatial
closeness follows a force layout, and you can jump straight to any node."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Static
from rich.text import Text

from src.data.links import GraphData, build_graph, layout_graph
from src.workspace.manager import WorkspaceManager

_BADGE = {"day": "D", "week": "W", "month": "M", "year": "Y", "note": "N"}
_COLOR = {"day": "green", "week": "cyan", "month": "yellow", "year": "magenta", "note": "white"}
_LEGEND = "N note · D day · W week · M month · Y year · bold = hub (many notes link here)"


def _line_points(x0: int, y0: int, x1: int, y1: int) -> list[tuple[int, int]]:
    """Bresenham's line algorithm between two integer grid points."""
    points = []
    dx, dy = abs(x1 - x0), -abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx + dy
    x, y = x0, y0
    while True:
        points.append((x, y))
        if x == x1 and y == y1:
            break
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x += sx
        if e2 <= dx:
            err += dx
            y += sy
    return points


def _edge_char(dx: int, dy: int) -> str:
    if dx == 0:
        return "│"
    if dy == 0:
        return "─"
    return "╲" if (dy / dx) > 0 else "╱"


class _GraphCanvas(Widget):
    """Pure rendering surface — all state/input handling lives on the owning
    NoteGraphView, which is the focusable widget."""

    def __init__(self, owner: "NoteGraphView") -> None:
        super().__init__()
        self._owner = owner

    def render(self) -> Text:
        return self._owner._render_canvas(self.size.width, self.size.height)


class NoteGraphView(Widget, can_focus=True):
    BORDER_TITLE = "Graph"

    DEFAULT_CSS = """
    NoteGraphView { layout: vertical; height: 1fr; }
    NoteGraphView _GraphCanvas { height: 1fr; }
    NoteGraphView #graph-status { height: 1; color: $foreground 60%; padding: 0 1; }
    """

    class Activated(Message):
        def __init__(self, note_id: str) -> None:
            super().__init__()
            self.note_id = note_id

    def __init__(self, wm: WorkspaceManager, **kwargs) -> None:
        super().__init__(**kwargs)
        self._wm = wm
        self._graph: GraphData = GraphData()
        self._positions: dict[str, tuple[float, float]] = {}
        self._selected: str | None = None
        self._layout_size: tuple[int, int] | None = None

    def compose(self) -> ComposeResult:
        yield _GraphCanvas(self)
        yield Static(self._status_text(), id="graph-status")

    def on_mount(self) -> None:
        self.refresh_graph()

    # ------------------------------------------------------------- data

    def refresh_graph(self) -> None:
        try:
            self._graph = build_graph(self._wm.notes_dir())
        except Exception:
            self._graph = GraphData()
        self._layout_size = None
        if self._selected not in self._graph.nodes:
            ordered = self._by_in_degree()
            self._selected = ordered[0] if ordered else None
        self._redraw()

    def _by_in_degree(self) -> list[str]:
        return sorted(self._graph.nodes, key=lambda i: -self._graph.nodes[i].in_degree)

    def _redraw(self) -> None:
        try:
            self.query_one(_GraphCanvas).refresh()
            self.query_one("#graph-status", Static).update(self._status_text())
        except Exception:
            pass  # not mounted yet — compose() picks up current state

    def _status_text(self) -> str:
        if not self._graph.nodes:
            return "  No linked notes yet."
        if self._selected and self._selected in self._graph.nodes:
            node = self._graph.nodes[self._selected]
            return (
                f"  {node.title}  ·  in:{node.in_degree} out:{node.out_degree}"
                f"  ·  {_LEGEND}"
            )
        return f"  {_LEGEND}"

    # ------------------------------------------------------------- render

    def _render_canvas(self, width: int, height: int) -> Text:
        if not self._graph.nodes:
            return Text("  No linked notes yet.", style="dim")

        w, h = max(width, 1), max(height, 1)
        if self._layout_size != (w, h) or not self._positions:
            self._positions = layout_graph(self._graph, w, h)
            self._layout_size = (w, h)

        grid: list[list[str]] = [[" "] * w for _ in range(h)]
        styles: list[list[str | None]] = [[None] * w for _ in range(h)]

        def _set(x: int, y: int, ch: str, style: str | None) -> None:
            if 0 <= x < w and 0 <= y < h:
                grid[y][x] = ch
                styles[y][x] = style

        neighbors: set[str] = set()
        if self._selected:
            for src, tgt in self._graph.edges:
                if src == self._selected:
                    neighbors.add(tgt)
                elif tgt == self._selected:
                    neighbors.add(src)

        in_degrees = sorted(n.in_degree for n in self._graph.nodes.values())
        median_in = in_degrees[len(in_degrees) // 2] if in_degrees else 0

        for src, tgt in self._graph.edges:
            if src not in self._positions or tgt not in self._positions:
                continue
            x0, y0 = self._positions[src]
            x1, y1 = self._positions[tgt]
            xi0, yi0, xi1, yi1 = round(x0), round(y0), round(x1), round(y1)
            active = self._selected in (src, tgt)
            ch = _edge_char(xi1 - xi0, yi1 - yi0)
            style = "bold" if active else "dim"
            points = _line_points(xi0, yi0, xi1, yi1)
            for x, y in points[1:-1]:
                _set(x, y, ch, style)

        for node_id, node in self._graph.nodes.items():
            if node_id not in self._positions:
                continue
            x, y = self._positions[node_id]
            badge = _BADGE.get(node.ntype, "N")
            color = _COLOR.get(node.ntype, "white")
            is_hub = node.in_degree > median_in and median_in > 0
            if node_id == self._selected:
                style = f"reverse bold {color}"
            elif node_id in neighbors:
                style = f"bold {color}"
            elif is_hub:
                style = f"bold {color}"
            else:
                style = f"dim {color}"
            _set(round(x), round(y), badge, style)

        text = Text()
        for row_idx, row in enumerate(grid):
            for col_idx, ch in enumerate(row):
                text.append(ch, style=styles[row_idx][col_idx])
            if row_idx != h - 1:
                text.append("\n")
        return text

    # ------------------------------------------------------------- input

    def on_key(self, event) -> None:
        if not self._graph.nodes:
            return
        if event.key == "tab":
            self._cycle(1)
            event.stop()
        elif event.key == "shift+tab":
            self._cycle(-1)
            event.stop()
        elif event.key in ("left", "right", "up", "down"):
            self._move_spatial(event.key)
            event.stop()
        elif event.key == "enter":
            if self._selected:
                self.post_message(self.Activated(self._selected))
            event.stop()

    def _cycle(self, direction: int) -> None:
        ordered = self._by_in_degree()
        if not ordered:
            return
        if self._selected not in ordered:
            self._selected = ordered[0]
        else:
            idx = ordered.index(self._selected)
            self._selected = ordered[(idx + direction) % len(ordered)]
        self._redraw()

    def _move_spatial(self, key: str) -> None:
        if self._selected is None or self._selected not in self._positions:
            return
        cx, cy = self._positions[self._selected]
        best_id, best_score = None, None
        for node_id, (x, y) in self._positions.items():
            if node_id == self._selected:
                continue
            dx, dy = x - cx, y - cy
            if key == "left" and dx >= -0.01:
                continue
            if key == "right" and dx <= 0.01:
                continue
            if key == "up" and dy >= -0.01:
                continue
            if key == "down" and dy <= 0.01:
                continue
            dist = (dx * dx + dy * dy) ** 0.5 or 1e-4
            align = (abs(dy) if key in ("left", "right") else abs(dx)) / dist
            score = dist + align * 3
            if best_score is None or score < best_score:
                best_score, best_id = score, node_id
        if best_id is not None:
            self._selected = best_id
            self._redraw()
