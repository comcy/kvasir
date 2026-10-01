"""Facts about a git repo, read via the git CLI."""
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class RepoInfo:
    root: Path        # project root: dir holding `.bare`, or the checkout for a normal clone
    bare_layout: bool
    remote_url: str | None


def _git(cwd: Path, *args: str) -> str | None:
    r = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=False)
    return r.stdout.strip() if r.returncode == 0 else None


def repo_info(cwd: Path) -> RepoInfo:
    """Raises ValueError outside a git repo."""
    common = _git(cwd, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if common is None:
        raise ValueError(f"not a git repository: {cwd}")
    common_dir = Path(common)
    bare = _git(common_dir, "rev-parse", "--is-bare-repository") == "true"
    if bare:
        # Layout: <root>/.bare + <root>/.git file. A plain `foo.git` bare repo is its own root.
        root = common_dir.parent if common_dir.name == ".bare" else common_dir
    else:
        root = Path(_git(cwd, "rev-parse", "--show-toplevel") or common_dir.parent)
    return RepoInfo(root=root, bare_layout=bare, remote_url=_git(cwd, "config", "--get", "remote.origin.url"))
