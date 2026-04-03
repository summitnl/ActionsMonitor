# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the app

```bash
# Install dependencies (one-time)
pip install -r requirements.txt

# Run (with console, useful for debug output)
python main.py

# Run without a console window (Windows)
pythonw main.py
# or double-click:
run.bat
```

## Architecture

Everything lives in `main.py` — single-file application by design. `config.yaml` sits alongside it and is hot-reloaded every 5 seconds via file mtime comparison.

### Threading model

| Thread | What it does |
|---|---|
| Main (tkinter) | UI event loop; only thread that may touch widgets |
| `poller-{n}` (one per workflow) | Polls GitHub API on a configurable interval; puts `StatusEvent` objects onto a shared `queue.Queue` |
| `tray` | Runs the `pystray` icon loop |
| Ad-hoc daemon threads | Fire toast notifications + sounds without blocking pollers |

The UI drains the queue via `root.after(500, _drain_queue)` — this is the only safe way to propagate poller results to tkinter widgets. Never call widget methods from poller threads directly.

### Data flow

```
WorkflowPoller._poll()        # branch mode (default)
  → fetch_latest_run()          # GitHub REST API
  → StatusEvent → queue.Queue
  → MainWindow._drain_queue()   # main thread
  → WorkflowRow.update()        # widget refresh
  → TrayManager.update()        # tray icon colour

PRWorkflowPoller._poll()      # pr mode
  → fetch_github_username()     # cached GET /user
  → fetch_pr_runs()             # runs filtered by actor+event
  → group by head_branch        # one StatusEvent per branch
  → StatusEvent(sub_key=branch) → queue.Queue
  → MainWindow creates/updates/removes WorkflowRows dynamically
```

### Workflow modes

- **Branch mode** (`mode: "branch"`, default) — one fixed row per workflow+branch combo. Uses `WorkflowPoller`.
- **PR mode** (`mode: "pr"`) — one row per active PR the authenticated user authored. Uses `PRWorkflowPoller`. Rows are created dynamically and auto-removed after `pr_stale_after` seconds.

### Key classes

- **`ConfigManager`** — loads `config.yaml` with `_deep_merge` against `DEFAULT_CONFIG`; thread-safe via a lock. `get()` always returns a snapshot.
- **`WorkflowPoller`** — one per configured workflow (branch mode); tracks previous `run_id` / `status` to detect transitions and decide which notification type to fire (`new_run`, `success`, `failure`).
- **`PRWorkflowPoller`** — subclass of `WorkflowPoller` (PR mode); fetches runs filtered by actor, groups by `head_branch`, tracks per-branch state, emits removal events for stale branches. Fetches and caches PR draft status.
- **`WorkflowRow`** — pure tkinter widget wrapper; receives updates only from the main thread via `update(state, poll_rate)`. PR rows display additional labels: branch prefix badge, PR number + branch name, DRAFT indicator.
- **`TrayManager`** — wraps `pystray`; coloured PIL icons are pre-generated at startup in `_icons` dict keyed by status constant.
- **`StartupManager`** — reads/writes `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` (Windows only); no admin required.
- **`NotificationManager`** — `plyer` for toast + `winsound`/`paplay` for sound; runs in a daemon thread so it never blocks pollers.

### Composite keys

`MainWindow._states` and `_rows` are keyed by `(workflow_id, sub_key)` where `sub_key` is `None` for branch-mode rows and the head branch name for PR-mode rows. This allows multiple dynamic rows per poller.

### README changelog

When adding features, always add a dated changelog entry to the `## Changelog` section at the bottom of `README.md`. Do not modify existing entries — only append new ones at the top of the list.

### Config files

- `config.template.yaml` — checked into the repo; edit this when adding/documenting new settings or examples.
- `config.yaml` — the user's personal config (gitignored, contains token and real workflow entries). **Never edit `config.yaml` directly.** Make changes to the template and ask the user to update their own config manually.

### Config resolution

Per-workflow `notifications` sections are deep-merged *over* the global `notifications` block at notification fire time (not at load time). The merge happens in `WorkflowPoller._fire_notification`.

For PR-mode workflows, an optional `notifications.pr` subsection is merged between global and per-workflow:
```
branch-mode: global[type] → per-workflow[type] → final
PR-mode:     global[type] → global.pr[type] → per-workflow[type] → final
```

### GitHub username caching

`fetch_github_username()` calls `GET /user` once and caches the result in a module-level variable behind a lock. The cache is reset on config reload (in case the token changes).

### Status constants

`ST_*` string constants (`"unknown"`, `"in_progress"`, `"success"`, etc.) are used as dict keys throughout — in `COLOUR`, `STATUS_LABEL`, `STATUS_SYMBOL`, and `_icons`. Adding a new status requires updating all four.

The `CONCLUSION_MAP` translates GitHub's `conclusion` field values into internal `ST_*` constants. `None` conclusion (run still active) maps to `ST_RUNNING`.

### Auto-update check

On startup (before the main window), `UpdateChecker.check()` runs `git fetch origin main` and compares local HEAD against `origin/main`. If behind, a modal dialog offers to pull + restart. All git/network errors are silently ignored so the app always starts.

### Tray icon colour precedence

`_combined_status()` priority: failure > running > queued > success > unknown.
