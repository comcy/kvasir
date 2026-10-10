"""Tabellenansicht von `kvasir status`. Eine Spalte = ein Eintrag in COLUMNS (Name, Zelle aus ItemStatus)."""
from __future__ import annotations

from dataclasses import dataclass

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
    out = schedule_lines(s.item.schedule)
    return out + [f"! {x}" for x in (s.hint, *s.notices) if x]


def order(items):
    """Geschwister: Vorgänger vor Nachfolger, dann Prio (ohne zuletzt), dann Nummer. Zyklen brechen bei der kleinsten Nummer."""
    left = sorted(items, key=lambda s: (s.item.prio or 9, s.item.number))
    nums, done, out = {s.item.number for s in left}, set(), []
    while left:
        ready = [s for s in left if all(b.number in done or b.number not in nums for b in s.blocked_by)]
        out.append(nxt := (ready or left)[0])
        done.add(nxt.item.number)
        left.remove(nxt)
    return out


@dataclass(frozen=True)
class Row:
    s: object  # ItemStatus
    prefix: str  # Baumzweig vor dem Titel (`│  └─ `)
    width: int  # Stellen der längsten Ticketnummer
    shown: frozenset  # {(repo, nummer)} des gezeigten Features
    repo: str


def rows(st) -> list[Row]:
    """Baum in Anzeigereihenfolge (Tiefensuche, je Ebene `order`)."""
    kids: dict = {}
    for s in st.sub_issues:
        kids.setdefault(s.item.parent, []).append(s)
    every = [st.issue, *st.sub_issues]
    shown = frozenset((st.repo, s.item.number) for s in every)
    width = len(str(max(s.item.number for s in every)))
    out: list[Row] = []

    def walk(s, lead, branch, cont):
        out.append(Row(s, lead + branch, width, shown, st.repo))
        ks = order(kids.get(s.item.number, []))
        for i, k in enumerate(ks):
            last = i == len(ks) - 1
            walk(k, lead + cont, "└─ " if last else "├─ ", "   " if last else "│  ")

    walk(st.issue, "", "", "")
    return out


def _title(r):
    return Text(r.s.item.title, no_wrap=True, overflow="ellipsis")


def _status(r):
    s = r.s
    if s.status == "open" and s.source == "fact" and not s.children:
        return Text("▶ startklar", "green", no_wrap=True)
    return Text(f"{SYMBOLS.get(s.status, '?')} {status_name(s)}", COLORS.get(s.status, ""), no_wrap=True)


def _prev(r):
    t = Text(no_wrap=True)
    for i, b in enumerate(r.s.blocked_by):
        t.append(", " if i else "")
        t.append(("↗ " if (b.repo, b.number) not in r.shown else "") + (f"#{b.number}" if b.repo == r.repo else f"{b.repo}#{b.number}"))
        t.append(" ✓" if b.state == "closed" else " ○ offen", "" if b.state == "closed" else "red")
    return t


# Spalten: (Überschrift, Zelle aus Row). Neue Spalte = ein Eintrag; Titel ist die einzige, die gekürzt wird.
TICKET_TITLE = {
    "tree": (("Ticket\u00a0\u00a0Titel", lambda r: Text(f"#{r.s.item.number}".ljust(r.width + 1) + "  " + r.prefix + r.s.item.title,
                                              no_wrap=True, overflow="ellipsis")),),
    "split": (("Ticket", lambda r: Text(f"#{r.s.item.number}", no_wrap=True)), ("Titel", _title)),
}
COLUMNS = (
    ("Prio", lambda r: Text(f"P{r.s.item.prio}" if r.s.item.prio else "–", no_wrap=True)),
    ("Status", _status),
    ("Fortschritt", lambda r: Text(progress(r.s), no_wrap=True)),
    ("Vorher", _prev),
    ("Nachher", lambda r: Text(", ".join(f"#{n}" for n in r.s.succ), no_wrap=True)),
)
FLEX = ("Titel", "Ticket\u00a0\u00a0Titel")  # NBSP: Kopf bricht nicht um  # die gekürzte Spalte


def render(st, layout: str = "tree") -> str:
    """Tabelle (Feature zuerst, dann Sub-Issues als Baum) und darunter der Hinweisblock. Breite/Farbe vom Terminal (COLUMNS, NO_COLOR)."""
    table = Table(box=None, padding=(0, 2, 0, 0), pad_edge=False)
    cols = (*TICKET_TITLE[layout], *COLUMNS)
    for name, _ in cols:
        table.add_column(name, justify="right" if name == "Ticket" else "left",
                         no_wrap=name not in FLEX, overflow="ellipsis" if name in FLEX else "fold",
                         min_width=14 if name in FLEX else None)
    rs = rows(st)
    for r in rs:
        table.add_row(*(cell(r) for _, cell in cols))
    notes = [(r.s.item.number, n) for r in rs for n in _notes(r.s)]
    console = Console(highlight=False)
    with console.capture() as cap:
        console.print(table)
        if notes:
            console.print("\nHinweise")
            for number, n in notes:
                console.print(Text(f"  #{number}  {n}"))
    return cap.get().rstrip("\n")
