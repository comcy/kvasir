from typer.testing import CliRunner

from kvasir.cli import app
from kvasir.config import RepoConfig, load_local, load_repos, save_repos


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
