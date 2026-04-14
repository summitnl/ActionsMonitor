# Changelog

### 2026-04-14

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
