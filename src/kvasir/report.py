"""Bericht eines Tages (`kvasir today`): Commits per `git log`, Tageslog-Ereignisse, Snapshot. No Textual."""
from __future__ import annotations

import subprocess
from datetime import date, datetime, time, timedelta
from pathlib import Path

from kvasir import daylog
from kvasir.config import load_local, load_repos
from kvasir.worktrees import read_repo

NOTE_TYPES = ("note", "closing_note")
STATE_TYPES = ("pr_state", "issue_state")
WORKTREE_TYPES = ("worktree_created", "worktree_removed")


def _git(path: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(path), *args], capture_output=True, check=False)
    return r.stdout.decode(errors="replace") if r.returncode == 0 else ""


def commits(path: Path, day: date) -> list[dict]:
    """Commits of the local calendar day on all branches, by the repo's configured git user."""
    since = datetime.combine(day, time.min).astimezone()
    args = ["log", "--all", "--source", f"--since={since.isoformat()}",
            f"--until={(since + timedelta(days=1)).isoformat()}", "--format=%H%x00%ct%x00%S%x00%s"]
    if email := _git(path, "config", "user.email").strip():
        args += ["--fixed-strings", f"--author=<{email}>"]
    out = []
    for line in _git(path, *args).splitlines():
        sha, ts, ref, subject = (line.split("\0") + ["", "", ""])[:4]
        ref = ref.removeprefix("refs/heads/").removeprefix("refs/remotes/")
        out.append({"sha": sha[:8], "time": datetime.fromtimestamp(int(ts)).astimezone().isoformat(timespec="seconds"),
                    "branch": ref, "subject": subject})
    return out


def snapshot_today() -> None:
    """Write today's snapshot (uncommitted work of all registered, locally present repos)."""
    known, repos = load_repos(), {}
    for url, p in load_local().paths.items():
        if url in known and Path(p).is_dir():
            try:
                repos[url] = read_repo(Path(p)).worktrees
            except ValueError:
                pass
    daylog.snapshot(repos)


def build(day: date) -> dict:
    events = daylog.read(day)
    snap = next((e for e in reversed(events) if e["type"] == "snapshot"), {})
    paths = load_local().paths
    urls = list(dict.fromkeys([*load_repos(), *(e["url"] for e in events if e.get("url")),
                               *(w["url"] for w in snap.get("worktrees", []))]))
    repos = []
    for url in urls:
        ev = [e for e in events if e.get("url") == url]
        r = {"url": url,
             "commits": commits(Path(paths[url]), day) if url in paths and Path(paths[url]).is_dir() else [],
             "notes": [e for e in ev if e["type"] in NOTE_TYPES],
             "status_changes": [e for e in ev if e["type"] in STATE_TYPES],
             "worktrees": [e for e in ev if e["type"] in WORKTREE_TYPES],
             "uncommitted": [w for w in snap.get("worktrees", []) if w["url"] == url]}
        if any(v for k, v in r.items() if k != "url"):
            repos.append(r)
    return {"date": day.isoformat(), "repos": repos}


def to_markdown(rep: dict) -> str:
    out = [f"# Bericht {rep['date']}", ""]
    if not rep["repos"]:
        return "\n".join([*out, "Keine Aktivität an diesem Tag.", ""])
    hm = lambda ts: ts[11:16]
    for r in rep["repos"]:
        out += [f"## {r['url']}", ""]
        sections = [
            ("Commits", [f"{hm(c['time'])} `{c['sha']}` {c['subject']}" + (f" ({c['branch']})" if c["branch"] else "")
                         for c in r["commits"]]),
            ("Notizen", [f"{hm(n['ts'])} {n['branch']}: {n['text']}" + (" (Abschluss)" if n["type"] == "closing_note" else "")
                         for n in r["notes"]]),
            ("Statuswechsel", [f"{hm(s['ts'])} {'PR' if s['type'] == 'pr_state' else 'Issue'} #{s['number']} "
                               f"{s.get('title', '')}: {s.get('old') or '-'} -> {s['new']}" for s in r["status_changes"]]),
            ("Worktrees", [f"{hm(w['ts'])} {w['branch']}: "
                           f"{'angelegt' if w['type'] == 'worktree_created' else 'entfernt'}" for w in r["worktrees"]]),
            ("Uncommittete Arbeit", [f"{w['branch']}: {w['staged']} staged, {w['unstaged']} unstaged, "
                                     f"{w['untracked']} untracked" for w in r["uncommitted"]]),
        ]
        for title, lines in sections:
            if lines:
                out += [f"### {title}", "", *[f"- {x}" for x in lines], ""]
    return "\n".join(out)
