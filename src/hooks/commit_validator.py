"""Conventional Commit parser and validator."""
from __future__ import annotations

import re
from dataclasses import dataclass

TYPES = (
    "feat", "fix", "docs", "style", "refactor",
    "perf", "test", "build", "ci", "chore", "revert",
)

_CC_RE = re.compile(
    r"^(?P<type>" + "|".join(TYPES) + r")"
    r"(?:\((?P<scope>[^)]+)\))?"
    r"(?P<breaking>!)?"
    r": (?P<subject>.+)$",
    re.IGNORECASE,
)


@dataclass
class ParsedCommit:
    type: str
    scope: str | None
    subject: str
    breaking: bool


def parse(first_line: str) -> ParsedCommit | None:
    """Return a ParsedCommit or None if the line is not a valid Conventional Commit."""
    m = _CC_RE.match(first_line.strip())
    if not m:
        return None
    return ParsedCommit(
        type=m.group("type").lower(),
        scope=m.group("scope"),
        subject=m.group("subject").strip(),
        breaking=bool(m.group("breaking")),
    )


def strip_comments(msg: str) -> str:
    """Remove git comment lines (starting with #) from a commit message."""
    return "\n".join(l for l in msg.splitlines() if not l.startswith("#")).strip()
