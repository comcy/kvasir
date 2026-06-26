"""Query block renderer: evaluates ```query blocks in note content."""
from __future__ import annotations

import re
from typing import Any

from src.data.store import NdjsonStore

_BLOCK_RE = re.compile(r"```query\n(.*?)```", re.DOTALL)

STATUS_ICON = {"open": "○", "done": "●", "cancelled": "⊘"}


def _parse_params(text: str) -> dict[str, Any]:
    params: dict[str, Any] = {}
    for line in text.strip().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        val = val.strip()
        if val.startswith("[") and val.endswith("]"):
            val = [v.strip() for v in val[1:-1].split(",") if v.strip()]
        params[key.strip()] = val
    return params


def _render_todos(params: dict, store: NdjsonStore) -> str:
    todos = store.all("todos")

    if status := params.get("status"):
        todos = [t for t in todos if t.get("status") == status]

    if raw_tags := params.get("tags"):
        filter_tags = [raw_tags] if isinstance(raw_tags, str) else raw_tags
        tag_by_id = {t["id"]: t["name"] for t in store.all("tags")}
        mapping: dict[str, list[str]] = {}
        for tt in store.all("todo_tags"):
            name = tag_by_id.get(tt.get("tag_id", ""))
            if name:
                mapping.setdefault(tt["todo_id"], []).append(name)
        todos = [t for t in todos if any(tg in mapping.get(t["id"], []) for tg in filter_tags)]

    sort_key = params.get("sort", "due_date")
    todos.sort(key=lambda t: (t.get(sort_key) or "9999", t.get("text", "")))

    limit = int(params.get("limit", 50))
    todos = todos[:limit]

    if not todos:
        return "_No todos found._\n"

    lines = []
    for t in todos:
        icon = STATUS_ICON.get(t.get("status", "open"), "○")
        text = t.get("text", "")
        due = f" _{t['due_date']}_" if t.get("due_date") else ""
        lines.append(f"- {icon} {text}{due}")
    return "\n".join(lines) + "\n"


def render_query_blocks(content: str, store: NdjsonStore) -> str:
    """Replace ```query blocks in *content* with live Markdown results."""
    def _replace(m: re.Match) -> str:
        params = _parse_params(m.group(1))
        qtype = params.get("type", "todo")
        if qtype == "todo":
            return _render_todos(params, store)
        return f"_Unknown query type: `{qtype}`_\n"

    return _BLOCK_RE.sub(_replace, content)
