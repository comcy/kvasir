"""One small widget per column. Detail panel is swappable: anything with `show(item)`."""
from __future__ import annotations

from rich.text import Text
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

from kvasir.tui.data import RepoRow, format_age
from kvasir.tui.layout import Group, cut, entry_name, format_entry, name_width, short_name, tilde
from kvasir.worktrees import Branch, Worktree


def _line(s: str, style: str = "") -> Text:
    return Text(s, style=style, no_wrap=True, overflow="ellipsis")


def counts(w: Worktree) -> str:
    return f"+{w.staged} ~{w.unstaged} ?{w.untracked}"


class RepoList(OptionList):
    """Left column: per Repo `owner/name`, `~/path`, info line, blank line."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._rows: list[RepoRow] = []
        self._sync: dict[str, tuple[float | None, str | None]] = {}
        self._platform: dict[str, tuple[str, bool]] = {}  # url -> (status line, is error)

    def set_platform(self, lines: dict[str, tuple[str, bool]]) -> None:
        """url -> (platform status line, is error); redraws without moving the highlight."""
        self._platform = lines
        self.on_resize()

    def set_rows(self, rows: list[RepoRow], sync: dict[str, tuple[float | None, str | None]] | None = None) -> None:
        """`sync`: url -> (last fetch unix ts, fetch error)."""
        self._rows, self._sync = rows, sync or {}
        self._render_rows()

    def _render_rows(self) -> None:
        w = max(8, self.scrollable_content_region.width - 2)  # option padding

        def line(s: str, style: str = "") -> Text:
            return _line(cut(s, w), style)

        self.clear_options()
        for r in self._rows:
            name = line(short_name(r.url), "bold")
            path = line(tilde(r.path) if r.path else "(no path)", "dim")
            if r.view:
                ts, err = self._sync.get(r.url, (None, None))
                info = f"{len(r.view.worktrees)} wt, {r.dirty} dirty, fetched {format_age(ts)}"
                lines = [line(info)] + ([line(f"fetch failed: {err}", "yellow")] if err else [])
                if r.url in self._platform:
                    text, bad = self._platform[r.url]
                    lines += [line(t, "yellow" if bad and i else "dim") for i, t in enumerate(text.split("\n"))]
            else:
                lines = [line(f"[{r.error}]", "red")]
            self.add_option(Text("\n").join([name, path, *lines, Text("")]))

    def on_resize(self) -> None:
        if self._rows:
            h = self.highlighted
            self._render_rows()
            if h is not None:
                with self.prevent(OptionList.OptionHighlighted):
                    self.highlighted = h


class EntryList(OptionList):
    """Middle column: grouped Entries. Headings are disabled options; `index_map` maps option -> entry index."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.index_map: list[int | None] = []  # option index -> index into the flat entry list (None = heading)
        self._groups: list[Group] = []
        self._notes: dict[str, dict] = {}
        self._marks: dict[str, str] = {}

    def set_entries(self, groups: list[Group], notes: dict[str, dict] | None = None, keep: int = 0,
                    marks: dict[str, str] | None = None) -> None:
        """`notes`: branch -> newest note. `keep`: entry index to highlight. `marks`: entry name -> PR marker."""
        self._groups, self._notes, self._marks = groups, notes or {}, marks or {}
        self._render_groups(keep)

    def entry_to_option(self, i: int) -> int | None:
        return self.index_map.index(i) if i in self.index_map else None

    def current_entry(self) -> int | None:
        h = self.highlighted
        return self.index_map[h] if h is not None and h < len(self.index_map) else None

    def _render_groups(self, keep: int | None) -> None:
        self.clear_options()
        self.index_map = []
        names = [entry_name(e) for g in self._groups for e in g.visible]
        total = max(8, self.scrollable_content_region.width - 2)  # option padding
        nw = name_width(names, total)
        mw = max((len(self._marks.get(n, "")) for n in names), default=0)  # column only if any marker
        n = 0
        for gi, g in enumerate(self._groups):
            head = ("\n" if gi else "") + cut(g.header, total)
            self.add_option(Option(Text(head, style="bold"), disabled=True))
            self.index_map.append(None)
            for e in g.visible:
                note = self._notes.get(getattr(e, "branch", None) or getattr(e, "name", ""))
                style = "red" if isinstance(e, Worktree) and e.broken else "dim" if isinstance(e, Branch) else ""
                line = format_entry(e, nw, note["text"] if note else "", self._marks.get(entry_name(e), ""), mw)
                self.add_option(_line(cut(line, total), style))
                self.index_map.append(n)
                n += 1
        opt = self.entry_to_option(keep) if keep is not None else None
        if opt is not None:
            with self.prevent(OptionList.OptionHighlighted):
                self.highlighted = opt

    def on_resize(self) -> None:
        if self._groups:
            self._render_groups(self.current_entry())


class DetailPanel(Static):
    def show(self, item: Worktree | Branch | None, note: dict | None = None, extra: str = "") -> None:
        """`extra`: platform block (PR / Work Item / Pipelines) appended below the details."""
        self._show(item)
        if note:
            kind = "closing note" if note["kind"] == "closing" else "note"
            self.update(Text.assemble(self.content, f"\n\n{kind} ({note['ts'][:10]}):\n{note['text']}"))
        if extra:
            self.update(Text.assemble(self.content, "\n\n", extra))

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
