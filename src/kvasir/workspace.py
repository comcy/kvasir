"""Workspace tab ([workspace] in local.toml): kvasir + AI session + git shell in one new terminal tab.

Pure argv builders (no shell, testable without a terminal) plus a thin runner. kitty and Windows Terminal only.
"""
from __future__ import annotations

import os
import shlex
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

LAYOUTS = ("columns", "bottom")
MODES = ("terminal", "workspace")
DEFAULT_AI = ["claude"]
DEFAULT_RESUME = ["claude", "--continue"]
KEYS = {"layout", "ai_command", "ai_resume_command", "open_mode"}


@dataclass
class WorkspaceConfig:
    layout: str = "columns"
    ai_command: list[str] = field(default_factory=lambda: list(DEFAULT_AI))
    ai_resume_command: list[str] = field(default_factory=lambda: list(DEFAULT_RESUME))
    open_mode: str = "terminal"


def _argv(raw, key: str) -> list[str]:
    parts = shlex.split(raw, posix=sys.platform != "win32") if isinstance(raw, str) else raw
    if not isinstance(parts, list) or not parts or not all(isinstance(a, str) and a for a in parts):
        raise ValueError(f"{key}: expected a command string or non-empty list of strings")
    return list(parts)


def parse(raw: dict) -> WorkspaceConfig:
    """Validate the raw [workspace] table; ValueError with a readable message. Empty table = defaults."""
    if bad := sorted(set(raw) - KEYS):
        raise ValueError(f"unknown key(s): {', '.join(bad)}")
    cfg = WorkspaceConfig()
    if (v := raw.get("layout", cfg.layout)) not in LAYOUTS:
        raise ValueError(f"layout: expected {' | '.join(LAYOUTS)}, got {v!r}")
    cfg.layout = v
    if (v := raw.get("open_mode", cfg.open_mode)) not in MODES:
        raise ValueError(f"open_mode: expected {' | '.join(MODES)}, got {v!r}")
    cfg.open_mode = v
    for key in ("ai_command", "ai_resume_command"):
        if key in raw:
            setattr(cfg, key, _argv(raw[key], key))
    return cfg


def detect(env: dict | None = None) -> str | None:
    """"kitty" | "wt" | None, from the environment of the terminal kvasir runs in."""
    env = os.environ if env is None else env
    if env.get("KITTY_WINDOW_ID"):
        return "kitty"
    if env.get("WT_SESSION"):
        return "wt"
    return None


def title(repo: str, branch: str) -> str:
    return f"{repo} · {branch}"


def kvasir_argv(path: Path) -> list[str]:
    return ["kvasir", "tui", "--select", str(path)]


def wt_argv(path: Path, tab_title: str, ai: list[str], layout: str = "columns") -> list[str]:
    """One wt call; each `;` is its own argument (wt's subcommand separator, no shell involved)."""
    p = str(path)
    ai_pane = ["sp", "-V", "-s", "0.7", "-d", p, "--title", "ai", *ai]
    git_pane = ["sp", "-H", "-s", "0.3", "-d", p, "--title", "git"]
    first = ["-w", "0", "nt", "-d", p, "--title", tab_title, *kvasir_argv(path)]
    if layout == "bottom":  # git strip first (full width), back to kvasir, then split the top row
        return ["wt", *first, ";", *git_pane, ";", "mf", "up", ";", *ai_pane]
    return ["wt", *first, ";", *ai_pane, ";", *git_pane]


def kitty_steps(path: Path, tab_title: str, ai: list[str], layout: str = "columns") -> list[list[str]]:
    """Launch argvs in order. `id:{kvasir}`/`id:{ai}` are replaced by window ids from earlier steps."""
    p = str(path)
    base = ["kitten", "@", "launch", "--cwd", p]
    tab = [*base, "--type=tab", "--tab-title", tab_title, *kvasir_argv(path)]
    ai_win = [*base, "--type=window", "--location=vsplit", "--bias=70", "--match", "id:{kvasir}", "--title", "ai", *ai]
    if layout == "bottom":
        git = [*base, "--type=window", "--location=hsplit", "--bias=30", "--match", "id:{kvasir}", "--title", "git"]
        return [tab, git, ai_win]
    git = [*base, "--type=window", "--location=hsplit", "--bias=30", "--match", "id:{ai}", "--title", "git"]
    return [tab, ai_win, git]


def _launch(argv: list[str]) -> str:
    r = subprocess.run(argv, capture_output=True, text=True, timeout=10, check=False)
    if r.returncode != 0:
        raise OSError(r.stderr.strip() or f"{argv[0]} exit {r.returncode}")
    return r.stdout.strip()


def run_kitty(steps: list[list[str]], launch: Callable[[list[str]], str] = _launch) -> None:
    """Run the steps; the window id each `launch` prints feeds the `--match` of the next ones."""
    ids: dict[str, str] = {}
    names = ["kvasir", *(["ai", "git"] if "{ai}" in " ".join(steps[-1]) else ["git", "ai"])]
    for name, argv in zip(names, steps, strict=True):
        wid = launch([a.format(**ids) if a.startswith("id:") else a for a in argv])
        if not wid.isdigit():
            raise OSError(f"unexpected output of kitten @ launch: {wid!r}")
        ids[name] = wid


def open_workspace(path: Path, tab_title: str, cfg: WorkspaceConfig, resume: bool = True,
                   env: dict | None = None, launch: Callable[[list[str]], str] = _launch) -> str | None:
    """Start the tab. None = done; otherwise a hint, the caller falls back to the plain open_command."""
    term = detect(env)
    ai = cfg.ai_resume_command if resume else cfg.ai_command
    try:
        if term == "kitty":
            run_kitty(kitty_steps(path, tab_title, ai, cfg.layout), launch)
        elif term == "wt":
            kw: dict = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
            if sys.platform == "win32":
                kw["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
            subprocess.Popen(wt_argv(path, tab_title, ai, cfg.layout), cwd=str(path), **kw)
        else:
            return "Workspace braucht kitty oder Windows Terminal; öffne normales Terminal"
    except OSError as e:
        return f"Workspace nicht gestartet ({e}); öffne normales Terminal"
    return None
