"""Stepper in `kvasir status` von außen: CLI, gh/openspec gefaked, cwd = Wegwerf-Verzeichnis."""
import json

import pytest
from test_status import FakeGh, issue, pr, runner, status_of, sub

from kvasir.cli import app

OS_LIST = json.dumps({"root": {"path": "/x"}, "changes": [{"name": "c1"}]})


def cwd_with(tmp_path, monkeypatch, *files):
    for f in files:
        (tmp_path / f).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / f).write_text("x")
    monkeypatch.chdir(tmp_path)


def feature(monkeypatch, root=None, subs=(), prs=(), openspec=None, rootbl=()):
    routes = {
        "repos/o/r/issues/1": json.dumps(root or issue(1, labels=["ready-for-agent"])),
        "repos/o/r/issues/1/sub_issues": json.dumps(list(subs)),
        "repos/o/r/issues/1/dependencies/blocked_by": json.dumps(list(rootbl)),
        "pr list": json.dumps(list(prs)),
        "repos/o/r/branches": "",
        **(openspec or {}),
    }
    for s in subs:
        routes[f"repos/o/r/issues/{s['number']}/dependencies/blocked_by"] = "[]"
    return FakeGh(monkeypatch, routes)


def steps(d):
    return [(x["name"], x["state"]) for x in d["stepper"]["steps"]]


def states(d):
    return "".join({"done": "x", "current": ">", "open": "."}[s] for _, s in steps(d))


# --- Detektoren: je einer über die Phasen-Zustände sichtbar gemacht ---

def test_issue_exists_and_file_exists(monkeypatch, tmp_path):
    cwd_with(tmp_path, monkeypatch)  # kein AGENTS.md
    feature(monkeypatch, subs=[issue(5)])
    assert steps(status_of()["issue"])[:2] == [("Setup", "current"), ("Eingang", "open")]
    cwd_with(tmp_path, monkeypatch, "AGENTS.md")
    assert steps(status_of()["issue"])[:2] == [("Setup", "done"), ("Eingang", "done")]


def test_label_detector(monkeypatch, tmp_path):
    cwd_with(tmp_path, monkeypatch, "AGENTS.md")
    feature(monkeypatch, root=issue(1, labels=["needs-triage"]), subs=[issue(5)])
    assert steps(status_of()["issue"])[2] == ("Idee schärfen", "current")


def test_openspec_detectors(monkeypatch, tmp_path):
    cwd_with(tmp_path, monkeypatch, "AGENTS.md")
    ok = {"list": OS_LIST, "status --change c1": json.dumps({"isComplete": True})}
    feature(monkeypatch, subs=[issue(5)], openspec=ok)
    assert ("Anforderungen", "done") in steps(status_of()["issue"])
    open_ = {**ok, "status --change c1": json.dumps({"isComplete": False})}
    feature(monkeypatch, subs=[issue(5)], openspec=open_)
    assert ("Anforderungen", "current") in steps(status_of()["issue"])
    none = {"list": json.dumps({"root": None, "changes": []})}
    feature(monkeypatch, subs=[issue(5)], openspec=none)
    assert steps(status_of()["issue"])[3][0] == "Arbeit schneiden"  # Phase unbeobachtbar -> fehlt


def test_openspec_missing_is_unknown_not_an_error(monkeypatch, tmp_path):
    cwd_with(tmp_path, monkeypatch, "AGENTS.md")
    feature(monkeypatch, subs=[issue(5)])  # kein openspec-Route -> FileNotFoundError
    names = [n for n, _ in steps(status_of()["issue"])]
    assert "Anforderungen" not in names and "Setup" in names


def test_subissues_exist(monkeypatch, tmp_path):
    cwd_with(tmp_path, monkeypatch, "AGENTS.md")
    feature(monkeypatch, subs=[issue(5)])
    assert ("Arbeit schneiden", "done") in steps(status_of()["issue"])


@pytest.mark.parametrize("prs, expected", [
    ([], "Bauen"),
    ([{**pr(7, "feat/5-x", draft=True, closes=[5]),
       "statusCheckRollup": [{"status": "COMPLETED", "conclusion": "SUCCESS"}]}], "Abnahme"),  # Draft -> Bauen done
])
def test_pr_state_draft(monkeypatch, tmp_path, prs, expected):
    cwd_with(tmp_path, monkeypatch, "AGENTS.md")
    feature(monkeypatch, subs=[issue(5)], prs=prs)
    cur = next(n for n, s in steps(status_of()["issue"]) if s == "current")
    assert cur == expected


def merged_pr(n, closes, checks="SUCCESS"):
    return {**pr(n, f"feat/{closes[0]}-x", closes=closes), "state": "MERGED",
            "statusCheckRollup": [{"status": "COMPLETED", "conclusion": checks}]}


def test_pr_ready_checks_and_merged_detectors(monkeypatch, tmp_path):
    cwd_with(tmp_path, monkeypatch, "AGENTS.md")
    ready_ok = {**pr(7, "feat/5-x", closes=[5]), "statusCheckRollup": [{"status": "COMPLETED", "conclusion": "SUCCESS"}]}
    feature(monkeypatch, subs=[issue(5)], prs=[ready_ok])
    d = status_of()["issue"]
    assert ("Abnahme", "done") in steps(d) and ("Abschließen", "current") in steps(d)
    ready_bad = {**ready_ok, "statusCheckRollup": [{"status": "COMPLETED", "conclusion": "FAILURE"}]}
    feature(monkeypatch, subs=[issue(5)], prs=[ready_bad])
    assert ("Abnahme", "current") in steps(status_of()["issue"])
    feature(monkeypatch, subs=[issue(5, "closed", "completed")], prs=[merged_pr(7, [5])])
    assert ("Abschließen", "current") in steps(status_of()["issue"])  # PR gemergt, Root offen


def test_issue_closed_detector(monkeypatch, tmp_path):
    cwd_with(tmp_path, monkeypatch, "AGENTS.md", "docs/adr/0001.md")
    feature(monkeypatch, root=issue(1, "closed", "completed", ["ready-for-agent"]),
            subs=[issue(5, "closed", "completed")], prs=[merged_pr(7, [5])])
    assert states(status_of()["issue"]) == "xxxxxxxx"  # alle Phasen (ohne openspec) erledigt


# --- Stepper-Zustände: Anfang / mittendrin / fertig ---

def test_feature_start_middle_end(monkeypatch, tmp_path):
    cwd_with(tmp_path, monkeypatch)
    feature(monkeypatch, root=issue(1), subs=[issue(5)])
    assert states(status_of()["issue"]) == ">......."  # am Anfang (ohne Phase Anforderungen)
    cwd_with(tmp_path, monkeypatch, "AGENTS.md")
    feature(monkeypatch, subs=[issue(5)], prs=[pr(7, "feat/5-x", draft=True, closes=[5])])
    assert states(status_of()["issue"]) == "xxxxx>."  # mittendrin (Abnahme ohne Checks unbeobachtbar)
    cwd_with(tmp_path, monkeypatch, "docs/adr/1.md")
    feature(monkeypatch, root=issue(1, "closed", "completed", ["ready-for-agent"]),
            subs=[issue(5, "closed", "completed")], prs=[merged_pr(7, [5])])
    assert set(states(status_of()["issue"])) == {"x"}  # fertig


# --- Ticket-Ebene ---

def body(*boxes):
    return "\n".join(f"- [{'x' if on else ' '}] {t}" for t, on in boxes)


def ticket(monkeypatch, branches=(), prs=(), blockers=()):
    scenario_prs = list(prs)
    FakeGh(monkeypatch, {
        "repos/o/r/issues/1": json.dumps(issue(1)),
        "repos/o/r/issues/1/sub_issues": json.dumps([issue(5)]),
        "repos/o/r/issues/1/dependencies/blocked_by": "[]",
        "repos/o/r/issues/5/dependencies/blocked_by": json.dumps(list(blockers)),
        "pr list": json.dumps(scenario_prs),
        "repos/o/r/branches": "\n".join(branches),
    })
    return sub(status_of())


def test_ticket_start(monkeypatch, tmp_path):
    cwd_with(tmp_path, monkeypatch)
    s = ticket(monkeypatch)
    assert s["stepper"]["level"] == "ticket"
    assert steps(s) == [("Branch", "current"), ("PR Draft", "open"), ("Checks grün", "open"),
                        ("PR bereit", "open"), ("gemergt", "open")]


def test_ticket_middle_reads_checklist(monkeypatch, tmp_path):
    cwd_with(tmp_path, monkeypatch)
    p = {**pr(7, "feat/5-x", draft=True, closes=[5]),
         "statusCheckRollup": [{"status": "COMPLETED", "conclusion": "SUCCESS"}],
         "body": body(("lokale Abnahme durch Nutzer", False), ("Code-Review erledigt", False), ("sonstiges", True))}
    s = ticket(monkeypatch, prs=[p])
    assert steps(s) == [("Branch", "done"), ("PR Draft", "done"), ("Checks grün", "done"),
                        ("lokale Abnahme", "current"), ("Review", "open"), ("PR bereit", "open"), ("gemergt", "open")]
    p["body"] = body(("lokale Abnahme", True), ("Code-Review", True))
    s = ticket(monkeypatch, prs=[p])
    assert ("lokale Abnahme", "done") in steps(s) and ("Review", "done") in steps(s)
    assert ("PR bereit", "current") in steps(s)


def test_ticket_without_checklist_has_no_such_steps(monkeypatch, tmp_path):
    cwd_with(tmp_path, monkeypatch)
    s = ticket(monkeypatch, prs=[{**pr(7, "feat/5-x", closes=[5]), "body": "nur Text"}])
    names = [n for n, _ in steps(s)]
    assert "lokale Abnahme" not in names and "Review" not in names


def test_ticket_without_ci_has_no_checks_step(monkeypatch, tmp_path):
    cwd_with(tmp_path, monkeypatch)
    s = ticket(monkeypatch, prs=[pr(7, "feat/5-x", closes=[5])])  # statusCheckRollup []
    assert "Checks grün" not in [n for n, _ in steps(s)]


def test_ticket_end_merged(monkeypatch, tmp_path):
    cwd_with(tmp_path, monkeypatch)
    s = ticket(monkeypatch, prs=[merged_pr(7, [5])])
    assert set(states(s)) == {"x"}


def test_ticket_branch_only(monkeypatch, tmp_path):
    cwd_with(tmp_path, monkeypatch)
    s = ticket(monkeypatch, branches=["feat/5-x"])
    assert steps(s)[:2] == [("Branch", "done"), ("PR Draft", "current")]


def test_closed_blockers_are_listed_as_previous(monkeypatch, tmp_path):
    cwd_with(tmp_path, monkeypatch)
    s = ticket(monkeypatch, blockers=[issue(3, "closed", "completed"), issue(4)])
    assert s["stepper"]["previous"] == [3]


def test_json_has_only_set_details(monkeypatch, tmp_path):
    cwd_with(tmp_path, monkeypatch)
    s = ticket(monkeypatch)
    assert list(s["stepper"]) == ["level", "steps"]  # kein "previous" ohne Vorgänger


def test_text_output_shows_stepper(monkeypatch, tmp_path):
    cwd_with(tmp_path, monkeypatch)
    ticket(monkeypatch, blockers=[issue(3, "closed", "completed")])
    out = runner.invoke(app, ["status", "#1", "--repo", "o/r", "--format", "text"]).output
    assert "Schritte: [>] Branch -> [ ] PR Draft" in out and "Vorgänger: #3" in out


# --- Detektoren aus workflow/detectors.tsv (#64), über eine kvasir.toml-Phase je Detektor

def one_phase(tmp_path, monkeypatch, spec, *files):
    cwd_with(tmp_path, monkeypatch, *files)
    (tmp_path / ".git").mkdir(exist_ok=True)
    (tmp_path / "kvasir.toml").write_text(f'[[phases]]\nname = "P"\ndone_when = ["{spec}"]\n')


def state(spec, tmp_path, monkeypatch, *files):
    one_phase(tmp_path, monkeypatch, spec, *files)
    return [x for _, x in steps(status_of()["issue"])]


def test_issue_open(monkeypatch, tmp_path):
    feature(monkeypatch, subs=[issue(5)])
    assert state("issue_open", tmp_path, monkeypatch) == ["done"]
    feature(monkeypatch, root=issue(1, "closed", "completed"), subs=[issue(5)])
    assert state("issue_open", tmp_path, monkeypatch) == ["done"]  # geschlossenes Feature: alle Phasen erledigt (#67)


def test_subissues_closed(monkeypatch, tmp_path):
    feature(monkeypatch, subs=[issue(5, "closed", "completed"), issue(6)])
    assert state("subissues_closed", tmp_path, monkeypatch) == ["current"]
    feature(monkeypatch, subs=[issue(5, "closed", "completed")])
    assert state("subissues_closed", tmp_path, monkeypatch) == ["done"]


def test_no_open_blockers(monkeypatch, tmp_path):
    feature(monkeypatch, subs=[issue(5)], rootbl=[issue(9)])
    assert state("no_open_blockers", tmp_path, monkeypatch) == ["current"]
    feature(monkeypatch, subs=[issue(5)], rootbl=[issue(9, "closed", "completed")])
    assert state("no_open_blockers", tmp_path, monkeypatch) == ["done"]


STATES = "id\tkind\n" + "needs-triage\ttriage\nstatus:in-progress\tstatus\n"


def test_has_label_kind(monkeypatch, tmp_path):
    feature(monkeypatch, root=issue(1, labels=["needs-triage"]), subs=[issue(5)])
    one_phase(tmp_path, monkeypatch, "has_label_kind:triage")
    assert state("has_label_kind:triage", tmp_path, monkeypatch) == []  # ohne states.tsv unbekannt
    (tmp_path / "workflow").mkdir()
    (tmp_path / "workflow/states.tsv").write_text(STATES)
    assert state("has_label_kind:triage", tmp_path, monkeypatch) == ["done"]
    assert state("has_label_kind:status", tmp_path, monkeypatch) == ["current"]


def test_pr_checklist(monkeypatch, tmp_path):
    def prs(*boxes):
        return [{**pr(7, "feat/5-x", closes=[5]), "body": body(*boxes)}]
    feature(monkeypatch, subs=[issue(5)], prs=prs(("Lokale Abnahme", True)))
    assert state("pr_checklist:Lokale Abnahme", tmp_path, monkeypatch) == ["done"]
    feature(monkeypatch, subs=[issue(5)], prs=prs(("Lokale Abnahme", False)))
    assert state("pr_checklist:Lokale Abnahme", tmp_path, monkeypatch) == ["current"]
    feature(monkeypatch, subs=[issue(5)], prs=prs(("Anderes", True)))
    assert state("pr_checklist:Lokale Abnahme", tmp_path, monkeypatch) == []  # kein solches Kästchen = unbekannt
    feature(monkeypatch, subs=[issue(5)])
    assert state("pr_checklist:Lokale Abnahme", tmp_path, monkeypatch) == ["current"]  # kein PR


def test_openspec_archived(monkeypatch, tmp_path):
    none = {"list": json.dumps({"root": {"path": "/x"}, "changes": []})}
    feature(monkeypatch, subs=[issue(5)], openspec=none)
    assert state("openspec_archived", tmp_path, monkeypatch) == ["current"]
    assert state("openspec_archived", tmp_path, monkeypatch, "openspec/changes/archive/2026-01-01-x/proposal.md") == ["done"]
    feature(monkeypatch, subs=[issue(5)], openspec={**none, "list": OS_LIST, "status --change c1": json.dumps({"isComplete": True})})
    assert state("openspec_archived", tmp_path, monkeypatch, "openspec/changes/archive/2026-01-01-x/p.md") == ["current"]  # aktiver Change
    feature(monkeypatch, subs=[issue(5)])  # kein openspec
    assert state("openspec_archived", tmp_path, monkeypatch) == []
