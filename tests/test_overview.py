"""Overview page (#29): pure list building, refresh/cache merge, and the screen. No network."""
import asyncio
import subprocess
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from textual.widgets import OptionList

from kvasir.config import LocalConfig, RepoConfig, save_local, save_repos
from kvasir.platform import Error, ErrorKind, PipelineRun, PullRequest, Result, cache
from kvasir.tui import overview_data as od
from kvasir.tui.app import KvasirApp
from kvasir.tui.columns import EntryList
from kvasir.tui.overview_screen import OverviewScreen
from kvasir.worktrees import Branch, RepoView, Worktree

URL = "github.com/o/a"
NOW = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)
AGO3H = (NOW - timedelta(hours=3)).isoformat()


def spr(n, repo="o/a", **kw):
    """Search result: no branch/review/checks."""
    return PullRequest(n, f"Title {n}", "open", f"https://x/{repo}/pull/{n}", "me", repo=repo, created_at=AGO3H, **kw)


def full(n, repo="o/a", **kw):
    return replace(spr(n, repo), branch=f"feat/{n}", **kw)


def run(repo="o/a", branch="main", status="completed", conclusion="success", started=AGO3H, dur=94):
    return PipelineRun("CI", branch, status, conclusion, f"https://x/{repo}/run", started, dur, repo)


class Fake:
    def __init__(self, mine=(), reviews=(), details=None, runs=(), error=None):
        self.mine, self.reviews, self.details, self.runs, self.error = list(mine), list(reviews), details or {}, runs, error
        self.calls = []

    def _res(self, name, data):
        self.calls.append(name)
        return Result(error=self.error) if self.error else Result(data=data)

    def my_pull_requests(self, limit=30):
        return self._res("mine", self.mine)

    def review_requests(self, limit=30):
        return self._res("reviews", self.reviews)

    def pull_request(self, number):
        self.calls.append(f"pr{number}")
        if number in self.details:
            return Result(data=self.details[number])
        return Result(error=Error(ErrorKind.OTHER, "nf"))

    def pipeline_runs(self, days=7, limit=20):
        return self._res("runs", self.runs)

    def pull_requests(self, limit=30):  # main view's own refresh
        return Result(data=[])

    def work_item(self, number):
        return Result(error=Error(ErrorKind.OTHER, "nf"))


# --- pure ---

def test_pr_entry_columns():
    e = od.pr_entry(full(7, review="changes_requested", checks="failure"), 5, 12, NOW.timestamp())
    assert e.text == "o/a    #7     Title 7       changes requested  ✗    3h"
    assert e.url == "https://x/o/a/pull/7" and e.repo == "o/a" and e.branch == "feat/7"
    t = od.pr_entry(full(8, review="approved", checks="success"), 5, 12, NOW.timestamp(), True).text
    assert "approved" in t and "✓" in t and "@me" in t
    t = od.pr_entry(spr(9), 5, 12, NOW.timestamp()).text
    assert "ausstehend" in t and "  -  " in t  # no checks known
    assert "draft" in od.pr_entry(full(1, state="draft"), 5, 12).text
    assert "ausstehend" in od.pr_entry(full(2, review="review_required"), 5, 12).text


def test_run_entry_columns():
    t = od.run_entry(run(), 5, 4, 6, NOW.timestamp()).text
    assert t == "o/a    CI    main    ✓ completed      1m34s    3h"
    assert od.run_symbol(run(status="in_progress", conclusion=None)) == "…"
    assert od.run_symbol(run(conclusion="failure")) == "✗"
    assert od.run_symbol(run(conclusion="cancelled")) == "cancelled"
    assert od.run_entry(run(dur=None), 5, 4, 6, NOW.timestamp()).text.count("-") >= 1


def test_sections_three_blocks_and_width():
    ov = od.Overview([full(1)], [full(2, review="approved")], [run()])
    s = od.sections(ov, 60, NOW.timestamp())
    assert [t for t, _ in s] == list(od.SECTIONS)
    assert all(len(e.text) <= 60 for _, es in s for e in es)
    assert "@me" in s[1][1][0].text and "@me" not in s[0][1][0].text
    assert [len(es) for _, es in s] == [1, 1, 1]


def test_status_text():
    assert od.status_text(od.Overview(), 0) == "Kein GitHub-Repo registriert."
    assert "noch nicht geladen" in od.status_text(od.Overview(), 1)
    ov = od.Overview(fetched_at=NOW, error=Error(ErrorKind.MISSING_CLI))
    t = od.status_text(ov, 1, NOW.timestamp() + 180)
    assert "aktualisiert vor 3m" in t and "gh nicht gefunden" in t
    assert "gh auth login" in od.status_text(od.Overview(error=Error(ErrorKind.NOT_LOGGED_IN)), 1)


def test_find_local():
    wt = Worktree(path=__import__("pathlib").Path("/x"), branch="main")
    view = RepoView(worktrees=[wt], branches=[Branch("feat/1", False, 0, ""), Branch("origin/feat/2", True, 0, "")])
    rows = [od.RepoRow(URL, None, view)]
    assert od.find_local(rows, URL, "main") == (0, 0)
    assert od.find_local(rows, URL, "feat/1") == (0, 1)
    assert od.find_local(rows, URL, "feat/2") is None  # only a remote branch
    assert od.find_local(rows, URL, None) is None and od.find_local(rows, "github.com/o/zz", "main") is None


# --- data ---

def test_refresh_filters_enriches_caches(monkeypatch):
    f = Fake(mine=[spr(1), spr(2, "x/unregistered")], reviews=[spr(3), spr(1)],
             details={1: full(1, review="approved", checks="success"), 3: full(3)},
             runs=[run(started=AGO3H), run(started=(NOW - timedelta(hours=1)).isoformat())])
    monkeypatch.setattr("kvasir.tui.platform_data.provider_for", lambda repo: f)
    assert od.refresh([URL, "dev.azure.com/o/p/r"]) is None
    assert f.calls == ["mine", "pr1", "reviews", "pr3", "runs"]  # unregistered skipped, #1 fetched once
    ov = od.snapshot([URL])
    assert [p.number for p in ov.mine] == [1] and ov.mine[0].review == "approved" and ov.mine[0].checks == "success"
    assert ov.mine[0].branch == "feat/1" and ov.mine[0].created_at == AGO3H
    assert [p.number for p in ov.reviews] == [3, 1]
    assert [r.started_at for r in ov.runs] == sorted((r.started_at for r in ov.runs), reverse=True)
    assert ov.runs[0].repo == "o/a" and ov.fetched_at is not None
    assert od.snapshot(["github.com/o/other"]).mine == []  # only registered repos


def test_refresh_caps_each_list(monkeypatch):
    f = Fake(mine=[spr(n) for n in range(1, 40)], details={n: full(n) for n in range(1, 40)})
    monkeypatch.setattr("kvasir.tui.platform_data.provider_for", lambda repo: f)
    od.refresh([URL])
    assert len(od.snapshot([URL]).mine) == od.MAX_ITEMS
    assert f.calls.count("mine") == 1 and sum(c.startswith("pr") for c in f.calls) == od.MAX_ITEMS


def test_refresh_non_fatal_detail_error_keeps_search_row(monkeypatch):
    f = Fake(mine=[spr(1)])
    monkeypatch.setattr("kvasir.tui.platform_data.provider_for", lambda repo: f)
    assert od.refresh([URL]).kind is ErrorKind.OTHER
    assert od.snapshot([URL]).mine[0].number == 1 and od.snapshot([URL]).mine[0].checks is None


def test_refresh_error_keeps_old_cache(monkeypatch):
    cache.write(od.KEY, "my_prs", [full(5)])
    e = Error(ErrorKind.NETWORK, "down")
    f = Fake(error=e)
    monkeypatch.setattr("kvasir.tui.platform_data.provider_for", lambda repo: f)
    assert od.refresh([URL]) == e
    assert f.calls == ["mine"]
    assert od.snapshot([URL], e).mine[0].number == 5


def test_refresh_without_gh_or_github_repo():
    assert od.refresh([URL]).kind is ErrorKind.MISSING_CLI  # conftest default: gh missing
    assert od.refresh(["dev.azure.com/o/p/r"]) is None


def test_is_stale():
    assert od.is_stale(od.Overview(), 10)
    assert not od.is_stale(od.Overview(fetched_at=datetime.fromtimestamp(time.time(), UTC)), 10)


# --- screen ---

def _register(make_repo):
    root = make_repo("a", bare_layout=True)
    subprocess.run(["git", "-C", str(root), "worktree", "add", "-q", "main", "main"], check=True)
    save_repos({URL: RepoConfig()})
    save_local(LocalConfig(paths={URL: str(root)}))


async def _wait(pilot, cond, n=60):
    for _ in range(n):
        await pilot.pause(0.1)
        if cond():
            return
    raise AssertionError("timeout")


def _texts(screen):
    lst = screen.query_one(OptionList)
    return [str(lst.get_option_at_index(i).prompt) for i in range(lst.option_count)]


def _fake(monkeypatch):
    f = Fake(mine=[spr(1), spr(2)], reviews=[spr(3)],
             details={1: replace(full(1, review="approved", checks="success"), branch="main"),
                      2: full(2), 3: full(3)}, runs=[run()])
    monkeypatch.setattr("kvasir.tui.platform_data.provider_for", lambda repo: f)
    return f


def test_i_opens_page_u_refreshes_esc_closes(make_repo, monkeypatch):
    _register(make_repo)
    f = _fake(monkeypatch)

    async def go():
        app = KvasirApp()
        async with app.run_test(size=(140, 30)) as pilot:
            await _wait(pilot, lambda: app.rows)
            await pilot.press("i")
            assert isinstance(app.screen, OverviewScreen)
            await _wait(pilot, lambda: any("Title 3" in t for t in _texts(app.screen)))
            t = _texts(app.screen)
            assert t[0].startswith("Meine offenen PRs (2)") and any(x.startswith("Zum Review angefragt (1)") for x in t)
            assert any("approved" in x and "✓" in x for x in t) and any("Pipeline-Läufe" in x for x in t)
            n = f.calls.count("mine")
            await pilot.press("u")
            await _wait(pilot, lambda: f.calls.count("mine") == n + 1)
            await pilot.press("escape")
            assert not isinstance(app.screen, OverviewScreen)

    asyncio.run(go())


def test_enter_opens_browser_and_c_jumps_to_local_branch(make_repo, monkeypatch):
    _register(make_repo)
    _fake(monkeypatch)
    opened = []
    monkeypatch.setattr("kvasir.tui.overview_screen.webbrowser.open", opened.append)

    async def go():
        app = KvasirApp()
        async with app.run_test(size=(140, 30)) as pilot:
            await _wait(pilot, lambda: app.rows)
            await pilot.press("i")
            await _wait(pilot, lambda: any("Title 2" in t for t in _texts(app.screen)))
            await pilot.press("down")  # starts on #1 (branch main); #2 has branch feat/2
            assert app.screen.entries[0].branch == "main"
            await pilot.press("enter")
            assert opened == ["https://x/o/a/pull/2"]
            await pilot.press("c")  # feat/2 has no local branch: stay, hint
            assert isinstance(app.screen, OverviewScreen)
            await pilot.press("up", "c")
            await _wait(pilot, lambda: not isinstance(app.screen, OverviewScreen))
            el = app.query_one(EntryList)
            assert app.entries[el.current_entry()].branch == "main"

    asyncio.run(go())


def test_page_hints_without_gh_and_without_github_repo(make_repo):
    _register(make_repo)  # conftest default provider: gh missing

    async def go():
        app = KvasirApp()
        async with app.run_test(size=(140, 30)) as pilot:
            await _wait(pilot, lambda: app.rows)
            await pilot.press("i")
            await _wait(pilot, lambda: "gh nicht gefunden" in str(app.screen.query_one("#ov-status").content))
            assert any("keine" in t for t in _texts(app.screen))
            await pilot.press("escape")
        save_repos({})
        app = KvasirApp()
        async with app.run_test(size=(140, 30)) as pilot:
            await pilot.pause(0.3)
            await pilot.press("i")
            assert "Kein GitHub-Repo" in str(app.screen.query_one("#ov-status").content)

    asyncio.run(go())
