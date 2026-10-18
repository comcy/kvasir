"""Modal form: add a Worktree for an existing or a new Branch. Dismisses with the new path or None."""
from __future__ import annotations

import datetime
from pathlib import Path
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Label, Select

from kvasir.branch_names import TYPES, build, matches, slugify, suggest
from kvasir.new_worktree import (
    NewWorktreeError,
    _git,
    add_worktree,
    add_worktree_moving_changes,
    default_branch,
)
from kvasir.worktrees import Branch, Worktree

NEW = "\0new"  # Select value for "new branch"


class NewWorktreeScreen(ModalScreen["Path | None"]):
    DEFAULT_CSS = """
    NewWorktreeScreen { align: center middle; }
    #dialog { width: 72; max-width: 95%; height: auto; max-height: 95%; padding: 0 2;
              border: round $accent; border-title-color: $accent; border-title-style: bold; background: $surface; overflow-y: auto; }
    #dialog .row { layout: horizontal; height: 1; }
    #dialog #new { height: auto; }
    #dialog .k { width: 9; color: $text-muted; }
    #dialog .k2 { width: auto; margin: 0 1; color: $text-muted; }
    #dialog Input, #dialog Select, #dialog SelectCurrent { border: none; height: 1; padding: 0 1; }
    #dialog Input, #dialog SelectCurrent { background: $boost; }
    #dialog Select { width: 1fr; }
    #dialog #type { width: 14; }
    #dialog #id { width: 20; }
    #dialog #fullname { width: 1fr; }
    #dialog #title { width: 1fr; }
    #dialog Button { height: 1; border: none; min-width: 20; margin-top: 1; }
    #dialog Checkbox { border: none; height: 1; padding: 0; }
    #warn { color: $warning; }
    #error { color: $error; }
    """
    BINDINGS: ClassVar[list[Binding]] = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, root: Path, patterns: list[str], branches: list[Branch],
                 source: Worktree | None = None) -> None:
        super().__init__()
        self.root, self.patterns, self.branches = root, patterns, branches
        try:
            self.base = default_branch(root)
        except NewWorktreeError:
            self.base = ""
        n = source.staged + source.unstaged + source.untracked if source else 0
        self.source = source if n else None
        self.n_changes = n
        self._forced: str | None = None  # name the user already saw a warning for
        self._auto = ""  # last generated name
        self._edited = False  # the user typed their own name: stop overwriting it

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            with Container(classes="row"):
                yield Label("Branch", classes="k")
                yield Select([("(new branch)", NEW), *((b.name, b.name) for b in self.branches)],
                             value=NEW, allow_blank=False, id="branch")
            with Vertical(id="new"):
                if self.patterns:
                    with Container(classes="row"):
                        yield Label("Template", classes="k")
                        yield Select([(p, p) for p in self.patterns], allow_blank=False, id="template")
                        yield Label("Type", classes="k2")
                        yield Select([(t, t) for t in TYPES], value=TYPES[0], allow_blank=False, id="type")
                    with Container(classes="row"):
                        yield Label("ID", classes="k")
                        yield Input(placeholder="1234 / ABC-123", id="id")
                        yield Label("Title", classes="k2")
                        yield Input(placeholder="Title", id="title")
                with Container(classes="row"):
                    yield Label("Name", classes="k")
                    yield Input(placeholder="branch name (also the worktree folder)", id="fullname")
                with Container(classes="row"):
                    yield Label("From", classes="k")
                    yield Input(self.base, placeholder="base branch", id="base")
                yield Label("", id="name")
            if self.source:
                yield Checkbox(f"Move {self.n_changes} uncommitted changes from {self.source.path.name}",
                               True, id="move")
            yield Label("", id="warn")
            yield Label("", id="error")
            yield Button("Create (Enter)", id="ok", variant="primary")

    def _msg(self, id_: str, text: str) -> None:
        lab = self.query_one(id_, Label)
        lab.update(text)
        lab.display = bool(text)  # no empty line when there is nothing to say

    def _is_new(self) -> bool:
        return self.query_one("#branch", Select).value == NEW

    def _auto_name(self) -> str:
        if not self.patterns:
            return ""
        return build(
            str(self.query_one("#template", Select).value),
            type=str(self.query_one("#type", Select).value),
            id=self.query_one("#id", Input).value.strip(),
            slug=slugify(self.query_one("#title", Input).value),
            date=datetime.datetime.now().astimezone().date().isoformat(),
        )

    def _new_name(self) -> str:
        """Typed name wins; empty or untouched = the generated one."""
        return self.query_one("#fullname", Input).value.strip() or self._auto_name()

    def _base_hint(self) -> str:
        base = self.query_one("#base", Input).value.strip() or self.base
        r = _git(self.root, "rev-parse", "--short", "--verify", "--quiet", f"{base}^{{commit}}")
        return f"from {base} ({r.stdout.strip()})" if r.returncode == 0 and base else f"from {base or '?'} (unknown ref)"

    def _update(self, *, keep_name: bool = False) -> None:
        self.query_one("#new").display = self._is_new()
        if self._is_new():
            full = self.query_one("#fullname", Input)
            if not keep_name and not self._edited:
                self._auto = self._auto_name()
                full.value = self._auto  # fires Input.Changed: equals _auto, so not "edited"
            self.query_one("#name", Label).update(f"Branch {self._base_hint()}" if self._new_name() else "Enter a branch name")
        self._forced = None
        self._msg("#warn", "")
        self._msg("#error", "")

    def on_mount(self) -> None:
        self.query_one("#dialog").border_title = "New worktree"
        self._update()

    def on_select_changed(self, _ev: Select.Changed) -> None:
        self._update()

    def on_input_changed(self, ev: Input.Changed) -> None:
        if ev.input.id == "fullname":
            self._edited = ev.value.strip() not in ("", self._auto)
            return self._update(keep_name=True)
        self._update()

    def on_input_submitted(self, _ev: Input.Submitted) -> None:
        self._submit()

    def on_button_pressed(self, _ev: Button.Pressed) -> None:
        self._submit()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def _submit(self) -> None:
        if not self._is_new():
            branch, base = str(self.query_one("#branch", Select).value), None
        else:
            branch, base = self._new_name(), self.query_one("#base", Input).value.strip() or self.base
            if not matches(branch, self.patterns) and self._forced != branch:
                self._forced = branch  # second Enter on the same name forces it
                hint = suggest(branch, self.patterns)
                self._msg("#warn", f"Name violates templates {self.patterns}."
                          + (f" Suggestion: {hint}." if hint else "") + " Enter again to create anyway.")
                return
        try:
            if self.source and self.query_one("#move", Checkbox).value:
                self.dismiss(add_worktree_moving_changes(self.root, branch, base, self.source.path))
            else:
                self.dismiss(add_worktree(self.root, branch, base))
        except NewWorktreeError as e:
            self._msg("#error", str(e))
