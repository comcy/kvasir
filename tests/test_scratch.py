import asyncio
import os
import shutil
import subprocess

import pytest
from typer.testing import CliRunner

from kvasir import scratch
from kvasir.cli import app
from kvasir.config import LocalConfig, RepoConfig, save_local, save_repos
from kvasir.tui.app import KvasirApp
from kvasir.tui.columns import EntryList

SCRIPT = os.path.expanduser(os.environ.get("KVASIR_GIT_SCRATCH", ""))


def sh(cwd, *a):
    return subprocess.run(a, cwd=cwd, check=True, capture_output=True, text=True).stdout


@pytest.fixture
def root(make_repo, tmp_path):
    r = make_repo("r", bare_layout=True, remote=str(tmp_path / "nowhere"))  # fetch fails fast: warning only
    sh(r, "git", "worktree", "add", "-q", "main", "main")
    sh(r, "git", "branch", "feat/x", "main")
    sh(r, "git", "update-ref", "refs/remotes/origin/feat/o", "main")
    sh(r, "git", "tag", "v1", "main")
    return r


def test_add_detached_at_expected_path_and_idempotent(root):
    p = scratch.add(root, "feat/x")
    assert p == root / ".scratch" / "feat--x"
    assert subprocess.run(["git", "-C", str(p), "symbolic-ref", "-q", "HEAD"], check=False, capture_output=True).returncode != 0
    assert scratch.add(root, "feat/x") == p
    assert scratch.listing(root) == [p] and scratch.is_scratch(p)


def test_ref_resolution_local_origin_tag(root):
    for ref in ("feat/x", "feat/o", "v1"):
        assert scratch.add(root, ref).is_dir()
    with pytest.raises(RuntimeError):
        scratch.add(root, "nope")


def test_clean_refuses_dirty_then_force_branch_untouched(root):
    before = sh(root, "git", "for-each-ref")
    p = scratch.add(root, "feat/x")
    (p / "f").write_text("x")
    sh(p, "git", "add", "f")
    removed, errors = scratch.clean(root, "feat/x")
    assert not removed and errors and p.exists()
    removed, errors = scratch.clean(root, force=True)
    assert removed == [p] and not errors and not p.exists()
    assert sh(root, "git", "for-each-ref") == before


def test_cli(root):
    r = CliRunner().invoke(app, ["scratch", "add", "feat/x", "--repo", str(root)])
    assert r.exit_code == 0 and r.stdout.strip() == str(root / ".scratch" / "feat--x")
    assert str(root / ".scratch" / "feat--x") in CliRunner().invoke(app, ["scratch", "list", "--repo", str(root)]).stdout
    assert CliRunner().invoke(app, ["scratch", "clean", "feat/x", "--repo", str(root)]).exit_code == 0
    assert CliRunner().invoke(app, ["scratch", "add", "nope", "--repo", str(root)]).exit_code == 1


@pytest.mark.skipif(
    shutil.which("sh") is None or not os.path.isfile(SCRIPT) or not os.access(SCRIPT, os.X_OK),
    reason="needs sh and KVASIR_GIT_SCRATCH=<path to git-scratch>",
)
def test_script_same_path_and_cleanup(root):
    out = subprocess.run(["sh", SCRIPT, "add", "feat/x"], cwd=root / "main", capture_output=True, text=True, check=True)
    p = root / ".scratch" / "feat--x"
    assert out.stdout.strip() == str(p) and scratch.listing(root) == [p]
    assert scratch.add(root, "feat/x") == p
    lst = subprocess.run(["sh", SCRIPT, "list"], cwd=root, capture_output=True, text=True, check=True)
    assert lst.stdout.strip() == str(p)
    subprocess.run(["sh", SCRIPT, "clean"], cwd=root, check=True, capture_output=True)
    assert not p.exists()
    p = scratch.add(root, "v1")  # created by kvasir, cleaned by the script
    subprocess.run(["sh", SCRIPT, "clean", "v1"], cwd=root, check=True, capture_output=True)
    assert not p.exists()


def test_tui_keys_add_and_clean(root, monkeypatch):
    save_repos({"github.com/o/a": RepoConfig()})
    save_local(LocalConfig(paths={"github.com/o/a": str(root)}))
    opened = []
    monkeypatch.setattr("kvasir.tui.app.open_terminal", lambda p, t: opened.append(p))

    async def run():
        a = KvasirApp()
        async with a.run_test(size=(100, 20)) as pilot:
            for _ in range(50):
                await pilot.pause(0.1)
                if a.rows:
                    break
            await pilot.press("l", "v")  # main worktree
            p = root / ".scratch" / "main"
            for _ in range(50):
                await pilot.pause(0.1)
                if opened:
                    break
            assert opened == [p] and p.is_dir()
            await pilot.pause(0.3)
            text = " ".join(str(o.prompt) for o in a.query_one(EntryList).options)
            assert "[scratch] main" in text
            idx = next(i for i, e in enumerate(a.entries) if getattr(e, "path", None) == p)
            a.query_one(EntryList).highlighted = a.query_one(EntryList).entry_to_option(idx)
            await pilot.press("d")
            await pilot.pause(0.5)
            assert not p.exists()

    asyncio.run(run())
