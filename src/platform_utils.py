"""Small per-OS helpers so the CLI/TUI behave the same on Linux, macOS and
Windows. Clipboard text/image access deliberately goes through the
well-tested `pyperclip`/`Pillow` libraries instead of hand-rolled per-OS
shell-outs — see `src/tui/widgets/notes_panel.py`."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def default_editor() -> str:
    """`$EDITOR`/`$VISUAL` if set, else a fallback actually installed by
    default on this OS ('nano' ships with Linux/macOS; Windows has neither,
    so it falls back to Notepad)."""
    return os.environ.get("EDITOR") or os.environ.get("VISUAL") or (
        "notepad" if sys.platform == "win32" else "nano"
    )


def open_file(path: str | Path) -> None:
    """Open *path* with the OS-default handler for its file type."""
    path = str(path)
    if sys.platform == "win32":
        os.startfile(path)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])
