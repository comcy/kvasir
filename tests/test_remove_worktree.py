import asyncio
import subprocess

import pytest

from kvasir import remove_worktree as rw
from kvasir.tui.remove_screen import RemoveScreen
from kvasir.worktrees import read_repo


def sh(cwd, *a):
    subprocess.run(a, cwd=cwd, check=True, capture_output=True)


def branches(root):
    return subprocess.run(["git", "-C", str(root), "branch"], capture_output=True, text=True, check=True).stdout


G = ("git", "-c", "user.name=t", "-c", "user.email=t@t")


@pytest.fixture
def repo(make_repo, tmp_path):
    root = make_repo("r", bare_layout=True)
    sh(root, "git", "worktree", "add", "-q", "main", "main")
    sh(root, "git", "update-ref", "refs/remotes/origin/main", "main")  # main is "on the remote"
    sh(root, "git", "worktree", "add", "-q", "-b", "feat/x", "feat-x", "main")
    return root


def wt(root, name):
    return next(w for w in read_repo(root).worktrees if w.path.name == name)


def commit(path):
    sh(path, *G, "commit", "-q", "--allow-empty", "-m", "c")


def test_clean_merged(repo, tmp_path):
    r = rw.assess(wt(repo, "feat-x"), repo, cwd=tmp_path)
    assert not r.dangerous and not r.blocked
    rw.remove(repo, repo / "feat-x")
    assert not (repo / "feat-x").exists()
    assert rw.is_merged(repo, "feat/x", "main")
    rw.delete_branch(repo, "feat/x")
    assert "feat/x" not in branches(repo)


def test_dirty(repo, tmp_path):
    (repo / "feat-x" / "f").write_text("x")
    r = rw.assess(wt(repo, "feat-x"), repo, cwd=tmp_path)
    assert r.untracked == 1 and r.dangerous
    with pytest.raises(RuntimeError):
        rw.remove(repo, repo / "feat-x")
    rw.remove(repo, repo / "feat-x", force=True)
    assert not (repo / "feat-x").exists()


def test_unpushed_no_upstream_and_unmerged(repo, tmp_path):
    commit(repo / "feat-x")
    r = rw.assess(wt(repo, "feat-x"), repo, cwd=tmp_path)
    assert r.unpushed == 1 and r.dangerous
    assert not rw.is_merged(repo, "feat/x", "main")
    # once the commit is on some remote branch it is safe
    sh(repo, "git", "update-ref", "refs/remotes/origin/feat/x", "feat/x")
    assert rw.assess(wt(repo, "feat-x"), repo, cwd=tmp_path).unpushed == 0


def test_protected(repo, tmp_path):
    assert rw.assess(wt(repo, "main"), repo, cwd=tmp_path).blocked
    assert rw.assess(wt(repo, "feat-x"), repo, cwd=repo / "feat-x").blocked


def test_prune(repo):
    import shutil
    shutil.rmtree(repo / "feat-x")
    assert wt(repo, "feat-x").broken == "directory missing"
    rw.prune(repo)
    assert all(w.path.name != "feat-x" for w in read_repo(repo).worktrees)


def _run(repo, w, keys):
    async def go():
        from textual.app import App

        class A(App):
            pass

        app = A()
        async with app.run_test() as pilot:
            await app.push_screen(RemoveScreen(repo, w))
            await pilot.pause()
            for k in keys:
                await pilot.press(*k) if isinstance(k, list) else await pilot.press(k)
                await pilot.pause()
    asyncio.run(go())


def test_screen_clean_merged_removes_and_deletes_branch(repo):
    _run(repo, wt(repo, "feat-x"), ["enter", "y"])
    assert not (repo / "feat-x").exists()
    assert "feat/x" not in branches(repo)


def test_screen_unmerged_no_branch_question(repo):
    commit(repo / "feat-x")
    _run(repo, wt(repo, "feat-x"), [list("feat/x") + ["enter"], "y"])
    assert not (repo / "feat-x").exists()
    assert "feat/x" in branches(repo)


def test_screen_wrong_name_keeps_worktree(repo):
    commit(repo / "feat-x")
    _run(repo, wt(repo, "feat-x"), [list("nope") + ["enter"]])
    assert (repo / "feat-x").exists()
