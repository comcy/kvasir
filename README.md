# kvasir

Terminal-Tool für **Git-Worktrees**: Überblick über mehrere Repos, schnell wechseln, neue Worktrees anlegen, sicher aufräumen. Läuft auf Linux, macOS und Windows. Befehle: `kvasir` oder kurz `kv`.

> **Status:** früh, aber nutzbar. `setup`, die TUI mit Terminal öffnen, Worktree anlegen, entfernen sowie Fetch/Pull sind da. Notizen folgen, siehe [`PLAN.md`](./PLAN.md). Unter Windows noch nicht getestet.

## Voraussetzungen

- **git** (ab 2.36)
- Python 3.11+ wird vom Installer über [uv](https://github.com/astral-sh/uv) bei Bedarf selbst besorgt.

## Installation

**Linux / macOS**

```bash
curl -LsSf https://raw.githubusercontent.com/comcy/kvasir/main/install.sh | sh
```

**Windows (PowerShell)**

```powershell
irm https://raw.githubusercontent.com/comcy/kvasir/main/install.ps1 | iex
```

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
curl -LsSf https://raw.githubusercontent.com/comcy/kvasir/main/install.sh | sh   # erneut ausführen
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
| `r` | Neu laden |
| `q` | Beenden |

Fetch läuft zusätzlich im eingestellten Intervall, solange die TUI offen ist. Pull passiert nie automatisch.

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

## Konfiguration

Zwei Dateien, Verzeichnis je Betriebssystem:

| System | Pfad |
|---|---|
| Linux / macOS | `~/.config/kvasir/` (bzw. `$XDG_CONFIG_HOME/kvasir/`) |
| Windows | `%APPDATA%\kvasir\` |
| überschreiben | Umgebungsvariable `KVASIR_CONFIG_DIR` |

- **`repos.toml`**: pro Remote-URL (z. B. `github.com/comcy/kvasir`) Branch-Vorlagen und Fetch-Intervall (Minuten). Unabhängig vom Rechner, kann synchronisiert werden.
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
