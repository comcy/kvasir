import subprocess

from typer.testing import CliRunner

from kvasir.cli import app
from kvasir.config import RepoConfig, load_local, load_repos, save_repos


def sh(cwd, *a):
    subprocess.run(a, cwd=cwd, check=True, capture_output=True)


def make_remote(tmp_path, name="up"):
    src = tmp_path / name
    src.mkdir()
    sh(src, "git", "init", "-q", "-b", "main")
    sh(src, "git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "i")
    sh(src, "git", "branch", "feat/x")
    return src


def setup(*args):
    return CliRunner().invoke(app, ["setup", *args])


def test_clone_url_default_target(tmp_path, monkeypatch):
    src = make_remote(tmp_path)
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    r = setup(src.as_uri())
    assert r.exit_code == 0, r.output
    root = (work / "up").resolve()
    assert (root / ".bare").is_dir()
    assert (root / ".git").read_text() == "gitdir: ./.bare\n"
    assert (root / "main" / ".git").exists()
    refs = subprocess.run(["git", "-C", str(root), "branch", "-r"], capture_output=True, text=True, check=True).stdout
    assert "origin/feat/x" in refs
    key = "/" + str(src).lstrip("/")  # file:// URLs normalize to the bare path
    assert load_repos()[key] == RepoConfig()
    assert load_local().paths[key] == str(root)
    assert "bare layout" in r.stdout


def test_clone_explicit_target_keeps_existing_entry(tmp_path):
    src = make_remote(tmp_path)
    key = "/" + str(src).lstrip("/")
    save_repos({key: RepoConfig(["fixes/{id}-{slug}"], 30)})
    dest = tmp_path / "a" / "b"
    assert setup(src.as_uri(), str(dest)).exit_code == 0
    assert (dest / "main").is_dir()
    assert load_repos()[key] == RepoConfig(["fixes/{id}-{slug}"], 30)


def test_existing_target_fails(tmp_path):
    src = make_remote(tmp_path)
    dest = tmp_path / "t"
    dest.mkdir()
    (dest / "keep").write_text("x")
    r = setup(src.as_uri(), str(dest))
    assert r.exit_code == 1 and "already exists" in r.output
    assert (dest / "keep").exists()


def test_failed_clone_leaves_nothing(tmp_path):
    dest = tmp_path / "t"
    r = setup((tmp_path / "missing").as_uri(), str(dest))
    assert r.exit_code == 1 and "failed" in r.output
    assert not dest.exists()
