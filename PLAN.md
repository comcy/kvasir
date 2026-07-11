# DevTrack – Konzept & Architektur

Lokales, offline-fähiges Developer-Workflow- und Journaling-Tool.
Läuft systemunabhängig auf Linux, Windows und macOS.

---

## 1. Grundprinzipien (die festen Entscheidungen)

- **Sprache:** Python (systemübergreifend, starke Git- und TUI-Bibliotheken).
- **Offline-first:** Keine Internetverbindung nötig. Alle Funktionen lokal.
- **Plaintext als Quelle der Wahrheit:** Daten in lesbaren, Git-/Sync-freundlichen Dateien. Kein Binär-Lock-in.
- **Datei-Formate:**
  - **NDJSON** für strukturierte „Tabellen"-Daten (TODOs, Tags, Metrik-Werte, Main-Branch-Commits, Relationen).
  - **Markdown + YAML-Frontmatter** für frei editierte Inhalte (Journal, Notes, Blogposts, Meeting Notes).
- **Kein Datenbank-Index nötig:** Datenmengen bleiben klein (einige hundert Datensätze, nur Main-Branch-Commits). Dateien werden bei Bedarf komplett in den Speicher geladen, Joins/Filter laufen in Python. Optionaler In-Memory-Index nur, falls später eine Abfrage langsam wird (nicht vorab bauen).
- **Archivierung:** Alte Datensätze werden in `archive/<zeitraum>.ndjson` verschoben. Aktiver Datensatz bleibt klein.

---

## 2. Workspaces (kritisch: Trennung privat / geschäftlich)

**Ein Workspace = vollständig isolierter Ordnerbaum mit eigener Sync-Konfiguration.**
Keine geteilten Dateien zwischen Workspaces.

```
~/.devtrack/
  config.toml                 # nur: welche Workspaces existieren, wo sie liegen
  workspaces/
    private/
      workspace.toml          # sync-ziel: homeserver (z. B. Syncthing/Nextcloud-Ordner)
      data/*.ndjson
      notes/*.md
      archive/*.ndjson
    work/
      workspace.toml          # sync-ziel: OneDrive-Ordner
      data/*.ndjson
      notes/*.md
      archive/*.ndjson
```

**Schutzmechanismen:**
- Befehle laufen immer gegen **genau einen aktiven Workspace** (`devtrack workspace use work`).
- Kein Befehl operiert standardmäßig über alle Workspaces – Sync **nie**.
- **Sync ist pro Workspace gekapselt.** Es gibt kein globales „sync alles".

**Sync-Mechanismus bewusst „dumm":**
Das Tool macht **keinen** eigenen Netzwerk-Sync. Es schreibt nur Dateien in den Workspace-Ordner. Den Transport übernimmt der jeweils zuständige Ordner-Sync-Client:
- `private/` → liegt im Homeserver-Sync-Ordner (Syncthing/Nextcloud).
- `work/` → liegt im OneDrive-Ordner.

Vorteil: erprobte Sync-Software, wasserdichte Trennung, NDJSON/Markdown sind merge-freundlich (anders als SQLite, das bei Cloud-Sync korrumpieren kann).

> **Hinweis Compliance:** Die technische Trennung ersetzt keine organisatorische Klärung. Ob geschäftliche Daten überhaupt auf privater Hardware / in bestimmten Clouds liegen dürfen (DSGVO, interne Richtlinien), ist mit dem Arbeitgeber zu klären.

---

## 2b. Projekte & Worktrees (Bare-Repo-Layout)

**Ein Projekt = benannter, registrierter Repo-Pfad innerhalb eines Workspace** (`projects.ndjson`). Projekte gibt es in jedem Workspace-Kontext (privat wie geschäftlich).

**Empfohlenes Layout (von `mimirlink project clone` erzeugt):**

```
myproject/
  .bare/          # git clone --bare
  .git            # Datei: "gitdir: ./.bare" — Ordner wirkt selbst als Repo
  main/           # Worktree = einfacher Unterordner
  feat-x/         # Worktree
```

Vorteile: kein „Arbeits-Checkout" nötig bevor Worktrees angelegt werden können; Branches liegen als parallele Ordner nebeneinander; `.bare` hält die gesamte Objektdatenbank einmal.

**Befehle:**
- `mimirlink project clone <url> [name]` — Bare-Clone + `.git`-Datei + Fetch-Refspec-Fix + Default-Branch-Worktree + Hook-Installation + Registrierung.
- `mimirlink project add <name>` — bestehendes Repo registrieren (Files bleiben unberührt).
- `mimirlink wt add <branch>` / `wt list` / `wt remove` — Worktrees verwalten; Sessions werden automatisch geöffnet/geschlossen.

**Session-Tracking** läuft über den `post-checkout`-Hook: Branch-Wechsel im selben Worktree schließt die alte Session und öffnet eine neue; parallele Worktrees haben parallele Sessions (Identifier: `worktree_path`). Der Hook zeigt zusätzlich WIP-Resumption (letzte Session + uncommittete Dateien) und Stale-Branch-Warnungen (Schwelle: `[git] stale_days` in `.mimirlink.toml`, Default 14 Tage).

**TUI-Projects-Tab (`5`):** dieselbe Verwaltung interaktiv — `n` (Clone/Add-Dialog), `a` (Worktree hinzufügen), `x` (Worktree/Projekt entfernen, mit Bestätigung), `o` (Shell im Worktree-Ordner öffnen — TUI suspendiert, `$SHELL` startet dort), `f` (Fetch). Clone und Fetch laufen als Background-Worker (`@work(thread=True)`), damit `git clone`/`git fetch` die UI nicht einfrieren. Die git-Mutationslogik liegt zentral in `src/data/projects.py` (`clone_project`, `register_existing`, `add_worktree`, `remove_worktree`, `fetch_project`) — CLI und TUI rufen dieselben Funktionen auf, keine doppelte Implementierung.

---

## 3. Datenmodell (NDJSON-„Tabellen")

Jede „Tabelle" ist eine NDJSON-Datei: eine JSON-Zeile pro Datensatz.
n:m-Beziehungen über separate Mapping-Dateien.

**Beispiel-Dateien pro Workspace (`data/`):**

| Datei | Inhalt |
|---|---|
| `todos.ndjson` | TODOs: id, text, status, due_date, created, ... |
| `tags.ndjson` | Tags: id, name, color |
| `todo_tags.ndjson` | n:m-Mapping: todo_id ↔ tag_id |
| `metrics.ndjson` | Metrik-Definitionen (siehe unten) |
| `metric_values.ndjson` | Zeitreihen-Werte: metric_id, timestamp, value |
| `commits.ndjson` | Nur Main/Master-Commits für Changelogs: hash, typ, scope, subject, breaking, date |
| `sessions.ndjson` | Branch-Sessions: repo, branch, worktree_path, start, end |
| `projects.ndjson` | Registrierte Projekte: name, path, remote |
| `links.ndjson` | Verlinkungen zwischen Notizen/Entitäten |

**Relationen in Python:** Beim Befehl werden die relevanten NDJSON-Dateien geladen, Mappings als `dict`-Lookups aufgelöst. Beim Löschen einer Entität müssen Mapping-Einträge selbst aufgeräumt werden (Konsistenz-Logik im Core).

---

## 4. Conventional Commits & Changelog-Pipeline

### Commit-Generator
- Analysiert `git diff --staged`: geänderte Pfade, Symbole.
- Leitet **Typ** (`feat`, `fix`, `refactor`, `chore`, `perf`, `test`, breaking `!`) und **Scope** ab.
- Optionaler KI-Vorschlag **lokal** über `ollama` (z. B. `llama3.2:3b` / `codellama`) – komplett offline. Nutzer bestätigt/passt an.

### Scope-Erkennung im Monorepo (kein Nx/Turborepo vorhanden)
1. **Explizite Scope-Map** (Config im Repo-Root, geteilt im Team):
   ```toml
   [scopes]
   "packages/auth/**"    = "auth"
   "packages/billing/**" = "billing"
   "apps/web/**"         = "web"
   ```
2. **Pfad-Heuristik als Fallback:** unbekannte Pfade → Scope aus erstem Segment unter `packages/`.
3. **Multi-Scope-Commit:** dominanter Scope als Default; optionale Warnung „Änderung betrifft N Packages – aufteilen?".

> Commit-Konvention lebt **im Repo** (geteilte Config), nicht nur lokal – sonst driftet das Team auseinander. Config-Hierarchie: repo-weit + lokal.

### Drei Changelog-Ebenen
| Ebene | Zielgruppe | Commit-Typen | Format |
|---|---|---|---|
| **Technical log** | Team intern | `refactor`, `chore`, `perf`, `test` | Rohdaten, maschinenlesbar |
| **Developer log** | API-Konsumenten | `feat!`, `fix!`, breaking | strukturiertes Markdown |
| **What's new** | Endnutzer / Marketing | `feat`, `fix` (nutzersichtbar) | Prosa, lokal per LLM umformuliert |

---

## 5. Journaling & dynamisches Markdown (Notion/Obsidian/Logseq-Stil)

- Inhalte = `.md`-Dateien mit YAML-Frontmatter (`title`, `tags`, `created`, ...).
- **Verlinkungen** über `[[wikilinks]]`.
- **Dynamische Query-Blöcke** im Markdown – beim Anzeigen/Export durch Live-Treffer ersetzt:
  ````markdown
  ```query
  type: todo
  status: open
  tags: [billing]
  sort: due_date
  ```
  ````
  Die Datei bleibt valides Markdown; nur das Rendering ist dynamisch.
- **Templates:** `.md`-Vorlagen mit Platzhaltern, beim Erstellen neuer Seiten gefüllt.
- TODO-States, Tags, Properties als Frontmatter-Konventionen (Org-mode-Konzepte geborgt, ohne Org-Syntax-Lock-in).

> **Org-mode vs. Markdown:** Bewusst **Markdown gewählt** – editor-/systemunabhängig (Windows/Linux/Mac). Org wäre mächtiger, aber außerhalb von Emacs schlecht unterstützt; Python-Tooling zum Schreiben dünn.

---

## 6. Flexible Metriken (ohne Code-Änderung)

Metriken **deklarativ** in Config/NDJSON definieren, nicht im Code:

```yaml
metrics:
  build_failures:
    label: "Build-Fehler pro Woche"
    type: counter
    aggregation: weekly
  focus_time:
    label: "Fokuszeit pro Branch"
    type: duration
    source: sessions
```

- Neue Metrik = neuer Eintrag, kein Code-Deploy.
- **Werte eingeben** über mehrere Wege: CLI (`devtrack metric build_failures +1`), TUI-Widget, Frontmatter/Inline-Block, automatisch aus Build-Events/Hooks.
- Persönliche **und** Team-Metriken (z. B. erreichte Ziele, Build-Brüche pro Woche).

---

## 7. CLI, TUI & tmux

- **CLI:** `Typer` – Befehle wie `devtrack today`, `devtrack summary`, `devtrack metric ...`, `devtrack workspace use ...`.
- **TUI:** `Textual` – interaktives Dashboard (Branches, TODOs, Metriken, Heatmaps).
- **tmux-Integration** (`libtmux`), Makros:
  - `:sw <branch>` – Branch wechseln + Pane-Titel
  - `:branches` – Übersicht (Commit-Zahl, letzte Aktivität)
  - `:commit` – interaktiver Conventional-Commit-Dialog
  - `:summary` – Tag zusammenfassen
  - `:new feat/x` – Branch anlegen + wechseln
- **Sprachsteuerung (offline, v. a. privat):** `Vosk` (leicht) oder `Whisper.cpp` (genauer); Sprachausgabe `pyttsx3`. Im Team niedrige Priorität.

---

## 8. Empfohlene Bibliotheken

| Zweck | Bibliothek |
|---|---|
| Git lesen | `gitpython` |
| Datei-Watching | `watchdog` |
| CLI | `typer` |
| TUI | `textual` |
| Terminal-Ausgabe | `rich` |
| Frontmatter | `python-frontmatter` |
| Markdown-Parsing | `mistune` |
| tmux | `libtmux` |
| Scheduler (lokal) | `apscheduler` |
| Benachrichtigungen | `plyer` |
| Sprache (offline) | `vosk` / `whisper.cpp`, `pyttsx3` |
| Lokales LLM (optional) | `ollama` |

---

## 9. Empfohlene Bau-Reihenfolge

1. **Fundament:** Workspace-Verwaltung + NDJSON-Lese-/Schreib-Layer + Konsistenz-Logik für Relationen.
2. **Scope-Erkennung:** Config-Parser (Scope-Map) + Pfad-Heuristik.
3. **Conventional-Commit-Generator:** `git diff`-Analyse + interaktiver CLI-Dialog.
4. **Changelog-Pipeline:** drei Ebenen aus `commits.ndjson`.
5. **Journaling:** Markdown + Frontmatter + Query-Blöcke + Templates.
6. **Metriken:** Definitionen + Werte-Eingabe + Aggregation.
7. **TUI-Dashboard** (Textual): Heatmaps, Metriken, TODOs, WIP-Wiederaufnahme.
8. **tmux-Makros.**
9. **Sprachsteuerung** (zuletzt, optional).

---

## 10. Offene Frage — geklärt

**Workspace-Granularität:** Ein Workspace umfasst **mehrere Projekte** (siehe 2b). Workspace = Kontextgrenze (privat/geschäftlich), Projekt = registriertes Repo mit Pfad, Repo = zur Laufzeit erkannte Identität (Remote-URL). „Repo" liegt damit eine Ebene unter dem Workspace.

---

## High-Value-Features (klarer Zeitgewinn)

- **WIP-Wiederaufnahme:** „Gestern 16:40 zuletzt auf `feat/payment-flow`, 3 uncommittete Dateien."
- **Stale-Branch-Warnung:** Branches ohne Commit seit X Tagen.
- **Commit-Validierung als Pre-Commit-Hook:** hält Changelog-Daten sauber.
- **„Was habe ich diese Woche gemacht":** für Standups/Wochenrückblick.
- **Repo-übergreifender Überblick (privat):** welche der vielen kleinen Projekte sind aktiv/brach.

### Bewusst vermieden (Overengineering)
- Vollständige lokale KI-Code-Review (zu langsam/ungenau mit kleinen Modellen).
- Grafische Web-UI (du arbeitest im Terminal).
- SQLite-Index vorab (Datenmengen zu klein).
