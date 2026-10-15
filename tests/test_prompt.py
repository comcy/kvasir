"""Prompt window: deterministic repo search, context, confirmation, background answer. Fake LLM, no network."""
import asyncio
import subprocess
import threading

from textual.containers import Vertical
from textual.widgets import Collapsible

from kvasir import ask, daylog, llm, notes
from kvasir.config import LocalConfig, RepoConfig, load_local, save_local, save_repos
from kvasir.platform.models import Error, ErrorKind, Result
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
        qs = [str(w.render()) for w in scr.query(".q")]  # questions carry their own class (background)
        assert qs == ["> frobnicate", "> again"]
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


def _fake_usage(monkeypatch, limit, error=None):
    sent = []

    def fake(messages, cfg=None, repo=None):
        sent.append(messages)
        if error:
            return Result(error=Error(ErrorKind.OTHER, error, cli="llm"))
        return Result(data="ok", usage={"prompt_tokens": 5000, "completion_tokens": 200})

    monkeypatch.setattr(llm, "complete", fake)
    monkeypatch.setattr(llm, "n_ctx", lambda cfg: limit)
    return sent


def test_title_usage_and_limit(make_repo, monkeypatch):
    _repo(make_repo, LOCAL)
    _fake_usage(monkeypatch, 8192)

    async def body(app, pilot, scr):
        await _send(pilot, "frobnicate")
        assert scr.query_one(Vertical).border_title == "Ask · 5.2k / 8.2k tokens"

    _run(body)


def test_title_usage_without_limit(make_repo, monkeypatch):
    _repo(make_repo, LOCAL)
    _fake_usage(monkeypatch, None)

    async def body(app, pilot, scr):
        await _send(pilot, "frobnicate")
        assert scr.query_one(Vertical).border_title == "Ask · 5.2k tokens"

    _run(body)


def test_ctrl_n_resets(make_repo, monkeypatch):
    _repo(make_repo, LOCAL)
    _fake_usage(monkeypatch, 8192)

    async def body(app, pilot, scr):
        await _send(pilot, "frobnicate")
        assert scr.history
        await pilot.press("ctrl+n")
        await pilot.pause()
        assert scr.history == [] and scr.lines == []
        assert len(scr.query(".q")) == 0 and len(scr.query(Collapsible)) == 0
        assert scr.query_one(Vertical).border_title == "Ask"
        assert isinstance(app.screen, PromptScreen)

    _run(body)


def test_fit_drops_oldest_pairs():
    h = [{"role": r, "content": "x" * 400} for r in ("user", "assistant", "user", "assistant")]
    msgs = [{"role": "system", "content": "s"}, *h, {"role": "user", "content": "q"}]
    out, n = ask.fit(msgs, ask.RESERVE + 150)  # ~150 tokens budget
    assert n == 2 and [m["content"] for m in out] == ["s", "q"]
    assert ask.fit(msgs, 100000) == (msgs, 0)


def test_autotrim_before_send(make_repo, monkeypatch):
    _repo(make_repo, LOCAL)
    sent = _fake_usage(monkeypatch, ask.RESERVE + 2000)

    async def body(app, pilot, scr):
        scr.history = [{"role": r, "content": "x" * 4000} for r in ("user", "assistant") * 3]
        await _send(pilot, "frobnicate")
        assert sum(len(m["content"]) for m in sent[0]) // 4 <= ask.RESERVE + 2000
        assert len(sent[0]) < 8
        assert "ältere Runden verworfen" in _text(scr)
        assert len(scr.history) == len(sent[0]) - 2 + 2  # kept history + new pair

    _run(body)


def test_exceed_context_hint(make_repo, monkeypatch):
    _repo(make_repo, LOCAL)
    _fake_usage(monkeypatch, None, error="HTTP 400 exceed_context_size_error (8294 > 8192)")

    async def body(app, pilot, scr):
        await _send(pilot, "frobnicate")
        t = _text(scr)
        assert "exceed_context_size_error" in t and "ctrl+n für Reset" in t

    _run(body)


def test_sent_system_prompt_collapsible(make_repo, monkeypatch):
    _repo(make_repo, LOCAL)
    sent = _fake_usage(monkeypatch, None)

    async def body(app, pilot, scr):
        await _send(pilot, "frobnicate")
        (c,) = scr.query(Collapsible)
        assert c.collapsed
        assert str(c.query_one(".ctx").render()) == sent[0][0]["content"]
        assert f"{len(sent[0][0]['content'])} Zeichen" in c.title

    _run(body)


def test_conversation_survives_reopen_until_reset(make_repo, monkeypatch):
    _repo(make_repo, LOCAL)
    sent = _fake_usage(monkeypatch, 8192)

    async def run():
        app = KvasirApp()
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            await pilot.press("a")
            await pilot.pause()
            await _send(pilot, "frobnicate")
            await pilot.press("escape")
            await pilot.pause()
            await pilot.press("a")
            await pilot.pause()
            scr = app.screen
            assert isinstance(scr, PromptScreen)
            assert [str(w.render()) for w in scr.query(".q")] == ["> frobnicate"]
            assert "ok" in _text(scr) and len(scr.query(Collapsible)) == 1
            assert scr.query_one(Vertical).border_title == "Ask · 5.2k / 8.2k tokens"
            await _send(pilot, "again")
            assert any(m["content"] == "ok" for m in sent[1])  # history goes to the server
            await pilot.press("ctrl+n")
            await pilot.press("escape")
            await pilot.pause()
            await pilot.press("a")
            await pilot.pause()
            assert app.screen.lines == [] and app.screen.history == []

    asyncio.run(run())


def _hist():
    from kvasir.config import config_dir
    return config_dir() / "ask-history.json"


def test_keep_history_validation():
    assert llm.parse({**LOCAL, "keep_history": True}).keep_history is True
    assert llm.parse(LOCAL).keep_history is False
    try:
        llm.parse({**LOCAL, "keep_history": "yes"})
    except ValueError as e:
        assert "keep_history" in str(e)
    else:
        raise AssertionError


def test_default_writes_nothing(make_repo, monkeypatch):
    _repo(make_repo, LOCAL)
    _fake_usage(monkeypatch, None)

    async def body(app, pilot, scr):
        await _send(pilot, "frobnicate")
        assert not _hist().exists()

    _run(body)


def test_keep_history_write_load_clear(make_repo, monkeypatch):
    _repo(make_repo, {**LOCAL, "keep_history": True})
    _fake_usage(monkeypatch, None)

    async def first(app, pilot, scr):
        await _send(pilot, "frobnicate")
        assert _hist().exists()
        assert "ctx" not in _hist().read_text() and "searching" not in _hist().read_text()

    _run(first)

    async def second(app, pilot, scr):  # new TUI start: restored from disk
        assert [str(w.render()) for w in scr.query(".q")] == ["> frobnicate"]
        assert [m["content"] for m in scr.history][-1] == "ok"
        await pilot.press("ctrl+n")
        await pilot.pause()
        assert not _hist().exists()

    _run(second)


def test_broken_history_file_is_empty(make_repo, monkeypatch):
    _repo(make_repo, {**LOCAL, "keep_history": True})
    _hist().parent.mkdir(parents=True, exist_ok=True)
    _hist().write_text("{not json")

    async def body(app, pilot, scr):
        assert scr.history == [] and scr.lines == []

    _run(body)


def test_file_not_read_without_keep_history(make_repo):
    _repo(make_repo, LOCAL)
    _hist().parent.mkdir(parents=True, exist_ok=True)
    _hist().write_text('{"history": [], "used": null, "log": [["say", "> old", "q"]]}')

    async def body(app, pilot, scr):
        assert scr.lines == []

    _run(body)


import pytest


@pytest.fixture(autouse=True)
def _no_props(monkeypatch):
    monkeypatch.setattr(llm, "n_ctx", lambda cfg: None)  # no network in tests
