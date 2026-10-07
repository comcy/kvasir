"""`kvasir status` auf Azure DevOps (#56): `az` als Fixture-Antworten (nicht live geprüft), nie echtes az."""
import json
import subprocess

from typer.testing import CliRunner

from kvasir.cli import app
from kvasir.platform import Azure
from kvasir.platform import az as azmod
from kvasir.platform.status import issue_status

runner = CliRunner()
def az():
    return Azure("contoso", "Shop", "webapp")


def wi(n, state="Active", tags="", due=None, start=None, target=None, it=None, rels=()):
    f = {"System.Title": f"T{n}", "System.State": state, "System.Tags": tags}
    for k, v in (("DueDate", due), ("StartDate", start), ("TargetDate", target)):
        if v:
            f[f"Microsoft.VSTS.Scheduling.{k}"] = v
    if it:
        f["System.IterationPath"] = it
    return {"id": n, "fields": f, "relations": [
        {"rel": f"System.LinkTypes.{r}", "url": f"https://dev.azure.com/contoso/_apis/wit/workItems/{i}"}
        for r, i in rels]}


def fake_az(monkeypatch, items, prs=(), refs=()):
    calls, real = [], subprocess.run

    def run(args, **kw):
        if args[0] == "openspec":  # nicht installiert
            raise FileNotFoundError
        if args[0] != "az":  # git läuft echt (tmp-Repos)
            return real(args, **kw)
        line = " ".join(args)
        calls.append(line)
        assert "create" not in line and "update" not in line, line  # nur lesend
        if "boards work-item show" in line:
            out = items[int(args[args.index("--id") + 1])]
        elif "repos pr list" in line:
            out = list(prs)
        elif "repos ref list" in line:
            out = [{"name": f"refs/heads/{r}"} for r in refs]
        elif "pr policy list" in line or "pr work-item list" in line:
            out = []
        else:
            raise AssertionError(f"unexpected az call: {line}")
        return subprocess.CompletedProcess(args, 0, json.dumps(out).encode(), b"")

    monkeypatch.setattr(azmod.subprocess, "run", run)
    return calls


def test_relations_dates_tags_and_status(monkeypatch):
    calls = fake_az(monkeypatch, {
        1: wi(1, rels=[("Hierarchy-Forward", 5), ("Hierarchy-Reverse", 9)]),
        5: wi(5, tags="status:in-review; backend", due="2026-12-31T00:00:00Z", start="2026-11-01T00:00:00Z",
              target="2026-12-15T00:00:00Z", it="Shop\\Sprint 12", rels=[("Dependency-Reverse", 7)]),
        7: wi(7, state="Active"),
    })
    st = issue_status(az(), 1).data
    assert st.repo == "contoso/shop/webapp"
    assert [s.item.number for s in st.sub_issues] == [5]  # Parent (9) ist kein Kind
    s = st.sub_issues[0]
    assert [b.number for b in s.blocked_by] == [7]  # Predecessor -> blocked_by
    assert s.status == "blocked"
    assert s.hint == "Label sagt in-review, Blocker #7 offen"  # Tag wie status:*-Label, Widerspruch -> Hinweis
    sc = s.item.schedule
    assert (sc.deadline.isoformat(), sc.deadlines[0].label) == ("2026-12-31", "Sprint 12")
    assert (str(sc.planned_from), str(sc.planned_to)) == ("2026-11-01", "2026-12-15")
    assert sc.planned_to < sc.deadline and not s.notices
    assert sum("work-item show --id 5" in c for c in calls) == 1  # je Item ein az-Aufruf


def test_closed_states_and_tag_fills_gap(monkeypatch):
    fake_az(monkeypatch, {1: wi(1, rels=[("Hierarchy-Forward", 2), ("Hierarchy-Forward", 3), ("Hierarchy-Forward", 4)]),
                          2: wi(2, state="Closed"), 3: wi(3, state="Removed"), 4: wi(4, tags="status:blocked")})
    subs = {s.item.number: s for s in issue_status(az(), 1).data.sub_issues}
    assert subs[2].status == "done" and subs[3].status == "dropped"
    assert (subs[4].status, subs[4].source) == ("blocked", "label")


def test_branch_makes_in_progress_and_pr_in_review(monkeypatch):
    pr = {"pullRequestId": 3, "title": "x", "status": "active", "sourceRefName": "refs/heads/feat/6-b",
          "createdBy": {"displayName": "A"}, "repository": {"name": "webapp"}}
    fake_az(monkeypatch, {1: wi(1, rels=[("Hierarchy-Forward", 5), ("Hierarchy-Forward", 6)]),
                          5: wi(5), 6: wi(6)}, prs=[pr], refs=["feat/5-a"])
    subs = {s.item.number: s for s in issue_status(az(), 1).data.sub_issues}
    assert (subs[5].status, subs[5].reason) == ("in_progress", "Branch feat/5-a")
    assert subs[6].status == "in_review"


def test_az_error_ends_with_its_error(monkeypatch):
    monkeypatch.setattr(azmod.subprocess, "run", lambda a, **k: subprocess.CompletedProcess(a, 1, b"", b"Please run 'az login'"))
    r = issue_status(az(), 1)
    assert not r.ok and r.error.kind.value == "not_logged_in"


def test_cli_detects_azure_origin(monkeypatch, tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "remote", "add", "origin",
                    "https://dev.azure.com/contoso/Shop/_git/webapp"], check=True)
    fake_az(monkeypatch, {1: wi(1)})
    monkeypatch.chdir(tmp_path)
    res = runner.invoke(app, ["status", "#1", "--format", "json"])
    assert res.exit_code == 0, res.output
    assert json.loads(res.output)["repo"] == "contoso/shop/webapp"
