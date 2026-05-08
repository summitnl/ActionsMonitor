"""GitHub workflow pollers + shared status / dataclass primitives.

Owns the four `WorkflowPoller` variants (branch / PR / actor / URL), the
`WorkflowState` + `StatusEvent` dataclasses they emit onto the shared queue,
the snooze registry mutated from MainWindow, and the status-mapping helpers
used by both pollers and widgets.

One-way imports: depends on `gh_api` and `notifications`. Never imports from
`main` (PyInstaller's `__main__` / `main` double-load makes that a circular
re-execution trap — see CLAUDE.md).
"""

from __future__ import annotations

import queue
import re
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Optional

import requests

from gh_api import (
    _aggregate_review_status,  # noqa: F401  (re-exported for callers)
    _build_branch_url,
    _build_workflow_url,
    _cached_review_fetch,
    _cached_unresolved_fetch,
    _compile_bot_regex,
    _DEFAULT_BOT_PATTERN,
    _friendly_error,
    _github_api_get,
    _PR_CACHE_MAX,
    _prune_cache,
    _REVIEW_CACHE_MAX,
    fetch_actor_runs,
    fetch_github_username,
    fetch_latest_run,
    fetch_pr_runs,
    fetch_runs_by_sha,
    parse_actor_url,
    parse_workflow_url,
)
from notifications import NOTIF

if TYPE_CHECKING:  # avoid runtime import of main
    from main import ConfigManager


# ---------------------------------------------------------------------------
# Status constants — sourced from status.py (single source of truth) and
# re-exported so existing `from pollers import ST_*` call sites keep working.
# ---------------------------------------------------------------------------
from status import (  # noqa: F401  (re-exported)
    CONCLUSION_MAP,
    ST_CANCELLED,
    ST_FAILURE,
    ST_QUEUED,
    ST_RUNNING,
    ST_SKIPPED,
    ST_SUCCESS,
    ST_UNKNOWN,
    _resolve_status,
    _STATUS_PRIORITY,
)

POLL_DEFAULT = 60  # seconds


_NOTIF_DEFAULT_BY_MODE = {
    "branch": True, "pr": True, "actor": True, "url": False,
}


def section_flags(cfg_entry: dict) -> dict:
    """Resolve per-section flags with mode-aware defaults.

    `include_in_tray_status` — when False, this section's rows do not feed the
    tray icon's combined status. Default True for every mode.

    `notifications_enabled` — when False, suppresses toast/sound for this
    section. Default True for branch/pr/actor; False for url (URL mode rarely
    surfaces PRs the user authored, so notifications would be noisy).
    """
    mode = cfg_entry.get("mode", "branch")
    return {
        "include_in_tray_status": bool(cfg_entry.get("include_in_tray_status", True)),
        "notifications_enabled":  bool(cfg_entry.get(
            "notifications_enabled", _NOTIF_DEFAULT_BY_MODE.get(mode, True))),
    }


# ---------------------------------------------------------------------------
# Snooze registry — shared between MainWindow and pollers (thread-safe)
# ---------------------------------------------------------------------------
_snoozed_keys: set[tuple[int, Optional[str]]] = set()
_snoozed_lock = threading.Lock()


def _is_snoozed(wid: int, sub_key: Optional[str]) -> bool:
    """Thread-safe check whether a (wid, sub_key) row is currently snoozed."""
    with _snoozed_lock:
        return (wid, sub_key) in _snoozed_keys


def add_snooze(wid: int, sub_key: Optional[str]):
    with _snoozed_lock:
        _snoozed_keys.add((wid, sub_key))


def discard_snooze(wid: int, sub_key: Optional[str]):
    with _snoozed_lock:
        _snoozed_keys.discard((wid, sub_key))


def clear_snooze():
    with _snoozed_lock:
        _snoozed_keys.clear()


def replace_snoozed(keys):
    """Atomic bulk replace, used when restoring from state.json."""
    with _snoozed_lock:
        _snoozed_keys.clear()
        for k in keys:
            _snoozed_keys.add(k)


# ---------------------------------------------------------------------------
# Helpers — branch parsing, jira keys, duration parsing, age formatting
# ---------------------------------------------------------------------------
def _deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


_KNOWN_PREFIXES = {"hotfix", "chore", "feature", "bugfix", "release", "fix", "docs"}


def parse_branch_prefix(branch: str) -> tuple[Optional[str], str]:
    """Parse a branch name like 'hotfix/fix-login' into ('hotfix', 'fix-login').
    Returns (None, original) if no known prefix."""
    if "/" in branch:
        prefix, rest = branch.split("/", 1)
        if prefix.lower() in _KNOWN_PREFIXES:
            return prefix.lower(), rest
    return None, branch


_JIRA_KEY_RE = re.compile(r"(?i)\b([A-Z][A-Z0-9]+-\d+)\b")


def extract_jira_key(branch: str) -> Optional[str]:
    """Extract a Jira ticket key (e.g. EDU-1234) from a branch name."""
    m = _JIRA_KEY_RE.search(branch)
    return m.group(1).upper() if m else None


_DURATION_RE = re.compile(r"(\d+)\s*([smhd])", re.IGNORECASE)
_DURATION_MULT = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def parse_duration(value) -> int:
    """Parse a human-friendly duration to seconds (e.g. '1d', '12h', '2d12h'). Plain ints pass through."""
    if isinstance(value, (int, float)):
        return int(value)
    total = sum(int(n) * _DURATION_MULT[u.lower()] for n, u in _DURATION_RE.findall(str(value)))
    if total:
        return total
    try:
        return int(value)
    except (ValueError, TypeError):
        return 0


def _format_age(updated_at_str: str) -> str:
    """Convert an ISO 8601 timestamp to a short relative age string like '3d', '12h', '45m'."""
    try:
        dt = datetime.fromisoformat(updated_at_str.replace("Z", "+00:00"))
        delta = (datetime.now(dt.tzinfo) - dt).total_seconds()
        if delta < 3600:
            return f"{max(1, int(delta // 60))}m"
        elif delta < 86400:
            return f"{int(delta // 3600)}h"
        else:
            return f"{int(delta // 86400)}d"
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Workflow state + queue events
# ---------------------------------------------------------------------------
@dataclass
class WorkflowState:
    name:        str
    url:         str
    branch:      Optional[str]
    status:      str      = ST_UNKNOWN
    run_id:      Optional[int] = None
    run_url:     Optional[str] = None
    workflow_url: Optional[str] = None  # GitHub workflow overview URL (filtered by branch when known)
    branch_url:   Optional[str] = None  # GitHub branch tree URL (e.g. /tree/main)
    run_number:  Optional[int] = None
    started_at:  Optional[str] = None
    run_updated_at: Optional[str] = None  # ISO 8601 from GitHub run API (last status change)
    last_check:  Optional[datetime] = None
    error:       Optional[str] = None
    # PR mode fields
    head_branch:   Optional[str] = None
    branch_prefix: Optional[str] = None
    branch_short:  Optional[str] = None
    pr_number:     Optional[int] = None
    pr_title:      Optional[str] = None
    pr_url:        Optional[str] = None
    is_draft:      bool = False
    review_status: Optional[str] = None   # "approved" | "changes_requested" | "commented" | "pending" | None
    review_by_bot: bool = False           # True iff winning reviewer(s) all match bot regex
    pr_target:     Optional[str] = None   # target branch (e.g. "acceptance", "production")
    jira_key:      Optional[str] = None
    staleness_level: Optional[str] = None  # "slightly_stale" | "moderately_stale" | "very_stale"
    pr_updated_at:   Optional[str] = None  # ISO 8601 from GitHub PR API
    has_conflict:    bool = False          # True when PR mergeable_state == "dirty"
    unresolved_threads: int = 0            # count of unresolved review threads (GraphQL)


@dataclass
class StatusEvent:
    workflow_id: int
    new_state:   WorkflowState
    notif_type:  Optional[str] = None   # "new_run" | "success" | "failure" | None
    sub_key:     Optional[str] = None   # head branch for PR rows, None for regular rows
    removed:     bool = False           # signals the UI to remove a stale row


# ---------------------------------------------------------------------------
# Branch-mode poller (base class)
# ---------------------------------------------------------------------------
class WorkflowPoller(threading.Thread):
    def __init__(
        self,
        wid: int,
        cfg_entry: dict,
        config_mgr: "ConfigManager",
        event_queue: queue.Queue,
    ):
        super().__init__(daemon=True, name=f"poller-{wid}")
        self.wid         = wid
        self.cfg_entry   = cfg_entry
        self.config_mgr  = config_mgr
        self.event_queue = event_queue
        self._stop_evt   = threading.Event()
        self._poll_now   = threading.Event()

        url = cfg_entry.get("url", "")
        try:
            owner, repo, wf_file, url_branch = parse_workflow_url(url)
        except ValueError:
            owner = repo = wf_file = ""
            url_branch = None

        self.owner       = owner
        self.repo        = repo
        self.wf_file     = wf_file
        self.url_branch  = url_branch

        # configured branch overrides URL branch
        cfg_branch = cfg_entry.get("branch")
        self.branch = cfg_branch if cfg_branch else url_branch

        self.name_display = cfg_entry.get("name") or wf_file or url
        self._session = requests.Session()
        self._prev_run_id    : Optional[int] = None
        self._prev_status    : Optional[str] = None

    def stop(self):
        self._stop_evt.set()

    def trigger_poll(self):
        """Wake the poller to re-poll immediately."""
        self._poll_now.set()

    def _detect_notification(self, prev_run_id, cur_run_id, prev_api_status, cur_api_status, resolved_status) -> Optional[str]:
        """Determine notification type from a run state transition.
        Returns 'new_run', 'success', 'failure', or None."""
        if prev_run_id is not None and cur_run_id != prev_run_id:
            return "new_run"
        if (cur_run_id == prev_run_id
                and cur_api_status == "completed"
                and prev_api_status != "completed"):
            if resolved_status == ST_SUCCESS:
                return "success"
            if resolved_status == ST_FAILURE:
                return "failure"
        return None

    def _remove_sub_key(self, sk: str):
        """Send a removal event and clean up tracking state for a sub_key."""
        branch_part = sk.split("#")[0] if "#" in sk else sk
        dummy = WorkflowState(name=self.name_display, url=self.cfg_entry.get("url", ""),
                              branch=branch_part)
        self.event_queue.put(StatusEvent(self.wid, dummy, sub_key=sk, removed=True))

    def _emit_request_error(self, exc: BaseException, *, branch=None, sub_key=None):
        """Emit a status from a `requests` exception with a sensible label.

        HTTPError → ``HTTP {status}``; everything else → `_friendly_error()`.
        Centralises the HTTPError-vs-generic split that every poller's `except`
        block was repeating verbatim.
        """
        if isinstance(exc, requests.HTTPError) and exc.response is not None:
            label = f"HTTP {exc.response.status_code}"
        else:
            label = _friendly_error(exc)
        self._emit_error(label, branch=branch, sub_key=sub_key)

    def _emit_error(self, error: str = "", branch=None, sub_key=None):
        """Emit a ST_UNKNOWN state with an optional error message."""
        eff_branch = branch or self.branch
        state = WorkflowState(
            name=self.name_display,
            url=self.cfg_entry.get("url", ""),
            branch=branch,
            workflow_url=_build_workflow_url(self.owner, self.repo, self.wf_file, eff_branch),
            branch_url=_build_branch_url(self.owner, self.repo, eff_branch),
        )
        state.status = ST_UNKNOWN
        state.error = error or None
        self.event_queue.put(StatusEvent(self.wid, state, sub_key=sub_key))

    def run(self):
        while not self._stop_evt.is_set():
            self._poll()
            self._poll_now.clear()
            poll_rate = int(self.cfg_entry.get("polling_rate", POLL_DEFAULT))
            # Wake early if stop or poll_now is signalled
            deadline = time.monotonic() + poll_rate
            while not self._stop_evt.is_set() and not self._poll_now.is_set():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._stop_evt.wait(min(remaining, 1.0))

    def _poll(self):
        # Skip polling entirely while snoozed — no API calls, no status checks
        if _is_snoozed(self.wid, None):
            return

        cfg      = self.config_mgr.get()
        token    = cfg.get("github_token", "")
        notif_cfg = cfg.get("notifications", {})

        state = WorkflowState(
            name=self.name_display,
            url=self.cfg_entry.get("url", ""),
            branch=self.branch,
            workflow_url=_build_workflow_url(self.owner, self.repo, self.wf_file, self.branch),
            branch_url=_build_branch_url(self.owner, self.repo, self.branch),
        )

        if not self.owner:
            self._emit_error("Invalid workflow URL in config", branch=self.branch)
            return

        try:
            run = fetch_latest_run(self.owner, self.repo, self.wf_file, self.branch, token, session=self._session)
        except Exception as exc:
            self._emit_request_error(exc, branch=self.branch)
            return

        state.last_check = datetime.now()
        state.error = None

        if run is None:
            self._emit_error(branch=self.branch)
            return

        run_id    = run.get("id")
        api_status  = run.get("status")       # queued / in_progress / completed
        conclusion  = run.get("conclusion")   # success / failure / … / None

        state.status = _resolve_status(api_status, conclusion)

        state.run_id    = run_id
        state.run_url   = run.get("html_url")
        state.run_number = run.get("run_number")
        state.started_at = run.get("run_started_at") or run.get("created_at")
        state.run_updated_at = run.get("updated_at")

        # Determine what notification to send
        notif_type = self._detect_notification(
            self._prev_run_id, run_id, self._prev_status, api_status, state.status)

        self._prev_run_id     = run_id
        self._prev_status     = api_status

        self.event_queue.put(StatusEvent(self.wid, state, notif_type))

        # Fire notification
        if notif_type:
            self._fire_notification(notif_type, state, notif_cfg)

    def _fire_notification(self, notif_type: str, state: WorkflowState, global_notif: dict,
                           is_pr: bool = False, sub_key: Optional[str] = None):
        # Per-section opt-out (e.g. URL mode default off, or any entry that sets
        # notifications_enabled: false to silence a noisy section).
        if not section_flags(self.cfg_entry)["notifications_enabled"]:
            return
        # Suppress notifications for snoozed rows
        with _snoozed_lock:
            if (self.wid, sub_key) in _snoozed_keys:
                return
        # Suppress stale notifications (e.g. after waking from sleep)
        max_age = parse_duration(global_notif.get("max_notification_age", "1h"))
        if max_age > 0:
            # For new_run use started_at; for success/failure use run_updated_at (completion time)
            ts = state.started_at if notif_type == "new_run" else (state.run_updated_at or state.started_at)
            if ts:
                try:
                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    age = (datetime.now(dt.tzinfo) - dt).total_seconds()
                    if age > max_age:
                        return
                except Exception:
                    pass

        # Merge chain: global → (pr override) → per-workflow
        base = global_notif.get(notif_type, {})
        if is_pr:
            pr_notif = global_notif.get("pr", {})
            base = _deep_merge(base, pr_notif.get(notif_type, {}))
        wf_notif = self.cfg_entry.get("notifications", {})
        section = _deep_merge(base, wf_notif.get(notif_type, {}))
        if not section.get("enabled", True):
            return
        sound = section.get("sound", "default")

        title, message, line = self._build_notification(notif_type, state, is_pr=is_pr)
        url = state.run_url or state.pr_url or state.url
        NOTIF.notify(title, message, sound, url=url, notif_type=notif_type,
                     row_keys=[(self.wid, sub_key)], line=line)

    @staticmethod
    def _build_notification(notif_type: str, state: WorkflowState, is_pr: bool
                            ) -> tuple[str, str, str]:
        """Return (title, body, single-line summary) for a notification.

        Body is multi-line; line is what shows up when several notifications are
        batched together into one toast. No extra API calls — uses only fields
        already populated on `state`.
        """
        sym = {"new_run": "\u25b6", "success": "\u2713", "failure": "\u2717"}[notif_type]
        verb = {"new_run": "started", "success": "succeeded", "failure": "failed"}[notif_type]

        # Build branch label once — prefix/short available in PR/actor mode, plain branch in branch mode.
        if state.branch_prefix and state.branch_short:
            branch_lbl = f"{state.branch_prefix}/{state.branch_short}"
        else:
            branch_lbl = state.branch_short or state.branch or state.head_branch or ""

        run_tag = f"#{state.run_number}" if state.run_number else ""

        if is_pr and state.pr_number:
            title = f"{sym} {state.name} {verb}"
            body_lines: list[str] = []
            if state.pr_title:
                pr_t = state.pr_title if len(state.pr_title) <= 60 else state.pr_title[:57] + "\u2026"
                body_lines.append(f"PR #{state.pr_number} {pr_t}")
            else:
                body_lines.append(f"PR #{state.pr_number}")
            if branch_lbl and state.pr_target:
                body_lines.append(f"{branch_lbl} \u2192 {state.pr_target}")
            elif branch_lbl:
                body_lines.append(branch_lbl)
            tail = f"Run {run_tag}" if run_tag else ""
            if state.jira_key:
                tail = f"{state.jira_key}  \u2022  {tail}".strip(" \u2022 ")
            if tail:
                body_lines.append(tail)
            line = f"{sym} {state.name}: PR #{state.pr_number}"
            if branch_lbl:
                line += f" ({branch_lbl})"
            return title, "\n".join(body_lines), line

        title = f"{sym} {state.name} {verb}"
        body_lines = []
        if branch_lbl:
            body_lines.append(branch_lbl)
        tail = f"Run {run_tag}" if run_tag else ""
        if state.jira_key:
            tail = f"{state.jira_key}  \u2022  {tail}".strip(" \u2022 ")
        if tail:
            body_lines.append(tail)
        if not body_lines:
            body_lines.append(state.name)
        line = f"{sym} {state.name}"
        if branch_lbl:
            line += f": {branch_lbl}"
        if run_tag:
            line += f" {run_tag}"
        return title, "\n".join(body_lines), line


# ---------------------------------------------------------------------------
# PR-mode poller
# ---------------------------------------------------------------------------
class PRWorkflowPoller(WorkflowPoller):
    """Poller that shows one row per active PR branch instead of one fixed row."""

    def __init__(self, wid, cfg_entry, config_mgr, event_queue):
        super().__init__(wid, cfg_entry, config_mgr, event_queue)
        self._max_prs = int(cfg_entry.get("max_prs", 5))
        self._stale_after = parse_duration(cfg_entry.get("pr_stale_after", "5m"))
        # Extra workflow files to aggregate status from
        self._extra_wf_files: list[str] = list(cfg_entry.get("extra_workflows", []))
        # Per-branch tracking
        self._prev_run_ids:    dict[str, set[int]] = {}   # set of run IDs across all workflows
        self._prev_statuses:   dict[str, str] = {}        # aggregate status string
        self._last_seen:       dict[str, datetime] = {}
        # PR detail cache: pr_number → {draft: bool}
        self._pr_cache: dict[int, dict] = {}
        # Review status cache: pr_number → (status, fetch_time)
        self._review_cache: dict[int, tuple[Optional[str], float]] = {}
        self._review_cache_ttl: float = 120.0  # seconds — reviews change less often than CI
        # Mergeable state cache: pr_number → (has_conflict, fetch_time)
        self._mergeable_cache: dict[int, tuple[bool, float]] = {}
        self._mergeable_cache_ttl: float = 120.0
        # Unresolved review threads cache: pr_number → (count, fetch_time)
        self._unresolved_cache: dict[int, tuple[int, float]] = {}
        self._unresolved_cache_ttl: float = 120.0
        # Short TTL cache on top of the global ETag layer — skips issuing the
        # per-branch runs HTTP call entirely on rapid successive polls (manual
        # refresh bursts, overlapping workflows). Keyed by (wf_file, branch).
        self._branch_runs_cache: dict[tuple[str, str], tuple[list[dict], float]] = {}
        self._branch_runs_ttl: float = 30.0
        # Parsed staleness thresholds (refreshed on each poll from config)
        self._staleness_thresholds: list[tuple[int, str]] = self._parse_staleness(config_mgr.get())

    @staticmethod
    def _parse_staleness(cfg: dict) -> list[tuple[int, str]]:
        """Parse staleness thresholds from config, sorted descending by duration."""
        stale_cfg = cfg.get("staleness_thresholds", {})
        return sorted(
            [
                (parse_duration(stale_cfg.get("very_stale", "5d")), "very_stale"),
                (parse_duration(stale_cfg.get("moderately_stale", "3d")), "moderately_stale"),
                (parse_duration(stale_cfg.get("slightly_stale", "1d")), "slightly_stale"),
            ],
            key=lambda t: t[0],
            reverse=True,
        )

    def _cache_pr(self, pr_num: int, pr_data: dict):
        """Update the PR cache from a PR API response dict."""
        self._pr_cache[pr_num] = {
            "draft": pr_data.get("draft", False),
            "title": pr_data.get("title", ""),
            "base_ref": pr_data.get("base", {}).get("ref", ""),
            "updated_at": pr_data.get("updated_at", ""),
        }
        _prune_cache(self._pr_cache, _PR_CACHE_MAX)

    def _poll(self):
        cfg   = self.config_mgr.get()
        token = cfg.get("github_token", "")
        notif_cfg = cfg.get("notifications", {})
        bot_regex = _compile_bot_regex(cfg.get("bot_pattern", _DEFAULT_BOT_PATTERN))

        # Refresh staleness thresholds from config (cheap parse, avoids stale cache)
        self._staleness_thresholds = self._parse_staleness(cfg)

        # Resolve username
        try:
            username = fetch_github_username(token, session=self._session)
        except Exception as exc:
            self._emit_error(f"Cannot resolve GitHub user: {_friendly_error(exc)}")
            return
        if not username:
            self._emit_error("No token configured (PR mode requires a token)")
            return

        if not self.owner:
            self._emit_error("Invalid workflow URL in config")
            return

        # Fetch runs from primary workflow + any extra workflows
        all_wf_files = [self.wf_file] + self._extra_wf_files
        all_runs: list[dict] = []
        for wf_file in all_wf_files:
            try:
                runs = fetch_pr_runs(
                    self.owner, self.repo, wf_file, username, token,
                    per_page=self._max_prs * 2, session=self._session,
                )
                all_runs.extend(runs)
            except Exception as exc:
                if not all_runs and wf_file == self.wf_file:
                    self._emit_request_error(exc)
                    return
                # Extra workflow failed — skip silently

        # Fetch the user's open PRs — used to discover branches with old runs
        # AND to filter out branches whose PRs have been closed/merged.
        branches_with_runs = {r.get("head_branch") for r in all_runs}
        open_prs_ok = False
        try:
            open_prs = self._fetch_user_open_prs(username, token)
            open_prs_ok = True
        except Exception as e:
            # Don't drop closed-PR filtering silently — surface so token/network
            # issues are diagnosable. Other rows continue rendering.
            print(f"[poller {self.wid}] open PRs fetch failed: {e}", file=sys.stderr)
            open_prs = []
        open_pr_branches = {pr["branch"] for pr in open_prs}
        user_pr_numbers = {pr["number"] for pr in open_prs}
        # Group open PRs by branch — used as fallback when runs don't surface PR data
        # and to render branches with zero CI runs yet (new draft PRs).
        branch_to_open_prs: dict[str, list[dict]] = {}
        for pr in open_prs:
            branch_to_open_prs.setdefault(pr["branch"], []).append(pr)
        for pr in open_prs:
            branch = pr["branch"]
            if branch in branches_with_runs:
                continue
            # Fetch latest runs for this branch across all configured workflows
            for wf_file in all_wf_files:
                try:
                    runs = self._fetch_branch_runs(wf_file, branch, token)
                    all_runs.extend(runs)
                except Exception as e:
                    # Permanent 404s (renamed workflow file) look identical to
                    # transient timeouts here — emit so user can diagnose either.
                    print(
                        f"[poller {self.wid}] branch runs fetch failed "
                        f"({wf_file} on {branch}): {e}",
                        file=sys.stderr,
                    )
            branches_with_runs.add(branch)

        # Drop runs for branches that no longer have an open PR
        if open_prs_ok:
            all_runs = [r for r in all_runs if r.get("head_branch") in open_pr_branches]

        # Group all runs by head_branch, keeping latest per workflow file
        by_branch: dict[str, list[dict]] = {}
        seen_wf_per_branch: dict[str, set[str]] = {}
        for run in all_runs:
            hb = run.get("head_branch", "")
            if not hb:
                continue
            wf_path = run.get("path", "")  # e.g. ".github/workflows/acceptance-pr.yml"
            if hb not in by_branch:
                by_branch[hb] = []
                seen_wf_per_branch[hb] = set()
            # Keep only the latest run per workflow file per branch
            if wf_path not in seen_wf_per_branch[hb]:
                seen_wf_per_branch[hb].add(wf_path)
                by_branch[hb].append(run)

        # Ensure every open-PR branch is represented, even if it has zero runs yet
        # (new drafts that haven't triggered CI). Empty list = render with unknown status.
        for branch in open_pr_branches:
            by_branch.setdefault(branch, [])

        # Limit to max_prs (order by most recent run across all workflows)
        branch_order = sorted(
            by_branch.keys(),
            key=lambda b: max(
                (r.get("run_started_at") or r.get("created_at") or "" for r in by_branch[b]),
                default="",
            ),
            reverse=True,
        )
        active_branches = {b: by_branch[b] for b in branch_order[:self._max_prs]}
        now = datetime.now()

        active_sub_keys: set[str] = set()

        for branch_name, branch_runs in active_branches.items():
            # Collect unique PR numbers across all runs for this branch.
            # Filter to PRs authored by the user — runs attach all PRs on a
            # branch, so other users' PRs would leak in otherwise.
            pr_numbers_seen: dict[int, str] = {}  # pr_num -> base_ref
            for r in branch_runs:
                for pr_entry in (r.get("pull_requests") or []):
                    pr_num = pr_entry.get("number")
                    if not pr_num or pr_num in pr_numbers_seen:
                        continue
                    if open_prs_ok and pr_num not in user_pr_numbers:
                        continue
                    pr_numbers_seen[pr_num] = pr_entry.get("base", {}).get("ref", "")

            # Fallback when workflow runs lack PR data: prefer already-fetched
            # open_prs (covers zero-run branches), fall back to Pulls API query.
            if not pr_numbers_seen:
                for pr_info in branch_to_open_prs.get(branch_name, []):
                    pr_numbers_seen[pr_info["number"]] = pr_info["base_ref"]
            if not pr_numbers_seen:
                for pr_info in self._fetch_prs_for_branch(branch_name, token):
                    if open_prs_ok and pr_info["number"] not in user_pr_numbers:
                        continue
                    pr_numbers_seen[pr_info["number"]] = pr_info["base_ref"]

            # Build groups: one per PR, or a single fallback group if no PRs found
            if not pr_numbers_seen:
                pr_groups: list[tuple[Optional[int], Optional[str], list[dict]]] = [
                    (None, None, branch_runs)
                ]
            else:
                pr_groups = []
                for pr_num, base_ref in pr_numbers_seen.items():
                    # Include runs that reference this PR, plus runs with no PR data (shared CI)
                    relevant = [
                        r for r in branch_runs
                        if pr_num in {p.get("number") for p in (r.get("pull_requests") or [])}
                        or not r.get("pull_requests")
                    ]
                    if not relevant:
                        relevant = branch_runs
                    pr_groups.append((pr_num, base_ref, relevant))

            for pr_num, pr_base_ref, group_runs in pr_groups:
                sub_key = f"{branch_name}#{pr_num}" if pr_num is not None else branch_name
                active_sub_keys.add(sub_key)
                self._last_seen[sub_key] = now

                # Snoozed rows: emit a minimal event (from already-fetched bulk data) so the
                # row renders after restart, then skip per-PR extras (draft/review fetches)
                # and notifications. Row stays in active_sub_keys so it isn't culled as stale.
                if _is_snoozed(self.wid, sub_key):
                    run_statuses = [
                        _resolve_status(r.get("status"), r.get("conclusion"))
                        for r in group_runs
                    ]
                    agg_status = _worst_status(set(run_statuses)) if run_statuses else ST_UNKNOWN
                    snoozed_state = WorkflowState(
                        name=self.name_display,
                        url=self.cfg_entry.get("url", ""),
                        branch=branch_name,
                        head_branch=branch_name,
                        branch_url=_build_branch_url(self.owner, self.repo, branch_name),
                    )
                    snoozed_state.last_check = now
                    snoozed_state.status = agg_status
                    prefix, short = parse_branch_prefix(branch_name)
                    snoozed_state.branch_prefix = prefix
                    snoozed_state.branch_short = short
                    snoozed_state.jira_key = extract_jira_key(branch_name)
                    if pr_num is not None:
                        snoozed_state.pr_number = pr_num
                        snoozed_state.pr_target = pr_base_ref or ""
                        snoozed_state.pr_url = (
                            f"https://github.com/{self.owner}/{self.repo}/pull/{pr_num}"
                        )
                        cached = self._pr_cache.get(pr_num, {})
                        snoozed_state.pr_title = cached.get("title")
                        snoozed_state.is_draft = cached.get("draft", False)
                    self.event_queue.put(
                        StatusEvent(self.wid, snoozed_state, sub_key=sub_key))
                    continue

                # Determine per-run statuses and pick the aggregate + representative run
                run_statuses: list[str] = []
                representative_run: Optional[dict] = None
                rep_priority = -1

                for run in group_runs:
                    api_status = run.get("status")
                    conclusion = run.get("conclusion")
                    st = _resolve_status(api_status, conclusion)
                    run_statuses.append(st)

                    p = _STATUS_PRIORITY.get(st, 0)
                    if p > rep_priority:
                        rep_priority = p
                        representative_run = run

                if representative_run is None and group_runs:
                    representative_run = group_runs[0]

                # Aggregate status (worst wins). Empty runs = unknown (zero-CI drafts).
                agg_status = _worst_status(set(run_statuses)) if run_statuses else ST_UNKNOWN

                state = WorkflowState(
                    name=self.name_display,
                    url=self.cfg_entry.get("url", ""),
                    branch=branch_name,
                    head_branch=branch_name,
                    branch_url=_build_branch_url(self.owner, self.repo, branch_name),
                )
                state.last_check = now
                state.status     = agg_status
                if representative_run is not None:
                    run = representative_run
                    state.run_id     = run.get("id")
                    state.run_url    = run.get("html_url")
                    state.run_number = run.get("run_number")
                    state.started_at = run.get("run_started_at") or run.get("created_at")
                    state.run_updated_at = run.get("updated_at")

                # Parse branch prefix
                prefix, short = parse_branch_prefix(branch_name)
                state.branch_prefix = prefix
                state.branch_short  = short

                # PR info
                if pr_num is not None:
                    state.pr_number = pr_num
                    state.pr_target = pr_base_ref
                    # PR details already cached by _fetch_user_open_prs / _fetch_prs_for_branch
                    cached = self._pr_cache.get(pr_num, {})
                    state.is_draft = cached.get("draft", False)
                    state.pr_title = cached.get("title")
                    if not state.pr_target:
                        state.pr_target = cached.get("base_ref", "")
                    state.pr_url = f"https://github.com/{self.owner}/{self.repo}/pull/{pr_num}"
                    state.review_status, state.review_by_bot = self._fetch_pr_review_status(
                        pr_num, token, bot_regex)
                    state.has_conflict  = self._fetch_pr_mergeable(pr_num, token)
                    state.unresolved_threads = self._fetch_pr_unresolved_threads(pr_num, token)

                    # Compute PR staleness from updated_at
                    updated_at_str = self._pr_cache.get(pr_num, {}).get("updated_at", "")
                    if updated_at_str:
                        state.pr_updated_at = updated_at_str
                        try:
                            updated_dt = datetime.fromisoformat(updated_at_str.replace("Z", "+00:00"))
                            age_secs = (datetime.now(updated_dt.tzinfo) - updated_dt).total_seconds()
                            for threshold_secs, level in self._staleness_thresholds:
                                if age_secs >= threshold_secs:
                                    state.staleness_level = level
                                    break
                        except Exception:
                            pass

                # Jira ticket key from branch name
                state.jira_key = extract_jira_key(branch_name)

                # Determine notification based on aggregate status transitions
                notif_type: Optional[str] = None
                cur_run_ids = {r.get("id") for r in group_runs}
                prev_rids   = self._prev_run_ids.get(sub_key, set())
                prev_agg    = self._prev_statuses.get(sub_key)

                # Fire "new_run" only when a run ID we haven't seen appears.
                # Pure shrinkage (GitHub GC'd an old run, no new one) must not
                # notify — we'd spam the user every time GitHub prunes history.
                if prev_rids and not cur_run_ids.issubset(prev_rids):
                    notif_type = "new_run"
                elif prev_agg and prev_agg != agg_status:
                    if agg_status == ST_SUCCESS:
                        notif_type = "success"
                    elif agg_status == ST_FAILURE:
                        notif_type = "failure"

                self._prev_run_ids[sub_key]     = cur_run_ids
                self._prev_statuses[sub_key]    = agg_status

                self.event_queue.put(StatusEvent(self.wid, state, notif_type, sub_key=sub_key))

                if notif_type:
                    self._fire_notification(notif_type, state, notif_cfg, is_pr=True, sub_key=sub_key)

        # Detect stale sub_keys
        for sk in list(self._last_seen.keys()):
            if sk in active_sub_keys:
                continue
            # If open-PR list is reliable and branch is gone, remove immediately
            branch_part = sk.split("#")[0] if "#" in sk else sk
            if open_prs_ok and branch_part not in open_pr_branches:
                self._remove_sub_key(sk)
                continue
            # Fallback: stale timeout for rows that vanish for other reasons
            elapsed = (now - self._last_seen[sk]).total_seconds()
            if elapsed >= self._stale_after:
                self._remove_sub_key(sk)

    def _fetch_user_open_prs(self, username: str, token: str) -> list[dict]:
        """Fetch open PRs authored by the user. Returns list of {number, branch, base_ref}.
        Uses the creator= API filter to avoid fetching all repo PRs, but re-checks
        user.login client-side — GitHub's creator= filter is loose and occasionally
        returns PRs authored by someone else (observed: foreign PRs leaking in)."""
        url = (
            f"https://api.github.com/repos/{self.owner}/{self.repo}"
            f"/pulls?state=open&sort=updated&direction=desc&per_page=50"
            f"&creator={username}"
        )
        username_lc = username.lower()
        results = []
        for pr in _github_api_get(url, token, self._session):
            pr_num = pr.get("number")
            if not pr_num:
                continue
            author = (pr.get("user") or {}).get("login", "")
            if author.lower() != username_lc:
                continue
            branch = pr.get("head", {}).get("ref", "")
            base_ref = pr.get("base", {}).get("ref", "")
            self._cache_pr(pr_num, pr)
            results.append({"number": pr_num, "branch": branch, "base_ref": base_ref})
        return results

    def _fetch_branch_runs(self, wf_file: str, branch: str, token: str) -> list[dict]:
        """Fetch latest workflow runs for a specific branch."""
        key = (wf_file, branch)
        cached = self._branch_runs_cache.get(key)
        if cached is not None:
            runs, fetched_at = cached
            if time.monotonic() - fetched_at < self._branch_runs_ttl:
                return runs
        url = (
            f"https://api.github.com/repos/{self.owner}/{self.repo}"
            f"/actions/workflows/{wf_file}/runs"
        )
        params = {"branch": branch, "per_page": 1}
        runs = _github_api_get(url, token, self._session, params).get("workflow_runs", [])
        self._branch_runs_cache[key] = (runs, time.monotonic())
        _prune_cache(self._branch_runs_cache, 200)
        return runs

    def _fetch_prs_for_branch(self, branch: str, token: str) -> list[dict]:
        """Fetch open PRs for a head branch. Returns list of {number, base_ref}."""
        try:
            url = (
                f"https://api.github.com/repos/{self.owner}/{self.repo}"
                f"/pulls?head={self.owner}:{branch}&state=open&per_page=10"
            )
            results = []
            for pr in _github_api_get(url, token, self._session):
                pr_num = pr.get("number")
                if pr_num:
                    self._cache_pr(pr_num, pr)
                    results.append({"number": pr_num, "base_ref": pr.get("base", {}).get("ref", "")})
            return results
        except Exception:
            return []

    def _remove_sub_key(self, sk: str):
        super()._remove_sub_key(sk)
        self._last_seen.pop(sk, None)
        self._prev_run_ids.pop(sk, None)
        self._prev_statuses.pop(sk, None)
        # Evict PR caches for the removed sub_key's PR number
        pr_num = self._pr_num_from_sub_key(sk)
        if pr_num is not None:
            self._pr_cache.pop(pr_num, None)
            self._review_cache.pop(pr_num, None)
            self._mergeable_cache.pop(pr_num, None)
            self._unresolved_cache.pop(pr_num, None)

    @staticmethod
    def _pr_num_from_sub_key(sk: str) -> Optional[int]:
        """Extract the PR number from a sub_key like 'branch#123'."""
        if "#" in sk:
            try:
                return int(sk.rsplit("#", 1)[1])
            except (ValueError, IndexError):
                pass
        return None

    def _fetch_pr_review_status(self, pr_number: int, token: str,
                                bot_regex: Optional[re.Pattern] = None
                                ) -> tuple[Optional[str], bool]:
        """Fetch the aggregate review status for a PR.
        Returns (status, by_bot) where status \u2208 {'approved','changes_requested',
        'commented','pending', None}. Cached for _review_cache_ttl seconds."""
        url = (
            f"https://api.github.com/repos/{self.owner}/{self.repo}"
            f"/pulls/{pr_number}/reviews"
        )
        return _cached_review_fetch(
            url, token, self._session,
            self._review_cache, pr_number, self._review_cache_ttl,
            bot_regex,
        )

    def _fetch_pr_mergeable(self, pr_number: int, token: str) -> bool:
        """Return True if the PR has merge conflicts (mergeable_state == 'dirty').
        Cached for _mergeable_cache_ttl seconds. GitHub computes mergeable lazily \u2014
        first call after a push may return null; we return the cached value in that case."""
        cached = self._mergeable_cache.get(pr_number)
        if cached is not None:
            val, fetched_at = cached
            if time.monotonic() - fetched_at < self._mergeable_cache_ttl:
                return val
        url = f"https://api.github.com/repos/{self.owner}/{self.repo}/pulls/{pr_number}"
        try:
            data = _github_api_get(url, token, self._session)
            state = data.get("mergeable_state", "unknown")
            # GitHub computes mergeable lazily; "unknown" means not ready yet \u2014
            # retry next poll instead of caching a false negative.
            if state == "unknown":
                return cached[0] if cached else False
            result = (state == "dirty")
            self._mergeable_cache[pr_number] = (result, time.monotonic())
            _prune_cache(self._mergeable_cache, _REVIEW_CACHE_MAX)
            return result
        except Exception:
            return cached[0] if cached else False

    def _fetch_pr_unresolved_threads(self, pr_number: int, token: str) -> int:
        """Count unresolved review threads via GraphQL, cached for _unresolved_cache_ttl."""
        return _cached_unresolved_fetch(
            self.owner, self.repo, pr_number, token, self._session,
            self._unresolved_cache, pr_number, self._unresolved_cache_ttl,
        )


# ---------------------------------------------------------------------------
# Actor-mode poller
# ---------------------------------------------------------------------------
class ActorWorkflowPoller(WorkflowPoller):
    """Poller that shows one row per recent workflow run by the authenticated user."""

    def __init__(self, wid, cfg_entry, config_mgr, event_queue):
        super().__init__(wid, cfg_entry, config_mgr, event_queue)
        # Parse actor URL (overwrite parent's owner/repo which may be empty)
        url = cfg_entry.get("url", "")
        try:
            owner, repo, _ = parse_actor_url(url)
            self.owner = owner
            self.repo = repo
        except ValueError:
            pass
        self._max_runs = int(cfg_entry.get("max_runs", 10))
        self._stale_after = parse_duration(cfg_entry.get("stale_after", "5m"))
        self._filter = cfg_entry.get("filter", "all")
        # Per-run tracking, keyed by composite "workflow_id:head_branch"
        self._prev_run_ids:     dict[str, int] = {}
        self._prev_statuses:    dict[str, str] = {}
        self._last_seen:        dict[str, datetime] = {}

    def _poll(self):
        cfg   = self.config_mgr.get()
        token = cfg.get("github_token", "")
        notif_cfg = cfg.get("notifications", {})

        # Resolve username
        try:
            username = fetch_github_username(token, session=self._session)
        except Exception as exc:
            self._emit_error(f"Cannot resolve GitHub user: {_friendly_error(exc)}")
            return
        if not username:
            self._emit_error("No token configured (actor mode requires a token)")
            return

        if not self.owner:
            self._emit_error("Invalid actor URL in config")
            return

        conclusion_filter = "failure" if self._filter == "failed" else None
        try:
            runs = fetch_actor_runs(
                self.owner, self.repo, username, token,
                per_page=self._max_runs * 3, session=self._session,
                conclusion=conclusion_filter,
            )
        except Exception as exc:
            self._emit_request_error(exc)
            return

        # Client-side filter: when filter is "failed", also keep in-progress runs
        if self._filter == "failed":
            runs = [r for r in runs if r.get("conclusion") in ("failure", "timed_out", "action_required", None)]

        # Group by workflow+branch, take latest per combo
        by_key: dict[str, dict] = {}
        for run in runs:
            wf_name = run.get("name", "")
            hb = run.get("head_branch", "")
            composite = f"{wf_name}:{hb}"
            if composite not in by_key:
                by_key[composite] = run

        active_keys = dict(list(by_key.items())[:self._max_runs])
        now = datetime.now()

        for composite_key, run in active_keys.items():
            self._last_seen[composite_key] = now

            # Snoozed rows: emit minimal state from bulk data so the row renders after restart,
            # skip notifications and transition tracking.
            if _is_snoozed(self.wid, composite_key):
                hb_snz = run.get("head_branch", "")
                wf_file_snz = (run.get("path", "") or "").rsplit("/", 1)[-1]
                snoozed_state = WorkflowState(
                    name=run.get("name", "unknown"),
                    url=self.cfg_entry.get("url", ""),
                    branch=hb_snz,
                    head_branch=hb_snz,
                    workflow_url=_build_workflow_url(self.owner, self.repo, wf_file_snz, hb_snz),
                    branch_url=_build_branch_url(self.owner, self.repo, hb_snz),
                )
                snoozed_state.last_check = now
                snoozed_state.status = _resolve_status(
                    run.get("status"), run.get("conclusion"))
                snoozed_state.run_id = run.get("id")
                snoozed_state.run_url = run.get("html_url")
                snoozed_state.run_number = run.get("run_number")
                if hb_snz:
                    prefix, short = parse_branch_prefix(hb_snz)
                    snoozed_state.branch_prefix = prefix
                    snoozed_state.branch_short = short
                    snoozed_state.jira_key = extract_jira_key(hb_snz)
                self.event_queue.put(
                    StatusEvent(self.wid, snoozed_state, sub_key=composite_key))
                continue

            run_id     = run.get("id")
            api_status = run.get("status")
            conclusion = run.get("conclusion")
            hb         = run.get("head_branch", "")
            wf_name    = run.get("name", "unknown")
            wf_file_active = (run.get("path", "") or "").rsplit("/", 1)[-1]

            state = WorkflowState(
                name=wf_name,
                url=self.cfg_entry.get("url", ""),
                branch=hb,
                head_branch=hb,
                workflow_url=_build_workflow_url(self.owner, self.repo, wf_file_active, hb),
                branch_url=_build_branch_url(self.owner, self.repo, hb),
            )
            state.last_check = now

            state.status = _resolve_status(api_status, conclusion)

            state.run_id     = run_id
            state.run_url    = run.get("html_url")
            state.run_number = run.get("run_number")
            state.started_at = run.get("run_started_at") or run.get("created_at")
            state.run_updated_at = run.get("updated_at")

            # Parse branch prefix
            if hb:
                prefix, short = parse_branch_prefix(hb)
                state.branch_prefix = prefix
                state.branch_short  = short
                state.jira_key = extract_jira_key(hb)

            # Determine notification
            notif_type = self._detect_notification(
                self._prev_run_ids.get(composite_key), run_id,
                self._prev_statuses.get(composite_key), api_status, state.status)

            self._prev_run_ids[composite_key]     = run_id
            self._prev_statuses[composite_key]    = api_status

            self.event_queue.put(StatusEvent(self.wid, state, notif_type, sub_key=composite_key))

            if notif_type:
                self._fire_notification(notif_type, state, notif_cfg, is_pr=False, sub_key=composite_key)

        # Detect stale entries
        for key in list(self._last_seen.keys()):
            if key in active_keys:
                continue
            elapsed = (now - self._last_seen[key]).total_seconds()
            if elapsed >= self._stale_after:
                self._remove_sub_key(key)

    def _remove_sub_key(self, sk: str):
        super()._remove_sub_key(sk)
        self._last_seen.pop(sk, None)
        self._prev_run_ids.pop(sk, None)
        self._prev_statuses.pop(sk, None)


# ---------------------------------------------------------------------------
# URL-mode poller
# ---------------------------------------------------------------------------
class URLQueryPoller(WorkflowPoller):
    """Poller that runs an arbitrary GitHub Search API query and renders each PR result.

    Uses GET /search/issues?q=<query> \u2014 supports the full GitHub PR filter syntax
    (see https://docs.github.com/en/search-github/searching-on-github/searching-issues-and-pull-requests).
    Only pull-request results are rendered; issue-only hits are skipped.

    The row status comes from the review state rather than CI: approved \u2192 success icon,
    changes-requested \u2192 failure icon, anything else \u2192 unknown icon. This keeps URL
    sections out of the tray status tree for pending/commented PRs while still
    surfacing review signal on the row itself.
    """

    def __init__(self, wid, cfg_entry, config_mgr, event_queue):
        super().__init__(wid, cfg_entry, config_mgr, event_queue)
        self.query = (cfg_entry.get("query") or "").strip()
        self._max_results = int(cfg_entry.get("max_results", 20))
        self._stale_after = parse_duration(cfg_entry.get("stale_after", "5m"))
        self._last_seen: dict[str, datetime] = {}
        # Caches keyed by (owner, repo, pr_num) — URL queries span repos
        self._pr_cache: dict[tuple[str, str, int], dict] = {}
        self._review_cache: dict[tuple[str, str, int], tuple[Optional[str], float]] = {}
        self._review_cache_ttl: float = 120.0
        self._unresolved_cache: dict[tuple[str, str, int], tuple[int, float]] = {}
        self._unresolved_cache_ttl: float = 120.0
        self._staleness_thresholds = PRWorkflowPoller._parse_staleness(config_mgr.get())

    def _poll(self):
        cfg = self.config_mgr.get()
        token = cfg.get("github_token", "")
        bot_regex = _compile_bot_regex(cfg.get("bot_pattern", _DEFAULT_BOT_PATTERN))

        if not self.query:
            self._emit_error("No 'query' configured for URL mode")
            return
        if not token:
            self._emit_error("URL mode requires a GitHub token")
            return

        query = self.query
        if "@me" in query:
            try:
                username = fetch_github_username(token, session=self._session)
            except Exception as exc:
                self._emit_error(f"Cannot resolve @me: {_friendly_error(exc)}")
                return
            if not username:
                self._emit_error("Cannot resolve @me — no user")
                return
            query = query.replace("@me", username)

        self._staleness_thresholds = PRWorkflowPoller._parse_staleness(cfg)

        try:
            data = _github_api_get(
                "https://api.github.com/search/issues",
                token, self._session,
                params={
                    "q": query,
                    "per_page": self._max_results,
                    "sort": "updated",
                    "order": "desc",
                },
            )
        except Exception as exc:
            self._emit_request_error(exc)
            return

        items = data.get("items", []) or []
        now = datetime.now()
        active: set[str] = set()

        for item in items:
            if not item.get("pull_request"):
                continue
            repo_url = item.get("repository_url", "")
            parts = repo_url.rstrip("/").split("/")
            if len(parts) < 2:
                continue
            owner, repo = parts[-2], parts[-1]
            pr_num = item.get("number")
            if not pr_num:
                continue

            sub_key = f"{owner}/{repo}#{pr_num}"
            active.add(sub_key)
            self._last_seen[sub_key] = now

            # Snoozed rows: emit a minimal state built from the bulk search result so the
            # row renders after restart, skip per-PR detail + review fetches.
            if _is_snoozed(self.wid, sub_key):
                cached_detail = self._pr_cache.get((owner, repo, pr_num)) or {}
                head_branch = cached_detail.get("head_ref", "")
                snoozed_state = WorkflowState(
                    name=f"{owner}/{repo}",
                    url=item.get("html_url", ""),
                    branch=head_branch or None,
                    head_branch=head_branch or None,
                    branch_url=_build_branch_url(owner, repo, head_branch) if head_branch else None,
                )
                snoozed_state.last_check = now
                snoozed_state.status = ST_UNKNOWN
                snoozed_state.pr_number = pr_num
                snoozed_state.pr_title = item.get("title") or None
                snoozed_state.pr_url = item.get("html_url", "")
                snoozed_state.pr_target = cached_detail.get("base_ref", "")
                snoozed_state.is_draft = cached_detail.get(
                    "draft", bool(item.get("draft", False)))
                if head_branch:
                    prefix, short = parse_branch_prefix(head_branch)
                    snoozed_state.branch_prefix = prefix
                    snoozed_state.branch_short = short
                    snoozed_state.jira_key = extract_jira_key(head_branch)
                self.event_queue.put(
                    StatusEvent(self.wid, snoozed_state, sub_key=sub_key))
                continue

            pr_detail     = self._fetch_pr_detail(owner, repo, pr_num, token)
            review_status, review_by_bot = self._fetch_review_status(
                owner, repo, pr_num, token, bot_regex)

            head_branch = (pr_detail or {}).get("head_ref", "")
            head_sha    = (pr_detail or {}).get("head_sha", "")
            latest_run = self._fetch_latest_run_for_sha(
                owner, repo, head_sha, token) if head_sha else None

            if latest_run is not None:
                row_status = _resolve_status(
                    latest_run.get("status"), latest_run.get("conclusion"))
            else:
                row_status = ST_UNKNOWN

            state = WorkflowState(
                name=f"{owner}/{repo}",
                url=item.get("html_url", ""),
                branch=head_branch or None,
                head_branch=head_branch or None,
                branch_url=_build_branch_url(owner, repo, head_branch) if head_branch else None,
            )
            state.last_check    = now
            state.status        = row_status
            if latest_run is not None:
                state.run_id         = latest_run.get("id")
                state.run_url        = latest_run.get("html_url")
                state.run_number     = latest_run.get("run_number")
                state.started_at     = (latest_run.get("run_started_at")
                                        or latest_run.get("created_at"))
                state.run_updated_at = latest_run.get("updated_at")
            state.pr_number     = pr_num
            state.pr_title      = item.get("title") or None
            state.pr_url        = item.get("html_url", "")
            state.pr_target     = (pr_detail or {}).get("base_ref", "")
            state.is_draft      = (pr_detail or {}).get("draft", bool(item.get("draft", False)))
            state.review_status = review_status
            state.review_by_bot = review_by_bot
            state.has_conflict  = (pr_detail or {}).get("mergeable_state") == "dirty"
            state.unresolved_threads = self._fetch_unresolved_threads(owner, repo, pr_num, token)

            updated_at_str = item.get("updated_at", "")
            if updated_at_str:
                state.pr_updated_at = updated_at_str
                try:
                    updated_dt = datetime.fromisoformat(updated_at_str.replace("Z", "+00:00"))
                    age_secs = (datetime.now(updated_dt.tzinfo) - updated_dt).total_seconds()
                    for threshold_secs, level in self._staleness_thresholds:
                        if age_secs >= threshold_secs:
                            state.staleness_level = level
                            break
                except Exception:
                    pass

            if head_branch:
                prefix, short = parse_branch_prefix(head_branch)
                state.branch_prefix = prefix
                state.branch_short  = short
                state.jira_key      = extract_jira_key(head_branch)

            self.event_queue.put(StatusEvent(self.wid, state, sub_key=sub_key))

        for sk in list(self._last_seen.keys()):
            if sk in active:
                continue
            elapsed = (now - self._last_seen[sk]).total_seconds()
            if elapsed >= self._stale_after:
                self._remove_sub_key(sk)

    def _fetch_pr_detail(self, owner: str, repo: str, pr_num: int, token: str) -> Optional[dict]:
        key = (owner, repo, pr_num)
        try:
            data = _github_api_get(
                f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_num}",
                token, self._session,
            )
        except Exception:
            return self._pr_cache.get(key)
        detail = {
            "draft":    data.get("draft", False),
            "base_ref": data.get("base", {}).get("ref", ""),
            "head_ref": data.get("head", {}).get("ref", ""),
            "head_sha": data.get("head", {}).get("sha", ""),
            "mergeable_state": data.get("mergeable_state", "unknown"),
        }
        self._pr_cache[key] = detail
        _prune_cache(self._pr_cache, _PR_CACHE_MAX)
        return detail

    def _fetch_latest_run_for_sha(self, owner: str, repo: str,
                                  head_sha: str, token: str) -> Optional[dict]:
        """Fetch the most recent workflow run for a commit. ETag layer dedupes."""
        try:
            runs = fetch_runs_by_sha(
                owner, repo, head_sha, token, per_page=1, session=self._session)
        except Exception:
            return None
        return runs[0] if runs else None

    def _fetch_review_status(self, owner: str, repo: str, pr_num: int, token: str,
                             bot_regex: Optional[re.Pattern] = None
                             ) -> tuple[Optional[str], bool]:
        url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_num}/reviews"
        return _cached_review_fetch(
            url, token, self._session,
            self._review_cache, (owner, repo, pr_num), self._review_cache_ttl,
            bot_regex,
        )

    def _fetch_unresolved_threads(self, owner: str, repo: str, pr_num: int, token: str) -> int:
        return _cached_unresolved_fetch(
            owner, repo, pr_num, token, self._session,
            self._unresolved_cache, (owner, repo, pr_num), self._unresolved_cache_ttl,
        )

    def _remove_sub_key(self, sk: str):
        super()._remove_sub_key(sk)
        self._last_seen.pop(sk, None)
        try:
            owner_repo, pr_str = sk.split("#")
            owner, repo = owner_repo.split("/")
            pr_num = int(pr_str)
            self._pr_cache.pop((owner, repo, pr_num), None)
            self._review_cache.pop((owner, repo, pr_num), None)
            self._unresolved_cache.pop((owner, repo, pr_num), None)
        except (ValueError, IndexError):
            pass


# ---------------------------------------------------------------------------
# Status aggregation helpers (used by main / tray)
# ---------------------------------------------------------------------------
def _worst_status(statuses: set[str]) -> str:
    """Return the highest-priority status from a set (failure > running > queued > success)."""
    if ST_FAILURE  in statuses: return ST_FAILURE
    if ST_RUNNING  in statuses: return ST_RUNNING
    if ST_QUEUED   in statuses: return ST_QUEUED
    if ST_SUCCESS  in statuses: return ST_SUCCESS
    return ST_UNKNOWN


def _combined_status(states: list[WorkflowState]) -> str:
    return _worst_status({s.status for s in states})
