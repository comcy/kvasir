from __future__ import annotations

from datetime import datetime, timezone

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static
from textual.containers import Vertical


def _duration(start: str, end: str | None) -> str:
    try:
        fmt = "%Y-%m-%dT%H:%M:%S"
        s = datetime.fromisoformat(start)
        e = datetime.fromisoformat(end) if end else datetime.now()
        delta = e - s
        h, rem = divmod(int(delta.total_seconds()), 3600)
        m = rem // 60
        return f"{h}h {m:02d}m" if h else f"{m}m"
    except Exception:
        return "?"


def _ago(ts: str) -> str:
    try:
        d = datetime.fromisoformat(ts)
        delta = datetime.now() - d
        s = int(delta.total_seconds())
        if s < 60:
            return "just now"
        if s < 3600:
            return f"{s // 60}m ago"
        if s < 86400:
            return f"{s // 3600}h ago"
        return f"{s // 86400}d ago"
    except Exception:
        return "?"


class SessionPanel(Widget):
    BORDER_TITLE = "Sessions / WIP"

    def __init__(self, sessions: list[dict], **kwargs) -> None:
        super().__init__(**kwargs)
        self._sessions = sessions

    def compose(self) -> ComposeResult:
        if not self._sessions:
            yield Static(
                "  [dim]No sessions yet.[/dim]\n  devtrack session start",
                classes="empty-hint",
            )
            return

        recent = sorted(self._sessions, key=lambda s: s.get("start", ""), reverse=True)[:10]
        active = [s for s in recent if not s.get("end")]

        with Vertical():
            if active:
                yield Static("  [bold green]● Active[/bold green]", classes="panel-section-header")
                for s in active:
                    repo = s.get("repo", "?")
                    branch = s.get("branch", "?")
                    dur = _duration(s.get("start", ""), None)
                    yield Static(
                        f"  [green]►[/green] [bold]{branch}[/bold]\n"
                        f"    [dim]{repo}  ·  {dur}[/dim]",
                        classes="session-active",
                    )

            past = [s for s in recent if s.get("end")]
            if past:
                yield Static(
                    f"\n  [bold]Recent[/bold] [dim]({len(past)})[/dim]",
                    classes="panel-section-header",
                )
                for s in past[:5]:
                    branch = s.get("branch", "?")
                    repo = s.get("repo", "?")
                    dur = _duration(s.get("start", ""), s.get("end"))
                    ago = _ago(s.get("end", ""))
                    yield Static(
                        f"  [dim]○[/dim] {branch}\n"
                        f"    [dim]{repo}  ·  {dur}  ·  {ago}[/dim]",
                        classes="session-past",
                    )
