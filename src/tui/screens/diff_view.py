"""Diff viewer: file list + hunk-navigable colorized diff. A Source/Target
branch selector at the top switches between the default view (uncommitted
changes, togglable all/staged) and a PR-style branch comparison, without
leaving the screen. Read-only — no stage/unstage per hunk (`git add -p`
territory)."""
from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Label, ListItem, ListView, Select, Static
from unidiff import PatchedFile, PatchSet

from src.data.diff import branch_diff, list_branches, staged_diff, working_diff

_WORKING_TREE = "__working__"


class _DiffFileRow(ListItem):
    def __init__(self, patched_file: PatchedFile) -> None:
        super().__init__()
        self.patched_file = patched_file

    def compose(self) -> ComposeResult:
        pf = self.patched_file
        status = "A" if pf.is_added_file else "D" if pf.is_removed_file else "M"
        color = {"A": "green", "D": "red", "M": "yellow"}[status]
        yield Static(
            f"  [{color}]{status}[/{color}] {pf.path}\n"
            f"    [green]+{pf.added}[/green] [red]-{pf.removed}[/red]"
        )


def _render_file(pf: PatchedFile, active_hunk: int) -> tuple[Text, list[int]]:
    """Colorized diff for one file + the line offset each hunk starts at.

    The active hunk's header is visually marked (reverse style + a ▶
    marker) — scrolling to a hunk that's already fully visible produces no
    change by itself on a short diff, so the marker is what actually makes
    "jump to next hunk" perceptible.
    """
    text = Text()
    offsets: list[int] = []
    line_no = 0
    for i, hunk in enumerate(pf):
        offsets.append(line_no)
        header = f"@@ -{hunk.source_start},{hunk.source_length} +{hunk.target_start},{hunk.target_length} @@"
        if hunk.section_header:
            header += f" {hunk.section_header}"
        is_active = i == active_hunk
        marker = "▶ " if is_active else "  "
        style = "reverse bold cyan" if is_active else "bold cyan"
        text.append(f"{marker}{header}\n", style=style)
        line_no += 1
        for line in hunk:
            prefix = "+" if line.is_added else "-" if line.is_removed else " "
            style = "green" if line.is_added else "red" if line.is_removed else "dim"
            text.append(f"  {prefix} {line.value}", style=style)
            line_no += 1
    return text, offsets


class DiffScreen(ModalScreen[None]):
    DEFAULT_CSS = """
    DiffScreen { align: center middle; }
    #dialog {
        width: 95%; height: 95%;
        background: $surface; border: round $secondary; padding: 1 2;
    }
    #diff-title { color: $secondary; text-style: bold; margin-bottom: 1; }
    #diff-branch-row { height: auto; margin-bottom: 1; align: left middle; }
    #diff-branch-row Label { margin: 1 1 0 0; color: $foreground 60%; }
    #diff-branch-row Select { width: 28; margin-right: 2; }
    #diff-split { height: 1fr; }
    #diff-files { width: 36; border-right: solid $panel; padding-right: 1; }
    #diff-files ListItem { padding: 0; }
    #diff-content { width: 1fr; padding: 0 1; }
    #diff-hint { color: $foreground 40%; margin-top: 1; }
    #diff-empty { color: $foreground 45%; padding: 2; }
    """

    BINDINGS = [
        ("escape", "close", "Close"),
        ("]", "next_hunk", "Next hunk"),
        ("[", "prev_hunk", "Prev hunk"),
        ("t", "toggle_staged", "Toggle staged/all"),
    ]

    def __init__(
        self,
        worktree_path: str,
        *,
        target_branch: str | None = None,
        source_branch: str | None = None,
    ) -> None:
        """*target_branch*/*source_branch* pre-engage branch-compare mode —
        target is where the changes would land (e.g. master), source is the
        branch carrying the new changes (e.g. a feature branch). Leave both
        unset for the default view (working tree, all/staged togglable)."""
        super().__init__()
        self._path = worktree_path
        self._branches = list_branches(worktree_path)
        self._target_branch = target_branch or (self._branches[0] if self._branches else "")
        self._source_branch = source_branch or _WORKING_TREE
        self._staged_only = False
        self._patchset: PatchSet = PatchSet("")
        self._current_file: PatchedFile | None = None
        self._hunk_offsets: list[int] = []
        self._hunk_idx = -1
        self._ready = False  # guards Select.Changed firing during initial compose

    @property
    def _compare_mode(self) -> bool:
        return self._source_branch != _WORKING_TREE

    def _load(self) -> None:
        if self._compare_mode:
            self._patchset = branch_diff(self._path, self._target_branch, self._source_branch)
        elif self._staged_only:
            self._patchset = staged_diff(self._path)
        else:
            self._patchset = working_diff(self._path)

    def compose(self) -> ComposeResult:
        self._load()
        if self._compare_mode:
            title = f"{self._target_branch}...{self._source_branch}"
        else:
            title = "Staged only" if self._staged_only else "Working changes (staged + unstaged)"

        source_options = [("Working tree (uncommitted)", _WORKING_TREE)] + [
            (b, b) for b in self._branches
        ]
        target_options = [(b, b) for b in self._branches] or [(self._target_branch, self._target_branch)]

        with Vertical(id="dialog"):
            yield Static(f"[bold]Diff[/bold]  ·  {title}", id="diff-title")
            with Horizontal(id="diff-branch-row"):
                yield Label("Source")
                yield Select(
                    source_options, value=self._source_branch, id="sel-source", allow_blank=False,
                )
                yield Label("Target")
                yield Select(
                    target_options, value=self._target_branch, id="sel-target",
                    allow_blank=False, disabled=not self._compare_mode,
                )
            with Horizontal(id="diff-split"):
                with VerticalScroll(id="diff-files"):
                    if self._patchset:
                        yield ListView(*[_DiffFileRow(pf) for pf in self._patchset])
                    else:
                        yield Static("  No changes.", id="diff-empty")
                with VerticalScroll(id="diff-content"):
                    yield Static("", id="diff-body")

            hint = "]/[: hunk"
            if not self._compare_mode:
                hint += "  ·  t: toggle staged/all"
            hint += "  ·  escape: close"
            yield Static(f"[dim]{hint}[/dim]", id="diff-hint")

    def on_mount(self) -> None:
        try:
            lv = self.query_one(ListView)
        except Exception:
            self._ready = True
            return
        lv.focus()
        if lv.children:
            lv.index = 0
        else:
            self._current_file = None
        self.call_after_refresh(self._mark_ready)

    def _mark_ready(self) -> None:
        self._ready = True

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if isinstance(event.item, _DiffFileRow):
            self._show_file(event.item.patched_file)

    def _show_file(self, pf: PatchedFile) -> None:
        self._current_file = pf
        self._hunk_idx = 0 if list(pf) else -1
        self._redraw_body()
        try:
            self.query_one("#diff-content", VerticalScroll).scroll_to(y=0, animate=False)
        except Exception:
            pass

    def _redraw_body(self) -> None:
        if self._current_file is None:
            return
        text, self._hunk_offsets = _render_file(self._current_file, self._hunk_idx)
        try:
            self.query_one("#diff-body", Static).update(text)
        except Exception:
            pass

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)

    def action_next_hunk(self) -> None:
        self._jump_hunk(1)

    def action_prev_hunk(self) -> None:
        self._jump_hunk(-1)

    def _jump_hunk(self, direction: int) -> None:
        if not self._hunk_offsets:
            return
        self._hunk_idx = (self._hunk_idx + direction) % len(self._hunk_offsets)
        self._redraw_body()
        try:
            self.query_one("#diff-content", VerticalScroll).scroll_to(
                y=self._hunk_offsets[self._hunk_idx], animate=True,
            )
        except Exception:
            pass

    def action_toggle_staged(self) -> None:
        if self._compare_mode:
            return
        self._staged_only = not self._staged_only
        self._reload()

    def on_select_changed(self, event: Select.Changed) -> None:
        if not self._ready:
            return  # Select posts Changed on its own initial mount — ignore that one
        if event.select.id == "sel-source" and event.value != self._source_branch:
            self._source_branch = event.value
            self._reload()
        elif event.select.id == "sel-target" and event.value != self._target_branch:
            self._target_branch = event.value
            self._reload()

    def _reload(self) -> None:
        self._ready = False
        self.refresh(recompose=True)
        self.call_after_refresh(self.on_mount)
