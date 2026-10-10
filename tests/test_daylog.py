import json
import os
import stat
import sys
from datetime import date
from pathlib import Path

import pytest

from kvasir import daylog, notes
from kvasir.platform import PullRequest, Result, WorkItem, cache
from kvasir.tui import platform_data
from kvasir.worktrees import Worktree

URL = "github.com/o/r"


def today() -> date:
    return date.today()


def types() -> list[str]:
    return [e["type"] for e in daylog.read(today())]


def test_record_and_read_in_config_dir(cfg_dir):
    daylog.record({"type": "worktree_created", "url": URL, "branch": "feat/x"})
    assert (cfg_dir / "days" / f"{today().isoformat()}.ndjson").exists()
    (e,) = daylog.read(today())
    assert e["type"] == "worktree_created" and e["branch"] == "feat/x"
    assert e["ts"][:10] == today().isoformat()


def test_read_skips_broken_lines(cfg_dir):
    daylog.record({"type": "note", "url": URL, "branch": "b", "text": "t"})
    f = cfg_dir / "days" / f"{today().isoformat()}.ndjson"
    with f.open("a") as fh:
        fh.write("{broken\n[1]\n" + json.dumps({"no": "type"}) + "\n")
    daylog.record({"type": "worktree_removed", "url": URL, "branch": "b"})
    assert types() == ["note", "worktree_removed"]


def test_read_missing_day_is_empty():
    assert daylog.read(date(2001, 1, 1)) == []


def test_events_without_duplicates():
    ev = {"type": "pr_state", "url": URL, "number": 1, "old": "open", "new": "merged"}
    daylog.record(ev)
    daylog.record(ev)
    assert types() == ["pr_state"]
    daylog.record({**ev, "number": 2})
    daylog.record(ev)  # not the last event any more: logged again
    assert len(daylog.read(today())) == 3


def wt(branch, staged=0, unstaged=0, untracked=0, ts=1_700_000_000):
    return Worktree(path=Path("/x") / branch, branch=branch, staged=staged, unstaged=unstaged,
                    untracked=untracked, last_active_ts=ts)


def test_snapshot_idempotent_and_replaces_last():
    daylog.record({"type": "note", "url": URL, "branch": "b", "text": "t"})
    daylog.snapshot({URL: [wt("a", staged=1), wt("clean")]})
    daylog.snapshot({URL: [wt("a", staged=1), wt("clean")]})
    assert types() == ["note", "snapshot"]
    daylog.snapshot({URL: [wt("a", unstaged=2), wt("b", untracked=1)]})
    snaps = [e for e in daylog.read(today()) if e["type"] == "snapshot"]
    assert len(snaps) == 1
    assert [w["branch"] for w in snaps[0]["worktrees"]] == ["a", "b"]  # clean worktrees left out
    assert snaps[0]["worktrees"][0]["unstaged"] == 2 and snaps[0]["worktrees"][0]["last_active"]
    daylog.record({"type": "worktree_removed", "url": URL, "branch": "a"})
    assert types() == ["note", "snapshot", "worktree_removed"]


def test_notes_are_logged():
    notes.add(URL, "feat/x", "stand", "note")
    notes.add(URL, "feat/x", "fertig", "closing")
    es = daylog.read(today())
    assert [(e["type"], e["text"]) for e in es] == [("note", "stand"), ("closing_note", "fertig")]


def pr(n, state):
    return PullRequest(number=n, title=f"t{n}", state=state, url="u", author="a", branch=f"b{n}")


class Prov:
    def __init__(self, prs, item=None):
        self.prs, self.item = prs, item

    def pull_requests(self, limit):
        return Result(data=self.prs)

    def pipeline_runs(self, days, limit):
        return Result(data=[])

    def work_item(self, n):
        return Result(data=self.item)


def test_platform_refresh_detects_status_changes():
    cache.write(URL, "pull_requests", [pr(1, "open"), pr(2, "open")])
    cache.write(URL, "work_item:5", [WorkItem(5, "i", "open", "u")])
    new = Prov([pr(1, "merged"), pr(2, "open"), pr(3, "draft")], WorkItem(5, "i", "closed", "u"))
    platform_data.refresh(URL, ["{type}/{id}-{slug}"], ["feat/5-x"], new)
    got = {(e["type"], e["number"], e["old"], e["new"]) for e in daylog.read(today())}
    assert got == {("pr_state", 1, "open", "merged"), ("pr_state", 3, None, "draft"),
                   ("issue_state", 5, "open", "closed")}
    platform_data.refresh(URL, ["{type}/{id}-{slug}"], ["feat/5-x"], new)  # no change vs. cache now
    assert len(daylog.read(today())) == 3


def test_platform_refresh_without_cache_logs_nothing():
    platform_data.refresh(URL, ["{type}/{slug}"], [], Prov([pr(1, "merged")]))
    assert daylog.read(today()) == []


@pytest.mark.skipif(sys.platform == "win32" or (hasattr(os, "geteuid") and os.geteuid() == 0),
                    reason="needs POSIX permissions, non-root")
def test_read_only_dir_does_not_break_actions(cfg_dir):
    cfg_dir.mkdir()
    cfg_dir.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        daylog.record({"type": "note", "url": URL})
        daylog.snapshot({URL: [wt("a", staged=1)]})
    finally:
        cfg_dir.chmod(stat.S_IRWXU)
    assert daylog.read(today()) == []


def test_write_error_in_notes_add_keeps_note(monkeypatch):
    def boom(*a, **k):
        raise OSError("read-only")
    monkeypatch.setattr(daylog, "_path", boom)
    notes.add(URL, "b", "t")  # must not raise
    assert notes.latest(URL, "b")["text"] == "t"
