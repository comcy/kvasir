"""Clone a remote into the bare layout: <root>/.bare + <root>/.git file + one worktree."""
import shutil
import subprocess
from pathlib import Path


def _git(cwd: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=False)
    if r.returncode != 0:
        raise ValueError(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout.strip()


def default_target(url: str) -> Path:
    name = url.strip().rstrip("/").removesuffix(".git").replace("\\", "/").rsplit("/", 1)[-1].rsplit(":", 1)[-1]
    if not name:
        raise ValueError(f"cannot derive repo name from {url!r}")
    return Path.cwd() / name


def clone_bare(url: str, target: Path | None = None) -> Path:
    """Returns the project root. Raises ValueError; leaves no partial directory behind."""
    root = (target or default_target(url)).resolve()
    if root.exists():
        raise ValueError(f"target already exists: {root}")
    root.mkdir(parents=True)
    try:
        bare = root / ".bare"
        _git(root, "clone", "--bare", "--", url, ".bare")
        (root / ".git").write_text("gitdir: ./.bare\n", encoding="utf-8")
        # `clone --bare` sets no fetch refspec; without it origin/* branches stay invisible.
        _git(root, "config", "remote.origin.fetch", "+refs/heads/*:refs/remotes/origin/*")
        _git(root, "fetch", "origin")
        branch = _git(bare, "symbolic-ref", "--short", "HEAD")
        _git(root, "worktree", "add", branch, branch)
        _git(root, "branch", f"--set-upstream-to=origin/{branch}", branch)
    except (ValueError, OSError):
        shutil.rmtree(root, ignore_errors=True)
        raise
    return root
