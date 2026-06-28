"""Parse checkbox todos out of Markdown note content."""
from __future__ import annotations

import hashlib
import re
import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path
    from src.data.store import NdjsonStore

_CHECKBOX_RE  = re.compile(r'^-\s+\[(?P<done>[xX ])\]\s+(?P<rest>.+)$', re.MULTILINE)
_ASSIGNEE_RE  = re.compile(r'@([\w][\w-]*)')
_TAG_RE       = re.compile(r'#([a-zA-Z][a-zA-Z0-9_-]*)')
_DUE_RE       = re.compile(r'due:(\d{4}-\d{2}-\d{2})')
# Matches !, !! or !!! not flanked by more ! characters. Higher count = higher priority.
_PRIORITY_RE  = re.compile(r'(?<![!])(!!!|!!|!)(?![!])')

PRIORITY_LEVEL = {"!!!": 3, "!!": 2, "!": 1}
PRIORITY_LABEL = {3: "!!!", 2: "!!", 1: "!", 0: ""}
PRIORITY_COLOR = {3: "bold red", 2: "yellow", 1: "dim", 0: ""}


def source_hash(note_ref: str, text: str) -> str:
    """Stable 12-char ID: md5(note_ref|normalised_text)."""
    return hashlib.md5(f"{note_ref}|{text.lower()}".encode()).hexdigest()[:12]


def _clean_text(rest: str) -> str:
    """
    Extract the human-readable text from a raw checkbox line, stripping all
    structured markers (@assignee, #tag, due:, priority tokens).
    Must stay identical to the stripping done in parse_note_todos.
    """
    text = rest
    am = _ASSIGNEE_RE.search(rest)
    if am:
        text = text.replace(am.group(0), "", 1)
    text = _DUE_RE.sub("", text)
    text = _TAG_RE.sub("", text)
    text = _PRIORITY_RE.sub("", text)
    return re.sub(r"\s+", " ", text).strip().strip("-").strip()


def _legacy_text(rest: str) -> str:
    """
    Same as _clean_text but WITHOUT priority stripping — reproduces the hash
    that was stored before priority support was added.  Used for drift repair.
    """
    text = rest
    am = _ASSIGNEE_RE.search(rest)
    if am:
        text = text.replace(am.group(0), "", 1)
    text = _DUE_RE.sub("", text)
    text = _TAG_RE.sub("", text)
    return re.sub(r"\s+", " ", text).strip().strip("-").strip()


def _find_checkbox(content: str, note_slug: str, todo_hash: str) -> re.Match | None:
    """
    Find the checkbox whose source_hash matches *todo_hash*.
    Checks both the current hash format AND the legacy format (no priority stripping)
    so that todos extracted before priority support was added are still found.
    """
    for m in _CHECKBOX_RE.finditer(content):
        rest = m.group("rest").strip()
        current = _clean_text(rest)
        if current and source_hash(note_slug, current) == todo_hash:
            return m
        legacy = _legacy_text(rest)
        if legacy and legacy != current and source_hash(note_slug, legacy) == todo_hash:
            return m
    return None


def parse_note_todos(content: str, note_slug: str) -> list[dict]:
    """
    Extract checkbox items from Markdown content.

    Syntax:
        - [ ] Task text @assignee #tag due:2026-07-01 !!!
        - [x] Already done @john #billing !!
    Priority: ! = low (1), !! = medium (2), !!! = high (3).
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
        pm = _PRIORITY_RE.search(rest)
        priority = PRIORITY_LEVEL.get(pm.group(1), 0) if pm else 0

        text = _clean_text(rest)
        if not text:
            continue

        todos.append({
            "text": text,
            "status": "done" if done else "open",
            "priority": priority,
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


# ── bidirectional sync ────────────────────────────────────────────────────────

def write_todo_status_to_note(
    note_path: "Path",
    note_slug: str,
    todo_source_hash: str,
    new_status: str,
) -> bool:
    """
    Toggle the checkbox marker ([ ] / [x]) that matches *todo_source_hash*.
    Text and metadata markers are left untouched.
    Returns True if found and updated.
    """
    return update_note_checkbox_full(
        note_path, note_slug, todo_source_hash,
        new_text=None,
        new_status=new_status,
    ) is not None


def update_note_checkbox_full(
    note_path: "Path",
    note_slug: str,
    todo_source_hash: str,
    new_text: str | None,
    new_status: str,
) -> str | None:
    """
    Find the checkbox whose source_hash matches *todo_source_hash* and update it.

    - *new_text*: if not None, the checkbox text is replaced (metadata markers
      like @assignee, #tag, due:, priority are preserved in the rebuilt line).
    - *new_status*: "done"/"cancelled" → [x], anything else → [ ].

    Returns the (possibly changed) source_hash of the updated entry so that the
    caller can update the stored hash when text was changed.  Returns None if the
    checkbox was not found.
    """
    import frontmatter as _fm
    from datetime import datetime

    try:
        post = _fm.load(str(note_path))
        content = post.content
        m = _find_checkbox(content, note_slug, todo_source_hash)
        if not m:
            return None

        rest  = m.group("rest").strip()
        done_char = "x" if new_status in ("done", "cancelled") else " "

        if new_text is None:
            # Status-only update: just flip the [ ] / [x]
            new_line = re.sub(r'\[[ xX]\]', f'[{done_char}]', m.group(0), count=1)
            final_text = _clean_text(rest)
        else:
            # Text + status update: rebuild the line keeping all metadata markers
            am = _ASSIGNEE_RE.search(rest)
            dm = _DUE_RE.search(rest)
            pm = _PRIORITY_RE.search(rest)
            tags = _TAG_RE.findall(rest)

            parts = [new_text]
            if am:   parts.append(f"@{am.group(1)}")
            if pm:   parts.append(pm.group(1))
            for tag in tags:
                parts.append(f"#{tag}")
            if dm:   parts.append(f"due:{dm.group(1)}")

            new_line = f"- [{done_char}] {' '.join(parts)}"
            final_text = new_text

        content = content[: m.start()] + new_line + content[m.end() :]
        post.content = content
        post.metadata["editedAt"] = datetime.now().isoformat()
        note_path.write_text(_fm.dumps(post), encoding="utf-8")
        return source_hash(note_slug, final_text)
    except Exception:
        return None


def sync_note_todos(
    store: "NdjsonStore",
    note_path: "Path",
    note_slug: str,
) -> tuple[int, int]:
    """
    Bidirectional note → store sync (called after a note is saved via $EDITOR).

    For each checkbox in the note:
      - If a matching todo exists (by source_hash OR by legacy hash OR by text):
        update status, text, and repair any hash drift.
      - Otherwise: create a new todo.

    Returns (created, updated).
    """
    import frontmatter as _fm
    from datetime import datetime

    try:
        post = _fm.load(str(note_path))
        parsed = parse_note_todos(post.content, note_slug)
    except Exception:
        return 0, 0

    if not parsed:
        return 0, 0

    all_todos = store.all("todos")

    # Primary index: current source_hash → todo
    existing_by_hash: dict[str, dict] = {}
    for t in all_todos:
        if t.get("source_hash"):
            existing_by_hash[t["source_hash"]] = t

    # Drift-repair index: for todos from this note, also index by what their
    # hash WOULD be if the text had its priority markers stripped (legacy→current).
    for t in all_todos:
        if t.get("note_ref") != note_slug or not t.get("text"):
            continue
        stripped = _PRIORITY_RE.sub("", t["text"]).strip()
        if stripped and stripped.lower() != t["text"].lower():
            new_h = source_hash(note_slug, stripped)
            if new_h not in existing_by_hash:
                existing_by_hash[new_h] = t

    # Secondary index: note-scoped text lookup (last-resort fallback)
    existing_by_text: dict[str, dict] = {}
    for t in all_todos:
        if t.get("note_ref") == note_slug and t.get("text"):
            existing_by_text[t["text"].lower()] = t

    now = datetime.now().isoformat()
    created = updated = 0
    matched_ids: set[str] = set()

    for todo in parsed:
        h = todo["source_hash"]
        existing = existing_by_hash.get(h)

        # Last-resort: match by text when both hash indices fail
        if not existing:
            existing = existing_by_text.get(todo["text"].lower())

        if existing:
            if existing["id"] in matched_ids:
                # Already matched this record — skip to avoid double-update
                continue
            matched_ids.add(existing["id"])

            changes: dict = {}
            if existing.get("status") != todo["status"]:
                changes["status"] = todo["status"]
            if existing.get("text") != todo["text"]:
                changes["text"] = todo["text"]
            # Repair hash drift (old record had priority in text, new format strips it)
            if existing.get("source_hash") != h:
                changes["source_hash"] = h
            if changes:
                store.update("todos", existing["id"], updated=now, **changes)
                updated += 1
        else:
            rec = store.insert("todos", {
                "id": str(uuid.uuid4()),
                "text": todo["text"],
                "status": todo["status"],
                "priority": todo.get("priority", 0),
                "due_date": todo["due_date"],
                "assignee": todo["assignee"],
                "note_ref": todo["note_ref"],
                "source_hash": h,
                "created": now,
                "updated": now,
            })
            if todo["tags"]:
                save_todo_tags(store, rec["id"], todo["tags"])
            created += 1

    return created, updated
