from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import DataTable, Static
from textual.containers import Vertical


def _sparkline(values: list[float], width: int = 8) -> str:
    """Render a tiny sparkline using block characters."""
    bars = " ▁▂▃▄▅▆▇█"
    if not values:
        return " " * width
    recent = values[-width:]
    mn, mx = min(recent), max(recent)
    span = mx - mn or 1
    return "".join(bars[min(8, int((v - mn) / span * 8))] for v in recent)


def _week_label(ts: str) -> str:
    try:
        d = date.fromisoformat(ts[:10])
        week_start = d - timedelta(days=d.weekday())
        return week_start.isoformat()
    except Exception:
        return ts[:10]


class MetricPanel(Widget):
    BORDER_TITLE = "Metrics"

    def __init__(self, metrics: list[dict], values: list[dict], **kwargs) -> None:
        super().__init__(**kwargs)
        self._metrics = metrics
        self._values = values

    def compose(self) -> ComposeResult:
        if not self._metrics:
            yield Static(
                "  [dim]No metrics defined yet.[/dim]\n  devtrack metric define ...",
                classes="empty-hint",
            )
            return

        values_by_metric: dict[str, list[float]] = defaultdict(list)
        for v in sorted(self._values, key=lambda x: x.get("timestamp", "")):
            values_by_metric[v["metric_id"]].append(float(v.get("value", 0)))

        table = DataTable(zebra_stripes=True, cursor_type="row", id="metric-table")
        table.add_columns("Metric", "Label", "Last", "Σ", "Trend")

        for m in self._metrics:
            vals = values_by_metric.get(m["id"], [])
            last = f"{vals[-1]:.1f}" if vals else "—"
            total = f"{sum(vals):.1f}" if vals else "—"
            spark = _sparkline(vals) if vals else "        "
            table.add_row(m["name"], m["label"], last, total, spark)

        yield table
