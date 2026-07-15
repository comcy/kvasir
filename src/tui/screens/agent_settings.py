"""Agent settings: configure the optional LLM/agent hookup used by the
Commit form's "Generate" button and `mimirlink commit -g`."""
from __future__ import annotations

import os

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static

from src.workspace.config import AgentConfig
from src.workspace.manager import WorkspaceManager

_PROVIDERS = ("none", "anthropic", "cli")
_PROVIDER_LABELS = {"none": "None", "anthropic": "Anthropic API", "cli": "CLI Agent"}


class AgentSettingsScreen(ModalScreen[AgentConfig | None]):
    DEFAULT_CSS = """
    AgentSettingsScreen {
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
    #mode-row {
        height: auto;
        margin-top: 1;
    }
    #mode-row Button { min-width: 16; margin-right: 1; }
    #hint {
        color: $foreground 50%;
        margin-top: 1;
    }
    #key-status {
        margin-top: 1;
    }
    #btn-row {
        margin-top: 1;
        align-horizontal: right;
    }
    Button { margin-left: 1; }
    #error { color: $error; margin-top: 1; }
    """

    def __init__(self, wm: WorkspaceManager) -> None:
        super().__init__()
        self._wm = wm
        cfg = wm.agent_config()
        self._provider = cfg.provider
        self._model = cfg.model
        self._api_key_env = cfg.api_key_env
        self._cli_command = cfg.cli_command
        self._error = ""

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static("[bold]Agent settings[/bold]  [dim]used by Commit → Generate[/dim]")
            with Horizontal(id="mode-row"):
                for p in _PROVIDERS:
                    yield Button(
                        _PROVIDER_LABELS[p], id=f"mode-{p}",
                        variant="primary" if p == self._provider else "default",
                    )

            if self._provider == "anthropic":
                yield Label("Model", classes="field-label")
                yield Input(value=self._model, placeholder="claude-sonnet-5", id="inp-model")
                yield Label("API key environment variable", classes="field-label")
                yield Input(value=self._api_key_env, placeholder="ANTHROPIC_API_KEY", id="inp-key-env")
                present = os.environ.get(self._api_key_env)
                status = "[green]set[/green]" if present else "[red]not set[/red]"
                yield Static(f"  Key currently: {status}  [dim](never stored in config)[/dim]", id="key-status")
                yield Static(
                    "[dim]Requires the optional 'anthropic' package (pip install anthropic).[/dim]",
                    id="hint",
                )
            elif self._provider == "cli":
                yield Label("CLI command (prompt is piped via stdin)", classes="field-label")
                yield Input(value=self._cli_command, placeholder="claude -p", id="inp-cli-command")
                yield Static(
                    "[dim]Any agent that reads a prompt on stdin and prints the message on "
                    "stdout works — e.g. `claude -p`, `ollama run llama3.2`, a custom script.[/dim]",
                    id="hint",
                )
            else:
                yield Static(
                    "[dim]No agent configured — the Commit form stays fully manual.[/dim]",
                    id="hint",
                )

            if self._error:
                yield Static(self._error, id="error")

            with Horizontal(id="btn-row"):
                yield Button("Save", variant="primary", id="btn-save")
                yield Button("Cancel", id="btn-cancel")

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss(None)

    def _capture_inputs(self) -> None:
        """Save whatever the user typed for the current provider before switching."""
        try:
            if self._provider == "anthropic":
                self._model = self.query_one("#inp-model", Input).value.strip() or self._model
                self._api_key_env = self.query_one("#inp-key-env", Input).value.strip() or self._api_key_env
            elif self._provider == "cli":
                self._cli_command = self.query_one("#inp-cli-command", Input).value
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        if bid.startswith("mode-"):
            new_provider = bid[len("mode-"):]
            if new_provider != self._provider:
                self._capture_inputs()
                self._provider = new_provider
                self._error = ""
                self.refresh(recompose=True)
        elif bid == "btn-save":
            self._submit()
        elif bid == "btn-cancel":
            self.dismiss(None)

    def _submit(self) -> None:
        self._capture_inputs()
        cfg = AgentConfig(
            provider=self._provider,
            model=self._model or "claude-sonnet-5",
            api_key_env=self._api_key_env or "ANTHROPIC_API_KEY",
            cli_command=self._cli_command,
        )
        if cfg.provider == "cli" and not cfg.cli_command.strip():
            self._error = "[red]CLI command is required for provider 'cli'.[/red]"
            self.refresh(recompose=True)
            return
        self._wm.set_agent_config(cfg)
        self.dismiss(cfg)
