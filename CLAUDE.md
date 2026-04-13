# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the app

```bash
# Install dependencies (one-time)
pip install -r src/requirements.txt

# Run (with console, useful for debug output)
python src/main.py

# Run without a console window (Windows)
pythonw src/main.py

# Build a standalone .exe (icon embedded, no Python needed to run)
src\build.bat          # produces ActionsMonitor.exe in the project root
```

When running as a `.exe`, place `config.yaml` next to the executable (project root).

## Architecture

Everything lives in `src/main.py` — single-file application by design.

### File paths and frozen mode

`_APP_DIR` resolves to the project root: `Path(__file__).resolve().parent.parent` (source in `src/`) or `Path(sys.executable).parent` (PyInstaller `.exe`). All user-facing files use this:

| File | Purpose | Gitignored |
|---|---|---|
| `config.yaml` | User config (token, workflows) — hot-reloaded every 5s via mtime | Yes |
| `config.template.yaml` | Checked-in template with documentation | No |
| `state.json` | Window position/size persistence | Yes |
| `app.ico` | Generated multi-size icon (16/32/48/256) | No |

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
  → fetch_pr_runs() × N         # primary + extra_workflows
  → group by head_branch        # latest run per workflow file per branch
  → aggregate status (worst wins)  # failure > running > queued > success
  → pick representative run     # highest-priority status run for display
  → StatusEvent(sub_key=branch) → queue.Queue
  → MainWindow creates/updates/removes WorkflowRows dynamically

ActorWorkflowPoller._poll()   # actor mode
  → fetch_github_username()     # cached GET /user
  → fetch_actor_runs()          # repo-level /actions/runs?actor=...
  → group by workflow_name+branch  # one StatusEvent per combo
  → StatusEvent(sub_key=composite) → queue.Queue
  → MainWindow creates/updates/removes WorkflowRows dynamically
```

### Workflow modes

- **Branch mode** (`mode: "branch"`, default) — one fixed row per workflow+branch combo. Uses `WorkflowPoller`.
- **PR mode** (`mode: "pr"`) — one row per active PR the authenticated user authored. Uses `PRWorkflowPoller`. Rows are created dynamically and auto-removed after `pr_stale_after` seconds.
- **Actor mode** (`mode: "actor"`) — one row per recent workflow run by the authenticated user across all workflows in a repo. Uses `ActorWorkflowPoller`. Supports `filter: "failed"` to show only failed runs. Rows are created dynamically and auto-removed after `stale_after` seconds.

### Key classes

- **`ConfigManager`** — loads `config.yaml` with `_deep_merge` against `DEFAULT_CONFIG`; thread-safe via a lock. `get()` always returns a snapshot.
- **`WorkflowPoller`** — one per configured workflow (branch mode); tracks previous `run_id` / `status` to detect transitions and decide which notification type to fire (`new_run`, `success`, `failure`).
- **`PRWorkflowPoller`** — subclass of `WorkflowPoller` (PR mode); fetches runs filtered by actor, groups by `head_branch`, tracks per-branch state, emits removal events for stale branches. Fetches and caches PR draft status.
- **`ActorWorkflowPoller`** — subclass of `WorkflowPoller` (actor mode); fetches runs via repo-level `/actions/runs?actor=...`, groups by `workflow_name:head_branch`, supports client-side `filter: "failed"`. Uses `parse_actor_url()` for the different URL format.
- **`WorkflowRow`** — auto-height tkinter widget with three lines: title, optional badges (prefix + DRAFT), and status text. PR rows hide the workflow name (shown in the section header) and display PR# + branch as the title. Has a coloured left accent bar and a Lucide-style status icon.
- **`TrayManager`** — wraps `pystray`; coloured PIL icons are pre-generated at startup in `_icons` dict keyed by status constant.
- **`StartupManager`** — reads/writes `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` (Windows only); no admin required.
- **`NotificationManager`** — `plyer` for toast + `winsound`/`paplay` for sound; runs in a daemon thread so it never blocks pollers.
- **`UpdateChecker`** — on startup, compares local HEAD to `origin/main` via git. Skipped entirely when running as a frozen `.exe`.

### Composite keys

`MainWindow._states` and `_rows` are keyed by `(workflow_id, sub_key)` where `sub_key` is `None` for branch-mode rows and the head branch name for PR-mode rows. This allows multiple dynamic rows per poller.

## Visual system

### Colour palette

Warm dark theme using stone/amber tones. Key constants:

- `BG_DARK`, `BG_ROW`, `BG_ROW_ALT` — background shades (stone-800/900)
- `FG_TEXT`, `FG_MUTED`, `FG_LINK` — text colours (stone-200, stone-400, amber-400)
- `COLOUR` — status → hex colour mapping (used for accent bars, tray dots)
- `COLOUR_BG` — status → muted fill for icon circles (white glyph on top)

### Status icons

Lucide-inspired icons rendered with PIL at 4x supersampling + LANCZOS downscale. Each is a white glyph on a solid coloured circle:

| Status | Icon | Function |
|---|---|---|
| Success | Checkmark | `_draw_lucide_circle_check` |
| Failure | X mark | `_draw_lucide_circle_x` |
| Running | Spinner arc | `_draw_lucide_loader` |
| Queued | Clock | `_draw_lucide_clock` |
| Cancelled | Ban slash | `_draw_lucide_ban` |
| Skipped | Skip-forward | `_draw_lucide_skip_forward` |
| Unknown | Question mark | `_draw_lucide_circle_help` |

`_init_status_icons()` generates `ImageTk.PhotoImage` objects after the Tk root exists, cached in `_status_tk_icons`. Adding a new status requires updating: `COLOUR`, `COLOUR_BG`, `_STATUS_ICON_FUNC`, `STATUS_LABEL`, and `CONCLUSION_MAP`.

### App and tray icons

- `_make_base_icon(size)` — amber play triangle on warm dark rounded rect (supersampled)
- `_make_icon_image(colour, size)` — base icon + coloured status dot (3-layer: dark outline → white ring → fill)
- `_generate_app_ico()` — writes `app.ico` with embedded 16/32/48/256px sizes (largest first for proper ICO embedding)
- Window icon set via both `iconbitmap` (`.ico` file) and `wm_iconphoto` (PIL images at multiple sizes)

### Tray icon colour precedence

`_combined_status()` priority: failure > running > queued > success > unknown.

## Persistence

### Window state

`_save_window_state()` writes position/size to `state.json` on quit. `_restore_window_state()` reads it on startup and clamps to visible monitors using `EnumDisplayMonitors` + `GetMonitorInfoW` via ctypes. Falls back to tkinter `winfo_screenwidth/height` if ctypes fails.

### Auto-update check

On startup (before the main window), `UpdateChecker.check()` runs `git fetch origin main` and compares local HEAD against `origin/main`. If behind, a modal dialog offers to pull + restart. All git/network errors are silently ignored so the app always starts. **Skipped when frozen** (`sys.frozen`) since `git pull` cannot update a bundled `.exe`.

## Configuration

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

### Named sounds

`_NAMED_SOUNDS` maps friendly names (`"whistle"`, `"default"`, `"reminder"`, etc.) to `winotify.audio` presets. When a sound config value matches a named sound, `NotificationManager._send()` couples it to the toast via `set_audio()` so the sound plays exactly when the flyout appears. Custom `.wav` file paths bypass this and fall back to `_play_sound()`. Adding a new named sound requires adding it to `_NAMED_SOUNDS` and documenting it in `config.template.yaml`.

## Conventions

### README changelog

When adding features, always add a dated changelog entry to the `## Changelog` section at the bottom of `README.md`. Do not modify existing entries — only append new ones at the top of the list.

### Building

`src\build.bat` runs PyInstaller to produce `ActionsMonitor.exe` in the project root. Build artifacts (`build/`, `*.spec`, `*.exe`) are gitignored.
