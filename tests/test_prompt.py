"""Prompt window: deterministic repo search, context, confirmation, background answer. Fake LLM, no network."""
import asyncio
import subprocess
import threading

from kvasir import ask, daylog, llm, notes
from kvasir.config import LocalConfig, RepoConfig, load_local, save_local, save_repos
from kvasir.platform.models import Result
from kvasir.tui.app import KvasirApp
from kvasir.tui.prompt_screen import PromptScreen

URL = "github.com/o/a"
LOCAL = {"provider": "openai", "base_url": "http://localhost:1/v1", "model": "m"}
REMOTE = {"provider": "openai", "base_url": "https://llm.example.com/v1", "model": "m"}


def sh(cwd, *a):
    subprocess.run(a, cwd=cwd, check=True, capture_output=True)


def _repo(make_repo, llm_cfg=None, name="a"):
    root = make_repo(name)
    (root / "app.py").write_text("def frobnicate():\n    pass\n")
    (root / ".env").write_text("frobnicate=secret\n")
    (root / "x.env").write_text("frobnicate=secret\n")
    sh(root, "git", "add", ".")
    sh(root, "git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "add zebrafish handling")
    save_local(LocalConfig(paths={URL: str(root)}, llm=llm_cfg or {}))
    return root


def test_search_hits_file_and_commit_not_env(make_repo):
    root = _repo(make_repo)
    hits = ask.search_repo(root, ["frobnicate"])
    assert any(h.startswith("app.py:1:") for h in hits)
    assert not any(".env" in h for h in hits)
    assert any(h.startswith("commit ") and "zebrafish" in h for h in ask.search_repo(root, ["zebrafish"]))
    assert any(h.startswith("commit ") for h in ask.search_repo(root, ["frobnicate"]))  # pickaxe


def test_search_skips_opted_out_repo(make_repo):
    _repo(make_repo)
    assert URL in ask.search("where is frobnicate")
    save_repos({URL: RepoConfig(llm=False)})
    assert ask.search("where is frobnicate") == {}


def test_messages_have_hits_notes_daylog(make_repo):
    _repo(make_repo)
    notes.add(URL, "feat/x", "remember the walrus")
    daylog.record({"type": "note", "url": URL, "branch": "b", "text": "daylogword"})
    ctx = ask.messages("frobnicate?", [{"role": "user", "content": "old"}])
    assert [m["role"] for m in ctx] == ["system", "user", "user"]
    s = ctx[0]["content"]
    assert "app.py:1:" in s and "walrus" in s and "daylogword" in s and "secret" not in s


def _run(body):
    async def run():
        app = KvasirApp()
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            await pilot.press("a")
            await pilot.pause()
            assert isinstance(app.screen, PromptScreen)
            await body(app, pilot, app.screen)

    asyncio.run(run())


async def _send(pilot, text):
    for c in text:
        await pilot.press("space" if c == " " else c)
    await pilot.press("enter")
    await pilot.pause(0.5)


def _text(scr):
    return "\n".join(scr.lines)


def test_key_in_footer():
    assert any(b.key == "a" and b.show for b in KvasirApp.BINDINGS)


def test_no_llm_message():
    async def body(app, pilot, scr):
        await _send(pilot, "hi")
        assert "No [llm] configured" in _text(scr)
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, PromptScreen)

    _run(body)


def test_answer_with_search_context_and_history(make_repo, monkeypatch):
    _repo(make_repo, LOCAL)
    seen = []

    def fake(messages, cfg=None, repo=None):
        seen.append(messages)
        return Result(data=f"answer {len(seen)}: {URL} app.py")

    monkeypatch.setattr(llm, "complete", fake)

    async def body(app, pilot, scr):
        await _send(pilot, "frobnicate")
        await _send(pilot, "again")
        assert "answer 1" in _text(scr) and "answer 2" in _text(scr)
        assert "app.py:1:" in seen[0][0]["content"]
        assert any(m["content"].startswith("answer 1") for m in seen[1])  # session history

    _run(body)


def test_remote_needs_confirmation_then_remembered(make_repo, monkeypatch):
    _repo(make_repo, REMOTE)
    calls = []
    monkeypatch.setattr(llm, "complete", lambda m, cfg=None, repo=None: calls.append(m) or Result(data="ok"))

    async def body(app, pilot, scr):
        await _send(pilot, "frobnicate")
        assert calls == [] and "llm.example.com" in _text(scr)
        assert load_local().llm.get("confirmed") is None
        await pilot.press("enter")
        await pilot.pause(0.5)
        assert len(calls) == 1
        assert load_local().llm["confirmed"] == ["llm.example.com"]

    _run(body)


def test_escape_cancels_confirmation(make_repo, monkeypatch):
    _repo(make_repo, REMOTE)
    monkeypatch.setattr(llm, "complete", lambda *a, **k: (_ for _ in ()).throw(AssertionError("sent")))

    async def body(app, pilot, scr):
        await _send(pilot, "frobnicate")
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, PromptScreen)
        assert load_local().llm.get("confirmed") is None

    _run(body)


def test_escape_discards_running_answer(make_repo, monkeypatch):
    _repo(make_repo, LOCAL)
    go, started = threading.Event(), threading.Event()

    def slow(m, cfg=None, repo=None):
        started.set()
        go.wait(5)
        return Result(data="late")

    monkeypatch.setattr(llm, "complete", slow)

    async def body(app, pilot, scr):
        await _send(pilot, "frobnicate")
        assert started.wait(5)
        await pilot.press("escape")  # must not wait for the blocked LLM call
        await pilot.pause()
        assert not isinstance(app.screen, PromptScreen)
        go.set()
        await pilot.pause(0.5)
        assert scr.history == [] and "late" not in _text(scr)

    _run(body)
