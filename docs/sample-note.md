---
title: Sample Note
created: 2026-06-25T10:00:00
tags: [dev, planning, sample]
---

# Sample Note

Diese Datei demonstriert alle Features des mimirlink Note-Systems.
Öffne sie im TUI unter dem **Notes**-Tab um Query-Blöcke live gerendert zu sehen.

---

## Frontmatter

Jede Note beginnt mit einem YAML-Block zwischen `---`. Pflichtfelder:

| Feld | Bedeutung |
|------|-----------|
| `title` | Anzeigename in der Liste |
| `created` | ISO-Timestamp der Erstellung |
| `tags` | Liste von Tags (auch als `#tag` im Text möglich) |

---

## Wikilinks

Verweise auf andere Notes mit doppelten eckigen Klammern:

- [[standup-2026-06-25]]
- [[architecture-decisions]]
- [[backlog]]

Wikilinks öffnen die verlinkte `.md`-Datei im selben Workspace.
Sie verlinken **nur** auf andere Notes — nicht auf Todos oder Repos.

---

## Inline-Tags

Tags können direkt im Fließtext angegeben werden und werden automatisch
als Frontmatter-Tags erkannt:

Dieses Projekt betrifft #dev und #planning — außerdem läuft gerade
ein Refactoring-Sprint mit Fokus auf #architecture.

---

## Bilder einfügen

Screenshot oder Bild in die Zwischenablage kopieren, dann im TUI
die Taste `p` drücken:

1. Bild wird als `notes/assets/img-<timestamp>.png` gespeichert
2. Markdown-Link `![](assets/img-<timestamp>.png)` landet in der Zwischenablage
3. In `$EDITOR` einfügen — fertig

Beispiel eines eingefügten Bildes:

![](assets/example-placeholder.png)

> **Hinweis:** Das Bild oben existiert nicht — es zeigt nur die Syntax.
> Terminal-Emulatoren mit Kitty Graphics Protocol zeigen Bilder inline an.

---

## Query-Blöcke

Query-Blöcke werden **nur im TUI gerendert** — die Datei selbst bleibt unverändert.
Für einen statischen Export: `mimirlink note export sample-note.md`

### Alle offenen Todos

```query
type: todo
status: open
sort: due_date
limit: 20
```

### Todos mit Tag "dev"

```query
type: todo
status: open
tags: [dev]
sort: due_date
```

### Erledigte Todos (letzte 10)

```query
type: todo
status: done
sort: updated
limit: 10
```

### Alle Todos unabhängig vom Status

```query
type: todo
sort: due_date
limit: 50
```

---

## Standard-Markdown

Alle normalen Markdown-Features funktionieren im Preview-Panel:

### Text-Formatierung

**Fett**, *kursiv*, ~~durchgestrichen~~, `inline code`

### Listen

- Punkt A
- Punkt B
  - Unterpunkt B1
  - Unterpunkt B2
- Punkt C

1. Erster Schritt
2. Zweiter Schritt
3. Dritter Schritt

### Code-Block

```python
def hello(name: str) -> str:
    return f"Hello, {name}!"
```

### Tabelle

| Feature | Status |
|---------|--------|
| Markdown-Preview | ✓ implementiert |
| Query-Blöcke | ✓ implementiert |
| Bild-Paste | ✓ implementiert |
| Wikilinks | geplant |
| Note-Export | geplant |

### Zitat

> "The best tool is the one you actually use."

### Trennlinie

---

## Tastenkürzel im Notes-Tab

| Taste | Aktion |
|-------|--------|
| `n` | Neue Note anlegen |
| `e` | Ausgewählte Note in `$EDITOR` öffnen |
| `x` | Note löschen |
| `p` | Bild aus Zwischenablage einfügen |
| `r` | Notizliste neu laden |
