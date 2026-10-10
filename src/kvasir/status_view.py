"""Tabellenansicht von `kvasir status`. Eine Spalte = ein Eintrag in COLUMNS (Name, Zelle aus ItemStatus)."""
from __future__ import annotations

from rich.console import Console
from rich.table import Table
from rich.text import Text

LABELS = {"done": "erledigt", "dropped": "verworfen", "blocked": "blockiert", "in_review": "in Review",
          "in_progress": "in Arbeit", "open": "offen"}
SYMBOLS = {"done": "✓", "dropped": "✗", "blocked": "⛔", "in_review": "◐", "in_progress": "▶", "open": "○"}
COLORS = {"done": "green", "dropped": "dim", "blocked": "red", "in_review": "yellow", "in_progress": "cyan"}


def status_name(s) -> str:
    return LABELS.get(s.status, s.status) + (" (laut Label)" if s.source == "label" else "")


def progress(s) -> str:
    """`●●●○○ Abnahme`: erledigte Schritte gefüllt, dahinter der aktuelle Schritt; alle erledigt = `fertig`."""
    steps = s.stepper.steps if s.stepper else ()
    if not steps:
        return ""
    cur = next((x.name for x in steps if x.state == "current"), "fertig")
    return "●" * sum(x.state == "done" for x in steps) + "○" * sum(x.state != "done" for x in steps) + " " + cur


def schedule_lines(sc) -> list[str]:
    lines = []
    if sc.deadlines:
        lines.append("Frist: " + ", ".join(f"{d.date} ({d.label})" for d in sc.deadlines))
    if sc.planned_from:
        lines.append(f"Geplant: {sc.planned_from} – {sc.planned_to}")
    return lines


def _notes(s) -> list[str]:
    out = []
    if s.blocked_by:
        out.append("blockiert von: " + ", ".join(f"#{b.number} ({b.state})" for b in s.blocked_by))
    out += schedule_lines(s.item.schedule)
    out += [f"! {x}" for x in (s.hint, *s.notices) if x]
    if s.stepper and s.stepper.previous:
        out.append("Vorgänger: " + ", ".join(f"#{n}" for n in s.stepper.previous))
    return out


# Spalten: (Überschrift, Zelle). Neue Spalte = ein Eintrag; Titel ist die einzige, die gekürzt wird.
COLUMNS = (
    ("Ticket", lambda s: Text(f"#{s.item.number}", no_wrap=True)),
    ("Titel", lambda s: Text(s.item.title, no_wrap=True, overflow="ellipsis")),
    ("Status", lambda s: Text(f"{SYMBOLS.get(s.status, '?')} {status_name(s)}", COLORS.get(s.status, ""), no_wrap=True)),
    ("Fortschritt", lambda s: Text(progress(s), no_wrap=True)),
)


def render(st) -> str:
    """Tabelle (Feature zuerst, dann Sub-Issues) und darunter der Hinweisblock. Breite/Farbe vom Terminal (COLUMNS, NO_COLOR)."""
    table = Table(box=None, padding=(0, 2, 0, 0), pad_edge=False)
    for name, _ in COLUMNS:
        table.add_column(name, justify="right" if name == "Ticket" else "left",
                         no_wrap=name != "Titel", overflow="ellipsis" if name == "Titel" else "fold",
                         min_width=8 if name == "Titel" else None)
    items = [st.issue, *st.sub_issues]
    for s in items:
        table.add_row(*(cell(s) for _, cell in COLUMNS))
    notes = [(s.item.number, n) for s in items for n in _notes(s)]
    console = Console(highlight=False)
    with console.capture() as cap:
        console.print(table)
        if notes:
            console.print("\nHinweise")
            for number, n in notes:
                console.print(Text(f"  #{number}  {n}"))
    return cap.get().rstrip("\n")
