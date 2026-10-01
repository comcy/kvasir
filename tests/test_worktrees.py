import shutil
import time

import pytest
from conftest import sh

from kvasir.worktrees import read_repo

G = ("git", "-c", "user.name=t", "-c", "user.email=t@t")


def commit(cwd, msg="c"):
    sh(cwd, *G, "commit", "-q", "--allow-empty", "-m", msg)


@pytest.fixture
def bare(make_repo):
    root = make_repo("b", bare_layout=True)
    sh(root, "git", "worktree", "add", "-q", "main", "main")
    return root


def test_not_a_repo(tmp_path):
    with pytest.raises(ValueError):
        read_repo(tmp_path)


def test_normal_clone(make_repo):
    root = make_repo()
    commit(root, "first")
    sh(root, "git", "branch", "other")
    v = read_repo(root)
    assert [w.branch for w in v.worktrees] == ["main"]
    assert v.worktrees[0].subject == "first"
    assert v.worktrees[0].ahead is None and v.worktrees[0].behind is None
    assert [(b.name, b.remote) for b in v.branches] == [("other", False)]


def test_no_commits(make_repo):
    w = read_repo(make_repo()).worktrees[0]
    assert w.broken is None and w.commit_ts is None and w.last_active_ts is None


def test_bare_layout_hides_bare_entry(bare):
    v = read_repo(bare)
    assert [w.path.name for w in v.worktrees] == ["main"]
    assert v.worktrees[0].subject == "i"


def test_counts_separate_and_special_chars(bare):
    wt = bare / "main"
    (wt / "a.txt").write_text("1")
    (wt / "b c.txt").write_text("1")
    sh(wt, "git", "add", "a.txt", "b c.txt")
    sh(wt, *G, "commit", "-q", "-m", "files")
    (wt / "a.txt").write_text("2")
    sh(wt, "git", "add", "a.txt")             # staged
    (wt / "b c.txt").write_text("2")          # unstaged
    (wt / "new").mkdir()
    (wt / "new" / "f").write_text("x")        # untracked, counted per file
    (wt / "ä x.txt").write_text("x")          # untracked, special chars
    (wt / "x\ny.txt").write_text("x")         # untracked, newline in name
    w = read_repo(bare).worktrees[0]
    assert (w.staged, w.unstaged, w.untracked) == (1, 1, 3)


def test_rename_counts_once(bare):
    wt = bare / "main"
    (wt / "a.txt").write_text("1")
    sh(wt, "git", "add", "a.txt")
    sh(wt, *G, "commit", "-q", "-m", "a")
    sh(wt, "git", "mv", "a.txt", "b.txt")
    w = read_repo(bare).worktrees[0]
    assert (w.staged, w.unstaged, w.untracked) == (1, 0, 0)


def test_last_active_uses_newer_uncommitted_file(bare):
    wt = bare / "main"
    (wt / "f").write_text("x")
    w = read_repo(bare).worktrees[0]
    assert w.last_active_ts >= w.commit_ts
    assert w.last_active_ts >= int(time.time()) - 5
    (wt / "f").unlink()
    w = read_repo(bare).worktrees[0]
    assert w.last_active_ts == w.commit_ts


def test_ahead_behind(make_repo, tmp_path):
    up = make_repo("up", bare_layout=True)
    sh(tmp_path, "git", "clone", "-q", str(up / ".bare"), "clone")
    clone = tmp_path / "clone"
    commit(clone, "local")
    w = read_repo(clone).worktrees[0]
    assert (w.ahead, w.behind) == (1, 0)


def test_branches_without_worktree_local_and_remote(bare):
    sh(bare, "git", "branch", "local-only", "main")
    sh(bare, "git", "update-ref", "refs/remotes/origin/main", "main")
    sh(bare, "git", "update-ref", "refs/remotes/origin/feat/x", "main")
    sh(bare, "git", "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
    got = {(b.name, b.remote) for b in read_repo(bare).branches}
    assert got == {("local-only", False), ("origin/feat/x", True)}


def test_detached(bare):
    sh(bare, "git", "worktree", "add", "-q", "--detach", "det", "main")
    w = {w.path.name: w for w in read_repo(bare).worktrees}["det"]
    assert w.branch is None and w.broken is None


def test_broken_worktree_does_not_abort(bare):
    sh(bare, "git", "worktree", "add", "-q", "-b", "gone", "gone")
    shutil.rmtree(bare / "gone")
    ws = {w.path.name: w for w in read_repo(bare).worktrees}
    assert ws["gone"].broken and ws["gone"].branch == "gone"
    assert ws["main"].broken is None
