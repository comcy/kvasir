"""Optionale Ablage des Berichts ([report] in local.toml): reine Datei-/Markdown-Ablage. No Textual."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

MODES = ("append-section", "replace-section", "overwrite")
DEFAULT_HEADING = "## Woran gearbeitet"
_HEADING = re.compile(r"^(#{1,6}) +\S")


@dataclass
class ReportConfig:
    output: str
    mode: str = "append-section"
    heading: str = DEFAULT_HEADING


def parse(raw: dict) -> ReportConfig:
    """Validate the raw [report] table; ValueError with a readable message."""
    if bad := sorted(set(raw) - {"output", "mode", "heading"}):
        raise ValueError(f"unknown key(s): {', '.join(bad)}")
    out = raw.get("output")
    if not isinstance(out, str) or not out.strip():
        raise ValueError("output: path (string) required")
    mode = raw.get("mode", "append-section")
    if mode not in MODES:
        raise ValueError(f"mode: expected {' | '.join(MODES)}, got {mode!r}")
    heading = raw.get("heading", DEFAULT_HEADING)
    if not isinstance(heading, str) or not _HEADING.match(heading):
        raise ValueError(f"heading: expected a markdown heading like {DEFAULT_HEADING!r}, got {heading!r}")
    return ReportConfig(out, mode, heading.rstrip())


def target(path: str | Path, day: date) -> Path:
    return Path(str(path).replace("{date}", day.isoformat())).expanduser()


def _section(md: str, heading: str) -> list[str]:
    """Report without its `# Bericht` title line; its headings sit one level below `heading`."""
    shift = len(_HEADING.match(heading).group(1)) - 1
    body = [("#" * shift + ln if ln.startswith("#") else ln) for ln in md.split("\n")[1:]]
    while body and not body[0]:
        body.pop(0)
    while body and not body[-1]:
        body.pop()
    return [heading, "", *body, ""]


def write(path: Path, md: str, mode: str = "overwrite", heading: str = DEFAULT_HEADING) -> None:
    """Store the report. Text outside the section stays byte-identical; missing file/folders are created.

    append-section: replace the section under `heading`, create it at the end if missing.
    replace-section: only replace; ValueError if file or heading is missing.
    overwrite: the whole file becomes the report.
    """
    if mode == "overwrite":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(md.encode("utf-8"))
        return
    if not path.exists() and mode == "replace-section":
        raise ValueError(f"replace-section: {path} does not exist")
    text = path.read_bytes().decode("utf-8") if path.exists() else ""
    new = _section(md, heading)
    lines = text.split("\n")
    level = len(_HEADING.match(heading).group(1))
    start = next((i for i, ln in enumerate(lines) if ln.rstrip() == heading), None)
    if start is None:
        if mode == "replace-section":
            raise ValueError(f"replace-section: heading {heading!r} not found in {path}")
        res = (text + ("" if text.endswith("\n") else "\n") + "\n" if text else "") + "\n".join(new)
    else:
        end = next((i for i in range(start + 1, len(lines))
                    if (m := _HEADING.match(lines[i])) and len(m.group(1)) <= level), len(lines))
        res = "\n".join(lines[:start] + new + lines[end:])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(res.encode("utf-8"))
