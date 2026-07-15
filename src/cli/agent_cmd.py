"""mimirlink agent <sub-command> — configure the optional LLM/agent hookup
used by `mimirlink commit -g` to draft Conventional Commit messages."""
from __future__ import annotations

import os
from typing import Optional

import typer
from rich.console import Console

from src.workspace.config import AgentConfig
from src.workspace.manager import WorkspaceManager

app = typer.Typer(help="Configure the optional commit-message agent.")
console = Console()
_wm = WorkspaceManager()

_PROVIDERS = ("none", "anthropic", "cli")


@app.command("show")
def show() -> None:
    """Show the current agent configuration."""
    cfg = _wm.agent_config()
    console.print(f"\n[bold]Agent configuration[/bold]\n")
    console.print(f"  provider     : [cyan]{cfg.provider}[/cyan]")
    if cfg.provider == "anthropic":
        console.print(f"  model        : {cfg.model}")
        console.print(f"  api_key_env  : {cfg.api_key_env}")
        set_marker = "[green]set[/green]" if os.environ.get(cfg.api_key_env) else "[red]not set[/red]"
        console.print(f"  key present  : {set_marker}  [dim](env var, never stored in config)[/dim]")
    elif cfg.provider == "cli":
        console.print(f"  cli_command  : {cfg.cli_command or '[dim](empty)[/dim]'}")
    console.print()


@app.command("set")
def set_agent(
    provider: str = typer.Option(..., "--provider", help=f"One of: {', '.join(_PROVIDERS)}"),
    model: Optional[str] = typer.Option(None, "--model", help="Model id (provider='anthropic')"),
    api_key_env: Optional[str] = typer.Option(
        None, "--api-key-env", help="Env var holding the API key (provider='anthropic')"
    ),
    cli_command: Optional[str] = typer.Option(
        None, "--cli-command", help="Shell command to run, prompt piped via stdin (provider='cli')"
    ),
) -> None:
    """Set the agent provider and its options."""
    if provider not in _PROVIDERS:
        console.print(f"[red]Unknown provider '{provider}'. Choose from: {', '.join(_PROVIDERS)}[/red]")
        raise typer.Exit(1)

    cfg = _wm.agent_config()
    new_cfg = AgentConfig(
        provider=provider,
        model=model if model is not None else cfg.model,
        api_key_env=api_key_env if api_key_env is not None else cfg.api_key_env,
        cli_command=cli_command if cli_command is not None else cfg.cli_command,
    )
    _wm.set_agent_config(new_cfg)
    console.print(f"[green]Agent provider set to[/green] '[bold]{provider}[/bold]'")
