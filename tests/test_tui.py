import asyncio
import subprocess

from kvasir.config import LocalConfig, RepoConfig, save_local, save_repos
from kvasir.tui.app import KvasirApp
from kvasir.tui.columns import DetailPanel, EntryList, RepoList
from kvasir.tui.data import format_age, load_rows


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


def test_new_worktree_dialog(make_repo):
    from textual.widgets import Input, Label

    root = _register(make_repo)

    async def run():
        app = KvasirApp()
        async with app.run_test(size=(100, 40)) as pilot:
            for _ in range(50):
                await pilot.pause(0.1)
                if app.rows:
                    break
            await pilot.press("n")
            await pilot.pause()
            title = app.screen.query_one("#title", Input)
            title.value = "Cool thing"
            title.focus()
            await pilot.pause()
            assert "feat/cool-thing" in str(app.screen.query_one("#name", Label).render())
            await pilot.press("enter")
            for _ in range(50):
                await pilot.pause(0.1)
                if (root / "feat" / "cool-thing").is_dir() and len(app.entries) == 2:
                    break
            assert (root / "feat" / "cool-thing").is_dir()
            hl = app.query_one(EntryList).highlighted
            assert getattr(app.entries[hl], "branch", None) == "feat/cool-thing"

    asyncio.run(run())
