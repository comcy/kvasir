"""Commit-message / note suggestions: fake LLM, throwaway repos, no network."""
import asyncio
import subprocess

from kvasir import daylog, llm, notes, suggest
from kvasir.config import LocalConfig, RepoConfig, save_local, save_repos
from kvasir.platform.models import Result
from kvasir.tui.app import KvasirApp
from kvasir.tui.suggest_screen import SuggestScreen

URL = "github.com/o/a"
LOCAL = {"provider": "openai", "base_url": "http://localhost:1/v1", "model": "m"}
REMOTE = {"provider": "openai", "base_url": "https://llm.example.com/v1", "model": "m"}
IDENT = ["-c", "user.name=Tester", "-c", "user.email=tester@example.com"]


def sh(cwd, *a):
    subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True)


def head(root):
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True).stdout


def _repo(make_repo, cfg=None):
    root = make_repo("a", remote="git@github.com:o/a.git")
    (root / "app.py").write_text("one\n")
    sh(root, "add", "app.py")
    sh(root, *IDENT, "commit", "-q", "-m", "init")
    save_local(LocalConfig(paths={URL: str(root)}, llm=cfg or LOCAL))
    save_repos({URL: RepoConfig()})
    sh(root, "config", "user.name", "Tester")  # commits from the TUI use the repo config
    sh(root, "config", "user.email", "tester@example.com")
    return root


def _stage(root):
    (root / "app.py").write_text("one\ntwo\n")
    (root / ".env").write_text("TOKEN=secret\n")
    (root / "x.env").write_text("TOKEN=secret\n")
    sh(root, "add", "-f", "app.py", ".env", "x.env")


def _run(root, kind, body, cfg=None):
    async def run():
        app = KvasirApp()
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            app.push_screen(SuggestScreen(kind, URL, "main", root, llm.parse(cfg or LOCAL)))
            await pilot.pause(0.5)
            await body(app, pilot, app.screen)

    asyncio.run(run())


def _fake(monkeypatch, answer="feat(app): add two"):
    seen = []

    def complete(messages, cfg=None, repo=None):
        seen.append((messages, repo))
        return Result(data=answer)

    monkeypatch.setattr(llm, "complete", complete)
    return seen


async def _loaded(app, pilot):
    for _ in range(50):
        await pilot.pause(0.1)
        if app.entries:
            break


def _status(scr):
    return str(scr.query_one("#status").render())


def test_staged_diff_excludes_env_and_is_capped(make_repo, monkeypatch):
    root = _repo(make_repo)
    _stage(root)
    d = suggest.staged_diff(root)
    assert "+two" in d and "secret" not in d
    monkeypatch.setattr(suggest, "MAX_DIFF", 10)
    assert len(suggest.staged_diff(root)) == 10


def test_empty_staged_diff_no_llm_call(make_repo, monkeypatch):
    root = _repo(make_repo)
    seen = _fake(monkeypatch)

    async def body(app, pilot, scr):
        assert "Nichts gestaged" in _status(scr)
        assert seen == []

    _run(root, "commit", body)


def test_commit_only_after_explicit_confirmation(make_repo, monkeypatch):
    root = _repo(make_repo)
    _stage(root)
    seen = _fake(monkeypatch)
    before = head(root)

    async def body(app, pilot, scr):
        assert "secret" not in seen[0][0][1]["content"] and seen[0][1] == URL
        assert scr.query_one("#text").value == "feat(app): add two"
        await pilot.press("enter")  # first Enter only asks
        await pilot.pause(0.3)
        assert head(root) == before
        await pilot.press("enter")
        await pilot.pause(1)
        assert head(root) != before
        assert not isinstance(app.screen, SuggestScreen)

    _run(root, "commit", body)
    out = subprocess.run(["git", "log", "-1", "--format=%s|%ae"], cwd=root, capture_output=True, text=True, check=True).stdout
    assert out.strip() == "feat(app): add two|tester@example.com"


def test_escape_does_not_commit(make_repo, monkeypatch):
    root = _repo(make_repo)
    _stage(root)
    _fake(monkeypatch)
    before = head(root)

    async def body(app, pilot, scr):
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, SuggestScreen) and head(root) == before

    _run(root, "commit", body)


def test_commit_failure_shown(make_repo, monkeypatch):
    root = _repo(make_repo)
    _stage(root)
    _fake(monkeypatch)
    hook = root / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\necho hookfail >&2\nexit 1\n")
    hook.chmod(0o755)

    async def body(app, pilot, scr):
        await pilot.press("enter")
        await pilot.press("enter")
        await pilot.pause(1)
        assert isinstance(app.screen, SuggestScreen)
        assert "hookfail" in _status(scr)

    _run(root, "commit", body)


def test_note_input_is_daylog_and_diff(make_repo, monkeypatch):
    root = _repo(make_repo)
    (root / "app.py").write_text("one\nthree\n")
    (root / ".env").write_text("TOKEN=secret\n")
    daylog.record({"type": "note", "url": URL, "branch": "main", "text": "earlier"})
    seen = _fake(monkeypatch, "Added three.")
    out = []

    async def body(app, pilot, scr):
        c = seen[0][0][1]["content"]
        assert "earlier" in c and "+three" in c and "secret" not in c
        await pilot.press("enter")
        await pilot.pause()
        assert out == ["Added three."]

    async def run():
        app = KvasirApp()
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            app.push_screen(SuggestScreen("note", URL, "main", root, llm.parse(LOCAL)), out.append)
            await pilot.pause(0.5)
            await body(app, pilot, app.screen)

    asyncio.run(run())


def test_key_saves_note_for_worktree(make_repo, monkeypatch):
    root = _repo(make_repo)
    (root / "app.py").write_text("one\nthree\n")
    _fake(monkeypatch, "Note via key.")

    async def run():
        app = KvasirApp()
        async with app.run_test(size=(120, 30)) as pilot:
            await _loaded(app, pilot)
            await pilot.press("t")
            await pilot.pause(0.7)
            assert isinstance(app.screen, SuggestScreen)
            await pilot.press("enter")
            await pilot.pause(0.5)

    asyncio.run(run())
    assert notes.latest(URL, "main")["text"] == "Note via key."


def test_opted_out_repo_no_screen(make_repo, monkeypatch):
    _repo(make_repo)
    save_repos({URL: RepoConfig(llm=False)})  # after _repo: replaces the registration
    seen = _fake(monkeypatch)

    async def run():
        app = KvasirApp()
        async with app.run_test(size=(120, 30)) as pilot:
            await _loaded(app, pilot)
            await pilot.press("c")
            await pilot.pause()
            assert not isinstance(app.screen, SuggestScreen)

    asyncio.run(run())
    assert seen == []


def test_remote_confirmation_cancel_sends_nothing(make_repo, monkeypatch):
    root = _repo(make_repo, REMOTE)
    _stage(root)
    seen = _fake(monkeypatch)

    async def body(app, pilot, scr):
        await pilot.press("escape")  # ConfirmScreen on top
        await pilot.pause()
        assert seen == [] and not isinstance(app.screen, SuggestScreen)

    _run(root, "commit", body, REMOTE)
