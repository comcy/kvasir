"""Cache of platform answers: `platform_cache.json` in the config dir, `{repo_url: {query: entry}}`.

Entry = `{"fetched_at": ISO UTC, "items": [dataclass as dict, ...]}`. Broken file or entry = cache miss.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, fields
from datetime import UTC, datetime
from typing import TypeVar

from kvasir.config import config_dir

T = TypeVar("T")


@dataclass(frozen=True)
class CacheEntry:
    items: list
    fetched_at: datetime


def _path():
    return config_dir() / "platform_cache.json"


def _load() -> dict:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write(url: str, query: str, items: list) -> None:
    """Store dataclass instances (e.g. `"pull_requests"`, `"work_item:27"`). Atomic: temp file + replace."""
    data = _load()
    repo = data.get(url) if isinstance(data.get(url), dict) else {}
    repo[query] = {"fetched_at": datetime.now(UTC).isoformat(), "items": [asdict(i) for i in items]}
    data[url] = repo
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".platform_cache.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, p)
    except BaseException:
        os.unlink(tmp)
        raise


def read(url: str, query: str, cls: type[T]) -> CacheEntry | None:
    """Cached `cls` instances with their `fetched_at`; None when missing or unusable. Works offline."""
    e = _load().get(url)
    e = e.get(query) if isinstance(e, dict) else None
    try:
        tuples = {f.name for f in fields(cls) if "tuple" in str(f.type)}
        items = [cls(**{k: tuple(v) if k in tuples else v for k, v in d.items()}) for d in e["items"]]
        return CacheEntry(items, datetime.fromisoformat(e["fetched_at"]))
    except (KeyError, TypeError, ValueError):
        return None
