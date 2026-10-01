## Agent skills

### Issue tracker

Issues live in GitHub Issues at `github.com/comcy/kvasir`; external PRs are not a triage surface. See `docs/agents/issue-tracker.md`.

### Triage labels

Default label vocabulary — `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context repo — one `CONTEXT.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.

## Workflow

Arbeit kommt aus GitHub Issues (`ready-for-agent`). Pläne/Entscheidungen: `PLAN.md`, Begriffe: `CONTEXT.md` (exakt verwenden).

1. **Issue wählen:** niedrigste offene Nummer mit Label `ready-for-agent`, deren "Blocked by"-Issues geschlossen sind. Mehrere unabhängige Issues dürfen parallel bearbeitet werden (je eigener Worktree).
2. **Branch:** `feat/<nr>-<slug>` (bzw. `fix/…`, `docs/…`) ab aktuellem `main`, eigener Git-Worktree.
3. **Umsetzen:** Akzeptanzkriterien des Issues abarbeiten. Kleinste Lösung, die sie erfüllt; keine Features darüber hinaus. Pro Kriterium Test (Pytest, Wegwerf-Repos, siehe `tests/conftest.py`).
4. **Prüfen:** `.venv/bin/pytest -q` und `.venv/bin/ruff check src tests` müssen grün sein. Neues venv im Worktree: `python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'`.
5. **Commit:** Conventional Commits, Autor `christian.silfang@gmail.com`, vorher auf Secrets prüfen.
6. **PR:** nur den Feature-Branch pushen, `gh pr create` gegen `main`, Beschreibung mit `Closes #<nr>`, Liste der erfüllten Kriterien, offene/manuelle Punkte (z. B. Windows). Nicht selbst mergen, `main` nie direkt pushen.
7. **Unklar oder widersprüchlich:** kein Raten. Am Issue kommentieren, Label `needs-info` setzen und das nächste unabhängige Issue nehmen.

Plattformen: Linux, macOS, Windows. Keine Shell-Strings für Prozessaufrufe (Argumentlisten), Pfade mit `pathlib`.
Vorherige Fassung des Projekts: Branch `archive/v0-mimirlink` (nur als Anhaltspunkt, nichts blind übernehmen).
