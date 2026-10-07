"""Status of an issue from facts (state, blockers, PRs, branches); `status:*` labels are only hints.

Pure rules in `derive`; `issue_status` reads via GitHub (gh) and never writes.
"""
from __future__ import annotations

import re
from dataclasses import replace

from kvasir.platform.az import Azure
from kvasir.platform.gh import GitHub
from kvasir.platform.models import IssueStatus, Item, ItemStatus, PullRequest, Result
from kvasir.platform.stepper import PHASES, Facts, Phases, feature_stepper, ticket_stepper

LABEL_PREFIX = "status:"


def _on_branch(number: int, branch: str | None) -> bool:
    return bool(branch) and re.search(rf"(?:^|[/_-]){number}(?:[/_-]|$)", branch) is not None


def _notices(item: Item, open_blockers: list[Item]) -> tuple[str, ...]:
    """Unlesbare Termin-Zeilen und Konflikte. Nur melden, nie bewerten oder korrigieren."""
    sc = item.schedule
    out = list(sc.notes)
    if sc.planned_to and sc.deadline and sc.planned_to > sc.deadline:
        out.append(f"Geplantes Ende {sc.planned_to} liegt nach Frist {sc.deadline}")
    if sc.planned_from:
        for b in open_blockers:
            end = b.schedule.planned_to or b.schedule.deadline  # ponytail: Ende = geplantes Ende, sonst Frist
            if end and end > sc.planned_from:
                out.append(f"Blocker #{b.number} endet {end}, nach Start {sc.planned_from}")
    return tuple(out)


def derive(item: Item, blockers: list[Item], prs: list[PullRequest], branches: list[str]) -> ItemStatus:
    """Order: closed -> blocked -> PR in review -> draft PR / branch -> open. Label only fills a gap or warns."""
    n = item.number
    mine = [p for p in prs if n in p.closing_issues or _on_branch(n, p.branch)]
    open_blockers = [b for b in blockers if b.state == "open"]
    if item.state == "closed":
        dropped = item.state_reason == "not_planned" or "wontfix" in item.labels
        status, reason = ("dropped", "Issue ist verworfen") if dropped else ("done", "Issue ist geschlossen")
    elif open_blockers:
        status, reason = "blocked", "Blocker " + ", ".join(f"#{b.number}" for b in open_blockers) + " offen"
    elif any(p.state == "open" for p in mine):
        p = next(p for p in mine if p.state == "open")
        status, reason = "in_review", f"PR #{p.number} ist bereit"
    elif mine:
        status, reason = "in_progress", f"PR #{mine[0].number} ist Draft"
    elif b := next((b for b in branches if _on_branch(n, b)), None):
        status, reason = "in_progress", f"Branch {b}"
    else:
        status, reason = "open", None
    label = next((x[len(LABEL_PREFIX):] for x in item.labels if x.startswith(LABEL_PREFIX)), None)
    source, hint = "fact", None
    if label and status == "open":
        status, source, reason = label.replace("-", "_"), "label", None
    elif label and label.replace("-", "_") != status:
        hint = f"Label sagt {label}, {reason}"
    return ItemStatus(item, tuple(blockers), status, source, reason, hint, _notices(item, open_blockers))


def _prs_of(n: int, prs: list[PullRequest]) -> list[PullRequest]:
    """PRs of issue n, live (open/draft) before merged; closed-unmerged ones don't count."""
    mine = [p for p in prs if p.state != "closed" and (n in p.closing_issues or _on_branch(n, p.branch))]
    return sorted(mine, key=lambda p: p.state == "merged")


def _with_stepper(st: ItemStatus, feature: bool, subs: list[Item], prs: list[PullRequest],
                  branches: list[str], phases: Phases) -> ItemStatus:
    n = st.item.number
    own = _prs_of(n, prs)
    if feature:
        own = [p for s in subs for p in _prs_of(s.number, prs)]
    f = Facts(st.item, tuple(subs), tuple(own), any(_on_branch(n, b) for b in branches))
    prev = tuple(b.number for b in st.blocked_by if b.state == "closed")
    return replace(st, stepper=feature_stepper(f, prev, phases) if feature else ticket_stepper(f, prev))


def issue_status(gh: GitHub | Azure, number: int, phases: Phases = PHASES) -> Result[IssueStatus]:
    """Issue + sub-issues, each with blockers and status. First failing gh call ends it with its Error."""
    root = gh.item(number)
    if not root.ok:
        return root
    subs = gh.sub_issues(number)
    prs = gh.pull_requests(limit=100, state="all") if subs.ok else subs
    branches = gh.branch_names() if prs.ok else prs
    for r in (subs, prs, branches):
        if not r.ok:
            return r
    out = []
    for it in [root.data, *subs.data]:
        bl = gh.blocked_by(it.number)
        if not bl.ok:
            return bl
        live = [p for p in prs.data if p.state in ("open", "draft")]
        feature = it is root.data and bool(subs.data)
        out.append(_with_stepper(derive(it, bl.data, live, branches.data), feature, subs.data, prs.data,
                                 branches.data, phases))
    return Result(data=IssueStatus(gh.slug, out[0], tuple(out[1:])))
