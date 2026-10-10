"""`kvasir status` Standardausgabe (Tabelle) von außen: CLI-Aufruf, gh gefaked."""
import json

from test_status import FakeGh, issue, pr, runner, scenario
from test_stepper import cwd_with, feature, merged_pr, ticket

from kvasir.cli import app

ARGS = ["status", "#1", "--repo", "o/r"]


def table(monkeypatch, cols=100, args=ARGS):
    monkeypatch.setenv("COLUMNS", str(cols))
    res = runner.invoke(app, args)
    assert res.exit_code == 0, res.output
    return res.output


def row(out, n):
    return next(line for line in out.splitlines() if line.lstrip().startswith(f"#{n} "))


def test_default_is_table_text_is_old_lines_json_unchanged(monkeypatch, tmp_path):
    cwd_with(tmp_path, monkeypatch)
    ticket(monkeypatch)
    out = table(monkeypatch)
    assert out.splitlines()[0].split() == ["Ticket", "Titel", "Prio", "Status", "Fortschritt", "Vorher", "Nachher"]
    old = runner.invoke(app, [*ARGS, "--format", "text"]).output
    assert old.startswith("#1 [offen] T1") and "Schritte: [>] Branch" in old
    d = json.loads(runner.invoke(app, [*ARGS, "--format", "json"]).output)
    assert list(d) == ["repo", "issue", "sub_issues"]
    assert list(d["sub_issues"][0]) == ["number", "title", "state", "state_reason", "labels", "status",
                                        "status_source", "reason", "hint", "schedule", "notices", "blocked_by",
                                        "parent", "children", "prio", "succ", "prev", "stepper"]


def test_progress_start(monkeypatch, tmp_path):
    cwd_with(tmp_path, monkeypatch)
    ticket(monkeypatch)
    assert "▶ startklar" in row(table(monkeypatch), 5) and "○○○○○ Branch" in row(table(monkeypatch), 5)


def test_progress_middle(monkeypatch, tmp_path):
    cwd_with(tmp_path, monkeypatch)
    p = {**pr(7, "feat/5-x", draft=True, closes=[5]),
         "statusCheckRollup": [{"status": "COMPLETED", "conclusion": "SUCCESS"}],
         "body": "- [ ] lokale Abnahme\n- [ ] Review"}
    ticket(monkeypatch, prs=[p])
    r = row(table(monkeypatch), 5)
    assert "▶ in Arbeit" in r and "●●●○○○○ lokale Abnahme" in r


def test_progress_done(monkeypatch, tmp_path):
    cwd_with(tmp_path, monkeypatch)
    ticket(monkeypatch, prs=[merged_pr(7, [5])])
    assert "●●●●●" in row(table(monkeypatch), 5) and "fertig" in row(table(monkeypatch), 5)


def test_progress_blocked(monkeypatch, tmp_path):
    cwd_with(tmp_path, monkeypatch)
    ticket(monkeypatch, blockers=[issue(3)])
    r = row(table(monkeypatch), 5)
    assert "⛔ blockiert" in r and "○○○○○ Branch" in r


def test_in_review_symbol(monkeypatch, tmp_path):
    cwd_with(tmp_path, monkeypatch)
    ticket(monkeypatch, prs=[pr(7, "feat/5-x", closes=[5])])
    assert "◐ in Review" in row(table(monkeypatch), 5)


def test_closed_feature_shows_all_phases_done(monkeypatch, tmp_path):
    cwd_with(tmp_path, monkeypatch)  # nichts beobachtbar außer: Issue ist zu
    feature(monkeypatch, root=issue(1, "closed", "completed"), subs=[issue(5, "closed", "completed")])
    d = json.loads(runner.invoke(app, [*ARGS, "--format", "json"]).output)
    assert {s["state"] for s in d["issue"]["stepper"]["steps"]} == {"done"}
    assert "●" in row(table(monkeypatch), 1) and "○" not in row(table(monkeypatch), 1)


def test_two_spaces_between_number_and_title_and_equal_width(monkeypatch, tmp_path):
    cwd_with(tmp_path, monkeypatch)
    sub = issue(5, title="Unterticket")
    FakeGh(monkeypatch, {
        "repos/o/r/issues/1": json.dumps(issue(1, title="Feature")),
        "repos/o/r/issues/1/sub_issues": json.dumps([sub, issue(123, title="Lang")]),
        "repos/o/r/issues/1/dependencies/blocked_by": "[]",
        "repos/o/r/issues/5/dependencies/blocked_by": "[]",
        "repos/o/r/issues/123/dependencies/blocked_by": "[]",
        "pr list": "[]", "repos/o/r/branches": "",
    })
    out = table(monkeypatch, args=[*ARGS, "--layout", "split"])
    lines = [row(out, 1), row(out, 5), row(out, 123)]
    assert all(x.lstrip().split("  ")[0].startswith("#") for x in lines)  # >= 2 Leerzeichen nach der Nummer
    assert len({x.index("Feature" if "Feature" in x else "Unterticket" if "Unterticket" in x else "Lang")
                for x in lines}) == 1  # Titel stehen in einer Spalte


def test_narrow_terminal_truncates_title_with_ellipsis(monkeypatch, tmp_path):
    cwd_with(tmp_path, monkeypatch)
    scenario(monkeypatch, issue(5, title="Ein sehr langer Titel der nicht in die Zeile passt"))
    out = table(monkeypatch, cols=80)
    assert "…" in row(out, 5)
    assert all(len(line) <= 80 for line in out.splitlines())
    assert "Fortschritt" in out.splitlines()[0]  # andere Spalten bleiben ganz


def test_notices_in_block_below_table(monkeypatch, tmp_path):
    cwd_with(tmp_path, monkeypatch)
    scenario(monkeypatch, issue(5, labels=["status:in-review"]), prs=[pr(7, "feat/5-x", draft=True, closes=[5])])
    lines = table(monkeypatch).splitlines()
    i = next(i for i, x in enumerate(lines) if "Hinweise" in x)
    assert not any("Label sagt" in x for x in lines[:i])  # nicht zwischen den Zeilen
    assert any("#5" in x and "Label sagt in-review" in x for x in lines[i:])


def test_blockers_and_deadline_in_block(monkeypatch, tmp_path):
    cwd_with(tmp_path, monkeypatch)
    scenario(monkeypatch, issue(5, body="Frist: 2026-12-31"), blockers=[issue(9)])
    out = table(monkeypatch)
    assert "#5" in out and "↗ #9 ○ offen" in out and "Frist: 2026-12-31" in out


def test_no_color_stays_readable(monkeypatch, tmp_path):
    cwd_with(tmp_path, monkeypatch)
    ticket(monkeypatch, blockers=[issue(3)])
    monkeypatch.setenv("NO_COLOR", "1")
    out = table(monkeypatch)
    assert "\x1b" not in out and "⛔ blockiert" in out
