"""`kvasir worktree add`: flags + optional terminal prompts. No Textual; prompts and messages go to stderr."""
from __future__ import annotations

import sys
from pathlib import Path

import typer

from kvasir.branch_names import TYPES, auto_name, matches, suggest
from kvasir.config import RepoConfig, load_local, load_repos
from kvasir.new_worktree import (
    NewWorktreeError,
    _git,
    _ref_exists,
    add_worktree,
    add_worktree_moving_changes,
    base_hint,
    default_branch,
    repo_root,
)
from kvasir.repo_file import effective_patterns
from kvasir.scratch import is_scratch
from kvasir.worktrees import Worktree, read_repo


def _is_tty() -> bool:
    return sys.stdin.isatty()


def _say(msg: str = "") -> None:
    typer.echo(msg, err=True)


def _ask(text: str, default: str | None = None) -> str:
    return typer.prompt(text, default=default, err=True).strip()


def _pick(title: str, options: list[str], default: str) -> str:
    """Numbered choice (number or free text); Enter = default."""
    for i, o in enumerate(options, 1):
        _say(f"  {i}) {o}")
    ans = _ask(title, default)
    return options[int(ans) - 1] if ans.isdigit() and 0 < int(ans) <= len(options) else ans


def _patterns(root: Path) -> list[str]:
    url = next((u for u, p in load_local().paths.items() if Path(p).resolve() == root.resolve()), None)
    cfg = load_repos().get(url) if url else None
    return effective_patterns(cfg or RepoConfig(patterns_set=False), root)


def _source(path: Path, worktrees: list[Worktree]) -> Worktree | None:
    """The Worktree the user stands in (not scratch, not broken); None at the repo root."""
    r = _git(path, "rev-parse", "--show-toplevel")
    if r.returncode != 0:
        return None
    top = Path(r.stdout.strip()).resolve()
    return next((w for w in worktrees if w.path.resolve() == top and not is_scratch(w.path) and not w.broken), None)


def _fail(msg: str) -> typer.Exit:
    _say(f"error: {msg}")
    return typer.Exit(1)


def run(branch: str | None, from_: str | None, move: bool | None, force_name: bool, repo: Path, interactive: bool) -> Path:
    """Path of the new Worktree. typer.Exit(1) on any failure or abort (message on stderr)."""
    if interactive and not _is_tty():
        raise _fail("--interactive needs a terminal (stdin is not a TTY)")
    try:
        root = repo_root(repo)
        view = read_repo(root)
        source = _source(repo, view.worktrees)
        n = source.staged + source.unstaged + source.untracked if source else 0
        return _create(root, [b.name for b in view.branches], _patterns(root), source if n else None, n,
                       branch, from_, move, force_name, interactive)
    except typer.Exit:  # already reported by _fail (click's Exit is a RuntimeError: don't report it twice)
        raise
    except (typer.Abort, EOFError) as e:
        _say("aborted, nothing created")
        raise typer.Exit(1) from e
    except (NewWorktreeError, ValueError, RuntimeError) as e:
        raise _fail(str(e)) from e


def _create(root: Path, names: list[str], patterns: list[str], source: Worktree | None, n: int,
            branch: str | None, from_: str | None, move: bool | None, force_name: bool, interactive: bool) -> Path:
    if interactive and branch is None:
        pick = "new"
        if names:
            _say("Existing branches without worktree:")
            pick = _pick("Branch (number or name, 'new' = new branch)", names, "new")
        branch = None if pick == "new" else pick
    if branch is None and not interactive:
        raise _fail("branch name required (or use --interactive)")
    base: str | None = None
    if branch is not None and from_ is None and not _ref_exists(root, f"refs/heads/{branch}") \
            and not _ref_exists(root, f"refs/remotes/{branch}") and _ref_exists(root, f"refs/remotes/origin/{branch}"):
        branch = f"origin/{branch}"  # remote-only: local tracking branch
    existing = branch is not None and from_ is None and (
        _ref_exists(root, f"refs/heads/{branch}") or _ref_exists(root, f"refs/remotes/{branch}"))
    if not existing:
        if branch is None:  # interactive, new branch
            proposal = None
            if patterns:
                tpl = _pick("Template", patterns, patterns[0]) if len(patterns) > 1 else patterns[0]
                proposal = auto_name(tpl, _ask("Type", TYPES[0]), _ask("ID", ""), _ask("Title", ""))
            branch = _ask("Name (also the worktree folder)", proposal)
        base = from_ or (_ask("From", default_branch(root)) if interactive else default_branch(root))
        if not matches(branch, patterns) and not force_name:
            hint = suggest(branch, patterns)
            msg = f"name {branch!r} violates templates {patterns}" + (f"; suggestion: {hint}" if hint else "")
            if not interactive:
                raise _fail(msg + " (--force-name to create anyway)")
            _say(f"warning: {msg}")
            if not typer.confirm("Create anyway?", default=False, err=True):
                raise typer.Abort
    if source and move is None:
        if interactive:
            move = typer.confirm(f"Move {n} uncommitted changes from {source.path.name}?", default=True, err=True)
        else:
            _say(f"note: {n} uncommitted changes in {source.path.name} left untouched (--move-changes to move them)")
    move = bool(move and source)
    if interactive:
        folder = branch.partition("/")[2] if existing and _ref_exists(root, f"refs/remotes/{branch}") else branch
        _say(f"Create worktree {root / folder}")
        _say(f"  base: {base_hint(root, base) if base else '(existing branch)'}")
        _say(f"  move changes: {'yes' if move else 'no'}")
        if not typer.confirm("Proceed?", default=True, err=True):
            raise typer.Abort
    if move and source:
        return add_worktree_moving_changes(root, branch, base, source.path)
    return add_worktree(root, branch, base)
