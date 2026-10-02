"""kvasir doctor. Nothing here runs a real install or touches the network: which/run are mocked."""
import subprocess
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from kvasir import doctor
from kvasir.cli import app
from kvasir.config import LocalConfig, RepoConfig, save_local, save_repos

GH = doctor.CLIS["github"]
AUTH_OK = "github.com\n  ✓ Logged in\n  - Token scopes: 'gist', 'read:org', 'repo'\n"


class Env:
    """Fake machine: which() knows `have`, run() answers by argv prefix, records every call."""

    def __init__(self, monkeypatch, have=("git", "gh"), runs=None):
        self.calls, self.have, self.runs = [], set(have), runs or {}
        # only doctor's own view is faked, so repo setup in the same test still uses the real tools
        monkeypatch.setattr(doctor, "shutil", SimpleNamespace(
            which=lambda n: f"/bin/{n}" if n in self.have else None))
        monkeypatch.setattr(doctor, "subprocess", SimpleNamespace(
            run=self._run, DEVNULL=subprocess.DEVNULL, SubprocessError=subprocess.SubprocessError, TimeoutExpired=subprocess.TimeoutExpired))

    def _run(self, argv, **kw):
        self.calls.append(argv)
        assert kw["timeout"] and kw["stdin"] is not None
        for prefix, (code, out) in self.runs.items():
            if " ".join(argv).startswith(prefix):
                return type("R", (), {"returncode": code, "stdout": out.encode(), "stderr": b""})()
        return type("R", (), {"returncode": 0, "stdout": b"", "stderr": b""})()


@pytest.fixture
def env(monkeypatch):
    return Env(monkeypatch, runs={"git --version": (0, "git version 2.43.0"), "gh auth status": (0, AUTH_OK)})


def by_text(checks, part):
    return next(c for c in checks if part in c.text)


# --- individual checks

def test_git_version(monkeypatch):
    Env(monkeypatch, runs={"git --version": (0, "git version 2.35.9")})
    c = doctor.check_git()
    assert c.status == "fail" and "2.36" in c.fix
    Env(monkeypatch, runs={"git --version": (0, "git version 2.43.0.windows.1")})
    assert doctor.check_git().status == "ok"
    Env(monkeypatch, have=())  # run() mocked, still returns 0 with empty output -> unparsable
    assert doctor.check_git().status == "fail"


def test_gh_missing_not_logged_in_scope(monkeypatch):
    Env(monkeypatch, have=("git",))
    c = doctor.check_cli(GH, "linux", "ID=arch")[0]
    assert c.status == "fail" and c.missing is GH and c.fix == "sudo pacman -S github-cli"

    Env(monkeypatch, runs={"gh auth status": (1, "You are not logged into any GitHub hosts")})
    assert by_text(doctor.check_cli(GH, "linux", ""), "not logged in").fix == "gh auth login"

    Env(monkeypatch, runs={"gh auth status": (0, AUTH_OK)})
    w = by_text(doctor.check_cli(GH, "linux", ""), "read:project")
    assert w.status == "warn" and w.fix == "gh auth refresh -s read:project"

    Env(monkeypatch, runs={"gh auth status": (0, "Token scopes: 'repo', 'read:project'")})
    assert all(c.status == "ok" for c in doctor.check_cli(GH, "linux", ""))
    Env(monkeypatch, runs={"gh auth status": (0, "Token scopes: 'repo', 'project'")})
    assert all(c.status == "ok" for c in doctor.check_cli(GH, "linux", ""))
    Env(monkeypatch, runs={"gh auth status": (0, "logged in, no scope line")})
    assert by_text(doctor.check_cli(GH, "linux", ""), "not readable").status == "warn"


def test_auth_status_never_raises(monkeypatch):
    def boom(*a, **k):
        raise subprocess.TimeoutExpired("gh", 1)
    Env(monkeypatch)
    monkeypatch.setattr(doctor.subprocess, "run", boom)
    assert by_text(doctor.check_cli(GH, "linux", ""), "not runnable").status == "warn"


@pytest.mark.parametrize("osr,expected", [
    ('NAME="Arch Linux"\nID=arch\n', "sudo pacman -S github-cli"),
    ("ID=fedora\nVERSION_ID=40\n", "sudo dnf install gh"),
    ('ID=debian\nID_LIKE=""\n', doctor.LINUX_DOCS),
    ('ID=linuxmint\nID_LIKE="ubuntu debian"\n', doctor.LINUX_DOCS),
    ("ID=nixos\n", "see https://cli.github.com"),
    ("", "see https://cli.github.com"),
])
def test_linux_hint(osr, expected):
    assert doctor.install_hint(GH, "linux", osr) == expected


def test_os_release_read_error_means_unknown(monkeypatch, tmp_path):
    monkeypatch.setattr(doctor, "OS_RELEASE", tmp_path / "nope")
    Env(monkeypatch, have=())
    assert doctor.check_cli(GH, "linux")[0].fix == "see https://cli.github.com"


def test_windows_mac_hint_needs_package_manager(monkeypatch):
    Env(monkeypatch, have=("winget", "brew"))
    assert doctor.install_hint(GH, "win32") == "winget install --id GitHub.cli"
    assert doctor.install_hint(GH, "darwin") == "brew install gh"
    Env(monkeypatch, have=())
    assert "winget not found" in doctor.install_hint(GH, "win32")
    assert "brew not found" in doctor.install_hint(GH, "darwin")


def test_azure_prepared_but_inactive():
    assert not doctor.CLIS["azure"].active


def test_platform_azure_not_supported_and_other_host():
    c = doctor.check_platform("dev.azure.com/org/proj/repo")[0]
    assert c.status == "warn" and "not supported yet (#26)" in c.text
    assert doctor.check_platform("gitlab.com/o/r")[0].status == "ok"


# --- install offer

@pytest.mark.parametrize("system,argv", [
    ("win32", ["winget", "install", "--id", "GitHub.cli"]), ("darwin", ["brew", "install", "gh"])])
def test_install_only_after_yes(monkeypatch, system, argv):
    e = Env(monkeypatch, have=("winget", "brew"))
    assert doctor.offer_install(GH, system, lambda q: False, print) is False
    assert e.calls == []
    assert doctor.offer_install(GH, system, lambda q: argv[0] in q, lambda m: None) is True
    assert e.calls == [argv]


def test_linux_never_installs(monkeypatch):
    e = Env(monkeypatch, have=("sudo", "pacman", "apt", "winget", "brew"))
    asked = []
    assert doctor.offer_install(GH, "linux", lambda q: asked.append(q) or True, print) is False
    assert doctor.install_argv(GH, "linux") is None
    assert asked == [] and e.calls == []


def test_report_offers_then_rechecks(monkeypatch):
    e = Env(monkeypatch, have=("brew",), runs={"git --version": (0, "git version 2.43.0")})
    out = []

    def checks():
        return doctor.check_cli(GH, "darwin")

    def ask(q):
        e.have.add("gh")  # as if the install had worked
        return True

    assert doctor.report(checks, True, ask, out.append, "darwin") == 0
    assert ["brew", "install", "gh"] in e.calls
    assert any(line.startswith("✓ gh installed") for line in out)


def test_report_no_tty_no_question(monkeypatch):
    e = Env(monkeypatch, have=("brew",))
    out = []
    code = doctor.report(lambda: doctor.check_cli(GH, "darwin"), False, lambda q: pytest.fail(q), out.append, "darwin")
    assert code == 1 and e.calls == [] and out[0].startswith("✗ gh not installed")
    assert "brew install gh" in out[0]


# --- command

def test_doctor_exit_codes(monkeypatch, env):
    r = CliRunner().invoke(app, ["doctor"])
    assert r.exit_code == 0, r.output  # warn (scope) is no failure
    assert "✓ git 2.43.0" in r.stdout and "! scope read:project missing" in r.stdout
    assert "-> gh auth refresh -s read:project" in r.stdout
    Env(monkeypatch, have=("git",), runs={"git --version": (0, "git version 2.43.0")})
    r = CliRunner().invoke(app, ["doctor"])
    assert r.exit_code == 1 and "✗ gh not installed" in r.stdout


def test_doctor_broken_config_and_missing_path(env, cfg_dir):
    cfg_dir.mkdir()
    (cfg_dir / "repos.toml").write_text("not [valid", encoding="utf-8")
    r = CliRunner().invoke(app, ["doctor"])
    assert r.exit_code == 1 and "✗ repos.toml not readable" in r.stdout and "✓ local.toml readable" in r.stdout


def test_doctor_repos(env, tmp_path):
    save_repos({"github.com/o/r": RepoConfig(), "dev.azure.com/org/p/r": RepoConfig()})
    save_local(LocalConfig(paths={"github.com/o/r": str(tmp_path / "gone")}))
    r = CliRunner().invoke(app, ["doctor"])
    assert r.exit_code == 0
    assert "local path missing" in r.stdout and "github.com/o/r: github, gh available" in r.stdout
    assert "Azure DevOps not supported yet (#26)" in r.stdout


# --- setup integration

@pytest.fixture
def tty(monkeypatch):
    monkeypatch.setattr("kvasir.cli._interactive", lambda: True)


def test_setup_runs_check_with_tty(make_repo, tty, env):
    r = CliRunner().invoke(app, ["setup", str(make_repo()), "-p", "{type}/{slug}"])
    assert r.exit_code == 0, r.output
    assert "✓ gh installed" in r.stdout and "github.com/o/r: github, gh available" in r.stdout


def test_setup_no_cli_check(make_repo, tty, env):
    r = CliRunner().invoke(app, ["setup", str(make_repo()), "-p", "{type}/{slug}", "--no-cli-check"])
    assert r.exit_code == 0 and "gh installed" not in r.stdout and env.calls == []


def test_setup_without_tty_skips_check(make_repo, env):
    r = CliRunner().invoke(app, ["setup", str(make_repo())])
    assert r.exit_code == 0 and "gh installed" not in r.stdout


def test_setup_missing_gh_declined_still_registered(make_repo, tty, monkeypatch):
    e = Env(monkeypatch, have=("brew",))
    monkeypatch.setattr(doctor, "sys", SimpleNamespace(platform="darwin"))
    r = CliRunner().invoke(app, ["setup", str(make_repo()), "-p", "{type}/{slug}"], input="\n")
    assert r.exit_code == 0 and "Registered" in r.stdout
    assert "Install gh now with `brew install gh`?" in r.stdout and "✗ gh not installed" in r.stdout
    assert ["brew", "install", "gh"] not in e.calls


def test_setup_azure_remote_not_supported(make_repo, tty, env):
    r = CliRunner().invoke(app, ["setup", str(make_repo(remote="https://dev.azure.com/org/p/_git/r")),
                                 "-p", "{type}/{slug}"])
    assert r.exit_code == 0 and "not supported yet (#26)" in r.stdout
