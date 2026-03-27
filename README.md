# Actions Monitor

A lightweight Windows tray application that monitors GitHub Actions workflow statuses and notifies you when something changes.

![Status indicators: green = success, orange = running, red = failed]

## Features

- **Live status** — polls your configured workflows and shows green / orange / red status indicators
- **System tray** — minimises to tray; tray icon colour reflects the worst combined state across all workflows
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

```bash
git pull
pip install -r requirements.txt
```
