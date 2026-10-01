"""Modal form: add a Worktree for an existing or a new Branch. Dismisses with the new path or None."""
from __future__ import annotations

import datetime
from pathlib import Path
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select

from kvasir.branch_names import TYPES, build, matches, slugify, suggest
from kvasir.new_worktree import NewWorktreeError, add_worktree, default_branch
from kvasir.worktrees import Branch

NEW = "\0new"  # Select value for "new branch"


class NewWorktreeScreen(ModalScreen["Path | None"]):
    DEFAULT_CSS = """
    NewWorktreeScreen { align: center middle; }
    #dialog { width: 70; max-width: 95%; height: auto; max-height: 95%; padding: 1 2;
              border: thick $primary; background: $surface; overflow-y: auto; }
    #warn { color: $warning; }
    #error { color: $error; }
    """
    BINDINGS: ClassVar[list[Binding]] = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, root: Path, patterns: list[str], branches: list[Branch]) -> None:
        super().__init__()
        self.root, self.patterns, self.branches = root, patterns, branches
        try:
            self.base = default_branch(root)
        except NewWorktreeError:
            self.base = ""
        self._forced: str | None = None  # name the user already saw a warning for

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label("New worktree")
            yield Select([("(new branch)", NEW), *((b.name, b.name) for b in self.branches)],
                         value=NEW, allow_blank=False, id="branch")
            with Vertical(id="new"):
                yield Select([(p, p) for p in self.patterns], allow_blank=False, id="template")
                yield Select([(t, t) for t in TYPES], value=TYPES[0], allow_blank=False, id="type")
                yield Input(placeholder="ID (1234 / ABC-123)", id="id")
                yield Input(placeholder="Title", id="title")
                yield Input(self.base, placeholder="Base branch", id="base")
                yield Label("", id="name")
            yield Label("", id="warn")
            yield Label("", id="error")
            yield Button("Create (Enter)", id="ok", variant="primary")

    def _is_new(self) -> bool:
        return self.query_one("#branch", Select).value == NEW

    def _new_name(self) -> str:
        return build(
            str(self.query_one("#template", Select).value),
            type=str(self.query_one("#type", Select).value),
            id=self.query_one("#id", Input).value.strip(),
            slug=slugify(self.query_one("#title", Input).value),
            date=datetime.datetime.now().astimezone().date().isoformat(),
        )

    def _update(self) -> None:
        self.query_one("#new").display = self._is_new()
        if self._is_new() and self.patterns:
            self.query_one("#name", Label).update(f"Name: {self._new_name()}")
        self._forced = None
        self.query_one("#warn", Label).update("")
        self.query_one("#error", Label).update("")

    def on_mount(self) -> None:
        self._update()

    def on_select_changed(self, _ev: Select.Changed) -> None:
        self._update()

    def on_input_changed(self, _ev: Input.Changed) -> None:
        self._update()

    def on_input_submitted(self, _ev: Input.Submitted) -> None:
        self._submit()

    def on_button_pressed(self, _ev: Button.Pressed) -> None:
        self._submit()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def _submit(self) -> None:
        warn, err = self.query_one("#warn", Label), self.query_one("#error", Label)
        if not self._is_new():
            branch, base = str(self.query_one("#branch", Select).value), None
        else:
            branch, base = self._new_name(), self.query_one("#base", Input).value.strip() or self.base
            if not matches(branch, self.patterns) and self._forced != branch:
                self._forced = branch  # second Enter on the same name forces it
                hint = suggest(branch, self.patterns)
                warn.update(f"Name violates templates {self.patterns}."
                            + (f" Suggestion: {hint}." if hint else "") + " Enter again to create anyway.")
                return
        try:
            self.dismiss(add_worktree(self.root, branch, base))
        except NewWorktreeError as e:
            err.update(str(e))
