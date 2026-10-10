import os
import subprocess
from datetime import date, timedelta

import pytest
from typer.testing import CliRunner

from kvasir import doctor, report_out
from kvasir.cli import app
from kvasir.config import LocalConfig, RepoConfig, load_local, save_local, save_repos

URL = "github.com/o/r"
E = "me@x.org"

MD = "# Bericht 2026-01-02\n\n## github.com/o/r\n\n### Commits\n\n- 12:00 `abc` feat: x\n"
H = "## Woran gearbeitet"
SECTION = f"{H}\n\n### github.com/o/r\n\n#### Commits\n\n- 12:00 `abc` feat: x\n"


def git(cwd, *a, when=None):
    env = {"GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when} if when else {}
    subprocess.run(["git", "-C", str(cwd), *a], check=True, capture_output=True, env={**os.environ, **env})


@pytest.fixture
def repo(make_repo):
    root = make_repo("r")
    git(root, "config", "user.name", "Me")
    git(root, "config", "user.email", E)
    save_repos({URL: RepoConfig()})
    save_local(LocalConfig(paths={URL: str(root)}))
    return root


def commit(root, msg, day):
    git(root, "commit", "-q", "--allow-empty", "-m", msg, when=f"{day.isoformat()}T12:00:00")


def test_parse_defaults_and_invalid():
    c = report_out.parse({"output": "~/x/{date}.md"})
    assert (c.mode, c.heading) == ("append-section", H)
    for bad in ({}, {"output": ""}, {"output": "a", "mode": "x"}, {"output": "a", "heading": "Foo"},
                {"output": "a", "oops": 1}):
        with pytest.raises(ValueError):
            report_out.parse(bad)


def test_target_replaces_date_and_expands_home(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    assert report_out.target("~/{date}.md", date(2026, 1, 2)) == tmp_path / "2026-01-02.md"


def test_report_config_roundtrip(cfg_dir):
    save_local(LocalConfig(report={"output": "a/{date}.md", "mode": "overwrite"}))
    assert load_local().report == {"output": "a/{date}.md", "mode": "overwrite"}


def test_append_creates_missing_file_and_folder(tmp_path):
    p = tmp_path / "a" / "b.md"
    report_out.write(p, MD, "append-section", H)
    assert p.read_text(encoding="utf-8") == SECTION


def test_append_adds_missing_heading_keeps_text_and_is_idempotent(tmp_path):
    p = tmp_path / "n.md"
    before = "# Tag\r\n\r\ntext ohne Ende"
    p.write_bytes(before.encode())
    report_out.write(p, MD, "append-section", H)
    once = p.read_bytes()
    assert once.decode().startswith(before + "\n\n" + SECTION)
    report_out.write(p, MD, "append-section", H)
    assert p.read_bytes() == once


def test_append_replaces_only_section_until_next_same_or_higher_heading(tmp_path):
    p = tmp_path / "n.md"
    pre, post = "# Tag\n\nvorher\n\n", "## Später\n\nnachher\n"
    p.write_text(f"{pre}{H}\n\nalt\n\n### Unter\n\nalt2\n\n{post}", encoding="utf-8")
    report_out.write(p, MD, "append-section", H)
    t = p.read_text(encoding="utf-8")
    assert t == f"{pre}{SECTION}\n{post}"
    report_out.write(p, MD, "replace-section", H)
    assert p.read_text(encoding="utf-8") == t


def test_replace_section_does_not_create(tmp_path):
    p = tmp_path / "n.md"
    with pytest.raises(ValueError):
        report_out.write(p, MD, "replace-section", H)
    assert not p.exists()
    p.write_text("# Tag\n", encoding="utf-8")
    with pytest.raises(ValueError):
        report_out.write(p, MD, "replace-section", H)
    assert p.read_text(encoding="utf-8") == "# Tag\n"


def test_overwrite_replaces_whole_file(tmp_path):
    p = tmp_path / "n.md"
    p.write_text("alt", encoding="utf-8")
    report_out.write(p, MD, "overwrite", H)
    assert p.read_text(encoding="utf-8") == MD


def test_heading_level_shifts_report_headings(tmp_path):
    p = tmp_path / "n.md"
    report_out.write(p, MD, "append-section", "### Arbeit")
    assert p.read_text(encoding="utf-8").startswith("### Arbeit\n\n#### github.com/o/r\n\n##### Commits")


def test_doctor_reports_invalid_report(cfg_dir):
    assert doctor.check_report(LocalConfig()) == []
    assert doctor.check_report(LocalConfig(report={"output": "x"}))[0].status == "ok"
    bad = doctor.check_report(LocalConfig(report={"mode": "nope"}))
    assert bad[0].status == "fail" and "[report]" in bad[0].text


def _today(*args):
    return CliRunner().invoke(app, ["today", *args])


def test_today_uses_output_default_out_wins_stdout_suppresses(repo, tmp_path):
    d = date.today() - timedelta(days=1)
    commit(repo, "feat: o", d)
    conf = tmp_path / "{date}.md"
    save_local(LocalConfig(paths=load_local().paths, report={"output": str(conf)}))
    day = d.isoformat()
    r = _today("--date", day)
    assert r.exit_code == 0 and r.output == ""
    assert "## Woran gearbeitet" in (tmp_path / f"{day}.md").read_text(encoding="utf-8")
    other = tmp_path / "other.md"
    assert _today("--date", day, "--out", str(other)).output == ""
    assert "feat: o" in other.read_text(encoding="utf-8")
    (tmp_path / f"{day}.md").unlink()
    r = _today("--date", day, "--stdout", "--out", str(other))
    assert "feat: o" in r.output and not (tmp_path / f"{day}.md").exists()


def test_today_invalid_report_exits_2(repo):
    save_local(LocalConfig(paths=load_local().paths, report={"mode": "x"}))
    assert _today("--date", "2001-01-01").exit_code == 2
    assert _today("--date", "2001-01-01", "--stdout").exit_code == 0
