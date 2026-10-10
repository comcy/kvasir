"""Notes per Worktree/branch: append-only `notes.ndjson` in the config dir. No Textual."""
from __future__ import annotations

import json
from datetime import UTC, datetime

from kvasir import daylog
from kvasir.config import config_dir

KINDS = ("note", "closing")


def add(url: str, branch: str, text: str, kind: str = "note") -> None:
    """Append one line (one write call, so concurrent appends do not interleave)."""
    rec = {"url": url, "branch": branch, "ts": datetime.now(UTC).isoformat(), "text": text, "kind": kind}
    p = config_dir() / "notes.ndjson"
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    daylog.record({"type": "closing_note" if kind == "closing" else "note", "url": url, "branch": branch, "text": text})


def read_all() -> list[dict]:
    """All valid notes in file order; broken or foreign lines are skipped."""
    p = config_dir() / "notes.ndjson"
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if (isinstance(r, dict) and all(isinstance(r.get(k), str) for k in ("url", "branch", "ts", "text"))
                and r.get("kind", "note") in KINDS):
            out.append({**r, "kind": r.get("kind", "note")})
    return out


def latest_by_branch(url: str) -> dict[str, dict]:
    """Newest note per branch of a repo (later line wins; file order = time order)."""
    return {r["branch"]: r for r in read_all() if r["url"] == url}


def latest(url: str, branch: str) -> dict | None:
    return latest_by_branch(url).get(branch)
