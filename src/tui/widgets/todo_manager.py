"""Full Todo manager: list with tag chips, status filter, CRUD via modals."""
from __future__ import annotations

import uuid
from datetime import date, datetime

from textual.app import ComposeResult
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Label, ListItem, ListView, Static
from textual.containers import Horizontal, Vertical, VerticalScroll

from src.workspace.manager import WorkspaceManager
from src.tui.screens.todo_form import TodoFormScreen

STATUS_ICON = {"open": "○", "done": "●", "cancelled": "⊘"}
STATUS_CLASS = {"open": "todo-open", "done": "todo-done", "cancelled": "todo-cancelled"}
STATUS_CYCLE = ["all", "open", "done", "cancelled"]


class FilterPill(Static):
    """Compact single-row toggle pill — fires FilterPill.Pressed on click."""

    class Pressed(Message):
        def __init__(self, pill: "FilterPill") -> None:
            super().__init__()
            self.pill = pill

    def __init__(self, label: str, pill_id: str = "", classes: str = "") -> None:
        super().__init__(label, id=pill_id, classes=classes)

    def on_click(self) -> None:
        self.post_message(FilterPill.Pressed(self))


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
        assignee = self.todo.get("assignee") or ""
        css = STATUS_CLASS.get(status, "")

        overdue = (
            status == "open"
            and bool(due)
            and due < date.today().isoformat()
        )

        tags_part = "  " + " ".join(f"[dim][{t}][/dim]" for t in tags) if tags else ""
        if due:
            due_part = f"  [bold red]{due} ![/bold red]" if overdue else f"  [dim]{due}[/dim]"
        else:
            due_part = ""
        assign_part = f"  [dim][→ @{assignee}][/dim]" if assignee else ""
        yield Label(f"  {icon}  [{css}]{text}[/{css}]{assign_part}{tags_part}{due_part}")


class TodoManager(Widget):
    DEFAULT_CSS = """
    TodoManager { height: 100%; }

    #filter-bar {
        height: auto;
        background: $surface;
        padding: 1 1 0 1;
        border-bottom: solid $panel;
    }
    #status-row {
        height: 1;
        align: left middle;
        margin-bottom: 1;
    }
    #and-row {
        height: 1;
        align: left middle;
        margin-bottom: 1;
    }

    .filter-label {
        color: $foreground 38%;
        width: 8;
        content-align: left middle;
    }
    .and-label {
        color: $accent 80%;
        text-style: bold;
        width: 8;
    }

    /* Status pills */
    FilterPill {
        height: 1;
        width: auto;
        padding: 0 1;
        margin-right: 1;
        background: $panel;
        color: $foreground 55%;
    }
    FilterPill:hover { background: $panel-lighten-1; color: $foreground; }
    FilterPill.active {
        background: $primary 22%;
        color: $primary;
        text-style: bold;
    }

    /* Tag pills */
    FilterPill.tag-pill {
        background: $surface;
        color: $foreground 40%;
        padding: 0 1;
    }
    FilterPill.tag-pill:hover { background: $surface-lighten-1; color: $foreground 70%; }
    FilterPill.tag-pill.active {
        background: $accent 20%;
        color: $accent;
        text-style: bold;
    }

    /* Delegated AND pill */
    FilterPill.delegated-pill {
        background: $surface;
        color: $foreground 40%;
        margin-left: 1;
    }
    FilterPill.delegated-pill:hover { background: $surface-lighten-1; color: $foreground 70%; }
    FilterPill.delegated-pill.active {
        background: $warning 18%;
        color: $warning;
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
        ("a", "add_todo",          "Add"),
        ("d", "mark_done",         "Done/Undo"),
        ("e", "edit_todo",         "Edit"),
        ("x", "delete_todo",       "Delete"),
        ("s", "cycle_status",      "Status"),
        ("g", "toggle_delegated",  "Delegated"),
        ("c", "clear_filters",     "Clear filters"),
    ]

    status_filter: reactive[str] = reactive("open")
    tag_filters: reactive[frozenset] = reactive(frozenset())
    delegated_only: reactive[bool] = reactive(False)

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
        if self.delegated_only:
            todos = [t for t in todos if t.get("assignee")]
        return sorted(todos, key=lambda t: (t.get("status") != "open", t.get("due_date") or "9999"))

    # ----------------------------------------------------------------- compose

    def compose(self) -> ComposeResult:
        todos, all_tags = self._todos_with_tags()
        visible = self._filtered(todos)

        with Vertical():
            with Vertical(id="filter-bar"):
                # Row 1: status radio pills
                with Horizontal(id="status-row"):
                    yield Label("Status", classes="filter-label")
                    for s in STATUS_CYCLE:
                        cls = "active" if s == self.status_filter else ""
                        yield FilterPill(s.capitalize(), pill_id=f"st-{s}", classes=cls)

                # Row 2: AND filters — delegated + tags
                with Horizontal(id="and-row"):
                    yield Label("AND", classes="filter-label and-label")
                    del_cls = "delegated-pill active" if self.delegated_only else "delegated-pill"
                    yield FilterPill("↗ delegated", pill_id="btn-delegated", classes=del_cls)
                    for tag in all_tags:
                        cls = "tag-pill active" if tag in self.tag_filters else "tag-pill"
                        yield FilterPill(f"#{tag}", pill_id=f"tg-{tag}", classes=cls)

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

    def watch_delegated_only(self) -> None:
        self.refresh(recompose=True)

    # ----------------------------------------------------------------- events

    def on_filter_pill_pressed(self, event: FilterPill.Pressed) -> None:
        pid = event.pill.id or ""
        if pid.startswith("st-"):
            self.status_filter = pid[3:]
        elif pid.startswith("tg-"):
            tag = pid[3:]
            cur = set(self.tag_filters)
            cur.discard(tag) if tag in cur else cur.add(tag)
            self.tag_filters = frozenset(cur)
        elif pid == "btn-delegated":
            self.delegated_only = not self.delegated_only

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
                "assignee": result.get("assignee"),
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
                assignee=result.get("assignee"),
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

    def action_toggle_delegated(self) -> None:
        self.delegated_only = not self.delegated_only

    def action_clear_filters(self) -> None:
        self.tag_filters = frozenset()
        self.status_filter = "open"
        self.delegated_only = False
