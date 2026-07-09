from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal


@dataclass
class Todo:
    id: str
    text: str
    status: Literal["open", "done", "cancelled"] = "open"
    due_date: str | None = None
    created: str = field(default_factory=lambda: datetime.now().isoformat())
    updated: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class Tag:
    id: str
    name: str
    color: str = "#888888"


@dataclass
class TodoTag:
    todo_id: str
    tag_id: str


@dataclass
class Metric:
    id: str
    name: str
    label: str
    type: Literal["counter", "duration", "gauge"]
    aggregation: Literal["daily", "weekly", "monthly"] = "weekly"
    source: str | None = None


@dataclass
class MetricValue:
    id: str
    metric_id: str
    timestamp: str
    value: float


@dataclass
class Commit:
    hash: str
    type: str
    scope: str | None
    subject: str
    breaking: bool
    date: str
    body: str = ""


@dataclass
class Session:
    id: str
    repo: str
    branch: str
    start: str
    end: str | None = None
    worktree_path: str = ""


@dataclass
class Project:
    id: str
    name: str
    path: str
    remote: str = ""
    created: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class Link:
    id: str
    source: str
    target: str
    relation: str = "related"
