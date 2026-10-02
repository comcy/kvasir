"""Pure formatting/grouping helpers for the TUI columns. No Textual."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from kvasir.tui.data import format_age
from kvasir.worktrees import Branch, RepoView, Worktree

AGE_W, COUNTS_W, GAP = 4, 10, 2


@dataclass
class Group:
    key: str                      # "worktrees" | "local" | "remote"
    title: str
    entries: list[Worktree | Branch] = field(default_factory=list)
    collapsed: bool = False       # entries exist but are hidden

    @property
    def visible(self) -> list[Worktree | Branch]:
        return [] if self.collapsed else self.entries

    @property
    def header(self) -> str:
        mark = "" if self.key != "remote" else ("▸ " if self.collapsed else "▾ ")
        hint = "  (b: show)" if self.collapsed else ""
        return f"{mark}{self.title} ({len(self.entries)}){hint}"


def group_entries(view: RepoView, show_remote: bool) -> list[Group]:
    """Worktrees, local Branches without Worktree, Remote-Branches; empty groups are dropped."""
    local = [b for b in view.branches if not b.remote]
    remote = [b for b in view.branches if b.remote]
    groups = [
        Group("worktrees", "Worktrees", list(view.worktrees)),
        Group("local", "Branches ohne Worktree", local),
        Group("remote", "Remote-Branches", remote, collapsed=not show_remote),
    ]
    return [g for g in groups if g.entries]


def short_name(url: str) -> str:
    """`github.com/owner/name` -> `owner/name`."""
    return "/".join(url.rstrip("/").split("/")[-2:])


def tilde(path: Path | str, home: Path | None = None) -> str:
    """Shorten a path under the home directory to `~/...`."""
    p, h = Path(path), home or Path.home()
    try:
        rel = p.relative_to(h)
    except ValueError:
        return str(p)
    return "~" if not rel.parts else f"~/{rel.as_posix()}"


def fit(s: str, width: int) -> str:
    """Pad to `width`, or cut with an ellipsis."""
    if width <= 0:
        return ""
    return s if len(s) == width else s.ljust(width) if len(s) < width else s[: width - 1] + "…"


def cut(s: str, width: int) -> str:
    """Shorten to at most `width` characters with an ellipsis (no padding)."""
    return s if len(s) <= width else fit(s, width)


def name_width(names: list[str], total: int) -> int:
    """Branch column: as wide as the longest name, capped at 40% of the line (cap at least 8)."""
    cap = max(8, total * 2 // 5)
    return min(max((len(n) for n in names), default=8), cap)


def entry_name(e: Worktree | Branch) -> str:
    if isinstance(e, Worktree):
        return ("! " + (e.branch or e.path.name)) if e.broken else (e.branch or "(detached)")
    return e.name


def format_entry(e: Worktree | Branch, name_w: int, note: str = "") -> str:
    """Fixed columns: name | age | counts | subject (the subject takes the rest)."""
    gap = " " * GAP
    name = fit(entry_name(e), name_w)
    if isinstance(e, Worktree) and e.broken:
        return f"{name}{gap}[defekt: {e.broken}]"
    age = format_age(e.commit_ts).rjust(AGE_W)
    counts = fit(f"+{e.staged} ~{e.unstaged} ?{e.untracked}" if isinstance(e, Worktree) else "", COUNTS_W)
    subject = e.subject + (f"  ✎ {note[:30]}" if note else "")
    return f"{name}{gap}{age}{gap}{counts}{gap}{subject}"
