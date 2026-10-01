import subprocess

import pytest
from conftest import sh

from kvasir.new_worktree import NewWorktreeError, add_worktree, default_branch

G = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]


@pytest.fixture
def repo(make_repo):
    root = make_repo("r", bare_layout=True)
    sh(root, "git", "config", "remote.origin.fetch", "+refs/heads/*:refs/remotes/origin/*")
    sh(root, "git", "worktree", "add", "-q", "main", "main")
    return root


def out(root, *a):
    return subprocess.run(["git", "-C", str(root), *a], capture_output=True, text=True, check=True).stdout.strip()


def branches(root):
    return out(root, "branch", "--format=%(refname:short)").split()


def test_default_branch(repo):
    assert default_branch(repo) == "main"


def test_existing_local_branch(repo):
    sh(repo, "git", "branch", "feat/x", "main")
    p = add_worktree(repo, "feat/x")
    assert p == repo / "feat" / "x" and (p / ".git").exists()


def test_remote_only_branch_tracks(repo):
    sh(repo, "git", "update-ref", "refs/remotes/origin/feat/r", "main")
    p = add_worktree(repo, "origin/feat/r")
    assert p == repo / "feat" / "r" and "feat/r" in branches(repo)
    assert out(p, "rev-parse", "--abbrev-ref", "@{u}") == "origin/feat/r"


def test_new_branch_from_base(repo):
    sh(repo / "main", *G, "commit", "-q", "--allow-empty", "-m", "second")
    sh(repo, "git", "branch", "dev", "HEAD~1")
    p = add_worktree(repo, "fix/new", base="main")
    assert p == repo / "fix" / "new"
    assert out(p, "rev-parse", "HEAD") == out(repo / "main", "rev-parse", "HEAD")
    assert out(add_worktree(repo, "fix/old", base="dev"), "rev-parse", "HEAD") != out(p, "rev-parse", "HEAD")


@pytest.mark.parametrize("kw, msg", [
    ({"branch": "main", "base": "main"}, "already exists"),
    ({"branch": "nope"}, "not found"),
    ({"branch": "fix/x", "base": "nope"}, "base branch"),
    ({"branch": "bad..name", "base": "main"}, "invalid"),
])
def test_errors_leave_nothing(repo, kw, msg):
    before = branches(repo)
    with pytest.raises(NewWorktreeError, match=msg):
        add_worktree(repo, **kw)
    assert branches(repo) == before
    assert not (repo / "fix").exists()


def test_checked_out_elsewhere(repo):
    with pytest.raises(NewWorktreeError, match="already checked out"):
        add_worktree(repo, "main")


def test_directory_exists(repo):
    (repo / "fix" / "d").mkdir(parents=True)
    with pytest.raises(NewWorktreeError, match="directory already exists"):
        add_worktree(repo, "fix/d", base="main")
    assert "fix/d" not in branches(repo)


def test_normal_clone_rejected(make_repo):
    with pytest.raises(NewWorktreeError, match="Bare-Layout"):
        add_worktree(make_repo("n"), "x", base="main")
