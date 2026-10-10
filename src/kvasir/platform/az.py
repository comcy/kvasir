"""Azure DevOps via the installed, logged-in `az` CLI with the `azure-devops` extension (read-only; no token).

NOT verified live: command lines and options follow the Microsoft Learn CLI reference (azure-cli 2.x,
azure-devops extension), the JSON shapes follow the Azure DevOps REST API objects that the extension prints
(see tests/fixtures/az/, invented but shape-faithful). Every parser is defensive: a missing field -> None/empty.
Blocking: run in a worker.
"""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

from kvasir.platform import schedule
from kvasir.platform.models import (
    Deadline,
    Error,
    ErrorKind,
    Item,
    PipelineRun,
    PlatformRepo,
    PullRequest,
    Result,
    Schedule,
    WorkItem,
)

TIMEOUT = 60  # seconds; `az` starts slowly
ENRICH = 8  # open PRs of a list that get policy status + linked work items (2 `az` calls each)
_ENV = {**os.environ, "AZURE_CORE_NO_COLOR": "true", "NO_COLOR": "1", "AZURE_CORE_ONLY_SHOW_ERRORS": "true",
        "AZURE_EXTENSION_USE_DYNAMIC_INSTALL": "no", "AZURE_CORE_COLLECT_TELEMETRY": "false"}
_CLOSED = {"closed", "done", "removed", "completed"}

_NETWORK = ("max retries exceeded", "failed to establish", "name or service not known", "getaddrinfo",
            "connection aborted", "connection reset", "timed out", "network is unreachable", "connectionerror")


def classify(code: int, stderr: str) -> Error:
    low = stderr.lower()
    if "misspelled or not recognized" in low or "extension add" in low or "requires the extension" in low:
        kind = ErrorKind.MISSING_EXTENSION  # unknown `repos`/`pipelines`/`boards` group = azure-devops missing
    elif "too many requests" in low or "rate limit" in low or "tf400733" in low or "exceeding usage" in low:
        kind = ErrorKind.RATE_LIMIT
    elif ("az login" in low or "az devops login" in low or "tf400813" in low or "aadsts" in low
          or "not logged in" in low or "authentication" in low):
        kind = ErrorKind.NOT_LOGGED_IN
    elif any(s in low for s in _NETWORK):
        kind = ErrorKind.NETWORK
    else:
        kind = ErrorKind.OTHER
    return Error(kind, stderr.strip() or f"az exited with {code}", "az")


def run_az(*args: str, timeout: int = TIMEOUT) -> Result[str]:
    """Run `az <args>`; stdout text or an Error. Never raises, never prompts."""
    try:
        r = subprocess.run(["az", *args, "--only-show-errors"], capture_output=True, check=False, env=_ENV,
                           timeout=timeout, stdin=subprocess.DEVNULL)
    except FileNotFoundError:
        return Result(error=Error(ErrorKind.MISSING_CLI, "az not found", "az"))
    except subprocess.TimeoutExpired:
        return Result(error=Error(ErrorKind.NETWORK, f"az timed out after {timeout}s", "az"))
    except OSError as e:
        return Result(error=Error(ErrorKind.OTHER, str(e), "az"))
    if r.returncode:
        return Result(error=classify(r.returncode, r.stderr.decode(errors="replace")))
    return Result(data=r.stdout.decode(errors="replace"))


def _json(*args: str) -> Result:
    res = run_az(*args, "--output", "json")
    if not res.ok:
        return res
    try:
        return Result(data=json.loads(res.data))
    except ValueError as e:
        return Result(error=Error(ErrorKind.OTHER, f"unparsable az output: {e}", "az"))


def _unexpected(e: Exception) -> Result:
    return Result(error=Error(ErrorKind.OTHER, f"unexpected az output: {e!r}", "az"))


def _branch(ref: str | None) -> str | None:
    return ref.removeprefix("refs/heads/") if ref else None


def _name(d: dict | str | None) -> str:
    """Identity (`{displayName, uniqueName}`; older API: plain string) -> display name."""
    if isinstance(d, dict):
        return d.get("displayName") or d.get("uniqueName") or ""
    return d or ""


def review_of(reviewers: list[dict] | None) -> str | None:
    """Votes (10 approved, 5 approved with suggestions, 0 none, -5 waiting for author, -10 rejected) ->
    approved | changes_requested | review_required. Groups (isContainer) do not vote."""
    votes = [r.get("vote") or 0 for r in reviewers or () if not r.get("isContainer")]
    if any(v < 0 for v in votes):
        return "changes_requested"
    if any(v > 0 for v in votes):
        return "approved"
    return "review_required" if votes else None


def checks_of(policies: list[dict] | None) -> str | None:
    """Policy evaluations -> success | failure | pending | None. Non-blocking and notApplicable are ignored."""
    states = []
    for p in policies or ():
        if (p.get("configuration") or {}).get("isBlocking") is False:
            continue
        s = p.get("status")
        if s in ("approved",):
            states.append("success")
        elif s in ("rejected", "broken"):
            states.append("failure")
        elif s in ("running", "queued"):
            states.append("pending")
    if not states:
        return None
    return "failure" if "failure" in states else "pending" if "pending" in states else "success"


class Azure:
    def __init__(self, org: str, project: str, repo: str):
        self.org, self.project, self.repo = org, project, repo
        self.org_url = f"https://dev.azure.com/{org}"
        self.slug = f"{org}/{project}/{repo}".lower()
        self._who: str | None = None
        self._raw: dict[int, dict] = {}  # work items incl. relations, one `az` call each

    @classmethod
    def for_repo(cls, r: PlatformRepo) -> Azure:
        return cls(r.org, r.project, r.repo)

    # -- parsing (needs org/project for URLs and slugs) --

    def parse_pr(self, d: dict) -> PullRequest:
        repo = d.get("repository") or {}
        project = (repo.get("project") or {}).get("name") or self.project
        rname = repo.get("name") or self.repo
        status = d.get("status", "active")
        state = {"active": "open", "completed": "merged", "abandoned": "closed"}.get(status, status)
        if state == "open" and d.get("isDraft"):
            state = "draft"
        return PullRequest(
            number=d["pullRequestId"], title=d["title"], state=state,
            url=f"{self.org_url}/{quote(project)}/_git/{quote(rname)}/pullrequest/{d['pullRequestId']}",
            author=_name(d.get("createdBy")), branch=_branch(d.get("sourceRefName")),
            review=review_of(d.get("reviewers")), checks=None, closing_issues=(),
            repo=f"{self.org}/{project}/{rname}".lower(), created_at=d.get("creationDate"),
        )

    def parse_work_item(self, d: dict) -> WorkItem:
        f = d.get("fields") or {}
        project = f.get("System.TeamProject") or self.project
        tags = tuple(t.strip() for t in (f.get("System.Tags") or "").split(";") if t.strip())
        who = _name(f.get("System.AssignedTo"))
        return WorkItem(
            number=int(d["id"]), title=f["System.Title"],
            state="closed" if (f.get("System.State") or "").lower() in _CLOSED else "open",
            url=f"{self.org_url}/{quote(project)}/_workitems/edit/{d['id']}",
            labels=tags, assignees=(who,) if who else (),
            board_status=f.get("System.BoardColumn") or None, board_available=True,
        )

    def parse_run(self, d: dict) -> PipelineRun:
        project = (d.get("project") or {}).get("name") or self.project
        start, end = d.get("startTime") or d.get("queueTime"), d.get("finishTime")
        dur = None
        try:
            dur = int((datetime.fromisoformat(end) - datetime.fromisoformat(d["startTime"])).total_seconds())
        except (KeyError, TypeError, ValueError):
            pass
        status = {"notStarted": "queued", "postponed": "queued", "inProgress": "in_progress",
                  "cancelling": "in_progress"}.get(d["status"], d["status"])
        result = {"succeeded": "success", "failed": "failure", "canceled": "cancelled",
                  "partiallySucceeded": "partially_succeeded"}.get(d.get("result") or "", d.get("result") or None)
        return PipelineRun(
            workflow=(d.get("definition") or {}).get("name") or d.get("buildNumber") or "?",
            branch=_branch(d.get("sourceBranch")) or "", status=status, conclusion=result,
            url=f"{self.org_url}/{quote(project)}/_build/results?buildId={d['id']}",
            started_at=start, duration_s=dur,
        )

    # -- provider --

    def _prs(self, *args: str) -> Result[list[PullRequest]]:
        res = _json("repos", "pr", "list", "--organization", self.org_url, *args)
        if not res.ok:
            return res
        try:
            return Result(data=[self.parse_pr(x) for x in res.data])
        except (KeyError, TypeError, AttributeError) as e:
            return _unexpected(e)

    def _enrich(self, pr: PullRequest) -> PullRequest:
        """Policy status and linked work items (needs one call each); failures leave the PR as it is."""
        pol = _json("repos", "pr", "policy", "list", "--id", str(pr.number), "--organization", self.org_url)
        wis = _json("repos", "pr", "work-item", "list", "--id", str(pr.number), "--organization", self.org_url)
        ids = []
        for w in (wis.data if wis.ok and isinstance(wis.data, list) else ()):
            try:
                ids.append(int(w["id"]))
            except (KeyError, TypeError, ValueError):
                pass
        return replace(pr, checks=checks_of(pol.data) if pol.ok and isinstance(pol.data, list) else None,
                       closing_issues=tuple(ids))

    def pull_requests(self, limit: int = 30, state: str = "all") -> Result[list[PullRequest]]:
        """Open + recently completed/abandoned PRs of this repo (newest first, at most `limit`). `state` is ignored."""
        res = self._prs("--project", self.project, "--repository", self.repo, "--status", "all",
                        "--top", str(limit))
        if not res.ok:
            return res
        done = 0
        out = []
        for p in res.data:  # ponytail: only the first ENRICH open PRs get checks/work items, raise if needed
            if p.state in ("open", "draft") and done < ENRICH:
                p, done = self._enrich(p), done + 1
            out.append(p)
        return Result(data=out)

    def pull_request(self, number: int) -> Result[PullRequest]:
        res = _json("repos", "pr", "show", "--id", str(number), "--organization", self.org_url)
        if not res.ok:
            return res
        try:
            return Result(data=self._enrich(self.parse_pr(res.data)))
        except (KeyError, TypeError, AttributeError) as e:
            return _unexpected(e)

    def work_item(self, number: int) -> Result[WorkItem]:
        res = _json("boards", "work-item", "show", "--id", str(number), "--organization", self.org_url)
        if not res.ok:
            return res
        try:
            return Result(data=self.parse_work_item(res.data))
        except (KeyError, TypeError, AttributeError, ValueError) as e:
            return _unexpected(e)

    # -- status (#56): work item relations as sub-issues / blocked_by, read-only --

    def _show(self, number: int) -> Result[dict]:
        if number not in self._raw:
            res = _json("boards", "work-item", "show", "--id", str(number), "--expand", "relations",
                        "--organization", self.org_url)
            if not res.ok:
                return res
            self._raw[number] = res.data
        return Result(data=self._raw[number])

    def parse_item(self, d: dict) -> Item:
        f = d.get("fields") or {}
        state = (f.get("System.State") or "").lower()
        dates = [schedule._iso((f.get(k) or "")[:10]) for k in
                 ("Microsoft.VSTS.Scheduling.DueDate", "Microsoft.VSTS.Scheduling.StartDate",
                  "Microsoft.VSTS.Scheduling.TargetDate")]
        due, von, bis = dates
        it = (f.get("System.IterationPath") or "").replace("\\", "/").rsplit("/", 1)[-1]
        notes = (f"Geplant: Ende {bis} liegt vor Start {von}",) if von and bis and bis < von else ()
        return Item(
            repo=self.slug, number=int(d["id"]), title=f["System.Title"],
            state="closed" if state in _CLOSED else "open",
            state_reason=None if state not in _CLOSED else "not_planned" if state == "removed" else "completed",
            labels=tuple(t.strip() for t in (f.get("System.Tags") or "").split(";") if t.strip()),
            schedule=Schedule((Deadline(due, it or "Fällig"),) if due else (), von, bis, notes),
            prio=p if (p := f.get("Microsoft.VSTS.Common.Priority")) in (1, 2, 3, 4) else None,
            sub_count=sum(r.get("rel") == "System.LinkTypes.Hierarchy-Forward" for r in d.get("relations") or ()),
        )

    def item(self, number: int) -> Result[Item]:
        res = self._show(number)
        if not res.ok:
            return res
        try:
            return Result(data=self.parse_item(res.data))
        except (KeyError, TypeError, AttributeError, ValueError) as e:
            return _unexpected(e)

    def _related(self, number: int, rel: str) -> Result[list[Item]]:
        """Items behind relations of type `rel`: Hierarchy-Forward = child, Dependency-Reverse = predecessor."""
        res = self._show(number)
        if not res.ok:
            return res
        out = []
        try:
            for r in res.data.get("relations") or ():
                if r.get("rel") == f"System.LinkTypes.{rel}":
                    got = self.item(int(r["url"].rstrip("/").rsplit("/", 1)[-1]))
                    if not got.ok:
                        return got
                    out.append(got.data)
        except (KeyError, TypeError, AttributeError, ValueError) as e:
            return _unexpected(e)
        return Result(data=out)

    def sub_issues(self, number: int) -> Result[list[Item]]:
        return self._related(number, "Hierarchy-Forward")

    def blocked_by(self, number: int) -> Result[list[Item]]:
        return self._related(number, "Dependency-Reverse")

    def branch_names(self) -> Result[list[str]]:
        res = _json("repos", "ref", "list", "--repository", self.repo, "--project", self.project,
                    "--filter", "heads/", "--organization", self.org_url)
        try:
            return Result(data=[_branch(r["name"]) for r in res.data]) if res.ok else res
        except (KeyError, TypeError) as e:
            return _unexpected(e)

    def login(self) -> Result[str]:
        """Signed-in user (`az account show`), cached for this provider."""
        if self._who:
            return Result(data=self._who)
        res = run_az("account", "show", "--query", "user.name", "--output", "tsv")
        if res.ok and not res.data.strip():
            return Result(error=Error(ErrorKind.NOT_LOGGED_IN, "az account show: no user", "az"))
        if res.ok:
            self._who = res.data.strip()
        return Result(data=self._who) if res.ok else res

    def pipeline_runs(self, days: int = 7, limit: int = 20) -> Result[list[PipelineRun]]:
        """My pipeline runs of the last `days` days in this repo (project-wide list, filtered by repository)."""
        who = self.login()
        if not who.ok:
            return who
        res = _json("pipelines", "runs", "list", "--organization", self.org_url, "--project", self.project,
                    "--requested-for", who.data, "--query-order", "QueueTimeDesc", "--top", str(limit))
        if not res.ok:
            return res
        since = datetime.now(UTC) - timedelta(days=days)
        out = []
        try:
            for d in res.data:
                name = (d.get("repository") or {}).get("name")
                if name and name.lower() != self.repo.lower():
                    continue
                run = self.parse_run(d)
                try:
                    if datetime.fromisoformat(run.started_at).astimezone(UTC) < since:
                        continue
                except (TypeError, ValueError):
                    pass
                out.append(run)
        except (KeyError, TypeError, AttributeError) as e:
            return _unexpected(e)
        return Result(data=out)

    def my_pull_requests(self, limit: int = 30) -> Result[list[PullRequest]]:
        """My open PRs in this repo's whole project (there is no organization-wide search)."""
        who = self.login()
        return who if not who.ok else self._prs("--project", self.project, "--creator", who.data,
                                                 "--status", "active", "--top", str(limit))

    def review_requests(self, limit: int = 30) -> Result[list[PullRequest]]:
        """Open PRs of the project where I am a reviewer and have not voted yet."""
        who = self.login()
        if not who.ok:
            return who
        res = _json("repos", "pr", "list", "--organization", self.org_url, "--project", self.project,
                    "--reviewer", who.data, "--status", "active", "--top", str(limit))
        if not res.ok:
            return res
        try:
            mine = [d for d in res.data if not any(
                (r.get("uniqueName") or "").lower() == who.data.lower() and r.get("vote")
                for r in d.get("reviewers") or ())]
            return Result(data=[self.parse_pr(d) for d in mine])
        except (KeyError, TypeError, AttributeError) as e:
            return _unexpected(e)
