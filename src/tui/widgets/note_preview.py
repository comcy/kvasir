"""Note preview: renders a note's markdown, showing embedded images inline
when the optional `textual-image` package is installed and the terminal
supports it — falls back to Textual's built-in "🖼 filename" clickable
anchor (open externally) otherwise, exactly like before this widget existed.

Terminal-capability detection happens at import time (importing
`textual_image.widget` queries the terminal) and cannot be redone once the
Textual app has started — this module is imported well before `App().run()`,
so the check below lands at the right moment for free.
"""
from __future__ import annotations

import re
from pathlib import Path

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Markdown

try:
    from textual_image.widget import Image as _TermImage
    IMAGES_AVAILABLE = True
except ImportError:
    _TermImage = None
    IMAGES_AVAILABLE = False

_IMG_RE = re.compile(r'!\[([^\]]*)\]\(([^)]+)\)')


def _resolve_image_path(src: str, notes_dir: Path) -> Path:
    path = Path(src.strip())
    return path if path.is_absolute() else notes_dir / src.strip()


class NotePreview(Widget):
    """Drop-in replacement for a single `Markdown(id=...)` preview widget —
    same `set_content(text, notes_dir)` call, but images embedded in *text*
    render inline instead of as a click-to-open anchor, when available."""

    DEFAULT_CSS = """
    NotePreview { height: auto; }
    NotePreview Markdown { margin: 0; background: transparent; }
    NotePreview Image { height: auto; max-height: 20; margin: 1 0; }
    """

    def __init__(self, initial_text: str = "*Select a note from the list.*", **kwargs) -> None:
        super().__init__(**kwargs)
        self._raw = initial_text
        self._notes_dir: Path | None = None

    def set_content(self, raw: str, notes_dir: Path | None = None) -> None:
        self._raw = raw
        self._notes_dir = notes_dir
        self.refresh(recompose=True)

    def compose(self) -> ComposeResult:
        if not IMAGES_AVAILABLE or self._notes_dir is None:
            yield Markdown(self._raw, open_links=False)
            return

        notes_dir = self._notes_dir
        last_end = 0
        for m in _IMG_RE.finditer(self._raw):
            text = self._raw[last_end:m.start()]
            if text.strip():
                yield Markdown(text, open_links=False)
            last_end = m.end()

            alt, src = m.group(1), m.group(2)
            path = _resolve_image_path(src, notes_dir)
            shown = False
            if path.exists():
                try:
                    yield _TermImage(path)
                    shown = True
                except Exception:
                    shown = False
            if not shown:
                # Same substitution _fix_images used to apply for every
                # image — Textual's Markdown already renders this as a
                # clickable "🖼 filename" anchor (open externally).
                yield Markdown(f"![{alt or path.name}]({path})", open_links=False)

        tail = self._raw[last_end:]
        if tail.strip() or last_end == 0:
            yield Markdown(tail, open_links=False)
