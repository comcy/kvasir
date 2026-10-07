"""`kvasir graph` von außen: CLI-Aufruf, `gh`-Antworten gefaked, Ausgabe gegen erwartete Mermaid-Texte."""
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from test_status import FakeGh, issue, pr
from typer.testing import CliRunner

from kvasir.cli import app

runner = CliRunner()
ISSUES = "repos/o/r/issues?state={}&sort=updated&direction=desc&per_page=100"


def ago(days):
    return (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def iss(n, parent=None, closed=None, **kw):
    d = issue(n, state="closed" if closed is not None else "open", **kw)
    d["closed_at"] = ago(closed) if closed is not None else None
    d["parent_issue_url"] = f"https://api.github.com/repos/o/r/issues/{parent}" if parent else None
    return d


def routes(opened, closed=(), blocked=None, prs=(), branches=(), **more):
    r = {ISSUES.format("open"): json.dumps(list(opened)), ISSUES.format("closed"): json.dumps(list(closed)),
         "pr list": json.dumps(list(prs)), "repos/o/r/branches": "\n".join(branches), **more}
    for d in [*opened, *closed]:
        r[f"repos/o/r/issues/{d['number']}/dependencies/blocked_by"] = json.dumps((blocked or {}).get(d["number"], []))
    return r


def graph(monkeypatch, r, *args):
    fake = FakeGh(monkeypatch, r)
    res = runner.invoke(app, ["graph", "--repo", "o/r", *args])
    assert res.exit_code == 0, res.output
    return res, fake


def test_lanes_edges_colors_and_deterministic(monkeypatch):
    r = routes([iss(2, 1, title="B"), iss(1, title="Feat"), iss(3, title="Solo"), iss(4, 1, title="Blocked")],
               [iss(5, 1, closed=3, title="Done")], blocked={4: [iss(2)], 2: [iss(5, closed=3)]},
               prs=[pr(7, "feat/2-x", draft=True)])
    out1 = graph(monkeypatch, r)[0].output
    assert graph(monkeypatch, r)[0].output == out1  # byte-identisch
    assert out1.startswith("```mermaid\nflowchart LR\n")
    assert """    subgraph lane0["#1 Feat"]
        n1["#1 Feat<br/>offen"]:::open
        n2["#2 B<br/>in Arbeit"]:::in_progress
        n4["#4 Blocked<br/>blockiert"]:::blocked
        n5["#5 Done<br/>erledigt"]:::done
    end
    subgraph lane1["Ohne Feature"]
        n3["#3 Solo<br/>offen"]:::open
    end
    n2 --> n4
    n5 --> n2
""" in out1
    assert "    classDef blocked fill:#cf222e" in out1
    assert "gantt" not in out1


def test_closed_older_than_14_days_only_dimmed_when_open_item_depends(monkeypatch):
    r = routes([iss(1, title="Open"), iss(2, title="Dep")], [iss(8, closed=30, title="Alt"), iss(9, closed=20)],
               blocked={1: [iss(8, closed=30, title="Alt")], 8: [iss(9, closed=20)]})
    out = graph(monkeypatch, r)[0].output
    assert 'n8["#8 Alt<br/>closed"]:::dimmed' in out and "n8 --> n1" in out
    assert "n9" not in out  # nur von altem Erledigten referenziert


def test_external_blocker_is_grey_node_with_link_not_expanded(monkeypatch):
    ext = issue(3)
    ext["repository_url"] = "https://api.github.com/repos/x/y"
    r = routes([iss(1)], blocked={1: [ext]})
    res, fake = graph(monkeypatch, r)
    assert 'ext_x_y_3["x/y#3<br/>extern"]:::external' in res.output
    assert 'click ext_x_y_3 "https://github.com/x/y/issues/3"' in res.output and "ext_x_y_3 --> n1" in res.output
    assert not any("x/y" in a for c in fake.calls for a in c)  # nicht aufgeklappt


def test_single_feature_by_number(monkeypatch):
    r = routes([], blocked={5: []}, **{"repos/o/r/issues/1": json.dumps(issue(1)),
                                       "repos/o/r/issues/1/sub_issues": json.dumps([iss(5, 1)]),
                                       "repos/o/r/issues/1/dependencies/blocked_by": "[]",
                                       "repos/o/r/issues/5/dependencies/blocked_by": "[]"})
    out = graph(monkeypatch, r, "#1")[0].output
    assert 'subgraph lane0["#1 T1"]' in out and "n5[" in out and "n1[" in out


def test_milestone_filters_via_number_and_unknown_fails(monkeypatch):
    r = routes([iss(1)], **{"repos/o/r/milestones": json.dumps([{"number": 4, "title": "Sprint 12"}])})
    r[ISSUES.format("open") + "&milestone=4"] = r.pop(ISSUES.format("open"))
    r[ISSUES.format("closed") + "&milestone=4"] = r.pop(ISSUES.format("closed"))
    assert "n1[" in graph(monkeypatch, r, "--milestone", "Sprint 12")[0].output
    FakeGh(monkeypatch, r)
    res = runner.invoke(app, ["graph", "--repo", "o/r", "--milestone", "nope"])
    assert res.exit_code == 1 and "milestone not found" in res.output


def test_warns_from_40_nodes_but_prints_everything(monkeypatch):
    r = routes([iss(n) for n in range(1, 41)])
    res, _ = graph(monkeypatch, r)
    assert "warning: 40 nodes" in res.output and "n40[" in res.output
    assert "warning" not in graph(monkeypatch, routes([iss(n) for n in range(1, 40)]))[0].output


def test_label_contradiction_marks_node(monkeypatch):
    r = routes([iss(1, labels=["status:in-review"]), iss(2, labels=["status:in-refinement"])],
               prs=[pr(7, "a", draft=True, closes=[1])])
    out = graph(monkeypatch, r)[0].output
    assert 'n1["#1 T1<br/>in Arbeit ⚠ Label widerspricht"]:::in_progress' in out
    assert 'n2["#2 T2<br/>in_refinement (laut Label)"]:::open' in out


def test_gantt_only_for_dated_items_with_deadline_marks(monkeypatch):
    r = routes([iss(1, body="Geplant: 2026-10-12 – 2026-10-14", ms=("Sprint 12", "2026-10-20T00:00:00Z")),
                iss(2, ms=("Sprint 12", "2026-10-20T00:00:00Z")), iss(3)])
    out = graph(monkeypatch, r)[0].output
    assert """```mermaid
gantt
    dateFormat YYYY-MM-DD
    section Ohne Feature
    #1 T1 :n1, 2026-10-12, 2026-10-14
    Frist #1 Sprint 12 :milestone, 2026-10-20, 0d
    Frist #2 Sprint 12 :milestone, 2026-10-20, 0d
```""" in out
    assert "#3" not in out.split("gantt")[1] and "#2 T2 :" not in out


def test_out_file_and_reads_only(monkeypatch, tmp_path):
    f = tmp_path / "g.md"
    res, fake = graph(monkeypatch, routes([iss(1)]), "--out", str(f))
    assert res.output == "" and f.read_text(encoding="utf-8").startswith("```mermaid")
    for args in fake.calls:
        assert args[:2] in (["gh", "api"], ["gh", "pr"])
        assert not {"-X", "--method", "-f", "-F", "--field", "--input", "edit", "create"} & set(args)


def test_gh_error_and_bad_arguments(monkeypatch):
    FakeGh(monkeypatch, {ISSUES.format("open"): (1, "API rate limit exceeded")})
    res = runner.invoke(app, ["graph", "--repo", "o/r"])
    assert res.exit_code == 1 and "rate_limit" in res.output
    assert runner.invoke(app, ["graph", "abc", "--repo", "o/r"]).exit_code == 2
    assert runner.invoke(app, ["graph", "--repo", "o/r", "--format", "dot"]).exit_code == 2


@pytest.mark.parametrize("title", ['Say "hi" <b>', "a\nb"])
def test_titles_are_escaped(monkeypatch, title):
    out = graph(monkeypatch, routes([iss(1, title=title)]))[0].output
    assert '"' not in out.split('n1["')[1].split('"]')[0] and "<b>" not in out


# --- HTML (#55) ---
REF = Path(__file__).parent / "fixtures" / "graph_reference.html"


def html_routes():
    ext = issue(3)
    ext["repository_url"] = "https://api.github.com/repos/x/y"
    return routes(
        [iss(2, 1, title="B", body="Geplant: 2026-10-12 – 2026-10-14", ms=("Sprint 12", "2026-10-20T00:00:00Z")),
         iss(1, title="Feat"), iss(3, title="Solo", labels=["status:in-review"]), iss(4, 1, title="Blocked <x>")],
        [iss(5, 1, closed=3, title="Done")], blocked={4: [iss(2)], 2: [iss(5, closed=3)], 3: [ext]},
        prs=[pr(7, "feat/2-x", draft=True), pr(8, "b", draft=True, closes=[3])])


def test_html_matches_reference_and_is_deterministic(monkeypatch):
    out = graph(monkeypatch, html_routes(), "--format", "html")[0].output
    assert graph(monkeypatch, html_routes(), "--format", "html")[0].output == out
    if not REF.exists():  # Referenz bewusst neu erzeugen: Datei löschen, Test laufen lassen, im Browser prüfen
        REF.parent.mkdir(exist_ok=True)
        REF.write_text(out, encoding="utf-8")
    assert out == REF.read_text(encoding="utf-8")


def test_html_is_standalone_with_lanes_links_edges_hints_and_timeline(monkeypatch):
    out = graph(monkeypatch, html_routes(), "--format", "html")[0].output
    assert out.startswith("<!doctype html>") and "prefers-color-scheme:dark" in out
    assert "http://" not in out.replace("https://github.com", "") and "<script" not in out and "src=" not in out
    for lane in ("#1 Feat", "Ohne Feature", "Extern / älter"):
        assert lane in out
    assert '<a href="https://github.com/o/r/issues/2">' in out and "https://github.com/x/y/issues/3" in out
    assert out.count('class="edge"') == 3  # 5->2, 2->4, ext->3
    assert "Blocked &lt;x&gt;" in out and "<x>" not in out
    assert "⚠ Label widerspricht" in out  # Label-Widerspruch am Knoten (#3)
    assert "<h2>Zeitachse</h2>" in out and "Frist 2026-10-20: Sprint 12" in out and "2026-10-12 – 2026-10-14" in out


def test_html_without_dates_has_no_timeline_and_no_nodes_still_renders(monkeypatch):
    assert "Zeitachse" not in graph(monkeypatch, routes([iss(1)]), "--format", "html")[0].output
    assert "<svg" in graph(monkeypatch, routes([]), "--format", "html")[0].output


def test_html_40_nodes_fit_one_viewbox_and_warn(monkeypatch):
    res, _ = graph(monkeypatch, routes([iss(n) for n in range(1, 41)]), "--format", "html")
    assert "warning: 40 nodes" in res.output and 'width:100%' in res.output and "viewBox" in res.output
