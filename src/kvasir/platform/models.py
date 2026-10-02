"""Platform data model + result type + the small provider interface. No Textual, no I/O."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Generic, Protocol, TypeVar

T = TypeVar("T")


class ErrorKind(Enum):
    MISSING_CLI = "cli_missing"  # gh not installed
    NOT_LOGGED_IN = "not_logged_in"
    MISSING_SCOPE = "missing_scope"  # token lacks a permission, e.g. read:project
    NETWORK = "network"  # incl. timeout
    RATE_LIMIT = "rate_limit"
    OTHER = "other"


@dataclass(frozen=True)
class Error:
    kind: ErrorKind
    message: str = ""


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


class Provider(Protocol):
    """What the UI needs from a platform. GitHub now, Azure DevOps (#26) later."""

    def pull_requests(self, limit: int = 30) -> Result[list[PullRequest]]: ...
    def work_item(self, number: int) -> Result[WorkItem]: ...
    def pipeline_runs(self, days: int = 7, limit: int = 20) -> Result[list[PipelineRun]]: ...
    def pull_request(self, number: int) -> Result[PullRequest]: ...
    def my_pull_requests(self, limit: int = 30) -> Result[list[PullRequest]]: ...
    def review_requests(self, limit: int = 30) -> Result[list[PullRequest]]: ...
