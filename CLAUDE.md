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
WorkflowPoller._poll()
  → fetch_latest_run()          # GitHub REST API
  → StatusEvent → queue.Queue
  → MainWindow._drain_queue()   # main thread
  → WorkflowRow.update()        # widget refresh
  → TrayManager.update()        # tray icon colour
```

### Key classes

- **`ConfigManager`** — loads `config.yaml` with `_deep_merge` against `DEFAULT_CONFIG`; thread-safe via a lock. `get()` always returns a snapshot.
- **`WorkflowPoller`** — one per configured workflow; tracks previous `run_id` / `status` to detect transitions and decide which notification type to fire (`new_run`, `success`, `failure`).
- **`WorkflowRow`** — pure tkinter widget wrapper; receives updates only from the main thread via `update(state, poll_rate)`.
- **`TrayManager`** — wraps `pystray`; coloured PIL icons are pre-generated at startup in `_icons` dict keyed by status constant.
- **`StartupManager`** — reads/writes `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` (Windows only); no admin required.
- **`NotificationManager`** — `plyer` for toast + `winsound`/`paplay` for sound; runs in a daemon thread so it never blocks pollers.

### Config resolution

Per-workflow `notifications` sections are deep-merged *over* the global `notifications` block at notification fire time (not at load time). The merge happens in `WorkflowPoller._fire_notification`.

### Status constants

`ST_*` string constants (`"unknown"`, `"in_progress"`, `"success"`, etc.) are used as dict keys throughout — in `COLOUR`, `STATUS_LABEL`, `STATUS_SYMBOL`, and `_icons`. Adding a new status requires updating all four.

The `CONCLUSION_MAP` translates GitHub's `conclusion` field values into internal `ST_*` constants. `None` conclusion (run still active) maps to `ST_RUNNING`.

### Tray icon colour precedence

`_combined_status()` priority: failure > running > queued > success > unknown.
