"""GitHub via the installed, logged-in `gh` CLI (read-only; kvasir stores no token).

Field lists were checked against gh 2.101 (see tests/fixtures/gh/). Blocking: run in a worker.
"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime, timedelta

from kvasir.platform.models import (
    Error,
    ErrorKind,
    PipelineRun,
    PullRequest,
    Result,
    WorkItem,
)

TIMEOUT = 30  # seconds
_ENV = {**os.environ, "GH_PROMPT_DISABLED": "1", "NO_COLOR": "1"}

PR_FIELDS = ("number,title,state,isDraft,reviewDecision,statusCheckRollup,url,author,headRefName,"
             "closingIssuesReferences")
SEARCH_FIELDS = "number,title,state,isDraft,url,repository,author"  # no checks/reviews/branch in search
ISSUE_FIELDS = "number,title,state,labels,assignees,url"
ISSUE_BOARD_FIELDS = ISSUE_FIELDS + ",projectItems"  # needs read:project when the issue is on a board
RUN_FIELDS = "workflowName,headBranch,status,conclusion,startedAt,updatedAt,url"

_NETWORK = ("proxyconnect", "dial tcp", "no such host", "i/o timeout", "connection refused",
            "connection reset", "error connecting to", "tls handshake", "network is unreachable")


def classify(code: int, stderr: str) -> Error:
    """Map a failed call to an error kind (exit code 4 = needs auth)."""
    low = stderr.lower()
    if "rate limit" in low:
        kind = ErrorKind.RATE_LIMIT
    elif "required scopes" in low or "read:project" in low or "missing required scope" in low:
        kind = ErrorKind.MISSING_SCOPE
    elif code == 4 or "gh auth login" in low or "not logged in" in low:
        kind = ErrorKind.NOT_LOGGED_IN
    elif any(s in low for s in _NETWORK):
        kind = ErrorKind.NETWORK
    else:
        kind = ErrorKind.OTHER
    return Error(kind, stderr.strip() or f"gh exited with {code}")


def run_gh(*args: str, timeout: int = TIMEOUT) -> Result[str]:
    """Run `gh <args>`; stdout text or an Error. Never raises, never prompts."""
    try:
        r = subprocess.run(["gh", *args], capture_output=True, check=False, env=_ENV, timeout=timeout,
                           stdin=subprocess.DEVNULL)
    except FileNotFoundError:
        return Result(error=Error(ErrorKind.MISSING_CLI, "gh not found"))
    except subprocess.TimeoutExpired:
        return Result(error=Error(ErrorKind.NETWORK, f"gh timed out after {timeout}s"))
    except OSError as e:
        return Result(error=Error(ErrorKind.OTHER, str(e)))
    if r.returncode:
        return Result(error=classify(r.returncode, r.stderr.decode(errors="replace")))
    return Result(data=r.stdout.decode(errors="replace"))


def _json(*args: str) -> Result:
    res = run_gh(*args)
    if not res.ok:
        return res
    try:
        return Result(data=json.loads(res.data))
    except ValueError as e:
        return Result(error=Error(ErrorKind.OTHER, f"unparsable gh output: {e}"))


def _checks(rollup: list[dict] | None) -> str | None:
    """CheckRun (status/conclusion) and StatusContext (state) entries -> success|failure|pending|None."""
    states = []
    for c in rollup or []:
        if "state" in c:  # StatusContext
            s = c["state"]
            states.append("pending" if s in ("PENDING", "EXPECTED")
                          else "failure" if s in ("FAILURE", "ERROR") else "success")
        elif c.get("status") != "COMPLETED":
            states.append("pending")
        else:
            ok = c.get("conclusion") in ("SUCCESS", "NEUTRAL", "SKIPPED")
            states.append("success" if ok else "failure")
    if not states:
        return None
    return "failure" if "failure" in states else "pending" if "pending" in states else "success"


def parse_pr(d: dict) -> PullRequest:
    state = d["state"].lower()
    if state == "open" and d.get("isDraft"):
        state = "draft"
    return PullRequest(
        number=d["number"], title=d["title"], state=state, url=d["url"],
        author=(d.get("author") or {}).get("login", ""),
        branch=d.get("headRefName"),
        review=(d.get("reviewDecision") or "").lower() or None,
        checks=_checks(d.get("statusCheckRollup")),
        closing_issues=tuple(i["number"] for i in d.get("closingIssuesReferences") or ()),
        repo=(d.get("repository") or {}).get("nameWithOwner"),
    )


def parse_work_item(d: dict, board_available: bool = True) -> WorkItem:
    items = d.get("projectItems") or []
    status = ((items[0].get("status") or {}).get("name") or None) if items else None
    return WorkItem(
        number=d["number"], title=d["title"], state=d["state"].lower(), url=d["url"],
        labels=tuple(label["name"] for label in d.get("labels") or ()),
        assignees=tuple(a["login"] for a in d.get("assignees") or ()),
        board_status=status, board_available=board_available,
    )


def parse_run(d: dict) -> PipelineRun:
    dur = None
    try:
        dur = int((datetime.fromisoformat(d["updatedAt"]) - datetime.fromisoformat(d["startedAt"])).total_seconds())
    except (KeyError, TypeError, ValueError):
        pass
    return PipelineRun(
        workflow=d["workflowName"], branch=d["headBranch"], status=d["status"].lower(),
        conclusion=(d.get("conclusion") or "").lower() or None, url=d["url"],
        started_at=d.get("startedAt"), duration_s=dur,
    )


def _parsed(res: Result, fn) -> Result:
    if not res.ok:
        return res
    try:
        return Result(data=[fn(x) for x in res.data])
    except (KeyError, TypeError, AttributeError) as e:
        return Result(error=Error(ErrorKind.OTHER, f"unexpected gh output: {e!r}"))


class GitHub:
    def __init__(self, slug: str):
        self.slug = slug

    def pull_requests(self, limit: int = 30) -> Result[list[PullRequest]]:
        """Open + recently merged/closed PRs (newest first, at most `limit`)."""
        return _parsed(_json("pr", "list", "-R", self.slug, "--state", "all", "--limit", str(limit),
                             "--json", PR_FIELDS), parse_pr)

    def work_item(self, number: int) -> Result[WorkItem]:
        """Issue incl. board status. Without read:project: still the issue, board_available=False."""
        base = ("issue", "view", str(number), "-R", self.slug, "--json")
        res = _json(*base, ISSUE_BOARD_FIELDS)
        board = True
        if not res.ok and res.error.kind is ErrorKind.MISSING_SCOPE:
            res, board = _json(*base, ISSUE_FIELDS), False
        if not res.ok:
            return res
        try:
            return Result(data=parse_work_item(res.data, board))
        except (KeyError, TypeError, AttributeError) as e:
            return Result(error=Error(ErrorKind.OTHER, f"unexpected gh output: {e!r}"))

    def login(self) -> Result[str]:
        res = run_gh("api", "user", "--jq", ".login")
        return Result(data=res.data.strip()) if res.ok else res

    def pipeline_runs(self, days: int = 7, limit: int = 20) -> Result[list[PipelineRun]]:
        """My workflow runs of the last `days` days."""
        who = self.login()
        if not who.ok:
            return who
        since = (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%d")
        return _parsed(_json("run", "list", "-R", self.slug, "--user", who.data, "--created", f">={since}",
                             "--limit", str(limit), "--json", RUN_FIELDS), parse_run)

    def _search(self, flag: str, limit: int) -> Result[list[PullRequest]]:
        return _parsed(_json("search", "prs", flag, "@me", "--state", "open", "--limit", str(limit),
                             "--json", SEARCH_FIELDS), parse_pr)

    def my_pull_requests(self, limit: int = 30) -> Result[list[PullRequest]]:
        """My open PRs across all repos (not limited to self.slug)."""
        return self._search("--author", limit)

    def review_requests(self, limit: int = 30) -> Result[list[PullRequest]]:
        """Open PRs awaiting my review, across all repos."""
        return self._search("--review-requested", limit)
