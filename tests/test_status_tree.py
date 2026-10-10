"""`kvasir status` Baum, Prio, Vorher/Nachher, Reihenfolge, Übersicht (#68) von außen: CLI, gh/az gefaked."""
import json
import re

from test_azure_status import fake_az, wi
from test_status import FakeGh, issue, pr, runner
from test_stepper import cwd_with

from kvasir.cli import app
from kvasir.platform import Azure
from kvasir.platform.status import issue_status


def it(n, kids=0, labels=(), **kw):
    d = issue(n, labels=labels, **kw)
    return {**d, "sub_issues_summary": {"total": kids}} if kids else d


def repo(monkeypatch, items, subs, blocks=None, prs=()):
    """items: Liste von Issue-Dicts; subs: {Eltern: [Kinder]}; blocks: {Nr: [Blocker-Dicts]}."""
    by = {d["number"]: d for d in items}
    routes = {"pr list": json.dumps(list(prs)), "repos/o/r/branches": "",
              "repos/o/r/issues": json.dumps([d for d in items if d["state"] == "open"])}
    for n, d in by.items():
        routes[f"repos/o/r/issues/{n}"] = json.dumps(d)
        routes[f"repos/o/r/issues/{n}/sub_issues"] = json.dumps([by[c] for c in subs.get(n, [])])
        routes[f"repos/o/r/issues/{n}/dependencies/blocked_by"] = json.dumps((blocks or {}).get(n, []))
    return FakeGh(monkeypatch, routes)


def out(monkeypatch, *args, cols=140):
    monkeypatch.setenv("COLUMNS", str(cols))
    res = runner.invoke(app, ["status", *args, "--repo", "o/r"])
    assert res.exit_code == 0, res.output
    return res.output


def row(text, n):
    return next(x for x in text.splitlines() if x.lstrip().startswith(f"#{n} "))


THREE = [it(1, 2, title="Feature"), it(2, 1, title="Zwei"), it(3, title="Drei"), it(4, title="Vier")]
THREE_SUBS = {1: [2, 3], 2: [4]}


def test_tree_layout_default_three_levels(monkeypatch, tmp_path):
    cwd_with(tmp_path, monkeypatch)
    repo(monkeypatch, THREE, THREE_SUBS)
    t = out(monkeypatch, "#1")
    for n, title in ((1, "Feature"), (2, "├─ Zwei"), (4, "│  └─ Vier"), (3, "└─ Drei")):
        assert re.match(rf"\s*#{n}\s{{2,}}{title}\s", row(t, n)), row(t, n)
    assert [x.split()[0] for x in t.splitlines()[1:5]] == ["#1", "#2", "#4", "#3"]  # Baumreihenfolge
    assert t.splitlines()[0].split()[:2] == ["Ticket", "Titel"]


def test_split_layout_separates_ticket_and_title(monkeypatch, tmp_path):
    cwd_with(tmp_path, monkeypatch)
    repo(monkeypatch, THREE, THREE_SUBS)
    t = out(monkeypatch, "#1", "--layout", "split")
    assert "├─" not in t and "└─" not in t
    assert row(t, 2).split()[:2] == ["#2", "Zwei"] and t.splitlines()[0].split()[:2] == ["Ticket", "Titel"]


def test_bad_layout_is_usage_error(monkeypatch, tmp_path):
    cwd_with(tmp_path, monkeypatch)
    assert runner.invoke(app, ["status", "#1", "--repo", "o/r", "--layout", "x"]).exit_code == 2


def test_number_width_equal_and_two_spaces(monkeypatch, tmp_path):
    cwd_with(tmp_path, monkeypatch)
    repo(monkeypatch, [it(1, 2, title="F"), it(5, title="A"), it(123, title="B")], {1: [5, 123]})
    t = out(monkeypatch, "#1")
    assert row(t, 1).startswith("#1    F") and row(t, 5).startswith("#5    ├─ A") and row(t, 123).startswith("#123  └─ B")


def test_prev_succ_external_and_blocked(monkeypatch, tmp_path):
    cwd_with(tmp_path, monkeypatch)
    repo(monkeypatch, [it(1, 3), it(2), it(3), it(4)], {1: [2, 3, 4]},
         blocks={3: [issue(2), issue(99, "closed", "completed")], 4: [issue(2, "closed", "completed")]})
    t = out(monkeypatch, "#1")
    assert "#2 ○ offen" in row(t, 3) and "↗ #99 ✓" in row(t, 3) and "⛔ blockiert" in row(t, 3)
    assert row(t, 2).rstrip().endswith("#3") or "#3, #4" in row(t, 2)  # Nachher = Umkehrung im gezeigten Satz
    assert "#2 ✓" in row(t, 4) and "↗" not in row(t, 4)  # #2 offen im Satz, aber hier als geschlossen gemeldet


def test_order_predecessor_then_prio_then_number_and_cycle(monkeypatch, tmp_path):
    cwd_with(tmp_path, monkeypatch)
    subs = [it(2), it(3), it(4, labels=["prio:3"]), it(5, labels=["prio:1"]), it(6), it(7)]
    repo(monkeypatch, [it(1, 6), *subs], {1: [2, 3, 4, 5, 6, 7]},
         blocks={2: [issue(3)], 6: [issue(7)], 7: [issue(6)]})
    order = [x.split()[0] for x in out(monkeypatch, "#1").splitlines()[1:]]
    # 3 vor 2 (Vorgänger); danach Prio 1 (#5), Prio 3 (#4), ohne Prio nach Nummer; Zyklus 6/7 hängt nicht
    assert order[:7] == ["#1", "#5", "#4", "#3", "#2", "#6", "#7"]


def test_prio_github_and_default(monkeypatch, tmp_path):
    cwd_with(tmp_path, monkeypatch)
    repo(monkeypatch, [it(1, 2), it(2, labels=["prio:2"]), it(3, labels=["prio:9"])], {1: [2, 3]})
    t = out(monkeypatch, "#1")
    assert " P2 " in row(t, 2) and " – " in row(t, 3) and " – " in row(t, 1)
    d = json.loads(out(monkeypatch, "#1", "--format", "json"))
    assert [d["issue"]["prio"], *(s["prio"] for s in d["sub_issues"])] == [None, 2, None]


def test_prio_azure(monkeypatch):
    root, child = wi(1, rels=[("Hierarchy-Forward", 2)]), wi(2)
    child["fields"]["Microsoft.VSTS.Common.Priority"] = 3
    fake_az(monkeypatch, {1: root, 2: child})
    st = issue_status(Azure("contoso", "Shop", "webapp"), 1).data
    assert [s.item.prio for s in st.sub_issues] == [3] and st.issue.item.prio is None


def test_startklar_only_without_blocker_and_work(monkeypatch, tmp_path):
    cwd_with(tmp_path, monkeypatch)
    repo(monkeypatch, [it(1, 3), it(2), it(3), it(4)], {1: [2, 3, 4]}, blocks={3: [issue(9)]},
         prs=[pr(7, "feat/4-x", draft=True, closes=[4])])
    t = out(monkeypatch, "#1")
    assert "▶ startklar" in row(t, 2) and "startklar" not in row(t, 3) and "startklar" not in row(t, 4)
    assert "startklar" not in row(t, 1)  # Feature mit Kindern


def test_json_has_relations_nothing_invented(monkeypatch, tmp_path):
    cwd_with(tmp_path, monkeypatch)
    repo(monkeypatch, THREE, THREE_SUBS, blocks={3: [issue(2)]})
    d = json.loads(out(monkeypatch, "#1", "--format", "json"))
    by = {s["number"]: s for s in d["sub_issues"]}
    assert set(by) == {2, 3, 4}
    assert d["issue"]["parent"] is None and d["issue"]["children"] == [2, 3]
    assert by[4]["parent"] == 2 and by[2]["children"] == [4] and by[4]["children"] == []
    assert by[3]["prev"] == [{"repo": "o/r", "number": 2, "state": "open"}] and by[2]["succ"] == [3]
    assert by[3]["succ"] == [] and by[4]["prev"] == [] and by[4]["prio"] is None


def features(monkeypatch, n):
    items = [it(100 + i, 1, title=f"F{i}") for i in range(n)] + [it(1, title="Kind"), it(2, title="Los")]
    return repo(monkeypatch, items, {100 + i: [1] for i in range(n)})


def test_no_argument_lists_open_features_as_trees(monkeypatch, tmp_path):
    cwd_with(tmp_path, monkeypatch)
    features(monkeypatch, 2)
    t = out(monkeypatch)
    assert "#100" in t and "#101" in t and "└─ Kind" in t and "Los" not in t  # #2 ist kein Feature
    d = json.loads(out(monkeypatch, "--format", "json"))
    assert [f["issue"]["number"] for f in d["features"]] == [100, 101]


def test_no_argument_warns_from_ten_features_and_limit(monkeypatch, tmp_path):
    cwd_with(tmp_path, monkeypatch)
    features(monkeypatch, 10)
    res = runner.invoke(app, ["status", "--repo", "o/r"])
    assert res.exit_code == 0 and "--limit" in res.stderr and "10" in res.stderr
    res = runner.invoke(app, ["status", "--repo", "o/r", "--limit", "3"])
    assert res.exit_code == 0 and "#102" in res.stdout and "#103" not in res.stdout
    features(monkeypatch, 9)
    assert "--limit" not in runner.invoke(app, ["status", "--repo", "o/r"]).stderr
