"""Platform data model + result type + the small provider interface. No Textual, no I/O."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Generic, Protocol, TypeVar

T = TypeVar("T")


class ErrorKind(Enum):
    MISSING_CLI = "cli_missing"  # gh / az not installed
    MISSING_EXTENSION = "extension_missing"  # az without the azure-devops extension
    NOT_LOGGED_IN = "not_logged_in"
    MISSING_SCOPE = "missing_scope"  # token lacks a permission, e.g. read:project
    NETWORK = "network"  # incl. timeout
    RATE_LIMIT = "rate_limit"
    OTHER = "other"


@dataclass(frozen=True)
class Error:
    kind: ErrorKind
    message: str = ""
    cli: str = "gh"  # which CLI failed: "gh" | "az" (picks the hint text)


@dataclass(frozen=True)
class Result(Generic[T]):
    """Data OR error. Provider calls return this and never raise."""
    data: T | None = None
    error: Error | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass(frozen=True)
class PlatformRepo:
    kind: str  # "github" | "azure"
    slug: str  # github: "owner/repo"; azure: "org/project/repo" (lowercase)
    org: str = ""  # azure only (empty for github)
    project: str = ""  # azure only
    repo: str = ""  # azure only


@dataclass(frozen=True)
class PullRequest:
    number: int
    title: str
    state: str  # open | draft | merged | closed
    url: str
    author: str
    branch: str | None = None  # None in cross-repo search results
    review: str | None = None  # approved | changes_requested | review_required | None
    checks: str | None = None  # success | failure | pending | None (no checks)
    closing_issues: tuple[int, ...] = ()
    repo: str | None = None  # "owner/repo", set by cross-repo search
    created_at: str | None = None  # ISO 8601
    body: str | None = None  # PR description (checklist for the stepper)


@dataclass(frozen=True)
class WorkItem:
    number: int
    title: str
    state: str  # open | closed
    url: str
    labels: tuple[str, ...] = ()
    assignees: tuple[str, ...] = ()
    board_status: str | None = None  # GitHub Projects v2 status, e.g. "In Progress"
    board_available: bool = True  # False: read:project missing -> "Board-Status nicht verfügbar"


@dataclass(frozen=True)
class PipelineRun:
    workflow: str
    branch: str
    status: str  # queued | in_progress | completed
    conclusion: str | None  # success | failure | cancelled | ... (None while running)
    url: str
    started_at: str | None = None  # ISO 8601
    duration_s: int | None = None
    repo: str | None = None  # "owner/repo", set by the overview (#29)


@dataclass(frozen=True)
class Deadline:
    date: date
    label: str  # Meilensteinname (z. B. "Sprint 12") oder die Zeile ("Frist: Ende Q4 2026")


@dataclass(frozen=True)
class Schedule:
    """Termine eines Items. `deadlines` aufsteigend, die erste ist die geltende Frist."""
    deadlines: tuple[Deadline, ...] = ()
    planned_from: date | None = None
    planned_to: date | None = None
    notes: tuple[str, ...] = ()  # Hinweise zu nicht lesbaren Zeilen

    @property
    def deadline(self) -> date | None:
        return self.deadlines[0].date if self.deadlines else None


@dataclass(frozen=True)
class Item:
    """A GitHub issue as plain facts (REST shape), also used for a blocker."""
    repo: str  # "owner/repo"
    number: int
    title: str
    state: str  # open | closed
    state_reason: str | None = None  # completed | not_planned | reopened | None
    labels: tuple[str, ...] = ()
    schedule: Schedule = Schedule()
    closed_at: str | None = None  # ISO date
    parent: int | None = None  # number of the parent issue (same repo)
    prio: int | None = None  # 1..4: Label `prio:N` (GitHub) / Feld Priority (Azure); sonst None
    sub_count: int = 0  # Zahl der Sub-Issues (spart den Aufruf bei Blättern)


@dataclass(frozen=True)
class Step:
    name: str
    state: str  # done | current | open


@dataclass(frozen=True)
class Stepper:
    level: str  # feature | ticket
    steps: tuple[Step, ...]
    previous: tuple[int, ...] = ()  # closed blockers


@dataclass(frozen=True)
class ItemStatus:
    """Item + its relations + status derived from facts. Status: done | dropped | blocked | in_review |
    in_progress | open; a `status:*` label only fills in where no fact exists (source "label")."""
    item: Item
    blocked_by: tuple[Item, ...]
    status: str
    source: str  # fact | label
    reason: str | None = None  # why the fact status holds, e.g. "PR #7 ist Draft"
    hint: str | None = None  # a status:* label that contradicts the fact status
    notices: tuple[str, ...] = ()  # Termin-Hinweise (unlesbare Zeile, Konflikte); keine Bewertung
    stepper: Stepper | None = None
    children: tuple[int, ...] = ()  # Nummern der Sub-Issues im gezeigten Satz
    succ: tuple[int, ...] = ()  # was dieses Item blockiert, nur im gezeigten Satz


@dataclass(frozen=True)
class IssueStatus:
    repo: str
    issue: ItemStatus
    sub_issues: tuple[ItemStatus, ...]  # alle Nachkommen, Tiefensuche in API-Reihenfolge


class Provider(Protocol):
    """What the UI needs from a platform. GitHub (gh) and Azure DevOps (az)."""

    def pull_requests(self, limit: int = 30) -> Result[list[PullRequest]]: ...
    def work_item(self, number: int) -> Result[WorkItem]: ...
    def pipeline_runs(self, days: int = 7, limit: int = 20) -> Result[list[PipelineRun]]: ...
    def pull_request(self, number: int) -> Result[PullRequest]: ...
    def my_pull_requests(self, limit: int = 30) -> Result[list[PullRequest]]: ...
    def review_requests(self, limit: int = 30) -> Result[list[PullRequest]]: ...
