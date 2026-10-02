import asyncio
import subprocess
from pathlib import Path

from kvasir.config import LocalConfig, RepoConfig, save_local, save_repos
from kvasir.tui.app import KvasirApp
from kvasir.tui.columns import DetailPanel, EntryList, RepoList
from kvasir.tui.data import format_age, load_rows
from kvasir.tui.layout import fit, format_entry, group_entries, name_width, short_name, tilde
from kvasir.worktrees import Branch, RepoView, Worktree


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
        async with app.run_test(size=(100, 15)) as pilot:
            for _ in range(50):
                await pilot.pause(0.1)
                if app.rows:
                    break
            repos, entries = app.query_one(RepoList), app.query_one(EntryList)
            assert repos.option_count == 2
            assert entries.option_count == 2  # heading + main; repo "a" selected first
            assert "main" in str(entries.get_option_at_index(1).prompt)
            assert "main" in str(app.query_one(DetailPanel).render())
            await pilot.press("down")  # "gone": not found, empty middle
            await pilot.pause()
            assert entries.option_count == 0
            assert "nicht gefunden" in str(repos.get_option_at_index(1).prompt)

    asyncio.run(run())


def test_app_f_fetches_and_shows_last_fetch(make_repo):
    root = make_repo("a", bare_layout=True)
    subprocess.run(["git", "-C", str(root), "worktree", "add", "-q", "main", "main"], check=True)
    save_repos({"github.com/o/a": RepoConfig()})
    save_local(LocalConfig(paths={"github.com/o/a": str(root)}))

    async def run():
        app = KvasirApp()
        async with app.run_test(size=(120, 15)) as pilot:
            for _ in range(50):
                await pilot.pause(0.1)
                if app.rows:
                    break
            assert "fetched -" in str(app.query_one(RepoList).get_option_at_index(0).prompt)
            await pilot.press("f")  # origin is a bad URL: error shown, no crash
            for _ in range(100):
                await pilot.pause(0.1)
                if "github.com/o/a" in app.sync:
                    break
            await pilot.pause(0.5)
            assert app.sync["github.com/o/a"][1]
            assert "fetch failed" in str(app.query_one(RepoList).get_option_at_index(0).prompt)

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
            entries.index_map.append(1)
            entries.highlighted = 2
            await pilot.press("enter")
            await pilot.pause()
            assert len(opened) == 1 and "Worktree" in notes[0]

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
            hl = app.query_one(EntryList).current_entry()
            assert getattr(app.entries[hl], "branch", None) == "feat/cool-thing"

    asyncio.run(run())


def test_layout_pure_functions():
    assert short_name("github.com/owner/name") == "owner/name"
    assert short_name("solo") == "solo"
    assert tilde(Path("/h/u/ws/x"), Path("/h/u")) == "~/ws/x"
    assert tilde(Path("/h/u"), Path("/h/u")) == "~"
    assert tilde(Path("/etc/x"), Path("/h/u")) == "/etc/x"
    assert fit("abc", 5) == "abc  " and fit("abcdef", 4) == "abc…" and fit("x", 0) == ""
    assert name_width(["a"], 100) == 1
    assert name_width(["x" * 80], 100) == 55  # capped at 55%
    assert name_width(["x" * 50], 10) == 8  # cap floor
    assert name_width(["x" * 20], 100) == 20
    wt = Worktree(Path("/r/main"), "main", commit_ts=0, subject="subj", staged=1, unstaged=2, untracked=3)
    line = format_entry(wt, 10, "note")
    assert line.startswith("main      ") and "+1 ~2 ?3" in line and line.endswith("subj  ✎ note")


def test_group_entries():
    view = RepoView([Worktree(Path("/r/a"), "a")], [Branch("l", False, None, ""), Branch("origin/r", True, None, "")])
    g = group_entries(view, show_remote=False)
    assert [x.header for x in g] == ["Worktrees (1)", "Branches ohne Worktree (1)", "▸ Remote-Branches (1)  (b: show)"]
    assert [len(x.visible) for x in g] == [1, 1, 0]
    assert group_entries(view, True)[2].header == "▾ Remote-Branches (1)"
    assert [x.key for x in group_entries(RepoView([Worktree(Path("/r/a"), "a")], []), False)] == ["worktrees"]


def test_app_groups_skip_headings_toggle_remote_and_keep_selection(make_repo):
    root = _register(make_repo)
    for ref in ("refs/heads/loc", "refs/remotes/origin/r1", "refs/remotes/origin/r2"):
        subprocess.run(["git", "-C", str(root), "update-ref", ref, "main"], check=True)

    async def run():
        app = KvasirApp()
        async with app.run_test(size=(100, 20)) as pilot:
            for _ in range(50):
                await pilot.pause(0.1)
                if app.rows:
                    break
            lst = app.query_one(EntryList)
            heads = [str(lst.get_option_at_index(i).prompt).strip() for i, e in enumerate(lst.index_map) if e is None]
            assert heads == ["Worktrees (1)", "Branches ohne Worktree (1)", "▸ Remote-Branches (2)  (b: show)"]
            assert [getattr(e, "name", None) or e.branch for e in app.entries] == ["main", "loc"]
            await pilot.press("l")  # focus entries
            await pilot.press("down")  # skips the "Branches ohne Worktree" heading
            assert app.entries[lst.current_entry()].name == "loc"
            await pilot.press("b")
            await pilot.pause()
            assert len(app.entries) == 4 and lst.option_count == 3 + 4
            await pilot.press("down")  # skips the Remote heading
            assert app.entries[lst.current_entry()].name == "origin/r1"
            await pilot.press("r")  # reload keeps selection and expanded state
            for _ in range(20):
                await pilot.pause(0.1)
            assert app.entries[lst.current_entry()].name == "origin/r1"
            await pilot.press("b")
            await pilot.pause()
            assert len(app.entries) == 2 and app.show_remote is False

    asyncio.run(run())


def test_narrow_terminal_hides_details_without_breaking(make_repo):
    _register(make_repo)

    async def run():
        app = KvasirApp()
        async with app.run_test(size=(40, 20)) as pilot:
            for _ in range(50):
                await pilot.pause(0.1)
                if app.rows:
                    break
            await pilot.pause()
            assert not app.query_one("#detail-col").display
            assert app.query_one("#entries-col").size.width >= 10
            assert len(app.entries) == 1

    asyncio.run(run())
