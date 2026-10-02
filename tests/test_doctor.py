"""kvasir doctor. Nothing here runs a real install or touches the network: which/run are mocked."""
import subprocess
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from kvasir import doctor
from kvasir.cli import app
from kvasir.config import LocalConfig, RepoConfig, save_local, save_repos

GH = doctor.CLIS["github"]
AZ = doctor.CLIS["azure"]
AZ_EXT = '[{"name": "azure-devops", "version": "1.0.1"}]'
AZ_KEY = "dev.azure.com/org/proj/_git/repo"
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


def test_platform_other_host_and_azure_states(monkeypatch):
    assert doctor.check_platform("gitlab.com/o/r")[0].status == "ok"
    Env(monkeypatch, have=("az",))
    assert doctor.check_platform(AZ_KEY)[0].text == f"{AZ_KEY}: azure, az available"
    Env(monkeypatch, have=())
    c = doctor.check_platform(AZ_KEY, "linux")[0]
    assert c.status == "fail" and "az missing" in c.text and c.missing is AZ
    assert c.fix == f"see {AZ.docs}"


def az_env(monkeypatch, show=(0, "{}"), ext=(0, AZ_EXT)):
    return Env(monkeypatch, have=("az",), runs={"az account show": show, "az extension list": ext})


def test_az_checks(monkeypatch):
    Env(monkeypatch, have=())
    c = doctor.check_cli(AZ, "darwin")[0]
    assert c.status == "fail" and c.missing is AZ and c.text == "az not installed"

    az_env(monkeypatch)
    assert [c.status for c in doctor.check_cli(AZ, "linux", "")] == ["ok", "ok", "ok"]

    az_env(monkeypatch, show=(1, "ERROR: Please run 'az login' to setup account."))
    assert by_text(doctor.check_cli(AZ, "linux", ""), "not logged in").fix == "az login"

    az_env(monkeypatch, ext=(0, '[{"name": "other"}]'))
    c = by_text(doctor.check_cli(AZ, "linux", ""), "azure-devops missing")
    assert c.status == "fail" and c.fix == "az extension add --name azure-devops"


@pytest.mark.parametrize("bad,status", [
    ((0, "not json"), "warn"), ((0, '{"name": "azure-devops"}'), "fail"), ((0, "[1, null]"), "fail"), ((1, "boom"), "warn")])
def test_az_extension_output_parsed_defensively(monkeypatch, bad, status):
    az_env(monkeypatch, ext=bad)
    c = next(c for c in doctor.check_cli(AZ, "linux", "") if "extension" in c.text)
    assert c.status == status  # never "ok", never raises


def test_az_never_runs_login_or_extension_add(monkeypatch):
    e = az_env(monkeypatch, show=(1, ""), ext=(0, "[]"))
    doctor.check_cli(AZ, "linux", "")
    assert e.calls == [["az", "account", "show", "-o", "json"], ["az", "extension", "list", "-o", "json"]]


# --- install offer

@pytest.mark.parametrize("system,argv", [
    ("win32", ["winget", "install", "--id", "GitHub.cli"]), ("darwin", ["brew", "install", "gh"])])
def test_install_only_after_yes(monkeypatch, system, argv):
    e = Env(monkeypatch, have=("winget", "brew"))
    assert doctor.offer_install(GH, system, lambda q: False, print) is False
    assert e.calls == []
    assert doctor.offer_install(GH, system, lambda q: argv[0] in q, lambda m: None) is True
    assert e.calls == [argv]


@pytest.mark.parametrize("system,argv", [
    ("win32", ["winget", "install", "--id", "Microsoft.AzureCLI"]), ("darwin", ["brew", "install", "azure-cli"])])
def test_az_install_only_after_yes(monkeypatch, system, argv):
    e = Env(monkeypatch, have=("winget", "brew"))
    assert doctor.offer_install(AZ, system, lambda q: False, print) is False
    assert e.calls == []
    assert doctor.offer_install(AZ, system, lambda q: True, lambda m: None) is True
    assert e.calls == [argv]


def test_az_linux_shows_only(monkeypatch):
    e = Env(monkeypatch, have=("sudo", "apt", "dnf", "brew"))
    assert doctor.offer_install(AZ, "linux", lambda q: pytest.fail(q), print) is False
    assert e.calls == [] and doctor.install_hint(AZ, "linux", "ID=ubuntu") == f"see {AZ.docs}"


def test_report_asks_once_per_cli_for_both(monkeypatch):
    e = Env(monkeypatch, have=("brew",))
    asked = []

    def checks():
        return (doctor.check_cli(GH, "darwin") + doctor.check_cli(AZ, "darwin")
                + doctor.check_platform(AZ_KEY, "darwin") + doctor.check_platform("github.com/o/r", "darwin"))

    doctor.report(checks, True, lambda q: asked.append(q) or False, lambda m: None, "darwin")
    assert len(asked) == 2 and "gh" in asked[0] and "az" in asked[1] and e.calls == []


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
    save_repos({"github.com/o/r": RepoConfig(), AZ_KEY: RepoConfig()})
    save_local(LocalConfig(paths={"github.com/o/r": str(tmp_path / "gone")}))
    r = CliRunner().invoke(app, ["doctor"])
    assert "local path missing" in r.stdout and "github.com/o/r: github, gh available" in r.stdout
    assert "✗ az not installed" in r.stdout and f"{AZ_KEY}: azure, az missing" in r.stdout and r.exit_code == 1


def test_doctor_azure_repo_with_az(monkeypatch):
    Env(monkeypatch, have=("git", "gh", "az"), runs={
        "git --version": (0, "git version 2.43.0"), "gh auth status": (0, AUTH_OK),
        "az account show": (0, "{}"), "az extension list": (0, AZ_EXT)})
    save_repos({AZ_KEY: RepoConfig()})
    r = CliRunner().invoke(app, ["doctor"])
    assert r.exit_code == 0, r.stdout
    assert "✓ az logged in" in r.stdout and "✓ az extension azure-devops installed" in r.stdout
    assert f"{AZ_KEY}: azure, az available" in r.stdout


def test_doctor_github_only_ignores_az(env):
    save_repos({"github.com/o/r": RepoConfig()})
    r = CliRunner().invoke(app, ["doctor"])
    assert "az " not in r.stdout and "azure" not in r.stdout


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


def test_setup_azure_repo_checks_az(make_repo, tty, monkeypatch):
    Env(monkeypatch, have=("az",), runs={
        "az account show": (1, "ERROR: Please run 'az login'"), "az extension list": (0, "[]")})
    r = CliRunner().invoke(app, ["setup", str(make_repo(remote="https://dev.azure.com/org/p/_git/r")),
                                 "-p", "{type}/{slug}"])
    assert r.exit_code == 0 and "✓ az installed" in r.stdout
    assert "✗ az not logged in" in r.stdout and "-> az login" in r.stdout
    assert "-> az extension add --name azure-devops" in r.stdout
    assert "dev.azure.com/org/p/_git/r: azure, az available" in r.stdout
