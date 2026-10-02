# kvasir – Plan

Stand: 2026-10-02 (Neustart auf `main`; alle zehn Issues #1 bis #10 umgesetzt). Der alte Stand liegt in `archive/v0-mimirlink`.

## Ziel

Terminal-Tool für **Git-Worktrees**: Überblick über mehrere Repos, schnelles Wechseln, schnelles Anlegen, sicheres Aufräumen. Später: Tagesauswertung („woran gearbeitet“) in das Obsidian-Vault-Journal (nicht Teil der ersten Version).

## Entscheidungen

| Thema | Entscheidung |
|---|---|
| Sprache | Python, Textual (TUI). Linux, macOS, Windows. |
| Name | Paket/Befehl `kvasir`, Kurzform `kv`. Installation per Git (PyPI-Name `kvasir` ist belegt). `mimirlink` bleibt dem Vault/Node-Tool vorbehalten. |
| Registrierung | Manuell per `kvasir setup`; nur registrierte Repos erscheinen. Schlüssel = normalisierte Remote-URL. |
| `setup`-Modi | (1) `setup <url>`: Bare-Klon im Layout + registrieren. (2) in Bare-Layout-Repo: registrieren. (3) in normalem Clone: registrieren (nur Überblick). |
| Normaler Clone | Variante A: Überblick, Fetch, Pull. Keine zusätzlichen Worktrees; `setup --convert` später. |
| Konfiguration | Zwei Dateien: synchronisierbar (pro URL: Branch-Vorlagen, Fetch-Intervall), lokal (Pfad je Repo, `open_command`). |
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

Danach: Tagesauswertung → Vault (`vault_path`), Metriken.

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

## Teststrategie

Pro Abschnitt ein Test gegen ein Wegwerf-Repo (`tempfile`, echtes `git`). Windows-Verhalten (`wt.exe`, Pfade) prüft der Nutzer manuell.

## Offen

- **Board-Status live prüfen:** `projectItems` mit echtem Projekt-Board ist nur über Fixtures getestet (Token braucht `read:project`).
- **Plattform-Nachbesserungen:** `webbrowser.open` läuft im UI-Thread; `gh api user` pro Repo bei jedem Refresh (cachen).
- **#26** (Azure DevOps, `az`): Entwurf, vor Umsetzung planen. Erledigt: #25 (`kvasir doctor`), #35 (`setup --reconfigure`, `kvasir config`), #36 (Einstellungen-Dialog `e`), #33 (Titel-Ränder, Footer), #37 (GitHub Pages von `main`).
- **Windows testen** (`wt.exe`, Pfade, `install.ps1`) und die Install-Skripte einmal real ausführen — nur Linux wurde bisher geprüft.
- **Tagesauswertung → Vault-Journal** („woran gearbeitet“): noch kein Issue, `vault_path` noch nicht konfigurierbar. Vorher grillen.
- **Kleinigkeiten:** Abschlussnotiz wird vor `git worktree remove` gespeichert (bleibt stehen, wenn Git ablehnt); SSH-Passphrase-Abfrage kann Fetch bis zum Timeout blockieren; `setup`-URL-Erkennung bei Tippfehler im Pfad; `{date}` prüft nur das Format.
- `setup --convert` (normalen Clone ins Bare-Layout umbauen), später.
- Konfiguration liegt lokal (`~/.config/kvasir/` bzw. `%APPDATA%\kvasir`), kein Dotfiles-Repo; `repos.toml` ist bei Bedarf synchronisierbar.
