"""Context for the prompt window: deterministic repo search + notes + day log. No Textual.

Search = `git grep` (committed HEAD tree) and `git log --grep/-S` per registered repo, capped.
The result goes to the LLM as context; the model does not call tools. `.env` files are never searched.
"""
from __future__ import annotations

import re
import subprocess
from datetime import date
from pathlib import Path

from kvasir import daylog, notes
from kvasir.config import RepoConfig, load_local, load_repos
from kvasir.llm import repo_enabled

TIMEOUT = 15  # seconds per git call
MAX_TERMS = 4
MAX_GREP = 15  # lines per repo
MAX_LOG = 8  # commits per repo and term
MAX_LINE = 200
MAX_NOTES = 20
MAX_DAY = 30
EXCLUDE = (":(exclude,glob)**/.env", ":(exclude,glob)**/.env.*", ":(exclude,glob)**/*.env")
STOP = frozenset("""the and for with that this was were what which where when how who from into about have has
der die das und mit für von dem den ein eine einer ist war wie wer wo wann welche welchem welcher welchen
nicht auch aber oder noch mal hat haben wurde repo repos""".split())  # noqa: SIM905
SYSTEM = (
    "You answer questions about the user's own software repos, notes and day log. Use only the context below. "
    "When you refer to something, name the repo, the file (with line) or the commit hash. "
    "If the context does not contain the answer, say so."
)


def terms(question: str) -> list[str]:
    """Longest distinct words (>=3 chars) minus stop words. ponytail: no stemming, add if recall is poor."""
    words = {w.lower() for w in re.findall(r"\w{3,}", question)} - STOP
    return sorted(words, key=lambda w: (-len(w), w))[:MAX_TERMS]


def _git(root: Path, *args: str) -> list[str]:
    try:
        r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, timeout=TIMEOUT, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return []
    return r.stdout.decode(errors="replace").splitlines() if r.returncode in (0, 1) else []


def _is_env(path: str) -> bool:
    n = path.rsplit("/", 1)[-1]
    return n == ".env" or n.startswith(".env.") or n.endswith(".env")


def search_repo(root: Path, words: list[str]) -> list[str]:
    """Hit lines for one repo: `file:line:text` and `commit <hash> <subject>`."""
    if not words:
        return []
    pat = [a for w in words for a in ("-e", w)]
    out = []
    for line in _git(root, "grep", "-I", "-i", "-F", "-n", "--no-color", *pat, "HEAD", "--", *EXCLUDE):
        path = line.partition(":")[2].partition(":")[0]  # HEAD:<path>:<n>:<text>
        if not _is_env(path):
            out.append(line.removeprefix("HEAD:")[:MAX_LINE])
        if len(out) >= MAX_GREP:
            break
    seen: set[str] = set()
    for w in words:  # message hits and content changes (pickaxe)
        for flag in (f"--grep={w}", f"-S{w}"):
            for line in _git(root, "log", "--all", "-i", "-F", flag, f"-n{MAX_LOG}", "--format=commit %h %s"):
                if line not in seen:
                    seen.add(line)
                    out.append(line[:MAX_LINE])
    return out


def search(question: str, paths: dict[str, str] | None = None,
           repos: dict[str, RepoConfig] | None = None) -> dict[str, list[str]]:
    """repo URL -> hit lines, only repos with a local path and `llm` not opted out."""
    paths = load_local().paths if paths is None else paths
    repos = load_repos() if repos is None else repos
    words = terms(question)
    res = {}
    for url, p in sorted(paths.items()):
        if repo_enabled(url, repos) and Path(p).is_dir() and (hits := search_repo(Path(p), words)):
            res[url] = hits
    return res


def _day_lines(repos: dict[str, RepoConfig]) -> list[str]:
    out = []
    for e in daylog.read(date.today()):
        if e["type"] == "snapshot" or ("url" in e and not repo_enabled(e["url"], repos)):
            continue
        out.append(f"{e['ts']} {e['type']} " + " ".join(f"{k}={v}" for k, v in e.items() if k not in ("ts", "type")))
    return out[-MAX_DAY:]


def context(question: str) -> str:
    repos = load_repos()
    parts = []
    for url, hits in search(question, repos=repos).items():
        parts.append(f"## Search hits in {url}\n" + "\n".join(hits))
    ns = [n for n in notes.read_all() if repo_enabled(n["url"], repos)][-MAX_NOTES:]
    if ns:
        parts.append("## Notes\n" + "\n".join(f"{n['url']} {n['branch']} ({n['ts'][:10]}): {n['text']}" for n in ns))
    if day := _day_lines(repos):
        parts.append("## Today\n" + "\n".join(day))
    return "\n\n".join(parts) or "(no context found)"


def messages(question: str, history: list[dict[str, str]]) -> list[dict[str, str]]:
    return [{"role": "system", "content": f"{SYSTEM}\n\n{context(question)}"}, *history,
            {"role": "user", "content": question}]
