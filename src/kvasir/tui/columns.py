"""One small widget per column. Detail panel is swappable: anything with `show(item)`."""
from __future__ import annotations

from rich.text import Text
from textual.widgets import OptionList, Static

from kvasir.tui.data import RepoRow, format_age
from kvasir.worktrees import Branch, Worktree


def _line(s: str, style: str = "") -> Text:
    return Text(s, style=style, no_wrap=True, overflow="ellipsis")


def counts(w: Worktree) -> str:
    return f"+{w.staged} ~{w.unstaged} ?{w.untracked}"


class RepoList(OptionList):
    def set_rows(self, rows: list[RepoRow], sync: dict[str, tuple[float | None, str | None]] | None = None) -> None:
        """`sync`: url -> (last fetch unix ts, fetch error)."""
        self.clear_options()
        for r in rows:
            if r.view:
                ts, err = (sync or {}).get(r.url, (None, None))
                info = f"{len(r.view.worktrees)} wt, {r.dirty} dirty, fetched {format_age(ts)}"
                if err:
                    self.add_option(_line(f"{r.url}  {info}  [fetch failed: {err}]", "yellow"))
                else:
                    self.add_option(_line(f"{r.url}  {info}"))
            else:
                self.add_option(_line(f"{r.url}  [{r.error}]", "red"))


class EntryList(OptionList):
    """Middle column: Worktrees, then Branches without Worktree."""

    def set_entries(self, entries: list[Worktree | Branch], notes: dict[str, dict] | None = None) -> None:
        """`notes`: branch -> newest note, shown shortened at the end of the line."""
        self.clear_options()
        for e in entries:
            n = (notes or {}).get(getattr(e, "branch", None) or getattr(e, "name", ""))
            tail = f"  ✎ {n['text'][:30]}" if n else ""
            if isinstance(e, Worktree):
                if e.broken:
                    self.add_option(_line(f"! {e.branch or e.path.name}  [defekt: {e.broken}]", "red"))
                else:
                    self.add_option(_line(
                        f"{e.branch or '(detached)'}  {format_age(e.commit_ts)}  {counts(e)}  {e.subject}{tail}"
                    ))
            else:
                self.add_option(_line(f"{e.name}  {format_age(e.commit_ts)}  {e.subject}{tail}", "dim"))


class DetailPanel(Static):
    def show(self, item: Worktree | Branch | None, note: dict | None = None) -> None:
        self._show(item)
        if note:
            kind = "closing note" if note["kind"] == "closing" else "note"
            self.update(Text.assemble(self.content, f"\n\n{kind} ({note['ts'][:10]}):\n{note['text']}"))

    def _show(self, item: Worktree | Branch | None) -> None:
        if item is None:
            self.update("")
        elif isinstance(item, Branch):
            kind = "remote branch" if item.remote else "branch"
            self.update(
                f"{item.name}\n{kind} (no worktree)\n\nlast commit: {format_age(item.commit_ts)}\n{item.subject}"
            )
        elif item.broken:
            self.update(Text(f"{item.path}\n\nbroken: {item.broken}", style="red"))
        else:
            ahead = "no upstream" if item.ahead is None else f"ahead {item.ahead} / behind {item.behind}"
            self.update(
                f"{item.branch or '(detached)'}\n{item.path}\n\n"
                f"last commit: {format_age(item.commit_ts)}\n{item.subject}\n\n"
                f"staged {item.staged}  unstaged {item.unstaged}  untracked {item.untracked}\n"
                f"last active: {format_age(item.last_active_ts)}\n{ahead}"
            )
