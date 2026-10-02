"""Platform data in the TUI (#28): pure view functions, data merge, and the app. No network."""
import asyncio
import subprocess
from datetime import UTC, datetime

from kvasir.config import LocalConfig, RepoConfig, load_repos, save_local, save_repos
from kvasir.platform import Error, ErrorKind, PipelineRun, PullRequest, Result, WorkItem, cache
from kvasir.tui import platform_data as pd
from kvasir.tui import platform_view as pv
from kvasir.tui.app import KvasirApp
from kvasir.tui.columns import DetailPanel, EntryList, RepoList
from kvasir.tui.layout import format_entry
from kvasir.worktrees import Branch, Worktree

URL = "github.com/o/a"


def pr(n=12, state="open", checks="success", branch="main", **kw):
    return PullRequest(n, "Fix it", state, f"https://x/{n}", "me", branch=branch, checks=checks, **kw)


def run(branch="main", status="completed", conclusion="success"):
    return PipelineRun("ci", branch, status, conclusion, "https://x/r", datetime.now(UTC).isoformat(), 34)


class Fake:
    """Provider with canned answers and call counters."""

    def __init__(self, prs=(), runs=(), items=None, error=None):
        self.prs, self.runs, self.items, self.error = list(prs), list(runs), items or {}, error
        self.calls = []

    def _res(self, name, data):
        self.calls.append(name)
        return Result(error=self.error) if self.error else Result(data=data)

    def pull_requests(self, limit=30):
        return self._res("prs", self.prs)

    def pipeline_runs(self, days=7, limit=20):
        return self._res("runs", self.runs)

    def work_item(self, number):
        self.calls.append(f"wi{number}")
        if self.error:
            return Result(error=self.error)
        return Result(data=self.items[number]) if number in self.items else Result(error=Error(ErrorKind.OTHER, "nf"))


# --- pure view ---

def test_marker():
    assert pv.marker(None) == ""
    assert pv.marker(pr(checks="success")) == "#12 ✓"
    assert pv.marker(pr(checks="failure")) == "#12 ✗"
    assert pv.marker(pr(checks="pending")) == "#12 …"
    assert pv.marker(pr(checks=None)) == "#12"
    assert pv.marker(pr(state="draft")) == "draft"
    assert pv.marker(pr(state="merged")) == "#12 merged"


def test_format_entry_keeps_alignment_with_marker_column():
    w = Worktree(path=__import__("pathlib").Path("/x"), branch="main", commit_ts=0, subject="s")
    b = Branch("loc", False, 0, "t")
    lines = [format_entry(w, 6, "", "#12 ✓", 5), format_entry(b, 6, "", "", 5)]
    assert lines[0].index("s") == lines[1].index("t")  # subject column identical with and without marker
    assert format_entry(w, 6) == format_entry(w, 6, "", "", 0)  # no marker column unless reserved


def _info(**kw):
    base = {"pr": None, "work_item": None, "work_item_number": None, "runs": (), "loaded": True}
    return pd.BranchInfo(**{**base, **kw})


def test_detail_text_empty_says_none():
    t = pv.detail_text(_info())
    assert "kein PR" in t and "kein Work Item" in t and "keine Läufe" in t


def test_detail_text_full():
    wi = WorkItem(3, "Bug", "open", "u", ("bug",), ("me",), "In Progress")
    t = pv.detail_text(_info(pr=pr(review="approved", checks="failure"), work_item=wi, work_item_number=3,
                             runs=(run(), run(conclusion="failure"))))
    assert "PR #12  Fix it" in t and "offen" in t and "Review: approved" in t and "Checks: ✗" in t
    assert "Work Item #3  Bug" in t and "Labels: bug" in t and "Zugewiesen: me" in t and "Board: In Progress" in t
    assert "  ✓ ci" in t and "  ✗ ci" in t


def test_detail_text_board_unavailable_not_loaded_and_error():
    wi = WorkItem(3, "Bug", "closed", "u", board_available=False)
    t = pv.detail_text(_info(work_item=wi, work_item_number=3), Error(ErrorKind.NOT_LOGGED_IN))
    assert "geschlossen" in t and "nicht verfügbar (read:project fehlt)" in t and "! gh nicht angemeldet" in t
    assert "noch nicht geladen" in pv.detail_text(_info(loaded=False))


def test_repo_line():
    snap = pd.Snapshot([], [], {}, [], datetime.now(UTC))
    assert pv.repo_line(snap).startswith("gh: aktualisiert vor")
    snap = pd.Snapshot([], [], {}, [], None, Error(ErrorKind.MISSING_CLI))
    assert pv.repo_line(snap) == "gh: noch nicht geladen\ngh nicht gefunden"


# --- data ---

def test_refresh_fills_cache_and_snapshot_merges():
    f = Fake([pr(branch="feat/3-x", closing_issues=(3,)), pr(9, "merged", branch="feat/3-x")],
             [run("feat/3-x")], {3: WorkItem(3, "Bug", "open", "u")})
    assert pd.refresh(URL, ["{type}/{slug}"], ["feat/3-x", "main"], f) is None
    assert f.calls == ["prs", "runs", "wi3"]  # one list each, issue only for the branch with an id
    s = pd.snapshot(URL, ["{type}/{slug}"], ["feat/3-x", "main"])
    i = s.info("feat/3-x")
    assert i.pr.number == 12 and i.work_item.title == "Bug" and len(i.runs) == 1 and i.loaded
    assert s.info("main").pr is None and s.info("main").work_item_number is None


def test_refresh_error_keeps_old_cache():
    pd.refresh(URL, ["{type}/{slug}"], ["main"], Fake([pr()]))
    e = Error(ErrorKind.NETWORK, "down")
    f = Fake(error=e)
    assert pd.refresh(URL, ["{type}/{slug}"], ["main"], f) == e
    assert f.calls == ["prs"]  # fatal: no further calls
    s = pd.snapshot(URL, ["{type}/{slug}"], ["main"], e)
    assert s.info("main").pr.number == 12 and s.error == e


def test_refresh_unknown_issue_is_not_an_error():
    f = Fake([pr()])
    assert pd.refresh(URL, ["features/{id}-{slug}"], ["features/99-x"], f) is None


def test_snapshot_without_cache_is_not_loaded():
    s = pd.snapshot(URL, [], ["main"])
    assert s.fetched_at is None and not s.info("main").loaded


def test_branch_of():
    assert pd.branch_of(Branch("origin/feat/x", True, 0, "")) == "feat/x"
    assert pd.branch_of(Branch("origin/HEAD", True, 0, "")) is None
    assert pd.branch_of(Branch("loc", False, 0, "")) == "loc"
    assert pd.branch_of(Worktree(path=__import__("pathlib").Path("/x"))) is None


def test_config_platform_interval_roundtrip_and_old_files(cfg_dir):
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "repos.toml").write_text('["github.com/o/a"]\nbranch_patterns = ["{type}/{slug}"]\nfetch_interval = 5\n')
    assert load_repos()[URL].platform_interval == 10  # old file: default
    save_repos({URL: RepoConfig(platform_interval=3)})
    assert load_repos()[URL].platform_interval == 3


# --- app ---

def _register(make_repo):
    root = make_repo("a", bare_layout=True)
    subprocess.run(["git", "-C", str(root), "worktree", "add", "-q", "main", "main"], check=True)
    save_repos({URL: RepoConfig()})
    save_local(LocalConfig(paths={URL: str(root)}))
    return root


async def _wait(pilot, cond, n=60):
    for _ in range(n):
        await pilot.pause(0.1)
        if cond():
            return
    raise AssertionError("timeout")


def test_app_shows_cache_marker_detail_and_u_refreshes(make_repo, monkeypatch):
    _register(make_repo)
    cache.write(URL, "pull_requests", [pr()])  # old state, shown before any refresh
    cache.write(URL, "pipeline_runs", [run()])
    f = Fake([pr(13, checks="failure")], [run(conclusion="failure")])
    monkeypatch.setattr("kvasir.tui.platform_data.provider_for", lambda repo: f)

    async def go():
        app = KvasirApp()
        async with app.run_test(size=(120, 25)) as pilot:
            await _wait(pilot, lambda: app.rows and f.calls)  # initial background refresh ran
            await _wait(pilot, lambda: "#13 ✗" in str(app.query_one(EntryList).get_option_at_index(1).prompt))
            detail = str(app.query_one(DetailPanel).content)
            assert "PR #13  Fix it" in detail and "kein Work Item" in detail and "✗ ci" in detail
            assert "gh: aktualisiert vor" in str(app.query_one(RepoList).get_option_at_index(0).prompt)
            n = f.calls.count("prs")
            f.prs = [pr(14, checks="pending")]
            await pilot.press("u")
            await _wait(pilot, lambda: f.calls.count("prs") == n + 1)
            await _wait(pilot, lambda: "#14 …" in str(app.query_one(EntryList).get_option_at_index(1).prompt))

    asyncio.run(go())


def test_app_cache_only_while_refresh_fails_without_gh(make_repo):
    _register(make_repo)
    cache.write(URL, "pull_requests", [pr()])  # conftest default provider = gh missing

    async def go():
        app = KvasirApp()
        async with app.run_test(size=(120, 25)) as pilot:
            await _wait(pilot, lambda: app.platform.get(URL) and app.platform[URL].error)
            await pilot.pause(0.2)
            line = str(app.query_one(RepoList).get_option_at_index(0).prompt)
            assert "gh nicht gefunden" in line and "aktualisiert vor" in line  # hint + old state
            assert "#12 ✓" in str(app.query_one(EntryList).get_option_at_index(1).prompt)  # old state stays

    asyncio.run(go())


def test_app_no_cache_no_gh_shows_hint_not_none(make_repo):
    _register(make_repo)

    async def go():
        app = KvasirApp()
        async with app.run_test(size=(120, 25)) as pilot:
            await _wait(pilot, lambda: app.platform.get(URL) and app.platform[URL].error)
            detail = str(app.query_one(DetailPanel).content)
            assert "noch nicht geladen" in detail and "kein PR" not in detail

    asyncio.run(go())
