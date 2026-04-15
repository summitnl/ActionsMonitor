<p align="center">
  <img src="docs/summit.svg" alt="Summit" height="35">
</p>

# Actions Monitor

A lightweight tray application that monitors GitHub Actions workflow statuses and notifies you when something changes. Runs on Windows and Linux.

> See the [Changelog](CHANGELOG.md) for updates.

![Application window](docs/application.png)

## Features

- **Live status** — polls your configured workflows and shows green / orange / red status indicators
- **PR mode** — monitor your own pull request builds: one row per active PR, with branch prefix tags, PR numbers, target branch indicators, and a DRAFT indicator. When a branch has multiple PRs (e.g. hotfix → acceptance and hotfix → production), each PR gets its own row. Stale rows auto-remove after a configurable timeout
- **System tray** — minimises to tray; tray icon colour reflects the worst combined state across all workflows

  ![System tray icon](docs/systemtray.png)
- **Toast notifications** — notified when a run starts, succeeds, or fails, with the app icon and an **Open workflow** button that takes you straight to the run
- **Per-workflow config** — different polling rates, branch filters, and notification overrides per workflow
- **Hot-reload** — edit `config.yaml` and the app picks up changes within seconds, no restart needed
- **Start with Windows** — toggle in the app footer; writes a registry entry for the current user (no admin required)

## Requirements

- **Windows** 10 / 11
- **Linux** with GTK3 (Ubuntu 22.04+, Fedora, etc.) — tray icon requires `gir1.2-ayatanaappindicator3-0.1`

## Getting started

### Windows

1. Run `ActionsMonitor.exe` — on first launch it creates `config.yaml` from the template
2. Add your GitHub token and workflows (see [Configuration](#configuration) below)
3. The app hot-reloads the config, no restart needed

### Linux

1. Run `./ActionsMonitor-linux` — on first launch it creates `config.yaml` from the template
2. Add your GitHub token and workflows (see [Configuration](#configuration) below)
3. The app hot-reloads the config, no restart needed

> **Note:** On Linux, named notification sounds (`whistle`, `reminder`, etc.) are Windows-only. Use `"default"` for a system sound via paplay/aplay, or provide a path to an `.oga`/`.wav` file.

### Development setup

If you want to run from source instead of the binary:

```bash
# Windows
src\dev-install.bat

# Linux
pip3 install -r src/requirements.txt
sudo apt-get install -y python3-tk gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1
python3 src/main.py
```

### Building from source

Requires Python 3.10+ with dependencies installed (`pip install -r src/requirements.txt`).

```bash
# Windows — produces ActionsMonitor.exe
src\build.bat

# Linux — produces ActionsMonitor-linux
pyinstaller --onefile --name ActionsMonitor-linux --add-data "config.template.yaml:." src/main.py
cp dist/ActionsMonitor-linux .
```

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

There are three modes: **branch mode** (default) monitors a specific workflow+branch combo, **PR mode** monitors your own pull request builds, and **actor mode** shows all your recent runs across a repo.

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
    pr_stale_after: "5m"   # duration before removing a stale row (default: "5m")
```

PR rows show:
- Branch prefix tags (e.g. `hotfix`, `feature`, `chore`) parsed from the branch name
- PR number, cleaned branch name, and target branch (e.g. `#42 fix-123 → acceptance`)
- A **DRAFT** badge when the PR is a draft
- A colour-escalating **STALE** badge (yellow → orange → red) based on how long since the PR was last updated
- Review status badges: **APPROVED**, **CHANGES REQUESTED**, or **REVIEW PENDING**
- When a branch has multiple PRs targeting different branches, each PR appears as a separate row

#### Staleness thresholds

Global config that controls when the STALE badge appears on PR rows. Accepts human-friendly durations (`"30m"`, `"12h"`, `"1d"`, `"2d12h"`):

```yaml
staleness_thresholds:
  slightly_stale: "1d"      # yellow badge after 1 day
  moderately_stale: "3d"    # orange badge after 3 days
  very_stale: "5d"          # red badge after 5 days
```

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

Disable **Start with Windows** in the app footer, then delete the folder.

If you used the development setup, run `src\dev-uninstall.bat` to also remove the startup registry entry and Python packages.

## Updating

The app checks for updates automatically on startup:

- **Binary builds** check GitHub Releases for a newer version. If found, a dialog offers to download and install the update in-place.
- **Running from source** uses `git fetch` to detect new commits. If behind, a dialog offers to pull and restart.

## License

This project is licensed under the [Summit Free Use License](LICENSE). All copies and forks must retain the [NOTICE](NOTICE) file.

