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
        if args[0] == "openspec":  # route "openspec list" etc.; no route = not installed
            ans = self.routes.get(" ".join(args[1:-1]))
            if ans is None:
                raise FileNotFoundError
            return subprocess.CompletedProcess(args, 0, ans.encode(), b"")
        if args[0] != "gh":  # git etc. run for real (in tmp dirs)
            return self.real(args, **kw)
        self.calls.append(args)
        key = " ".join(args[1:3]) if args[1] == "pr" else args[2].split("?")[0]
        ans = self.routes[key]  # KeyError = unerwarteter Aufruf = Testfehler
        if isinstance(ans, tuple):
            return subprocess.CompletedProcess(args, ans[0], b"", ans[1].encode())
        return subprocess.CompletedProcess(args, 0, ans.encode(), b"")


def issue(n, state="open", reason=None, labels=(), title=None, body=None, ms=None):
    """ms = (Titel, due_on) -> Meilenstein."""
    return {"body": body, "milestone": {"title": ms[0], "due_on": ms[1]} if ms else None, "number": n, "title": title or f"T{n}", "state": state, "state_reason": reason,
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
                         "hint", "schedule", "notices", "blocked_by", "stepper"]
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


# --- Termine: Meilenstein, `Frist:`, `Geplant:` ---

MS = ("Sprint 12", "2026-10-14T00:00:00Z")


def plan(monkeypatch, sub, **kw):
    scenario(monkeypatch, sub, **kw)
    return sub_of_status()


def sub_of_status():
    return sub(status_of())


def test_milestone_due_is_deadline_with_name_as_label(monkeypatch):
    s = plan(monkeypatch, issue(5, ms=MS))
    assert s["schedule"]["deadline"] == "2026-10-14"
    assert s["schedule"]["deadlines"] == [{"date": "2026-10-14", "label": "Sprint 12"}]
    assert "Frist: 2026-10-14 (Sprint 12)" in runner.invoke(app, ["status", "#1", "--repo", "o/r"]).output


@pytest.mark.parametrize("text, date", [
    ("2026-10-17", "2026-10-17"), ("Ende Q4 2026", "2026-12-31"), ("Ende Q1 2026", "2026-03-31"),
    ("Ende 2026-02", "2026-02-28"), ("Ende 2028-02", "2028-02-29"), ("Ende 2026", "2026-12-31"),
])
def test_frist_line_forms(monkeypatch, text, date):
    s = plan(monkeypatch, issue(5, body=f"Text\nFrist: {text}\nMehr"))
    assert s["schedule"]["deadline"] == date and s["notices"] == []


@pytest.mark.parametrize("text", ["bald", "Ende Q5 2026", "Ende 2026-13", "2026-02-30", ""])
def test_unknown_frist_is_a_notice_not_an_abort(monkeypatch, text):
    s = plan(monkeypatch, issue(5, body=f"Frist: {text}"))
    assert s["schedule"]["deadline"] is None and len(s["notices"]) == 1 and "Frist" in s["notices"][0]


def test_earlier_of_line_and_milestone_wins_and_both_shown(monkeypatch):
    s = plan(monkeypatch, issue(5, body="Frist: 2026-10-10", ms=MS))
    assert s["schedule"]["deadline"] == "2026-10-10"
    assert [d["date"] for d in s["schedule"]["deadlines"]] == ["2026-10-10", "2026-10-14"]
    s = plan(monkeypatch, issue(5, body="Frist: 2026-10-17", ms=MS))
    assert s["schedule"]["deadline"] == "2026-10-14"
    text = runner.invoke(app, ["status", "#1", "--repo", "o/r"]).output
    assert "Frist: 2026-10-14 (Sprint 12), 2026-10-17 (Frist: 2026-10-17)" in text


@pytest.mark.parametrize("sep", [" – ", " - ", "–"])
def test_geplant_gives_start_and_end(monkeypatch, sep):
    s = plan(monkeypatch, issue(5, body=f"Geplant: 2026-10-12{sep}2026-10-14"))
    assert (s["schedule"]["planned_from"], s["schedule"]["planned_to"]) == ("2026-10-12", "2026-10-14")
    assert s["notices"] == []
    assert "Geplant: 2026-10-12 – 2026-10-14" in runner.invoke(app, ["status", "#1", "--repo", "o/r"]).output


def test_geplant_end_before_start_is_a_notice(monkeypatch):
    s = plan(monkeypatch, issue(5, body="Geplant: 2026-10-14 – 2026-10-12"))
    assert len(s["notices"]) == 1 and "vor Start" in s["notices"][0]


def test_geplant_unreadable_is_a_notice(monkeypatch):
    s = plan(monkeypatch, issue(5, body="Geplant: nächste Woche"))
    assert s["schedule"]["planned_from"] is None and "Geplant nicht verstanden" in s["notices"][0]


def test_planned_end_after_deadline_is_a_notice(monkeypatch):
    s = plan(monkeypatch, issue(5, body="Geplant: 2026-10-12 – 2026-10-20", ms=MS))
    assert s["notices"] == ["Geplantes Ende 2026-10-20 liegt nach Frist 2026-10-14"]
    assert s["schedule"]["planned_to"] == "2026-10-20"  # nichts korrigiert


def test_blocker_ending_after_start_is_a_notice(monkeypatch):
    s = plan(monkeypatch, issue(5, body="Geplant: 2026-10-12 – 2026-10-14"),
             blockers=[issue(9, body="Geplant: 2026-10-08 – 2026-10-13")])
    assert s["notices"] == ["Blocker #9 endet 2026-10-13, nach Start 2026-10-12"]
    s = plan(monkeypatch, issue(5, body="Geplant: 2026-10-12 – 2026-10-14"), blockers=[issue(9, ms=MS)])
    assert s["notices"] == ["Blocker #9 endet 2026-10-14, nach Start 2026-10-12"]  # ohne Plan: Frist
    s = plan(monkeypatch, issue(5, body="Geplant: 2026-10-12 – 2026-10-14"),
             blockers=[issue(9, body="Geplant: 2026-10-08 – 2026-10-12")])
    assert s["notices"] == []


def test_items_without_dates_get_none(monkeypatch):
    s = plan(monkeypatch, issue(5, body="Nur Text, Frist im Satz: morgen", ms=("Backlog", None)))
    assert s["schedule"] == {"deadline": None, "deadlines": [], "planned_from": None, "planned_to": None}
    assert s["notices"] == []
    text = runner.invoke(app, ["status", "#1", "--repo", "o/r"]).output
    assert "Frist" not in text and "Geplant" not in text
