"""Config files. Two, so the shared one can be synced between machines later.

- repos.toml  (shareable, keyed by normalized remote URL): branch patterns, fetch interval
- local.toml  (per machine): open_command, local path per repo URL
"""
import json
import os
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_PATTERNS = ["{type}/{slug}"]
DEFAULT_FETCH_MINUTES = 15


def config_dir() -> Path:
    if env := os.environ.get("KVASIR_CONFIG_DIR"):
        return Path(env)
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home())) / "kvasir"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "kvasir"


def default_open_command() -> str:
    return "wt.exe -d {path}" if sys.platform == "win32" else "kitty --directory {path}"


@dataclass
class RepoConfig:
    branch_patterns: list[str] = field(default_factory=lambda: list(DEFAULT_PATTERNS))
    fetch_interval: int = DEFAULT_FETCH_MINUTES  # minutes


@dataclass
class LocalConfig:
    open_command: str | None = None
    paths: dict[str, str] = field(default_factory=dict)  # repo URL -> local path


def _read(name: str) -> dict:
    p = config_dir() / name
    return tomllib.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _write(name: str, text: str) -> None:
    p = config_dir() / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _q(s: str) -> str:
    return json.dumps(s)  # JSON string escaping is valid TOML basic-string escaping


def load_repos() -> dict[str, RepoConfig]:
    return {
        url: RepoConfig(
            branch_patterns=list(v.get("branch_patterns", DEFAULT_PATTERNS)),
            fetch_interval=int(v.get("fetch_interval", DEFAULT_FETCH_MINUTES)),
        )
        for url, v in _read("repos.toml").items()
    }


def save_repos(repos: dict[str, RepoConfig]) -> None:
    out = []
    for url, c in sorted(repos.items()):
        patterns = ", ".join(_q(p) for p in c.branch_patterns)
        out.append(f"[{_q(url)}]\nbranch_patterns = [{patterns}]\nfetch_interval = {c.fetch_interval}\n")
    _write("repos.toml", "\n".join(out))


def load_local() -> LocalConfig:
    raw = _read("local.toml")
    return LocalConfig(open_command=raw.get("open_command"), paths=dict(raw.get("repos", {})))


def save_local(c: LocalConfig) -> None:
    out = [f"open_command = {_q(c.open_command)}\n"] if c.open_command else []
    if c.paths:
        out.append("[repos]")
        out += [f"{_q(u)} = {_q(p)}" for u, p in sorted(c.paths.items())]
    _write("local.toml", "\n".join(out) + "\n")
