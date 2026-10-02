"""Modal form: edit one repo's settings (key `e`). Dismisses with the saved RepoConfig or None."""
from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select

from kvasir.branch_names import build
from kvasir.config import RepoConfig
from kvasir.repo_settings import PRESETS, preset_key, update_repo, validate_patterns

PRESET_NAMES = {"1": "Conventional Commits", "2": "Work item", "3": "Both"}
EXAMPLE = {"type": "feat", "id": "4711", "slug": "login-fehler", "date": "2026-10-20"}


def parse_minutes(text: str) -> int:
    """Whole minutes >= 1, else ValueError."""
    try:
        n = int(text.strip())
    except ValueError:
        raise ValueError("whole number of minutes") from None
    if n < 1:
        raise ValueError("at least 1 minute")
    return n


class SettingsScreen(ModalScreen["RepoConfig | None"]):
    DEFAULT_CSS = """
    SettingsScreen { align: center middle; }
    #dialog { width: 80; max-width: 95%; height: auto; max-height: 95%; padding: 0 2;
              border: round $accent; border-title-color: $accent; border-title-style: bold; background: $surface; overflow-y: auto; }
    #preset { height: 3; }
    #path { color: $text-muted; }
    .err { color: $error; }
    .ex { color: $text-muted; }
    """
    BINDINGS: ClassVar[list[Binding]] = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, url: str, path: str, cfg: RepoConfig) -> None:
        super().__init__()
        self.url, self.path, self.cfg = url, path, cfg

    def compose(self) -> ComposeResult:
        key = preset_key(self.cfg.branch_patterns)
        with Vertical(id="dialog"):
            yield Label(self.path or "(no local path)", id="path")
            yield Label("Branch templates (comma separated)")
            yield Select([(PRESET_NAMES[k], k) for k in PRESETS], value=key or Select.BLANK,
                         prompt="Custom", id="preset")
            yield Input(", ".join(self.cfg.branch_patterns), id="patterns")
            yield Label("", id="patterns-msg", classes="ex")
            yield Label("Fetch interval (minutes)")
            yield Input(str(self.cfg.fetch_interval), id="fetch")
            yield Label("", id="fetch-msg", classes="err")
            yield Label("GitHub interval (minutes)")
            yield Input(str(self.cfg.platform_interval), id="platform")
            yield Label("", id="platform-msg", classes="err")
            yield Label("", id="error", classes="err")
            yield Button("Save (Enter)", id="ok", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#dialog").border_title = f"Settings · {self.url}"
        self._check()

    def _check(self) -> bool:
        """Validate all fields, mark bad ones, lock Save. True if everything is valid."""
        ok = True
        for fid in ("fetch", "platform"):
            inp, msg = self.query_one(f"#{fid}", Input), self.query_one(f"#{fid}-msg", Label)
            try:
                parse_minutes(inp.value)
                text = ""
            except ValueError as e:
                text, ok = str(e), False
            msg.update(text)
            inp.set_class(bool(text), "-invalid")
        pat, msg = self.query_one("#patterns", Input), self.query_one("#patterns-msg", Label)
        try:
            patterns = validate_patterns(pat.value.split(","))
            text, bad = "\n".join(f"{p}  ->  {build(p, **EXAMPLE)}" for p in patterns), False
        except ValueError as e:
            text, bad, ok = str(e), True, False
        msg.update(text)
        msg.set_class(bad, "err")
        pat.set_class(bad, "-invalid")
        self.query_one("#ok", Button).disabled = not ok
        self.query_one("#error", Label).update("")
        return ok

    def on_select_changed(self, ev: Select.Changed) -> None:
        if ev.value is not Select.BLANK:
            self.query_one("#patterns", Input).value = ", ".join(PRESETS[str(ev.value)])

    def on_input_changed(self, _ev: Input.Changed) -> None:
        self._check()

    def on_input_submitted(self, _ev: Input.Submitted) -> None:
        self._save()

    def on_button_pressed(self, _ev: Button.Pressed) -> None:
        self._save()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def _save(self) -> None:
        if not self._check():
            return
        patterns = validate_patterns(self.query_one("#patterns", Input).value.split(","))
        fetch, platform = (parse_minutes(self.query_one(f"#{f}", Input).value) for f in ("fetch", "platform"))
        try:
            self.dismiss(update_repo(self.url, patterns, fetch, platform))
        except (ValueError, OSError) as e:  # not registered any more, unreadable/unwritable repos.toml
            self.query_one("#error", Label).update(str(e))
