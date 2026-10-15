"""Workspace tab ([workspace] in local.toml): kvasir + AI session + git shell in one new terminal tab.

Pure argv builders (no shell, testable without a terminal) plus a thin runner. kitty and Windows Terminal only.
"""
from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from kvasir.config import config_dir

LAYOUTS = ("columns", "bottom")
MODES = ("terminal", "workspace")
DEFAULT_AI = ["claude"]
DEFAULT_RESUME = ["claude", "--continue"]
KEYS = {"layout", "ai_command", "ai_resume_command", "open_mode", "tint"}
PALETTE = ["#e5484d", "#f76b15", "#e5a50a", "#30a46c", "#12a594", "#0091ff", "#6e56cf", "#d6409f"]
REGISTRY = "workspaces.json"
MAX_AGE = 7 * 86400  # entries without a window id (Windows Terminal) are dropped after this


@dataclass
class WorkspaceConfig:
    layout: str = "columns"
    ai_command: list[str] = field(default_factory=lambda: list(DEFAULT_AI))
    ai_resume_command: list[str] = field(default_factory=lambda: list(DEFAULT_RESUME))
    open_mode: str = "terminal"
    tint: bool = False  # kitty only: tint the background of the workspace windows with the repo color


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
    v = raw.get("tint", cfg.tint)
    if v not in (True, False) or not isinstance(v, bool):
        raise ValueError(f"tint: expected true | false, got {v!r}")
    cfg.tint = v
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


def needs_suspend(env: dict | None = None) -> bool:
    """kitty without a socket (`listen_on`): `kitten @` talks over the tty the TUI is reading, so Textual
    would swallow kitty's answer (timeout). The caller then runs open_workspace inside `App.suspend()`."""
    env = os.environ if env is None else env
    return detect(env) == "kitty" and not env.get("KITTY_LISTEN_ON")


def title(repo: str, branch: str) -> str:
    return f"{repo} · {branch}"


def kvasir_argv(path: Path) -> list[str]:
    return ["kvasir", "tui", "--select", str(path)]


def repo_color(url: str, override: str | None = None) -> str:
    """Stable `#rrggbb` per repo URL (md5, not hash(): that one is salted per process); override wins."""
    return override or PALETTE[int(hashlib.md5(url.encode()).hexdigest(), 16) % len(PALETTE)]


def _blend(color: str, k: float = 0.18, base: int = 0x10) -> str:
    """Subtle background: `k` of the color over a dark base. ponytail: assumes a dark terminal background."""
    return "#" + "".join(f"{round(base + (int(color[i:i + 2], 16) - base) * k):02x}" for i in (1, 3, 5))


AI_SHARE = 45   # percent of the width for the AI pane (kvasir keeps ~55)
GIT_SHARE = 30  # percent of the height for the git strip


def keep_shell(ai: list[str], win: bool = False) -> list[str]:
    """Run `ai`, then leave the user's shell in the pane whatever the exit code. posix: the command is
    passed as "$@", never interpolated. PowerShell has no "$@" and -Command takes text, so each argument
    is single-quoted (`'` doubled) and `-NoExit` keeps the shell."""
    if win:
        return ["powershell", "-NoExit", "-Command", "& " + " ".join("'" + a.replace("'", "''") + "'" for a in ai)]
    return ["sh", "-c", '"$@"; exec "${SHELL:-sh}"', "sh", *ai]


def wt_argv(path: Path, tab_title: str, ai: list[str], layout: str = "columns", color: str | None = None) -> list[str]:
    """One wt call; each `;` is its own argument (wt's subcommand separator, no shell involved)."""
    p = str(path)
    ai_pane = ["sp", "-V", "-s", f"{AI_SHARE / 100:g}", "-d", p, "--title", "ai", *keep_shell(ai, win=True)]
    git_pane = ["sp", "-H", "-s", f"{GIT_SHARE / 100:g}", "-d", p, "--title", "git"]
    first = ["-w", "0", "nt", "-d", p, "--title", tab_title, *(["--tabColor", color] if color else []),
             *kvasir_argv(path)]
    if layout == "bottom":  # git strip first (full width), back to kvasir, then split the top row
        return ["wt", *first, ";", *git_pane, ";", "mf", "up", ";", *ai_pane]
    return ["wt", *first, ";", *ai_pane, ";", *git_pane]


def kitty_steps(path: Path, tab_title: str, ai: list[str], layout: str = "columns") -> list[list[str]]:
    """Argvs in order: tab, goto-layout, then the splits. `{kvasir}`/`{ai}` in `window_id:`/`id:` args are
    replaced by the window ids earlier `launch` steps printed (window_id: = the tab holding that window,
    id: with --next-to = the window itself; a bare `--match id:` would mean a *tab* id)."""
    p = str(path)
    base = ["kitten", "@", "launch", "--cwd", p]
    tab = [*base, "--type=tab", "--tab-title", tab_title, *kvasir_argv(path)]
    layout_step = ["kitten", "@", "goto-layout", "--match", "window_id:{kvasir}", "splits"]  # vsplit/hsplit need it

    def win(loc: str, bias: int, near: str, title: str, *cmd: str) -> list[str]:
        return [*base, "--type=window", f"--location={loc}", f"--bias={bias}", "--match", "window_id:{kvasir}",
                "--next-to", f"id:{{{near}}}", "--title", title, *cmd]

    shell_ai = keep_shell(ai)
    if layout == "bottom":
        return [tab, layout_step, win("hsplit", GIT_SHARE, "kvasir", "git"),
                win("vsplit", AI_SHARE, "kvasir", "ai", *shell_ai)]
    return [tab, layout_step, win("vsplit", AI_SHARE, "kvasir", "ai", *shell_ai),
            win("hsplit", GIT_SHARE, "ai", "git")]


def kitty_color_steps(color: str, tint: bool = False) -> list[list[str]]:
    """Tab color (and optional window tint) for the tab holding the `{kvasir}` window."""
    steps = [["kitten", "@", "set-tab-color", "--match", "window_id:{kvasir}", f"active_bg={color}",
              f"inactive_bg={_blend(color, 0.5)}", "active_fg=#ffffff", "inactive_fg=#ffffff"]]
    if tint:
        steps.append(["kitten", "@", "set-colors", "--match", "id:{kvasir} or id:{ai} or id:{git}",
                      f"background={_blend(color)}"])
    return steps


def kitty_focus_argv(window: str) -> list[str]:
    return ["kitten", "@", "focus-tab", "--match", f"window_id:{window}"]


def kitty_alive(launch: Callable[[list[str]], str] | None = None) -> set[str] | None:
    """Window ids kitty currently has (`kitten @ ls`); None when kitty cannot be asked."""
    try:
        data = json.loads((launch or _launch)(["kitten", "@", "ls"]))
        return {str(w["id"]) for o in data for t in o["tabs"] for w in t["windows"]}
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        return None


def _registry_path() -> Path:
    return config_dir() / REGISTRY


def _load_registry() -> dict[str, dict]:
    try:
        data = json.loads(_registry_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    ok = isinstance(data, dict) and all(isinstance(v, dict) and isinstance(v.get("ts"), (int, float))
                                        for v in data.values())
    return data if ok else {}


def _save_registry(reg: dict[str, dict]) -> None:
    p = _registry_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(json.dumps(reg, indent=1), encoding="utf-8")
        os.replace(tmp, p)  # atomic
    except OSError:
        pass  # remembering is a convenience, never an error


def register(path: Path, term: str, window: str | None, now: float | None = None) -> None:
    """Remember an opened workspace: worktree path -> terminal, window id (None for wt), timestamp."""
    reg = _load_registry()
    reg[str(path)] = {"terminal": term, "window": window, "ts": time.time() if now is None else now}
    _save_registry(reg)


def sessions(alive: set[str] | None = None, now: float | None = None) -> dict[str, dict]:
    """Registry without orphans, written back when something was dropped. `alive`: window ids kitty has
    (None = unknown, keep kitty entries). Entries without window id expire after MAX_AGE."""
    now = time.time() if now is None else now
    reg = _load_registry()
    keep = {p: e for p, e in reg.items()
            if (e.get("window") and (alive is None or e["window"] in alive))
            or (not e.get("window") and now - e["ts"] < MAX_AGE)}
    if keep != reg:
        _save_registry(keep)
    return keep


def _launch(argv: list[str]) -> str:
    r = subprocess.run(argv, capture_output=True, text=True, timeout=10, check=False)
    if r.returncode != 0:
        raise OSError(r.stderr.strip() or f"{argv[0]} exit {r.returncode}")
    return r.stdout.strip()


def run_kitty(steps: list[list[str]], launch: Callable[[list[str]], str] = _launch) -> str:
    """Run the steps; the window id each `launch` prints feeds the match args of the later ones.
    Returns the id of the kvasir window."""
    ids: dict[str, str] = {}
    last = [s for s in steps if s[2] == "launch"][-1]
    names = iter(["kvasir", *(["ai", "git"] if any("id:{ai}" in a for a in last) else ["git", "ai"])])
    for argv in steps:
        out = launch([a.format(**ids) if a.startswith(("id:", "window_id:")) else a for a in argv])
        if argv[2] != "launch":
            continue
        if not out.isdigit():
            raise OSError(f"unexpected output of kitten @ launch: {out!r}")
        ids[next(names)] = out
    return ids["kvasir"]


def open_workspace(path: Path, tab_title: str, cfg: WorkspaceConfig, resume: bool = True,
                   env: dict | None = None, launch: Callable[[list[str]], str] = _launch,
                   color: str | None = None, on_open: Callable[[str, str | None], None] | None = None) -> str | None:
    """Start the tab. None = done; otherwise a hint, the caller falls back to the plain open_command.
    `color`: tab color; `on_open(terminal, window id or None)` is called after a successful start."""
    term = detect(env)
    ai = cfg.ai_resume_command if resume else cfg.ai_command
    try:
        if term == "kitty":
            steps = kitty_steps(path, tab_title, ai, cfg.layout) + (kitty_color_steps(color, cfg.tint) if color else [])
            win: str | None = run_kitty(steps, launch)
        elif term == "wt":
            kw: dict = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
            if sys.platform == "win32":
                kw["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
            subprocess.Popen(wt_argv(path, tab_title, ai, cfg.layout, color), cwd=str(path), **kw)
            win = None  # wt reports no window id
        else:
            return "Workspace braucht kitty oder Windows Terminal; öffne normales Terminal"
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"Workspace nicht gestartet ({e}); öffne normales Terminal"
    if on_open:
        on_open(term, win)
    return None
