# ruff: noqa: C408
"""`kvasir status` von außen: CLI-Aufruf, `gh`-Antworten als Fixtures (nie echtes gh)."""
import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from kvasir.cli import app
from kvasir.platform import gh as ghmod

FIX = Path(__file__).parent / "fixtures" / "gh" / "status"
runner = CliRunner()


def fx(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


class FakeGh:
    """Ersetzt subprocess.run im gh-Modul. routes: Endpunkt (ohne Query) oder 'pr list' -> Ausgabe oder (code, stderr)."""

    def __init__(self, monkeypatch, routes):
        self.routes, self.calls, self.real = routes, [], subprocess.run
        monkeypatch.setattr(ghmod.subprocess, "run", self)

    def __call__(self, args, **kw):
        if args[0] != "gh":  # git etc. run for real (in tmp dirs)
            return self.real(args, **kw)
        self.calls.append(args)
        key = " ".join(args[1:3]) if args[1] == "pr" else args[2].split("?")[0]
        ans = self.routes[key]  # KeyError = unerwarteter Aufruf = Testfehler
        if isinstance(ans, tuple):
            return subprocess.CompletedProcess(args, ans[0], b"", ans[1].encode())
        return subprocess.CompletedProcess(args, 0, ans.encode(), b"")


def issue(n, state="open", reason=None, labels=(), title=None):
    return {"number": n, "title": title or f"T{n}", "state": state, "state_reason": reason,
            "html_url": f"https://github.com/o/r/issues/{n}", "repository_url": "https://api.github.com/repos/o/r",
            "labels": [{"name": x} for x in labels]}


def pr(n, branch, draft=False, closes=()):
    return {"number": n, "title": f"PR{n}", "state": "OPEN", "isDraft": draft, "url": f"https://x/pull/{n}",
            "author": {"login": "a"}, "headRefName": branch, "closingIssuesReferences": [{"number": c} for c in closes],
            "reviewDecision": "", "statusCheckRollup": [], "createdAt": "2026-10-01T00:00:00Z"}


def scenario(monkeypatch, sub, blockers=(), prs=(), branches=(), root=None):
    """Issue #1 (Eltern) mit genau einem Sub-Issue `sub` (#5)."""
    return FakeGh(monkeypatch, {
        "repos/o/r/issues/1": json.dumps(root or issue(1)),
        "repos/o/r/issues/1/sub_issues": json.dumps([sub]),
        "repos/o/r/issues/1/dependencies/blocked_by": "[]",
        "repos/o/r/issues/5/dependencies/blocked_by": json.dumps(list(blockers)),
        "pr list": json.dumps(list(prs)),
        "repos/o/r/branches": "\n".join(branches),
    })


def status_of(args=("status", "#1", "--repo", "o/r", "--format", "json")):
    res = runner.invoke(app, list(args))
    assert res.exit_code == 0, res.output
    return json.loads(res.output)


def sub(d):
    return d["sub_issues"][0]


# --- Leseprobe als Fixture: echte Antworten zu comcy/comcy.github.io #13 ---

@pytest.fixture
def real13(monkeypatch):
    routes = {
        "repos/comcy/comcy.github.io/issues/13": fx("issue_13.json"),
        "repos/comcy/comcy.github.io/issues/13/sub_issues": fx("sub_issues_13.json"),
        "pr list": fx("pr_open.json"),
        "repos/comcy/comcy.github.io/branches": fx("branches.txt"),
    }
    for n in (13, 16, 17, 18, 19, 20, 33, 34):
        routes[f"repos/comcy/comcy.github.io/issues/{n}/dependencies/blocked_by"] = fx(f"blocked_by_{n}.json")
    return FakeGh(monkeypatch, routes)


def test_lists_issue_sub_issues_and_blockers_as_text(real13):
    res = runner.invoke(app, ["status", "#13", "--repo", "comcy/comcy.github.io"])
    assert res.exit_code == 0, res.output
    lines = res.output.splitlines()
    assert lines[0].startswith("#13 [erledigt]")
    for n in (16, 17, 18, 19, 20, 33, 34):
        assert any(line.strip().startswith(f"#{n} [erledigt]") for line in lines)
    i = next(i for i, line in enumerate(lines) if line.strip().startswith("#20 "))
    assert "#17" in lines[i + 1] and "#19" in lines[i + 1]


def test_json_model_is_stable(real13):
    d = status_of(("status", "13", "--repo", "comcy/comcy.github.io", "--format", "json"))
    assert list(d) == ["repo", "issue", "sub_issues"]
    assert d["repo"] == "comcy/comcy.github.io"
    assert [s["number"] for s in d["sub_issues"]] == [16, 17, 18, 19, 20, 33, 34]
    s20 = d["sub_issues"][4]
    assert list(s20) == ["number", "title", "state", "state_reason", "labels", "status", "status_source", "reason",
                         "hint", "blocked_by"]
    assert s20["status"] == "done" and s20["status_source"] == "fact" and s20["hint"] is None
    assert s20["blocked_by"] == [{"repo": "comcy/comcy.github.io", "number": 17, "state": "closed"},
                                 {"repo": "comcy/comcy.github.io", "number": 19, "state": "closed"}]


def test_reads_only(real13):
    runner.invoke(app, ["status", "#13", "--repo", "comcy/comcy.github.io"])
    for args in real13.calls:
        assert args[:2] in (["gh", "api"], ["gh", "pr"])
        assert not {"-X", "--method", "-f", "-F", "--field", "--input", "edit", "create"} & set(args)


# --- Statusregeln, in der festgelegten Reihenfolge ---

@pytest.mark.parametrize("kw, expected", [
    (dict(sub=issue(5, "closed", "completed")), "done"),
    (dict(sub=issue(5, "closed", "not_planned")), "dropped"),
    (dict(sub=issue(5, "closed", "completed", ["wontfix"])), "dropped"),
    (dict(sub=issue(5), blockers=[issue(9)]), "blocked"),
    (dict(sub=issue(5), blockers=[issue(9, "closed", "completed")]), "open"),
    (dict(sub=issue(5), prs=[pr(7, "feat/x", closes=[5])]), "in_review"),
    (dict(sub=issue(5), prs=[pr(7, "feat/5-x")]), "in_review"),
    (dict(sub=issue(5), prs=[pr(7, "feat/x", draft=True, closes=[5])]), "in_progress"),
    (dict(sub=issue(5), branches=["main", "feat/5-x"]), "in_progress"),
    (dict(sub=issue(5), branches=["main", "feat/15-x", "feat/50-x", "v5.1"]), "open"),
    (dict(sub=issue(5), prs=[pr(7, "feat/other", closes=[6])]), "open"),
    # Reihenfolge
    (dict(sub=issue(5, "closed", "completed"), blockers=[issue(9)], prs=[pr(7, "a", closes=[5])]), "done"),
    (dict(sub=issue(5), blockers=[issue(9)], prs=[pr(7, "a", closes=[5])], branches=["feat/5-x"]), "blocked"),
    (dict(sub=issue(5), prs=[pr(7, "a", closes=[5]), pr(8, "b", draft=True, closes=[5])]), "in_review"),
    (dict(sub=issue(5), prs=[pr(7, "a", draft=True, closes=[5])], branches=["feat/5-x"]), "in_progress"),
])
def test_status_rules(monkeypatch, kw, expected):
    scenario(monkeypatch, **kw)
    s = sub(status_of())
    assert s["status"] == expected and s["status_source"] == "fact"


# --- status:*-Label: Hinweis bei Widerspruch, "laut Label" ohne Tatsache ---

def test_label_contradicting_fact_is_a_hint_and_changes_nothing(monkeypatch):
    scenario(monkeypatch, issue(5, labels=["status:in-review"]), prs=[pr(7, "a", draft=True, closes=[5])])
    s = sub(status_of())
    assert s["status"] == "in_progress" and s["status_source"] == "fact"
    assert s["hint"] == "Label sagt in-review, PR #7 ist Draft"


def test_label_matching_fact_has_no_hint(monkeypatch):
    scenario(monkeypatch, issue(5, labels=["status:in-progress"]), branches=["feat/5-x"])
    s = sub(status_of())
    assert s["status"] == "in_progress" and s["hint"] is None


def test_label_on_closed_issue_is_a_hint(monkeypatch):
    scenario(monkeypatch, issue(5, "closed", "completed", ["status:in-progress"]))
    s = sub(status_of())
    assert s["status"] == "done" and s["hint"].startswith("Label sagt in-progress")


def test_label_counts_where_no_fact_exists(monkeypatch):
    scenario(monkeypatch, issue(5, labels=["status:in-refinement", "enhancement"]))
    s = sub(status_of())
    assert s["status"] == "in_refinement" and s["status_source"] == "label" and s["hint"] is None
    text = runner.invoke(app, ["status", "#1", "--repo", "o/r"]).output
    assert "in_refinement (laut Label)" in text


def test_open_with_unmatched_other_label_stays_open(monkeypatch):
    scenario(monkeypatch, issue(5, labels=["enhancement", "ready-for-agent"]))
    s = sub(status_of())
    assert s["status"] == "open" and s["status_source"] == "fact"


def test_root_issue_gets_status_too(monkeypatch):
    scenario(monkeypatch, issue(5), root=issue(1, "closed", "not_planned"))
    assert status_of()["issue"]["status"] == "dropped"


# --- Fehler wie in der Plattformschicht ---

@pytest.mark.parametrize("code, err, kind", [
    (4, "gh auth login", "not_logged_in"),
    (1, "HTTP 404: Not Found", "other"),
    (1, "API rate limit exceeded", "rate_limit"),
])
def test_gh_errors_are_reported_by_kind(monkeypatch, code, err, kind):
    FakeGh(monkeypatch, {"repos/o/r/issues/1": (code, err)})
    res = runner.invoke(app, ["status", "#1", "--repo", "o/r"])
    assert res.exit_code == 1 and kind in res.output


def test_sub_issues_unavailable_is_reported(monkeypatch):
    FakeGh(monkeypatch, {"repos/o/r/issues/1": json.dumps(issue(1)),
                         "repos/o/r/issues/1/sub_issues": (1, "HTTP 404: Not Found")})
    res = runner.invoke(app, ["status", "#1", "--repo", "o/r"])
    assert res.exit_code == 1 and "other" in res.output and "404" in res.output


def test_gh_missing(monkeypatch):
    def boom(*a, **k):
        raise FileNotFoundError
    monkeypatch.setattr(ghmod.subprocess, "run", boom)
    res = runner.invoke(app, ["status", "#1", "--repo", "o/r"])
    assert res.exit_code == 1 and "cli_missing" in res.output


def test_bad_arguments(monkeypatch):
    assert runner.invoke(app, ["status", "abc", "--repo", "o/r"]).exit_code != 0
    assert runner.invoke(app, ["status", "#1", "--repo", "o/r", "--format", "xml"]).exit_code != 0


def test_repo_from_cwd_origin(monkeypatch, make_repo):
    scenario(monkeypatch, issue(5))
    monkeypatch.chdir(make_repo(remote="git@github.com:o/r.git"))
    d = json.loads(runner.invoke(app, ["status", "#1", "--format", "json"]).output)
    assert d["repo"] == "o/r"


def test_no_github_repo_needs_repo_option(monkeypatch, make_repo):
    monkeypatch.chdir(make_repo(remote="git@gitlab.com:o/r.git"))
    assert runner.invoke(app, ["status", "#1"]).exit_code == 2
