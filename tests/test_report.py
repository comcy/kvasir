import json
import os
import subprocess
from datetime import date, timedelta

import pytest
from typer.testing import CliRunner

from kvasir import daylog, notes
from kvasir.cli import app
from kvasir.config import LocalConfig, RepoConfig, save_local, save_repos

URL = "github.com/o/r"
E = "me@x.org"


def git(cwd, *a, when=None):
    env = {"GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when} if when else {}
    subprocess.run(["git", "-C", str(cwd), *a], check=True, capture_output=True, env={**os.environ, **env})


@pytest.fixture
def repo(make_repo):
    root = make_repo("r")
    git(root, "config", "user.name", "Me")
    git(root, "config", "user.email", E)
    save_repos({URL: RepoConfig()})
    save_local(LocalConfig(paths={URL: str(root)}))
    return root


def commit(root, msg, day, email=E):
    git(root, "-c", f"user.email={email}", "commit", "-q", "--allow-empty", "-m", msg,
        when=f"{day.isoformat()}T12:00:00")


def run(*args):
    r = CliRunner().invoke(app, ["today", *args])
    assert r.exit_code == 0, r.output
    return r.output


def test_commits_of_day_by_configured_author_all_branches(repo):
    d = date.today() - timedelta(days=3)
    commit(repo, "feat: yesterday", d - timedelta(days=1))
    commit(repo, "feat: mine", d)
    commit(repo, "feat: other", d, "other@x.org")
    git(repo, "checkout", "-q", "-b", "side")
    commit(repo, "fix: on side", d)
    git(repo, "checkout", "-q", "main")
    (r,) = json.loads(run("--date", d.isoformat(), "--format", "json"))["repos"]
    assert sorted(c["subject"] for c in r["commits"]) == ["feat: mine", "fix: on side"]
    assert {c["branch"] for c in r["commits"]} == {"main", "side"}
    md = run("--date", d.isoformat())
    assert f"# Bericht {d.isoformat()}" in md and "## github.com/o/r" in md and "feat: mine" in md


def test_empty_day_message(repo):
    assert "Keine Aktivität" in run("--date", "2001-01-01")
    assert json.loads(run("--date", "2001-01-01", "--format", "json"))["repos"] == []


def test_sections_from_log_and_snapshot(repo):
    commit(repo, "feat: today", date.today())
    (repo / "wip.txt").write_text("x")
    notes.add(URL, "main", "Stand: läuft")
    daylog.record({"type": "pr_state", "url": URL, "number": 3, "title": "T", "old": "open", "new": "merged"})
    daylog.record({"type": "worktree_created", "url": URL, "branch": "feat/x"})
    out = run()
    for s in ("### Commits", "feat: today", "### Notizen", "Stand: läuft", "### Statuswechsel",
              "PR #3 T: open -> merged", "### Worktrees", "feat/x: angelegt", "### Uncommittete Arbeit",
              "main: 0 staged, 0 unstaged, 1 untracked"):
        assert s in out
    assert len([e for e in daylog.read(date.today()) if e["type"] == "snapshot"]) == 1


def test_past_day_without_log_and_no_snapshot_written(repo, cfg_dir):
    d = date.today() - timedelta(days=2)
    commit(repo, "feat: old", d)
    assert "feat: old" in run("--date", d.isoformat())
    assert not (cfg_dir / "days").exists()


def test_out_replaces_date_and_stdout_stays_empty(repo, tmp_path):
    d = date.today() - timedelta(days=1)
    commit(repo, "feat: o", d)
    assert run("--date", d.isoformat(), "--out", str(tmp_path / "rep" / "{date}.md")) == ""
    assert "feat: o" in (tmp_path / "rep" / f"{d.isoformat()}.md").read_text(encoding="utf-8")


def test_nothing_written_without_out(repo, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    run("--date", "2001-01-01")
    assert list(tmp_path.glob("*.md")) == []


def test_bad_args():
    assert CliRunner().invoke(app, ["today", "--date", "x"]).exit_code == 2
    assert CliRunner().invoke(app, ["today", "--format", "x"]).exit_code == 2
