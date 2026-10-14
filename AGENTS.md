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
2. **Branch:** `feat/<nr>-<slug>` (bzw. `fix/…`, `docs/…`) ab dem **Basis-Branch** (siehe Absatz "Basis-Branch"; Standard `main`), eigener Git-Worktree.
3. **Umsetzen:** Akzeptanzkriterien des Issues abarbeiten. Kleinste Lösung, die sie erfüllt; keine Features darüber hinaus. Pro Kriterium Test (Pytest, Wegwerf-Repos, siehe `tests/conftest.py`).
4. **Prüfen:** `.venv/bin/pytest -q` und `.venv/bin/ruff check src tests` müssen grün sein. Neues venv im Worktree: `python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'`.
5. **Commit:** Conventional Commits, Autor `christian.silfang@gmail.com`, vorher auf Secrets prüfen.
6. **PR:** nur den Feature-Branch pushen, `gh pr create --base <Basis-Branch>`, Beschreibung mit `Closes #<nr>` (gegen `main`) bzw. `Refs #<nr>` (gegen einen anderen Branch, siehe unten), Liste der erfüllten Kriterien, offene/manuelle Punkte (z. B. Windows). Code-Änderungen nie direkt auf `main` oder einen Integrationsbranch pushen (reine Doku-Änderungen nur auf ausdrückliche Anweisung des Nutzers).
   - **Review:** Der PR wird vom Hauptagenten (nicht vom Autor-Agenten) geprüft: Feature-Branches auf `origin/main` zusammenführen, `pytest` + `ruff` laufen lassen, Diff lesen.
   - **Merge:** Der Hauptagent darf per `gh pr merge --squash` selbst mergen, wenn Tests und `ruff` grün sind, das Review keine Blocker ergibt und die Akzeptanzkriterien erfüllt sind. Danach Feature-Branch (remote und lokal) und Worktree löschen. Nicht gemergt wird bei Blockern, offenen Fragen oder rotem CI; dann Nutzer informieren.
   - **Freigabe:** Die Merge-Erlaubnis gilt nur, weil der Nutzer sie am 2026-10-02 einmalig ausdrücklich erteilt hat (nachdem der Agent gefragt hat). Bevor ein Agent in einem anderen Projekt oder ohne diese Notiz selbst mergt, muss er den Nutzer einmal fragen und die Zustimmung abwarten.
7. **Unklar oder widersprüchlich:** kein Raten. Am Issue kommentieren, Label `needs-info` setzen und das nächste unabhängige Issue nehmen.

### Basis-Branch

Standard ist `main`. Ein PR darf auch gegen einen anderen Branch gehen, wenn das einen Grund hat:

- **Integrationsbranch** für ein Feature, das erst getestet werden soll (z. B. `feat/workspace`): Teil-PRs gehen dorthin; am Ende ein PR `feat/<name>` → `main`, der alle Issues mit `Closes` schließt. Den Integrationsbranch legt der Hauptagent auf ausdrücklichen Wunsch des Nutzers an.
- **Abhängige/parallele Tasks:** Baut ein Issue auf einem noch nicht gemergten Feature-Branch auf, geht der PR gegen diesen Branch (`--base feat/<nr>-<slug>`). Der Hauptagent merkt sich die Reihenfolge: zuerst der Basis-PR nach `main`, danach wird der abhängige PR auf `main` umgestellt (`gh pr edit --base main`) und neu geprüft. Nie den abhängigen PR vor seiner Basis nach `main` mergen.
- **Regeln für Nicht-`main`-Basen:** Beschreibung mit `Refs #<nr>` statt `Closes` (GitHub schließt Issues nur beim Merge in den Default-Branch). Review und Merge wie üblich (Basis-Branch zusammenführen, `pytest` + `ruff`, Diff lesen, Mergbarkeit abwarten, erst nach bestätigtem Merge aufräumen).
- Der Autor-Agent bekommt den Basis-Branch im Auftrag genannt; ohne Angabe gilt `main`.

Plattformen: Linux, macOS, Windows. Keine Shell-Strings für Prozessaufrufe (Argumentlisten), Pfade mit `pathlib`.
Vorherige Fassung des Projekts: Branch `archive/v0-mimirlink` (nur als Anhaltspunkt, nichts blind übernehmen).
