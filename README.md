# mimirlink

- badge
- image

Local, offline-first developer workflow and journaling tool.
Runs on Linux, macOS, and Windows — no internet connection required.

Tracks todos, notes, journal entries, metrics, work sessions, and commits. All data is stored as plain NDJSON and Markdown files: readable, Git-friendly, and sync-tool-agnostic.

---

## Installation

### One-liner (recommended)

**Linux / macOS**
```bash
curl -sSL https://comcy.github.io/kvasir/install.sh | bash
```

**Windows (PowerShell)**
```powershell
irm https://comcy.github.io/kvasir/install.ps1 | iex
```

Requires **Python 3.11+**. The installer fetches [uv](https://github.com/astral-sh/uv) automatically if not present, then builds mimirlink directly from GitHub — no package registry, no account.

### Manual install (via uv or pipx)

```bash
# uv (recommended)
uv tool install "git+https://github.com/comcy/kvasir.git"

# pipx
pipx install "git+https://github.com/comcy/kvasir.git"
```

**With PDF export support** (requires system libs: Cairo, Pango):
```bash
uv tool install "git+https://github.com/comcy/kvasir.git" --extra pdf
```

**Manage the installation:**
```bash
uv tool upgrade mimirlink      # update to latest
uv tool uninstall mimirlink    # remove
```

### First-time setup

Create at least one workspace before using any other command:

```bash
mimirlink workspace create private
```

With optional flags:

```bash
mimirlink workspace create work \
  --path ~/sync/work-mimirlink \
  --sync "OneDrive" \
  --desc "Work projects"
```

All workspace data lives under `~/.mimirlink/workspaces/<name>/`.

---

## TUI — Quick Reference

```bash
mimirlink tui                     # launch (default theme: dracula)
mimirlink tui --theme nord        # launch with a different theme
```

Available themes: `dracula` · `nord` · `tokyo-night` · `gruvbox` · `catppuccin` · `solarized`

### Global TUI keys

| Key | Action |
|-----|--------|
| `1` | Dashboard tab |
| `2` | Todos tab |
| `3` | Notes tab (includes Journal) |
| `4` | Search tab |
| `t` | Cycle theme |
| `r` | Reload dashboard |
| `m` | Morning routine (todo triage, journal gap-fill, plan today) |
| `/` | Jump to search |
| `ctrl+p` | Command bar (run any `mimirlink` subcommand inline) |
| `q` | Quit |

---

## Todos

### CLI

```bash
mimirlink todo add "Write release notes" --due 2026-07-01 --tags "docs,release"
mimirlink todo list                      # open todos (default)
mimirlink todo list --status done
mimirlink todo list --status all --tag release
mimirlink todo done <id-prefix>          # first 8 chars of the ID are enough
mimirlink todo delete <id-prefix>
```

### TUI keys (Todos tab)

| Key | Action |
|-----|--------|
| `a` | Add todo (opens form) |
| `e` | Edit selected todo |
| `d` | Toggle done / reopen |
| `x` | Delete todo |
| `s` | Cycle status filter (All → Open → Done → Cancelled) |
| `g` | Toggle delegated AND-filter |
| `c` | Clear all filters |

### Filter bar

The filter bar has two rows:

```
Status   All  Open ●  Done  Cancelled
AND      ↗ delegated   #dev   #billing
```

- **Status row** — radio-style: select one status at a time.
- **AND row** — additive filters applied on top of the status filter:
  - **↗ delegated** — shows only todos that have an assignee (tasks you handed off).
  - **#tag pills** — each active tag narrows the list further. Multiple tags = union (any match).

Click a pill or use `s` / `g` to toggle.

### Todo form fields

| Field | Format | Example |
|-------|--------|---------|
| Text | Free text | `Set up staging env` |
| Assignee | `@name` or just `name` | `@alice` |
| Due date | `YYYY-MM-DD` | `2026-07-15` |
| Tags | Comma-separated | `infra, release` |

Todos past their due date are highlighted in red in the TUI.

### Todos inside notes (inline extraction)

Write checkbox items directly in any note using this syntax:

```markdown
- [ ] Deploy staging @alice #infra due:2026-07-01
- [x] Write release notes #docs
- [ ] Review PR @finance-team #billing
```

Rules:
- `@handle` — assignee (`@finance-team` with hyphens is valid)
- `#tag` — tags (must start with a letter; `#42` is treated as an issue ref and ignored)
- `due:YYYY-MM-DD` — due date
- `[x]` or `[X]` — marks the todo as done

When you close a note in the editor (`e` key), mimirlink automatically extracts any checkbox items and adds them to `todos.ndjson`. Extraction is **idempotent** — re-saving a note never creates duplicates. The origin note is stored as `note_ref` on each extracted todo.

You can also extract manually:

```bash
mimirlink note extract-todos my-note.md          # insert into todos.ndjson
mimirlink note extract-todos my-note.md --dry-run  # preview only
```

---

## Notes

Notes are Markdown files with YAML frontmatter stored in the active workspace's `notes/` directory.

### Switching between Journal and Notes view

The Notes tab (`3`) has two modes toggled with **`Tab`** (or click the tab pills at the top):

| Mode | Description |
|------|-------------|
| **Journal** | Calendar navigation, bullet-journal structure |
| **Notes** | Flat list with tag filter, preview panel |

### Journal mode

The journal follows a **bullet-journal hierarchy**:

| File name | Type | Purpose |
|-----------|------|---------|
| `2026.md` | Year | Annual planning, yearly review |
| `2026-06.md` | Month | Monthly log, goals for the month |
| `2026-W26.md` | Week | Weekly spread, week in review |
| `2026-06-27.md` | Day | Daily log, meeting notes, quick captures |

Files are auto-detected by name — no manual tagging required. New journal notes are created automatically with pre-filled frontmatter and a structured template:

| Type | Template content |
|------|-----------------|
| **Year** | 12 month headings `## Januar · 2026-01` … `## Dezember · 2026-12` |
| **Month** | Table `\| KW \| Tag \| Privat \| Geschäftlich \|` with all days; week number on Mondays; German weekday abbreviations (Mo/Di/Mi/Do/Fr/Sa/So) |
| **Week** | 7 day headings `## Mo — 2026-06-22` … `## So — 2026-06-28` |
| **Day** | `## Plan`, `## Log`, and `## Aufgaben` sections |

Date strings inside templates (e.g. `2026-06-28`) are auto-linked in the preview panel — click them to navigate to that day's journal entry.

#### Calendar navigation keys

| Key | Action |
|-----|--------|
| `←` `→` | Move cursor day by day |
| `↑` `↓` | Move cursor week by week |
| `[` `]` | Previous / next month |
| `t` | Jump to today |
| `Enter` | Open or create the day note in `$EDITOR` |
| `W` | Open or create the **week** note |
| `M` | Open or create the **month** note |
| `Y` | Open or create the **year** note |

**Calendar legend:**
- **Bold** = today
- **Green** = day with an existing journal entry
- **Reverse** = calendar cursor (selected day)

The preview panel on the right shows the content of the selected day's note. If no note exists yet, it shows a placeholder prompting you to press Enter.

Below the calendar, three quick-access pills show the ISO week, month, and year for the current cursor position. Click them (or use `W`/`M`/`Y`) to jump directly to that period's note.

### Notes mode

A flat list of all notes, sorted by last-edited timestamp (most recent first).

#### Tag filter

If notes have tags, a filter bar appears above the list:

```
Tags   #dev   #journal-day ●   #billing
```

Click a tag pill to activate it. Multiple active tags = union (any note matching at least one tag is shown). Click again to deactivate. Use `r` to reload and reset the view.

#### Note list layout

Each entry shows two lines:

```
 *D │ Today's daily journal          #journal-day
    │ ✎ 2026-06-28 09:41
```

- **Badge** — `*D` today's day · `D` day · `W` week · `M` month · `Y` year · blank for regular notes
- `│` separator · **Title** from frontmatter · tag chips
- Second line: `✎ YYYY-MM-DD HH:MM` — last edited timestamp

Journal entries are listed first (Year → Month → Week → Day, current period at top per level), followed by regular notes sorted by last-edited.

#### Notes TUI keys (both modes)

| Key | Action |
|-----|--------|
| `n` | New note (opens form, then `$EDITOR`) |
| `e` | Edit selected note in `$EDITOR` |
| `x` | Delete selected note |
| `p` | Paste image from clipboard into `assets/` |
| `l` | Insert wikilink modal (`[[…]]`) |
| `r` | Reload |
| `Tab` | Switch between Journal and Notes mode |

### Wikilinks

Use `[[note-name]]` in any note to link to another note in the same workspace. In the preview panel, wikilinks are rendered as clickable `[[note-name]]` links — clicking one navigates to that note directly. If the target note does not exist, it is created automatically (with frontmatter stub) and opened in the editor.

To insert a wikilink while editing:

1. Press `l` in the Notes panel to open the wikilink search modal.
2. Type to fuzzy-search existing notes.
3. Press Enter — the `[[slug]]` is copied to your clipboard.
4. Paste it into your editor.

If the search query matches no existing note, the modal offers a "create new" option.

### Images

Press `p` to paste an image from the clipboard:

- Saves as `notes/assets/img-<timestamp>.png`
- Copies `![](assets/img-<timestamp>.png)` to your clipboard — paste into your editor

In the preview panel, images are rendered as `🖼 filename` anchors. Clicking one opens the image in your system viewer (`xdg-open` on Linux). Requires `wl-paste` (Wayland) or `xclip` (X11).

### Query blocks

Embed live data from your workspace inside a note:

````markdown
```query
type: todo
status: open
tags: [billing]
due_date: 2026-07-08
sort: due_date
limit: 10
```
````

The block is evaluated at render time — the file on disk is never modified.

Every day-journal note gets one of these automatically in its `## Aufgaben`
section, filtered to that day's `due_date` — see
[Morning routine](#morning-routine).

| Parameter | Values | Default |
|-----------|--------|---------|
| `type` | `todo` | `todo` |
| `status` | `open`, `done`, `cancelled` | _(all)_ |
| `tags` | `[tag1, tag2]` or single | _(all)_ |
| `due_date` | `YYYY-MM-DD` (exact match) | _(all)_ |
| `sort` | `due_date`, `created`, `updated` | `due_date` |
| `limit` | number | `50` |

### Export a note

Renders query blocks to static Markdown (file on disk stays unchanged):

```bash
mimirlink note export my-note.md
mimirlink note export my-note.md --out exported.md
```

### Note format

```markdown
---
title: My Note
created: 2026-06-27T10:00:00
editedAt: 2026-06-27T14:32:00
tags: [dev, planning]
---

Note content here.

Link to another note: [[backlog]]

Inline tasks:
- [ ] Review architecture doc @alice #dev due:2026-07-01
- [x] Update README #docs
```

A full example is in [`docs/sample-note.md`](./docs/sample-note.md).

---

## Workspaces

```bash
mimirlink workspace create <name> [--path PATH] [--sync TARGET] [--desc TEXT]
mimirlink workspace list
mimirlink workspace use <name>
mimirlink workspace delete <name>
```

---

## Git hooks

mimirlink can validate commit messages and automatically record commits into `commits.ndjson`.

**Install into a repo:**

```bash
cd ~/work/my-repo
mimirlink hooks install-hooks
mimirlink hooks install-hooks --force   # overwrite existing hooks
```

| Hook | Trigger | Action |
|------|---------|--------|
| `commit-msg` | Before commit is saved | Validates Conventional Commits — soft-warn + `[y/N]` if invalid |
| `post-commit` | After every commit | Parses commit and appends to `commits.ndjson` |
| `post-checkout` | Branch switch / worktree add | Session tracking, WIP resumption (last session + uncommitted files), stale-branch warning |

The hooks directory is resolved via `git rev-parse --git-path hooks`, so installation works in plain repos, worktrees, and the bare `.bare/` project layout alike. The stale-branch threshold defaults to 14 days and can be overridden per repo in `.mimirlink.toml`:

```toml
[git]
stale_days = 30
```

**Conventional Commits format:**

```
<type>[(scope)][!]: <subject>

feat(auth): add OAuth2 login
fix!: correct session expiry
chore: update dependencies
```

Valid types: `feat` · `fix` · `docs` · `style` · `refactor` · `perf` · `test` · `build` · `ci` · `chore` · `revert`

Non-conventional commits trigger a warning but are allowed after confirmation. They are recorded as `type: wip`.

If `mimirlink` is not in PATH when git runs the hook, the hook exits silently without blocking the commit.

---

## Projects & Worktrees

A **project** is a named, registered repo path in the active workspace — every workspace context (private or work) has its own projects, stored in `projects.ndjson`.

### Clone with the bare-repo worktree layout

```bash
mimirlink project clone git@github.com:me/myproject.git
```

creates:

```
myproject/
  .bare/          # bare clone (the single object database)
  .git            # file: "gitdir: ./.bare" — the folder itself acts as the repo
  main/           # worktree for the default branch (plain subfolder)
```

No working checkout is needed before adding worktrees — each branch simply becomes a sibling folder. The clone also fixes the fetch refspec (bare clones don't track remote branches by default), installs the mimirlink git hooks, and registers the project.

### Manage projects

```bash
mimirlink project add myproject          # register an existing repo (cwd)
mimirlink project add tools --path ~/dev/tools
mimirlink project list                   # name, path, remote, worktrees, active session
mimirlink project remove myproject       # unregister only — files are never deleted
```

### Manage worktrees (inside a project)

```bash
mimirlink wt add feat/login              # folder feat-login/, branch created if missing
mimirlink wt add hotfix --from origin/main
mimirlink wt list                        # folder, branch, uncommitted count, session, stale marker
mimirlink wt remove feat-login           # closes the session; branch is kept
mimirlink wt remove feat-login --force   # even with uncommitted changes
```

`wt` is an alias for `worktree` — both work.

### Automatic session tracking

With the hooks installed, every branch switch or `wt add` opens a **session** (`sessions.ndjson`: repo, branch, `worktree_path`, start, end). Parallel worktrees have parallel sessions; switching branches inside one worktree closes its previous session. On every checkout mimirlink prints WIP-resumption context — when you last worked on the branch and which files are uncommitted — plus a warning for stale branches. Sessions and worktree status appear in the TUI dashboard's *Sessions / WIP* panel.

### Typical workflow

**Once per repo** — clone it as a project (or register an existing checkout):

```bash
cd ~/dev
mimirlink project clone git@github.com:me/myproject.git
cd myproject
```

**Per feature/fix** — one worktree per branch, work happens in plain folders:

```bash
mimirlink wt add feat/login        # creates feat-login/, opens a session
cd feat-login
# ... edit, commit as usual — hooks validate messages and track sessions ...
```

Because every branch is its own folder, switching tasks is just `cd ../hotfix-123` — no stashing, no checkout dance, and each worktree keeps its own uncommitted state. A `git checkout` *inside* a worktree still works normally; the post-checkout hook closes the old session, opens a new one, and reminds you what was in progress:

```
mimirlink: last session on feat/login: 2026-07-09 22:26
mimirlink: 1 uncommitted file(s)
    ?? wip.txt
mimirlink: 1 stale branch(es) (no commits for >14d):
    old-feature — 69d
```

**Staying oriented:**

```bash
mimirlink wt list                  # where is WIP? which session is running? what's stale?
mimirlink project list             # all projects of the current workspace
mimirlink today                    # today's sessions and open todos
```

**When the branch is merged:**

```bash
cd ..                              # leave the worktree before removing it
mimirlink wt remove feat-login     # closes the session, keeps the branch
```

The `morning` routine complements this: overdue-todo triage first, then straight into the right worktree with full WIP context.

---

## Metrics

```bash
# Define a metric
mimirlink metric define build_failures \
  --label "Build failures per week" --type counter --agg weekly

mimirlink metric define focus_time \
  --label "Focus time (minutes)" --type duration --agg daily

# Record values
mimirlink metric record build_failures 1
mimirlink metric record focus_time 45

# Inspect
mimirlink metric show
mimirlink metric show build_failures
```

---

## Daily commands

```bash
mimirlink today                  # today's sessions and open todos
mimirlink summary                # week in review: todos done, commits tracked
mimirlink morning                # morning routine (see below)
mimirlink morning --lookback 14  # check further back for missing journal entries
```

### Morning routine

Run at the start of the day (CLI: `mimirlink morning`, TUI: press `m`) to walk
through four steps in order:

1. **Todo triage** — every open todo due today or overdue is reviewed one at a
   time: mark done, reschedule to a new due date, keep the due date but bump
   priority, or leave it for next time.
2. **Undated todos** — open todos with no due date at all are listed one at a
   time so you can optionally assign one. Setting a due date is the only thing
   that happens — no note is written and no link table is created. The todo
   then simply matches that day's auto-embedded query (see below) and shows up
   there; leaving it undated means it's asked about again next run.
3. **Journal gap-fill** — days in the last 7 (configurable via `--lookback`)
   with no day-journal note are listed one at a time: open `$EDITOR` now to
   write a retrospective entry, permanently skip (never asked again for that
   day), or defer to the next run.
4. **Plan today** — an optional, multi-line prompt for today's plans/intentions
   (CLI: one line per point, blank line to finish; TUI: a text area, Enter adds
   a newline). Each non-empty line becomes its own bullet, appended to a
   `## Plan` section in today's journal note. Leaving it empty skips the step
   — no note is force-created just for this.

Todos are never copied or synced into journal notes. Each day-journal note's
`## Aufgaben` section is created with a `query` block
(`due_date: <that day>`) that renders live at view time — a todo shows up on
exactly the day it's due, and only there, with `todos.ndjson` staying the
single source of truth (see [Query blocks](#query-blocks)).

---

## Data layout

```
~/.mimirlink/
  config.toml                  # workspace list + active workspace
  workspaces/
    private/
      workspace.toml           # metadata + sync target
      data/
        todos.ndjson
        tags.ndjson
        todo_tags.ndjson
        metrics.ndjson
        metric_values.ndjson
        commits.ndjson
        sessions.ndjson
        projects.ndjson
        journal_skips.ndjson
      notes/                   # Markdown + YAML frontmatter
        2026.md                # year journal
        2026-06.md             # month journal
        2026-W26.md            # week journal
        2026-06-27.md          # day journal
        my-note.md             # regular note
        assets/                # images pasted via 'p'
      archive/                 # rotated NDJSON files
    work/
      ...
```

All files are plain text. Put them under version control, edit them directly, or sync them with any folder-sync tool (Syncthing, Nextcloud, OneDrive, Dropbox).

---

## Developer setup

### 1. Clone and create a virtual environment

```bash
git clone git@github.com:comcy/kvasir.git
cd kvasir
python -m venv .venv
source .venv/bin/activate          # Linux / macOS
# .venv\Scripts\Activate.ps1      # Windows PowerShell
```

### 2. Install in editable mode

```bash
pip install -e .
# with PDF export support:
pip install -e ".[pdf]"
```

Changes in `src/` take effect immediately without reinstalling.

### 3. Linting

```bash
pip install -e ".[dev]"
ruff check .
ruff format .
```

### Project layout

```
kvasir/
├── src/
│   ├── cli/            # Typer entry point + subcommands
│   ├── data/           # NDJSON store, journal helpers, todo extraction
│   ├── models/         # Dataclass entities
│   ├── tui/            # Textual app, screens, widgets, themes
│   └── workspace/      # WorkspaceManager + config.toml read/write
├── docs/
│   └── agents/         # Agent skill configuration
├── CONTEXT.md          # Domain vocabulary
├── PLAN.md             # Architecture + design decisions
└── pyproject.toml
```

### Extending the CLI

1. Create `src/cli/your_cmd.py` with a Typer app.
2. Register in `src/cli/main.py`:

```python
from .your_cmd import app as your_app
app.add_typer(your_app, name="your-name")
```

### Architecture reference

See [`PLAN.md`](./PLAN.md) for the full design document covering workspaces, data model, journaling, metrics, TUI layout, and tmux integration.
