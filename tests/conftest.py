import subprocess

import pytest


@pytest.fixture(autouse=True)
def cfg_dir(tmp_path, monkeypatch):
    d = tmp_path / "cfg"
    monkeypatch.setenv("KVASIR_CONFIG_DIR", str(d))
    return d


def sh(cwd, *a):
    subprocess.run(a, cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def make_repo(tmp_path):
    def _make(name="r", bare_layout=False, remote="git@github.com:o/r.git"):
        root = tmp_path / name
        root.mkdir()
        if bare_layout:
            src = tmp_path / f"{name}-src"
            src.mkdir()
            sh(src, "git", "init", "-q", "-b", "main")
            sh(src, "git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "i")
            sh(root, "git", "clone", "-q", "--bare", str(src), ".bare")
            (root / ".git").write_text("gitdir: ./.bare\n")
            sh(root, "git", "remote", "set-url", "origin", remote)
        else:
            sh(root, "git", "init", "-q", "-b", "main")
            sh(root, "git", "remote", "add", "origin", remote)
        return root
    return _make
