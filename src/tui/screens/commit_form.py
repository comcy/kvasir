"""Commit form: compose and run a Conventional Commit for staged changes.

Never recomposes on error/toggle — all field values live in the mounted
Input/TextArea widgets, mutated in place, so a rejected message never
forces the user to retype the whole form.
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static, TextArea

from src.agent.provider import AgentError, generate_commit_message
from src.data.projects import staged_diff_text, staged_files
from src.hooks.commit_validator import TYPES, parse
from src.workspace.manager import WorkspaceManager


class CommitFormScreen(ModalScreen[bool]):
    DEFAULT_CSS = """
    CommitFormScreen {
        align: center middle;
    }
    #dialog {
        width: 76;
        height: auto;
        background: $surface;
        border: round $primary;
        padding: 1 2;
    }
    .field-label {
        color: $primary;
        margin-top: 1;
    }
    #type-row {
        height: auto;
        margin-top: 0;
    }
    #type-row Button { min-width: 10; margin-right: 1; margin-bottom: 1; }
    #btn-row {
        margin-top: 1;
        align-horizontal: right;
    }
    Button { margin-left: 1; }
    #error { color: $error; margin-top: 1; }
    #body-input { height: 6; margin-top: 1; border: round $panel; }
    #scope-hint { color: $warning; margin-top: 1; }
    #agent-row { height: auto; margin-top: 1; align-vertical: middle; }
    #agent-row LoadingIndicator { width: 3; height: 1; margin-left: 1; }
    #agent-hint { color: $foreground 40%; margin-top: 1; }
    """

    def __init__(
        self,
        worktree_path: str,
        staged_count: int,
        dominant_scope: str | None,
        breakdown: dict[str, int],
        suggested_type: str | None,
    ) -> None:
        super().__init__()
        self._path = worktree_path
        self._staged_count = staged_count
        self._dominant_scope = dominant_scope or ""
        self._breakdown = breakdown
        self._ctype = suggested_type or "feat"
        self._breaking = False
        self._wm = WorkspaceManager()

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(f"[bold]Commit[/bold]  [dim]{self._staged_count} file(s) staged[/dim]")
            if len(self._breakdown) > 1:
                parts = ", ".join(
                    f"{s}({n})" for s, n in sorted(self._breakdown.items(), key=lambda kv: -kv[1])
                )
                yield Static(f"Spans multiple scopes: {parts}", id="scope-hint")

            if self._wm.agent_config().provider != "none":
                with Horizontal(id="agent-row"):
                    yield Button("✦ Generate", id="btn-generate")
            else:
                yield Static(
                    "[dim]No agent configured — press ctrl+g on the dashboard to add one.[/dim]",
                    id="agent-hint",
                )

            yield Label("Type", classes="field-label")
            with Horizontal(id="type-row"):
                for t in TYPES:
                    variant = "primary" if t == self._ctype else "default"
                    yield Button(t, id=f"type-{t}", variant=variant)

            yield Label("Scope (optional)", classes="field-label")
            yield Input(value=self._dominant_scope, placeholder="auth", id="inp-scope")

            yield Label("Subject", classes="field-label")
            yield Input(placeholder="add OAuth2 login", id="inp-subject")

            yield Button("Breaking: no", id="btn-breaking")

            yield Label("Body (optional)", classes="field-label")
            yield TextArea(id="body-input")

            yield Static("", id="error")

            with Horizontal(id="btn-row"):
                yield Button("Commit", variant="primary", id="btn-submit")
                yield Button("Cancel", id="btn-cancel")

    def on_mount(self) -> None:
        self.query_one("#inp-subject", Input).focus()

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss(False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        if bid.startswith("type-"):
            self._ctype = bid[5:]
            for t in TYPES:
                self.query_one(f"#type-{t}", Button).variant = (
                    "primary" if t == self._ctype else "default"
                )
        elif bid == "btn-breaking":
            self._breaking = not self._breaking
            event.button.label = "Breaking: yes" if self._breaking else "Breaking: no"
            event.button.variant = "error" if self._breaking else "default"
        elif bid == "btn-submit":
            self._submit()
        elif bid == "btn-cancel":
            self.dismiss(False)
        elif bid == "btn-generate":
            self._generate()

    def _generate(self) -> None:
        staged = staged_files(self._path)
        if not staged:
            self.query_one("#error", Static).update("[red]Nothing staged.[/red]")
            return
        btn = self.query_one("#btn-generate", Button)
        btn.disabled = True
        btn.label = "Generating…"
        self.query_one("#error", Static).update("")
        self._generate_worker(staged)

    @work(thread=True)
    def _generate_worker(self, staged: list[str]) -> None:
        cfg = self._wm.agent_config()
        try:
            message = generate_commit_message(
                cfg, staged_diff_text(self._path), staged,
                self._ctype, self._dominant_scope or None,
            )
        except AgentError as e:
            self.app.call_from_thread(self._generate_failed, str(e))
            return
        self.app.call_from_thread(self._generate_done, message)

    def _generate_failed(self, message: str) -> None:
        btn = self.query_one("#btn-generate", Button)
        btn.disabled = False
        btn.label = "✦ Generate"
        self.query_one("#error", Static).update(f"[red]{message}[/red]")

    def _generate_done(self, message: str) -> None:
        btn = self.query_one("#btn-generate", Button)
        btn.disabled = False
        btn.label = "✦ Generate"

        first, _, rest = message.partition("\n")
        parsed = parse(first.strip())
        if parsed:
            self._ctype = parsed.type
            for t in TYPES:
                self.query_one(f"#type-{t}", Button).variant = (
                    "primary" if t == self._ctype else "default"
                )
            if parsed.scope:
                self.query_one("#inp-scope", Input).value = parsed.scope
            self.query_one("#inp-subject", Input).value = parsed.subject
            if parsed.breaking and not self._breaking:
                self._breaking = True
                bbtn = self.query_one("#btn-breaking", Button)
                bbtn.label = "Breaking: yes"
                bbtn.variant = "error"
        else:
            self.query_one("#inp-subject", Input).value = first.strip()

        if rest.strip():
            self.query_one("#body-input", TextArea).text = rest.strip()

    def _submit(self) -> None:
        error = self.query_one("#error", Static)
        scope = self.query_one("#inp-scope", Input).value.strip()
        subject = self.query_one("#inp-subject", Input).value.strip()

        if not subject:
            error.update("[red]Subject is required.[/red]")
            return

        scope_part = f"({scope})" if scope else ""
        bang = "!" if self._breaking else ""
        first_line = f"{self._ctype}{scope_part}{bang}: {subject}"

        if parse(first_line) is None:
            error.update(f"[red]Not a valid Conventional Commit:[/red] {first_line}")
            return

        body = self.query_one("#body-input", TextArea).text.strip()
        message = first_line if not body else f"{first_line}\n\n{body}"

        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
            f.write(message)
            msg_path = f.name

        try:
            subprocess.run(
                ["git", "commit", "-F", msg_path], cwd=self._path, check=True, capture_output=True,
            )
        except subprocess.CalledProcessError as e:
            detail = e.stderr.decode(errors="replace").strip() if e.stderr else str(e)
            error.update(f"[red]git commit failed:[/red] {detail}")
            return
        finally:
            Path(msg_path).unlink(missing_ok=True)

        self.dismiss(True)
