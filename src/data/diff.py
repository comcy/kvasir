"""Git diff parsing for the diff viewer (TUI `DiffScreen` + `mimirlink wt
diff`/`wt compare`). Wraps `git diff` text through `unidiff` for structured
hunk access, and renders a parsed file as colorized Rich text shared by
both the CLI and TUI — Rich is fine here (every CLI module already uses it
for output), the boundary this codebase keeps is "no Textual in data/"."""
from __future__ import annotations

import subprocess
from pathlib import Path

from rich.text import Text
from unidiff import PatchedFile, PatchSet


def _git(args: list[str], cwd: Path | str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=str(cwd), stderr=subprocess.DEVNULL
    ).decode().strip()


def _parse(text: str) -> PatchSet:
    try:
        return PatchSet(text)
    except Exception:
        return PatchSet("")


def working_diff(worktree_dir: Path | str) -> PatchSet:
    """Staged + unstaged changes combined — everything since the last commit."""
    try:
        text = _git(["diff", "HEAD"], worktree_dir)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return PatchSet("")
    return _parse(text)


def staged_diff(worktree_dir: Path | str) -> PatchSet:
    """Only what's staged for the next commit."""
    try:
        text = _git(["diff", "--staged"], worktree_dir)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return PatchSet("")
    return _parse(text)


def branch_diff(worktree_dir: Path | str, base: str, target: str) -> PatchSet:
    """PR-style diff: what *target* introduced since it diverged from *base*
    (triple-dot / merge-base diff — the same semantics GitHub/GitLab use for
    pull-request diffs, not a plain tip-to-tip comparison)."""
    try:
        text = _git(["diff", f"{base}...{target}"], worktree_dir)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return PatchSet("")
    return _parse(text)


def list_branches(worktree_dir: Path | str) -> list[str]:
    """Local branch names."""
    try:
        out = _git(["branch", "--format=%(refname:short)"], worktree_dir)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    return [line.strip() for line in out.splitlines() if line.strip()]


def current_branch(worktree_dir: Path | str) -> str:
    try:
        return _git(["rev-parse", "--abbrev-ref", "HEAD"], worktree_dir)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


def default_branch(worktree_dir: Path | str) -> str:
    """The repo's main branch — resolved from `origin/HEAD`, falling back to
    'main' (or 'master' if that's the only local branch matching)."""
    try:
        ref = _git(
            ["symbolic-ref", "--short", "refs/remotes/origin/HEAD"], worktree_dir,
        )
        return ref.removeprefix("origin/")
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    branches = list_branches(worktree_dir)
    if "main" in branches:
        return "main"
    if "master" in branches:
        return "master"
    return branches[0] if branches else "main"


def render_patched_file(patched_file: PatchedFile) -> Text:
    """Colorized Rich rendering of one file's diff: hunk headers bold cyan,
    added lines green, removed lines red, context dim."""
    text = Text()
    for hunk in patched_file:
        header = f"@@ -{hunk.source_start},{hunk.source_length} +{hunk.target_start},{hunk.target_length} @@"
        if hunk.section_header:
            header += f" {hunk.section_header}"
        text.append(header + "\n", style="bold cyan")
        for line in hunk:
            prefix = "+" if line.is_added else "-" if line.is_removed else " "
            style = "green" if line.is_added else "red" if line.is_removed else "dim"
            text.append(f"{prefix} {line.value}", style=style)
    return text


def render_patchset(patchset: PatchSet) -> Text:
    """All files in *patchset*, each preceded by a header line."""
    text = Text()
    for pf in patchset:
        status = "added" if pf.is_added_file else "removed" if pf.is_removed_file else "modified"
        text.append(
            f"\n{pf.path}  ", style="bold",
        )
        text.append(f"({status}, +{pf.added} -{pf.removed})\n", style="dim")
        text.append(render_patched_file(pf))
    return text
