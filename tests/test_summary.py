import asyncio
import json
import subprocess

from kvasir import llm, summary
from kvasir.config import LocalConfig, RepoConfig, config_dir, load_local, save_local, save_repos
from kvasir.platform.models import Error, ErrorKind, Result
from kvasir.tui.app import KvasirApp
from kvasir.tui.summary_screen import ConfirmScreen, SummaryScreen

URL = "github.com/o/a"
CMD = {"provider": "command", "command": ["fake"]}  # command = never local -> needs confirmation
ID = ["-c", "user.name=t", "-c", "user.email=t@t"]


class Fake:
    def __init__(self, text="Eine Zusammenfassung."):
        self.calls, self.text = [], text

    def __call__(self, messages, cfg=None, repo=None):
        self.calls.append(messages[0]["content"])
        return Result(data=self.text)


def _repo(make_repo):
    root = make_repo("a", bare_layout=True)
    wt = root / "main"
    subprocess.run(["git", "-C", str(root), "worktree", "add", "-q", "main", "main"], check=True)
    (wt / "README.md").write_text("# Hello kvasir\n")
    (wt / ".env").write_text("SECRET=hunter2\n")
    subprocess.run(["git", "-C", str(wt), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(wt), *ID, "commit", "-q", "-m", "add readme"], check=True)
    save_repos({URL: RepoConfig()})
    save_local(LocalConfig(paths={URL: str(root)}))
    return root


def _with_llm():
    local = load_local()
    local.llm = dict(CMD)
    save_local(local)


def test_generate_caches_and_skips_unchanged(make_repo, monkeypatch):
    root = _repo(make_repo)
    fake = Fake()
    monkeypatch.setattr(llm, "complete", fake)
    cfg = llm.parse(CMD)
    r = summary.generate(URL, root, None, cfg)
    assert r.ok and r.data.text == "Eine Zusammenfassung."
    assert "Hello kvasir" in fake.calls[0] and "add readme" in fake.calls[0]
    assert "hunter2" not in fake.calls[0]  # .env never in the input
    assert summary.cached(URL).head == summary.head_of(root)
    assert summary.generate(URL, root, None, cfg).ok and len(fake.calls) == 1  # unchanged: cache
    summary.generate(URL, root, None, cfg, force=True)
    assert len(fake.calls) == 2


def test_stale_when_head_changes(make_repo, monkeypatch):
    root = _repo(make_repo)
    monkeypatch.setattr(llm, "complete", Fake())
    summary.generate(URL, root, None, llm.parse(CMD))
    assert not summary.is_stale(URL, root)
    subprocess.run(["git", "-C", str(root / "main"), *ID, "commit", "-q", "--allow-empty", "-m", "more"], check=True)
    assert summary.is_stale(URL, root)


def test_broken_cache_file_is_miss(make_repo, monkeypatch):
    root = _repo(make_repo)
    monkeypatch.setattr(llm, "complete", Fake())
    config_dir().mkdir(parents=True, exist_ok=True)
    (config_dir() / "summary_cache.json").write_text("{not json")
    assert summary.cached(URL) is None
    assert summary.generate(URL, root, None, llm.parse(CMD)).ok
    assert json.loads((config_dir() / "summary_cache.json").read_text())[URL]["text"]


def test_llm_error_is_returned_not_cached(make_repo, monkeypatch):
    root = _repo(make_repo)
    monkeypatch.setattr(llm, "complete", lambda *a, **k: Result(error=Error(ErrorKind.NETWORK, "down", cli="llm")))
    r = summary.generate(URL, root, None, llm.parse(CMD))
    assert not r.ok and summary.cached(URL) is None


def _tui(body):
    async def run():
        app = KvasirApp()
        async with app.run_test(size=(120, 30)) as pilot:
            for _ in range(50):
                await pilot.pause(0.1)
                if app.rows:
                    break
            await body(app, pilot)
    asyncio.run(run())


def test_key_without_llm_hints(make_repo):
    _repo(make_repo)

    async def body(app, pilot):
        await pilot.press("s")
        await pilot.pause()
        assert not isinstance(app.screen, SummaryScreen)
        assert any("[llm]" in n.message for n in app._notifications)
    _tui(body)


def test_confirm_dialog_then_generate(make_repo, monkeypatch):
    _repo(make_repo)
    fake = Fake()
    monkeypatch.setattr(llm, "complete", fake)
    _with_llm()

    async def body(app, pilot):
        await pilot.press("s")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmScreen)
        await pilot.press("enter")
        for _ in range(50):
            await pilot.pause(0.1)
            if fake.calls:
                break
        await pilot.pause(0.3)
        assert fake.calls and isinstance(app.screen, SummaryScreen)
        assert "Eine Zusammenfassung." in str(app.screen.query_one("#summary-text").render())
        assert "fake" in load_local().llm["confirmed"]
    _tui(body)


def test_confirm_escape_sends_nothing(make_repo, monkeypatch):
    _repo(make_repo)
    fake = Fake()
    monkeypatch.setattr(llm, "complete", fake)
    _with_llm()

    async def body(app, pilot):
        await pilot.press("s")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert not fake.calls and "confirmed" not in load_local().llm
    _tui(body)
