"""Project form: clone a new repo (bare-worktree layout) or register an existing one.

git clone/fetch can take a while — running them on Textual's event loop would
freeze the whole UI, so the clone runs in a @work(thread=True) worker and
reports back to the UI thread via app.call_from_thread.
"""
from __future__ import annotations

from pathlib import Path

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, LoadingIndicator, Static

from src.data.projects import clone_project, register_existing
from src.workspace.manager import WorkspaceManager


class ProjectFormScreen(ModalScreen[dict | None]):
    DEFAULT_CSS = """
    ProjectFormScreen {
        align: center middle;
    }
    #dialog {
        width: 74;
        height: auto;
        background: $surface;
        border: round $primary;
        padding: 1 2;
    }
    .field-label {
        color: $primary;
        margin-top: 1;
    }
    #mode-row {
        height: auto;
        margin-top: 1;
    }
    #mode-row Button { min-width: 16; margin-right: 1; }
    #btn-row {
        margin-top: 1;
        align-horizontal: right;
    }
    Button { margin-left: 1; }
    #error { color: $error; margin-top: 1; }
    #busy { height: auto; margin-top: 1; }
    #busy LoadingIndicator { width: 3; height: 1; }
    """

    def __init__(self, wm: WorkspaceManager) -> None:
        super().__init__()
        self._wm = wm
        self._mode = "clone"  # "clone" | "add"
        self._busy = False
        self._error = ""

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static("[bold]New Project[/bold]")
            with Horizontal(id="mode-row"):
                yield Button(
                    "Clone", id="mode-clone",
                    variant="primary" if self._mode == "clone" else "default",
                )
                yield Button(
                    "Add existing", id="mode-add",
                    variant="primary" if self._mode == "add" else "default",
                )

            yield Label("Name", classes="field-label")
            yield Input(placeholder="myproject", id="inp-name", disabled=self._busy)

            if self._mode == "clone":
                yield Label("Repository URL", classes="field-label")
                yield Input(placeholder="git@github.com:me/myproject.git", id="inp-url", disabled=self._busy)
                yield Label("Clone into directory", classes="field-label")
                yield Input(value=str(Path.home()), id="inp-dir", disabled=self._busy)
            else:
                yield Label("Path to existing repo", classes="field-label")
                yield Input(value=str(Path.cwd()), id="inp-path", disabled=self._busy)

            if self._error:
                yield Static(self._error, id="error")
            if self._busy:
                with Horizontal(id="busy"):
                    yield LoadingIndicator()
                    yield Static("  Cloning…")

            with Horizontal(id="btn-row"):
                yield Button(
                    "Save" if self._mode == "add" else "Clone",
                    variant="primary", id="btn-submit", disabled=self._busy,
                )
                yield Button("Cancel", id="btn-cancel", disabled=self._busy)

    def on_mount(self) -> None:
        try:
            self.query_one("#inp-name", Input).focus()
        except Exception:
            pass

    def on_key(self, event) -> None:
        if event.key == "escape" and not self._busy:
            self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        if bid == "mode-clone" and self._mode != "clone":
            self._mode = "clone"
            self._error = ""
            self.refresh(recompose=True)
        elif bid == "mode-add" and self._mode != "add":
            self._mode = "add"
            self._error = ""
            self.refresh(recompose=True)
        elif bid == "btn-submit":
            self._submit()
        elif bid == "btn-cancel":
            self.dismiss(None)

    def _fail(self, message: str) -> None:
        self._busy = False
        self._error = message
        self.refresh(recompose=True)
        self.call_after_refresh(self.on_mount)

    def _submit(self) -> None:
        name = self.query_one("#inp-name", Input).value.strip()
        if not name:
            self._fail("Name is required.")
            return

        if self._mode == "add":
            path = self.query_one("#inp-path", Input).value.strip() or str(Path.cwd())
            try:
                record = register_existing(self._wm.store(), name, path)
            except Exception as e:
                self._fail(str(e))
                return
            self.dismiss(record)
            return

        url = self.query_one("#inp-url", Input).value.strip()
        dest_dir = self.query_one("#inp-dir", Input).value.strip() or str(Path.home())
        if not url:
            self._fail("URL is required.")
            return

        self._busy = True
        self._error = ""
        self.refresh(recompose=True)
        self._clone_worker(name, url, dest_dir)

    @work(thread=True)
    def _clone_worker(self, name: str, url: str, dest_dir: str) -> None:
        try:
            record = clone_project(self._wm.store(), url, name, dest_dir)
        except Exception as e:
            self.app.call_from_thread(self._fail, str(e))
            return
        self.app.call_from_thread(self.dismiss, record)
