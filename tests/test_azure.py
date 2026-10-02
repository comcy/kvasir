"""Azure DevOps provider (#43): parsers against tests/fixtures/az (documentation-derived, not live), `run_az`,
error kinds, mapping of votes/policies. `subprocess.run` is mocked; `az` is never started."""
import json
import subprocess
from pathlib import Path

import pytest

from kvasir.platform import (
    Azure,
    ErrorKind,
    PlatformRepo,
    PullRequest,
    detect_platform,
    provider_for,
    work_item_for,
)
from kvasir.platform import az as azmod
from kvasir.platform.az import checks_of, review_of

FIX = Path(__file__).parent / "fixtures" / "az"
REPO = PlatformRepo("azure", "contoso/shop/webapp", "contoso", "Shop", "webapp")
ORG = "https://dev.azure.com/contoso"


def fx(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


class Router:
    """Replaces subprocess.run in the az module; `routes` = [(substring of the joined args, answer)]."""

    def __init__(self, monkeypatch, *routes):
        self.routes, self.calls, self.kw = list(routes), [], []
        monkeypatch.setattr(azmod.subprocess, "run", self)

    def __call__(self, args, **kw):
        line = " ".join(args)
        self.calls.append(line)
        self.kw.append(kw)
        for key, a in self.routes:
            if key in line:
                if isinstance(a, BaseException):
                    raise a
                out, err, code = a
                return subprocess.CompletedProcess(args, code, out.encode(), err.encode())
        raise AssertionError(f"unexpected az call: {line}")


def ok(text):
    return (text, "", 0)


def fail(text, code=1):
    return ("", text, code)


WHO = ("account show", ok(fx("account_user.txt")))
ENRICH = [("pr policy list", ok(fx("pr_policy_list.json"))), ("pr work-item list", ok(fx("pr_work_items.json")))]


# --- provider_for / detect ---

def test_provider_for_azure_and_github():
    assert isinstance(provider_for(REPO), Azure)
    assert provider_for(REPO).org_url == ORG
    assert provider_for(PlatformRepo("github", "o/r")).__class__.__name__ == "GitHub"
    assert detect_platform("https://dev.azure.com/contoso/Shop/_git/webapp") == PlatformRepo(
        "azure", "contoso/shop/webapp", "contoso", "shop", "webapp")  # identity is lower-case (names are case-insensitive)


# --- run_az / errors ---

def test_run_az_is_non_interactive_list_with_timeout(monkeypatch):
    r = Router(monkeypatch, ("account", ok("x")))
    assert azmod.run_az("account", "show").data == "x"
    args = r.calls[0].split()
    assert args[0] == "az" and "--only-show-errors" in args
    kw = r.kw[0]
    assert kw["stdin"] == subprocess.DEVNULL and kw["timeout"] == azmod.TIMEOUT and "shell" not in kw
    assert kw["env"]["AZURE_CORE_NO_COLOR"] == "true" and kw["env"]["AZURE_EXTENSION_USE_DYNAMIC_INSTALL"] == "no"


@pytest.mark.parametrize(("exc", "kind"), [
    (FileNotFoundError(), ErrorKind.MISSING_CLI),
    (subprocess.TimeoutExpired("az", 1), ErrorKind.NETWORK),
    (PermissionError("x"), ErrorKind.OTHER),
])
def test_run_az_exceptions(monkeypatch, exc, kind):
    Router(monkeypatch, ("", exc))
    res = azmod.run_az("x")
    assert not res.ok and res.error.kind is kind and res.error.cli == "az"


@pytest.mark.parametrize(("name", "kind"), [
    ("err_not_logged_in.txt", ErrorKind.NOT_LOGGED_IN),
    ("err_devops_login.txt", ErrorKind.NOT_LOGGED_IN),
    ("err_missing_extension.txt", ErrorKind.MISSING_EXTENSION),
    ("err_network.txt", ErrorKind.NETWORK),
    ("err_rate_limit.txt", ErrorKind.RATE_LIMIT),
])
def test_error_kinds_from_fixtures(monkeypatch, name, kind):
    Router(monkeypatch, ("", fail(fx(name))))
    res = azmod.run_az("repos", "pr", "list")
    assert res.error.kind is kind and res.error.cli == "az"


def test_other_error_and_unparsable_output(monkeypatch):
    Router(monkeypatch, ("pr list", fail("ERROR: something odd")))
    assert Azure("contoso", "Shop", "webapp").pull_requests().error.kind is ErrorKind.OTHER
    Router(monkeypatch, ("pr list", ok("not json")))
    assert Azure("contoso", "Shop", "webapp").pull_requests().error.kind is ErrorKind.OTHER
    Router(monkeypatch, ("pr list", ok('[{"nope": 1}]')))  # unexpected shape: error result, no exception
    assert Azure("contoso", "Shop", "webapp").pull_requests().error.kind is ErrorKind.OTHER


# --- review / checks mapping ---

@pytest.mark.parametrize(("votes", "want"), [
    ([10], "approved"), ([5], "approved"), ([0], "review_required"), ([-5], "changes_requested"),
    ([-10], "changes_requested"), ([10, -5], "changes_requested"), ([10, 0], "approved"), ([], None),
])
def test_review_of_votes(votes, want):
    assert review_of([{"vote": v} for v in votes]) == want


def test_review_of_ignores_groups_and_missing_vote():
    assert review_of([{"isContainer": True, "vote": 0}]) is None
    assert review_of([{"displayName": "x"}]) == "review_required"
    assert review_of(None) is None


def test_checks_of():
    assert checks_of(json.loads(fx("pr_policy_list.json"))) == "pending"  # running blocking; rejected one is optional
    assert checks_of([{"status": "approved"}]) == "success"
    assert checks_of([{"status": "approved"}, {"status": "rejected"}]) == "failure"
    assert checks_of([{"status": "notApplicable"}]) is None and checks_of([]) is None and checks_of(None) is None


# --- pull requests ---

def test_pull_requests_parse_and_enrich(monkeypatch):
    r = Router(monkeypatch, ("pr list", ok(fx("pr_list.json"))), *ENRICH)
    res = Azure("contoso", "Shop", "webapp").pull_requests(50)
    assert res.ok
    first = r.calls[0]
    assert "repos pr list" in first and f"--organization {ORG}" in first and "--project Shop" in first
    assert "--repository webapp" in first and "--status all" in first and "--top 50" in first
    prs = {p.number: p for p in res.data}
    assert [p.state for p in res.data] == ["open", "draft", "merged", "closed", "open"]
    p = prs[42]
    assert p.title == "Warenkorb: Rabatte" and p.branch == "feature/101-rabatte" and p.author == "Anna Beispiel"
    assert p.url == f"{ORG}/Shop/_git/webapp/pullrequest/42" and p.repo == "contoso/shop/webapp"
    assert p.created_at == "2026-10-01T09:15:03.1234567Z"
    assert p.review == "approved" and prs[38].review == "changes_requested" and prs[39].review == "changes_requested"
    assert prs[42].checks == "pending" and prs[42].closing_issues == (101,)  # enriched (open)
    assert prs[40].checks is None and prs[40].closing_issues == ()  # merged: no extra calls
    assert sum("policy list" in c for c in r.calls) == 3  # the three open/draft PRs only


def test_pull_requests_enrichment_failure_is_not_an_error(monkeypatch):
    Router(monkeypatch, ("pr list", ok(fx("pr_list.json"))), ("pr policy", fail("ERROR: boom")),
           ("pr work-item", fail("ERROR: boom")))
    res = Azure("contoso", "Shop", "webapp").pull_requests()
    assert res.ok and res.data[0].checks is None and res.data[0].closing_issues == ()


def test_pull_request_detail(monkeypatch):
    r = Router(monkeypatch, ("pr show", ok(fx("pr_show.json"))), *ENRICH)
    res = Azure("contoso", "Shop", "webapp").pull_request(42)
    assert "repos pr show --id 42" in r.calls[0] and f"--organization {ORG}" in r.calls[0]
    assert res.data.number == 42 and res.data.review == "approved" and res.data.checks == "pending"
    assert res.data.repo == "contoso/shop/webapp"


def test_my_pull_requests_and_review_requests(monkeypatch):
    data = json.loads(fx("pr_list.json"))
    data[0]["reviewers"][0] = {"uniqueName": "anna@example.com", "vote": 10}  # I already voted on #42
    data[4]["reviewers"][0] = {"uniqueName": "anna@example.com", "vote": 0}
    r = Router(monkeypatch, WHO, ("pr list", ok(json.dumps(data))))
    a = Azure("contoso", "Shop", "webapp")
    assert [p.number for p in a.my_pull_requests(20).data] == [42, 41, 40, 39, 38]
    assert "--creator anna@example.com" in r.calls[-1] and "--status active" in r.calls[-1]
    assert "--repository" not in r.calls[-1]  # whole project: there is no organization-wide search
    rev = a.review_requests(20)
    assert [p.number for p in rev.data] == [41, 40, 39, 38]  # #42 already has my vote
    assert "--reviewer anna@example.com" in r.calls[-1]
    assert sum("account show" in c for c in r.calls) == 1  # user asked once per provider


def test_login_errors(monkeypatch):
    Router(monkeypatch, ("account show", fail(fx("err_not_logged_in.txt"))))
    assert Azure("o", "p", "r").my_pull_requests().error.kind is ErrorKind.NOT_LOGGED_IN
    Router(monkeypatch, ("account show", ok("\n")))
    assert Azure("o", "p", "r").review_requests().error.kind is ErrorKind.NOT_LOGGED_IN


# --- work item ---

def test_work_item(monkeypatch):
    r = Router(monkeypatch, ("boards work-item show", ok(fx("work_item.json"))))
    wi = Azure("contoso", "Shop", "webapp").work_item(101).data
    assert "boards work-item show --id 101" in r.calls[0] and f"--organization {ORG}" in r.calls[0]
    assert wi.number == 101 and wi.title == "Rabatte im Warenkorb" and wi.state == "open"
    assert wi.board_status == "In Progress" and wi.board_available is True
    assert wi.labels == ("checkout", "backend") and wi.assignees == ("Anna Beispiel",)
    assert wi.url == f"{ORG}/Shop/_workitems/edit/101"


def test_work_item_defensive(monkeypatch):
    d = json.loads(fx("work_item.json"))
    d["fields"].update({"System.State": "Closed", "System.AssignedTo": "plain@example.com"})
    del d["fields"]["System.BoardColumn"], d["fields"]["System.Tags"]
    Router(monkeypatch, ("work-item show", ok(json.dumps(d))))
    wi = Azure("contoso", "Shop", "webapp").work_item(101).data
    assert wi.state == "closed" and wi.board_status is None and wi.labels == () and wi.assignees == ("plain@example.com",)
    d["fields"].pop("System.AssignedTo")
    Router(monkeypatch, ("work-item show", ok(json.dumps(d))))
    assert Azure("contoso", "Shop", "webapp").work_item(101).data.assignees == ()


def test_work_item_not_found_and_bad_shape(monkeypatch):
    Router(monkeypatch, ("work-item show", fail("ERROR: TF401232: Work item 5 does not exist")))
    assert Azure("o", "p", "r").work_item(5).error.kind is ErrorKind.OTHER
    Router(monkeypatch, ("work-item show", ok("{}")))
    assert Azure("o", "p", "r").work_item(5).error.kind is ErrorKind.OTHER


def test_work_item_for_numeric_id_and_pr_links(monkeypatch):
    Router(monkeypatch, ("pr list", ok(fx("pr_list.json"))), *ENRICH)
    prs = Azure("contoso", "Shop", "webapp").pull_requests().data
    assert work_item_for("feature/101-rabatte", ["feature/{id}-{slug}"], prs) == 101  # from the template
    assert work_item_for("feature/101-rabatte", [], prs) == 101  # via the PR's linked work item
    assert work_item_for("feature/102-suche", [], [p for p in prs if p.number == 40]) is None
    assert work_item_for("main", ["feature/{id}-{slug}"], prs) is None


# --- pipelines ---

def test_pipeline_runs(monkeypatch):
    r = Router(monkeypatch, WHO, ("pipelines runs list", ok(fx("runs_list.json"))))
    res = Azure("contoso", "Shop", "webapp").pipeline_runs(7, 20)
    c = r.calls[-1]
    assert "--requested-for anna@example.com" in c and "--top 20" in c and "--project Shop" in c
    runs = res.data
    assert [x.status for x in runs] == ["completed", "in_progress", "completed"]  # other repo + old run dropped
    assert [x.conclusion for x in runs] == ["success", None, "failure"]
    assert runs[0].workflow == "CI" and runs[0].branch == "feature/101-rabatte" and runs[0].duration_s == 94
    assert runs[0].url == f"{ORG}/Shop/_build/results?buildId=900" and runs[1].duration_s is None


def test_pipeline_runs_status_mapping_and_login_error(monkeypatch):
    a = Azure("o", "p", "r")
    base = {"id": 1, "status": "notStarted", "sourceBranch": "refs/heads/x"}
    assert a.parse_run(base).status == "queued"
    assert a.parse_run({**base, "status": "completed", "result": "canceled"}).conclusion == "cancelled"
    assert a.parse_run({**base, "status": "completed", "result": "partiallySucceeded"}).conclusion == "partially_succeeded"
    assert a.parse_run(base).workflow == "?"  # missing definition: defensive
    Router(monkeypatch, ("account show", fail(fx("err_not_logged_in.txt"))))
    assert a.pipeline_runs().error.kind is ErrorKind.NOT_LOGGED_IN


def test_models_are_plain_values():
    assert isinstance(Azure("o", "p", "r").parse_pr(json.loads(fx("pr_show.json"))), PullRequest)
