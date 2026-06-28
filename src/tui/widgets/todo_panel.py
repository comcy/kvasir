"""Compact dashboard todo panel — two-line items, full CRUD."""
from __future__ import annotations

import uuid
from datetime import date, datetime

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Label, ListItem, ListView, Static
from textual.containers import Vertical

from src.workspace.manager import WorkspaceManager
from src.data.note_todos import PRIORITY_LABEL

STATUS_ICON  = {"open": "○", "done": "●", "cancelled": "⊘"}
STATUS_CLASS = {"open": "todo-open", "done": "todo-done", "cancelled": "todo-cancelled"}

_PRIO_MARKUP = {
    3: "[bold red]!!![/bold red]",
    2: "[yellow]!![/yellow]",
    1: "[dim]![/dim]",
}


def _urgency(todo: dict, today: str) -> int:
    due = todo.get("due_date") or ""
    if not due:   return 3
    if due < today: return 0
    if due == today: return 1
    return 2


# ── list items ──────────────────────────────────────────────────────────────

class _SectionDivider(ListItem):
    def __init__(self, label: str) -> None:
        super().__init__()
        self._label = label

    def compose(self) -> ComposeResult:
        yield Label(f"  [dim]── {self._label}[/dim]")


class TodoItem(ListItem):
    def __init__(self, todo: dict, today: str) -> None:
        super().__init__()
        self.todo = todo
        self._today = today

    def watch_highlighted(self, _: bool) -> None:
        self.refresh(recompose=True)

    def compose(self) -> ComposeResult:
        status   = self.todo.get("status", "open")
        icon     = STATUS_ICON.get(status, "?")
        text     = self.todo.get("text", "")
        due      = self.todo.get("due_date") or ""
        assignee = self.todo.get("assignee") or ""
        tags     = self.todo.get("_tags", [])
        priority = int(self.todo.get("priority") or 0)
        sel      = self.highlighted

        # Urgency colouring for open todos
        if status == "open" and due:
            if due < self._today:
                text_cls = "todo-overdue"
                due_str  = f"[bold red]⚠ {due}[/bold red]"
            elif due == self._today:
                text_cls = "todo-today"
                due_str  = f"[bold yellow]● {due}[/bold yellow]"
            else:
                text_cls = "todo-open"
                due_str  = f"[dim]{due}[/dim]"
        else:
            text_cls = STATUS_CLASS.get(status, "")
            due_str  = f"[dim]{due}[/dim]" if due else ""

        arrow = "[bold bright_cyan]▶[/bold bright_cyan]" if sel else " "
        text_markup = f"[bold]{text}[/bold]" if sel else text

        # Line 1: arrow + status icon + text
        yield Label(f" {arrow} {icon}  [{text_cls}]{text_markup}[/{text_cls}]")

        # Line 2: priority · due · assignee · tags
        meta: list[str] = []
        if priority in _PRIO_MARKUP:
            meta.append(_PRIO_MARKUP[priority])
        if due_str:
            meta.append(due_str)
        if assignee:
            meta.append(f"[dim]→ @{assignee}[/dim]")
        if tags:
            meta.append("[dim]" + "  ".join(f"#{t}" for t in tags) + "[/dim]")
        if meta:
            yield Label("        " + "  ·  ".join(meta))


# ── panel ────────────────────────────────────────────────────────────────────

class TodoPanel(Widget):

    DEFAULT_CSS = """
    TodoPanel { height: 1fr; }

    .todo-overdue { color: $error; }
    .todo-today   { color: $warning; }
    .todo-open    { color: $foreground; }
    .todo-done    { color: $success; text-style: dim; }
    .todo-cancelled { color: $error; text-style: dim strike; }

    TodoPanel ListView  { background: transparent; height: auto; }
    TodoPanel ListItem  { background: transparent; padding: 0; }
    TodoPanel ListItem:hover { background: $surface; }
    TodoPanel ListView:focus > ListItem.--highlight { background: $primary 20%; }

    TodoPanel _SectionDivider { height: 1; background: $background; margin-top: 1; }
    TodoPanel _SectionDivider:hover { background: $background; }
    TodoPanel ListView:focus > _SectionDivider.--highlight { background: $background; }

    TodoItem { height: auto; padding: 1 0 0 0; }

    .tp-section { color: $foreground; text-style: bold; margin-top: 1; padding: 0 1; }
    .tp-empty   { color: $foreground 45%; padding: 0 2; }
    """

    BINDINGS = [
        ("a", "add_todo",    "Add"),
        ("d", "toggle_done", "Done/Undo"),
        ("e", "edit_todo",   "Edit"),
        ("x", "delete_todo", "Delete"),
    ]

    def __init__(self, wm: WorkspaceManager, **kwargs) -> None:
        super().__init__(**kwargs)
        self._wm = wm

    # ── data ────────────────────────────────────────────────────────────────

    def _load(self) -> list[dict]:
        try:
            store = self._wm.store()
            todos = store.all("todos")
            tag_by_id = {t["id"]: t["name"] for t in store.all("tags")}
            tag_map: dict[str, list[str]] = {}
            for tt in store.all("todo_tags"):
                name = tag_by_id.get(tt.get("tag_id", ""))
                if name:
                    tag_map.setdefault(tt["todo_id"], []).append(name)
            for t in todos:
                t["_tags"] = sorted(tag_map.get(t["id"], []))
            return todos
        except Exception:
            return []

    def _sync_to_note(self, todo: dict, new_status: str, new_text: str | None = None) -> str | None:
        """Write status (and optionally text) back to the source note checkbox."""
        sh = todo.get("source_hash")
        note_ref = todo.get("note_ref")
        if not sh or not note_ref:
            return None
        try:
            from src.data.note_todos import update_note_checkbox_full
            note_path = self._wm.notes_dir() / f"{note_ref}.md"
            if not note_path.exists():
                return None
            new_hash = update_note_checkbox_full(note_path, note_ref, sh, new_text, new_status)
            if new_hash:
                from src.tui.widgets.notes_panel import NotesPanel
                try:
                    np = self.app.query_one(NotesPanel)
                    if np._selected_path == note_path:
                        np._refresh_preview()
                except Exception:
                    pass
            return new_hash
        except Exception:
            return None

    def _save_tags(self, todo_id: str, tag_names: list[str]) -> None:
        store = self._wm.store()
        store.delete_where("todo_tags", todo_id=todo_id)
        for name in tag_names:
            existing = store.find("tags", name=name)
            tag = existing[0] if existing else store.insert(
                "tags", {"id": str(uuid.uuid4()), "name": name}
            )
            store.insert("todo_tags", {"todo_id": todo_id, "tag_id": tag["id"]})

    # ── compose ──────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        today = date.today().isoformat()
        todos = self._load()

        open_todos = sorted(
            [t for t in todos if t.get("status") == "open"],
            key=lambda t: (_urgency(t, today), t.get("due_date") or "9999"),
        )
        done_todos = [t for t in todos if t.get("status") == "done"]

        overdue   = [t for t in open_todos if _urgency(t, today) == 0]
        today_due = [t for t in open_todos if _urgency(t, today) == 1]
        rest      = [t for t in open_todos if _urgency(t, today) >= 2]

        with Vertical():
            if not todos:
                yield Static("  [dim]No todos yet.[/dim]", classes="tp-empty")
                return

            items: list[ListItem] = []

            if overdue:
                items.append(_SectionDivider(f"Overdue ({len(overdue)})"))
                items.extend(TodoItem(t, today) for t in overdue)

            if today_due:
                items.append(_SectionDivider(f"Today ({len(today_due)})"))
                items.extend(TodoItem(t, today) for t in today_due)

            if rest:
                items.append(_SectionDivider(f"Open ({len(rest)})"))
                items.extend(TodoItem(t, today) for t in rest)

            if not open_todos:
                items.append(Static("  [dim]All done! ✓[/dim]", classes="tp-empty"))

            if done_todos:
                items.append(_SectionDivider(f"Done ({len(done_todos)})"))
                items.extend(TodoItem(t, today) for t in done_todos[-5:])

            yield ListView(*items, id="tp-lv")

    # ── helpers ──────────────────────────────────────────────────────────────

    def _selected(self) -> dict | None:
        try:
            lv = self.query_one("#tp-lv", ListView)
            idx = lv.index
            if idx is None:
                return None
            children = list(lv.children)
            if idx >= len(children):
                return None
            item = children[idx]
            return item.todo if isinstance(item, TodoItem) else None
        except Exception:
            return None

    def reload(self) -> None:
        self.refresh(recompose=True)

    # ── actions ──────────────────────────────────────────────────────────────

    def action_add_todo(self) -> None:
        from src.tui.screens.todo_form import TodoFormScreen

        def cb(result: dict | None) -> None:
            if not result:
                return
            store = self._wm.store()
            now = datetime.now().isoformat()
            rec = store.insert("todos", {
                "id": str(uuid.uuid4()),
                "text": result["text"],
                "status": "open",
                "priority": result.get("priority", 0),
                "due_date": result.get("due_date"),
                "assignee": result.get("assignee"),
                "created": now,
                "updated": now,
            })
            self._save_tags(rec["id"], result.get("tags", []))
            self.refresh(recompose=True)
            self.notify("Todo added.", timeout=1.5)

        self.app.push_screen(TodoFormScreen(), cb)

    def action_toggle_done(self) -> None:
        todo = self._selected()
        if not todo:
            self.notify("Select a todo first.", severity="warning")
            return
        new_status = "open" if todo.get("status") == "done" else "done"
        self._wm.store().update(
            "todos", todo["id"], status=new_status, updated=datetime.now().isoformat()
        )
        self._sync_to_note(todo, new_status)
        self.refresh(recompose=True)

    def action_edit_todo(self) -> None:
        todo = self._selected()
        if not todo:
            self.notify("Select a todo first.", severity="warning")
            return
        from src.tui.screens.todo_form import TodoFormScreen

        def cb(result: dict | None) -> None:
            if not result:
                return
            store_updates: dict = {
                "text":     result["text"],
                "priority": result.get("priority", 0),
                "due_date": result.get("due_date"),
                "assignee": result.get("assignee"),
                "updated":  datetime.now().isoformat(),
            }
            new_hash = self._sync_to_note(
                todo, todo.get("status", "open"), new_text=result["text"]
            )
            if new_hash and new_hash != todo.get("source_hash"):
                store_updates["source_hash"] = new_hash
            self._wm.store().update("todos", todo["id"], **store_updates)
            self._save_tags(todo["id"], result.get("tags", []))
            self.refresh(recompose=True)
            self.notify("Todo updated.", timeout=1.5)

        self.app.push_screen(
            TodoFormScreen(todo=todo, tag_names=todo.get("_tags", [])), cb
        )

    def action_delete_todo(self) -> None:
        todo = self._selected()
        if not todo:
            self.notify("Select a todo first.", severity="warning")
            return
        self._wm.store().delete_with_relations(
            "todos", todo["id"], [("todo_tags", "todo_id")]
        )
        self.refresh(recompose=True)
        self.notify("Todo deleted.", timeout=1.5)
