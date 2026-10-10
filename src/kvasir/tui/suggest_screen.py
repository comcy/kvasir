"""Modal LLM suggestion (keys `c` commit message, `t` note): editable text, Enter confirms, Esc cancels."""
from __future__ import annotations

import threading
from pathlib import Path
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Static

from kvasir import llm, suggest
from kvasir.tui.summary_screen import _BOX, ConfirmScreen


class SuggestScreen(ModalScreen["str | None"]):
    """Dismisses with the confirmed text (kind "note"), the committed message (kind "commit") or None."""
    DEFAULT_CSS = f"SuggestScreen {{ align: center middle; }} SuggestScreen > Vertical {{ {_BOX} }}"
    BINDINGS: ClassVar[list[Binding]] = [Binding("escape", "close", "Abbrechen")]

    def __init__(self, kind: str, url: str, branch: str, path: Path, cfg: llm.LlmConfig) -> None:
        super().__init__()
        self.kind, self.url, self.branch, self.path, self.cfg = kind, url, branch, path, cfg
        self._discard = False
        self._armed = False  # commit: first Enter shows the question, second Enter commits
        self._busy = False

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("", id="status", markup=False)
            yield Input(id="text", disabled=True)

    def on_mount(self) -> None:
        what = "Commit-Message" if self.kind == "commit" else "Notiz"
        self.query_one(Vertical).border_title = f"{what} vorschlagen · {self.branch}"
        if not llm.needs_confirmation(self.cfg):
            return self._start()

        def done(ok: bool | None) -> None:
            if ok:
                llm.confirm(self.cfg)
                self._start()
            else:
                self.dismiss(None)

        self.app.push_screen(ConfirmScreen(llm.target(self.cfg)), done)

    def _say(self, s: str) -> None:
        self.query_one("#status", Static).update(s)

    def _start(self) -> None:
        self._say("Erzeuge Vorschlag ...")

        def work() -> None:
            if self.kind == "commit":
                diff = suggest.staged_diff(self.path)
                msgs = suggest.commit_messages(diff) if diff.strip() else None
                empty = "Nichts gestaged (git add), kein Vorschlag."
            else:
                msgs = suggest.note_messages(self.url, self.branch, suggest.head_diff(self.path))
                empty = "Kein Tageslog und kein Diff für diesen Branch, kein Vorschlag."
            res = llm.complete(msgs, self.cfg, self.url) if msgs else None
            self._post(self._suggested, res, empty)

        # plain daemon thread: a Textual worker would make closing the screen wait for the LLM
        threading.Thread(target=work, daemon=True).start()

    def _post(self, fn, *args) -> None:
        if not self._discard:
            try:
                self.app.call_from_thread(fn, *args)
            except RuntimeError:  # app already gone
                pass

    def _suggested(self, res, empty: str) -> None:
        if self._discard:
            return
        if res is None:
            return self._say(empty + "\nEsc = schließen.")
        if not res.ok:
            return self._say(f"Fehler: {res.error.message}\nEsc = schließen.")
        text = suggest.one_line(res.data) if self.kind == "commit" else res.data.strip()
        inp = self.query_one("#text", Input)
        inp.disabled, inp.value = False, text
        inp.focus()
        inp.cursor_position = len(text)
        self._armed = False
        self._say("Bearbeiten, Enter = " + ("committen (nach Rückfrage)" if self.kind == "commit" else "als Notiz speichern")
                  + ", Esc = abbrechen.")

    def on_input_changed(self, ev: Input.Changed) -> None:
        self._armed = False

    def on_input_submitted(self, ev: Input.Submitted) -> None:
        text = ev.value.strip()
        if not text or self._busy:
            return
        if self.kind == "note":
            self.dismiss(text)
            return
        if not self._armed:
            self._armed = True
            return self._say(f'git commit -m "{text}" in {self.path.name}?\nEnter = jetzt committen, Esc = abbrechen.')
        self._busy = True
        self._say("Committe ...")

        def work() -> None:
            self._post(self._committed, text, *suggest.commit(self.path, text))

        threading.Thread(target=work, daemon=True).start()

    def _committed(self, text: str, ok: bool, out: str) -> None:
        self._busy = False
        if ok:
            self.dismiss(text)
        else:
            self._armed = False
            self._say(f"Commit fehlgeschlagen:\n{out[-600:]}\nEnter = erneut versuchen, Esc = schließen.")

    def action_close(self) -> None:
        self._discard = True
        self.dismiss(None)
