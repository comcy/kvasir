import asyncio
import subprocess

from kvasir.config import LocalConfig, RepoConfig, save_local, save_repos
from kvasir.tui.app import KvasirApp
from kvasir.tui.columns import DetailPanel, EntryList, RepoList
from kvasir.tui.data import format_age, load_rows
from kvasir.worktrees import Branch


def test_format_age():
    assert format_age(None) == "-"
    assert format_age(1000, now=1000) == "now"
    assert format_age(0, now=90) == "1m"
    assert format_age(0, now=3 * 3600) == "3h"
    assert format_age(0, now=2 * 86400 + 5) == "2d"
    assert format_age(0, now=14 * 86400) == "2w"
    assert format_age(0, now=400 * 86400) == "1y"
    assert format_age(100, now=50) == "now"  # future timestamp


def _register(make_repo):
    root = make_repo("a", bare_layout=True)
    subprocess.run(["git", "-C", str(root), "worktree", "add", "-q", "main", "main"], check=True)
    save_repos({"github.com/o/a": RepoConfig(), "github.com/o/gone": RepoConfig()})
    save_local(LocalConfig(paths={"github.com/o/a": str(root)}))
    return root


def test_load_rows_missing_path(make_repo):
    _register(make_repo)
    rows = {r.url: r for r in load_rows()}
    assert rows["github.com/o/gone"].error == "nicht gefunden"
    a = rows["github.com/o/a"]
    assert a.view and len(a.view.worktrees) == 1 and a.dirty == 0


def test_app_selecting_repo_loads_middle_column(make_repo):
    _register(make_repo)

    async def run():
        app = KvasirApp()
        async with app.run_test(size=(40, 15)) as pilot:  # narrow terminal
            for _ in range(50):
                await pilot.pause(0.1)
                if app.rows:
                    break
            repos, entries = app.query_one(RepoList), app.query_one(EntryList)
            assert repos.option_count == 2
            assert entries.option_count == 1  # repo "a" selected first
            assert "main" in str(entries.get_option_at_index(0).prompt)
            assert "main" in str(app.query_one(DetailPanel).render())
            await pilot.press("down")  # "gone": not found, empty middle
            await pilot.pause()
            assert entries.option_count == 0
            assert "nicht gefunden" in str(repos.get_option_at_index(1).prompt)

    asyncio.run(run())


def test_enter_opens_terminal_or_hints(make_repo, monkeypatch):
    root = _register(make_repo)
    opened = []
    monkeypatch.setattr("kvasir.tui.app.open_terminal", lambda p, t: opened.append(p))

    async def run():
        app = KvasirApp()
        notes = []
        monkeypatch.setattr(app, "notify", lambda msg, **kw: notes.append(msg))
        async with app.run_test(size=(80, 15)) as pilot:
            for _ in range(50):
                await pilot.pause(0.1)
                if app.rows:
                    break
            await pilot.press("l", "enter")  # Worktree main
            await pilot.pause()
            assert opened == [root / "main"] and not notes
            app.entries.append(Branch("feat/x", False, None, ""))
            entries = app.query_one(EntryList)
            entries.add_option("x")
            entries.highlighted = 1
            await pilot.press("enter")
            await pilot.pause()
            assert len(opened) == 1 and "Worktree" in notes[0]

    asyncio.run(run())
