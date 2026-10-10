"""`kvasir metrics` von außen: CLI-Aufruf, `gh`-Antworten als Fixtures (nie echtes gh, nur lesend)."""
import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from kvasir.cli import app
from kvasir.platform import gh as ghmod

FIX = Path(__file__).parent / "fixtures" / "metrics"
runner = CliRunner()

@pytest.fixture(autouse=True)
def _cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # metrics.tsv wird im aktuellen Ordner gesucht


HEAD = "id\tart\tname\tunit\tsource\ttarget\n"
CYCLE = "cycle\tlagging\tDurchlaufzeit\th\tticket_cycle_time\t24\n"


class FakeGh:
    def __init__(self, monkeypatch, issues, timelines, prs=(), runs=(), items=None):
        self.calls, self.issues, self.timelines, self.prs, self.runs = [], issues, timelines, list(prs), list(runs)
        self.items = items or {}
        monkeypatch.setattr(ghmod.subprocess, "run", self)

    def __call__(self, args, **kw):
        assert args[0] == "gh"
        self.calls.append(args)
        if args[1] in ("pr", "run"):
            assert args[2] == "list"
            return subprocess.CompletedProcess(args, 0, json.dumps(self.prs if args[1] == "pr" else self.runs).encode(), b"")
        path = args[2].split("?")[0]
        if path.split("/")[-2:-1] == ["issues"]:  # repos/o/r/issues/N
            ans = self.items[int(path.split("/")[-1])]
        elif path == "repos/o/r/issues":
            ans = self.issues
        else:
            ans = self.timelines[int(path.split("/")[-2])]  # KeyError = unerwarteter Aufruf
        return subprocess.CompletedProcess(args, 0, json.dumps(ans).encode(), b"")


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def closed_issue(n, closed_at):
    return {"number": n, "title": f"T{n}", "state": "closed", "state_reason": "completed", "labels": [],
            "body": None, "milestone": None, "closed_at": closed_at,
            "repository_url": "https://api.github.com/repos/o/r"}


def timeline(start, end):
    """start/end: datetime oder None; Form wie die echte Timeline (gekürzt)."""
    ev = [{"event": "labeled", "created_at": "2020-01-01T00:00:00Z", "label": {"name": "ready-for-agent"}}]
    if start:
        ev.append({"event": "labeled", "created_at": iso(start), "label": {"name": "status:in-progress"}})
    if end:
        ev.append({"event": "closed", "created_at": iso(end), "label": None})
    return ev


def run(tmp_path, metrics_tsv, *args):
    (tmp_path / "workflow").mkdir(exist_ok=True)
    if metrics_tsv is not None:
        (tmp_path / "workflow" / "metrics.tsv").write_text(metrics_tsv, encoding="utf-8")
    return runner.invoke(app, ["metrics", "--repo", "o/r", *args])


def hours(tmp_path, monkeypatch, *durations_h, extra=()):
    now = datetime.now(UTC).replace(microsecond=0)
    issues, tls = [], {}
    for i, h in enumerate(durations_h, 1):
        end = now - timedelta(days=1)
        issues.append(closed_issue(i, iso(end)))
        tls[i] = timeline(end - timedelta(hours=h), end)
    for n, i, t in extra:
        issues.append(i)
        tls[n] = t
    return FakeGh(monkeypatch, issues, tls)


def test_median_n_und_einheit(tmp_path, monkeypatch):
    fake = hours(tmp_path, monkeypatch, 10, 30, 20, 40)
    res = run(tmp_path, HEAD + CYCLE)
    assert res.exit_code == 0, res.output
    assert "Durchlaufzeit" in res.output and "25 h" in res.output and "n=4" in res.output and "Ziel 24" in res.output
    assert all(c[1] in ("api", "pr", "run") and c[2] != "create" and "-X" not in c and "--method" not in c for c in fake.calls)  # nur lesend


def test_einheit_tage(tmp_path, monkeypatch):
    hours(tmp_path, monkeypatch, 24, 48, 72)
    res = run(tmp_path, HEAD + "cycle\tlagging\tDurchlaufzeit\td\tticket_cycle_time\t\n")
    assert "2 d" in res.output and "n=3" in res.output


def test_ticket_ohne_in_arbeit_zaehlt_nicht(tmp_path, monkeypatch):
    now = datetime.now(UTC).replace(microsecond=0)
    extra = [(9, closed_issue(9, iso(now)), timeline(None, now))]
    hours(tmp_path, monkeypatch, 10, 20, 30, extra=extra)
    assert "n=3" in run(tmp_path, HEAD + CYCLE).output


def test_zu_klein(tmp_path, monkeypatch):
    hours(tmp_path, monkeypatch, 10, 20)
    out = run(tmp_path, HEAD + CYCLE).output
    assert "n=2" in out and "zu klein" in out and "15 h" not in out


def test_keine_daten(tmp_path, monkeypatch):
    hours(tmp_path, monkeypatch)
    out = run(tmp_path, HEAD + CYCLE).output
    assert "keine Daten" in out


def test_ausserhalb_zeitraum_zaehlt_nicht(tmp_path, monkeypatch):
    old = datetime(2020, 1, 3, tzinfo=UTC)
    FakeGh(monkeypatch, [closed_issue(1, iso(old))], {1: timeline(old - timedelta(hours=5), old)})
    assert "keine Daten" in run(tmp_path, HEAD + CYCLE).output
    assert "n=1" in run(tmp_path, HEAD + CYCLE, "--since", "36500d").output


def test_unbekannte_quelle(tmp_path, monkeypatch):
    hours(tmp_path, monkeypatch, 10, 20, 30)
    out = run(tmp_path, HEAD + "x\tlagging\tNeu\tn\tgibt_es_nicht\t\n").output
    assert "unbekannt" in out


def test_echte_timeline_form(tmp_path, monkeypatch):
    """Gekürzte echte Antwort von comcy/comcy.github.io#134: 20:36:54 -> 09:05:47 am Folgetag = 12,5 h."""
    real = json.loads((FIX / "timeline_real.json").read_text(encoding="utf-8"))
    ns = (134, 135, 136)
    FakeGh(monkeypatch, [closed_issue(n, "2026-10-10T09:05:47Z") for n in ns], dict.fromkeys(ns, real))
    res = run(tmp_path, HEAD + CYCLE, "--since", "36500d")
    assert "12.5 h" in res.output and "n=3" in res.output


def test_ohne_metrics_tsv(tmp_path):
    res = run(tmp_path, None)
    assert res.exit_code == 1 and "metrics.tsv" in res.output


def test_ungueltiges_since(tmp_path):
    assert run(tmp_path, HEAD + CYCLE, "--since", "x").exit_code == 2


PRD = "prd\tleading\tPR-Dauer\th\tpr_duration\t\n"
RED = "red\tleading\tPRs mit rotem Lauf\t%\tci_red_before_merge\t\n"


def pr(n, created, merged, branch=None):
    return {"number": n, "title": f"P{n}", "createdAt": iso(created), "mergedAt": iso(merged),
            "headRefName": branch or f"feat/{n}"}


def ci(branch, when, conclusion="success", event="pull_request"):
    return {"conclusion": conclusion, "createdAt": iso(when), "headBranch": branch, "event": event}


def prs_fake(monkeypatch, prs, runs=()):
    return FakeGh(monkeypatch, [], {}, prs, runs)


def test_pr_duration_median(tmp_path, monkeypatch):
    t = datetime.now(UTC).replace(microsecond=0) - timedelta(days=2)
    fake = prs_fake(monkeypatch, [pr(i, t, t + timedelta(hours=h)) for i, h in enumerate((1, 2, 6, 10), 1)])
    out = run(tmp_path, HEAD + PRD).output
    assert "PR-Dauer: 4 h, n=4" in out
    assert all(c[2] == "list" for c in fake.calls if c[1] in ("pr", "run"))


def test_pr_duration_zu_klein_und_keine_daten(tmp_path, monkeypatch):
    t = datetime.now(UTC).replace(microsecond=0) - timedelta(days=2)
    prs_fake(monkeypatch, [pr(1, t, t + timedelta(hours=1))])
    assert "n=1 (zu klein)" in run(tmp_path, HEAD + PRD).output
    prs_fake(monkeypatch, [])
    assert "keine Daten" in run(tmp_path, HEAD + PRD).output


def test_ci_red_anteil(tmp_path, monkeypatch):
    """Ohne Läufe zählt nicht rot; mehrfach rot zählt einmal; rot nach Merge, Fremdlauf und cancelled zählen nicht."""
    t = datetime.now(UTC).replace(microsecond=0) - timedelta(days=2)
    h = timedelta(hours=1)
    prs = [pr(i, t, t + 4 * h) for i in (1, 2, 3, 4)]
    runs = [
        ci("feat/1", t + h, "failure"), ci("feat/1", t + 2 * h, "failure"), ci("feat/1", t + 3 * h),  # mehrfach rot
        ci("feat/2", t + h),  # grün
        # feat/3: keine Läufe
        ci("feat/4", t + 5 * h, "failure"),  # rot erst nach Merge
        ci("feat/4", t + h, "cancelled"),  # abgebrochen
        ci("feat/4", t + h, "failure", event="push"),  # anderes Ereignis
        ci("feat/9", t + h, "failure"),  # fremder Branch
    ]
    prs_fake(monkeypatch, prs, runs)
    assert "PRs mit rotem Lauf: 25 %, n=4" in run(tmp_path, HEAD + RED).output


def test_pr_zeitraum(tmp_path, monkeypatch):
    old = datetime(2020, 1, 3, tzinfo=UTC)
    prs_fake(monkeypatch, [pr(i, old, old + timedelta(hours=2)) for i in (1, 2, 3)])
    assert "keine Daten" in run(tmp_path, HEAD + PRD).output
    assert "2 h, n=3" in run(tmp_path, HEAD + PRD, "--since", "36500d").output


def test_echte_pr_und_lauf_form(tmp_path, monkeypatch):
    """Gekürzte echte Antworten von comcy/comcy.github.io (`gh pr list --state merged`, `gh run list`)."""
    prs = json.loads((FIX / "prs_real.json").read_text(encoding="utf-8"))
    runs = json.loads((FIX / "runs_real.json").read_text(encoding="utf-8"))
    prs_fake(monkeypatch, prs, runs)
    out = run(tmp_path, HEAD + PRD + RED, "--since", "36500d").output
    assert "0.1 h, n=4" in out and "0 %, n=4" in out


def test_pr_gh_fehler(tmp_path, monkeypatch):
    monkeypatch.setattr(ghmod.subprocess, "run", lambda a, **kw: subprocess.CompletedProcess(a, 1, b"", b"boom"))
    assert run(tmp_path, HEAD + PRD).exit_code == 1
# --- eval_pass_rate ---
EVALS = "e\tlagging\tEval-Bestehensquote\t%\teval_pass_rate\t80\n"


def test_eval_pass_rate_echter_bericht(tmp_path):
    res = run(tmp_path, HEAD + EVALS, "--evals", str(FIX / "evals"))
    assert res.exit_code == 0, res.output
    assert "75 %" in res.output and "n=4" in res.output and "Ziel 80" in res.output  # nur der neueste Bericht


def test_eval_standardpfad_und_altformat_ohne_kosten(tmp_path):
    d = tmp_path / "evals" / "reports"
    d.mkdir(parents=True)
    (d / "2026-01-01-0000.md").write_text(
        "| Aufgabe | Läufe | Ergebnis |\n| --- | --- | --- |\n| a | 3/3 | bestanden |\n"
        "| b | 0/3 | durchgefallen |\n| c | 0/0 | nicht prüfbar |\n| d | 3/3 | bestanden |\n", encoding="utf-8")
    out = run(tmp_path, HEAD + EVALS).output
    assert "66.7 %" in out and "n=3" in out  # nicht prüfbar zählt nicht


def test_eval_keine_berichte(tmp_path):
    assert "keine Daten" in run(tmp_path, HEAD + EVALS).output
    assert "keine Daten" in run(tmp_path, HEAD + EVALS, "--evals", str(tmp_path / "nix")).output


def test_eval_ohne_github_aufruf(tmp_path, monkeypatch):
    fake = FakeGh(monkeypatch, [], {})
    run(tmp_path, HEAD + EVALS, "--evals", str(FIX / "evals"))
    assert fake.calls == []


# --- rework_fixes_per_change ---
REWORK = "r\tlagging\tNacharbeit\tn\trework_fixes_per_change\t1\n"


def pr_rework(n, title, body, state="MERGED", created="2099-01-01T00:00:00Z"):
    return {"number": n, "title": title, "state": state, "isDraft": False, "url": f"https://x/{n}", "author": {"login": "a"},
            "headRefName": f"b{n}", "closingIssuesReferences": [], "createdAt": created, "body": body}


def item(n, parent=None):
    d = closed_issue(n, "2099-01-01T00:00:00Z")
    if parent:
        d["parent_issue_url"] = f"https://api.github.com/repos/o/r/issues/{parent}"
    return d


def test_nacharbeit_treffer_fehltreffer_ohne_bezug(tmp_path, monkeypatch):
    # Features 10 (Sub-Issues 11, 12), 20 (Sub-Issue 21), 30 (ohne Sub-Issue): alle geschlossen
    issues = [item(11, 10), item(12, 10), item(21, 20), item(30)]
    offen = {**item(22, 20), "state": "open", "closed_at": None}
    prs = [
        pr_rework(1, "fix(a): x", "Refs #11"),                      # Treffer -> Feature 10
        pr_rework(2, "fix(b): y", "Closes #12"),                    # Treffer -> Feature 10
        pr_rework(3, "feat(a): z", "Refs #11"),                     # Fehltreffer: kein fix
        pr_rework(4, "fix(c): w", "kein Bezug"),                    # kein Bezug
        pr_rework(5, "fix(d): v", "Refs #21", state="CLOSED"),      # nicht gemergt
        pr_rework(6, "fix(e): u", "Closes #30"),                    # Treffer -> Feature 30 (ohne Parent = selbst)
        pr_rework(8, "fix: offen", "Refs #22"),                     # Treffer -> Feature 20 (Issue 22 offen, Parent per item())
        pr_rework(7, "fix: alt", "Refs #11", created="2000-01-01T00:00:00Z"),  # außerhalb Zeitraum
    ]
    FakeGh(monkeypatch, issues, {}, prs, items={22: offen})
    out = run(tmp_path, HEAD + REWORK).output
    assert "1.3, n=3" in out and "Heuristik" in out  # (2+1+1)/3 Features


def test_nacharbeit_keine_daten(tmp_path, monkeypatch):
    FakeGh(monkeypatch, [], {}, [])
    assert "keine Daten" in run(tmp_path, HEAD + REWORK).output


# --- Formate (#75) ---
ALLE = (CYCLE + PRD + "x\tlagging\tNeu\tn\tgibt_es_nicht\t\n"
        + "e|f\tleading\tPipe | Name\t%\teval_pass_rate\t80\n")


def fmt_setup(tmp_path, monkeypatch):
    t = datetime.now(UTC).replace(microsecond=0) - timedelta(days=2)
    issues = [closed_issue(i, iso(t)) for i in (1, 2, 3)]
    tls = {i: timeline(t - timedelta(hours=h), t) for i, h in ((1, 10), (2, 20), (3, 30))}
    FakeGh(monkeypatch, issues, tls, [pr(1, t, t + timedelta(hours=1)), pr(2, t, t + timedelta(hours=2))])
    d = tmp_path / "evals" / "reports"
    d.mkdir(parents=True)
    (d / "2026-01-01-0000.md").write_text("| Aufgabe | Ergebnis |\n| - | - |\n| a | bestanden |\n| b | durchgefallen |\n"
                                          "| c | bestanden |\n| d | bestanden |\n", encoding="utf-8")


def test_format_json_feste_schluessel(tmp_path, monkeypatch):
    fmt_setup(tmp_path, monkeypatch)
    res = run(tmp_path, HEAD + ALLE, "--format", "json")
    assert res.exit_code == 0, res.output
    data = json.loads(res.output)
    keys = ["id", "art", "name", "unit", "value", "n", "target", "status"]
    assert all(list(d) == keys for d in data)
    by = {d["id"]: d for d in data}
    assert by["cycle"] == {"id": "cycle", "art": "lagging", "name": "Durchlaufzeit", "unit": "h", "value": 20,
                           "n": 3, "target": 24, "status": "ok"}
    assert by["prd"]["value"] is None and by["prd"]["n"] == 2 and by["prd"]["status"] == "zu_klein"  # kein Wert bei n < 3
    assert by["x"] == {"id": "x", "art": "lagging", "name": "Neu", "unit": "n", "value": None, "n": None,
                       "target": None, "status": "unbekannt"}
    assert by["e|f"]["value"] == 75 and by["e|f"]["n"] == 4 and by["e|f"]["target"] == 80


def test_format_json_keine_daten(tmp_path, monkeypatch):
    hours(tmp_path, monkeypatch)
    [d] = json.loads(run(tmp_path, HEAD + CYCLE, "--format", "json").output)
    assert d["status"] == "keine_daten" and d["value"] is None and d["n"] == 0


def test_format_markdown_referenz(tmp_path, monkeypatch):
    fmt_setup(tmp_path, monkeypatch)
    res = run(tmp_path, HEAD + ALLE, "--format", "markdown")
    assert res.exit_code == 0, res.output
    assert res.output == (
        "| Id | Art | Metrik | Wert | n | Ziel | Status |\n"
        "| --- | --- | --- | ---: | ---: | ---: | --- |\n"
        "| cycle | lagging | Durchlaufzeit | 20 h | 3 | 24 | ok |\n"
        "| prd | leading | PR-Dauer | - | 2 | - | zu klein |\n"
        "| x | lagging | Neu | - | - | - | unbekannt |\n"
        "| e\\|f | leading | Pipe \\| Name | 75 % | 4 | 80 | ok |\n")


def test_format_ungueltig(tmp_path):
    assert run(tmp_path, HEAD + CYCLE, "--format", "xml").exit_code == 2


# --- Status-Labels aus workflow/states.tsv ---
def test_labels_aus_states_tsv_und_rueckfall(tmp_path, monkeypatch):
    now = datetime.now(UTC).replace(microsecond=0)
    end = now - timedelta(days=1)
    tl = [{"event": "labeled", "created_at": iso(end - timedelta(hours=h)), "label": {"name": "flow:in-progress"}} for h in (5,)]
    tl.append({"event": "closed", "created_at": iso(end), "label": None})
    FakeGh(monkeypatch, [closed_issue(i, iso(end)) for i in (1, 2, 3)], dict.fromkeys((1, 2, 3), tl))
    assert "keine Daten" in run(tmp_path, HEAD + CYCLE).output  # Rückfall: status:in-progress, Datei fehlt
    (tmp_path / "workflow" / "states.tsv").write_text(
        "id\tkind\tcolor\tdescription\nflow:in-progress\tstatus\t-\t-\nflow:in-review\tstatus\t-\t-\n"
        "in-progress\ttriage\t-\t-\n", encoding="utf-8")  # nur kind=status zählt
    assert "5 h" in run(tmp_path, HEAD + CYCLE).output
