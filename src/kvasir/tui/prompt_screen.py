"""Modal prompt window (key `a`): chat with repo/notes/day-log context. History lives only in this screen."""
from __future__ import annotations

import threading
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Input, Static

from kvasir import ask, llm


class PromptScreen(ModalScreen[None]):
    DEFAULT_CSS = """
    PromptScreen { align: center middle; }
    PromptScreen > Vertical { width: 90%; height: 90%; border: round $accent; border-title-color: $accent; border-title-style: bold; padding: 0 1; background: $surface; }
    PromptScreen VerticalScroll { height: 1fr; }
    """
    BINDINGS: ClassVar[list[Binding]] = [Binding("escape", "close", "Close")]

    def __init__(self) -> None:
        super().__init__()
        self.history: list[dict[str, str]] = []
        self._pending: str | None = None  # question waiting for the confirmation of a remote target
        self._discard = False
        self.lines: list[str] = []

    def compose(self) -> ComposeResult:
        with Vertical():
            with VerticalScroll():
                yield Static("", id="log", markup=False)
            yield Input(placeholder="ask (enter to send, esc to close)")

    def on_mount(self) -> None:
        self.query_one(Vertical).border_title = "Ask"
        self.query_one(Input).focus()

    def _say(self, text: str) -> None:
        self.lines.append(text)
        self.query_one("#log", Static).update("\n".join(self.lines))
        self.query_one(VerticalScroll).scroll_end(animate=False)

    def on_input_submitted(self, ev: Input.Submitted) -> None:
        text, ev.input.value = ev.value.strip(), ""
        try:
            cfg = llm.load()
        except (OSError, ValueError, TypeError, AttributeError) as e:
            return self._say(f"! [llm] invalid: {e}")
        if cfg is None:
            return self._say("! No [llm] configured in local.toml.")
        if self._pending is not None:  # confirmation dialog: Enter = yes
            q, self._pending = self._pending, None
            llm.confirm(cfg)
            return self._ask(q, cfg)
        if not text:
            return
        if llm.needs_confirmation(cfg):
            self._pending = text
            return self._say(f"! Data goes to {llm.target(cfg)}. Enter = confirm and remember, Esc = cancel.")
        self._ask(text, cfg)

    def _ask(self, question: str, cfg: llm.LlmConfig) -> None:
        self._say(f"> {question}")
        self._say("... searching and asking")

        def work() -> None:
            res = llm.complete(ask.messages(question, self.history), cfg)
            if not self._discard:  # Esc discards the answer
                try:
                    self.app.call_from_thread(self._answer, question, res)
                except RuntimeError:  # app already gone
                    pass

        # plain daemon thread: a Textual worker would make closing the screen wait for the LLM
        threading.Thread(target=work, daemon=True).start()

    def _answer(self, question: str, res) -> None:
        if self._discard:
            return
        if not res.ok:
            return self._say(f"! {res.error.message}")
        self.history += [{"role": "user", "content": question}, {"role": "assistant", "content": res.data}]
        self._say(res.data)

    def action_close(self) -> None:
        self._discard = True
        self.dismiss(None)
