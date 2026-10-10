# kvasir – Plan

Stand: 2026-10-11 (Neustart auf `main`; Worktree-Tool, Plattform-Informationen, Sichtbarkeit/Kennzahlen, Tagesbericht und optionale LLM-Funktionen umgesetzt). Der alte Stand liegt in `archive/v0-mimirlink`.

## Ziel

Terminal-Tool für **Git-Worktrees**: Überblick über mehrere Repos, schnelles Wechseln, schnelles Anlegen, sicheres Aufräumen. Dazu ein Tagesbericht („woran gearbeitet“), optional in eine Markdown-Datei (z. B. Obsidian-Journal) abgelegt, und optionale LLM-Funktionen.

**Seit 2026-10-07 zusätzlich: Sichtbarkeit, Prozessstand und Kennzahlen** (Issue #48, #70). kvasir ist dafür der deterministische, rein lesende „Motor“ (CLI mit JSON-Ausgabe, TUI-Panel als Verbraucher). Ursprung und Entscheidungen liegen im Repo `comcy/comcy.github.io` (Issue #28, `docs/workflow.md`, Abschnitt „Sichtbarkeit und Prozessstand“); die Umsetzung hier stammt nicht aus der Worktree-Planung oben und ist dort führend.

## Entscheidungen

| Thema | Entscheidung |
|---|---|
| Sprache | Python, Textual (TUI). Linux, macOS, Windows. |
| Name | Paket/Befehl `kvasir`, Kurzform `kv`. Installation per Git (PyPI-Name `kvasir` ist belegt). `mimirlink` bleibt dem Vault/Node-Tool vorbehalten. |
| Registrierung | Manuell per `kvasir setup`; nur registrierte Repos erscheinen. Schlüssel = normalisierte Remote-URL. |
| `setup`-Modi | (1) `setup <url>`: Bare-Klon im Layout + registrieren. (2) in Bare-Layout-Repo: registrieren. (3) in normalem Clone: registrieren (nur Überblick). |
| Normaler Clone | Variante A: Überblick, Fetch, Pull. Keine zusätzlichen Worktrees; `setup --convert` später. |
| Konfiguration | Zwei Dateien: synchronisierbar (pro URL: Branch-Vorlagen, Fetch-Intervall), lokal (Pfad je Repo, `open_command`). Dritte Ebene **im Repo geteilt** (#53): `kvasir.toml` + `workflow/phases.tsv`; Vorrang lokal > Repo > Standard. |
| Branch-Vorlagen | Pro Repo, mit `{type}`, `{id}` (`1234` oder `ABC-123`), `{slug}`, `{date}`. Default Conventional Commits. Verstoß = Warnung. |
| Wechseln | `Enter` öffnet neues Terminal im Worktree via `open_command` (`{path}`). Default Windows `wt.exe -d {path}`, macOS/Linux `kitty --directory {path}`. Kein `cd`-Wrapper. |
| Anzeige Worktree | Branch, Alter, Betreff, „zuletzt aktiv“, Zähler staged/unstaged/untracked, Notiz. |
| Fetch/Pull | `git fetch --prune` per Intervall (Standard 15 min, pro Repo), nur solange TUI offen. Pull nur manuell (`p`). |
| Entfernen | Verweigern bei ungesicherter Arbeit (Bestätigung durch Branchnamen tippen), Notiz-Prompt, danach „Branch auch löschen?“ nur wenn gemergt (`git branch -d`). |
| Notizen | Taste `m` + beim Entfernen. Kein Prompt beim Schließen des Terminals. |
| TUI | Drei Spalten: Repos → Worktrees/Branches → Details (Panel austauschbar, später Metriken). |

## Bauabschnitte (Reihenfolge)

1. Konfiguration + `setup` (Modi 2/3 zuerst, URL-Normalisierung, zwei Dateien; dann `setup <url>`)
2. Lesen: Drei-Spalten-TUI ohne Aktionen
3. Wechseln (`open_command`)
4. Neuer Worktree (bestehender/neuer Branch, Vorlagen-Prüfung)
5. Entfernen (Sicherheitsprüfung, Notiz, Branch-Frage)
6. Fetch-Intervall + manuelles Pull
7. Notizen

Danach: Tagesbericht und LLM-Funktionen (siehe unten), Metriken.

## Umsetzung: GitHub Issues

Umgesetzt: alle Issues #1 bis #10 (gemergt):

| # | Thema | Abhängig von |
|---|---|---|
| 1 | `setup <url>`: Bare-Klon | – |
| 2 | Worktrees/Branches lesen (Datenmodell) | – |
| 3 | TUI Drei-Spalten (lesen) | 2 |
| 4 | Terminal öffnen (`Enter`) | 3 |
| 5 | Branch-Vorlagen: Prüfung/Namensbau | – |
| 6 | Neuen Worktree anlegen | 3, 5 |
| 7 | Worktree entfernen (sicher) | 3 |
| 8 | Fetch-Intervall + manuelles Pull | 3 |
| 9 | Notizen | 3, 7 |
| 10 | `setup`: interaktive Rückfragen | – |

## Plattform-Informationen (GitHub, danach Azure DevOps)

Aus Issue #24, geplant per Grilling (2026-10-02). Rein lesend, ausschließlich über die `gh` CLI (kein Token in kvasir).

| Thema | Entscheidung |
|---|---|
| Plattformen | Start GitHub (`gh`), danach Azure DevOps (`az` + `azure-devops`), Plattform aus der Remote-URL erkannt |
| Anzeige | Pro Branch: Detail-Panel (PR, Work Item, Pipeline-Läufe) + Marker in der Branchzeile (`#12 ✓`). Zusätzlich Gesamtansicht (`i`): meine PRs, Review-Anfragen, meine Pipeline-Läufe (7 Tage, max. 20) |
| Work Item | GitHub-Issue; erst `{id}` aus dem Branchnamen (Branch-Vorlage), sonst vom PR geschlossene Issues; Board-Status ("In Progress") braucht `gh auth refresh -s read:project` |
| Aktualisierung | Zwischenspeicher `platform_cache.json`; Intervall (Standard 10 min, `platform_interval` pro Repo) und Taste `u`; läuft nur bei offener TUI |
| Aktionen | Nur lesen. `Enter` öffnet im Browser, `c` springt zum lokalen Branch |

| # | Thema | Blockiert durch |
|---|---|---|
| 27 | Plattform-Fundament: `gh`-Zugriff, Datenmodell, Cache (erledigt) | – |
| 28 | Detail-Panel, Branch-Marker, Aktualisierung (erledigt) | 27 |
| 29 | Gesamtansicht (`i`) (erledigt) | 27, 28 |
| 25 | `setup`: CLIs prüfen / Installation anbieten, Konventionen nachträglich ändern (Entwurf) | – |
| 26 | Azure DevOps (Entwurf) | 27 |

## Sichtbarkeit, Prozessstand und Kennzahlen (#48, #70)

Rein lesend, ohne Modell, über `gh`/`az`. Quelle der Entscheidungen: `comcy/comcy.github.io` (`docs/workflow.md`). Befehle und Dateiformate sind in der README beschrieben.

| Baustein | Inhalt | Issues |
|---|---|---|
| `kvasir status [#nr]` | Sub-Issues (beliebig tief), `blocked_by` (Prev/Succ), Prio, Status aus **Fakten** (erledigt, verworfen, blockiert, in Review, in Arbeit, offen; `status:*`-Label nur Hinweis), Termine (Meilenstein, `Geplant:`/`Frist:`), Stepper (Phasen/Schritte); `--format table\|text\|json`, `--layout tree\|split` | #49, #50, #51, #56, #67, #68 |
| `kvasir graph` | Mermaid oder eigenständiges HTML/SVG: Spuren je Feature, Statusfarben, Blocker, Zeitachse | #52, #55 |
| `kvasir metrics` | Kennzahlen aus `workflow/metrics.tsv`: `ticket_cycle_time`, `pr_duration`, `ci_red_before_merge`, `rework_fixes_per_change` (Heuristik), `eval_pass_rate`; Ereignismodell, GitHub und Azure DevOps; `text\|json\|markdown` | #70–#75 |
| `kvasir init` / `kvasir.toml` | Konfiguration im Repo (Branch-Vorlagen, Phasen), `workflow/phases.tsv`, `states.tsv`, `detectors.tsv`; `doctor` prüft sie | #53, #64 |
| TUI | Status- und Stepper-Panel in der Gesamtansicht (`i`) | #54 |

Grenzen (gewollt): kein Schreiben in den Tracker; ohne Termine keine erfundene Zeit; Azure-DevOps-Teil nur gegen Fakes getestet.

## Tagesbericht (#84, #85, #86)

kvasir ist agnostisch: es erzeugt einen Bericht, führt aber kein eigenes Journal. Ablage ist reine Datei-/Markdown-Konfiguration.

| Teil | Inhalt | Issue |
|---|---|---|
| Tageslog | `<config>/days/YYYY-MM-DD.ndjson`: Worktree angelegt/entfernt, Notizen, PR-/Issue-Statuswechsel, Snapshot uncommitteter Arbeit; geschrieben bei Aktionen, Plattform-Refresh und TUI-Ende (kein Dienst) | #84 |
| `kvasir today` | Bericht je Tag (`--date`, `--format md\|json`, `--out`, `--stdout`): Commits aus `git log` (nachträglich für jeden Tag), Log-Ereignisse, Snapshot | #85 |
| `[report]` | `local.toml`: `output` (`{date}`), `mode` (`append-section`, `replace-section`, `overwrite`), `heading`; JSON geht nie in die konfigurierte Datei | #86 |

Entscheidungen: Kalendertag (lokal); Commits werden nicht gespeichert; nur ausdrücklicher Aufruf schreibt, nie automatisch ins Vault.

## LLM-Funktionen (optional, #87–#90)

Ohne `[llm]` in `local.toml` ist alles ausgeblendet. kvasir speichert keine Tokens.

| Teil | Inhalt | Issue |
|---|---|---|
| Client | Provider `openai` (OpenAI-kompatibel: Ollama, vLLM, LM Studio; Key per Env-Variable) und `command` (z. B. `claude -p`); `doctor`-Check; einmalige Bestätigung für nicht-lokale Endpunkte; Opt-out je Repo (`llm = false`) | #87 |
| Zusammenfassung | Taste `s`, je Repo, gecacht per HEAD-Hash | #88 |
| Prompt-Fenster | Taste `a`: Chat mit deterministischer Repo-Suche (`git grep`, `git log`), Notizen, Tageslog | #89 |
| Vorschläge | `c` Commit-Message (nach Rückfrage `git commit`), `t` Notiz; kein Agent | #90 |

Grenzen: `.env`-Dateien nie als Kontext; kein autonomer Agent, kein Tool-Calling; nicht gegen echte Modelle getestet (Ollama/vLLM/`claude -p`); Gemini-Kompatibilität ungeprüft.

## Teststrategie

Pro Abschnitt ein Test gegen ein Wegwerf-Repo (`tempfile`, echtes `git`). Windows-Verhalten (`wt.exe`, Pfade) prüft der Nutzer manuell.

## Offen

- **Windows testen** (#21): `wt.exe`, Pfade, `install.ps1`, `doctor`-Symbole; bisher nur Linux geprüft.
- **Azure DevOps live prüfen** (#26): Provider, `status`, `metrics` nur gegen Dokumentation/Fakes getestet; Checkliste als Kommentar an #26.
- **Board-Status live prüfen:** `projectItems` mit echtem Projekt-Board nur über Fixtures getestet (Token braucht `read:project`).
- **`kvasir status` ohne Argument** (#80, `needs-triage`): Spaltenbreiten (Titel zuerst), ruhigere Übersicht, erledigte Teilbäume ausblenden.
- **Tagesbericht und LLM live prüfen:** `kvasir today`, `[report]`, `s`/`a`/`c`/`t` nur gegen Fakes getestet; Windows ungeprüft. Optional später: Snapshot per Cron/Task Scheduler (`kvasir snapshot`), wenn Tage ohne kvasir-Nutzung fehlen.
- **LLM-Nachbesserungen:** Commit-Message nur einzeilig; Suche nur auf dem committeten HEAD; naive Schlagwortsuche; Tageslog-Snapshot ohne Sperre bei zwei gleichzeitigen Instanzen; Einstieg für Vorschläge aus dem Prompt-Fenster fehlt.
- **Kleinigkeiten:** Abschlussnotiz wird vor `git worktree remove` gespeichert (bleibt stehen, wenn Git ablehnt); SSH-Passphrase-Abfrage kann Fetch bis zum Timeout blockieren; `setup`-URL-Erkennung bei Tippfehler im Pfad; `{date}` prüft nur das Format; `webbrowser.open` im UI-Thread; `gh api user` pro Refresh; `doctor`-Hilfetext nennt `az` nicht; Hinweis bei `credential.helper store`.
- `setup --convert` (normalen Clone ins Bare-Layout umbauen), später.
- Konfiguration liegt lokal (`~/.config/kvasir/` bzw. `%APPDATA%\kvasir`), kein Dotfiles-Repo; `repos.toml` ist bei Bedarf synchronisierbar.
