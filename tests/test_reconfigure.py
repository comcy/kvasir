"""setup --reconfigure, kvasir config, repo_settings."""
import pytest
from typer.testing import CliRunner

from kvasir.cli import app
from kvasir.config import RepoConfig, load_local, load_repos, save_repos
from kvasir.repo_settings import PRESETS, preset_key, update_repo, validate_patterns

R = "github.com/o/r"


def ask(*args, input=""):
    return CliRunner().invoke(app, ["setup", *args], input=input)


def tty(monkeypatch, on=True):
    monkeypatch.setattr("kvasir.cli._interactive", lambda: on)


@pytest.fixture
def root(make_repo):
    save_repos({R: RepoConfig(["fixes/{id}-{slug}"], 30, 20), "github.com/o/other": RepoConfig(["{type}/{slug}"], 7, 8)})
    root = make_repo()
    assert ask(str(root)).exit_code == 0  # writes local.toml path, keeps existing entry
    return root


def test_reconfigure_prompts_with_current_values(root, monkeypatch):
    before_local = load_local()
    tty(monkeypatch)
    r = ask(str(root), "--reconfigure", input="\n\n\n\n")  # Enter keeps current values (custom preset, templates, 2 intervals)
    assert r.exit_code == 0, r.output
    assert load_repos()[R] == RepoConfig(["fixes/{id}-{slug}"], 30, 20)
    r = ask(str(root), "--reconfigure", input="3\n5\n6\n")
    assert r.exit_code == 0, r.output
    assert load_repos()[R] == RepoConfig(["{type}/{slug}", "features/{id}-{slug}", "fixes/{id}-{slug}"], 5, 6)
    assert load_repos()["github.com/o/other"] == RepoConfig(["{type}/{slug}"], 7, 8)
    assert load_local() == before_local


def test_reconfigure_custom_default_is_current_and_reasks(root, monkeypatch):
    tty(monkeypatch)
    r = ask(str(root), "--reconfigure", input="4\nfoo/{bad}\nrel/{id}\n\n\n")
    assert r.exit_code == 0, r.output
    assert "unknown placeholder" in r.output
    assert load_repos()[R].branch_patterns == ["rel/{id}"]
    r = ask(str(root), "--reconfigure", input="4\n\n\n\n")  # custom default = current templates
    assert r.exit_code == 0, r.output
    assert load_repos()[R].branch_patterns == ["rel/{id}"]


def test_reconfigure_no_tty_with_options(root, monkeypatch):
    tty(monkeypatch, False)
    r = ask(str(root), "--reconfigure", "--platform-interval", "3", "-p", "rel/{id}")
    assert r.exit_code == 0, r.output
    assert load_repos()[R] == RepoConfig(["rel/{id}"], 30, 3)
    assert load_repos()["github.com/o/other"] == RepoConfig(["{type}/{slug}"], 7, 8)


def test_reconfigure_no_tty_without_options_fails(root, monkeypatch):
    tty(monkeypatch, False)
    assert ask(str(root), "--reconfigure").exit_code == 1
    assert load_repos()[R] == RepoConfig(["fixes/{id}-{slug}"], 30, 20)


def test_reconfigure_rejects_invalid_pattern_and_unregistered(root, make_repo, monkeypatch):
    tty(monkeypatch, False)
    r = ask(str(root), "--reconfigure", "-p", "x/{nope}")
    assert r.exit_code == 1 and "unknown placeholder" in r.output
    assert load_repos()[R].branch_patterns == ["fixes/{id}-{slug}"]
    r = ask(str(make_repo("r9", remote="https://github.com/o/r9")), "--reconfigure", "--fetch-interval", "5")
    assert r.exit_code == 1 and "not registered" in r.output
    assert "github.com/o/r9" not in load_repos()


def test_setup_platform_interval_option(make_repo):
    assert ask(str(make_repo()), "--platform-interval", "4").exit_code == 0
    assert load_repos()[R].platform_interval == 4


def test_repo_settings_functions():
    assert validate_patterns([" a/{id} ", ""]) == ["a/{id}"]
    for bad in ([], [" "], ["{x}"]):
        with pytest.raises(ValueError):
            validate_patterns(bad)
    assert preset_key(PRESETS["2"]) == "2" and preset_key(["z"]) is None
    save_repos({"u": RepoConfig()})
    assert update_repo("u", fetch_interval=2).fetch_interval == 2
    with pytest.raises(ValueError):
        update_repo("u", platform_interval=0)
    with pytest.raises(ValueError):
        update_repo("missing")


def test_config_command(make_repo, cfg_dir):
    r = CliRunner().invoke(app, ["config"])
    assert r.exit_code == 0 and str(cfg_dir) in r.output and r.output.count("(missing)") == 2
    assert ask(str(make_repo())).exit_code == 0
    out = CliRunner().invoke(app, ["config"]).output
    assert "(missing)" not in out and R in out and "[repos]" in out
    assert CliRunner().invoke(app, ["config", "--path"]).output.strip() == str(cfg_dir)
