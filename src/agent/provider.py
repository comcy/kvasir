"""Generic agent hookup — the single place that knows how to reach whichever
agent the user configured (see AgentConfig).

Two backends, chosen via `AgentConfig.provider`:
- "cli": shells out to any command (`claude -p`, `ollama run ...`, a custom
  script) with the prompt on stdin — the vendor-agnostic way to attach
  whichever agent the user already has installed.
- "anthropic": calls the Anthropic API directly (optional `anthropic`
  package, lazy-imported so it's never a hard dependency).

`ask()` is the generic primitive — send a prompt, get text back. Feature-
specific callers (commit-message generation today; note actions, Q&A over
notes, etc. later) build their own prompt and call `ask()`; they don't talk
to the backends directly. Always optional: with provider="none" (the
default) `ask()` raises `AgentError` and callers fall back to their existing
non-agent behavior — mirrors CONTEXT.md's "LLM integration is always
optional" rule.
"""
from __future__ import annotations

import os
import shlex
import subprocess

from src.hooks.commit_validator import TYPES
from src.workspace.config import AgentConfig

_MAX_DIFF_CHARS = 8000
_TIMEOUT_SECONDS = 60


class AgentError(Exception):
    """Agent call failed or is unavailable; message is safe to show to the user."""


def _build_commit_prompt(
    diff: str,
    staged_files: list[str],
    suggested_type: str | None,
    dominant_scope: str | None,
) -> str:
    truncated = diff[:_MAX_DIFF_CHARS]
    if len(diff) > _MAX_DIFF_CHARS:
        truncated += "\n… (diff truncated)"

    hints = []
    if suggested_type:
        hints.append(f"likely type: {suggested_type}")
    if dominant_scope:
        hints.append(f"likely scope: {dominant_scope}")
    hint_line = f"Hints: {', '.join(hints)}\n" if hints else ""

    return (
        "Write a Conventional Commit message for the following staged changes.\n"
        f"Allowed types: {', '.join(TYPES)}.\n"
        "Output ONLY the commit message (a type(scope): subject first line, "
        "optionally followed by a blank line and a short body). "
        "No markdown code fences, no explanation.\n\n"
        f"{hint_line}"
        f"Staged files ({len(staged_files)}):\n"
        + "\n".join(f"  {f}" for f in staged_files)
        + "\n\nDiff:\n"
        + truncated
    )


def _call_cli(cfg: AgentConfig, prompt: str) -> str:
    if not cfg.cli_command.strip():
        raise AgentError("No cli_command configured for provider='cli'.")
    try:
        args = shlex.split(cfg.cli_command)
    except ValueError as e:
        raise AgentError(f"Invalid cli_command: {e}")

    try:
        result = subprocess.run(
            args, input=prompt, capture_output=True, text=True, timeout=_TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        raise AgentError(f"Command not found: {args[0]}")
    except subprocess.TimeoutExpired:
        raise AgentError(f"Agent command timed out after {_TIMEOUT_SECONDS}s.")

    if result.returncode != 0:
        detail = result.stderr.strip() or f"exit code {result.returncode}"
        raise AgentError(f"Agent command failed: {detail}")

    output = result.stdout.strip()
    if not output:
        raise AgentError("Agent command produced no output.")
    return output


def _call_anthropic(cfg: AgentConfig, prompt: str) -> str:
    try:
        import anthropic
    except ImportError:
        raise AgentError(
            "The 'anthropic' package is not installed. Run: pip install anthropic "
            "(or `pip install mimirlink[llm]`)."
        )

    api_key = os.environ.get(cfg.api_key_env)
    if not api_key:
        raise AgentError(f"Environment variable '{cfg.api_key_env}' is not set.")

    client = anthropic.Anthropic(api_key=api_key)
    try:
        response = client.messages.create(
            model=cfg.model,
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as e:
        raise AgentError(f"Anthropic API call failed: {e}")

    text = "".join(
        block.text for block in response.content if getattr(block, "type", "") == "text"
    ).strip()
    if not text:
        raise AgentError("Anthropic API returned no text.")
    return text


def _strip_fences(text: str) -> str:
    lines = text.strip().splitlines()
    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def ask(cfg: AgentConfig, prompt: str) -> str:
    """Send an arbitrary prompt to the configured agent, return its text reply.

    The generic building block behind generate_commit_message and any future
    agent-powered feature (note actions, Q&A over notes, ...) — carries no
    feature-specific logic itself. Raises AgentError if no agent is
    configured or the call fails; callers must catch it and fall back to
    their non-agent behavior, never block on it.
    """
    if cfg.provider == "none":
        raise AgentError("No agent configured.")

    if cfg.provider == "cli":
        raw = _call_cli(cfg, prompt)
    elif cfg.provider == "anthropic":
        raw = _call_anthropic(cfg, prompt)
    else:
        raise AgentError(f"Unknown provider: {cfg.provider!r}")

    return _strip_fences(raw)


def generate_commit_message(
    cfg: AgentConfig,
    diff: str,
    staged_files: list[str],
    suggested_type: str | None = None,
    dominant_scope: str | None = None,
) -> str:
    """Ask the configured agent for a Conventional Commit message."""
    if not staged_files:
        raise AgentError("Nothing staged.")
    prompt = _build_commit_prompt(diff, staged_files, suggested_type, dominant_scope)
    return ask(cfg, prompt)
