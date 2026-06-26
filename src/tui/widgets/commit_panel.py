from __future__ import annotations

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static
from textual.containers import Vertical

TYPE_COLOR = {
    "feat": "green",
    "fix": "red",
    "refactor": "blue",
    "chore": "dim",
    "perf": "yellow",
    "test": "cyan",
    "docs": "magenta",
    "breaking": "bold red",
}


class CommitPanel(Widget):
    BORDER_TITLE = "Recent Commits"

    def __init__(self, commits: list[dict], **kwargs) -> None:
        super().__init__(**kwargs)
        self._commits = commits

    def compose(self) -> ComposeResult:
        if not self._commits:
            yield Static(
                "  [dim]No commits tracked yet.[/dim]\n  Use: mimirlink commit",
                classes="empty-hint",
            )
            return

        recent = sorted(self._commits, key=lambda c: c.get("date", ""), reverse=True)[:20]

        with Vertical():
            for c in recent:
                ctype = c.get("type", "?")
                scope = c.get("scope") or ""
                subject = c.get("subject", "")
                date_str = c.get("date", "")[:10]
                breaking = c.get("breaking", False)
                hash_str = c.get("hash", "")[:7]

                color = TYPE_COLOR.get(ctype, "white")
                scope_str = f"({scope})" if scope else ""
                bang = "[bold red]![/bold red]" if breaking else ""

                yield Static(
                    f"  [{color}]{ctype}{scope_str}{bang}[/{color}]"
                    f"  [dim]{hash_str}[/dim]  {subject}"
                    f"  [dim]{date_str}[/dim]",
                    classes="commit-row",
                )
