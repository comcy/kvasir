import json
import subprocess
from pathlib import Path

import pytest

from kvasir.platform import (
    ErrorKind,
    GitHub,
    PlatformRepo,
    PullRequest,
    WorkItem,
    cache,
    detect_platform,
)
from kvasir.platform import gh as ghmod
from kvasir.platform.detect import work_item_for

FIX = Path(__file__).parent / "fixtures" / "gh"


def fx(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


class FakeRun:
    """Replaces subprocess.run in the gh module; answers are consumed in order."""

    def __init__(self, monkeypatch, *answers):
        self.answers, self.calls = list(answers), []
        monkeypatch.setattr(ghmod.subprocess, "run", self)

    def __call__(self, args, **kw):
        self.calls.append((args, kw))
        a = self.answers.pop(0)
        if isinstance(a, BaseException):
            raise a
        out, err, code = a
        return subprocess.CompletedProcess(args, code, out.encode(), err.encode())


def ok(text):
    return (text, "", 0)


def fail(text, code=1):
    return ("", text, code)


# --- detect ---

@pytest.mark.parametrize("url", [
    "git@github.com:comcy/kvasir.git", "https://github.com/comcy/kvasir", "ssh://git@github.com/comcy/kvasir.git",
    "https://GitHub.com/comcy/kvasir/",
])
def test_detect_github(url):
    assert detect_platform(url) == PlatformRepo("github", "comcy/kvasir")


@pytest.mark.parametrize("url", [
    "https://dev.azure.com/Org/My%20Proj/_git/Repo",
    "https://org@dev.azure.com/org/my proj/_git/repo.git",
    "git@ssh.dev.azure.com:v3/org/my%20proj/repo",
    "https://org.visualstudio.com/DefaultCollection/my proj/_git/repo",
    "org@vs-ssh.visualstudio.com:v3/org/my%20proj/repo",
    "https://dev.azure.com/org/my proj/_git/repo",  # registered key behind "https://", as platform_of passes it
])
def test_detect_azure(url):
    assert detect_platform(url) == PlatformRepo("azure", "org/my proj/repo", "org", "my proj", "repo")


@pytest.mark.parametrize("url", [
    "git@gitlab.com:o/r.git", "https://dev.azure.com/org/proj", "https://github.com/onlyowner", "nonsense",
])
def test_detect_other(url):
    assert detect_platform(url) is None


# --- work_item_for ---

def pr(branch, closing=()):
    return PullRequest(1, "t", "open", "u", "me", branch=branch, closing_issues=tuple(closing))


def test_work_item_from_branch_template():
    assert work_item_for("features/12-login", ["{type}/{slug}", "features/{id}-{slug}"], []) == 12


def test_work_item_template_wins_over_pr():
    assert work_item_for("features/12-x", ["features/{id}-{slug}"], [pr("features/12-x", [99])]) == 12


def test_work_item_non_numeric_id_falls_back_to_pr():
    assert work_item_for("feat/ABC-7-x", ["{type}/{id}-{slug}"], [pr("feat/ABC-7-x", [5])]) == 5


def test_work_item_from_pr_closing_issues():
    prs = [pr("other", [1]), pr("feat/x", [22, 23])]
    assert work_item_for("feat/x", ["{type}/{slug}"], prs) == 22


def test_work_item_none_and_bad_patterns():
    assert work_item_for("feat/x", ["{id}-{id}", "{nope}", "{type}/{slug}"], [pr("feat/x")]) is None


# --- runner ---

def test_runner_call_shape(monkeypatch):
    f = FakeRun(monkeypatch, ok("[]"))
    assert ghmod.run_gh("pr", "list").data == "[]"
    args, kw = f.calls[0]
    assert args == ["gh", "pr", "list"] and kw["timeout"] == ghmod.TIMEOUT
    assert kw["env"]["GH_PROMPT_DISABLED"] == "1" and kw["env"]["NO_COLOR"] == "1"
    assert kw["stdin"] == subprocess.DEVNULL


@pytest.mark.parametrize("answer,kind", [
    (FileNotFoundError(), ErrorKind.MISSING_CLI),
    (subprocess.TimeoutExpired("gh", 30), ErrorKind.NETWORK),
    (fail(fx("err_not_logged_in.txt"), 4), ErrorKind.NOT_LOGGED_IN),
    (fail(fx("err_missing_scope.txt")), ErrorKind.MISSING_SCOPE),
    (fail(fx("err_network.txt")), ErrorKind.NETWORK),
    (fail("API rate limit exceeded for user ID 1. (HTTP 403)"), ErrorKind.RATE_LIMIT),
    (fail(fx("err_not_found.txt")), ErrorKind.OTHER),
    (PermissionError("denied"), ErrorKind.OTHER),
])
def test_error_kinds(monkeypatch, answer, kind):
    FakeRun(monkeypatch, answer)
    r = ghmod.run_gh("x")
    assert not r.ok and r.data is None and r.error.kind is kind


def test_unparsable_output_is_error(monkeypatch):
    FakeRun(monkeypatch, ok("not json"))
    assert GitHub("o/r").pull_requests().error.kind is ErrorKind.OTHER


def test_unexpected_shape_is_error(monkeypatch):
    FakeRun(monkeypatch, ok('[{"number": 1}]'))
    assert GitHub("o/r").pull_requests().error.kind is ErrorKind.OTHER


# --- queries (fixtures = real gh 2.101 output) ---

def test_pull_requests(monkeypatch):
    f = FakeRun(monkeypatch, ok(fx("pr_list_kvasir.json")))
    r = GitHub("comcy/kvasir").pull_requests(limit=3)
    args = f.calls[0][0]
    assert args[:6] == ["gh", "pr", "list", "-R", "comcy/kvasir", "--state"] and ghmod.PR_FIELDS in args
    p = r.data[0]
    assert (p.number, p.state, p.branch, p.author, p.review, p.checks) == (
        23, "merged", "feat/22-tui-layout", "comcy", None, None)
    assert p.closing_issues == (22,)


def test_pull_requests_checks_and_states(monkeypatch):
    FakeRun(monkeypatch, ok(fx("pr_list_skiclub.json")))
    prs = {p.number: p for p in GitHub("comcy/skiclub-kapfenburg.de").pull_requests().data}
    assert prs[177].state == "open" and prs[177].checks == "success"
    assert prs[175].state == "merged" and prs[175].checks == "failure"  # one failed check
    assert prs[174].state == "closed"


def test_checks_pending_status_context_and_draft():
    d = {"number": 1, "title": "t", "state": "OPEN", "isDraft": True, "url": "u", "reviewDecision": "APPROVED",
         "statusCheckRollup": [{"status": "COMPLETED", "conclusion": "SUCCESS"},
                               {"state": "PENDING", "context": "ci"}]}
    p = ghmod.parse_pr(d)
    assert (p.state, p.review, p.checks) == ("draft", "approved", "pending")
    d["statusCheckRollup"] = [{"state": "ERROR"}]
    assert ghmod.parse_pr(d).checks == "failure"


def test_work_item(monkeypatch):
    f = FakeRun(monkeypatch, ok(fx("issue_view.json")))
    w = GitHub("comcy/kvasir").work_item(27).data
    assert f.calls[0][0][-1] == ghmod.ISSUE_BOARD_FIELDS
    assert w == WorkItem(27, "Plattform-Fundament: gh-Zugriff, Datenmodell, Cache (GitHub)", "open",
                         "https://github.com/comcy/kvasir/issues/27",
                         labels=("enhancement", "ready-for-agent"), board_status=None, board_available=True)


def test_work_item_board_status():
    d = json.loads(fx("issue_view.json"))
    d["projectItems"] = [{"status": {"name": "In Progress", "optionId": "x"}, "title": "Board"}]
    assert ghmod.parse_work_item(d).board_status == "In Progress"


def test_work_item_missing_read_project_degrades(monkeypatch):
    f = FakeRun(monkeypatch, fail(fx("err_missing_scope.txt")), ok(fx("issue_view.json")))
    r = GitHub("comcy/kvasir").work_item(27)
    assert r.ok and r.data.board_available is False and r.data.board_status is None
    assert r.data.labels == ("enhancement", "ready-for-agent")  # status/labels still shown
    assert f.calls[1][0][-1] == ghmod.ISSUE_FIELDS


def test_work_item_other_error_passes_through(monkeypatch):
    FakeRun(monkeypatch, fail(fx("err_not_found.txt")))
    assert GitHub("o/r").work_item(1).error.kind is ErrorKind.OTHER


def test_pipeline_runs_own_only(monkeypatch):
    f = FakeRun(monkeypatch, ok(fx("api_user.txt")), ok(fx("run_list.json")))
    r = GitHub("comcy/skiclub-kapfenburg.de").pipeline_runs(days=7, limit=3)
    assert f.calls[0][0] == ["gh", "api", "user", "--jq", ".login"]
    args = f.calls[1][0]
    assert args[args.index("--user") + 1] == "comcy" and args[args.index("--created") + 1].startswith(">=")
    run = r.data[0]
    assert (run.status, run.conclusion, run.duration_s) == ("completed", "success", 126)
    assert run.workflow == "SCK-WEB Workflow" and run.started_at == "2026-04-04T08:14:15Z"


def test_pipeline_runs_login_error(monkeypatch):
    FakeRun(monkeypatch, fail(fx("err_not_logged_in.txt"), 4))
    assert GitHub("o/r").pipeline_runs().error.kind is ErrorKind.NOT_LOGGED_IN


def test_running_run_has_no_conclusion():
    run = ghmod.parse_run({"workflowName": "w", "headBranch": "b", "status": "in_progress", "conclusion": "",
                           "url": "u", "startedAt": "2026-01-01T00:00:00Z", "updatedAt": "2026-01-01T00:01:00Z"})
    assert run.conclusion is None and run.status == "in_progress"


def test_search(monkeypatch):
    f = FakeRun(monkeypatch, ok(fx("search_prs.json")), ok("[]"))
    g = GitHub("comcy/kvasir")
    mine = g.my_pull_requests().data
    assert mine[0].repo == "comcy/kvasir" and mine[0].state == "merged" and mine[0].branch is None
    assert f.calls[0][0][:5] == ["gh", "search", "prs", "--author", "@me"]
    assert g.review_requests().data == []
    assert "--review-requested" in f.calls[1][0]


def test_pull_request_view(monkeypatch):
    f = FakeRun(monkeypatch, ok(fx("pr_view.json")), fail("HTTP 404: Not Found"), ok("{}"))
    g = GitHub("comcy/kvasir")
    p = g.pull_request(23).data
    assert (p.number, p.branch, p.repo, p.state, p.review, p.checks) == (
        23, "feat/22-tui-layout", "comcy/kvasir", "merged", None, None)
    assert p.created_at == "2026-10-02T16:28:34Z" and p.closing_issues == (22,)
    assert f.calls[0][0][:7] == ["gh", "pr", "view", "23", "-R", "comcy/kvasir", "--json"]
    assert g.pull_request(1).error.kind is ErrorKind.OTHER  # error object, no exception
    assert g.pull_request(2).error.kind is ErrorKind.OTHER  # unexpected output


# --- cache ---

U = "github.com/o/r"


def test_cache_roundtrip_with_tuples(cfg_dir):
    assert cache.read(U, "pull_requests", PullRequest) is None
    cache.write(U, "pull_requests", [PullRequest(1, "t", "open", "u", "me", closing_issues=(2, 3))])
    e = cache.read(U, "pull_requests", PullRequest)
    assert e.items == [PullRequest(1, "t", "open", "u", "me", closing_issues=(2, 3))]
    assert e.fetched_at.tzinfo is not None and e.fetched_at.year >= 2026
    assert (cfg_dir / "platform_cache.json").exists()


def test_cache_keys_are_independent(cfg_dir):
    cache.write(U, "a", [pr("x")])
    cache.write(U, "b", [pr("y")])
    cache.write("github.com/o/other", "a", [pr("z")])
    assert cache.read(U, "a", PullRequest).items[0].branch == "x"
    assert cache.read(U, "b", PullRequest).items[0].branch == "y"
    assert cache.read("github.com/o/other", "a", PullRequest).items[0].branch == "z"


def test_cache_fetched_at_updates(cfg_dir):
    cache.write(U, "a", [])
    t1 = cache.read(U, "a", PullRequest).fetched_at
    cache.write(U, "a", [])
    assert cache.read(U, "a", PullRequest).fetched_at >= t1


@pytest.mark.parametrize("content", ["{not json", "[1, 2]", '{"github.com/o/r": 5}',
                                     '{"github.com/o/r": {"a": {"fetched_at": "bad", "items": []}}}',
                                     '{"github.com/o/r": {"a": {"fetched_at": "2026-01-01T00:00:00+00:00", "items": [{"x": 1}]}}}'])
def test_cache_tolerates_broken_file(cfg_dir, content):
    cfg_dir.mkdir()
    (cfg_dir / "platform_cache.json").write_text(content)
    assert cache.read(U, "a", PullRequest) is None
    cache.write(U, "a", [pr("ok")])  # recovers by overwriting
    assert cache.read(U, "a", PullRequest).items[0].branch == "ok"


def test_cache_atomic_write_keeps_old_file_on_failure(cfg_dir, monkeypatch):
    cache.write(U, "a", [pr("old")])

    def boom(*a):
        raise OSError("disk")

    with monkeypatch.context() as m:
        m.setattr(cache.os, "replace", boom)
        with pytest.raises(OSError):
            cache.write(U, "a", [pr("new")])
    assert cache.read(U, "a", PullRequest).items[0].branch == "old"
    assert [p.name for p in cfg_dir.iterdir()] == ["platform_cache.json"]  # temp file cleaned up
