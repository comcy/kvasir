"""LLM suggestions for a commit message / a note: deterministic input, text out, fixed action after the
user confirmed. No Textual, no agent. `.env` files never leave the machine (pathspec exclude)."""
from __future__ import annotations

import subprocess
from datetime import date
from pathlib import Path

from kvasir import daylog
from kvasir.ask import EXCLUDE

TIMEOUT = 30  # seconds per git call
MAX_DIFF = 20000  # characters sent to the model
COMMIT_SYSTEM = (
    "Write a Conventional Commit message (type(scope): subject, imperative, max 72 characters) for the staged "
    "diff below. Answer with the single subject line only, no quotes, no explanation."
)
NOTE_SYSTEM = (
    "Write a short note (1-3 sentences) on the state of this branch for the author's own work log, based on "
    "today's activity and the uncommitted diff below. Answer with the note text only."
)


def _git(path: Path, *args: str) -> tuple[int, str]:
    try:
        r = subprocess.run(["git", "-C", str(path), *args], capture_output=True, timeout=TIMEOUT, check=False)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)
    return r.returncode, (r.stdout if r.returncode == 0 else r.stderr + r.stdout).decode(errors="replace")


def staged_diff(path: Path) -> str:
    rc, out = _git(path, "diff", "--staged", "--no-color", "--", ".", *EXCLUDE)
    return out[:MAX_DIFF] if rc == 0 else ""


def head_diff(path: Path) -> str:
    rc, out = _git(path, "diff", "HEAD", "--no-color", "--", ".", *EXCLUDE)
    return out[:MAX_DIFF] if rc == 0 else ""


def commit_messages(diff: str) -> list[dict[str, str]]:
    return [{"role": "system", "content": COMMIT_SYSTEM}, {"role": "user", "content": diff}]


def note_messages(url: str, branch: str, diff: str) -> list[dict[str, str]] | None:
    """None = nothing to base a note on (no day log entries for this branch, no diff)."""
    day = [f"{e['ts']} {e['type']} " + " ".join(f"{k}={v}" for k, v in e.items() if k not in ("ts", "type"))
           for e in daylog.read(date.today())
           if e["type"] != "snapshot" and e.get("url") == url and e.get("branch") in (None, branch)]
    if not day and not diff:
        return None
    return [{"role": "system", "content": NOTE_SYSTEM},
            {"role": "user", "content": f"## Day log ({url}, {branch})\n" + "\n".join(day) + f"\n\n## Diff\n{diff}"}]


def one_line(text: str) -> str:
    """Model answers may carry fences/quotes/body: keep the first real line."""
    lines = [ln.strip().strip("`\"'") for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("```")]
    return lines[0] if lines else ""


def commit(path: Path, message: str) -> tuple[bool, str]:
    """`git commit -m` in the Worktree: author from git config, hooks run (never --no-verify/--amend)."""
    rc, out = _git(path, "commit", "-m", message)
    return rc == 0, out.strip()
