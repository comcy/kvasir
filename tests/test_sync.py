import subprocess

import pytest
from conftest import sh

from kvasir.sync import fetch, pull

G = ("git", "-c", "user.name=t", "-c", "user.email=t@t")


def commit(cwd, msg="c"):
    sh(cwd, *G, "commit", "-q", "--allow-empty", "-m", msg)


def out(cwd, *a):
    return subprocess.run(a, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def pair(tmp_path):
    """(remote, clone): clone tracks origin/main."""
    remote, clone = tmp_path / "remote", tmp_path / "clone"
    remote.mkdir()
    sh(remote, "git", "init", "-q", "-b", "main")
    commit(remote, "i")
    sh(tmp_path, "git", "clone", "-q", f"file://{remote}", "clone")
    return remote, clone


def test_fetch_gets_new_commit_and_prunes(pair):
    remote, clone = pair
    sh(remote, "git", "branch", "gone")
    assert fetch(clone) is None
    assert "origin/gone" in out(clone, "git", "branch", "-r")
    commit(remote, "new")
    sh(remote, "git", "branch", "-D", "gone")
    assert fetch(clone) is None
    assert out(clone, "git", "rev-parse", "origin/main") == out(remote, "git", "rev-parse", "main")
    assert "origin/gone" not in out(clone, "git", "branch", "-r")
    assert out(clone, "git", "rev-parse", "HEAD") != out(clone, "git", "rev-parse", "origin/main")  # no auto pull


def test_fetch_invalid_remote_returns_error(tmp_path):
    sh(tmp_path, "git", "init", "-q", "-b", "main")
    sh(tmp_path, "git", "remote", "add", "origin", str(tmp_path / "nope"))
    assert fetch(tmp_path)
    assert fetch(tmp_path / "missing-dir")


def test_pull_ff(pair):
    remote, clone = pair
    commit(remote, "new")
    sh(clone, "git", "fetch", "-q")
    ok, msg = pull(clone)
    assert ok and "pulled 1" in msg
    assert out(clone, "git", "rev-parse", "HEAD") == out(remote, "git", "rev-parse", "main")
    assert pull(clone) == (True, "already up to date")


def test_pull_refuses_dirty(pair):
    remote, clone = pair
    commit(remote, "new")
    (clone / "f0").write_text("x")
    sh(clone, "git", "add", "f0")
    sh(clone, "git", "fetch", "-q")
    head = out(clone, "git", "rev-parse", "HEAD")
    ok, msg = pull(clone)
    assert not ok and "uncommitted" in msg
    assert out(clone, "git", "rev-parse", "HEAD") == head


def test_pull_refuses_diverged(pair):
    remote, clone = pair
    commit(remote, "r")
    commit(clone, "l")
    sh(clone, "git", "fetch", "-q")
    head = out(clone, "git", "rev-parse", "HEAD")
    ok, msg = pull(clone)
    assert not ok and "diverged" in msg
    assert out(clone, "git", "rev-parse", "HEAD") == head


def test_pull_no_upstream(pair):
    _, clone = pair
    sh(clone, "git", "checkout", "-q", "-b", "local")
    ok, msg = pull(clone)
    assert not ok and "upstream" in msg
