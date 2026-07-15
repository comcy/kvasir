"""Morning routine wizard — todo triage, journal gap-fill, plan today."""
from __future__ import annotations

import subprocess
from datetime import date, datetime

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static, TextArea

from src.data.journal import append_plan, ensure_note, slug_for
from src.data.morning import (
    due_or_overdue_todos,
    mark_journal_day_skipped,
    missing_journal_days,
    undated_todos,
)
from src.platform_utils import default_editor
from src.workspace.manager import WorkspaceManager


class MorningWizardScreen(ModalScreen[None]):
    DEFAULT_CSS = """
    MorningWizardScreen {
        align: center middle;
    }
    #dialog {
        width: 72;
        height: auto;
        background: $surface;
        border: round $primary;
        padding: 1 2;
    }
    .field-label {
        color: $primary;
        margin-top: 1;
    }
    #btn-row {
        margin-top: 1;
        align-horizontal: right;
    }
    Button { margin-left: 1; }
    #inp-plan {
        height: 8;
        margin-top: 1;
        border: round $panel;
    }
    """

    def __init__(self, wm: WorkspaceManager, lookback: int = 7) -> None:
        super().__init__()
        self._wm = wm
        self._lookback = lookback
        self._store = wm.store()
        self._notes_dir = wm.notes_dir()

        self._todos = due_or_overdue_todos(self._store)
        self._todo_idx = 0
        self._awaiting_reschedule = False

        self._undated: list[dict] = []
        self._undated_idx = 0
        self._awaiting_assign = False

        self._missing_days: list[date] = []
        self._day_idx = 0

        self._step = "todos"
        if not self._todos:
            self._enter_undated_step()

    # ------------------------------------------------------------- compose

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            if self._step == "todos":
                yield from self._compose_todo_step()
            elif self._step == "undated":
                yield from self._compose_undated_step()
            elif self._step == "journal":
                yield from self._compose_journal_step()
            else:
                yield from self._compose_plan_step()

    def _compose_todo_step(self) -> ComposeResult:
        todo = self._todos[self._todo_idx]
        priority = int(todo.get("priority") or 0)
        yield Static(f"[bold]Morning routine — Todo triage[/bold]  ({self._todo_idx + 1}/{len(self._todos)})")
        yield Static(todo.get("text", ""), classes="field-label")
        yield Static(f"[dim]due {todo.get('due_date')}  ·  priority {priority}[/dim]")
        if self._awaiting_reschedule:
            yield Input(placeholder="YYYY-MM-DD", id="inp-reschedule")
            with Horizontal(id="btn-row"):
                yield Button("Confirm", variant="primary", id="btn-confirm-reschedule")
                yield Button("Cancel", id="btn-cancel-reschedule")
        else:
            with Horizontal(id="btn-row"):
                yield Button("Done", variant="primary", id="btn-done")
                yield Button("Reschedule", id="btn-reschedule")
                yield Button("+Priority", id="btn-bump")
                yield Button("Skip", id="btn-skip")

    def _compose_undated_step(self) -> ComposeResult:
        todo = self._undated[self._undated_idx]
        yield Static(f"[bold]Morning routine — Undated todos[/bold]  ({self._undated_idx + 1}/{len(self._undated)})")
        yield Static(todo.get("text", ""), classes="field-label")
        yield Static("[dim]No due date set.[/dim]")
        if self._awaiting_assign:
            yield Input(placeholder="YYYY-MM-DD", id="inp-assign-due")
            with Horizontal(id="btn-row"):
                yield Button("Confirm", variant="primary", id="btn-confirm-assign")
                yield Button("Cancel", id="btn-cancel-assign")
        else:
            with Horizontal(id="btn-row"):
                yield Button("Assign due date", variant="primary", id="btn-assign")
                yield Button("Skip", id="btn-skip-undated")

    def _compose_journal_step(self) -> ComposeResult:
        d = self._missing_days[self._day_idx]
        yield Static(f"[bold]Morning routine — Journal gap-fill[/bold]  ({self._day_idx + 1}/{len(self._missing_days)})")
        yield Static(d.isoformat(), classes="field-label")
        yield Static("[dim]No journal entry for this day.[/dim]")
        with Horizontal(id="btn-row"):
            yield Button("Open in editor", variant="primary", id="btn-open")
            yield Button("Skip permanently", id="btn-skip-perm")
            yield Button("Not now", id="btn-defer")

    def _compose_plan_step(self) -> ComposeResult:
        yield Static("[bold]Morning routine — Plan today[/bold]")
        yield Static("Vorhaben (optional, mehrzeilig, leer = überspringen)", classes="field-label")
        yield TextArea(id="inp-plan")
        with Horizontal(id="btn-row"):
            yield Button("Save", variant="primary", id="btn-save-plan")
            yield Button("Skip", id="btn-skip-plan")

    def on_mount(self) -> None:
        self._focus_default()

    def _focus_default(self) -> None:
        try:
            if self._step == "todos" and self._awaiting_reschedule:
                self.query_one("#inp-reschedule", Input).focus()
            elif self._step == "undated" and self._awaiting_assign:
                self.query_one("#inp-assign-due", Input).focus()
            elif self._step == "plan":
                self.query_one("#inp-plan", TextArea).focus()
        except Exception:
            pass

    # ------------------------------------------------------------- events

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "inp-reschedule":
            self._confirm_reschedule()
        elif event.input.id == "inp-assign-due":
            self._confirm_assign()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""

        if self._step == "todos":
            self._handle_todo_button(bid)
        elif self._step == "undated":
            self._handle_undated_button(bid)
        elif self._step == "journal":
            self._handle_journal_button(bid)
        else:
            self._handle_plan_button(bid)

    # ------------------------------------------------------------- todos

    def _handle_todo_button(self, bid: str) -> None:
        todo = self._todos[self._todo_idx]
        now = datetime.now().isoformat()

        if bid == "btn-done":
            self._store.update("todos", todo["id"], status="done", updated=now)
            self._advance_todo()
        elif bid == "btn-reschedule":
            self._awaiting_reschedule = True
            self.refresh(recompose=True)
            self.call_after_refresh(self._focus_default)
        elif bid == "btn-confirm-reschedule":
            self._confirm_reschedule()
        elif bid == "btn-cancel-reschedule":
            self._awaiting_reschedule = False
            self.refresh(recompose=True)
        elif bid == "btn-bump":
            priority = int(todo.get("priority") or 0)
            self._store.update("todos", todo["id"], priority=min(priority + 1, 3), updated=now)
            self._advance_todo()
        elif bid == "btn-skip":
            self._advance_todo()

    def _confirm_reschedule(self) -> None:
        todo = self._todos[self._todo_idx]
        new_due = self.query_one("#inp-reschedule", Input).value.strip()
        if new_due:
            self._store.update("todos", todo["id"], due_date=new_due, updated=datetime.now().isoformat())
        self._awaiting_reschedule = False
        self._advance_todo()

    def _advance_todo(self) -> None:
        self._todo_idx += 1
        self._awaiting_reschedule = False
        if self._todo_idx >= len(self._todos):
            self._enter_undated_step()
        self.refresh(recompose=True)
        self.call_after_refresh(self._focus_default)

    # ------------------------------------------------------------- undated

    def _enter_undated_step(self) -> None:
        self._step = "undated"
        self._undated = undated_todos(self._store)
        self._undated_idx = 0
        if not self._undated:
            self._enter_journal_step()

    def _handle_undated_button(self, bid: str) -> None:
        if bid == "btn-assign":
            self._awaiting_assign = True
            self.refresh(recompose=True)
            self.call_after_refresh(self._focus_default)
        elif bid == "btn-confirm-assign":
            self._confirm_assign()
        elif bid == "btn-cancel-assign":
            self._awaiting_assign = False
            self.refresh(recompose=True)
        elif bid == "btn-skip-undated":
            self._advance_undated()

    def _confirm_assign(self) -> None:
        todo = self._undated[self._undated_idx]
        due = self.query_one("#inp-assign-due", Input).value.strip()
        if due:
            self._store.update("todos", todo["id"], due_date=due, updated=datetime.now().isoformat())
        self._awaiting_assign = False
        self._advance_undated()

    def _advance_undated(self) -> None:
        self._undated_idx += 1
        self._awaiting_assign = False
        if self._undated_idx >= len(self._undated):
            self._enter_journal_step()
        self.refresh(recompose=True)
        self.call_after_refresh(self._focus_default)

    # ------------------------------------------------------------- journal

    def _enter_journal_step(self) -> None:
        self._step = "journal"
        self._missing_days = missing_journal_days(self._notes_dir, self._store, self._lookback)
        self._day_idx = 0
        if not self._missing_days:
            self._step = "plan"

    def _handle_journal_button(self, bid: str) -> None:
        d = self._missing_days[self._day_idx]

        if bid == "btn-open":
            path = ensure_note(self._notes_dir, slug_for(d, "day"), "day")
            editor = default_editor()
            with self.app.suspend():
                subprocess.call([editor, str(path)])
            self._advance_day()
        elif bid == "btn-skip-perm":
            mark_journal_day_skipped(self._store, d)
            self._advance_day()
        elif bid == "btn-defer":
            self._advance_day()

    def _advance_day(self) -> None:
        self._day_idx += 1
        if self._day_idx >= len(self._missing_days):
            self._step = "plan"
        self.refresh(recompose=True)
        self.call_after_refresh(self._focus_default)

    # ------------------------------------------------------------- plan

    def _handle_plan_button(self, bid: str) -> None:
        if bid == "btn-save-plan":
            self._save_plan()
        elif bid == "btn-skip-plan":
            self.dismiss(None)

    def _save_plan(self) -> None:
        text = self.query_one("#inp-plan", TextArea).text
        if text.strip():
            append_plan(self._notes_dir, text)
        self.dismiss(None)
