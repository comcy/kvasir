"""GitHub via the installed, logged-in `gh` CLI (read-only; kvasir stores no token).

Field lists were checked against gh 2.101 (see tests/fixtures/gh/). Blocking: run in a worker.
"""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from kvasir.platform import schedule
from kvasir.platform.models import (
    Error,
    ErrorKind,
    Item,
    PipelineRun,
    PullRequest,
    Result,
    WorkItem,
)

TIMEOUT = 30  # seconds
_ENV = {**os.environ, "GH_PROMPT_DISABLED": "1", "NO_COLOR": "1"}

PR_FIELDS = ("number,title,state,isDraft,reviewDecision,statusCheckRollup,url,author,headRefName,"
             "closingIssuesReferences,createdAt,body")
SEARCH_FIELDS = "number,title,state,isDraft,url,repository,author,createdAt"  # no checks/reviews/branch in search
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
        created_at=d.get("createdAt"), body=d.get("body"),
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


def parse_item(d: dict) -> Item:
    """REST issue (`gh api repos/o/r/issues/N`, sub_issues, blocked_by entries)."""
    return Item(
        repo=d["repository_url"].split("/repos/", 1)[1], number=d["number"], title=d["title"],
        state=d["state"], state_reason=d.get("state_reason"),
        labels=tuple(label["name"] for label in d.get("labels") or ()),
        schedule=schedule.parse(d.get("body"), d.get("milestone")),
        closed_at=(d.get("closed_at") or "")[:10] or None,
        parent=int(d["parent_issue_url"].rsplit("/", 1)[1]) if d.get("parent_issue_url") else None,
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

    def pull_requests(self, limit: int = 30, state: str = "all") -> Result[list[PullRequest]]:
        """Open + recently merged/closed PRs (newest first, at most `limit`); `state="open"` only open ones."""
        return _parsed(_json("pr", "list", "-R", self.slug, "--state", state, "--limit", str(limit),
                             "--json", PR_FIELDS), parse_pr)

    def pull_request(self, number: int) -> Result[PullRequest]:
        """One PR with review decision, checks and branch (what `gh search prs` lacks)."""
        res = _json("pr", "view", str(number), "-R", self.slug, "--json", PR_FIELDS)
        if not res.ok:
            return res
        try:
            return Result(data=replace(parse_pr(res.data), repo=self.slug))
        except (KeyError, TypeError, AttributeError) as e:
            return Result(error=Error(ErrorKind.OTHER, f"unexpected gh output: {e!r}"))

    def _items(self, path: str):
        return _parsed(_json("api", f"repos/{self.slug}/{path}?per_page=100"), parse_item)

    def item(self, number: int) -> Result[Item]:
        res = _json("api", f"repos/{self.slug}/issues/{number}")
        if not res.ok:
            return res
        try:
            return Result(data=parse_item(res.data))
        except (KeyError, TypeError, AttributeError, IndexError) as e:
            return Result(error=Error(ErrorKind.OTHER, f"unexpected gh output: {e!r}"))

    def timeline(self, number: int) -> Result[list[dict]]:
        """Raw REST timeline of an issue (labeled/closed/... with created_at). # ponytail: first 100 events"""
        return _json("api", f"repos/{self.slug}/issues/{number}/timeline?per_page=100")

    def merged_prs(self, limit: int = 200) -> Result[list[dict]]:
        """Raw merged PRs (number, createdAt, mergedAt, headRefName), newest first. # ponytail: first `limit`"""
        return _json("pr", "list", "-R", self.slug, "--state", "merged", "--limit", str(limit),
                     "--json", "number,title,createdAt,mergedAt,headRefName")

    def runs_since(self, since: str, limit: int = 1000) -> Result[list[dict]]:
        """Raw workflow runs created on/after `since` (YYYY-MM-DD). # ponytail: first `limit`"""
        return _json("run", "list", "-R", self.slug, "--created", f">={since}", "--limit", str(limit),
                     "--json", "conclusion,createdAt,headBranch,event")

    def sub_issues(self, number: int) -> Result[list[Item]]:
        # ponytail: first 100 only, no pagination
        return self._items(f"issues/{number}/sub_issues")

    def blocked_by(self, number: int) -> Result[list[Item]]:
        return self._items(f"issues/{number}/dependencies/blocked_by")

    def issues(self, state: str, milestone: int | None = None) -> Result[list[Item]]:
        """Repo issues (no PRs), newest update first. # ponytail: first 100 per state, no pagination"""
        q = f"state={state}&sort=updated&direction=desc&per_page=100" + (f"&milestone={milestone}" if milestone else "")
        res = _json("api", f"repos/{self.slug}/issues?{q}")
        return _parsed(Result(data=[d for d in res.data if "pull_request" not in d]) if res.ok else res, parse_item)

    def milestone_number(self, title: str) -> Result[int | None]:
        res = _json("api", f"repos/{self.slug}/milestones?state=all&per_page=100")
        if not res.ok:
            return res
        return Result(data=next((m["number"] for m in res.data if m.get("title") == title), None))

    def branch_names(self) -> Result[list[str]]:
        # ponytail: --paginate prints one name per line; fine for a few hundred branches
        res = run_gh("api", f"repos/{self.slug}/branches?per_page=100", "--paginate", "--jq", ".[].name")
        return Result(data=res.data.split()) if res.ok else res

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
