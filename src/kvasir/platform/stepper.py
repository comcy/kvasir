"""Stepper: where an item stands in the development cycle, from detectors (fixed vocabulary, read-only).

Feature level: phases of the built-in standard process, each with a `done_when` list of detectors.
Ticket level: branch -> PR draft -> checks -> local acceptance -> review -> PR ready -> merged.
A detector is True, False or None (unknown); a step with an unknown detector is not shown.
First step that is not done is "current", everything after it is "open".
"""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from kvasir.platform.models import Item, PullRequest, Step, Stepper

Phases = tuple[tuple[str, tuple[str, ...]], ...]  # (name, done_when detectors, AND)
# Built-in standard; a repo overrides it via kvasir.toml / workflow/phases.tsv (see kvasir.repo_file)
PHASES: Phases = (
    ("Setup", ("file_exists:AGENTS.md",)),
    ("Eingang", ("issue_exists",)),
    ("Idee schärfen", ("label:ready-for-agent",)),
    ("Anforderungen", ("openspec_change_exists", "openspec_artifacts_complete")),
    ("Arbeit schneiden", ("subissues_exist",)),
    ("Bauen", ("pr_state:draft",)),
    ("Abnahme", ("pr_state:ready", "checks:success")),
    ("Abschließen", ("pr_state:merged", "issue_closed")),
    ("Wissen sichern", ("file_exists:docs/adr",)),
)
# Fixed detector vocabulary: name -> argument kind ("-" none, "text", "path" or tuple of allowed values)
DETECTORS: dict[str, str | tuple[str, ...]] = {
    "issue_exists": "-", "label": "text", "subissues_exist": "-", "issue_closed": "-", "file_exists": "path",
    "openspec_change_exists": "-", "openspec_artifacts_complete": "-",
    "pr_state": ("draft", "ready", "merged"), "checks": ("success", "failure"),
    "issue_open": "-", "has_label_kind": ("triage", "status"), "no_open_blockers": "-", "subissues_closed": "-",
    "pr_checklist": "text", "openspec_archived": "-",
}
# Vocabulary of a repo = workflow/detectors.tsv (see kvasir.repo_file); kvasir can only evaluate DETECTORS.
Vocabulary = dict[str, str | tuple[str, ...]]
_BOX = re.compile(r"^\s*[-*]\s*\[( |x|X)\]\s*(.*)$", re.MULTILINE)


@dataclass(frozen=True)
class Facts:
    item: Item
    subs: tuple[Item, ...]
    prs: tuple[PullRequest, ...]  # PRs of the item (feature level: of its sub-issues), merged ones included
    branch: bool = False
    blockers: tuple[Item, ...] = ()


def _openspec() -> tuple[bool, bool] | None:
    """(any active change, all complete) via `openspec`; None when missing or no OpenSpec root."""
    def run(*a: str):
        try:
            r = subprocess.run(["openspec", *a, "--json"], capture_output=True, check=False, timeout=30,
                               stdin=subprocess.DEVNULL)
            return json.loads(r.stdout) if r.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired, ValueError):
            return None
    listing = run("list")
    if not isinstance(listing, dict) or not listing.get("root"):
        return None
    names = [c["name"] for c in listing.get("changes", [])]
    done = [run("status", "--change", n) for n in names]
    if any(not isinstance(d, dict) for d in done):
        return None
    return bool(names), bool(names) and all(d.get("isComplete") for d in done)


def _archived() -> bool | None:
    """Archived change(s) and no active one. ponytail: not tied to the issue, fine as phases run in order."""
    o = _openspec()
    return None if o is None else (not o[0]) and any(p.is_dir() for p in Path("openspec/changes/archive").glob("*"))


def _label_kinds() -> dict[str, str] | None:
    """label -> kind from workflow/states.tsv (cwd = checkout); None when missing."""
    try:
        lines = [x for x in Path("workflow/states.tsv").read_text(encoding="utf-8").splitlines()
                 if x.strip() and not x.startswith("#")]
    except OSError:
        return None
    head = lines[0].split("\t") if lines else []
    rows = [dict(zip(head, x.split("\t"), strict=False)) for x in lines[1:]]
    return {r["id"]: r.get("kind", "") for r in rows if "id" in r and r.get("enabled", "").lower() != "no"}


def check_detector(spec: str, vocab: Vocabulary | None = None) -> str | None:
    """Error text when `spec` ("name" or "name:arg") is not in the vocabulary (default: built-in), else None."""
    name, _, arg = spec.partition(":")
    kind = (DETECTORS if vocab is None else vocab).get(name)
    if kind is None:
        return f"unknown detector {name}"
    if kind == "-":
        return f"detector {name} takes no argument" if arg else None
    if not arg:
        return f"detector {name} needs an argument"
    if isinstance(kind, tuple) and arg not in kind:
        return f"detector {name}: {arg} is not one of {'|'.join(kind)}"
    return None


def detect(spec: str, f: Facts) -> bool | None:
    kind, _, arg = spec.partition(":")
    ps = f.prs
    if kind == "issue_exists":
        return True
    if kind == "label":
        return arg in f.item.labels
    if kind == "issue_open":
        return f.item.state == "open"
    if kind == "no_open_blockers":
        return not any(b.state == "open" for b in f.blockers)
    if kind == "subissues_exist":
        return bool(f.subs)
    if kind == "subissues_closed":
        return bool(f.subs) and all(x.state == "closed" for x in f.subs)
    if kind == "has_label_kind":
        kinds = _label_kinds()
        return None if kinds is None else any(kinds.get(x) == arg for x in f.item.labels)
    if kind == "pr_checklist":  # False without PR; None when no PR has such a box
        if not ps:
            return False
        boxes = [b for p in ps if (b := _box(p.body, arg.lower())) is not None]
        return all(boxes) if boxes else None
    if kind == "openspec_archived":
        return _archived()
    if kind == "issue_closed":
        return f.item.state == "closed"
    if kind == "file_exists":
        return Path(arg).exists()
    if kind in ("openspec_change_exists", "openspec_artifacts_complete"):
        o = _openspec()
        return None if o is None else o[kind == "openspec_artifacts_complete"]
    if kind == "pr_state":  # draft = a PR exists, ready = ready or merged, merged = merged
        ok = {"draft": ("draft", "open", "merged"), "ready": ("open", "merged"), "merged": ("merged",)}[arg]
        return bool(ps) and all(p.state in ok for p in ps)
    if kind == "checks":
        if not ps:
            return False
        return None if any(p.checks is None for p in ps) else all(p.checks == arg for p in ps)
    raise ValueError(f"unknown detector {spec}")


def _mark(steps: list[tuple[str, bool]]) -> tuple[Step, ...]:
    cur = next((i for i, (_, d) in enumerate(steps) if not d), len(steps))
    return tuple(Step(n, "done" if i < cur else "current" if i == cur else "open") for i, (n, _) in enumerate(steps))


def feature_stepper(f: Facts, previous: tuple[int, ...] = (), phases: Phases = PHASES) -> Stepper:
    steps = []
    for name, specs in phases:
        # unknown detector (typo in a repo file) = unknown, never an exception; no detector = not observable
        res = [detect(s, f) if check_detector(s) is None else None for s in specs]
        if specs and None not in res:
            steps.append((name, all(res)))
    return Stepper("feature", _mark(steps), previous)


def _box(body: str | None, word: str) -> bool | None:
    return next((m[0] != " " for m in _BOX.findall(body or "") if word in m[1].lower()), None)


def ticket_stepper(f: Facts, previous: tuple[int, ...] = ()) -> Stepper:
    pr = f.prs[0] if f.prs else None  # live PR first (see issue_status)
    steps = [("Branch", f.branch or pr is not None), ("PR Draft", pr is not None)]
    if pr is None or pr.checks is not None:
        steps.append(("Checks grün", detect("checks:success", f) is True))
    for name, word in (("lokale Abnahme", "abnahme"), ("Review", "review")):
        if pr and (b := _box(pr.body, word)) is not None:
            steps.append((name, b))
    steps += [("PR bereit", detect("pr_state:ready", f) is True), ("gemergt", detect("pr_state:merged", f) is True)]
    return Stepper("ticket", _mark(steps), previous)
