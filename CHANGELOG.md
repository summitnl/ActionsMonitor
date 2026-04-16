# Changelog

### 2026-04-16

- **Fix run timestamps showing UTC instead of local time** — the time displayed next to run numbers (e.g. "16 Apr 14:30") was parsed without timezone conversion, causing it to be offset from the user's local time. Now properly converts from UTC to the system's local timezone.

- **Immediate merged PR removal** — PR-mode rows for merged/closed PRs are now removed on the next poll cycle instead of waiting for the 5-minute stale timeout. The stale timeout is preserved as a fallback for edge cases (API failures, `max_prs` truncation).
- **Fix open PR filter bug** — when `_fetch_user_open_prs()` API call failed, the empty-set guard skipped run filtering entirely, causing merged PR rows to persist indefinitely. Now tracks API success separately so the filter works correctly even when the user has zero open PRs.
- **Linux system dependency check** — on startup, checks for required system libraries (GTK3, AppIndicator, paplay/aplay). Shows a dismissible warning dialog listing missing packages with install instructions. App continues running regardless.
- **Linux sound defaults** — new configs on Linux default to `"default"` sound (freedesktop system sound via paplay) instead of `"whistle"` (Windows-only winotify preset).
- **Resilient tray icon** — tray icon initialization wrapped in try/except so the app runs without a tray icon if system libraries are missing (e.g. no AppIndicator on Linux). Window close/minimize now falls back to iconify instead of withdraw when no tray is present, preventing the app from becoming invisible.
- **Code review fixes** — comprehensive cleanup pass addressing bugs, inefficiencies, and Linux gaps:
  - Fix mousewheel scrolling on Linux (was Windows-only `<MouseWheel>` event; added `Button-4`/`Button-5` bindings)
  - Fix window vanishing on minimize when tray icon is unavailable (close button now minimizes instead of hiding)
  - Fix update checker `target_commitish` comparison (could be a branch name, not a SHA)
  - Fix `StartupManager._exe_cmd()` for frozen builds (was using `__file__` which points to a temp dir)
  - Guard Windows-only code paths (`_check_focus_signal`, VBS cleanup) to skip on Linux
  - Remove redundant `_fetch_pr_draft()` API call per PR per poll (data already cached from open PRs fetch)
  - Cache `_make_base_icon()` result (was regenerated 7× for tray icons)
  - Remove duplicate `_REPR_PRIORITY` dict (was copy of module-level `_STATUS_PRIORITY`)
  - Extract shared `_set_row_bg` helper (deduplicate bg-walking in 3 places)
  - Consolidate `state.json` reads on startup (was read 3× independently)
  - Fix config watch interval to 5s (was 2s, docs said 5s)
  - Fix `_restripe_rows()` to stripe per-section instead of globally
  - Move `_review_cfg` dict to module-level constant (was rebuilt every UI update)
  - Add platform-aware `UI_FONT` constant (`"DejaVu Sans"` on Linux instead of `"Segoe UI"`)
  - Try multiple font files for question mark icon on Linux (`DejaVu Sans Bold`, `Liberation Sans Bold`, `FreeSans Bold`)
  - Remove duplicate `import ctypes` and unused variable in monitor enumeration
  - Remove dead methods (`_restore_window_state`, `_restore_collapse_state`, `_restore_always_on_top`, `_fetch_pr_draft`)
  - Remove unused `_SORT_KEYS` class variable
  - Move `base64`/`io` imports from inside `_build_ui` to module level
  - Extract `_stale_cfg` dict to module-level `_STALENESS_BADGE_CFG` constant
- **Always on top** — checkbox next to "Start with Windows" in the footer. Keeps the window above all other windows. State persisted in `state.json` and restored on startup.
- **Snooze rows** — failed workflow rows show a Zzz button below the status icon (with hover highlight). Click to snooze; right-click context menu also available on any row. Snoozed rows are visually dimmed (grey accent bar, muted text) and show a "SNOOZED" badge. Snoozed rows are excluded from the tray icon status aggregation so they won't turn the icon red. Notifications are suppressed for snoozed rows. Snooze auto-clears when a new run starts on that workflow. In-memory only — not persisted across restarts.
- **Fix duplicate daily releases** — the daily build's change-detection compared a branch name against a commit SHA, causing it to always detect "changes" and create a release even when nothing had changed. Now resolves `targetCommitish` to a full SHA before comparing.

### 2026-04-15

- **GitHub Actions CI** — added daily build workflow (05:00 UTC) and manual release workflow. Builds Windows `.exe` and Linux binary via PyInstaller, creates date-tagged GitHub Releases (e.g. `v2026.04.15`) with changelog in the release body. Binaries removed from git tracking.
- **Release-based auto-updater** — frozen builds now check the GitHub Releases API for updates on startup. Downloads the correct platform binary, swaps the executable in-place, and restarts. Source installs keep the existing git-based update flow.
- **Linux support** — fixed `ctypes.wintypes` unconditional import that prevented the app from starting on Linux. Guarded `iconbitmap` and VBScript focus signal to Windows only. Added Linux binary (`ActionsMonitor-linux`) built via WSL/PyInstaller. Added `src/build.sh` for building on Linux or via WSL. Added Linux sound notes to config template. Updated README with Linux instructions.
- **Sort controls per section** — each section header now has clickable Status, Updated, and Created sort labels. Click cycles through ascending (▲), descending (▼), and off. Only one sort active globally — activating one clears all others. Sort preference persists in `state.json`.
- **Notification click brings window to foreground** — clicking a toast notification body now raises the app window and blinks the relevant row(s) with a brief amber flash animation (3 cycles, 900ms). The "Open workflow" action button keeps its existing behavior. Uses a VBScript signal file mechanism for silent IPC between the notification click and the running app.
- **Stale notification suppression** — notifications older than `max_notification_age` (default `"1h"`) are now silently dropped. Prevents a flood of stale toasts after waking from sleep. For `new_run` notifications the run's start time is checked; for `success`/`failure` the run's last update time is used (so long-running jobs that just completed still notify). Configurable under `notifications.max_notification_age` using duration strings (`"30m"`, `"2h"`, etc.) or `0` to disable.

### 2026-04-14 (UI polish)

- **Refresh icon button** — replaced the text "Refresh" button in the header with a Lucide-style rotate-cw icon, matching the app's visual language.
- **Notification icon** — Windows toast notifications now display the app icon (amber play triangle) instead of a blank square.

### 2026-04-14 (code cleanup)

- **Code cleanup** — removed unused imports (`field`, `tkfont`), dead `_prev_conclusion(s)` tracking variables, extracted `_gh_headers()` helper (replaced 9 inline header constructions), extracted `_resolve_status()` helper (replaced 3 duplicated status-mapping blocks), extracted `_cache_pr()` helper (replaced 3 identical PR cache update blocks), consolidated state file I/O into `_load_state()`/`_write_state()`/`_persist_collapsed()` helpers, fixed redundant `config_mgr.get()` call in `_add_poller()`, and skipped `_generate_app_ico()` when `app.ico` already exists.

### 2026-04-14

- **PR staleness badge** — PR-mode rows now show a colour-escalating staleness badge (yellow/orange/red) based on how long since the PR was last updated. Thresholds are configurable with human-friendly durations (`"1d"`, `"3d"`, `"5d"`). New `parse_duration()` utility accepts `"30m"`, `"12h"`, `"2d12h"`, etc. — also used by `pr_stale_after` and `stale_after` which now accept the same format (plain integers still work).
- **IN REVIEW badge** — review status now distinguishes between "no reviews" (REVIEW PENDING, amber) and "has review comments but no formal decision" (IN REVIEW, blue).
- **Multiple PRs per branch** — PR-mode now shows separate rows when a branch has multiple PRs targeting different branches (e.g. `hotfix/fix-123 → acceptance` and `hotfix/fix-123 → production`). Each row displays its own target branch, PR number, draft status, review status, and build status independently.
- **Reliable DRAFT badge** — draft status is now refreshed every poll cycle (previously cached forever). The badge has a new bold amber style for better visibility.
- **Open PR discovery** — PR-mode now queries the GitHub Pulls API to find all your open PRs, ensuring that PRs with older CI runs (like long-lived drafts) still appear even when their workflow runs have fallen off the recent runs page. PR numbers, titles, and target branches are now reliably detected for all rows via the Pulls API fallback.
- **Closed PR cleanup** — PR-mode now filters out branches whose PRs have been closed or merged, so stale rows from completed work no longer linger in the list.
- **Scroll fix** — fixed empty space appearing above content when scrolling up.

### 2026-04-13

- **Refresh button** — click **Refresh** in the header to trigger an immediate re-poll of all workflows without waiting for the next interval.
- **PR review status** — PR-mode rows show a colour-coded review badge: green APPROVED, red CHANGES REQUESTED, or amber REVIEW PENDING. Updated each poll cycle.
- **PR title display** — PR-mode rows now show the pull request title as the main clickable title (opens the PR), with #number + branch as a subtitle (opens the build run).
- **Jira ticket links** — when `jira_base_url` is configured, Jira ticket IDs (e.g. `EDU-1234`) are extracted from branch names and shown as clickable badges on PR and actor-mode rows. Clicking opens the ticket in Jira.
- **Fix PR mode false success with multiple workflows** — PR-mode entries now support an `extra_workflows` list that aggregates status across multiple workflow files. The row shows the worst-of status (failure > running > queued > success), so integration tests still running or failing are no longer hidden behind a passing primary workflow. Notifications fire on aggregate status transitions.
- **Collapsible categories** — click any section header to collapse/expand its rows. Collapse state persists across restarts via `state.json`. Collapsed sections still contribute to the tray icon status.

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
