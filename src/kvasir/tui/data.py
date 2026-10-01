"""Load Repos for the TUI. Pure/blocking, no Textual: run it in a worker."""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from kvasir.config import load_local, load_repos
from kvasir.worktrees import RepoView, read_repo


@dataclass
class RepoRow:
    url: str
    path: Path | None            # None = no local path registered
    view: RepoView | None = None
    error: str | None = None     # "nicht gefunden" or the read error

    @property
    def dirty(self) -> int:
        """Worktrees with staged/unstaged/untracked changes."""
        if not self.view:
            return 0
        return sum(1 for w in self.view.worktrees if w.staged or w.unstaged or w.untracked)


def format_age(ts: int | None, now: float | None = None) -> str:
    """Relative time: "now", "5m", "3h", "2d", "7w", "4mo", "2y"; "-" if unknown."""
    if ts is None:
        return "-"
    s = max(0, int((time.time() if now is None else now) - ts))
    for unit, size in (("y", 31536000), ("mo", 2592000), ("w", 604800), ("d", 86400), ("h", 3600), ("m", 60)):
        if s >= size:
            return f"{s // size}{unit}"
    return "now"


def load_rows() -> list[RepoRow]:
    paths = load_local().paths
    rows = []
    for url in sorted(load_repos()):
        p = paths.get(url)
        row = RepoRow(url, Path(p) if p else None)
        if row.path is None or not row.path.is_dir():
            row.error = "nicht gefunden"
        else:
            try:
                row.view = read_repo(row.path)
            except ValueError as e:
                row.error = str(e)
        rows.append(row)
    return rows
