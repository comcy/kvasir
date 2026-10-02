"""Read-only platform information (GitHub via `gh`) for the Branches of a Repo."""
from kvasir.platform.detect import detect_platform, work_item_for
from kvasir.platform.gh import GitHub
from kvasir.platform.models import (
    Error,
    ErrorKind,
    PipelineRun,
    PlatformRepo,
    Provider,
    PullRequest,
    Result,
    WorkItem,
)


def provider_for(repo: PlatformRepo) -> Provider:
    return GitHub(repo.slug)  # only GitHub so far; Azure DevOps (#26) adds a branch on repo.kind


__all__ = ["Error", "ErrorKind", "GitHub", "PipelineRun", "PlatformRepo", "Provider", "PullRequest",
           "Result", "WorkItem", "detect_platform", "provider_for", "work_item_for"]
