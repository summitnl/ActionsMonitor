<p align="center">
  <a href="https://github.com/WizX20">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="docs/wizx20.png">
      <img src="docs/wizx20-transparent.png" alt="WizX20" height="140">
    </picture>
  </a>
</p>

# Actions Monitor

A lightweight tray application that monitors GitHub Actions workflow statuses and notifies you when something changes. Runs on Windows and Linux.

> See the [Changelog](CHANGELOG.md) for updates.

## License

This project is licensed under the [WizX20 Free Use License](LICENSE). All copies and forks must retain the [NOTICE](NOTICE) file.

## Requirements

- **Windows** 10 / 11
- **Linux** with GTK3 (Ubuntu 22.04+, Fedora, etc.) — tray icon requires `gir1.2-ayatanaappindicator3-0.1`

## Install

![Application window](docs/application.png)

> **Note:** screenshot is from a build 2–3 releases back; the current UI looks slightly different.

### Windows — winget

> **Currently broken.** The winget publishing pipeline is temporarily disabled while we sort out a packaging issue, so the manifest is stale. Use Scoop or the direct download in the meantime.

```powershell
winget install WizX20.ActionsMonitor
```

### Windows — Scoop (recommended)

```powershell
scoop bucket add wizx20 https://github.com/WizX20/ActionsMonitor
scoop install actionsmonitor
```

### Direct download

Grab `ActionsMonitor.exe` (Windows) or `ActionsMonitor-linux` from [GitHub Releases](https://github.com/WizX20/ActionsMonitor/releases/latest).

> **Heads up:** the binary is unsigned, so the browser flags the `.exe` as unverified and Windows marks it blocked. Right-click the downloaded file → **Properties** → tick **Unblock** → **OK** before running. Prefer winget or Scoop to skip this step.

## Getting started

### Windows

1. Launch Actions Monitor — on first run it creates `config.yaml` from the template
2. Add your GitHub token and workflows (see [Configuration](#configuration) below)
3. The app hot-reloads the config, no restart needed

### Linux

1. Run `./ActionsMonitor-linux` — on first launch it creates `config.yaml` from the template
2. Add your GitHub token and workflows (see [Configuration](#configuration) below)
3. The app hot-reloads the config, no restart needed

> **Note:** On Linux, named notification sounds (`whistle`, `reminder`, etc.) are Windows-only. Use `"default"` for a system sound via paplay/aplay, or provide a path to an `.oga`/`.wav` file.

## Features

- **Live status** — polls your configured workflows and shows green / orange / red status indicators
- **PR mode** — monitor your own pull request builds: one row per active PR, with branch prefix tags, PR numbers, target branch indicators, and a DRAFT indicator. When a branch has multiple PRs (e.g. hotfix → acceptance and hotfix → production), each PR gets its own row. Stale rows auto-remove after a configurable timeout
- **System tray** — minimises to tray; tray icon colour reflects the worst combined state across all workflows
- **Toast notifications** — notified when a run starts, succeeds, or fails, with the app icon and an **Open workflow** button that takes you straight to the run
- **Per-workflow config** — different polling rates, branch filters, and notification overrides per workflow
- **Hot-reload** — edit `config.yaml` and the app picks up changes within seconds, no restart needed
- **Start with Windows** — toggle in the app footer; writes a registry entry for the current user (no admin required)

## Configuration

Open `config.yaml` (or click **Open config ↗** in the app footer). The file is heavily commented — see [`config.template.yaml`](config.template.yaml) for a full example with every option documented. The key things to fill in are:

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

There are four modes: **branch mode** (default) monitors a specific workflow+branch combo, **PR mode** monitors your own pull request builds, **actor mode** shows all your recent runs across a repo, and **URL mode** renders any GitHub Search query (e.g. `is:pr is:open review-requested:@me`) as a PR inbox. See [`config.template.yaml`](config.template.yaml) for URL-mode and actor-mode examples.

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

### Status colours

| Colour | Meaning |
|--------|---------|
| 🟢 Green | Last run succeeded |
| 🟠 Orange | Run in progress or queued |
| 🔴 Red | Last run failed |
| ⚫ Grey | Unknown / no runs found |

The tray icon follows the same logic, showing the worst state across all configured workflows.

### Updating

Binary builds (the `.exe` / Linux binary) check GitHub Releases shortly after startup. If a newer release is found, a dialog offers to download and install the update in-place, then restart.

Running from source does not auto-update — use `git pull` manually.

## Uninstall

- **winget:** `winget uninstall WizX20.ActionsMonitor`
- **Scoop:** `scoop uninstall actionsmonitor`
- **Direct download:** disable **Start with Windows** in the app footer, then delete the folder.

## Contributing

Running from source, building binaries, and the release pipeline are documented in [DEVGUIDE.md](DEVGUIDE.md).
