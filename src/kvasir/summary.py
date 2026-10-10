"""AI summary of a Repo (key `s`): input gathering + cache. No Textual; blocking: run in a worker.

Input = README start, recent commits, branches/worktrees, notes. Read via `git show <head>:...`, so
`.env` and other working-tree files are never touched. Cache: `summary_cache.json` in the config dir,
`{repo_url: {head, input_hash, ts, text}}`; a broken file or entry is a cache miss.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from kvasir import llm, notes
from kvasir.config import config_dir
from kvasir.platform.models import Error, ErrorKind, Result
from kvasir.worktrees import RepoView

README_CHARS = 4000
COMMITS = 20
NOTES = 10


@dataclass(frozen=True)
class Entry:
    text: str
    head: str
    input_hash: str
    ts: datetime


def _git(root: Path, *args: str) -> str | None:
    r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=False)
    return r.stdout.decode(errors="replace").strip() if r.returncode == 0 else None


def head_of(root: Path) -> str | None:
    """Commit hash of the default branch (origin/HEAD, else HEAD)."""
    for ref in ("refs/remotes/origin/HEAD", "HEAD"):
        if h := _git(root, "rev-parse", "--verify", "-q", ref):
            return h
    return None


def gather(url: str, root: Path, view: RepoView | None, head: str) -> str:
    parts = [f"Repository: {url}"]
    names = (_git(root, "ls-tree", "--name-only", head) or "").splitlines()
    readme = next((n for n in names if n.lower().startswith("readme")), None)
    if readme and (txt := _git(root, "show", f"{head}:{readme}")):
        parts.append("README (start):\n" + txt[:README_CHARS])
    if log := _git(root, "log", f"-{COMMITS}", "--format=%h %s", head):
        parts.append("Recent commits:\n" + log)
    if view:
        parts.append("Worktrees:\n" + "\n".join(f"{w.branch or 'detached'} {w.subject}" for w in view.worktrees))
        parts.append("Branches:\n" + "\n".join(b.name for b in view.branches))
    mine = [n for n in notes.read_all() if n["url"] == url][-NOTES:]
    if mine:
        parts.append("Notes:\n" + "\n".join(f"{n['branch']}: {n['text']}" for n in mine))
    return "\n\n".join(parts)


def _path() -> Path:
    return config_dir() / "summary_cache.json"


def _load() -> dict:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def cached(url: str) -> Entry | None:
    e = _load().get(url)
    try:
        return Entry(e["text"], e["head"], e["input_hash"], datetime.fromisoformat(e["ts"]))
    except (KeyError, TypeError, ValueError):
        return None


def _store(url: str, e: Entry) -> None:
    data = _load()
    data[url] = {"head": e.head, "input_hash": e.input_hash, "ts": e.ts.isoformat(), "text": e.text}
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".summary_cache.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, p)
    except BaseException:
        os.unlink(tmp)
        raise


def is_stale(url: str, root: Path) -> bool:
    e = cached(url)
    return e is not None and e.head != head_of(root)


def generate(url: str, root: Path, view: RepoView | None, cfg: llm.LlmConfig, force: bool = False) -> Result[Entry]:
    """Summary for the Repo: from cache when head and input are unchanged (unless `force`), else via the LLM."""
    head = head_of(root)
    if head is None:
        return Result(error=Error(ErrorKind.OTHER, f"{root}: no commits", cli="llm"))
    text = gather(url, root, view, head)
    digest = hashlib.sha256(text.encode()).hexdigest()
    old = cached(url)
    if old and not force and old.head == head and old.input_hash == digest:
        return Result(data=old)
    prompt = ("Fasse dieses Git-Repository in 3 bis 5 Sätzen zusammen: Zweck, Stand, woran gerade gearbeitet wird. "
              "Antworte nur mit der Zusammenfassung.\n\n" + text)
    res = llm.complete([{"role": "user", "content": prompt}], cfg, repo=url)
    if not res.ok:
        return Result(error=res.error)
    entry = Entry(res.data.strip(), head, digest, datetime.now(UTC))
    try:
        _store(url, entry)
    except OSError:
        pass  # shown anyway, just not cached
    return Result(data=entry)
