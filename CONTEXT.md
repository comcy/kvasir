# mimirlink — Domain Context

This file defines the canonical vocabulary for the mimirlink project. When writing code, tests, issue titles, or commit messages, use these terms exactly. Do not drift to synonyms listed under "avoid".

---

## Core Concepts

### Workspace
A context boundary, not a project. Examples: `private`, `work`, `university`.

One workspace = one isolated data directory (`~/.mimirlink/workspaces/<name>/`). No shared state between workspaces. A workspace is selected automatically via path-prefix mapping, or explicitly with `mimirlink workspace use <name>`.

**Avoid:** "project", "environment", "profile" when referring to a Workspace.

---

### Repo
A Git repository tracked within a Workspace. Identified by its **remote URL** (`git remote get-url origin`). Fallback for repos without a remote: the absolute path from `git rev-parse --show-toplevel`.

Repos are not configured manually — they are discovered at runtime from the current working directory.

**Avoid:** "project", "repository name", "alias" when referring to a Repo identifier.

---

### Worktree
A Git worktree path. The primary identifier for a Session when multiple branches of the same repo are active simultaneously. Each worktree has its own `.git` link and can hold an independent Session.

---

### Session
A period of work on a specific branch within a specific Worktree. A Session has: `repo` (remote URL), `branch`, `worktree_path`, `start` (ISO timestamp), `end` (ISO timestamp or null if active).

Multiple Sessions can be active in parallel — one per Worktree path. A branch switch within the same Worktree closes the current Session and opens a new one.

**Avoid:** "work period", "time block", "activity".

---

### Stale Branch
A Git branch with no commit activity for longer than the configured threshold (default: 14 days). Detected by reading `git branch --sort=-committerdate` — no separate tracking required.

---

### Scope
A Conventional Commit scope (e.g. `auth`, `billing`, `web`). Defined in `.mimirlink.toml` at the repo root via a path-to-scope map. Falls back to a path heuristic (first path segment under `packages/` or `src/`) if no map is present.

---

### Hook
A shell script installed by `mimirlink install-hooks` into a specific Git repo's `.git/hooks/` directory. Two hooks:

- `post-checkout` — fires on branch switch and `git worktree` operations. Handles: Session tracking, WIP resumption output, Stale Branch warnings.
- `commit-msg` — fires after the commit message is written. Handles: Conventional Commit format validation (soft-warn), auto-entry into `commits.ndjson`.

---

### WIP Resumption
Contextual output shown when switching to a branch: the timestamp of the last Session on that branch, plus the output of `git status --short` for uncommitted files. Surfaced via the `post-checkout` Hook, the TUI Session Panel, and `mimirlink today`.

---

### Query Block
A fenced Markdown code block with the language tag `query` inside a Note file. Evaluated at render time by the TUI — the source file is never modified. Example:

````markdown
```query
type: todo
status: open
tags: [billing]
sort: due_date
```
````

Supported `type` values: `todo`, `note`. Supported fields: `status`, `tags`, `sort`, `limit`.

---

### Wikilink
A `[[note-name]]` reference inside a Note. Resolves to another Note file in the same Workspace's `notes/` directory. Does not resolve to Todos, Repos, or external URLs.

---

### Metric (auto)
A metric derived at query time from existing NDJSON data. Not stored in `metric_values.ndjson`. Examples:
- `focus_time` — aggregated session duration from `sessions.ndjson`
- `commit_frequency` — commit count per day/week from `commits.ndjson`

Defined with `source: sessions` or `source: commits` in the metric definition.

---

### Metric (manual)
A metric whose values are entered explicitly by the user via `mimirlink metric record <name> <value>`. Values stored in `metric_values.ndjson`. Examples: `build_failures`, `prs_reviewed`.

---

## Configuration Hierarchy

```
~/.mimirlink/config.toml      ← global, user-local, never committed
.mimirlink.toml               ← repo-root, committed, shared with team
```

Repo-level config overrides global config for scope maps and stale-branch thresholds. LLM endpoint and path-prefix workspace mappings live in global config only.

---

## What Does Not Exist Here

- Todos have **no Repo field** — they are Workspace-level. Use Tags for grouping by topic or project.
- Wikilinks do **not** resolve to Todos or Repos.
- Sessions are **not** manually started/stopped in normal use — Hooks handle it.
- LLM integration is **always optional** — every command degrades gracefully without it.
