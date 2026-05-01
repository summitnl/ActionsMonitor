# Developer Guide

Contributor reference for Actions Monitor. End-user install and usage live in [README.md](README.md). For deep architecture (threading model, file layout, config resolution, visual system), see [CLAUDE.md](CLAUDE.md).

## Running from source

### Windows

```bat
src\dev-install.bat
```

Installs Python dependencies, copies `config.template.yaml` to `config.yaml` if missing, and launches the app via `pythonw`.

### Linux

```bash
pip3 install -r src/requirements.txt
sudo apt-get install -y python3-tk gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1
python3 src/main.py
```

Requires Python 3.10+.

## Building from source

### Windows — `ActionsMonitor.zip`

```bat
src\build.bat
```

Runs PyInstaller with `--onedir --noconsole`, embeds `app.ico`, bundles `config.template.yaml`, drops the dist folder in `dist/ActionsMonitor/` (exe + `_internal/`), and zips it to `ActionsMonitor.zip` in the repo root. The zip wraps a top-level `ActionsMonitor/` folder so the layout matches what winget's `NestedInstallerFiles.RelativeFilePath` and Scoop's `extract_dir` expect.

### Linux — `ActionsMonitor-linux.zip`

Build via WSL (Ubuntu 24.04). The Windows filesystem has permission issues with PyInstaller, so copy to `/tmp` first:

```bash
wsl -d Ubuntu-24.04 -- bash -c "cp -r /mnt/c/Repos/ActionsMonitor /tmp/am-build && cd /tmp/am-build && ~/.local/bin/pyinstaller --onedir --name ActionsMonitor-linux --add-data 'config.template.yaml:.' src/main.py && (cd /tmp/am-build/dist && zip -r ActionsMonitor-linux.zip ActionsMonitor-linux) && cp /tmp/am-build/dist/ActionsMonitor-linux.zip /mnt/c/Repos/ActionsMonitor/ && rm -rf /tmp/am-build"
```

Ubuntu 24.04 prerequisites:

```bash
sudo apt-get install -y python3-pip python3-tk python3-venv gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1
pip3 install --break-system-packages -r src/requirements.txt pyinstaller
```

## Release process

Releases are driven by `.github/workflows/release.yml` (manual dispatch only). The workflow:

1. **`check`** — first verifies that the latest completed CI run on `main` is `success` (`gh run list -w ci.yml -b main --status completed -L 1`); aborts the release if not. Then compares HEAD to the latest release's `targetCommitish`; skips if identical.
2. **`build`** — calls the reusable `_build.yml` workflow (shared with CI). Runs PyInstaller on `windows-latest` / `ubuntu-latest`; embeds a 7-char commit SHA into `src/version.py`.
3. **`release`** — tags `v$(date -u +%Y.%m.%d)`, deletes any same-day tag, creates the GitHub Release with `ActionsMonitor.zip` + `ActionsMonitor-linux.zip` attached, and uses the first dated block of `CHANGELOG.md` as the release body.
4. **`update-scoop`** — computes the SHA256 of the uploaded zip, bumps `bucket/actionsmonitor.json` (version, URL, hash, `extract_dir`), and commits back to `main`.
5. **`update-winget`** — runs `wingetcreate update WizX20.ActionsMonitor` on the new zip URL and submits a PR to `microsoft/winget-pkgs`.

### CI workflow

`.github/workflows/ci.yml` runs on every pull request and on every push to `main`. It calls the same `_build.yml` reusable workflow, so PR builds use the identical PyInstaller pipeline as releases — Windows + Linux artifacts are attached to each run for download.

#### Required status checks (branch protection)

Configure on GitHub: **Settings → Branches → Branch protection rules → `main`**. Enable **Require status checks to pass before merging** and select:

- `build / build-windows`
- `build / build-linux`

A PR with a failing CI run is then blocked from merging. Names appear in the picker after the first CI run lands; trigger one PR first if the list is empty.

### Required secrets

- **`WINGET_PAT`** — classic GitHub PAT with `public_repo` scope, issued from an account that maintains a fork of [`microsoft/winget-pkgs`](https://github.com/microsoft/winget-pkgs). `wingetcreate` pushes the manifest update to that fork and opens a PR upstream.

### First-time winget bootstrap

The automated `update-winget` job only works once `WizX20.ActionsMonitor` exists in `microsoft/winget-pkgs`. Do the first submission manually from a Windows box, against the first WizX20 zip release URL:

```powershell
winget install Microsoft.WingetCreate
wingetcreate new https://github.com/WizX20/ActionsMonitor/releases/download/v<TAG>/ActionsMonitor.zip
```

Fill the prompts:

| Field | Value |
|---|---|
| `PackageIdentifier` | `WizX20.ActionsMonitor` |
| `PackageVersion` | `<TAG without leading v>` |
| `Publisher` | `WizX20` |
| `PackageName` | `Actions Monitor` |
| `Moniker` | `actionsmonitor` |
| `License` | `BUSL-1.1` |
| `ShortDescription` | `Desktop monitor for GitHub Actions workflows and pull requests.` |
| `Homepage` | `https://github.com/WizX20/ActionsMonitor` |
| `InstallerType` | `zip` |
| `NestedInstallerType` | `portable` |
| `NestedInstallerFiles[0].RelativeFilePath` | `ActionsMonitor/ActionsMonitor.exe` |
| `Commands` | `actionsmonitor` |

Then `wingetcreate submit --token <PAT>`. Initial review can take days; subsequent CI-submitted PRs often merge within hours.

### Repo visibility

winget and Scoop both fetch release assets over unauthenticated HTTPS. The `WizX20/ActionsMonitor` repository must be **public** for the two install channels to work.

## Scoop bucket maintenance

- Manifest lives at `bucket/actionsmonitor.json`.
- `update-scoop` auto-bumps it on every release; manual edits are rarely needed.
- Users subscribe to the bucket directly from this repo:

  ```powershell
  scoop bucket add wizx20 https://github.com/WizX20/ActionsMonitor
  scoop install actionsmonitor
  ```

- `persist` keeps `config.yaml` and `state.json` between upgrades (Scoop stores them under `~/scoop/persist/actionsmonitor/`).

## Uninstalling a dev setup

```bat
src\dev-uninstall.bat
```

Removes the `HKCU\Software\Microsoft\Windows\CurrentVersion\Run\ActionsMonitor` startup entry and uninstalls the Python dependencies added by `dev-install.bat`.

## Conventions

- **Changelog** — always append a dated entry to `CHANGELOG.md` for user-visible changes. Never edit existing entries.
- **Config files** — never edit `config.yaml` directly; update `config.template.yaml` and have the user apply changes to their own config.
- **Commits** — create new commits; do not amend published commits. Do not skip pre-commit hooks.
