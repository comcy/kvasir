"""`kvasir doctor`: check prerequisites, offer to install a missing platform CLI. No Typer.

Safety: only winget (Windows) and brew (macOS) are ever run, and only after an explicit yes.
Linux: command is shown, never run. Login and scopes are shown, never run. No sudo by kvasir.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from kvasir.config import load_local, load_repos
from kvasir.platform.detect import detect_platform

TIMEOUT = 30  # seconds, version/auth checks
INSTALL_TIMEOUT = 600  # winget/brew can be slow
MIN_GIT = (2, 36)
OS_RELEASE = Path("/etc/os-release")
LINUX_DOCS = "https://github.com/cli/cli/blob/trunk/docs/install_linux.md"


@dataclass(frozen=True)
class Cli:
    name: str
    platform: str  # PlatformRepo.kind served by this CLI
    docs: str  # install instructions (fallback)
    install: dict[str, list[str]]  # sys.platform -> argv (only win32/darwin are ever executed)
    linux: dict[str, str]  # distro id -> command or link (shown only)
    login: str
    scope_cmd: str | None = None
    scope: str | None = None  # needed for the optional board status
    min_version: tuple[int, ...] | None = None
    active: bool = True


CLIS = {
    "github": Cli(
        "gh", "github", "https://cli.github.com",
        {"win32": ["winget", "install", "--id", "GitHub.cli"], "darwin": ["brew", "install", "gh"]},
        {"arch": "sudo pacman -S github-cli", "fedora": "sudo dnf install gh",
         "debian": LINUX_DOCS, "ubuntu": LINUX_DOCS},
        "gh auth login", "gh auth refresh -s read:project", "read:project",
    ),
    "azure": Cli(
        "az", "azure", "https://learn.microsoft.com/cli/azure/install-azure-cli",
        {"win32": ["winget", "install", "--id", "Microsoft.AzureCLI"], "darwin": ["brew", "install", "azure-cli"]},
        {}, "az login",  # linux: no per-distro table, the Microsoft page covers every distribution
    ),
}


@dataclass
class Check:
    status: str  # "ok" | "fail" | "warn"
    text: str
    fix: str | None = None
    missing: Cli | None = None  # set when this CLI is not installed (install offer)


MARK = {"ok": "✓", "fail": "✗", "warn": "!"}


def _run(argv: list[str], timeout: int = TIMEOUT) -> tuple[int, str] | None:
    """(exit code, stdout+stderr) or None when not runnable. Never raises, never prompts."""
    try:
        r = subprocess.run(argv, capture_output=True, check=False, timeout=timeout, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.returncode, (r.stdout + b"\n" + r.stderr).decode(errors="replace")


def _version(text: str) -> tuple[int, ...] | None:
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", text)
    return tuple(int(x) for x in m.groups() if x is not None) if m else None


def _dotted(v: tuple[int, ...]) -> str:
    return ".".join(map(str, v))


def os_release_ids(text: str) -> list[str]:
    """`ID` then `ID_LIKE` entries of an os-release file, lowercase."""
    ids: dict[str, str] = {}
    for line in text.splitlines():
        k, _, v = line.partition("=")
        ids[k.strip()] = v.strip().strip("\"'").lower()
    return [i for i in [ids.get("ID", ""), *ids.get("ID_LIKE", "").split()] if i]


def install_hint(cli: Cli, system: str, os_release: str = "") -> str:
    """What to tell the user: the command (win/mac, linux distro) or a link."""
    if system in ("win32", "darwin"):
        argv = cli.install.get(system)
        if argv and shutil.which(argv[0]):
            return " ".join(argv)
        return f"{argv[0] if argv else 'package manager'} not found, see {cli.docs}"
    if system.startswith("linux"):
        for i in os_release_ids(os_release):
            if i in cli.linux:
                return cli.linux[i]
    return f"see {cli.docs}"


def _read_os_release() -> str:
    try:
        return OS_RELEASE.read_text(encoding="utf-8")
    except OSError:
        return ""


def check_git() -> Check:
    res = _run(["git", "--version"])
    if res is None or res[0]:
        return Check("fail", "git not found", f"install git >= {_dotted(MIN_GIT)}")
    v = _version(res[1])
    if v is None or v < MIN_GIT:
        return Check("fail", f"git too old ({res[1].strip()})", f"update git to >= {_dotted(MIN_GIT)}")
    return Check("ok", f"git {_dotted(v)}")


def parse_scopes(text: str) -> set[str] | None:
    """Scopes from `gh auth status` ("Token scopes: 'repo', 'gist'"), None when not listed."""
    m = re.search(r"Token scopes:\s*(.*)", text)
    return set(re.findall(r"[\w:.-]+", m[1])) if m else None


AZ_EXTENSION = "azure-devops"


def _check_az() -> list[Check]:
    """Login and the `azure-devops` extension. Assumed from the Microsoft docs, NOT verified live (no az here):
    `az account show` exits 0 with JSON when logged in, non-zero ("Please run 'az login'") when not;
    `az extension list` prints a JSON array of objects with a "name" key. Anything else -> warn, never raise."""
    out = []
    res = _run(["az", "account", "show", "-o", "json"])
    if res is None:
        out.append(Check("warn", "az account show not runnable"))
    elif res[0]:
        out.append(Check("fail", "az not logged in", CLIS["azure"].login))
    else:
        out.append(Check("ok", "az logged in"))
    res = _run(["az", "extension", "list", "-o", "json"])
    names: set[str] | None = None
    if res is not None and res[0] == 0:
        try:
            names = {e["name"] for e in json.loads(res[1]) if isinstance(e, dict) and isinstance(e.get("name"), str)}
        except (ValueError, TypeError):
            pass
    if names is None:
        out.append(Check("warn", f"az extensions not readable (needed: {AZ_EXTENSION})"))
    elif AZ_EXTENSION in names:
        out.append(Check("ok", f"az extension {AZ_EXTENSION} installed"))
    else:  # only shown, never run
        out.append(Check("fail", f"az extension {AZ_EXTENSION} missing", f"az extension add --name {AZ_EXTENSION}"))
    return out


def check_cli(cli: Cli, system: str | None = None, os_release: str | None = None) -> list[Check]:
    """Installed, logged in, scope. Each Check carries its fix command."""
    system = system or sys.platform
    if not shutil.which(cli.name):
        hint = install_hint(cli, system, _read_os_release() if os_release is None else os_release)
        return [Check("fail", f"{cli.name} not installed", hint, missing=cli)]
    out = [Check("ok", f"{cli.name} installed")]
    if cli.min_version:
        res = _run([cli.name, "--version"])
        v = _version(res[1]) if res else None
        if v is not None and v < cli.min_version:
            out.append(Check("fail", f"{cli.name} too old", f"update {cli.name} to >= {_dotted(cli.min_version)}"))
    if cli.name == "az":
        return out + _check_az()
    res = _run(["gh", "auth", "status"])
    if res is None:
        out.append(Check("warn", "gh auth status not runnable"))
    elif res[0]:
        out.append(Check("fail", "gh not logged in", cli.login))
    else:
        out.append(Check("ok", "gh logged in"))
        scopes = parse_scopes(res[1])
        if cli.scope and (scopes is None or not ({cli.scope, "project"} & scopes)):
            why = "scopes not readable" if scopes is None else f"scope {cli.scope} missing"
            out.append(Check("warn", f"{why} (needed for board status)", cli.scope_cmd))
    return out


def check_config() -> tuple[list[Check], dict, object]:
    """Config checks plus the parsed data (empty when unreadable)."""
    out, repos, local = [], {}, None
    for name, load in (("repos.toml", load_repos), ("local.toml", load_local)):
        try:
            data = load()
        except (OSError, ValueError, TypeError, AttributeError) as e:  # unreadable, TOML error, wrong types
            out.append(Check("fail", f"{name} not readable: {e}", f"fix or delete {name} (kvasir config --path)"))
            continue
        out.append(Check("ok", f"{name} readable"))
        if name == "repos.toml":
            repos = data
        else:
            local = data
    return out, repos, local


def check_platform(url: str, system: str | None = None) -> list[Check]:
    """Platform of a registered repo (normalized URL) and whether its CLI is usable."""
    repo = detect_platform(url if "://" in url else f"https://{url}")
    if repo is None:
        return [Check("ok", f"{url}: no platform recognized (git only)")]
    cli = CLIS[repo.kind]
    if not cli.active:
        return [Check("warn", f"{url}: {repo.kind} not supported yet")]
    if shutil.which(cli.name):
        return [Check("ok", f"{url}: {repo.kind}, {cli.name} available")]
    hint = install_hint(cli, system or sys.platform, _read_os_release())
    return [Check("fail", f"{url}: {repo.kind}, {cli.name} missing", hint, missing=cli)]


def all_checks(system: str | None = None) -> list[Check]:
    out = [check_git(), *check_cli(CLIS["github"], system)]
    cfg, repos, local = check_config()
    out += cfg
    if any((r := detect_platform(f"https://{u}")) and r.kind == "azure" for u in repos):
        out += check_cli(CLIS["azure"], system)  # az only matters when an Azure repo is registered
    for url in repos:
        path = local.paths.get(url) if local else None
        if path and not Path(path).exists():
            out.append(Check("warn", f"{url}: local path missing ({path})", "kvasir setup <path>"))
        out += check_platform(url, system)
    return out


def repo_checks(url: str, system: str | None = None) -> list[Check]:
    """What `setup` shows for a just registered repo: its platform's CLI, nothing else."""
    out = check_platform(url, system)
    repo = detect_platform(f"https://{url}")
    if repo and CLIS[repo.kind].active:
        out = check_cli(CLIS[repo.kind], system) + out
    return out


def install_argv(cli: Cli, system: str) -> list[str] | None:
    """Command kvasir may run itself: winget (Windows), brew (macOS), only if present. Never Linux."""
    argv = cli.install.get(system) if system in ("win32", "darwin") else None
    return argv if argv and shutil.which(argv[0]) else None


def offer_install(cli: Cli, system: str, ask: Callable[[str], bool], echo: Callable[[str], None]) -> bool:
    """Ask (default no), then run the install command. True when it ran successfully."""
    argv = install_argv(cli, system)
    if argv is None or not ask(f"Install {cli.name} now with `{' '.join(argv)}`?"):
        return False
    res = _run(argv, INSTALL_TIMEOUT)
    if res is None:
        echo(f"could not run {argv[0]}")
        return False
    echo(res[1].strip())
    return res[0] == 0


def report(
    checks_fn: Callable[[], list[Check]],
    interactive: bool,
    ask: Callable[[str], bool],
    echo: Callable[[str], None],
    system: str | None = None,
) -> int:
    """Print checks with fixes; with a TTY offer to install a missing CLI, then re-check.
    Returns 1 if any check failed, else 0."""
    system = system or sys.platform
    checks = checks_fn()
    if interactive:
        asked: set[str] = set()
        for c in checks:
            if c.missing and c.missing.active and c.missing.name not in asked:
                asked.add(c.missing.name)
                if offer_install(c.missing, system, ask, echo):
                    checks = checks_fn()
    for c in checks:
        echo(f"{MARK[c.status]} {c.text}" + (f"\n    -> {c.fix}" if c.fix else ""))
    return int(any(c.status == "fail" for c in checks))
