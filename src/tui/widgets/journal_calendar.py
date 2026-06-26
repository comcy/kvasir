"""Interactive month-calendar widget for journal navigation."""
from __future__ import annotations

import calendar as _cal
from datetime import date, timedelta

from rich.text import Text
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget


class JournalCalendar(Widget, can_focus=True):
    """
    Month calendar — arrow-key navigation, highlights days with existing notes.

    Messages posted:
      JournalCalendar.CursorChanged  — cursor moved (preview update)
      JournalCalendar.Activated      — user wants to open/create a note (Enter/W/M/Y)
    """

    DEFAULT_CSS = """
    JournalCalendar {
        height: auto;
        width: 22;
        padding: 0;
    }
    JournalCalendar:focus {
        border: none;
        outline: none;
    }
    """

    BINDINGS = [
        ("left",  "prev_day",   "←"),
        ("right", "next_day",   "→"),
        ("up",    "prev_week",  "↑"),
        ("down",  "next_week",  "↓"),
        ("[",     "prev_month", "Prev month"),
        ("]",     "next_month", "Next month"),
        ("t",     "go_today",   "Today"),
        ("enter", "open_day",   "Day note"),
        ("W",     "open_week",  "Week note"),
        ("M",     "open_month", "Month note"),
        ("Y",     "open_year",  "Year note"),
    ]

    cursor: reactive[date] = reactive(date.today)

    # ---------------------------------------------------------------- messages

    class CursorChanged(Message):
        def __init__(self, d: date) -> None:
            super().__init__()
            self.date = d

    class Activated(Message):
        """Open or create a journal note."""
        def __init__(self, d: date, note_type: str) -> None:
            super().__init__()
            self.date = d
            self.note_type = note_type  # "day" | "week" | "month" | "year"

    # --------------------------------------------------------------- init

    def __init__(self, entry_dates: set[date] | None = None) -> None:
        super().__init__()
        self._entry_dates: set[date] = entry_dates or set()

    def update_entries(self, entry_dates: set[date]) -> None:
        self._entry_dates = entry_dates
        self.refresh()

    # --------------------------------------------------------------- render

    def render(self) -> Text:
        d = self.cursor
        today = date.today()
        year, month = d.year, d.month

        text = Text(no_wrap=True)

        # Header row
        label = d.strftime("%B %Y")
        text.append(f" {label}\n", style="bold")

        # Weekday header
        text.append(" Mo Tu We Th Fr Sa Su\n", style="dim")

        first_wd = date(year, month, 1).weekday()  # Mon=0
        month_len = _cal.monthrange(year, month)[1]

        for row in range(6):
            for wd in range(7):
                day_n = row * 7 + wd - first_wd + 1
                if day_n < 1 or day_n > month_len:
                    text.append("   ")
                    continue
                cur_date = date(year, month, day_n)
                s = f"{day_n:2d}"
                is_cursor  = cur_date == d
                is_today   = cur_date == today
                has_entry  = cur_date in self._entry_dates

                text.append(" ")
                if is_cursor and is_today:
                    text.append(s, style="reverse bold")
                elif is_cursor:
                    text.append(s, style="reverse")
                elif is_today:
                    text.append(s, style="bold")
                elif has_entry:
                    text.append(s, style="green")
                else:
                    text.append(s, style="dim")

            text.append("\n")
            if row * 7 + 6 - first_wd + 1 >= month_len:
                break

        return text

    # --------------------------------------------------------------- reactive

    def watch_cursor(self, new_date: date) -> None:
        self.post_message(self.CursorChanged(new_date))
        self.refresh()

    # ------------------------------------------------------------ navigation

    def _clamp(self, year: int, month: int) -> date:
        max_day = _cal.monthrange(year, month)[1]
        return date(year, month, min(self.cursor.day, max_day))

    def action_prev_day(self)  -> None: self.cursor -= timedelta(days=1)
    def action_next_day(self)  -> None: self.cursor += timedelta(days=1)
    def action_prev_week(self) -> None: self.cursor -= timedelta(weeks=1)
    def action_next_week(self) -> None: self.cursor += timedelta(weeks=1)
    def action_go_today(self)  -> None: self.cursor = date.today()

    def action_prev_month(self) -> None:
        d = self.cursor
        y, m = (d.year - 1, 12) if d.month == 1 else (d.year, d.month - 1)
        self.cursor = self._clamp(y, m)

    def action_next_month(self) -> None:
        d = self.cursor
        y, m = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
        self.cursor = self._clamp(y, m)

    def action_open_day(self)   -> None: self.post_message(self.Activated(self.cursor, "day"))
    def action_open_week(self)  -> None: self.post_message(self.Activated(self.cursor, "week"))
    def action_open_month(self) -> None: self.post_message(self.Activated(self.cursor, "month"))
    def action_open_year(self)  -> None: self.post_message(self.Activated(self.cursor, "year"))
