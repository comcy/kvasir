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
    def __init__(self, monkeypatch, issues, timelines):
        self.calls, self.issues, self.timelines = [], issues, timelines
        monkeypatch.setattr(ghmod.subprocess, "run", self)

    def __call__(self, args, **kw):
        assert args[0] == "gh"
        self.calls.append(args)
        path = args[2].split("?")[0]
        if path == "repos/o/r/issues":
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
    assert all(c[1] == "api" and "-X" not in c and "--method" not in c for c in fake.calls)  # nur lesend


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
