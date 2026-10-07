# kvasir — Domain Context

Kanonisches Vokabular. In Code, Tests, Issues und Commits genau diese Begriffe verwenden.

## Begriffe

### Repo
Ein bei kvasir **registriertes** Git-Repository. Identität = normalisierte `origin`-URL (`git@github.com:comcy/kvasir.git` und `https://github.com/comcy/kvasir` → `github.com/comcy/kvasir`). Repos ohne Remote werden (vorerst) nicht unterstützt.
**Avoid:** "Projekt", "Workspace".

### Registrierung
Von Hand ausgeführtes `kvasir setup`. Nur registrierte Repos erscheinen in der Übersicht. Kein automatisches Scannen.

### Layout
- **Bare-Layout:** `.bare/` + `.git`-Datei (`gitdir: ./.bare`) + ein Worktree pro Branch, Verzeichnisname = Branchname.
- **Normaler Clone:** ein Checkout, mehrere Branches. Nur Überblick, Fetch, Pull; keine zusätzlichen Worktrees (siehe PLAN.md).

### Worktree
Ein ausgechecktes Verzeichnis eines Branches. Zeigt: Branch, Alter, Betreff des letzten Commits, "zuletzt aktiv" (jüngerer Wert aus letztem Commit und neuester Änderungszeit uncommitteter Dateien), Zähler staged / unstaged / untracked, optional Notiz.

### Branch-Vorlage
Pro Repo konfigurierte Namensvorlage mit Platzhaltern `{type}`, `{id}`, `{slug}`, `{date}`, z. B. `{type}/{slug}`, `features/{id}-{slug}`. Ein neuer Branch ist gültig, wenn er mindestens eine Vorlage trifft. Verstoß = Warnung, kein Block. Default: Conventional-Commit-Typen. Bestehende Branches werden nicht geprüft.

### Notiz
Freitext zu einem Worktree (Taste `m`, oder Abschlussnotiz beim Entfernen). Einziger eigener Zustand neben der Konfiguration.

### Konfiguration
- **Synchronisierbar** (pro Remote-URL): Branch-Vorlagen, Fetch-Intervall.
- **Lokal** (pro Rechner): lokaler Pfad je Repo, `open_command`.
- **Im Repo geteilt:** `kvasir.toml` im Repo-Wurzelverzeichnis (`[branches] patterns`, optional `[[phases]]` als Überschreibung) und `workflow/phases.tsv` (Quelle der Phasen, auch ohne kvasir lesbar). Nur Detektor-Namen, nie Code. Vokabular der Detektoren: `workflow/detectors.tsv` des Repos (Quelle; `kvasir doctor` prüft dagegen, ohne Datei gilt der eingebaute Satz). Was kvasir nicht auswerten kann, erscheint als unbekannt (Phase fehlt) mit doctor-Hinweis. Vorrang: lokal (`repos.toml`, nur wenn gesetzt) vor Repo-Datei vor eingebautem Standard; Phasen: `kvasir.toml` vor `workflow/phases.tsv` vor Standard. `kvasir init` legt `kvasir.toml` an, `kvasir doctor` prüft sie.

### Item, Beziehung, Status
- **Item:** ein GitHub-Issue als reine Tatsachen (Zustand, Schließgrund, Labels). **Beziehung:** Sub-Issue oder `blocked_by` zwischen Items.
- **Status** (erledigt, verworfen, blockiert, in Review, in Arbeit, offen) kommt aus Tatsachen, nie aus Labels. Ein `status:*`-Label ist nur Hinweis bei Widerspruch oder Status "laut Label", wo keine Tatsache existiert. Siehe `kvasir status`.

## Was es hier nicht gibt

- Kein Hintergrunddienst: Fetch läuft nur, solange die TUI offen ist.
- Kein automatischer Pull. Pull ist immer manuell.
- Kein `git branch -D`, kein Entfernen eines Worktrees mit ungesicherter Arbeit ohne ausdrückliche Bestätigung.
- Kein eigenes Journal, keine Todos, keine Notes (das macht der Obsidian-Vault).
