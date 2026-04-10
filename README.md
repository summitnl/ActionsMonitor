# Actions Monitor

A lightweight Windows tray application that monitors GitHub Actions workflow statuses and notifies you when something changes.

![Application window](docs/application.png)

## Features

- **Live status** — polls your configured workflows and shows green / orange / red status indicators
- **PR mode** — monitor your own pull request builds: one row per active PR, with branch prefix tags, PR numbers, and a DRAFT indicator. Stale rows auto-remove after a configurable timeout
- **System tray** — minimises to tray; tray icon colour reflects the worst combined state across all workflows

  ![System tray icon](docs/systemtray.png)
- **Toast notifications** — notified when a run starts, succeeds, or fails, with an **Open workflow** button that takes you straight to the run
- **Per-workflow config** — different polling rates, branch filters, and notification overrides per workflow
- **Hot-reload** — edit `config.yaml` and the app picks up changes within seconds, no restart needed
- **Start with Windows** — toggle in the app footer; writes a registry entry for the current user (no admin required)

## Requirements

- Windows 10 / 11 (Linux works too, without the toast button feature)
- Python 3.10 or newer — download from [python.org](https://www.python.org/downloads/), tick **"Add Python to PATH"** during install

## Installation

```
install.bat
```

That's it. The script installs all Python dependencies and creates a `config.yaml` from the template. The app launches automatically when done.

To start it manually afterwards, double-click `run.bat`.

### Building a standalone `.exe`

```
build.bat
```

Produces `dist\ActionsMonitor.exe` — a single file with the icon embedded. Place your `config.yaml` next to it.

## Configuration

Open `config.yaml` (or click **Open config ↗** in the app footer). The file is heavily commented — the key things to fill in are:

### GitHub token

Required for private repositories. Without one the API returns a 404.

Use a **classic token** (fine-grained tokens require org admin approval):

1. Go to [github.com/settings/tokens](https://github.com/settings/tokens)
2. Click **Generate new token (classic)**
3. Enable the top-level **`repo`** scope
4. Paste the token into `config.yaml`

```yaml
github_token: "ghp_xxxxxxxxxxxxxxxxxxxx"
```

> **Note:** Classic tokens have no dedicated "read Actions" scope — the Actions API for private repos falls under the broad `repo` scope. The token still only acts on behalf of your own account.

### Adding workflows

There are two modes: **branch mode** (default) monitors a specific workflow+branch combo, and **PR mode** monitors your own pull request builds.

#### Branch mode

Paste the workflow URL straight from your browser:

```yaml
workflows:
  - url: https://github.com/your-org/your-repo/actions/workflows/ci.yml
    name: "CI"
    polling_rate: 30

  - url: https://github.com/your-org/your-repo/actions/workflows/deploy.yml?query=branch%3Amain
    name: "Deploy (main)"
    polling_rate: 60
```

Branch filters are extracted automatically from the URL query string, or you can set them explicitly:

```yaml
  - url: https://github.com/your-org/your-repo/actions/workflows/ci.yml
    branch: main
```

#### PR mode

Set `mode: "pr"` to see one row per active PR you authored. Your GitHub username is auto-detected from the token — no extra config needed.

```yaml
  - url: https://github.com/your-org/your-repo/actions/workflows/ci.yml
    name: "CI — My PRs"
    mode: "pr"
    polling_rate: 45
    max_prs: 5             # max PR rows to show (default: 5)
    pr_stale_after: 300    # seconds before removing a stale row (default: 300)
```

PR rows show:
- Branch prefix tags (e.g. `hotfix`, `feature`, `chore`) parsed from the branch name
- PR number and cleaned branch name
- A **DRAFT** badge when the PR is a draft

### Notifications

Global defaults, with optional per-workflow overrides:

```yaml
notifications:
  new_run:
    enabled: true
    sound: default       # "default", "none", or path to a .wav file
  failure:
    enabled: true
    sound: default
  success:
    enabled: true
    sound: none
```

## Status colours

| Colour | Meaning |
|--------|---------|
| 🟢 Green | Last run succeeded |
| 🟠 Orange | Run in progress or queued |
| 🔴 Red | Last run failed |
| ⚫ Grey | Unknown / no runs found |

The tray icon follows the same logic, showing the worst state across all configured workflows.

## Uninstall

```
uninstall.bat
```

Removes the startup registry entry and uninstalls the Python packages. Delete the folder afterwards.

## Updating

The app checks for updates automatically on startup. If a new version is available, a dialog offers to pull and restart for you.

To update manually:

```bash
git pull
pip install -r requirements.txt
```

## Changelog

### 2026-04-10

- **Visual refresh & UX improvements** — warm dark theme (stone/amber palette), Lucide-inspired status icons rendered with PIL (checkmark, X, loader, clock, ban, skip, question mark), coloured left accent bars on rows, amber section headers, themed scrollbar, and refined spacing throughout. PR rows now show just the PR number and branch name (the workflow name is in the section header). Badges like DRAFT and branch prefix sit on their own line. The app remembers its window position and size across restarts (`state.json`), with multi-monitor–aware clamping so it never restores off-screen. Added PyInstaller support (`build.bat`) to produce a single `.exe` with the icon embedded.

### 2026-04-09

- **Named notification sounds** — new named sound options (`whistle`, `default`, `reminder`, `mail`, `sms`) that play in sync with the Windows notification flyout instead of firing independently. The default sound for new runs is now `whistle`. Custom `.wav` file paths still work as a fallback.
- **Custom app icon** — the window, taskbar, and system tray now show a dedicated Actions Monitor icon (play triangle with status dot) instead of the generic Python icon.
- **Section headers** — workflows are visually grouped by type: branch-mode workflows under a "Workflows" header, each PR-mode workflow under its own named header with a separator line.
- **Actor mode** — new `mode: "actor"` shows all your recent workflow runs across an entire repo (not just one workflow). Supports `filter: "failed"` to show only failed builds. Configure with a GitHub Actions actor URL like `https://github.com/owner/repo/actions?query=actor%3Ausername`.

### 2026-04-03

- **Notification batching** — notifications arriving within a short window (default 3 s) are combined into a single toast and sound, preventing notification spam when many workflows trigger at once. Configurable via `notifications.batch_window` (set to `0` to disable).
- **PR mode** — monitor your own pull request builds with `mode: "pr"`. One row per active PR, with branch prefix tags (`hotfix`, `feature`, etc.), PR numbers, and a DRAFT indicator. Stale rows auto-remove after a configurable timeout.
- **PR notification overrides** — new `notifications.pr` config subsection lets you override notification defaults for PR-mode workflows (e.g. disable success notifications for PRs only).
- **Auto-update check** — the app checks for updates on startup via git and offers to pull + restart automatically.
