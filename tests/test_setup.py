from typer.testing import CliRunner

from kvasir.cli import app
from kvasir.config import (
    LocalConfig,
    RepoConfig,
    default_open_command,
    load_local,
    load_repos,
    save_local,
    save_repos,
)


def run(*args):
    return CliRunner().invoke(app, ["setup", *args])


def test_register_bare_layout(make_repo):
    root = make_repo(bare_layout=True)
    r = run(str(root))
    assert r.exit_code == 0, r.output
    assert load_repos()["github.com/o/r"] == RepoConfig()
    assert load_local().paths["github.com/o/r"] == str(root)
    assert "bare layout" in r.stdout


def test_register_normal_clone_with_options(make_repo):
    root = make_repo()
    r = run(str(root), "-p", "features/{id}-{slug}", "-p", "{type}/{slug}", "--fetch-interval", "5")
    assert r.exit_code == 0, r.output
    c = load_repos()["github.com/o/r"]
    assert c.branch_patterns == ["features/{id}-{slug}", "{type}/{slug}"] and c.fetch_interval == 5
    assert "overview only" in r.stdout


def test_existing_entry_kept_on_new_machine(make_repo):
    save_repos({"github.com/o/r": RepoConfig(["fixes/{id}-{slug}"], 30)})
    root = make_repo(remote="https://github.com/o/r")
    assert run(str(root)).exit_code == 0
    assert load_repos()["github.com/o/r"] == RepoConfig(["fixes/{id}-{slug}"], 30)
    assert load_local().paths["github.com/o/r"] == str(root)


def test_no_remote_fails(tmp_path):
    import subprocess
    subprocess.run(["git", "init", "-q", str(tmp_path / "x")], check=True)
    assert run(str(tmp_path / "x")).exit_code == 1


def test_not_a_repo(tmp_path):
    assert run(str(tmp_path)).exit_code == 1


def interactive(monkeypatch, on=True):
    monkeypatch.setattr("kvasir.cli._interactive", lambda: on)


def ask(*args, input):
    return CliRunner().invoke(app, ["setup", *args], input=input)


def test_prompt_preset_both(make_repo, monkeypatch):
    interactive(monkeypatch)
    r = ask(str(make_repo()), input="3\n10\nmycmd {path}\n")
    assert r.exit_code == 0, r.output
    c = load_repos()["github.com/o/r"]
    assert c.branch_patterns == ["{type}/{slug}", "features/{id}-{slug}", "fixes/{id}-{slug}"]
    assert c.fetch_interval == 10
    assert load_local().open_command == "mycmd {path}"


def test_prompt_defaults(make_repo, monkeypatch):
    interactive(monkeypatch)
    r = ask(str(make_repo()), input="\n\n\n")
    assert r.exit_code == 0, r.output
    assert load_repos()["github.com/o/r"] == RepoConfig()
    assert load_local().open_command == default_open_command()


def test_prompt_custom_reasks_on_bad_placeholder(make_repo, monkeypatch):
    interactive(monkeypatch)
    r = ask(str(make_repo()), input="4\nfoo/{bad}\nrel/{id}, hotfix/{slug}\n\n\n")
    assert r.exit_code == 0, r.output
    assert "unknown placeholder" in r.output
    assert load_repos()["github.com/o/r"].branch_patterns == ["rel/{id}", "hotfix/{slug}"]


def test_open_command_not_asked_when_set(make_repo, monkeypatch):
    interactive(monkeypatch)
    save_local(LocalConfig(open_command="x {path}"))
    r = ask(str(make_repo()), input="2\n\n")
    assert r.exit_code == 0, r.output
    assert load_local().open_command == "x {path}"
    assert load_repos()["github.com/o/r"].branch_patterns == ["features/{id}-{slug}", "fixes/{id}-{slug}"]


def test_no_prompts_for_known_entry_or_options_or_no_tty(make_repo, monkeypatch):
    save_repos({"github.com/o/r": RepoConfig(["fixes/{id}-{slug}"], 30)})
    interactive(monkeypatch)
    assert ask(str(make_repo(remote="https://github.com/o/r")), input="").exit_code == 0  # would abort if prompted
    assert load_repos()["github.com/o/r"] == RepoConfig(["fixes/{id}-{slug}"], 30)
    r2 = make_repo("r2", remote="https://github.com/o/r2")
    assert ask(str(r2), "--fetch-interval", "5", input="").exit_code == 0
    assert load_repos()["github.com/o/r2"].fetch_interval == 5
    interactive(monkeypatch, False)
    r3 = make_repo("r3", remote="https://github.com/o/r3")
    assert ask(str(r3), input="").exit_code == 0
    assert load_repos()["github.com/o/r3"] == RepoConfig()
    assert load_local().open_command is None
