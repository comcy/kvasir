"""Platform from a remote URL, and branch -> work item id."""
from __future__ import annotations

import re

from kvasir.branch_names import compile_pattern
from kvasir.platform.models import PlatformRepo, PullRequest
from kvasir.repo_url import normalize


def detect_platform(remote_url: str) -> PlatformRepo | None:
    """`git@github.com:o/r.git` / `https://github.com/o/r` -> GitHub `o/r`; any Azure DevOps form (or the bare
    key `dev.azure.com/org/project/_git/repo` behind a `https://`) -> Azure; other hosts -> None."""
    try:
        host, _, path = normalize(remote_url).partition("/")
    except ValueError:
        return None
    parts = path.split("/")
    if host == "dev.azure.com" and len(parts) == 4 and parts[2] == "_git" and all(parts):
        org, project, repo = parts[0], parts[1], parts[3]
        return PlatformRepo("azure", f"{org}/{project}/{repo}", org, project, repo)
    if host == "github.com" and len(parts) == 2 and all(parts):
        return PlatformRepo("github", path)
    return None


def work_item_for(branch: str, patterns: list[str], prs: list[PullRequest]) -> int | None:
    """Work item number of a branch: numeric `{id}` from a matching Branch-Vorlage, else the first
    issue the branch's PR closes."""
    for p in patterns:
        if "{id}" not in p:
            continue
        try:
            m = compile_pattern(p).fullmatch(branch)
        except (ValueError, re.error):  # unknown or duplicate placeholder
            continue
        if m and m["id"].isdigit():
            return int(m["id"])
    for pr in prs:
        if pr.branch == branch and pr.closing_issues:
            return pr.closing_issues[0]
    return None
