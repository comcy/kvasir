"""Config files. Two, so the shared one can be synced between machines later.

- repos.toml  (shareable, keyed by normalized remote URL): branch patterns, fetch interval, platform interval
- local.toml  (per machine): open_command, local path per repo URL, [llm] (see llm.py), [report] (see report_out.py)
"""
import json
import os
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_PATTERNS = ["{type}/{slug}"]
DEFAULT_FETCH_MINUTES = 15
DEFAULT_PLATFORM_MINUTES = 10


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
    platform_interval: int = DEFAULT_PLATFORM_MINUTES  # minutes, PR/issue/pipeline refresh
    patterns_set: bool = True  # False = no local choice, kvasir.toml [branches] decides (see repo_file)
    llm: bool = True  # False = opt-out: no LLM function may send this repo's data (repos.toml `llm = false`)


@dataclass
class LocalConfig:
    open_command: str | None = None
    paths: dict[str, str] = field(default_factory=dict)  # repo URL -> local path
    llm: dict = field(default_factory=dict)  # raw [llm] table, parsed/validated by kvasir.llm
    report: dict = field(default_factory=dict)  # raw [report] table, parsed/validated by kvasir.report_out


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
            platform_interval=int(v.get("platform_interval", DEFAULT_PLATFORM_MINUTES)),
            patterns_set="branch_patterns" in v,
            llm=bool(v.get("llm", True)),
        )
        for url, v in _read("repos.toml").items()
    }


def save_repos(repos: dict[str, RepoConfig]) -> None:
    out = []
    for url, c in sorted(repos.items()):
        patterns = ", ".join(_q(p) for p in c.branch_patterns)
        pat = f"branch_patterns = [{patterns}]\n" if c.patterns_set else ""
        out.append(f"[{_q(url)}]\n{pat}fetch_interval = {c.fetch_interval}\n"
                   f"platform_interval = {c.platform_interval}\n" + ("" if c.llm else "llm = false\n"))
    _write("repos.toml", "\n".join(out))


def load_local() -> LocalConfig:
    raw = _read("local.toml")
    return LocalConfig(open_command=raw.get("open_command"), paths=dict(raw.get("repos", {})),
                       llm=dict(raw.get("llm", {})), report=dict(raw.get("report", {})))


def save_local(c: LocalConfig) -> None:
    out = [f"open_command = {_q(c.open_command)}\n"] if c.open_command else []
    if c.paths:
        out.append("[repos]")
        out += [f"{_q(u)} = {_q(p)}" for u, p in sorted(c.paths.items())]
    if c.llm:  # values: str, int or list of str
        out.append("\n[llm]")
        out += [f"{k} = {json.dumps(v)}" for k, v in c.llm.items()]
    if c.report:  # values: str
        out.append("\n[report]")
        out += [f"{k} = {json.dumps(v)}" for k, v in c.report.items()]
    _write("local.toml", "\n".join(out) + "\n")
