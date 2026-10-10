"""LLM client: `[llm]` in local.toml, two providers. Never raises, stores no token (only an env variable name).

- openai:  OpenAI-compatible chat API (Ollama /v1, vLLM, LM Studio, llama.cpp server). base_url, model, api_key_env
- command: argv list, prompt on stdin, answer on stdout (e.g. ["claude", "-p"]); kvasir never sees credentials
Blocking: run in a worker.
"""
from __future__ import annotations

import ipaddress
import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from urllib.parse import urlparse

from kvasir.config import RepoConfig, load_local, load_repos, save_local
from kvasir.platform.models import Error, ErrorKind, Result

TIMEOUT = 120  # seconds, default for a completion
PROBE_TIMEOUT = 10  # seconds, doctor reachability check


@dataclass
class LlmConfig:
    provider: str  # "openai" | "command"
    base_url: str = ""
    model: str = ""
    api_key_env: str | None = None
    command: list[str] = field(default_factory=list)
    timeout: int = TIMEOUT
    confirmed: list[str] = field(default_factory=list)  # targets the user agreed to send data to


def parse(raw: dict) -> LlmConfig:
    """Validate the raw [llm] table. ValueError with a readable message."""
    provider = raw.get("provider")
    if provider == "openai":
        base_url, model = raw.get("base_url"), raw.get("model")
        if not isinstance(base_url, str) or urlparse(base_url).scheme not in ("http", "https"):
            raise ValueError("base_url must be an http(s) URL")
        if not isinstance(model, str) or not model:
            raise ValueError("model is required")
        cfg = LlmConfig("openai", base_url=base_url.rstrip("/"), model=model, api_key_env=raw.get("api_key_env"))
    elif provider == "command":
        cmd = raw.get("command")
        if not isinstance(cmd, list) or not cmd or not all(isinstance(a, str) and a for a in cmd):
            raise ValueError("command must be a non-empty list of strings")
        cfg = LlmConfig("command", command=list(cmd))
    else:
        raise ValueError('provider must be "openai" or "command"')
    if cfg.api_key_env is not None and not isinstance(cfg.api_key_env, str):
        raise ValueError("api_key_env must be the NAME of an env variable")
    t = raw.get("timeout", TIMEOUT)
    if not isinstance(t, int) or isinstance(t, bool) or t < 1:
        raise ValueError("timeout must be a positive number of seconds")
    cfg.timeout = t
    cfg.confirmed = [str(c) for c in raw.get("confirmed", [])]
    return cfg


def load() -> LlmConfig | None:
    """Config from local.toml; None = LLM functions disabled. ValueError when [llm] is invalid."""
    raw = load_local().llm
    return parse(raw) if raw else None


def target(cfg: LlmConfig) -> str:
    """Where data goes: host[:port] of base_url, or the command line."""
    return urlparse(cfg.base_url).netloc if cfg.provider == "openai" else " ".join(cfg.command)


def is_local(cfg: LlmConfig) -> bool:
    """localhost / loopback / private network. A `command` is never local (it may call out)."""
    if cfg.provider != "openai":
        return False
    host = urlparse(cfg.base_url).hostname or ""
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private or ip.is_link_local


def needs_confirmation(cfg: LlmConfig) -> bool:
    return not is_local(cfg) and target(cfg) not in cfg.confirmed


def confirm(cfg: LlmConfig) -> None:
    """Remember the user's yes in local.toml ([llm] confirmed)."""
    t = target(cfg)
    if t in cfg.confirmed:
        return
    local = load_local()
    local.llm["confirmed"] = [*local.llm.get("confirmed", []), t]
    save_local(local)
    cfg.confirmed.append(t)


def repo_enabled(url: str, repos: dict[str, RepoConfig] | None = None) -> bool:
    """False when the repo opted out (repos.toml `llm = false`). Unknown repo: enabled."""
    repos = load_repos() if repos is None else repos
    return repos[url].llm if url in repos else True


def _err(kind: ErrorKind, msg: str) -> Result:
    return Result(error=Error(kind, msg, cli="llm"))


def _open(cfg: LlmConfig, req: urllib.request.Request, timeout: int) -> Result[bytes]:
    handlers = [urllib.request.ProxyHandler({})] if is_local(cfg) else []  # local endpoints: no env proxy
    t = target(cfg)
    try:
        with urllib.request.build_opener(*handlers).open(req, timeout=timeout) as r:
            return Result(data=r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:300]
        if e.code in (401, 403):
            return _err(ErrorKind.NOT_LOGGED_IN, f"{t}: HTTP {e.code}, check api_key_env")
        if e.code == 404 and "model" in body.lower():
            return _err(ErrorKind.OTHER, f"model not found at {t}: {body}")
        return _err(ErrorKind.OTHER, f"{t}: HTTP {e.code} {body}")
    except urllib.error.URLError as e:
        if isinstance(e.reason, TimeoutError):
            return _err(ErrorKind.NETWORK, f"{t} timed out after {timeout}s")
        return _err(ErrorKind.NETWORK, f"{t} not reachable: {e.reason}")
    except TimeoutError:
        return _err(ErrorKind.NETWORK, f"{t} timed out after {timeout}s")
    except OSError as e:
        return _err(ErrorKind.NETWORK, f"{t} not reachable: {e}")


def _headers(cfg: LlmConfig) -> dict[str, str]:
    h = {"Content-Type": "application/json"}
    if cfg.api_key_env and (key := os.environ.get(cfg.api_key_env)):
        h["Authorization"] = f"Bearer {key}"
    return h


def _json(res: Result[bytes]) -> Result:
    if not res.ok:
        return res
    try:
        return Result(data=json.loads(res.data))
    except ValueError as e:
        return _err(ErrorKind.OTHER, f"unparsable answer: {e}")


def _run_command(cfg: LlmConfig, stdin: bytes) -> Result[str]:
    name = cfg.command[0]
    try:
        r = subprocess.run(cfg.command, input=stdin, capture_output=True, check=False, timeout=cfg.timeout)
    except FileNotFoundError:
        return _err(ErrorKind.MISSING_CLI, f"{name} not found")
    except subprocess.TimeoutExpired:
        return _err(ErrorKind.NETWORK, f"{name} timed out after {cfg.timeout}s")
    except OSError as e:
        return _err(ErrorKind.OTHER, str(e))
    if r.returncode:
        msg = r.stderr.decode(errors="replace").strip()
        return _err(ErrorKind.OTHER, msg or f"{name} exited with {r.returncode}")
    return Result(data=r.stdout.decode(errors="replace").strip())


def complete(messages: list[dict[str, str]], cfg: LlmConfig | None = None, repo: str | None = None) -> Result[str]:
    """Answer text for chat `messages` ([{"role", "content"}]) or an Error. Never raises.
    Refuses without [llm], for an opted-out `repo` (normalized URL) and for an unconfirmed remote target."""
    try:
        cfg = cfg or load()
        if cfg is None:
            return _err(ErrorKind.OTHER, "no [llm] configured in local.toml")
        if repo is not None and not repo_enabled(repo):
            return _err(ErrorKind.OTHER, f"{repo} opted out (repos.toml llm = false)")
    except (OSError, ValueError, TypeError, AttributeError) as e:  # unreadable/invalid config files
        return _err(ErrorKind.OTHER, f"config invalid: {e}")
    if needs_confirmation(cfg):
        return _err(ErrorKind.OTHER, f"data would go to {target(cfg)}: not confirmed yet")
    if cfg.provider == "command":
        return _run_command(cfg, "\n\n".join(m["content"] for m in messages).encode())
    body = json.dumps({"model": cfg.model, "messages": messages, "stream": False}).encode()
    req = urllib.request.Request(cfg.base_url + "/chat/completions", body, _headers(cfg), method="POST")
    res = _json(_open(cfg, req, cfg.timeout))
    if not res.ok:
        return res
    try:
        return Result(data=res.data["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError):
        return _err(ErrorKind.OTHER, "unexpected answer (no choices[0].message.content)")


def probe(cfg: LlmConfig) -> Result:
    """Reachability for doctor, sends no user data. openai: GET /models -> list of model ids;
    command: the executable is on PATH (data = None)."""
    if cfg.provider == "command":
        if shutil.which(cfg.command[0]):
            return Result()
        return _err(ErrorKind.MISSING_CLI, f"{cfg.command[0]} not found in PATH")
    res = _json(_open(cfg, urllib.request.Request(cfg.base_url + "/models", headers=_headers(cfg)), PROBE_TIMEOUT))
    if not res.ok:
        return res
    try:
        return Result(data=[m["id"] for m in res.data["data"]])
    except (KeyError, TypeError):
        return _err(ErrorKind.OTHER, "unexpected /models answer")


def model_listed(model: str, ids: list[str]) -> bool:
    """Ollama lists "llama3:latest" for model "llama3"."""
    return any(i == model or i.startswith(model + ":") for i in ids)
