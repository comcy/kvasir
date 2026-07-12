"""Scope + type suggestion for the commit generator (src/cli/commit_cmd.py,
src/tui/screens/commit_form.py). Heuristics only — no AI involved.

Scope: read from `.mimirlink.toml`'s [scopes] table (pattern -> scope name,
e.g. "packages/auth/**" = "auth"), falling back to the first path segment
under packages/ or src/ for unmapped files — the CONTEXT.md "Scope" concept.
"""
from __future__ import annotations

import fnmatch
from pathlib import Path

_DOC_EXTS = {".md", ".rst", ".adoc"}


def _load_scope_map(root: Path | str) -> dict[str, str]:
    import tomllib

    cfg = Path(root) / ".mimirlink.toml"
    if not cfg.exists():
        return {}
    try:
        with cfg.open("rb") as f:
            raw = tomllib.load(f)
        scopes = raw.get("scopes", {})
        return {str(k): str(v) for k, v in scopes.items()} if isinstance(scopes, dict) else {}
    except Exception:
        return {}


def _heuristic_scope(path: str) -> str | None:
    parts = Path(path).parts
    for anchor in ("packages", "src"):
        if anchor in parts:
            idx = parts.index(anchor)
            if idx + 1 < len(parts):
                return parts[idx + 1]
    return None


def detect_scope(root: Path | str, staged_files: list[str]) -> tuple[str | None, dict[str, int]]:
    """Dominant scope + per-scope file-count breakdown across *staged_files*.

    Each file is matched against the [scopes] map first (fnmatch, so `**`
    behaves like `*` — fine for the documented glob-style patterns), falling
    back to the path heuristic. Files matching neither are left out of the
    breakdown entirely.
    """
    scope_map = _load_scope_map(root)
    counts: dict[str, int] = {}

    for f in staged_files:
        scope = None
        for pattern, name in scope_map.items():
            if fnmatch.fnmatch(f, pattern):
                scope = name
                break
        if scope is None:
            scope = _heuristic_scope(f)
        if scope:
            counts[scope] = counts.get(scope, 0) + 1

    if not counts:
        return None, {}
    dominant = max(counts.items(), key=lambda kv: kv[1])[0]
    return dominant, counts


def suggest_type(staged_files: list[str]) -> str | None:
    """Conservative type guess — None means "no confident guess, ask the user"."""
    if not staged_files:
        return None

    def _all(pred) -> bool:
        return all(pred(f) for f in staged_files)

    if _all(lambda f: f.startswith(".github/workflows/")):
        return "ci"
    if _all(lambda f: f.startswith("docs/") or Path(f).suffix in _DOC_EXTS):
        return "docs"
    if _all(lambda f: "test" in Path(f).stem.lower() or f.startswith("tests/")):
        return "test"
    return None
