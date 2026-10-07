"""kvasir.toml / workflow/phases.tsv von außen: status, init, doctor, setup. Wegwerf-Repos, kein Netz."""
import json
import shutil
from pathlib import Path

import pytest
from test_doctor import AUTH_OK, Env
from test_status import FakeGh, issue, runner
from test_stepper import steps

from kvasir import repo_file
from kvasir.cli import app
from kvasir.config import LocalConfig, RepoConfig, load_repos, save_local, save_repos

URL = "github.com/o/r"
TSV = ("# Kommentar\nid\tname\ttool\tdone_when\tlevel\tenabled\n"
       "0\tEingang\t-\tissue_exists\trequired\t\n"
       "1\tGeschlossen\t-\tissue_closed\trequired\t\n"
       "2\tAus\t-\tissue_exists\trequired\tno\n"
       "3\tUnbekannt\t-\tbogus_detector\trequired\t\n"
       "4\tManuell\t-\t-\trequired\t\n")


def write(root, name, text):
    (root / name).parent.mkdir(parents=True, exist_ok=True)
    (root / name).write_text(text, encoding="utf-8")


@pytest.fixture
def repo(make_repo, monkeypatch):
    root = make_repo()
    monkeypatch.chdir(root)
    return root


def feature_status(monkeypatch):
    FakeGh(monkeypatch, {
        "repos/o/r/issues/1": json.dumps(issue(1)),
        "repos/o/r/issues/1/sub_issues": json.dumps([issue(5)]),
        "repos/o/r/issues/1/dependencies/blocked_by": "[]",
        "repos/o/r/issues/5/dependencies/blocked_by": "[]",
        "pr list": "[]", "repos/o/r/branches": "",
    })
    res = runner.invoke(app, ["status", "#1", "--repo", "o/r", "--format", "json"])
    assert res.exit_code == 0, res.output
    return json.loads(res.output)["issue"]


# --- status liest die Phasen

def test_status_default_phases_without_file(repo, monkeypatch):
    assert steps(feature_status(monkeypatch))[0][0] == "Setup"


def test_status_reads_workflow_tsv(repo, monkeypatch):
    write(repo, "workflow/phases.tsv", TSV)
    # "Aus" (enabled: no), "Unbekannt" (Detektor nicht im Vokabular) und "Manuell" (-) erscheinen nicht
    assert steps(feature_status(monkeypatch)) == [("Eingang", "done"), ("Geschlossen", "current")]


def test_status_from_subdirectory(repo, monkeypatch):
    write(repo, "workflow/phases.tsv", TSV)
    (repo / "sub").mkdir()
    monkeypatch.chdir(repo / "sub")
    assert steps(feature_status(monkeypatch))[0][0] == "Eingang"


def test_kvasir_toml_overrides_tsv(repo, monkeypatch):
    write(repo, "workflow/phases.tsv", TSV)
    write(repo, "kvasir.toml", '[[phases]]\nname = "Nur das"\ndone_when = ["issue_exists", "label:nope"]\n')
    assert steps(feature_status(monkeypatch)) == [("Nur das", "current")]


def test_unusable_file_falls_back_to_default(repo, monkeypatch):
    write(repo, "kvasir.toml", "[[phases")
    assert steps(feature_status(monkeypatch))[0][0] == "Setup"


# --- Detektoren sind nur Namen

def test_file_never_executes_code(repo, monkeypatch):
    write(repo, "kvasir.toml", '[[phases]]\nname = "X"\ndone_when = ["file_exists:__import__(\'os\').system(\'touch pwned\')"]\n')
    feature_status(monkeypatch)
    assert not (repo / "pwned").exists()


# --- Vorrang lokal > Repo > Standard

def test_precedence_patterns(repo):
    write(repo, "kvasir.toml", '[branches]\npatterns = ["features/{id}-{slug}"]\n')
    save_local(LocalConfig(paths={URL: str(repo)}))
    assert repo_file.patterns_for(URL) == ["features/{id}-{slug}"]  # Repo vor Standard (nicht registriert)
    save_repos({URL: RepoConfig(patterns_set=False)})
    assert repo_file.patterns_for(URL) == ["features/{id}-{slug}"]
    save_repos({URL: RepoConfig(["fixes/{id}-{slug}"])})
    assert repo_file.patterns_for(URL) == ["fixes/{id}-{slug}"]  # lokal vor Repo
    (repo / "kvasir.toml").unlink()
    save_repos({URL: RepoConfig(patterns_set=False)})
    assert repo_file.patterns_for(URL) == ["{type}/{slug}"]  # Standard


def test_setup_takes_shared_templates_without_local_copy(repo):
    write(repo, "kvasir.toml", '[branches]\npatterns = ["features/{id}-{slug}"]\n')
    r = CliRunnerSetup(repo)
    assert "features/{id}-{slug}" in r.output
    assert not load_repos()[URL].patterns_set


def CliRunnerSetup(repo, *a):
    r = runner.invoke(app, ["setup", str(repo), *a])
    assert r.exit_code == 0, r.output
    return r


def test_setup_pattern_flag_is_local_override(repo):
    write(repo, "kvasir.toml", '[branches]\npatterns = ["features/{id}-{slug}"]\n')
    CliRunnerSetup(repo, "-p", "fixes/{id}-{slug}")
    assert load_repos()[URL].patterns_set
    assert repo_file.patterns_for(URL) == ["fixes/{id}-{slug}"]


# --- init

@pytest.fixture
def tty(monkeypatch):
    monkeypatch.setattr("kvasir.cli._interactive", lambda: True)


def test_init_non_interactive_needs_yes(repo):
    r = runner.invoke(app, ["init", "-p", "{type}/{slug}"])
    assert r.exit_code == 1 and "+patterns" in r.output and not (repo / "kvasir.toml").exists()
    assert runner.invoke(app, ["init", "-p", "{type}/{slug}", "--yes"]).exit_code == 0
    assert repo_file.load(repo) == {"branches": {"patterns": ["{type}/{slug}"]}}


def test_init_unchanged_and_never_silent_overwrite(repo):
    runner.invoke(app, ["init", "-p", "{type}/{slug}", "-y"])
    assert "unchanged" in runner.invoke(app, ["init", "-p", "{type}/{slug}"]).output
    r = runner.invoke(app, ["init", "-p", "fixes/{id}-{slug}"])
    assert r.exit_code == 1 and "-patterns" in r.output and "+patterns" in r.output
    assert repo_file.load(repo)["branches"]["patterns"] == ["{type}/{slug}"]


def test_init_interactive_default_process_declined_write(repo, tty):
    r = runner.invoke(app, ["init"], input="1\ny\nn\n")  # Preset 1, Standardprozess ja, Schreiben nein
    assert r.exit_code == 1 and not (repo / "kvasir.toml").exists()
    r = runner.invoke(app, ["init"], input="1\ny\ny\n")
    assert r.exit_code == 0 and repo_file.load(repo) == {"branches": {"patterns": ["{type}/{slug}"]}}


def test_init_interactive_customize_phases(repo, tty):
    write(repo, "workflow/phases.tsv", TSV)
    # Preset 1, anpassen; Eingang behalten, Geschlossen: ungültiger Detektor, dann neu; Rest streichen; schreiben
    r = runner.invoke(app, ["init"], input="1\nn\n\nbogus\nissue_closed, label:x\nskip\nskip\ny\n")
    assert r.exit_code == 0, r.output
    ph = repo_file.load(repo)["phases"]
    assert ph == [{"name": "Eingang", "done_when": ["issue_exists"]},
                  {"name": "Geschlossen", "done_when": ["issue_closed", "label:x"]}]
    assert repo_file.problems(repo) == []


# --- doctor

@pytest.fixture
def doc(monkeypatch):
    return Env(monkeypatch, runs={"git --version": (0, "git version 2.43.0"), "gh auth status": (0, AUTH_OK)})


def doctor_out(repo, cfg=None):
    save_repos({URL: cfg or RepoConfig(patterns_set=False)})
    save_local(LocalConfig(paths={URL: str(repo)}))
    return runner.invoke(app, ["doctor"])


def test_doctor_reports_unknown_detector_and_missing_fields(repo, doc):
    write(repo, "kvasir.toml", '[[phases]]\nname = "A"\ndone_when = ["nope", "pr_state:x", "label"]\n'
                               '[[phases]]\ndone_when = []\n[[phases]]\nname = "C"\n')
    r = doctor_out(repo)
    assert r.exit_code == 1
    for part in ("unknown detector nope", "pr_state: x is not one of", "label needs an argument",
                 "required field name missing", "phase C: required field done_when missing"):
        assert part in r.output, r.output


def test_doctor_checks_tsv(repo, doc):
    write(repo, "workflow/phases.tsv", TSV)
    r = doctor_out(repo)
    assert "unknown detector bogus_detector" in r.output and r.exit_code == 1


def test_doctor_broken_toml(repo, doc):
    write(repo, "kvasir.toml", "[[phases")
    assert "kvasir.toml:" in doctor_out(repo).output


def test_doctor_conflict_with_local_override(repo, doc):
    write(repo, "kvasir.toml", '[branches]\npatterns = ["features/{id}-{slug}"]\n')
    r = doctor_out(repo, RepoConfig(["fixes/{id}-{slug}"]))
    assert "! " + URL + ": repos.toml branch_patterns override" in r.output and r.exit_code == 0
    assert "repo files ok" not in r.output
    assert "repo files ok" in doctor_out(repo, RepoConfig(["features/{id}-{slug}"])).output


def test_doctor_ok_and_silent_without_files(repo, doc):
    assert "repo files" not in doctor_out(repo).output
    write(repo, "kvasir.toml", '[branches]\npatterns = ["{type}/{slug}"]\n[[phases]]\nname = "A"\ndone_when = ["issue_exists"]\n')
    assert "repo files ok" in doctor_out(repo).output


# --- Vokabular aus workflow/detectors.tsv (#64): echte Dateien des Blog-Repos als Fixture

WF = Path(__file__).parent / "fixtures" / "workflow"


def blog_files(repo):
    shutil.copytree(WF, repo / "workflow")


def test_blog_phases_show_up_in_status(repo, monkeypatch):
    blog_files(repo)
    (repo / "openspec").mkdir()
    (repo / "openspec/config.yaml").write_text("x")
    monkeypatch.setattr("kvasir.platform.stepper._openspec", lambda: (False, False))  # kein Change, keiner archiviert
    got = steps(feature_status(monkeypatch))
    names = [n for n, _ in got]
    assert names[:2] == ["Setup (einmalig je Klon)", "Eingang"] and "Bauen und prüfen" in names
    assert "Wissen sichern" not in names  # done_when "-" = nicht erkennbar
    assert got[0] == ("Setup (einmalig je Klon)", "done")
    assert got[1] == ("Eingang", "current")  # kein Triage-Label am Issue


def test_blog_vocabulary_is_clean_in_doctor(repo, doc):
    blog_files(repo)
    r = doctor_out(repo)
    assert "repo files ok" in r.output and r.exit_code == 0, r.output


def test_doctor_uses_repo_vocabulary(repo, doc):
    blog_files(repo)
    # nur issue_open im Vokabular: label ist dort unbekannt, auch wenn kvasir es kennt
    write(repo, "workflow/detectors.tsv", "name\targ\tdescription\nissue_open\t-\td\nneu_ding\t-\td\n")
    write(repo, "workflow/phases.tsv",
          "id\tname\tdone_when\n0\tA\tlabel:x\n1\tB\tneu_ding\n2\tC\tissue_open:x\n")
    out = doctor_out(repo).output
    assert "unknown detector label" in out
    assert "detector neu_ding is not evaluated by kvasir" in out
    assert "detector issue_open takes no argument" in out
