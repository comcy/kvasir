from __future__ import annotations

from textual.app import ComposeResult
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Label, ListItem, ListView, Static
from textual.containers import Vertical


STATUS_ICON = {"open": "○", "done": "●", "cancelled": "⊘"}
STATUS_CLASS = {"open": "todo-open", "done": "todo-done", "cancelled": "todo-cancelled"}


class TodoItem(ListItem):
    def __init__(self, todo: dict) -> None:
        super().__init__()
        self.todo = todo

    def compose(self) -> ComposeResult:
        status = self.todo.get("status", "open")
        icon = STATUS_ICON.get(status, "?")
        text = self.todo.get("text", "")
        due = self.todo.get("due_date") or ""
        due_str = f"  [dim]{due}[/dim]" if due else ""
        css_class = STATUS_CLASS.get(status, "")
        yield Label(f"{icon}  {text}{due_str}", classes=css_class)


class TodoPanel(Widget):
    BORDER_TITLE = "TODOs"

    todos: reactive[list[dict]] = reactive([], layout=True)

    def __init__(self, todos: list[dict], **kwargs) -> None:
        super().__init__(**kwargs)
        self.todos = todos

    def compose(self) -> ComposeResult:
        open_todos = [t for t in self.todos if t.get("status") == "open"]
        done_todos = [t for t in self.todos if t.get("status") == "done"]

        with Vertical():
            if not self.todos:
                yield Static("  [dim]No todos yet.[/dim]\n  devtrack todo add \"...\"", classes="empty-hint")
                return

            yield Static(
                f"  [bold]Open[/bold] [dim]({len(open_todos)})[/dim]",
                classes="panel-section-header",
            )
            if open_todos:
                yield ListView(
                    *[TodoItem(t) for t in open_todos],
                    id="todo-open-list",
                )
            else:
                yield Static("  [dim]All done![/dim]", classes="empty-hint")

            if done_todos:
                yield Static(
                    f"\n  [bold]Done[/bold] [dim]({len(done_todos)})[/dim]",
                    classes="panel-section-header",
                )
                yield ListView(
                    *[TodoItem(t) for t in done_todos[-5:]],
                    id="todo-done-list",
                )

    def watch_todos(self) -> None:
        self.refresh(recompose=True)
