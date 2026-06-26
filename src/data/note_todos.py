"""Parse checkbox todos out of Markdown note content."""
from __future__ import annotations

import hashlib
import re
import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.data.store import NdjsonStore

_CHECKBOX_RE = re.compile(r'^-\s+\[(?P<done>[xX ])\]\s+(?P<rest>.+)$', re.MULTILINE)
_ASSIGNEE_RE = re.compile(r'@([\w][\w-]*)')          # @john, @finance-team
_TAG_RE = re.compile(r'#([a-zA-Z][a-zA-Z0-9_-]*)')  # #dev, #admin — NOT #42 (issue refs)
_DUE_RE = re.compile(r'due:(\d{4}-\d{2}-\d{2})')


def source_hash(note_ref: str, text: str) -> str:
    """Stable 12-char ID for deduplication: (note_slug, normalised task text)."""
    return hashlib.md5(f"{note_ref}|{text.lower()}".encode()).hexdigest()[:12]


def parse_note_todos(content: str, note_slug: str) -> list[dict]:
    """
    Extract checkbox items from Markdown content.

    Syntax:
        - [ ] Task text @assignee #tag due:2026-07-01
        - [x] Already done @john #billing
    """
    todos = []
    for m in _CHECKBOX_RE.finditer(content):
        done = m.group("done").strip().lower() == "x"
        rest = m.group("rest").strip()

        am = _ASSIGNEE_RE.search(rest)
        assignee = am.group(1) if am else None
        tags = _TAG_RE.findall(rest)
        dm = _DUE_RE.search(rest)
        due_date = dm.group(1) if dm else None

        # Strip structured markers from text
        text = rest
        if am:
            text = text.replace(am.group(0), "", 1)
        text = _DUE_RE.sub("", text)
        text = _TAG_RE.sub("", text)
        text = re.sub(r"\s+", " ", text).strip().strip("-").strip()

        if not text:
            continue

        todos.append({
            "text": text,
            "status": "done" if done else "open",
            "assignee": assignee,
            "tags": tags,
            "due_date": due_date,
            "note_ref": note_slug,
            "source_hash": source_hash(note_slug, text),
        })
    return todos


def save_todo_tags(store: "NdjsonStore", todo_id: str, tag_names: list[str]) -> None:
    """Ensure tags exist and link them to a todo."""
    for name in tag_names:
        existing = store.find("tags", name=name)
        tag = existing[0] if existing else store.insert("tags", {"id": str(uuid.uuid4()), "name": name})
        store.insert("todo_tags", {"todo_id": todo_id, "tag_id": tag["id"]})
