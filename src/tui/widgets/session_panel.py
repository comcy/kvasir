"""Worktree-aware session panel: projects → worktrees → WIP, plus recent sessions."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static
from textual.containers import Vertical

from src.workspace.manager import WorkspaceError, WorkspaceManager


def _duration(start: str, end: str | None) -> str:
    try:
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

    def __init__(self, wm: WorkspaceManager, **kwargs) -> None:
        super().__init__(**kwargs)
        self._wm = wm

    def _load(self) -> tuple[list[dict], list[dict]]:
        try:
            store = self._wm.store()
            return store.all("sessions"), store.all("projects")
        except (WorkspaceError, Exception):
            return [], []

    def compose(self) -> ComposeResult:
        sessions, projects = self._load()

        if not sessions and not projects:
            yield Static(
                "  [dim]No projects or sessions yet.[/dim]\n"
                "  mimirlink project add <name>\n"
                "  mimirlink hooks install-hooks",
                classes="empty-hint",
            )
            return

        active_by_path = {
            s.get("worktree_path"): s for s in sessions if not s.get("end")
        }

        with Vertical():
            # ── Projects / Worktrees ──────────────────────────────────────
            if projects:
                from src.data.projects import list_worktrees, uncommitted_count

                yield Static("  [bold]⌂ Projects[/bold]", classes="panel-section-header")
                for p in sorted(projects, key=lambda x: x.get("name", "")):
                    yield Static(f"  [bold]{p.get('name', '?')}[/bold]", classes="session-active")
                    try:
                        worktrees = list_worktrees(p.get("path", ""))
                    except Exception:
                        worktrees = []
                    if not worktrees:
                        yield Static("    [dim]no worktrees[/dim]", classes="session-past")
                        continue
                    for w in worktrees:
                        branch = w["branch"] or "(detached)"
                        try:
                            n = uncommitted_count(w["path"])
                        except Exception:
                            n = 0
                        wip = f"  [yellow]±{n}[/yellow]" if n else ""
                        active = active_by_path.get(w["path"])
                        if active:
                            dur = _duration(active.get("start", ""), None)
                            mark = f"[green]►[/green] [bold]{branch}[/bold]  [green]{dur}[/green]"
                        else:
                            mark = f"[dim]○[/dim] {branch}"
                        yield Static(
                            f"    {mark}{wip}\n      [dim]{Path(w['path']).name}/[/dim]",
                            classes="session-past",
                        )

            # ── Recent sessions ───────────────────────────────────────────
            recent = sorted(sessions, key=lambda s: s.get("start", ""), reverse=True)
            past = [s for s in recent if s.get("end")]
            if past:
                yield Static(
                    f"\n  [bold]Recent[/bold] [dim]({len(past)})[/dim]",
                    classes="panel-section-header",
                )
                for s in past[:5]:
                    branch = s.get("branch", "?")
                    wt = Path(s.get("worktree_path", "")).name or "?"
                    dur = _duration(s.get("start", ""), s.get("end"))
                    ago = _ago(s.get("end", ""))
                    yield Static(
                        f"  [dim]○[/dim] {branch}\n"
                        f"    [dim]{wt}/  ·  {dur}  ·  {ago}[/dim]",
                        classes="session-past",
                    )
