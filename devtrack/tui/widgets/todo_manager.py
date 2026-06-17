"""Full Todo manager: list with tag chips, status filter, CRUD via modals."""
from __future__ import annotations

import uuid
from datetime import datetime

from textual.app import ComposeResult
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Button, Label, ListItem, ListView, Static
from textual.containers import Horizontal, Vertical, VerticalScroll

from devtrack.workspace.manager import WorkspaceManager
from devtrack.tui.screens.todo_form import TodoFormScreen

STATUS_ICON = {"open": "○", "done": "●", "cancelled": "⊘"}
STATUS_CLASS = {"open": "todo-open", "done": "todo-done", "cancelled": "todo-cancelled"}
STATUS_CYCLE = ["all", "open", "done", "cancelled"]


class TodoListItem(ListItem):
    def __init__(self, todo: dict) -> None:
        super().__init__()
        self.todo = todo

    def compose(self) -> ComposeResult:
        status = self.todo.get("status", "open")
        icon = STATUS_ICON.get(status, "?")
        text = self.todo.get("text", "")
        due = self.todo.get("due_date") or ""
        tags = self.todo.get("_tags", [])
        css = STATUS_CLASS.get(status, "")

        tags_part = "  " + " ".join(f"[dim][{t}][/dim]" for t in tags) if tags else ""
        due_part = f"  [dim]{due}[/dim]" if due else ""
        yield Label(f"  {icon}  [{css}]{text}[/{css}]{tags_part}{due_part}")


class TodoManager(Widget):
    DEFAULT_CSS = """
    TodoManager { height: 100%; }

    #filter-bar {
        height: auto;
        background: $surface;
        padding: 0 1;
        border-bottom: solid $panel;
    }
    #status-row { height: 3; padding: 0 1; }
    #tag-row    { height: auto; min-height: 3; padding: 0 1; }

    .filter-label {
        color: $foreground 50%;
        width: 8;
        padding: 1 1 0 0;
    }

    .status-btn {
        min-width: 12;
        height: 1;
        border: none;
        background: $panel;
        margin-right: 1;
    }
    .status-btn.active {
        background: $primary 25%;
        color: $primary;
        text-style: bold;
    }

    .tag-btn {
        height: 1;
        border: none;
        margin-right: 1;
        background: $panel;
        color: $foreground 65%;
    }
    .tag-btn.sel {
        background: $accent 25%;
        color: $accent;
        text-style: bold;
    }

    #todo-scroll { height: 1fr; }

    ListView { background: transparent; height: auto; }
    ListItem { background: transparent; padding: 0; }
    ListItem:hover { background: $surface; }
    ListView:focus > ListItem.--highlight { background: $surface; }

    .todo-open      { color: $foreground; }
    .todo-done      { color: $success;    text-style: dim; }
    .todo-cancelled { color: $error;      text-style: dim strike; }

    #empty { padding: 2 4; color: $foreground 45%; }
    """

    BINDINGS = [
        ("a", "add_todo",       "Add"),
        ("d", "mark_done",      "Done/Undo"),
        ("e", "edit_todo",      "Edit"),
        ("x", "delete_todo",    "Delete"),
        ("s", "cycle_status",   "Status"),
        ("c", "clear_filters",  "Clear filters"),
    ]

    status_filter: reactive[str] = reactive("open")
    tag_filters: reactive[frozenset] = reactive(frozenset())

    def __init__(self, wm: WorkspaceManager) -> None:
        super().__init__()
        self._wm = wm

    # ------------------------------------------------------------------ data

    def _store(self):
        return self._wm.store()

    def _todos_with_tags(self) -> tuple[list[dict], list[str]]:
        store = self._store()
        todos = store.all("todos")
        tag_by_id = {t["id"]: t["name"] for t in store.all("tags")}
        tag_map: dict[str, list[str]] = {}
        for tt in store.all("todo_tags"):
            name = tag_by_id.get(tt.get("tag_id", ""))
            if name:
                tag_map.setdefault(tt["todo_id"], []).append(name)
        for t in todos:
            t["_tags"] = sorted(tag_map.get(t["id"], []))
        all_tags = sorted(set(tag_by_id.values()))
        return todos, all_tags

    def _filtered(self, todos: list[dict]) -> list[dict]:
        if self.status_filter != "all":
            todos = [t for t in todos if t.get("status") == self.status_filter]
        if self.tag_filters:
            todos = [t for t in todos if any(tg in t.get("_tags", []) for tg in self.tag_filters)]
        return sorted(todos, key=lambda t: (t.get("status") != "open", t.get("due_date") or "9999"))

    # ----------------------------------------------------------------- compose

    def compose(self) -> ComposeResult:
        todos, all_tags = self._todos_with_tags()
        visible = self._filtered(todos)

        with Vertical():
            with Vertical(id="filter-bar"):
                with Horizontal(id="status-row"):
                    yield Label("Status:", classes="filter-label")
                    for s in STATUS_CYCLE:
                        cls = "status-btn active" if s == self.status_filter else "status-btn"
                        yield Button(s.capitalize(), id=f"st-{s}", classes=cls)

                if all_tags:
                    with Horizontal(id="tag-row"):
                        yield Label("Tags:", classes="filter-label")
                        for tag in all_tags:
                            cls = "tag-btn sel" if tag in self.tag_filters else "tag-btn"
                            yield Button(tag, id=f"tg-{tag}", classes=cls)

            with VerticalScroll(id="todo-scroll"):
                if not visible:
                    yield Static(
                        "  No todos found.\n  [dim]Press [bold]a[/bold] to add one.[/dim]",
                        id="empty",
                    )
                else:
                    yield ListView(*[TodoListItem(t) for t in visible], id="lv")

    def watch_status_filter(self) -> None:
        self.refresh(recompose=True)

    def watch_tag_filters(self) -> None:
        self.refresh(recompose=True)

    # ----------------------------------------------------------------- events

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        if bid.startswith("st-"):
            self.status_filter = bid[3:]
        elif bid.startswith("tg-"):
            tag = bid[3:]
            cur = set(self.tag_filters)
            cur.discard(tag) if tag in cur else cur.add(tag)
            self.tag_filters = frozenset(cur)

    # ----------------------------------------------------------------- helpers

    def _selected(self) -> dict | None:
        try:
            lv = self.query_one("#lv", ListView)
            if lv.index is None:
                return None
            items = [c for c in lv.children if isinstance(c, TodoListItem)]
            return items[lv.index].todo if lv.index < len(items) else None
        except Exception:
            return None

    def _save_tags(self, todo_id: str, tag_names: list[str]) -> None:
        store = self._store()
        store.delete_where("todo_tags", todo_id=todo_id)
        for name in tag_names:
            existing = store.find("tags", name=name)
            tag = existing[0] if existing else store.insert("tags", {"id": str(uuid.uuid4()), "name": name})
            store.insert("todo_tags", {"todo_id": todo_id, "tag_id": tag["id"]})

    # ----------------------------------------------------------------- actions

    def action_add_todo(self) -> None:
        def cb(result: dict | None) -> None:
            if not result:
                return
            store = self._store()
            now = datetime.now().isoformat()
            rec = store.insert("todos", {
                "id": str(uuid.uuid4()),
                "text": result["text"],
                "status": "open",
                "due_date": result.get("due_date"),
                "created": now,
                "updated": now,
            })
            self._save_tags(rec["id"], result.get("tags", []))
            self.refresh(recompose=True)
            self.notify("Todo added.", timeout=1.5)

        self.app.push_screen(TodoFormScreen(), cb)

    def action_mark_done(self) -> None:
        todo = self._selected()
        if not todo:
            self.notify("Select a todo first.", severity="warning")
            return
        new_status = "open" if todo.get("status") == "done" else "done"
        self._store().update("todos", todo["id"], status=new_status, updated=datetime.now().isoformat())
        self.refresh(recompose=True)

    def action_edit_todo(self) -> None:
        todo = self._selected()
        if not todo:
            self.notify("Select a todo first.", severity="warning")
            return

        def cb(result: dict | None) -> None:
            if not result:
                return
            self._store().update(
                "todos", todo["id"],
                text=result["text"],
                due_date=result.get("due_date"),
                updated=datetime.now().isoformat(),
            )
            self._save_tags(todo["id"], result.get("tags", []))
            self.refresh(recompose=True)
            self.notify("Todo updated.", timeout=1.5)

        self.app.push_screen(TodoFormScreen(todo=todo, tag_names=todo.get("_tags", [])), cb)

    def action_delete_todo(self) -> None:
        todo = self._selected()
        if not todo:
            self.notify("Select a todo first.", severity="warning")
            return
        self._store().delete_with_relations("todos", todo["id"], [("todo_tags", "todo_id")])
        self.refresh(recompose=True)
        self.notify("Todo deleted.", timeout=1.5)

    def action_cycle_status(self) -> None:
        idx = STATUS_CYCLE.index(self.status_filter)
        self.status_filter = STATUS_CYCLE[(idx + 1) % len(STATUS_CYCLE)]

    def action_clear_filters(self) -> None:
        self.tag_filters = frozenset()
        self.status_filter = "open"
