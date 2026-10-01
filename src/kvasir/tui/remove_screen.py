"""Modal for removing a Worktree (key `x`). Dismisses with True if anything changed."""
from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Static

from kvasir import remove_worktree as rw
from kvasir.worktrees import Worktree


def before_remove(wt: Worktree) -> None:
    """HOOK for #9: note prompt before removal. Intentionally empty."""


class RemoveScreen(ModalScreen[bool]):
    DEFAULT_CSS = """
    RemoveScreen { align: center middle; }
    RemoveScreen > Vertical { width: 70%; min-width: 30; height: auto; border: thick $primary; padding: 1 2; background: $surface; }
    """
    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "cancel", "Cancel"),
        Binding("enter", "confirm", "Confirm"),
        Binding("y", "yes", "Yes", show=False),
        Binding("n", "cancel", "No", show=False),
    ]

    def __init__(self, root: Path, wt: Worktree) -> None:
        super().__init__()
        self.root, self.wt = root, wt
        self.label = wt.branch or wt.path.name
        self.changed = False
        self.risks = rw.Risks()
        self.phase = "remove"  # remove | branch | prune | blocked

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(id="msg")
            yield Input(placeholder="type the branch name to confirm", id="confirm")

    def on_mount(self) -> None:
        msg, inp = self.query_one("#msg", Static), self.query_one(Input)
        inp.display, inp.disabled = False, True
        if self.wt.broken == "directory missing":
            self.phase = "prune"
            msg.update(f"{self.wt.path}\ndirectory is already gone.\n\nRun `git worktree prune`? [y/n]")
            return
        try:
            self.risks = rw.assess(self.wt, self.root)
        except RuntimeError as e:
            self.phase = "blocked"
            msg.update(f"cannot assess {self.label}: {e}\n\n[esc]")
            return
        if self.risks.blocked:
            self.phase = "blocked"
            msg.update(f"{self.label}: {self.risks.blocked}.\n\n[esc]")
        elif self.risks.dangerous:
            lines = "\n".join(f"  - {d}" for d in self.risks.describe())
            msg.update(f"Remove {self.label}? AT RISK:\n{lines}\n\nType '{self.label}' + enter to remove anyway, esc to cancel.")
            inp.display, inp.disabled = True, False
            inp.focus()
        else:
            msg.update(f"Remove worktree {self.label}?\n{self.wt.path}\n\n[enter] remove  [esc] cancel")

    def _say(self, text: str) -> None:
        self.query_one("#msg", Static).update(text)

    def action_cancel(self) -> None:
        self.dismiss(self.changed)

    def action_confirm(self) -> None:
        if self.phase == "remove" and not self.risks.dangerous:
            self._remove(force=False)

    def on_input_submitted(self, ev: Input.Submitted) -> None:
        if self.phase == "remove" and ev.value == self.label:
            self.query_one(Input).display, self.query_one(Input).disabled = False, True
            self._remove(force=True)

    def action_yes(self) -> None:
        try:
            if self.phase == "prune":
                rw.prune(self.root)
                self.dismiss(True)
            elif self.phase == "branch":
                rw.delete_branch(self.root, self.wt.branch or "")
                self.dismiss(True)
        except RuntimeError as e:
            self._say(f"failed: {e}\n\n[esc]")
            self.phase = "blocked"

    def _remove(self, force: bool) -> None:
        before_remove(self.wt)
        try:
            rw.remove(self.root, self.wt.path, force)
        except RuntimeError as e:
            self._say(f"failed: {e}\n\n[esc]")
            self.phase = "blocked"
            return
        self.changed = True
        base = rw.default_branch(self.root)
        if self.wt.branch and base and rw.is_merged(self.root, self.wt.branch, base):
            self.phase = "branch"
            self._say(f"Removed. Branch {self.wt.branch} is merged. Delete branch too? [y/n]")
        else:
            self.dismiss(True)
