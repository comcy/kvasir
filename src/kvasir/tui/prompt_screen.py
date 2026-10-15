"""Modal prompt window (key `a`): chat with repo/notes/day-log context. History lives only in this screen."""
from __future__ import annotations

import threading
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Collapsible, Input, Static

from kvasir import ask, llm


class _State:
    """Conversation of the Ask dialog; kept on the app so reopening restores it."""

    def __init__(self) -> None:
        self.history: list[dict[str, str]] = []
        self.log: list[tuple[str, str, str]] = []  # (kind "say"|"ctx", text, css classes)
        self.used: int | None = None  # tokens of the last answer
        self.limit: int | None = None  # n_ctx of the server, fetched once
        self.limit_known = False
        self.inflight: int | None = None
        self.keep = False  # [llm] keep_history of the last request


class PromptScreen(ModalScreen[None]):
    DEFAULT_CSS = """
    PromptScreen { align: center middle; }
    PromptScreen > Vertical { width: 90%; height: 90%; border: round $accent; border-title-color: $accent; border-title-style: bold; padding: 0 1; background: $surface; }
    PromptScreen VerticalScroll { height: 1fr; }
    PromptScreen .q { background: $primary 30%; padding: 0 1; margin-top: 1; text-style: bold; }
    PromptScreen .ctx { color: $text-muted; text-style: italic; }
    """
    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "close", "Close"), Binding("ctrl+n", "reset", "Reset"),
    ]

    def __init__(self) -> None:
        super().__init__()
        # conversation lives on the app: survives closing/reopening the dialog (memory only)
        self.state = _State()  # replaced by the app's in on_mount
        self._pending: str | None = None  # question waiting for the confirmation of a remote target
        self._discard = False
        self._gen = 0  # bumped by reset: late answers of an older conversation are dropped

    @property
    def history(self) -> list[dict[str, str]]:
        return self.state.history

    @history.setter
    def history(self, v: list[dict[str, str]]) -> None:
        self.state.history = v

    @property
    def lines(self) -> list[str]:
        return [e[1] for e in self.state.log if e[0] == "say"]

    def compose(self) -> ComposeResult:
        with Vertical():
            yield VerticalScroll()
            yield Input(placeholder="ask (enter to send, ctrl+n reset, esc to close)")

    def on_mount(self) -> None:
        if "ask_state" not in self.app.__dict__:  # first open of this TUI start: restore the saved one
            try:
                cfg = llm.load()
            except (OSError, ValueError, TypeError, AttributeError):
                cfg = None
            if cfg and cfg.keep_history:
                self.state.history, self.state.log, self.state.used = ask.load_conversation()
        self.state = self.app.__dict__.setdefault("ask_state", self.state)
        self.state.inflight = None
        box = self.query_one(VerticalScroll)
        for e in self.state.log:
            box.mount(self._widget(*e))
        box.scroll_end(animate=False)
        self._title()
        self.query_one(Input).focus()

    @staticmethod
    def _widget(kind: str, text: str, classes: str = ""):
        if kind == "ctx":
            return Collapsible(Static(text, markup=False, classes="ctx"), collapsed=True,
                               title=f"Kontext gesendet · {len(text)} Zeichen")
        return Static(text, markup=False, classes=classes)

    def _say(self, text: str, classes: str = "") -> None:
        self.state.log.append(("say", text, classes))
        box = self.query_one(VerticalScroll)
        box.mount(self._widget("say", text, classes))
        box.scroll_end(animate=False)

    def _title(self) -> None:
        def k(n: int) -> str:
            return f"{n / 1000:.1f}k" if n >= 1000 else str(n)

        t = "Ask"
        if self.state.used is not None:
            t += f" · {k(self.state.used)}" + (f" / {k(self.state.limit)}" if self.state.limit else "") + " tokens"
        self.query_one(Vertical).border_title = t

    def action_reset(self) -> None:
        self._gen += 1
        self._pending = None
        self.state.history, self.state.log, self.state.used, self.state.inflight = [], [], None, None
        ask.clear_conversation()
        self.query_one(VerticalScroll).remove_children()
        self._title()

    def _show_ctx(self, system: str, at: int, dropped: int, gen: int) -> None:
        if self._discard or gen != self._gen:
            return
        box = self.query_one(VerticalScroll)
        self.state.log.insert(at, ("ctx", system, ""))
        box.mount(self._widget("ctx", system), before=box.children[at])
        if dropped:
            self._say("! ältere Runden verworfen")

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
        st = self.state
        st.keep = cfg.keep_history
        st.inflight = len(st.log)  # log index of the question; dropped again when closed unanswered
        self._say(f"> {question}", "q")
        self._say(ask.WAIT)
        gen = self._gen
        at = st.inflight + 1  # the Collapsible goes between question and wait line

        def work() -> None:
            if not st.limit_known:
                st.limit, st.limit_known = llm.n_ctx(cfg), True
            msgs = ask.messages(question, self.history)
            dropped = 0
            if st.limit:
                msgs, dropped = ask.fit(msgs, st.limit)
            if self._discard or gen != self._gen:
                return
            try:
                self.app.call_from_thread(self._show_ctx, msgs[0]["content"], at, dropped, gen)
            except RuntimeError:
                return
            res = llm.complete(msgs, cfg)
            if not self._discard:  # Esc discards the answer
                try:
                    self.app.call_from_thread(self._answer, question, res, gen, dropped)
                except RuntimeError:  # app already gone
                    pass

        # plain daemon thread: a Textual worker would make closing the screen wait for the LLM
        threading.Thread(target=work, daemon=True).start()

    def _answer(self, question: str, res, gen: int, dropped: int) -> None:
        if self._discard or gen != self._gen:
            return
        self.state.inflight = None
        if dropped:
            self.history = self.history[2 * dropped:]
        if not res.ok:
            self._say(f"! {res.error.message}")
            if "exceed_context_size" in res.error.message:
                self._say("! Kontext voll: ctrl+n für Reset oder llama-server -c erhöhen")
            return
        if res.usage:
            self.state.used = res.usage.get("prompt_tokens", 0) + res.usage.get("completion_tokens", 0)
            self._title()
        self.history += [{"role": "user", "content": question}, {"role": "assistant", "content": res.data}]
        self._say(res.data)
        if self.state.keep:
            ask.save_conversation(self.history, self.state.log, self.state.used)

    def action_close(self) -> None:
        self._discard = True
        if self.state.inflight is not None:  # unanswered question does not stay
            del self.state.log[self.state.inflight:]
            self.state.inflight = None
        self.dismiss(None)
