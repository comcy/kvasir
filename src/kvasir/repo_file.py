"""Im Repo geteilte Einstellungen: `kvasir.toml` und `workflow/phases.tsv` im Repo-Wurzelverzeichnis.

Phasen-Vorrang: kvasir.toml [[phases]] > workflow/phases.tsv > eingebauter Standard.
Branch-Vorlagen-Vorrang: lokal (repos.toml, nur wenn gesetzt) > kvasir.toml [branches] > Standard.
Die Dateien enthalten nur Detektor-Namen; ausgewertet wird in kvasir, nie Code aus den Dateien.
"""
from __future__ import annotations

import json
import tomllib
from pathlib import Path

from kvasir.branch_names import compile_pattern
from kvasir.config import DEFAULT_PATTERNS, RepoConfig, load_local, load_repos
from kvasir.platform.stepper import DETECTORS, PHASES, Phases, Vocabulary, check_detector

FILE = "kvasir.toml"
PHASES_TSV = Path("workflow") / "phases.tsv"
DETECTORS_TSV = Path("workflow") / "detectors.tsv"


def checkout_root(cwd: Path) -> Path:
    """Nearest dir upwards holding `.git` (dir or worktree file) = the checkout; cwd when none."""
    cwd = cwd.resolve()
    return next((d for d in (cwd, *cwd.parents) if (d / ".git").exists()), cwd)


def load(root: Path) -> dict:
    """Parsed kvasir.toml, {} when missing. ValueError when unreadable or not valid TOML."""
    p = root / FILE
    if not p.exists():
        return {}
    try:
        return tomllib.loads(p.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise ValueError(f"{FILE}: {e}") from e


def _tsv(root: Path, rel: Path = PHASES_TSV) -> list[dict[str, str]]:
    """Rows of a workflow TSV as dicts (Kopfzeile = Spaltennamen), `enabled: no` dropped."""
    p = root / rel
    lines = [x for x in p.read_text(encoding="utf-8").splitlines() if x.strip() and not x.startswith("#")]
    head = lines[0].split("\t") if lines else []
    rows = [dict(zip(head, (c.strip() for c in x.split("\t")), strict=False)) for x in lines[1:]]
    return [r for r in rows if r.get("enabled", "yes").lower() != "no"]


def vocabulary(root: Path) -> Vocabulary | None:
    """Detector vocabulary of workflow/detectors.tsv (name -> '-', 'text', 'path' or allowed values);
    None when the repo has no such file. Raises ValueError when unreadable."""
    if not (root / DETECTORS_TSV).exists():
        return None
    try:
        rows = _tsv(root, DETECTORS_TSV)
    except OSError as e:
        raise ValueError(f"{DETECTORS_TSV}: {e}") from e
    out: Vocabulary = {}
    for r in rows:
        arg = r.get("arg", "-")
        out[r.get("name", "")] = tuple(arg[5:].split("|")) if arg.startswith("enum:") else arg
    return out


def _specs(done_when) -> tuple[str, ...]:
    """TSV text ("a,b", "-") or TOML list -> detector specs; "-"/empty = not observable."""
    items = done_when.split(",") if isinstance(done_when, str) else list(done_when)
    return tuple(s.strip() for s in items if str(s).strip() not in ("", "-"))


def phase_rows(root: Path) -> tuple[str, list[tuple[object, object]]] | None:
    """(source, [(name, done_when), ...]) as written in the repo, None when no file defines phases.
    Raises ValueError for unreadable files. No validation here (see problems())."""
    data = load(root)
    if "phases" in data:
        ph = data["phases"]
        if not isinstance(ph, list):
            raise ValueError(f"{FILE}: phases must be an array of tables ([[phases]])")
        return FILE, [(p.get("name"), p.get("done_when")) if isinstance(p, dict) else (None, None) for p in ph]
    if (root / PHASES_TSV).exists():
        try:
            rows = _tsv(root)
        except OSError as e:
            raise ValueError(f"{PHASES_TSV}: {e}") from e
        return str(PHASES_TSV), [(r.get("name"), r.get("done_when")) for r in rows]
    return None


def load_phases(root: Path) -> Phases:
    """Phases for `kvasir status`. Unreadable/incomplete rows are skipped (doctor reports them), the
    built-in standard is the fallback when no repo file defines phases or none is usable."""
    try:
        found = phase_rows(root)
    except ValueError:
        return PHASES
    out = tuple((n, _specs(d)) for n, d in found[1] if isinstance(n, str) and n and d is not None) if found else ()
    return out or PHASES


def problems(root: Path) -> list[str]:
    """Everything wrong in the repo files: unknown detectors, missing required fields, bad templates."""
    out: list[str] = []
    try:
        found = phase_rows(root)
        data = load(root)
    except ValueError as e:
        return [str(e)]
    try:
        vocab = vocabulary(root)
    except ValueError as e:
        return [str(e)]
    if found:
        src, rows = found
        for i, (name, done_when) in enumerate(rows, 1):
            label = f"{src}: phase {name or i}"
            if not isinstance(name, str) or not name:
                out.append(f"{src}: phase {i}: required field name missing")
            if done_when is None or not isinstance(done_when, (str, list)):
                out.append(f"{label}: required field done_when missing")
                continue
            for s in _specs(done_when):
                if e := check_detector(s, vocab):
                    out.append(f"{label}: {e}")
                elif s.partition(":")[0] not in DETECTORS:  # in the repo vocabulary, but kvasir has no rule for it
                    out.append(f"{label}: detector {s.partition(':')[0]} is not evaluated by kvasir (shown as unknown)")
    for p in _branch_patterns(data):
        try:
            compile_pattern(p)
        except ValueError as e:
            out.append(f"{FILE}: [branches] {e}")
    return out


def _branch_patterns(data: dict) -> list[str]:
    b = data.get("branches")
    ps = b.get("patterns") if isinstance(b, dict) else None
    return [p for p in ps if isinstance(p, str)] if isinstance(ps, list) else []


def repo_patterns(root: Path | None) -> list[str] | None:
    """[branches] patterns of the repo file, None when absent or unreadable."""
    try:
        return _branch_patterns(load(root)) or None if root else None
    except ValueError:
        return None


def effective_patterns(cfg: RepoConfig, root: Path | None) -> list[str]:
    """Local (repos.toml, only when set) > kvasir.toml > default."""
    if cfg.patterns_set:
        return cfg.branch_patterns
    return repo_patterns(root) or list(DEFAULT_PATTERNS)


def patterns_for(url: str) -> list[str]:
    """Effective branch templates of a registered repo (normalized URL)."""
    path = load_local().paths.get(url)
    return effective_patterns(load_repos().get(url, RepoConfig(patterns_set=False)), Path(path) if path else None)


def render(patterns: list[str] | None, phases: Phases | None) -> str:
    """kvasir.toml text. Strings via JSON quoting (valid TOML basic strings)."""
    q = json.dumps
    out = []
    if patterns:
        out.append("[branches]\npatterns = [" + ", ".join(q(p) for p in patterns) + "]\n")
    for name, specs in phases or ():
        out.append(f"[[phases]]\nname = {q(name, ensure_ascii=False)}\n"
                   f"done_when = [{', '.join(q(s) for s in specs)}]\n")
    return "\n".join(out)
