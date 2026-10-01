# kvasir – Plan

Stand: 2026-10-01 (Neustart auf `main`, Ergebnis des Grillings). Der alte Stand liegt in `archive/v0-mimirlink`.

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

Abschnitt 1 (Konfiguration, `setup` für bestehende Repos) ist umgesetzt. Rest als Issues, alle `ready-for-agent`:

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

## Teststrategie

Pro Abschnitt ein Test gegen ein Wegwerf-Repo (`tempfile`, echtes `git`). Windows-Verhalten (`wt.exe`, Pfade) prüft der Nutzer manuell.

## Offen

- Pfad der synchronisierbaren Konfigurationsdatei (Vorschlag: eigener Ordner, den du in Dotfiles legen kannst).
- Konfiguration pro Rechner für `setup --convert` (später).
