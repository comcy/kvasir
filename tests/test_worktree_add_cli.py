import subprocess

import pytest
from conftest import sh
from typer.testing import CliRunner

from kvasir import worktree_add
from kvasir.cli import app

G = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]


# CliRunner echoes prompt input to stdout; real stdout carries only the path (see non-interactive tests)
def run(*args, input=None):
    return CliRunner().invoke(app, ["worktree", "add", *args], input=input)


def out(cwd, *a):
    return subprocess.run(["git", "-C", str(cwd), *a], capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def root(make_repo):
    r = make_repo("r", bare_layout=True)
    sh(r, "git", "config", "remote.origin.fetch", "+refs/heads/*:refs/remotes/origin/*")
    sh(r, "git", "worktree", "add", "-q", "main", "main")
    sh(r, "git", "branch", "feat/old", "main")
    sh(r, "git", "update-ref", "refs/remotes/origin/fix/rem", "main")
    return r


@pytest.fixture
def tty(monkeypatch):
    monkeypatch.setattr(worktree_add, "_is_tty", lambda: True)


def dirty(wt):
    (wt / "a").write_text("1")
    sh(wt, "git", "add", "a")
    (wt / "README").write_text("x")  # untracked
    (wt / "b").write_text("2")
    sh(wt, "git", "add", "b")
    (wt / "b").write_text("3")  # staged + unstaged


def test_new_branch_default_base_stdout_only_path(root):
    r = run("feat/x", "--repo", str(root))
    assert r.exit_code == 0 and r.stdout.strip() == str(root / "feat" / "x")
    assert out(root / "feat" / "x", "rev-parse", "--abbrev-ref", "HEAD") == "feat/x"


def test_from_base_and_existing_local_and_remote(root):
    sh(root / "main", *G, "commit", "-q", "--allow-empty", "-m", "m2")
    sh(root, "git", "branch", "feat/b", "main~1")
    r = run("feat/y", "--from", "feat/b", "--repo", str(root))
    assert r.exit_code == 0 and out(root / "feat" / "y", "rev-parse", "HEAD") == out(root, "rev-parse", "feat/b")
    for name, want in (("feat/old", "feat/old"), ("fix/rem", "fix/rem")):
        r = run(name, "--repo", str(root))
        assert r.exit_code == 0, r.stderr
        assert r.stdout.strip() == str(root / name)
        assert out(root / name, "rev-parse", "--abbrev-ref", "HEAD") == want


def test_unknown_base_exit_1(root):
    r = run("feat/z", "--from", "nope", "--repo", str(root))
    assert r.exit_code == 1 and not r.stdout and not (root / "feat" / "z").exists()


def test_not_bare_layout(make_repo):
    r = run("feat/x", "--repo", str(make_repo("n")))
    assert r.exit_code == 1 and "Bare-Layout" in r.stderr


def test_repo_from_inside_worktree(root, monkeypatch):
    monkeypatch.chdir(root / "main")
    r = run("feat/x")
    assert r.exit_code == 0 and r.stdout.strip() == str(root / "feat" / "x")


def test_name_violation_suggestion_and_force(root):
    r = run("Foo_Bar", "--repo", str(root))
    assert r.exit_code == 1 and "suggestion" in r.stderr and not r.stdout
    assert r.stderr.count("error:") == 1  # reported once, not again as "error: 1"
    r = run("Foo_Bar", "--force-name", "--repo", str(root))
    assert r.exit_code == 0, r.stderr


def test_move_changes_and_without_flag(root):
    dirty(root / "main")
    r = run("feat/n", "--repo", str(root / "main"))
    assert r.exit_code == 0 and "--move-changes" in r.stderr and "--move-changes" not in r.stdout
    assert out(root / "main", "status", "--porcelain") and not out(root / "feat" / "n", "status", "--porcelain")
    r = run("feat/m", "--move-changes", "--repo", str(root / "main"))
    assert r.exit_code == 0 and not out(root / "main", "status", "--porcelain")
    assert sorted(out(root / "feat" / "m", "status", "--porcelain").splitlines()) == ["?? README", "A  a", "AM b"]


def test_interactive_needs_tty(root):
    r = run("-i", "--repo", str(root))
    assert r.exit_code == 1 and "TTY" in r.stderr


def test_interactive_new_branch_suggestion_and_override(root, tty):
    # no existing choice shown as 'new' (Enter); type, id, title -> suggestion accepted; base; confirm
    # (patterns default: {type}/{slug}, ID unused by it)
    r = run("-i", "--repo", str(root), input="new\nfeat\n\nMy Title\n\n\n\n")
    assert r.exit_code == 0 and r.stdout.splitlines()[-1] == str(root / "feat" / "my-title")
    assert "main (" in r.stderr and "Create worktree" in r.stderr
    r = run("-i", "--repo", str(root), input="new\nfix\n\nOther\nfix/free-name\n\n\n")
    assert r.exit_code == 0 and r.stdout.splitlines()[-1] == str(root / "fix" / "free-name")


def test_interactive_existing_branch_by_number(root, tty):
    r = run("-i", "--repo", str(root), input="1\n\n")
    assert r.exit_code == 0 and r.stdout.splitlines()[-1] == str(root / "feat" / "old")
    assert "Existing branches" in r.stderr and "From" not in r.stderr


def test_interactive_violation_confirm_and_abort(root, tty):
    r = run("-i", "--repo", str(root), input="new\nfeat\n\nT\nBad_Name\n\nn\n")
    assert r.exit_code == 1 and not (root / "Bad_Name").exists() and "violates" in r.stderr
    r = run("-i", "--repo", str(root), input="new\nfeat\n\nT\nBad_Name\n\ny\n\n")
    assert r.exit_code == 0 and (root / "Bad_Name").exists()


def test_interactive_move_question_only_with_changes_and_abort(root, tty):
    r = run("feat/q", "-i", "--repo", str(root / "main"), input="\n\n")
    assert "Move" not in r.stderr
    dirty(root / "main")
    r = run("feat/r", "-i", "--repo", str(root / "main"), input="\ny\nn\n")  # base, move yes, final confirm no
    assert r.exit_code == 1 and "Move 4 uncommitted changes" in r.stderr and not (root / "feat" / "r").exists()
    assert out(root / "main", "status", "--porcelain")
    r = run("feat/s", "-i", "--repo", str(root / "main"), input="\ny\ny\n")
    assert r.exit_code == 0 and not out(root / "main", "status", "--porcelain")


def test_interactive_eof_aborts_cleanly(root, tty):
    r = run("-i", "--repo", str(root), input="")
    assert r.exit_code == 1 and not r.stdout.strip()
