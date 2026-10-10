# kvasir

Terminal-Tool für **Git-Worktrees**: Überblick über mehrere Repos, schnell wechseln, neue Worktrees anlegen, sicher aufräumen. Läuft auf Linux, macOS und Windows. Befehle: `kvasir` oder kurz `kv`.

> **Status:** früh, aber nutzbar. `setup`, die TUI mit Terminal öffnen, Worktree anlegen, entfernen Fetch/Pull und Notizen sind da, siehe [`PLAN.md`](./PLAN.md). Unter Windows noch nicht getestet.

## Voraussetzungen

- **git** (ab 2.36)
- optional, für PR/Issue/Pipeline-Anzeige (GitHub): **gh** installiert und angemeldet (`gh auth login`). Für den Board-Status ("In Progress") eines Issues zusätzlich `gh auth refresh -s read:project`; ohne diese Berechtigung steht dort "nicht verfügbar (read:project fehlt)".
- optional, für PR/Work-Item/Pipeline-Anzeige (Azure DevOps): **az** (Azure CLI) installiert, angemeldet (`az login`) und mit der Erweiterung `azure-devops` (`az extension add --name azure-devops`). kvasir ruft `az` nur lesend auf, speichert kein Token und installiert die Erweiterung nie selbst. Hinweis: der Azure-DevOps-Teil ist bisher nur anhand der Microsoft-Dokumentation und von Fixtures getestet, nicht gegen eine echte Organisation.
- Python 3.11+ wird vom Installer über [uv](https://github.com/astral-sh/uv) bei Bedarf selbst besorgt.

## Installation

**Linux / macOS**

```bash
curl -LsSf https://comcy.github.io/kvasir/install.sh | sh
```

**Windows (PowerShell)**

```powershell
irm https://comcy.github.io/kvasir/install.ps1 | iex
```

Die Skripte liegen auch unter `https://raw.githubusercontent.com/comcy/kvasir/main/install.sh` bzw. `install.ps1` (Fallback, falls die Seite nicht erreichbar ist).

Das Skript installiert `uv` (falls nicht vorhanden) und danach kvasir direkt aus GitHub. Kein Paketregister, kein Konto.
Wird `kvasir` danach nicht gefunden: Terminal neu starten oder `uv tool update-shell` ausführen.

### Ohne Skript

```bash
uv tool install "git+https://github.com/comcy/kvasir"
# oder
pipx install "git+https://github.com/comcy/kvasir"
```

### Aktualisieren

```bash
curl -LsSf https://comcy.github.io/kvasir/install.sh | sh   # erneut ausführen
# oder
uv tool upgrade kvasir
```

### Deinstallieren

```bash
uv tool uninstall kvasir
```

Die Konfiguration (siehe unten) bleibt dabei erhalten.

## Schnellstart

```bash
# 1. Repo klonen im Bare-Layout und registrieren (.bare/ + Worktree pro Branch)
kvasir setup https://github.com/comcy/kvasir

# oder ein vorhandenes Repo (Bare-Layout oder normaler Clone) registrieren
kvasir setup ~/Workspace/mein-repo

# 2. Übersicht öffnen
kvasir tui
```

`setup` fragt bei einem neuen Repo nach Branch-Vorlagen, Fetch-Intervall und dem Befehl zum Öffnen eines Terminals. Mit `-p`/`--fetch-interval` lässt sich das überspringen:

```bash
kvasir setup ~/Workspace/mein-repo -p "features/{id}-{slug}" -p "fixes/{id}-{slug}" --fetch-interval 30
```

Einstellungen später ändern:

```bash
kvasir setup ~/Workspace/mein-repo --reconfigure           # fragt Vorlagen, Fetch- und Plattform-Intervall erneut ab (Enter = aktueller Wert)
kvasir setup ~/Workspace/mein-repo --reconfigure --platform-interval 5   # ohne Rückfragen (auch ohne Terminal)
kvasir config          # Konfigurationsverzeichnis, repos.toml und local.toml anzeigen
kvasir config --path   # nur das Verzeichnis
```

`--platform-interval` (Minuten) steuert, wie oft PRs, Work Items und Pipelines aktualisiert werden. Ungültige Vorlagen werden abgelehnt. Änderungen gelten nach `r` in der TUI bzw. beim nächsten Start, bestehende Branches bleiben unberührt.

Nur registrierte Repos erscheinen in der Übersicht. Repos ohne `origin`-Remote werden (noch) nicht unterstützt.

### Bare-Layout

```
mein-repo/
├── .bare/              ← Bare-Klon
├── .git                ← Datei: "gitdir: ./.bare"
├── main/               ← Worktree für Branch "main"
└── feat/login/         ← Worktree für Branch "feat/login" (Verzeichnis = Branchname)
```

Normale Clones werden nur als Überblick angezeigt (Branches, Fetch, Pull), zusätzliche Worktrees entstehen dort nicht.

### TUI

Drei Spalten, von links nach rechts verfeinert: **Repos → Worktrees/Branches → Details**.

| Taste | Aktion |
|---|---|
| `↑` `↓` | Auswahl |
| `h` / `l` | Spalte links / rechts |
| `Enter` | Terminal im Worktree öffnen (`open_command`) |
| `n` | Neuen Worktree anlegen (bestehender oder neuer Branch, Namensprüfung) |
| `x` | Worktree entfernen (verweigert bei ungesicherter Arbeit) |
| `f` | Alle Repos jetzt fetchen (`git fetch --prune`) |
| `p` | Markierten Worktree pullen (`--ff-only`, nie Merge/Rebase) |
| `m` | Notiz zum markierten Worktree/Branch |
| `b` | Remote-Branches ein-/ausklappen (standardmäßig eingeklappt) |
| `u` | Plattform-Daten (GitHub / Azure DevOps: PR, Work Item, Pipelines) jetzt aktualisieren |
| `e` | Einstellungen des gewählten Repos bearbeiten (Branch-Vorlagen mit Presets, Fetch- und Plattform-Intervall; wirkt sofort) |
| `i` | Gesamtansicht: meine PRs, Review-Anfragen, Pipeline-Läufe (siehe unten) |
| `r` | Neu laden |
| `q` | Beenden |

Fetch läuft zusätzlich im eingestellten Intervall, solange die TUI offen ist. Pull passiert nie automatisch.

Für Repos auf GitHub oder Azure DevOps (Remote `dev.azure.com/<org>/<projekt>/_git/<repo>`, alle vier Schreibweisen) zeigt kvasir pro Branch zusätzlich einen Marker in der Branchzeile (`#12 ✓` Checks grün, `#12 ✗` rot, `#12 …` läuft, `draft`) und im Detail-Panel den PR (Status, Review, Checks), das Work Item (Issue: Status, Labels, Zugewiesene, Board-Status) und die letzten Pipeline-Läufe des Branches. Das Work Item kommt aus der `{id}` des Branchnamens (Branch-Vorlage), sonst aus den vom PR geschlossenen Issues. Die Daten stammen aus dem Zwischenspeicher (`platform_cache.json`, "gh: aktualisiert vor …" in der Repo-Spalte) und werden im Hintergrund im Intervall `platform_interval` und mit `u` aktualisiert, nur solange die TUI offen ist und nur lesend. Fehlt `gh`/`az`, ist es nicht angemeldet oder fehlt die Erweiterung `azure-devops`, steht ein dezenter Hinweis in der Repo-Spalte ("az: aktualisiert vor …"), der alte Stand bleibt sichtbar. Bei Azure DevOps kommt das Work Item ebenfalls aus der `{id}` des Branchnamens, sonst aus den am PR verknüpften Work Items; der Board-Status ist die Board-Spalte (`System.BoardColumn`), der Review-Stand ergibt sich aus den Reviewer-Stimmen (10/5 approved, -5/-10 changes requested), "Checks" aus den PR-Richtlinien. "Ich" ist der mit `az login` angemeldete Benutzer (`az account show`).

**Gesamtansicht (`i`):** eigene Seite über alle registrierten GitHub- und Azure-DevOps-Repos, unabhängig vom ausgewählten Branch, mit drei Abschnitten (je höchstens 20 Einträge): **Meine offenen PRs**, **Zum Review angefragt** (mit Autor) und **Meine Pipeline-Läufe** der letzten 7 Tage (GitHub Actions bzw. Azure Pipelines). PR-Zeilen zeigen Repo, Nummer, Titel, Review-Stand (approved / changes requested / ausstehend), Checks (✓ ✗ …) und Alter; Lauf-Zeilen Repo, Workflow, Branch, Status, Dauer und Alter. Review-Stand und Checks lädt kvasir pro PR mit `gh pr view` bzw. `az repos pr show` nach (die Suche liefert sie nicht). Bei Azure DevOps gibt es keine organisationsweite Suche: kvasir fragt je Projekt eines registrierten Repos ab, führt die Ergebnisse zusammen und zeigt nur PRs registrierter Repos. Tasten: `Enter` öffnet den Eintrag im Browser, `c` springt zum zugehörigen Branch/Worktree der Hauptansicht (falls lokal vorhanden), `u` aktualisiert sofort, `Esc` geht zurück. Die Daten kommen aus dem Zwischenspeicher, die Seite zeigt "aktualisiert vor …" und aktualisiert im Intervall `platform_interval` (kürzester Wert der Repos). Fehlt `gh`/`az` oder die Anmeldung, steht ein Hinweis oben auf der Seite. Rein lesend.

Pro Worktree zeigt kvasir Branch, Alter und Betreff des letzten Commits, zuletzt aktive Zeit, Anzahl staged / unstaged / untracked Dateien sowie ahead/behind.

## Branch-Vorlagen

Pro Repo festgelegt (Platzhalter: `{type}`, `{id}`, `{slug}`, `{date}`):

| Vorlage | Beispiel |
|---|---|
| `{type}/{slug}` (Standard, Conventional Commits) | `feat/login-fehler` |
| `features/{id}-{slug}` | `features/4711-login-fehler` |
| `fixes/{id}-{slug}` | `fixes/ABC-123-null-pointer` |
| `release/{date}` | `release/2026-10-20` |

Ein neuer Branch ist gültig, wenn er mindestens eine Vorlage trifft. Ein Verstoß ist nur eine Warnung.

## `kvasir status #<nr>`

Sub-Issues, `blocked_by`-Beziehungen und Status eines GitHub-Issues, rein lesend über `gh`. Repo aus `origin` des aktuellen Ordners oder `--repo owner/repo`; `--format json` für die maschinenlesbare Fassung.

Standardausgabe ist eine Tabelle (`--format table`): Ticket (rechtsbündig), Titel (bei schmalem Terminal mit `…` gekürzt), Status und Fortschritt. Status-Symbole bleiben ohne Farbe lesbar (`NO_COLOR`): `✓` erledigt, `◐` in Review, `▶` in Arbeit, `⛔` blockiert, `○` offen, `✗` verworfen. Fortschritt ist eine Punktleiste über die Schritte plus der aktuelle Schritt, z. B. `●●●○○ Abnahme` (beim Feature die Phasen; ein geschlossenes Feature zeigt alle Phasen erledigt, `●●●●● fertig`). Hinweise (Blocker, Termine, Label-Widerspruch, Vorgänger) stehen als Block `Hinweise` unter der Tabelle. `--format text` liefert die frühere Zeilenausgabe, `--format json` die unveränderte maschinenlesbare Fassung.

Status aus Tatsachen, in dieser Reihenfolge: geschlossen = erledigt (Grund "nicht geplant" oder Label `wontfix` = verworfen), offener Blocker = blockiert, offener PR (nicht Draft) = in Review, Draft-PR oder Branch mit der Issue-Nummer im Namen = in Arbeit, sonst offen. Ein `status:*`-Label widerspricht nur als Hinweis (`! Label sagt in-review, PR #7 ist Draft`); es ersetzt den Status nur dort, wo keine Tatsache vorliegt, und ist dann mit "(laut Label)" gekennzeichnet. Grenzen: höchstens 100 Sub-Issues, Blocker und offene PRs; Branch-Treffer über die Nummer als eigenes Namensstück (`feat/5-x`, nicht `feat/15-x`).

## `kvasir metrics`

Kennzahlen aus `workflow/metrics.tsv` des Repos (aktuelles Verzeichnis), rein lesend über `gh`; Repo aus `origin` oder `--repo owner/repo`, Zeitraum `--since 30d` (Standard, nur Tage). Spalten nach Namen: `id`, `art`, `name`, `unit`, `source`, optional `target`/`enabled`.

Kvasir übersetzt GitHub-Daten in ein neutrales Ereignismodell `Event(item, art, zeit)` und rechnet nur darauf. Quellen: `ticket_cycle_time` = Median von erstem Label `status:in-progress` (`in_arbeit`) bis `closed` (`geschlossen`) der im Zeitraum geschlossenen Tickets; Einheit `h` oder `d` aus der Datei. Tickets ohne `in_arbeit` zählen nicht. `pr_duration` = Median `pr_erstellt` (createdAt) bis `pr_gemergt` (mergedAt) der im Zeitraum gemergten PRs (`gh pr list --state merged`). `ci_red_before_merge` = Anteil dieser PRs mit mindestens einem `ci_rot` (Lauf `gh run list`, Ereignis `pull_request`, Branch des PRs, Ergebnis `failure`, zwischen Erstellen und Merge; abgebrochene Läufe und PRs ohne Läufe zählen nicht rot), in %. Ausgabe: Wert, `n=<Stichprobe>`, Ziel; `n < 3` als `zu klein` statt Wert, ohne Tickets `keine Daten`, jede andere Quelle `unbekannt`. Grenzen: höchstens 200 gemergte PRs und 1000 Läufe; höchstens 100 geschlossene Issues und 100 Timeline-Ereignisse je Issue; nur Text, nur GitHub.

`eval_pass_rate`: Bestehensquote der Aufgaben im **neuesten** Bericht (Dateiname = Zeitstempel) unter `--evals PFAD` (Standard `evals/reports/` des Checkouts, lokal, ohne Plattform). Gelesen wird die Tabelle `| Aufgabe | Läufe | Ergebnis | … |` nach Spaltennamen (Altformat ohne Kosten-Spalte geht); Zeilen `bestanden` / `durchgefallen` zählen, `nicht prüfbar` nicht. Ohne Bericht `keine Daten`.

`rework_fixes_per_change`: Mittel gemergter PRs mit Titel `fix(...)` und `Refs #N` / `Closes #N` im Body je Feature (Feature = Parent des bezogenen Issues, sonst das Issue selbst; Grundmenge = Features der im Zeitraum geschlossenen Tickets, ohne Fix-PR zählt 0). **Heuristik**, im Bericht gekennzeichnet; höchstens 100 PRs.

## `kvasir doctor`

Prüft die Voraussetzungen, jederzeit und ohne ein Repo zu registrieren. Je Punkt `✓` (ok), `✗` (Fehler) oder `!` (Warnung) mit passendem Befehl zur Behebung. Exit-Code 1 bei mindestens einem `✗`, sonst 0.

Geprüft werden: `git` ab 2.36, `gh` im PATH, `gh` angemeldet, Berechtigung `read:project` (nur Warnung), lesbare `repos.toml`/`local.toml`, registrierte Repos mit fehlendem lokalem Pfad, und je Repo die erkannte Plattform samt verfügbarer CLI. Ist ein Azure-DevOps-Repo registriert (oder wird es mit `setup` registriert), prüft `doctor` zusätzlich `az` im PATH, die Anmeldung (`az account show`, sonst Hinweis `az login`) und die Erweiterung `azure-devops` (`az extension list`, sonst Hinweis `az extension add --name azure-devops`). Beides zeigt kvasir nur an und führt es nie selbst aus.

`setup` führt dieselbe Prüfung für die Plattform des Repos aus (nur im Terminal, abschaltbar mit `--no-cli-check`). Ohne Terminal gibt `doctor` nur aus und fragt nie.

**Installation von `gh`** (nur nach ausdrücklicher Bestätigung `[y/N]`, Standard Nein):

| System | Befehl |
|---|---|
| Windows | `winget install --id GitHub.cli` (kvasir führt ihn nach `y` aus) |
| macOS | `brew install gh` (kvasir führt ihn nach `y` aus) |
| Arch | `sudo pacman -S github-cli` (nur angezeigt) |
| Fedora | `sudo dnf install gh` (nur angezeigt) |
| Debian / Ubuntu | [offizielle Anleitung](https://github.com/cli/cli/blob/trunk/docs/install_linux.md) |
| sonst | <https://cli.github.com> |

**Installation von `az`** (gleiche Regeln): Windows `winget install --id Microsoft.AzureCLI`, macOS `brew install azure-cli` (jeweils nur nach `y`); Linux nur Link zur [Microsoft-Anleitung](https://learn.microsoft.com/cli/azure/install-azure-cli) (Paketquelle je Distribution). Die Frage kommt pro CLI nur einmal, auch wenn GitHub- und Azure-Repos registriert sind.

Unter Linux führt kvasir nie eine Installation aus (braucht `sudo`). Fehlt `winget`/`brew`, gibt es nur den Link. Anmeldung (`gh auth login`) und Berechtigung (`gh auth refresh -s read:project`) zeigt kvasir nur an und führt sie nie selbst aus.

## Konfiguration

Zwei Dateien, Verzeichnis je Betriebssystem:

| System | Pfad |
|---|---|
| Linux / macOS | `~/.config/kvasir/` (bzw. `$XDG_CONFIG_HOME/kvasir/`) |
| Windows | `%APPDATA%\kvasir\` |
| überschreiben | Umgebungsvariable `KVASIR_CONFIG_DIR` |

- **`repos.toml`**: pro Remote-URL (z. B. `github.com/comcy/kvasir`) Branch-Vorlagen, Fetch-Intervall (`fetch_interval`) und Intervall für die Plattform-Daten (GitHub, Azure DevOps) (`platform_interval`, Standard 10), jeweils in Minuten. Unabhängig vom Rechner, kann synchronisiert werden.
- **`local.toml`**: pro Rechner der lokale Pfad je Repo und `open_command`.

`open_command` startet ein neues Terminal im Worktree, `{path}` wird durch den Pfad ersetzt. Standard: Windows `wt.exe -d {path}`, macOS und Linux `kitty --directory {path}`.

Auf einem zweiten Rechner reicht `kvasir setup <pfad>` im Repo, die Vorlagen aus `repos.toml` bleiben erhalten.

## Entwicklung

```bash
git clone https://github.com/comcy/kvasir && cd kvasir
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/pytest -q
.venv/bin/ruff check src tests
```

- Begriffe: [`CONTEXT.md`](./CONTEXT.md), Plan und Entscheidungen: [`PLAN.md`](./PLAN.md), Arbeitsweise für Agenten: [`AGENTS.md`](./AGENTS.md).
- Offene Arbeit: [GitHub Issues](https://github.com/comcy/kvasir/issues).
