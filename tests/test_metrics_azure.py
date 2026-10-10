"""`kvasir metrics` auf Azure DevOps (#74): `az`-Antworten als Fakes (Form UNVERIFIZIERT, nie echtes az, nur lesend)."""
import json
import subprocess
from datetime import UTC, datetime, timedelta

import pytest
from test_metrics import (
    CYCLE,
    EVALS,
    FIX,
    HEAD,
    PRD,
    RED,
    FakeGh,
    ci,
    closed_issue,
    iso,
    pr,
    timeline,
)
from typer.testing import CliRunner

from kvasir.cli import app
from kvasir.platform import az as azmod

runner = CliRunner()
REAL_RUN = subprocess.run  # vor den Fakes (diese patchen dasselbe Modul)
ALL = HEAD + CYCLE + PRD + RED


@pytest.fixture(autouse=True)
def _repo(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    real = REAL_RUN
    for cmd in (["init", "-q"], ["remote", "add", "origin", "https://dev.azure.com/contoso/Shop/_git/webapp"]):
        real(["git", "-C", str(tmp_path), *cmd], check=True)
    (tmp_path / "workflow").mkdir()


def metrics(tmp_path, tsv=ALL, *args):
    (tmp_path / "workflow" / "metrics.tsv").write_text(tsv, encoding="utf-8")
    return runner.invoke(app, ["metrics", *args])


def rev(n, when, state, tags=""):
    return {"id": 1, "rev": n, "fields": {"System.State": state, "System.Tags": tags, "System.ChangedDate": iso(when)}}


def revisions(start, end):
    """Form wie `az devops invoke --area wit --resource revisions` (REST: count + value), UNVERIFIZIERT."""
    revs = [rev(1, start - timedelta(days=3), "New", "ready-for-agent"),
            rev(2, start, "Active", "ready-for-agent; status:in-progress"),
            rev(3, start + timedelta(minutes=1), "Active", "status:in-progress; backend")]  # kein neuer Wechsel
    if end:
        revs.append(rev(4, end, "Closed", "status:in-progress"))
    return {"count": len(revs), "value": revs}


def az_pr(n, created, merged, branch):
    return {"pullRequestId": n, "status": "completed", "creationDate": iso(created), "closedDate": iso(merged),
            "sourceRefName": f"refs/heads/{branch}"}


def az_run(branch, when, result, reason="pullRequest"):
    return {"id": 1, "reason": reason, "result": result, "queueTime": iso(when), "sourceBranch": f"refs/heads/{branch}"}


class FakeAz:
    def __init__(self, monkeypatch, revs, prs=(), runs=(), fail=None):
        self.calls, self.revs, self.prs, self.runs, self.fail = [], revs, list(prs), list(runs), fail
        real = REAL_RUN

        def run(args, **kw):
            if args[0] != "az":
                return real(args, **kw)
            line = " ".join(args)
            self.calls.append(args)
            if fail:
                raise fail
            assert "create" not in line and "update" not in line and "delete" not in line, line
            if "boards query" in line:
                out = [{"id": n, "fields": {"System.State": "Closed"}} for n in revs]
            elif "devops invoke" in line:
                assert "--area wit" in line and "--resource revisions" in line and "--api-version 7.1" in line
                out = revs[int(args[args.index("--route-parameters") + 1].removeprefix("id="))]
            elif "repos pr list" in line:
                assert "--status completed" in line
                out = self.prs
            elif "pipelines runs list" in line:
                out = self.runs
            else:
                raise AssertionError(line)
            return subprocess.CompletedProcess(args, 0, json.dumps(out).encode(), b"")

        monkeypatch.setattr(azmod.subprocess, "run", run)


def scenario():
    now = datetime.now(UTC).replace(microsecond=0)
    t, h = now - timedelta(days=2), timedelta(hours=1)
    ends = [now - timedelta(days=1)] * 3
    return t, h, ends, [10, 20, 30]


def test_gleiche_werte_wie_github(tmp_path, monkeypatch):
    t, h, ends, durs = scenario()
    prs = [(i, t, t + i * h, f"feat/{i}") for i in (1, 2, 3)]
    runs = [("feat/1", t + h, "failure"), ("feat/2", t + h, "success"), ("feat/3", t + h, "success")]
    FakeGh(monkeypatch, [closed_issue(i, iso(e)) for i, e in enumerate(ends, 1)],
           {i: timeline(e - timedelta(hours=d), e) for i, (e, d) in enumerate(zip(ends, durs, strict=True), 1)},
           [pr(*p) for p in prs], [ci(b, w, c) for b, w, c in runs])
    (tmp_path / "workflow" / "metrics.tsv").write_text(ALL, encoding="utf-8")
    gh_out = runner.invoke(app, ["metrics", "--repo", "o/r"]).output
    FakeAz(monkeypatch, {i: revisions(e - timedelta(hours=d), e) for i, (e, d) in enumerate(zip(ends, durs, strict=True), 1)},
           [az_pr(*p) for p in prs], [az_run(b, w, {"failure": "failed", "success": "succeeded"}[c]) for b, w, c in runs])
    az_out = metrics(tmp_path).output
    assert az_out == gh_out and "20 h, n=3" in az_out and "2 h, n=3" in az_out and "33.3 %, n=3" in az_out


def test_nur_lesende_az_aufrufe_und_filter(tmp_path, monkeypatch):
    t, h, ends, _ = scenario()
    fake = FakeAz(monkeypatch, {1: revisions(t, ends[0])},
                  [az_pr(i, t, t + 3 * h, f"feat/{i}") for i in (1, 2, 3)],
                  [az_run("feat/1", t + 4 * h, "failed"),  # nach Merge
                   az_run("feat/1", t + h, "failed", reason="manual"),  # kein PR-Lauf
                   az_run("feat/1", t + h, "canceled"),
                   {"id": 2, "reason": "pullRequest", "result": "failed", "queueTime": iso(t + h),
                    "sourceBranch": "refs/pull/1/merge"}])  # PR-Validierung per refs/pull/<id>/merge
    out = metrics(tmp_path, HEAD + RED).output
    assert "33.3 %, n=3" in out
    assert {tuple(c[1:3]) for c in fake.calls} <= {("boards", "query"), ("devops", "invoke"), ("repos", "pr"), ("pipelines", "runs")}


def test_az_fehlt(tmp_path, monkeypatch):
    FakeAz(monkeypatch, {}, fail=FileNotFoundError())
    res = metrics(tmp_path)
    assert res.exit_code == 1 and "cli_missing" in res.output and "az not found" in res.output


def test_az_nicht_angemeldet(tmp_path, monkeypatch):
    real = REAL_RUN
    monkeypatch.setattr(azmod.subprocess, "run", lambda a, **kw: subprocess.CompletedProcess(
        a, 1, b"", b"Please run 'az login' to setup account.") if a[0] == "az" else real(a, **kw))
    res = metrics(tmp_path)
    assert res.exit_code == 1 and "not_logged_in" in res.output


def test_revisionen_tolerant(tmp_path, monkeypatch):
    """Nackte Liste statt {value}, Delta-Revisionen ohne Tags/State, Revision ohne Zeit, Großschreibung: kein Absturz."""
    t, _, ends, _ = scenario()
    odd = [{"rev": 1, "fields": {"System.State": "Active", "System.Tags": "Status:In-Progress",
                                 "System.ChangedDate": iso(t)}},
           {"rev": 2, "fields": {"System.Title": "x"}},
           {"rev": 3, "fields": {"System.State": "Done", "System.ChangedDate": iso(ends[0])}}]
    FakeAz(monkeypatch, {1: odd, 2: odd, 3: odd})
    out = metrics(tmp_path, HEAD + CYCLE).output
    assert "n=3" in out


def test_eval_ignoriert_nachtraegliche_anmerkung(tmp_path):
    res = metrics(tmp_path, HEAD + EVALS, "--evals", str(FIX / "evals_anmerkung"))
    assert res.exit_code == 0, res.output
    assert "75 %" in res.output and "n=4" in res.output  # neuester (mit Anmerkung) übersprungen -> 10-08-131313
