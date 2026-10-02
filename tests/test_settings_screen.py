import asyncio
import subprocess

from textual.widgets import Button, Input

from kvasir.config import LocalConfig, RepoConfig, load_repos, save_local, save_repos
from kvasir.tui.app import KvasirApp
from kvasir.tui.settings_screen import SettingsScreen, parse_minutes

A, B = "github.com/o/a", "github.com/o/b"


def _setup(make_repo):
    root = make_repo("a", bare_layout=True)
    subprocess.run(["git", "-C", str(root), "worktree", "add", "-q", "main", "main"], check=True)
    save_repos({A: RepoConfig(fetch_interval=7, platform_interval=3), B: RepoConfig()})
    save_local(LocalConfig(paths={A: str(root)}))


async def _open(app, pilot):
    for _ in range(50):
        await pilot.pause(0.1)
        if app.rows:
            break
    await pilot.press("e")
    await pilot.pause()
    assert isinstance(app.screen, SettingsScreen)
    return app.screen


def _run(make_repo, body):
    _setup(make_repo)

    async def run():
        app = KvasirApp()
        async with app.run_test(size=(120, 30)) as pilot:
            await body(app, pilot, await _open(app, pilot))

    asyncio.run(run())


def test_parse_minutes():
    assert parse_minutes(" 5 ") == 5
    for bad in ("", "x", "0", "-1", "1.5"):
        try:
            parse_minutes(bad)
        except ValueError:
            continue
        raise AssertionError(bad)


def test_opens_prefilled_with_examples(make_repo):
    async def body(app, pilot, scr):
        assert scr.query_one("#patterns", Input).value == "{type}/{slug}"
        assert scr.query_one("#fetch", Input).value == "7"
        assert scr.query_one("#platform", Input).value == "3"
        assert scr.url in scr.query_one("#dialog").border_title
        assert "{type}/{slug}  ->  feat/login-fehler" in str(scr.query_one("#patterns-msg").content)

    _run(make_repo, body)


def test_invalid_input_blocks_save(make_repo):
    async def body(app, pilot, scr):
        scr.query_one("#patterns", Input).value = "{nope}/{slug}"
        scr.query_one("#fetch", Input).value = "0"
        await pilot.pause()
        assert scr.query_one("#ok", Button).disabled
        assert scr.query_one("#patterns", Input).has_class("-invalid")
        assert scr.query_one("#fetch", Input).has_class("-invalid")
        scr.query_one("#platform", Input).focus()
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, SettingsScreen)
        assert load_repos()[A].fetch_interval == 7

    _run(make_repo, body)


def test_save_changes_only_this_repo_and_resets_timer(make_repo):
    async def body(app, pilot, scr):
        old = app._intervals[("fetch", A)]
        assert old._interval == 7 * 60
        scr.query_one("#patterns", Input).value = "features/{id}-{slug}, fixes/{id}-{slug}"
        scr.query_one("#fetch", Input).value = "2"
        scr.query_one("#platform", Input).value = "4"
        await pilot.pause()
        scr.query_one("#platform", Input).focus()
        await pilot.press("enter")
        await pilot.pause()
        assert not isinstance(app.screen, SettingsScreen)
        repos = load_repos()
        assert repos[A] == RepoConfig(["features/{id}-{slug}", "fixes/{id}-{slug}"], 2, 4)
        assert repos[B] == RepoConfig()
        assert app._intervals[("fetch", A)] is not old
        assert app._intervals[("fetch", A)]._interval == 2 * 60

    _run(make_repo, body)


def test_escape_changes_nothing(make_repo):
    async def body(app, pilot, scr):
        before = (scr.cfg.fetch_interval, load_repos())
        scr.query_one("#fetch", Input).value = "99"
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, SettingsScreen)
        assert load_repos() == before[1] and before[0] == 7

    _run(make_repo, body)


def test_preset_fills_patterns(make_repo):
    async def body(app, pilot, scr):
        from textual.widgets import Select
        scr.query_one("#preset", Select).value = "2"
        await pilot.pause()
        assert scr.query_one("#patterns", Input).value == "features/{id}-{slug}, fixes/{id}-{slug}"

    _run(make_repo, body)


def test_no_repos_hints(cfg_dir):
    async def run():
        app = KvasirApp()
        async with app.run_test(size=(100, 15)) as pilot:
            await pilot.pause(0.3)
            await pilot.press("e")
            await pilot.pause()
            assert not isinstance(app.screen, SettingsScreen)

    asyncio.run(run())
