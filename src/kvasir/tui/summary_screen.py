"""Modal AI summary of a Repo (key `s`) plus the data-leaves-the-machine confirmation."""
from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Static

from kvasir import llm, summary
from kvasir.worktrees import RepoView

_BOX = ("width: 80%; min-width: 30; height: auto; max-height: 80%; border: round $accent; "
        "border-title-color: $accent; border-title-style: bold; padding: 1 2; background: $surface;")


class ConfirmScreen(ModalScreen[bool]):
    """Enter = yes, Esc = no."""
    DEFAULT_CSS = f"ConfirmScreen {{ align: center middle; }} ConfirmScreen > Vertical {{ {_BOX} }}"
    BINDINGS: ClassVar[list[Binding]] = [
        Binding("enter", "yes", "Senden"), Binding("escape", "no", "Abbrechen")]

    def __init__(self, target: str) -> None:
        super().__init__()
        self.target = target

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(f"Daten gehen an {self.target}.\nEnter = senden und merken, Esc = abbrechen.")

    def action_yes(self) -> None:
        self.dismiss(True)

    def action_no(self) -> None:
        self.dismiss(False)


class SummaryScreen(ModalScreen[None]):
    DEFAULT_CSS = f"SummaryScreen {{ align: center middle; }} SummaryScreen > Vertical {{ {_BOX} }}"
    BINDINGS: ClassVar[list[Binding]] = [
        Binding("g", "generate", "Neu erzeugen"), Binding("escape", "close", "Schließen")]

    def __init__(self, url: str, root: Path, view: RepoView | None, cfg: llm.LlmConfig) -> None:
        super().__init__()
        self.url, self.root, self.view, self.cfg = url, root, view, cfg
        self._busy = False

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("", id="summary-text")

    def on_mount(self) -> None:
        self.query_one(Vertical).border_title = f"Zusammenfassung · {self.url}"
        if summary.cached(self.url) is None:
            self._start(force=False)  # the `s` key press is the trigger
        else:
            self._show_cached()

    def _text(self, s: str) -> None:
        self.query_one("#summary-text", Static).update(s)

    @work(thread=True)
    def _show_cached(self) -> None:
        e, stale = summary.cached(self.url), summary.is_stale(self.url, self.root)
        self.app.call_from_thread(self._show, e, stale)

    def _show(self, e: summary.Entry | None, stale: bool) -> None:
        if e is None:
            return
        mark = "  [veraltet: HEAD hat sich geändert, g = neu erzeugen]" if stale else ""
        self._text(f"{e.text}\n\nStand: {e.ts.astimezone():%Y-%m-%d %H:%M}{mark}")

    def action_generate(self) -> None:
        self._start(force=True)

    def _start(self, force: bool) -> None:
        if self._busy:
            return
        if llm.needs_confirmation(self.cfg):
            def done(ok: bool | None) -> None:
                if ok:
                    llm.confirm(self.cfg)
                    self._run(force)
                else:
                    self._text("Abgebrochen (nicht bestätigt). g = erneut versuchen.")
            self.app.push_screen(ConfirmScreen(llm.target(self.cfg)), done)
        else:
            self._run(force)

    def _run(self, force: bool) -> None:
        self._busy = True
        self._text("Erzeuge Zusammenfassung ...")
        self._generate(force)

    @work(thread=True)
    def _generate(self, force: bool) -> None:
        res = summary.generate(self.url, self.root, self.view, self.cfg, force)
        self.app.call_from_thread(self._done, res)

    def _done(self, res) -> None:
        self._busy = False
        if res.ok:
            self._show(res.data, False)
        else:
            self._text(f"Fehler: {res.error.message}")

    def action_close(self) -> None:
        self.dismiss(None)
