"""Platform from a remote URL, and branch -> work item id."""
from __future__ import annotations

import re

from kvasir.branch_names import compile_pattern
from kvasir.platform.models import PlatformRepo, PullRequest
from kvasir.repo_url import normalize


def detect_platform(remote_url: str) -> PlatformRepo | None:
    """`git@github.com:o/r.git` / `https://github.com/o/r` -> GitHub `o/r`; other hosts -> None.
    Azure DevOps detection joins here with #26."""
    try:
        host, _, path = normalize(remote_url).partition("/")
    except ValueError:
        return None
    parts = path.split("/")
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
