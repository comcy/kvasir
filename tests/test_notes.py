import asyncio
import subprocess

from kvasir import notes
from kvasir.config import LocalConfig, RepoConfig, save_local, save_repos
from kvasir.tui.app import KvasirApp
from kvasir.tui.columns import DetailPanel, EntryList

U = "github.com/o/a"


def test_write_read_latest_wins():
    assert notes.latest(U, "b") is None
    notes.add(U, "b", "first")
    notes.add(U, "b", "zweite äöü")
    notes.add(U, "c", "other")
    n = notes.latest(U, "b")
    assert n["text"] == "zweite äöü" and n["kind"] == "note" and n["ts"].endswith("+00:00")
    assert notes.latest("github.com/o/x", "b") is None


def test_broken_and_foreign_lines_skipped(cfg_dir):
    notes.add(U, "b", "ok")
    with (cfg_dir / "notes.ndjson").open("a", encoding="utf-8") as f:
        f.write('not json\n[1]\n{"url": 1}\n{"url":"u","branch":"b","ts":"t","text":"x","kind":"weird"}\n\n')
    notes.add(U, "b", "after")
    assert [n["text"] for n in notes.read_all()] == ["ok", "after"]


def test_closing_note_kind():
    notes.add(U, "b", "stand", "closing")
    assert notes.latest(U, "b")["kind"] == "closing"


def test_app_m_saves_note_and_shows_it(make_repo):
    root = make_repo("a", bare_layout=True)
    subprocess.run(["git", "-C", str(root), "worktree", "add", "-q", "main", "main"], check=True)
    save_repos({U: RepoConfig()})
    save_local(LocalConfig(paths={U: str(root)}))

    async def run():
        app = KvasirApp()
        async with app.run_test(size=(100, 20)) as pilot:
            for _ in range(50):
                await pilot.pause(0.1)
                if app.rows:
                    break
            app.query_one(EntryList).focus()
            await pilot.press("m")
            await pilot.pause()
            await pilot.press(*"wip", "enter")
            await pilot.pause()
            assert notes.latest(U, "main")["text"] == "wip"
            assert "wip" in str(app.query_one(EntryList).get_option_at_index(0).prompt)
            assert "wip" in str(app.query_one(DetailPanel).content)

    asyncio.run(run())
