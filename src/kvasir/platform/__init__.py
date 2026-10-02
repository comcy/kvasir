"""Read-only platform information (GitHub via `gh`, Azure DevOps via `az`) for the Branches of a Repo."""
from kvasir.platform.az import Azure
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
    return Azure.for_repo(repo) if repo.kind == "azure" else GitHub(repo.slug)


__all__ = ["Azure", "Error", "ErrorKind", "GitHub", "PipelineRun", "PlatformRepo", "Provider", "PullRequest",
           "Result", "WorkItem", "detect_platform", "provider_for", "work_item_for"]
