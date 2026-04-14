#!/usr/bin/env python3
"""
Actions Monitor — Lightweight GitHub Actions workflow status monitor.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import json
import os
import shutil
import sys
import platform
import threading
import webbrowser
import time
import queue
import subprocess
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, parse_qs, unquote

import tkinter as tk
from tkinter import ttk, font as tkfont

# ---------------------------------------------------------------------------
# Dependency checks
# ---------------------------------------------------------------------------
_missing = []
try:
    import requests
except ImportError:
    _missing.append("requests")
try:
    import yaml
except ImportError:
    _missing.append("pyyaml")
try:
    from PIL import Image, ImageDraw, ImageFont, ImageTk
except ImportError:
    _missing.append("Pillow")
try:
    import pystray
except ImportError:
    _missing.append("pystray")

if _missing:
    import tkinter.messagebox as mb
    root = tk.Tk(); root.withdraw()
    mb.showerror(
        "Actions Monitor — Missing Dependencies",
        "Please install the required packages:\n\n"
        f"  pip install {' '.join(_missing)}\n\n"
        "Then restart the application.",
    )
    sys.exit(1)

try:
    from plyer import notification as _plyer_notify
    PLYER_AVAILABLE = True
except ImportError:
    PLYER_AVAILABLE = False

try:
    from winotify import Notification as _WinNotification
    from winotify import audio as _winotify_audio
    WINOTIFY_AVAILABLE = True
except ImportError:
    WINOTIFY_AVAILABLE = False

IS_WINDOWS = platform.system() == "Windows"
IS_LINUX   = platform.system() == "Linux"

if IS_WINDOWS:
    import winsound
    import winreg
    import ctypes
    # Tell Windows to identify this process as "Actions Monitor" rather than "Python"
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Summit.ActionsMonitor")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
APP_NAME    = "Actions Monitor"
APP_VERSION = "1.0"

# When frozen by PyInstaller, __file__ points to a temp dir.
# Use the executable's directory instead so config/state live next to the .exe.
# When running from source in src/, go up one level to the project root.
if getattr(sys, "frozen", False):
    _APP_DIR = Path(sys.executable).parent
else:
    _APP_DIR = Path(__file__).resolve().parent.parent

CONFIG_FILE = _APP_DIR / "config.yaml"
STATE_FILE  = _APP_DIR / "state.json"
APP_ICO     = _APP_DIR / "app.ico"

POLL_DEFAULT = 60  # seconds

# Status values
ST_UNKNOWN    = "unknown"
ST_QUEUED     = "queued"
ST_RUNNING    = "in_progress"
ST_SUCCESS    = "success"
ST_FAILURE    = "failure"
ST_CANCELLED  = "cancelled"
ST_SKIPPED    = "skipped"

# Colour palette — warm dark theme
COLOUR = {
    ST_UNKNOWN:   "#A8A29E",  # warm grey (stone-400)
    ST_QUEUED:    "#FBBF24",  # amber
    ST_RUNNING:   "#FBBF24",  # amber
    ST_SUCCESS:   "#4ADE80",  # warm green
    ST_FAILURE:   "#F87171",  # warm red
    ST_CANCELLED: "#A8A29E",  # warm grey
    ST_SKIPPED:   "#A8A29E",  # warm grey
}

# Background fills for status icon circles (white glyph on top)
COLOUR_BG = {
    ST_UNKNOWN:   "#8C857F",  # stone-450
    ST_QUEUED:    "#CA8A04",  # amber-550
    ST_RUNNING:   "#CA8A04",  # amber-550
    ST_SUCCESS:   "#22994D",  # green-550
    ST_FAILURE:   "#C53030",  # red-550
    ST_CANCELLED: "#8C857F",  # stone-450
    ST_SKIPPED:   "#8C857F",  # stone-450
}

CONCLUSION_MAP = {
    "success":          ST_SUCCESS,
    "failure":          ST_FAILURE,
    "timed_out":        ST_FAILURE,
    "action_required":  ST_FAILURE,
    "cancelled":        ST_CANCELLED,
    "skipped":          ST_SKIPPED,
    "neutral":          ST_SUCCESS,
    None:               ST_RUNNING,
}

# UI colours — warm dark base
BG_DARK    = "#1C1917"   # stone-900
BG_ROW     = "#292524"   # stone-800
BG_ROW_ALT = "#231F1E"   # between stone-800 and 900
FG_TEXT    = "#E7E5E4"   # stone-200
FG_MUTED   = "#A8A29E"   # stone-400
FG_LINK    = "#FBBF24"   # amber-400 (primary accent)
ACCENT     = "#292524"   # stone-800

# Named sounds → winotify audio presets (Windows toast-coupled sounds)
# These play in sync with the notification flyout instead of independently.
_NAMED_SOUNDS: dict[str, object] = {}
if WINOTIFY_AVAILABLE:
    _NAMED_SOUNDS = {
        "default":  _winotify_audio.Default,
        "whistle":  _winotify_audio.IM,
        "reminder": _winotify_audio.Reminder,
        "mail":     _winotify_audio.Mail,
        "sms":      _winotify_audio.SMS,
    }

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DEFAULT_CONFIG: dict = {
    "github_token": "",
    "notifications": {
        "batch_window": 3,
        "new_run":  {"enabled": True,  "sound": "whistle"},
        "failure":  {"enabled": True,  "sound": "default"},
        "success":  {"enabled": True,  "sound": "none"},
    },
    "workflows": [],
}


class ConfigManager:
    def __init__(self):
        self._lock = threading.Lock()
        self.data: dict = {}
        self._mtime: float = 0
        self.load()

    def load(self) -> bool:
        """Load (or reload) the config file. Returns True if changed."""
        if not CONFIG_FILE.exists():
            self._write_default()
        try:
            mtime = CONFIG_FILE.stat().st_mtime
            if mtime == self._mtime:
                return False
            with open(CONFIG_FILE, encoding="utf-8") as fh:
                raw = yaml.safe_load(fh) or {}
            # Deep-merge with defaults
            merged = _deep_merge(DEFAULT_CONFIG, raw)
            with self._lock:
                self.data = merged
                self._mtime = mtime
            return True
        except Exception as exc:
            print(f"[Config] Load error: {exc}")
            return False

    def get(self) -> dict:
        with self._lock:
            return self.data

    def _write_default(self):
        # Copy the commented template if available, otherwise write bare defaults
        template = _APP_DIR / "config.template.yaml"
        if template.exists():
            shutil.copy2(template, CONFIG_FILE)
        else:
            with open(CONFIG_FILE, "w", encoding="utf-8") as fh:
                yaml.dump(DEFAULT_CONFIG, fh, default_flow_style=False)

    @staticmethod
    def open_in_editor():
        if IS_WINDOWS:
            os.startfile(str(CONFIG_FILE))
        elif IS_LINUX:
            editors = ["xdg-open", "gedit", "nano", "vim"]
            for ed in editors:
                try:
                    subprocess.Popen([ed, str(CONFIG_FILE)])
                    break
                except FileNotFoundError:
                    continue


def _deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


# ---------------------------------------------------------------------------
# GitHub API
# ---------------------------------------------------------------------------
def parse_workflow_url(url: str) -> tuple[str, str, str, Optional[str]]:
    """
    Parse a GitHub workflow URL into (owner, repo, workflow_file, branch).
    Supports URLs like:
      https://github.com/owner/repo/actions/workflows/file.yml
      https://github.com/owner/repo/actions/workflows/file.yml?query=branch%3Amain
    """
    parsed = urlparse(url)
    parts  = parsed.path.strip("/").split("/")
    # parts: [owner, repo, 'actions', 'workflows', 'file.yml']
    if len(parts) < 5 or parts[2] != "actions" or parts[3] != "workflows":
        raise ValueError(f"Cannot parse workflow URL: {url}")
    owner         = parts[0]
    repo          = parts[1]
    workflow_file = parts[4]

    branch = None
    qs = parse_qs(parsed.query)
    # ?query=branch%3Amain  or  ?branch=main
    if "branch" in qs:
        branch = qs["branch"][0]
    elif "query" in qs:
        raw_query = unquote(qs["query"][0])
        m = re.search(r"branch[:\s]+(\S+)", raw_query)
        if m:
            branch = m.group(1)

    return owner, repo, workflow_file, branch


def parse_actor_url(url: str) -> tuple[str, str, Optional[str]]:
    """Parse a GitHub Actions actor URL like:
      https://github.com/owner/repo/actions?query=actor%3Ausername
    Returns (owner, repo, actor_username_or_None).
    """
    parsed = urlparse(url)
    parts = parsed.path.strip("/").split("/")
    if len(parts) < 3 or parts[2] != "actions":
        raise ValueError(f"Cannot parse actor URL: {url}")
    owner = parts[0]
    repo = parts[1]

    actor = None
    qs = parse_qs(parsed.query)
    if "query" in qs:
        raw_query = unquote(qs["query"][0])
        m = re.search(r"actor[:\s]+(\S+)", raw_query)
        if m:
            actor = m.group(1)

    return owner, repo, actor


def fetch_latest_run(
    owner: str,
    repo: str,
    workflow_file: str,
    branch: Optional[str],
    token: str,
) -> Optional[dict]:
    """Fetch the latest workflow run from the GitHub API."""
    api_url = (
        f"https://api.github.com/repos/{owner}/{repo}"
        f"/actions/workflows/{workflow_file}/runs"
    )
    params: dict = {"per_page": 1}
    if branch:
        params["branch"] = branch

    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    resp = requests.get(api_url, params=params, headers=headers, timeout=15)
    resp.raise_for_status()
    runs = resp.json().get("workflow_runs", [])
    return runs[0] if runs else None


# ---------------------------------------------------------------------------
# GitHub username (cached)
# ---------------------------------------------------------------------------
_cached_github_username: Optional[str] = None
_github_username_lock = threading.Lock()


def fetch_github_username(token: str) -> Optional[str]:
    """Fetch the authenticated user's login via GET /user. Cached after first call."""
    global _cached_github_username
    if not token:
        return None
    with _github_username_lock:
        if _cached_github_username is not None:
            return _cached_github_username
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    resp = requests.get("https://api.github.com/user", headers=headers, timeout=15)
    resp.raise_for_status()
    login = resp.json().get("login")
    with _github_username_lock:
        _cached_github_username = login
    return login


def fetch_pr_runs(
    owner: str,
    repo: str,
    workflow_file: str,
    actor: str,
    token: str,
    per_page: int = 10,
) -> list[dict]:
    """Fetch recent workflow runs filtered by actor and pull_request event."""
    api_url = (
        f"https://api.github.com/repos/{owner}/{repo}"
        f"/actions/workflows/{workflow_file}/runs"
    )
    params = {"actor": actor, "event": "pull_request", "per_page": per_page}
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    resp = requests.get(api_url, params=params, headers=headers, timeout=15)
    resp.raise_for_status()
    return resp.json().get("workflow_runs", [])


def fetch_actor_runs(
    owner: str,
    repo: str,
    actor: str,
    token: str,
    per_page: int = 20,
    conclusion: Optional[str] = None,
) -> list[dict]:
    """Fetch recent workflow runs for a user across all workflows in a repo."""
    api_url = f"https://api.github.com/repos/{owner}/{repo}/actions/runs"
    params: dict = {"actor": actor, "per_page": per_page}
    if conclusion:
        params["conclusion"] = conclusion
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    resp = requests.get(api_url, params=params, headers=headers, timeout=15)
    resp.raise_for_status()
    return resp.json().get("workflow_runs", [])


# Known branch prefixes for display tagging
_KNOWN_PREFIXES = {"hotfix", "chore", "feature", "bugfix", "release", "fix", "docs"}


def parse_branch_prefix(branch: str) -> tuple[Optional[str], str]:
    """Parse a branch name like 'hotfix/fix-login' into ('hotfix', 'fix-login').
    Returns (None, original) if no known prefix."""
    if "/" in branch:
        prefix, rest = branch.split("/", 1)
        if prefix.lower() in _KNOWN_PREFIXES:
            return prefix.lower(), rest
    return None, branch


# Jira ticket extraction
_JIRA_KEY_RE = re.compile(r"(?i)\b([A-Z][A-Z0-9]+-\d+)\b")


def extract_jira_key(branch: str) -> Optional[str]:
    """Extract a Jira ticket key (e.g. EDU-1234) from a branch name."""
    m = _JIRA_KEY_RE.search(branch)
    return m.group(1).upper() if m else None


# ---------------------------------------------------------------------------
# Workflow state
# ---------------------------------------------------------------------------
@dataclass
class WorkflowState:
    name:        str
    url:         str
    branch:      Optional[str]
    status:      str      = ST_UNKNOWN
    run_id:      Optional[int] = None
    run_url:     Optional[str] = None
    run_number:  Optional[int] = None
    started_at:  Optional[str] = None
    conclusion:  Optional[str] = None
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
    review_status: Optional[str] = None   # "approved" | "changes_requested" | "pending" | None
    pr_target:     Optional[str] = None   # target branch (e.g. "acceptance", "production")
    jira_key:      Optional[str] = None


# ---------------------------------------------------------------------------
# Events put on the queue by pollers
# ---------------------------------------------------------------------------
@dataclass
class StatusEvent:
    workflow_id: int
    new_state:   WorkflowState
    notif_type:  Optional[str] = None   # "new_run" | "success" | "failure" | None
    sub_key:     Optional[str] = None   # head branch for PR rows, None for regular rows
    removed:     bool = False           # signals the UI to remove a stale row


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------
_NOTIF_TYPE_PRIORITY: dict[str, int] = {"success": 1, "new_run": 2, "failure": 3}

@dataclass
class _PendingNotification:
    notif_type: str        # "new_run" | "success" | "failure"
    title:      str
    message:    str
    sound_cfg:  str
    url:        Optional[str]


class NotificationManager:
    def __init__(self):
        self._lock = threading.Lock()
        self._pending: list[_PendingNotification] = []
        self._flush_timer: Optional[threading.Timer] = None
        self._batch_window: float = 3.0

    def set_batch_window(self, seconds: float):
        with self._lock:
            self._batch_window = max(seconds, 0.0)

    def notify(self, title: str, message: str, sound_cfg: str,
               url: Optional[str] = None, notif_type: str = "new_run"):
        with self._lock:
            if self._batch_window <= 0:
                # Batching disabled — fire immediately (old behaviour)
                threading.Thread(
                    target=self._send,
                    args=(title, message, sound_cfg, url),
                    daemon=True,
                ).start()
                return
            self._pending.append(_PendingNotification(notif_type, title, message, sound_cfg, url))
            if self._flush_timer is None:
                self._flush_timer = threading.Timer(self._batch_window, self._flush)
                self._flush_timer.daemon = True
                self._flush_timer.start()

    # -- flush batched notifications -----------------------------------------
    def _flush(self):
        with self._lock:
            batch = list(self._pending)
            self._pending.clear()
            self._flush_timer = None

        if not batch:
            return

        if len(batch) == 1:
            item = batch[0]
            threading.Thread(
                target=self._send,
                args=(item.title, item.message, item.sound_cfg, item.url),
                daemon=True,
            ).start()
            return

        # Multiple notifications — combine into one
        counts: dict[str, int] = {}
        for item in batch:
            counts[item.notif_type] = counts.get(item.notif_type, 0) + 1

        type_labels = {
            "failure": "\u2717 {n} failed",
            "new_run": "\u25b6 {n} started",
            "success": "\u2713 {n} succeeded",
        }
        parts = []
        for ntype in ("failure", "new_run", "success"):
            if ntype in counts:
                parts.append(type_labels[ntype].format(n=counts[ntype]))

        title = f"{sum(counts.values())} workflow notifications"
        body = "  \u2022  ".join(parts)

        # Pick sound from highest-priority notification type
        best = max(batch, key=lambda i: _NOTIF_TYPE_PRIORITY.get(i.notif_type, 0))
        sound = best.sound_cfg

        # URL: use the first failure's URL, or first item's
        url = None
        for item in batch:
            if item.notif_type == "failure" and item.url:
                url = item.url
                break
        if url is None:
            url = batch[0].url

        threading.Thread(
            target=self._send,
            args=(title, body, sound, url),
            daemon=True,
        ).start()

    # -- low-level send / sound ----------------------------------------------
    def _send(self, title: str, message: str, sound_cfg: str, url: Optional[str] = None):
        sound_coupled = False
        if IS_WINDOWS and WINOTIFY_AVAILABLE:
            try:
                toast = _WinNotification(
                    app_id="Summit.ActionsMonitor",
                    title=title,
                    msg=message,
                    duration="short",
                )
                if url:
                    toast.add_actions(label="Open workflow", launch=url)
                # Couple sound to toast so it plays when the flyout appears
                winotify_sound = _NAMED_SOUNDS.get(sound_cfg)
                if winotify_sound and sound_cfg != "none":
                    toast.set_audio(winotify_sound, loop=False)
                    sound_coupled = True
                toast.show()
            except Exception:
                pass
        elif PLYER_AVAILABLE:
            try:
                _plyer_notify.notify(
                    app_name=APP_NAME,
                    title=title,
                    message=message,
                    timeout=5,
                )
            except Exception:
                pass
        # Only play sound separately if it wasn't coupled to the toast
        if not sound_coupled:
            self._play_sound(sound_cfg)

    def _play_sound(self, sound_cfg: str):
        if sound_cfg == "none" or not sound_cfg:
            return
        if IS_WINDOWS:
            if sound_cfg == "default":
                try:
                    winsound.MessageBeep(winsound.MB_ICONASTERISK)
                except Exception:
                    pass
            else:
                try:
                    winsound.PlaySound(sound_cfg, winsound.SND_FILENAME | winsound.SND_ASYNC)
                except Exception:
                    pass
        elif IS_LINUX:
            if sound_cfg == "default":
                for cmd in [["paplay", "/usr/share/sounds/freedesktop/stereo/message.oga"],
                             ["aplay",  "/usr/share/sounds/alsa/Front_Left.wav"]]:
                    try:
                        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        break
                    except FileNotFoundError:
                        continue
            else:
                try:
                    subprocess.Popen(["paplay", sound_cfg],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except FileNotFoundError:
                    pass


NOTIF = NotificationManager()


# ---------------------------------------------------------------------------
# Poller thread
# ---------------------------------------------------------------------------
class WorkflowPoller(threading.Thread):
    def __init__(
        self,
        wid: int,
        cfg_entry: dict,
        config_mgr: ConfigManager,
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
        self._prev_run_id    : Optional[int] = None
        self._prev_status    : Optional[str] = None
        self._prev_conclusion: Optional[str] = None

    def stop(self):
        self._stop_evt.set()

    def trigger_poll(self):
        """Wake the poller to re-poll immediately."""
        self._poll_now.set()

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
        cfg      = self.config_mgr.get()
        token    = cfg.get("github_token", "")
        notif_cfg = cfg.get("notifications", {})

        state = WorkflowState(
            name=self.name_display,
            url=self.cfg_entry.get("url", ""),
            branch=self.branch,
        )

        if not self.owner:
            state.status = ST_UNKNOWN
            state.error  = "Invalid workflow URL in config"
            self.event_queue.put(StatusEvent(self.wid, state))
            return

        try:
            run = fetch_latest_run(self.owner, self.repo, self.wf_file, self.branch, token)
        except requests.HTTPError as exc:
            state.status = ST_UNKNOWN
            state.error  = f"HTTP {exc.response.status_code}"
            self.event_queue.put(StatusEvent(self.wid, state))
            return
        except Exception as exc:
            state.status = ST_UNKNOWN
            state.error  = str(exc)
            self.event_queue.put(StatusEvent(self.wid, state))
            return

        state.last_check = datetime.now()
        state.error = None

        if run is None:
            state.status = ST_UNKNOWN
            self.event_queue.put(StatusEvent(self.wid, state))
            return

        run_id    = run.get("id")
        api_status  = run.get("status")       # queued / in_progress / completed
        conclusion  = run.get("conclusion")   # success / failure / … / None

        if api_status == "completed":
            state.status = CONCLUSION_MAP.get(conclusion, ST_UNKNOWN)
        elif api_status == "in_progress":
            state.status = ST_RUNNING
        elif api_status == "queued":
            state.status = ST_QUEUED
        else:
            state.status = ST_UNKNOWN

        state.run_id    = run_id
        state.run_url   = run.get("html_url")
        state.run_number = run.get("run_number")
        state.started_at = run.get("run_started_at") or run.get("created_at")
        state.conclusion = conclusion

        # Determine what notification to send
        notif_type: Optional[str] = None
        if self._prev_run_id is not None and run_id != self._prev_run_id:
            notif_type = "new_run"
        elif (
            run_id == self._prev_run_id
            and api_status == "completed"
            and self._prev_status != "completed"
        ):
            if state.status == ST_SUCCESS:
                notif_type = "success"
            elif state.status == ST_FAILURE:
                notif_type = "failure"

        self._prev_run_id     = run_id
        self._prev_status     = api_status
        self._prev_conclusion = conclusion

        self.event_queue.put(StatusEvent(self.wid, state, notif_type))

        # Fire notification
        if notif_type:
            self._fire_notification(notif_type, state, notif_cfg)

    def _fire_notification(self, notif_type: str, state: WorkflowState, global_notif: dict, is_pr: bool = False):
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

        titles = {
            "new_run": f"▶ New run started",
            "success": f"✓ Run succeeded",
            "failure": f"✗ Run failed",
        }
        messages = {
            "new_run": f"{state.name}  •  Run #{state.run_number}",
            "success": f"{state.name}  •  Run #{state.run_number}",
            "failure": f"{state.name}  •  Run #{state.run_number}",
        }
        url = state.run_url or state.url
        NOTIF.notify(titles[notif_type], messages[notif_type], sound, url=url, notif_type=notif_type)


# ---------------------------------------------------------------------------
# PR-mode poller
# ---------------------------------------------------------------------------
class PRWorkflowPoller(WorkflowPoller):
    """Poller that shows one row per active PR branch instead of one fixed row."""

    def __init__(self, wid, cfg_entry, config_mgr, event_queue):
        super().__init__(wid, cfg_entry, config_mgr, event_queue)
        self._max_prs = int(cfg_entry.get("max_prs", 5))
        self._stale_after = int(cfg_entry.get("pr_stale_after", 300))
        # Extra workflow files to aggregate status from
        self._extra_wf_files: list[str] = list(cfg_entry.get("extra_workflows", []))
        # Per-branch tracking
        self._prev_run_ids:    dict[str, set[int]] = {}   # set of run IDs across all workflows
        self._prev_statuses:   dict[str, str] = {}        # aggregate status string
        self._prev_conclusions: dict[str, Optional[str]] = {}
        self._last_seen:       dict[str, datetime] = {}
        # PR detail cache: pr_number → {draft: bool}
        self._pr_cache: dict[int, dict] = {}

    def _poll(self):
        cfg   = self.config_mgr.get()
        token = cfg.get("github_token", "")
        notif_cfg = cfg.get("notifications", {})

        # Resolve username
        try:
            username = fetch_github_username(token)
        except Exception as exc:
            state = WorkflowState(name=self.name_display, url=self.cfg_entry.get("url", ""), branch=None)
            state.status = ST_UNKNOWN
            state.error = f"Cannot resolve GitHub user: {exc}"
            self.event_queue.put(StatusEvent(self.wid, state))
            return
        if not username:
            state = WorkflowState(name=self.name_display, url=self.cfg_entry.get("url", ""), branch=None)
            state.status = ST_UNKNOWN
            state.error = "No token configured (PR mode requires a token)"
            self.event_queue.put(StatusEvent(self.wid, state))
            return

        if not self.owner:
            state = WorkflowState(name=self.name_display, url=self.cfg_entry.get("url", ""), branch=None)
            state.status = ST_UNKNOWN
            state.error = "Invalid workflow URL in config"
            self.event_queue.put(StatusEvent(self.wid, state))
            return

        # Fetch runs from primary workflow + any extra workflows
        all_wf_files = [self.wf_file] + self._extra_wf_files
        all_runs: list[dict] = []
        for wf_file in all_wf_files:
            try:
                runs = fetch_pr_runs(
                    self.owner, self.repo, wf_file, username, token,
                    per_page=self._max_prs * 2,
                )
                all_runs.extend(runs)
            except requests.HTTPError as exc:
                if not all_runs and wf_file == self.wf_file:
                    # Primary workflow failed — report error
                    state = WorkflowState(name=self.name_display, url=self.cfg_entry.get("url", ""), branch=None)
                    state.status = ST_UNKNOWN
                    state.error = f"HTTP {exc.response.status_code}"
                    self.event_queue.put(StatusEvent(self.wid, state))
                    return
                # Extra workflow failed — skip silently
            except Exception as exc:
                if not all_runs and wf_file == self.wf_file:
                    state = WorkflowState(name=self.name_display, url=self.cfg_entry.get("url", ""), branch=None)
                    state.status = ST_UNKNOWN
                    state.error = str(exc)
                    self.event_queue.put(StatusEvent(self.wid, state))
                    return

        # Ensure open PRs by the user are included even if their runs fell
        # off the per_page window.  Fetch the user's open PRs once and, for
        # any branch not yet present, fetch its latest runs individually.
        branches_with_runs = {r.get("head_branch") for r in all_runs}
        try:
            open_prs = self._fetch_user_open_prs(username, token)
        except Exception:
            open_prs = []
        for pr in open_prs:
            branch = pr["branch"]
            if branch in branches_with_runs:
                continue
            # Fetch latest runs for this branch across all configured workflows
            for wf_file in all_wf_files:
                try:
                    runs = self._fetch_branch_runs(wf_file, branch, token)
                    all_runs.extend(runs)
                except Exception:
                    pass
            branches_with_runs.add(branch)

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

        _REPR_PRIORITY = {ST_FAILURE: 4, ST_RUNNING: 3, ST_QUEUED: 2, ST_SUCCESS: 1,
                          ST_UNKNOWN: 0, ST_CANCELLED: 0, ST_SKIPPED: 0}
        active_sub_keys: set[str] = set()

        for branch_name, branch_runs in active_branches.items():
            # Collect all unique PR numbers across all runs for this branch
            pr_numbers_seen: dict[int, str] = {}  # pr_num -> base_ref
            for r in branch_runs:
                for pr_entry in (r.get("pull_requests") or []):
                    pr_num = pr_entry.get("number")
                    if pr_num and pr_num not in pr_numbers_seen:
                        pr_numbers_seen[pr_num] = pr_entry.get("base", {}).get("ref", "")

            # Fallback: query the Pulls API when workflow runs lack PR data
            if not pr_numbers_seen:
                for pr_info in self._fetch_prs_for_branch(branch_name, token):
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

                # Determine per-run statuses and pick the aggregate + representative run
                run_statuses: list[str] = []
                representative_run: Optional[dict] = None
                rep_priority = -1

                for run in group_runs:
                    api_status = run.get("status")
                    conclusion = run.get("conclusion")
                    if api_status == "completed":
                        st = CONCLUSION_MAP.get(conclusion, ST_UNKNOWN)
                    elif api_status == "in_progress":
                        st = ST_RUNNING
                    elif api_status == "queued":
                        st = ST_QUEUED
                    else:
                        st = ST_UNKNOWN
                    run_statuses.append(st)

                    p = _REPR_PRIORITY.get(st, 0)
                    if p > rep_priority:
                        rep_priority = p
                        representative_run = run

                if representative_run is None:
                    representative_run = group_runs[0]

                # Aggregate status (worst wins)
                status_set = set(run_statuses)
                if ST_FAILURE  in status_set: agg_status = ST_FAILURE
                elif ST_RUNNING  in status_set: agg_status = ST_RUNNING
                elif ST_QUEUED   in status_set: agg_status = ST_QUEUED
                elif ST_SUCCESS  in status_set: agg_status = ST_SUCCESS
                else:                           agg_status = ST_UNKNOWN

                run = representative_run
                state = WorkflowState(
                    name=self.name_display,
                    url=self.cfg_entry.get("url", ""),
                    branch=branch_name,
                    head_branch=branch_name,
                )
                state.last_check = now
                state.status     = agg_status
                state.run_id     = run.get("id")
                state.run_url    = run.get("html_url")
                state.run_number = run.get("run_number")
                state.started_at = run.get("run_started_at") or run.get("created_at")
                state.conclusion = run.get("conclusion")

                # Parse branch prefix
                prefix, short = parse_branch_prefix(branch_name)
                state.branch_prefix = prefix
                state.branch_short  = short

                # PR info
                if pr_num is not None:
                    state.pr_number = pr_num
                    state.pr_target = pr_base_ref
                    # Always re-fetch PR details to keep draft/title up to date
                    state.is_draft = self._fetch_pr_draft(pr_num, token)
                    if pr_num in self._pr_cache:
                        state.pr_title = self._pr_cache[pr_num].get("title")
                        if not state.pr_target:
                            state.pr_target = self._pr_cache[pr_num].get("base_ref", "")
                    state.pr_url = f"https://github.com/{self.owner}/{self.repo}/pull/{pr_num}"
                    state.review_status = self._fetch_pr_review_status(pr_num, token)

                # Jira ticket key from branch name
                state.jira_key = extract_jira_key(branch_name)

                # Determine notification based on aggregate status transitions
                notif_type: Optional[str] = None
                cur_run_ids = {r.get("id") for r in group_runs}
                prev_rids   = self._prev_run_ids.get(sub_key, set())
                prev_agg    = self._prev_statuses.get(sub_key)

                if prev_rids and cur_run_ids != prev_rids and not cur_run_ids.issubset(prev_rids):
                    notif_type = "new_run"
                elif prev_agg and prev_agg != agg_status:
                    if agg_status == ST_SUCCESS:
                        notif_type = "success"
                    elif agg_status == ST_FAILURE:
                        notif_type = "failure"

                self._prev_run_ids[sub_key]     = cur_run_ids
                self._prev_statuses[sub_key]    = agg_status
                self._prev_conclusions[sub_key] = run.get("conclusion")

                self.event_queue.put(StatusEvent(self.wid, state, notif_type, sub_key=sub_key))

                if notif_type:
                    self._fire_notification(notif_type, state, notif_cfg, is_pr=True)

        # Detect stale sub_keys
        for sk in list(self._last_seen.keys()):
            if sk in active_sub_keys:
                continue
            elapsed = (now - self._last_seen[sk]).total_seconds()
            if elapsed >= self._stale_after:
                branch_part = sk.split("#")[0] if "#" in sk else sk
                dummy = WorkflowState(name=self.name_display, url=self.cfg_entry.get("url", ""), branch=branch_part)
                self.event_queue.put(StatusEvent(self.wid, dummy, sub_key=sk, removed=True))
                del self._last_seen[sk]
                self._prev_run_ids.pop(sk, None)
                self._prev_statuses.pop(sk, None)
                self._prev_conclusions.pop(sk, None)

    def _fetch_user_open_prs(self, username: str, token: str) -> list[dict]:
        """Fetch open PRs authored by the user. Returns list of {number, branch, base_ref}."""
        url = (
            f"https://api.github.com/repos/{self.owner}/{self.repo}"
            f"/pulls?state=open&sort=updated&direction=desc&per_page=50"
        )
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        results = []
        for pr in resp.json():
            author = pr.get("user", {}).get("login", "")
            if author.lower() != username.lower():
                continue
            pr_num = pr.get("number")
            if pr_num:
                branch = pr.get("head", {}).get("ref", "")
                base_ref = pr.get("base", {}).get("ref", "")
                is_draft = pr.get("draft", False)
                title = pr.get("title", "")
                self._pr_cache[pr_num] = {
                    "draft": is_draft,
                    "title": title,
                    "base_ref": base_ref,
                }
                results.append({"number": pr_num, "branch": branch, "base_ref": base_ref})
        return results

    def _fetch_branch_runs(self, wf_file: str, branch: str, token: str) -> list[dict]:
        """Fetch latest workflow runs for a specific branch."""
        url = (
            f"https://api.github.com/repos/{self.owner}/{self.repo}"
            f"/actions/workflows/{wf_file}/runs"
        )
        params = {"branch": branch, "per_page": 1}
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        resp = requests.get(url, params=params, headers=headers, timeout=15)
        resp.raise_for_status()
        return resp.json().get("workflow_runs", [])

    def _fetch_prs_for_branch(self, branch: str, token: str) -> list[dict]:
        """Fetch open PRs for a head branch. Returns list of {number, base_ref}."""
        try:
            url = (
                f"https://api.github.com/repos/{self.owner}/{self.repo}"
                f"/pulls?head={self.owner}:{branch}&state=open&per_page=10"
            )
            headers = {
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
            if token:
                headers["Authorization"] = f"Bearer {token}"
            resp = requests.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
            results = []
            for pr in resp.json():
                pr_num = pr.get("number")
                if pr_num:
                    base_ref = pr.get("base", {}).get("ref", "")
                    is_draft = pr.get("draft", False)
                    title = pr.get("title", "")
                    self._pr_cache[pr_num] = {
                        "draft": is_draft,
                        "title": title,
                        "base_ref": base_ref,
                    }
                    results.append({"number": pr_num, "base_ref": base_ref})
            return results
        except Exception:
            return []

    def _fetch_pr_draft(self, pr_number: int, token: str) -> bool:
        """Fetch draft status for a PR. Caches the result."""
        try:
            url = f"https://api.github.com/repos/{self.owner}/{self.repo}/pulls/{pr_number}"
            headers = {
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
            if token:
                headers["Authorization"] = f"Bearer {token}"
            resp = requests.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            is_draft = data.get("draft", False)
            self._pr_cache[pr_number] = {
                "draft": is_draft,
                "title": data.get("title", ""),
                "base_ref": data.get("base", {}).get("ref", ""),
            }
            return is_draft
        except Exception:
            return False

    def _fetch_pr_review_status(self, pr_number: int, token: str) -> Optional[str]:
        """Fetch the aggregate review status for a PR.
        Returns 'approved', 'changes_requested', 'pending', or None."""
        try:
            url = (
                f"https://api.github.com/repos/{self.owner}/{self.repo}"
                f"/pulls/{pr_number}/reviews"
            )
            headers = {
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
            if token:
                headers["Authorization"] = f"Bearer {token}"
            resp = requests.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
            reviews = resp.json()

            # Keep only the latest review per reviewer (ignore COMMENTED/PENDING)
            latest: dict[str, str] = {}
            for r in reviews:
                user = r.get("user", {}).get("login", "")
                state = r.get("state", "")
                if state in ("APPROVED", "CHANGES_REQUESTED"):
                    latest[user] = state

            if not latest:
                return "pending"
            if "CHANGES_REQUESTED" in latest.values():
                return "changes_requested"
            return "approved"
        except Exception:
            return None


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
        self._stale_after = int(cfg_entry.get("stale_after", 300))
        self._filter = cfg_entry.get("filter", "all")
        # Per-run tracking, keyed by composite "workflow_id:head_branch"
        self._prev_run_ids:     dict[str, int] = {}
        self._prev_statuses:    dict[str, str] = {}
        self._prev_conclusions: dict[str, Optional[str]] = {}
        self._last_seen:        dict[str, datetime] = {}

    def _poll(self):
        cfg   = self.config_mgr.get()
        token = cfg.get("github_token", "")
        notif_cfg = cfg.get("notifications", {})

        # Resolve username
        try:
            username = fetch_github_username(token)
        except Exception as exc:
            state = WorkflowState(name=self.name_display, url=self.cfg_entry.get("url", ""))
            state.status = ST_UNKNOWN
            state.error = f"Cannot resolve GitHub user: {exc}"
            self.event_queue.put(StatusEvent(self.wid, state))
            return
        if not username:
            state = WorkflowState(name=self.name_display, url=self.cfg_entry.get("url", ""))
            state.status = ST_UNKNOWN
            state.error = "No token configured (actor mode requires a token)"
            self.event_queue.put(StatusEvent(self.wid, state))
            return

        if not self.owner:
            state = WorkflowState(name=self.name_display, url=self.cfg_entry.get("url", ""))
            state.status = ST_UNKNOWN
            state.error = "Invalid actor URL in config"
            self.event_queue.put(StatusEvent(self.wid, state))
            return

        conclusion_filter = "failure" if self._filter == "failed" else None
        try:
            runs = fetch_actor_runs(
                self.owner, self.repo, username, token,
                per_page=self._max_runs * 3,
                conclusion=conclusion_filter,
            )
        except requests.HTTPError as exc:
            state = WorkflowState(name=self.name_display, url=self.cfg_entry.get("url", ""))
            state.status = ST_UNKNOWN
            state.error = f"HTTP {exc.response.status_code}"
            self.event_queue.put(StatusEvent(self.wid, state))
            return
        except Exception as exc:
            state = WorkflowState(name=self.name_display, url=self.cfg_entry.get("url", ""))
            state.status = ST_UNKNOWN
            state.error = str(exc)
            self.event_queue.put(StatusEvent(self.wid, state))
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

            run_id     = run.get("id")
            api_status = run.get("status")
            conclusion = run.get("conclusion")
            hb         = run.get("head_branch", "")
            wf_name    = run.get("name", "unknown")

            state = WorkflowState(
                name=wf_name,
                url=self.cfg_entry.get("url", ""),
                branch=hb,
                head_branch=hb,
            )
            state.last_check = now

            if api_status == "completed":
                state.status = CONCLUSION_MAP.get(conclusion, ST_UNKNOWN)
            elif api_status == "in_progress":
                state.status = ST_RUNNING
            elif api_status == "queued":
                state.status = ST_QUEUED
            else:
                state.status = ST_UNKNOWN

            state.run_id     = run_id
            state.run_url    = run.get("html_url")
            state.run_number = run.get("run_number")
            state.started_at = run.get("run_started_at") or run.get("created_at")
            state.conclusion = conclusion

            # Parse branch prefix
            if hb:
                prefix, short = parse_branch_prefix(hb)
                state.branch_prefix = prefix
                state.branch_short  = short
                state.jira_key = extract_jira_key(hb)

            # Determine notification
            notif_type: Optional[str] = None
            prev_rid = self._prev_run_ids.get(composite_key)
            prev_st  = self._prev_statuses.get(composite_key)
            if prev_rid is not None and run_id != prev_rid:
                notif_type = "new_run"
            elif (
                run_id == prev_rid
                and api_status == "completed"
                and prev_st != "completed"
            ):
                if state.status == ST_SUCCESS:
                    notif_type = "success"
                elif state.status == ST_FAILURE:
                    notif_type = "failure"

            self._prev_run_ids[composite_key]     = run_id
            self._prev_statuses[composite_key]    = api_status
            self._prev_conclusions[composite_key] = conclusion

            self.event_queue.put(StatusEvent(self.wid, state, notif_type, sub_key=composite_key))

            if notif_type:
                self._fire_notification(notif_type, state, notif_cfg, is_pr=False)

        # Detect stale entries
        for key in list(self._last_seen.keys()):
            if key in active_keys:
                continue
            elapsed = (now - self._last_seen[key]).total_seconds()
            if elapsed >= self._stale_after:
                dummy = WorkflowState(name=self.name_display, url=self.cfg_entry.get("url", ""))
                self.event_queue.put(StatusEvent(self.wid, dummy, sub_key=key, removed=True))
                del self._last_seen[key]
                self._prev_run_ids.pop(key, None)
                self._prev_statuses.pop(key, None)
                self._prev_conclusions.pop(key, None)


# ---------------------------------------------------------------------------
# Icon creation helpers — Lucide-inspired, rendered with PIL
# ---------------------------------------------------------------------------
_ICON_GLYPH = "#FFFFFF"  # white glyph on coloured circle — max contrast at small size

def _s(val: float, size: int, svg_size: float = 24.0, pad_frac: float = 0.18) -> float:
    """Scale an SVG coordinate to image space with padding."""
    usable = size * (1 - 2 * pad_frac)
    return val / svg_size * usable + size * pad_frac


def _sw(size: int) -> int:
    """Bold stroke width for small-icon legibility."""
    return max(3, round(size / 24 * 3.2))


def _icon_base(size: int, ss: int = 4) -> tuple[Image.Image, ImageDraw.Draw, int]:
    """Create a supersampled RGBA canvas and return (img, draw, hi_size)."""
    hi = size * ss
    img = Image.new("RGBA", (hi, hi), (0, 0, 0, 0))
    return img, ImageDraw.Draw(img), hi


def _fill_circle(draw: ImageDraw.Draw, hi: int, colour: str):
    """Filled circle — no outline, just the solid status colour."""
    pad = hi * 0.04
    draw.ellipse([pad, pad, hi - pad, hi - pad], fill=colour)


def _draw_lucide_circle_check(size: int, bg_fill: str) -> Image.Image:
    """Checkmark on coloured circle."""
    img, draw, hi = _icon_base(size)
    _fill_circle(draw, hi, bg_fill)
    sw = _sw(hi)
    # Bold checkmark: (8,12)→(11,15)→(16,9)
    pts = [(_s(8, hi), _s(12.5, hi)), (_s(11, hi), _s(15.5, hi)), (_s(16.5, hi), _s(9, hi))]
    draw.line(pts, fill=_ICON_GLYPH, width=sw, joint="curve")
    return img.resize((size, size), Image.LANCZOS)


def _draw_lucide_circle_x(size: int, bg_fill: str) -> Image.Image:
    """X mark on coloured circle."""
    img, draw, hi = _icon_base(size)
    _fill_circle(draw, hi, bg_fill)
    sw = _sw(hi)
    # Bold X
    draw.line([(_s(9, hi), _s(9, hi)), (_s(15, hi), _s(15, hi))], fill=_ICON_GLYPH, width=sw)
    draw.line([(_s(15, hi), _s(9, hi)), (_s(9, hi), _s(15, hi))], fill=_ICON_GLYPH, width=sw)
    return img.resize((size, size), Image.LANCZOS)


def _draw_lucide_loader(size: int, bg_fill: str) -> Image.Image:
    """Partial arc (spinner) on coloured circle."""
    img, draw, hi = _icon_base(size)
    _fill_circle(draw, hi, bg_fill)
    sw = _sw(hi)
    r = hi * 0.30
    cx, cy = hi / 2, hi / 2
    draw.arc([cx - r, cy - r, cx + r, cy + r], start=-60, end=240,
             fill=_ICON_GLYPH, width=sw)
    return img.resize((size, size), Image.LANCZOS)


def _draw_lucide_clock(size: int, bg_fill: str) -> Image.Image:
    """Clock face on coloured circle."""
    img, draw, hi = _icon_base(size)
    _fill_circle(draw, hi, bg_fill)
    sw = _sw(hi)
    # Circle outline for clock face
    r = hi * 0.30
    cx, cy = hi / 2, hi / 2
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=_ICON_GLYPH, width=sw)
    # Clock hands: 12 o'clock down to center, then to ~2 o'clock
    draw.line([(cx, cy - r * 0.65), (cx, cy), (cx + r * 0.55, cy + r * 0.35)],
              fill=_ICON_GLYPH, width=sw, joint="curve")
    return img.resize((size, size), Image.LANCZOS)


def _draw_lucide_ban(size: int, bg_fill: str) -> Image.Image:
    """Ban/slash on coloured circle."""
    img, draw, hi = _icon_base(size)
    _fill_circle(draw, hi, bg_fill)
    sw = _sw(hi)
    # Diagonal slash
    draw.line([(_s(6, hi), _s(6, hi)), (_s(18, hi), _s(18, hi))],
              fill=_ICON_GLYPH, width=sw)
    return img.resize((size, size), Image.LANCZOS)


def _draw_lucide_skip_forward(size: int, bg_fill: str) -> Image.Image:
    """Skip-forward on coloured circle."""
    img, draw, hi = _icon_base(size)
    _fill_circle(draw, hi, bg_fill)
    sw = _sw(hi)
    # Filled play triangle + bar
    tri = [(_s(7, hi), _s(7, hi)), (_s(14.5, hi), _s(12, hi)), (_s(7, hi), _s(17, hi))]
    draw.polygon(tri, fill=_ICON_GLYPH)
    draw.line([(_s(16.5, hi), _s(7, hi)), (_s(16.5, hi), _s(17, hi))],
              fill=_ICON_GLYPH, width=sw)
    return img.resize((size, size), Image.LANCZOS)


def _draw_lucide_circle_help(size: int, bg_fill: str) -> Image.Image:
    """Question mark on coloured circle."""
    img, draw, hi = _icon_base(size)
    _fill_circle(draw, hi, bg_fill)
    sw = _sw(hi)
    # Question mark — use a font for clean rendering
    try:
        fsize = int(hi * 0.52)
        font = ImageFont.truetype("segoeuib.ttf", fsize)  # Segoe UI Bold
    except Exception:
        font = ImageFont.load_default()
    bbox = draw.textbbox((0, 0), "?", font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    tx = (hi - tw) / 2 - bbox[0]
    ty = (hi - th) / 2 - bbox[1]
    draw.text((tx, ty), "?", fill=_ICON_GLYPH, font=font)
    return img.resize((size, size), Image.LANCZOS)


# Map status → icon drawing function
_STATUS_ICON_FUNC = {
    ST_SUCCESS:   _draw_lucide_circle_check,
    ST_FAILURE:   _draw_lucide_circle_x,
    ST_RUNNING:   _draw_lucide_loader,
    ST_QUEUED:    _draw_lucide_clock,
    ST_CANCELLED: _draw_lucide_ban,
    ST_SKIPPED:   _draw_lucide_skip_forward,
    ST_UNKNOWN:   _draw_lucide_circle_help,
}


def _make_status_icon(status: str, size: int = 32) -> Image.Image:
    """Generate a Lucide-style status icon with coloured background circle."""
    bg_fill = COLOUR_BG.get(status, COLOUR_BG[ST_UNKNOWN])
    func = _STATUS_ICON_FUNC.get(status, _draw_lucide_circle_help)
    return func(size, bg_fill)


# --- App / tray icon (play triangle on dark rounded rect + status dot) ---

def _make_base_icon(size: int = 64) -> Image.Image:
    """App icon: amber play triangle on dark rounded-rect background."""
    ss = 4
    hi = size * ss
    img = Image.new("RGBA", (hi, hi), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    pad = hi // 16
    radius = hi // 4
    draw.rounded_rectangle([pad, pad, hi - pad, hi - pad],
                           radius=radius, fill="#252220")
    inner_pad = pad + hi // 32
    inner_radius = radius - hi // 32
    draw.rounded_rectangle([inner_pad, inner_pad, hi - inner_pad, hi - inner_pad],
                           radius=inner_radius, fill="#2D2926")

    # Play triangle — amber accent
    cx, cy = hi // 2, hi // 2
    offset = hi // 12
    s = int(hi * 0.26)
    draw.polygon([
        (cx - s + offset, cy - int(s * 1.15)),
        (cx + int(s * 1.1) + offset, cy),
        (cx - s + offset, cy + int(s * 1.15)),
    ], fill="#FBBF24")

    return img.resize((size, size), Image.LANCZOS)


def _make_icon_image(colour: str, size: int = 64) -> Image.Image:
    """Base icon with a coloured status dot in the bottom-right corner."""
    img = _make_base_icon(size)
    ss = 4
    hi = size * ss
    overlay = Image.new("RGBA", (hi, hi), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    dot_r = hi // 5
    x = hi - dot_r - ss
    y = hi - dot_r - ss
    draw.ellipse([x - dot_r - 3*ss, y - dot_r - 3*ss,
                  x + dot_r + 3*ss, y + dot_r + 3*ss], fill="#1C1917")
    draw.ellipse([x - dot_r - ss, y - dot_r - ss,
                  x + dot_r + ss, y + dot_r + ss], fill="#FFFFFF")
    draw.ellipse([x - dot_r, y - dot_r, x + dot_r, y + dot_r], fill=colour)

    overlay = overlay.resize((size, size), Image.LANCZOS)
    img.paste(overlay, (0, 0), overlay)
    return img


def _generate_app_ico() -> None:
    """Generate app.ico with multiple sizes for crisp display at all scales."""
    try:
        sizes = [256, 48, 32, 16]  # largest first for proper ICO embedding
        images = [_make_base_icon(s) for s in sizes]
        images[0].save(str(APP_ICO), format="ICO",
                       sizes=[(s, s) for s in sizes],
                       append_images=images[1:])
    except Exception as exc:
        print(f"[Icon] Generate error: {exc}")


def _combined_status(states: list[WorkflowState]) -> str:
    statuses = {s.status for s in states}
    if ST_FAILURE  in statuses: return ST_FAILURE
    if ST_RUNNING  in statuses: return ST_RUNNING
    if ST_QUEUED   in statuses: return ST_QUEUED
    if ST_SUCCESS  in statuses: return ST_SUCCESS
    return ST_UNKNOWN


# ---------------------------------------------------------------------------
# Tray icon
# ---------------------------------------------------------------------------
class TrayManager:
    def __init__(self, show_cb, quit_cb):
        self._show_cb  = show_cb
        self._quit_cb  = quit_cb
        self._icons    = {s: _make_icon_image(c) for s, c in COLOUR.items()}
        self._icon     = pystray.Icon(
            APP_NAME,
            self._icons[ST_UNKNOWN],
            APP_NAME,
            menu=pystray.Menu(
                pystray.MenuItem("Show",          lambda: self._show_cb(), default=True),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Quit",          lambda: self._quit_cb()),
            ),
        )
        self._thread   = threading.Thread(target=self._icon.run, daemon=True, name="tray")

    def start(self):
        self._thread.start()

    def update(self, states: list[WorkflowState]):
        combined = _combined_status(states)
        self._icon.icon  = self._icons[combined]
        self._icon.title = f"{APP_NAME} — {combined.replace('_', ' ').title()}"

    def stop(self):
        try:
            self._icon.stop()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Workflow row widget
# ---------------------------------------------------------------------------
STATUS_LABEL = {
    ST_UNKNOWN:  "Unknown",
    ST_QUEUED:   "Queued",
    ST_RUNNING:  "Running…",
    ST_SUCCESS:  "Success",
    ST_FAILURE:  "Failed",
    ST_CANCELLED:"Cancelled",
    ST_SKIPPED:  "Skipped",
}

# Pre-generated status icon PhotoImages (populated once the Tk root exists)
_status_tk_icons: dict[str, ImageTk.PhotoImage] = {}
_ICON_SIZE = 24  # px for row status icons


def _init_status_icons():
    """Generate and cache PhotoImage icons for all statuses. Call after Tk root exists."""
    if _status_tk_icons:
        return
    for st in (ST_UNKNOWN, ST_QUEUED, ST_RUNNING, ST_SUCCESS,
               ST_FAILURE, ST_CANCELLED, ST_SKIPPED):
        img = _make_status_icon(st, _ICON_SIZE)
        _status_tk_icons[st] = ImageTk.PhotoImage(img)


class WorkflowRow:

    def __init__(self, parent: tk.Frame, wid: int, state: WorkflowState, alt: bool,
                 jira_base_url: str = ""):
        self.wid    = wid
        self._state = state
        self._jira_base_url = jira_base_url
        bg = BG_ROW_ALT if alt else BG_ROW

        self.frame = tk.Frame(parent, bg=bg)
        self.frame.pack(fill=tk.X, padx=4, pady=(2, 0))

        # Left accent bar (coloured strip indicating status)
        self._accent = tk.Frame(self.frame, bg=COLOUR[state.status], width=3)
        self._accent.pack(side=tk.LEFT, fill=tk.Y)

        # Status icon (Lucide-style image)
        icon = _status_tk_icons.get(state.status, _status_tk_icons.get(ST_UNKNOWN))
        self._icon_lbl = tk.Label(self.frame, image=icon, bg=bg)
        self._icon_lbl.image = icon  # prevent GC
        self._icon_lbl.pack(side=tk.LEFT, padx=(12, 10), pady=8)

        # Right column — polling rate (pack before centre so it reserves space)
        self._poll_lbl = tk.Label(
            self.frame, text="", font=("Segoe UI", 8),
            bg=bg, fg=FG_MUTED, anchor="ne",
        )
        self._poll_lbl.pack(side=tk.RIGHT, padx=(4, 12), anchor="n", pady=(10, 0))

        # Centre column (fills remaining space)
        centre = tk.Frame(self.frame, bg=bg)
        centre.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, pady=(8, 6))

        # Line 1: workflow name + PR number + branch (becomes subtitle in PR mode)
        self._top_row = tk.Frame(centre, bg=bg)
        self._top_row.pack(fill=tk.X)

        self._name_lbl = tk.Label(
            self._top_row, text=state.name, font=("Segoe UI", 9),
            bg=bg, fg=FG_TEXT, cursor="hand2", anchor="w",
        )
        self._name_lbl.pack(side=tk.LEFT)
        self._name_lbl.bind("<Button-1>", self._open_url)

        # Separator " / " between workflow name and PR info (hidden for non-PR)
        self._sep_lbl = tk.Label(
            self._top_row, text=" / ", font=("Segoe UI", 9),
            bg=bg, fg=FG_MUTED, anchor="w",
        )

        # PR number + branch short name (subtitle in PR mode, opens build run)
        self._branch_lbl = tk.Label(
            self._top_row, text="", font=("Segoe UI", 8),
            bg=bg, fg=FG_MUTED, cursor="hand2", anchor="w",
        )
        self._branch_lbl.bind("<Button-1>", self._open_url)

        # Line 2 (optional): badges row — prefix badge + DRAFT badge
        self._badge_row = tk.Frame(centre, bg=bg)
        # (only packed when badges are present)

        self._prefix_lbl = tk.Label(
            self._badge_row, text="", font=("Segoe UI", 7),
            bg="#3D3530", fg="#FBBF24", anchor="w", padx=3, pady=0,
        )

        self._draft_lbl = tk.Label(
            self._badge_row, text="DRAFT", font=("Segoe UI", 7, "bold"),
            bg="#92400E", fg="#FEF3C7", anchor="w", padx=4, pady=0,
        )

        self._jira_lbl = tk.Label(
            self._badge_row, text="", font=("Segoe UI", 7),
            bg="#302830", fg="#A78BFA", anchor="w", padx=3, pady=0,
            cursor="hand2",
        )
        self._jira_lbl.bind("<Button-1>", self._open_jira)

        # Review status badge (APPROVED / CHANGES REQUESTED / REVIEW PENDING)
        self._review_lbl = tk.Label(
            self._badge_row, text="", font=("Segoe UI", 7),
            anchor="w", padx=3, pady=0,
        )

        # PR title (becomes the main title for PR-mode rows, opens PR page)
        self._pr_title_lbl = tk.Label(
            centre, text="", font=("Segoe UI", 9),
            bg=bg, fg=FG_TEXT, anchor="w", cursor="hand2",
        )
        self._pr_title_lbl.bind("<Button-1>", self._open_pr)

        # Line 3: status text
        self._info_lbl = tk.Label(
            centre, text="", font=("Segoe UI", 8),
            bg=bg, fg=FG_MUTED, anchor="w",
        )
        self._info_lbl.pack(fill=tk.X)

        self._bg = bg
        self._update_labels()

    def _open_url(self, _event=None):
        url = self._state.run_url or self._state.url
        if url:
            webbrowser.open(url)

    def _open_pr(self, _event=None):
        if self._state.pr_url:
            webbrowser.open(self._state.pr_url)

    def _open_jira(self, _event=None):
        if self._jira_base_url and self._state.jira_key:
            webbrowser.open(f"{self._jira_base_url.rstrip('/')}/browse/{self._state.jira_key}")

    def update(self, state: WorkflowState, poll_rate: int, jira_base_url: str = ""):
        self._state = state
        self._jira_base_url = jira_base_url or self._jira_base_url
        # Update accent bar colour
        self._accent.config(bg=COLOUR.get(state.status, COLOUR[ST_UNKNOWN]))
        # Update status icon
        icon = _status_tk_icons.get(state.status, _status_tk_icons.get(ST_UNKNOWN))
        self._icon_lbl.config(image=icon)
        self._icon_lbl.image = icon
        self._poll_lbl.config(text=f"every {poll_rate}s")
        self._update_labels()

    def _update_labels(self):
        s = self._state
        status_txt = STATUS_LABEL.get(s.status, s.status)
        if s.error:
            status_txt = f"Error: {s.error}"
        elif s.run_number:
            status_txt = f"{status_txt}  —  run #{s.run_number}"
            if s.started_at:
                try:
                    dt = datetime.fromisoformat(s.started_at.rstrip("Z"))
                    status_txt += f"  ({dt.strftime('%d %b %H:%M')})"
                except Exception:
                    pass

        self._info_lbl.config(text=status_txt)

        # PR-mode labels — PR title is the main title (opens PR page),
        # #number + branch is the subtitle (opens build run).
        has_badges = False
        if s.head_branch:
            self._name_lbl.pack_forget()
            self._sep_lbl.pack_forget()

            # PR title as main title (above #number + branch)
            if s.pr_title:
                self._pr_title_lbl.config(text=s.pr_title)
                self._pr_title_lbl.pack(fill=tk.X, before=self._top_row)
            else:
                self._pr_title_lbl.pack_forget()

            # #number + branch as subtitle (opens build run)
            branch_text = s.branch_short or s.head_branch
            if s.pr_number:
                branch_text = f"#{s.pr_number}  {branch_text}"
            if s.pr_target:
                branch_text += f" \u2192 {s.pr_target}"
            self._branch_lbl.config(text=branch_text)
            self._branch_lbl.pack(side=tk.LEFT, padx=(0, 4))

            # Badges on their own line
            if s.branch_prefix:
                self._prefix_lbl.config(text=s.branch_prefix)
                self._prefix_lbl.pack(side=tk.LEFT, padx=(0, 4))
                has_badges = True
            else:
                self._prefix_lbl.pack_forget()

            if s.is_draft:
                self._draft_lbl.pack(side=tk.LEFT, padx=(0, 4))
                has_badges = True
            else:
                self._draft_lbl.pack_forget()

            if s.jira_key and self._jira_base_url:
                self._jira_lbl.config(text=s.jira_key)
                self._jira_lbl.pack(side=tk.LEFT, padx=(0, 4))
                has_badges = True
            else:
                self._jira_lbl.pack_forget()

            if s.review_status:
                _review_cfg = {
                    "approved":          ("APPROVED",          "#1C3A2A", "#4ADE80"),
                    "changes_requested": ("CHANGES REQUESTED", "#3A1C1C", "#F87171"),
                    "pending":           ("REVIEW PENDING",    "#3D3530", "#FBBF24"),
                }
                text, bg_col, fg_col = _review_cfg.get(
                    s.review_status, ("REVIEW PENDING", "#3D3530", "#FBBF24")
                )
                self._review_lbl.config(text=text, bg=bg_col, fg=fg_col)
                self._review_lbl.pack(side=tk.LEFT, padx=(0, 4))
                has_badges = True
            else:
                self._review_lbl.pack_forget()

            if has_badges:
                self._badge_row.pack(fill=tk.X, pady=(2, 0), before=self._info_lbl)
            else:
                self._badge_row.pack_forget()
        else:
            self._name_lbl.pack(side=tk.LEFT)
            self._sep_lbl.pack_forget()
            self._branch_lbl.pack_forget()
            self._prefix_lbl.pack_forget()
            self._draft_lbl.pack_forget()
            self._jira_lbl.pack_forget()
            self._review_lbl.pack_forget()
            self._pr_title_lbl.pack_forget()
            self._badge_row.pack_forget()


# ---------------------------------------------------------------------------
# Windows startup (registry Run key)
# ---------------------------------------------------------------------------
_STARTUP_REG_KEY  = r"Software\Microsoft\Windows\CurrentVersion\Run"
_STARTUP_REG_NAME = "ActionsMonitor"


class StartupManager:
    """Manage the 'Start with Windows' registry entry."""

    @staticmethod
    def _exe_cmd() -> str:
        """Return the command to launch this script at startup."""
        exe = sys.executable  # pythonw.exe or python.exe
        # Prefer pythonw.exe so no console window appears
        pythonw = Path(exe).parent / "pythonw.exe"
        if pythonw.exists():
            exe = str(pythonw)
        script = str(Path(__file__).resolve())
        return f'"{exe}" "{script}"'

    @classmethod
    def is_enabled(cls) -> bool:
        if not IS_WINDOWS:
            return False
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _STARTUP_REG_KEY) as key:
                val, _ = winreg.QueryValueEx(key, _STARTUP_REG_NAME)
                return bool(val)
        except FileNotFoundError:
            return False
        except Exception:
            return False

    @classmethod
    def enable(cls):
        if not IS_WINDOWS:
            return
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, _STARTUP_REG_KEY,
                0, winreg.KEY_SET_VALUE,
            ) as key:
                winreg.SetValueEx(key, _STARTUP_REG_NAME, 0, winreg.REG_SZ, cls._exe_cmd())
        except Exception as exc:
            print(f"[Startup] Could not enable: {exc}")

    @classmethod
    def disable(cls):
        if not IS_WINDOWS:
            return
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, _STARTUP_REG_KEY,
                0, winreg.KEY_SET_VALUE,
            ) as key:
                winreg.DeleteValue(key, _STARTUP_REG_NAME)
        except FileNotFoundError:
            pass
        except Exception as exc:
            print(f"[Startup] Could not disable: {exc}")


# ---------------------------------------------------------------------------
# Update checker
# ---------------------------------------------------------------------------
class UpdateChecker:
    REPO_URL = "https://github.com/summitnl/ActionsMonitor"

    @staticmethod
    def check() -> Optional[str]:
        """Returns the new commit short-hash if an update is available, None otherwise.

        Skipped when running as a frozen .exe (no git repo available).
        """
        if getattr(sys, "frozen", False):
            return None
        try:
            subprocess.run(
                ["git", "fetch", "origin", "main", "--quiet"],
                cwd=_APP_DIR, timeout=15, capture_output=True,
            )
            local = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=_APP_DIR, capture_output=True, text=True,
            ).stdout.strip()
            remote = subprocess.run(
                ["git", "rev-parse", "origin/main"],
                cwd=_APP_DIR, capture_output=True, text=True,
            ).stdout.strip()
            if local and remote and local != remote:
                return remote[:7]
        except Exception:
            pass
        return None

    @staticmethod
    def apply_update() -> tuple[bool, str]:
        """Pull latest and install deps. Returns (success, message)."""
        try:
            result = subprocess.run(
                ["git", "pull", "origin", "main"],
                cwd=_APP_DIR, capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                return False, result.stderr.strip() or "git pull failed"
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "-r",
                 str(_APP_DIR / "src" / "requirements.txt"), "--quiet"],
                cwd=_APP_DIR, capture_output=True, timeout=60,
            )
            return True, "Update complete"
        except Exception as exc:
            return False, str(exc)

    @staticmethod
    def restart_app():
        """Re-launch the app and exit the current process."""
        os.execv(sys.executable, [sys.executable] + sys.argv)


def _show_update_dialog(root: tk.Tk, commit_hash: str):
    """Show a modal dark-themed update dialog."""
    dlg = tk.Toplevel(root)
    dlg.title(f"{APP_NAME} — Update Available")
    if APP_ICO.exists():
        dlg.iconbitmap(str(APP_ICO))
    dlg.configure(bg=BG_DARK)
    dlg.resizable(False, False)

    pad = {"padx": 20, "pady": 6}

    tk.Label(
        dlg, text="A new version of Actions Monitor is available.",
        font=("Segoe UI", 11, "bold"), bg=BG_DARK, fg=FG_TEXT,
    ).pack(**pad, pady=(16, 6))

    tk.Label(
        dlg, text=f"Latest commit: {commit_hash}",
        font=("Segoe UI", 9), bg=BG_DARK, fg=FG_MUTED,
    ).pack(**pad, pady=(0, 4))

    link = tk.Label(
        dlg, text="View README on GitHub",
        font=("Segoe UI", 9, "underline"), bg=BG_DARK, fg=FG_LINK,
        cursor="hand2",
    )
    link.pack(**pad, pady=(0, 10))
    link.bind("<Button-1>", lambda _: webbrowser.open(f"{UpdateChecker.REPO_URL}#readme"))

    status_lbl = tk.Label(dlg, text="", font=("Segoe UI", 9), bg=BG_DARK, fg=FG_MUTED)
    status_lbl.pack(**pad, pady=(0, 4))

    btn_frame = tk.Frame(dlg, bg=BG_DARK)
    btn_frame.pack(**pad, pady=(0, 16))

    def do_update():
        update_btn.config(state=tk.DISABLED)
        skip_btn.config(state=tk.DISABLED)
        status_lbl.config(text="Updating...", fg=FG_TEXT)
        dlg.update()

        def _run():
            ok, msg = UpdateChecker.apply_update()
            dlg.after(0, lambda: _on_result(ok, msg))

        def _on_result(ok, msg):
            if ok:
                status_lbl.config(text="Update complete — restarting...", fg=COLOUR[ST_SUCCESS])
                dlg.update()
                dlg.after(500, UpdateChecker.restart_app)
            else:
                status_lbl.config(text=f"Update failed: {msg}", fg=COLOUR[ST_FAILURE])
                skip_btn.config(state=tk.NORMAL)

        threading.Thread(target=_run, daemon=True).start()

    update_btn = tk.Button(
        btn_frame, text="Update", font=("Segoe UI", 10),
        bg=ACCENT, fg=FG_TEXT, activebackground=BG_ROW, activeforeground=FG_TEXT,
        relief=tk.FLAT, padx=16, pady=4, cursor="hand2", command=do_update,
    )
    update_btn.pack(side=tk.LEFT, padx=(0, 8))

    skip_btn = tk.Button(
        btn_frame, text="Skip", font=("Segoe UI", 10),
        bg=ACCENT, fg=FG_MUTED, activebackground=BG_ROW, activeforeground=FG_TEXT,
        relief=tk.FLAT, padx=16, pady=4, cursor="hand2", command=dlg.destroy,
    )
    skip_btn.pack(side=tk.LEFT)

    # Center on screen
    dlg.update_idletasks()
    w, h = dlg.winfo_width(), dlg.winfo_height()
    x = (dlg.winfo_screenwidth() - w) // 2
    y = (dlg.winfo_screenheight() - h) // 2
    dlg.geometry(f"+{x}+{y}")

    dlg.grab_set()
    root.wait_window(dlg)


# ---------------------------------------------------------------------------
# Window state persistence
# ---------------------------------------------------------------------------
def _get_monitor_work_areas() -> list[tuple[int, int, int, int]]:
    """Return list of (left, top, right, bottom) work areas for all monitors."""
    areas: list[tuple[int, int, int, int]] = []
    try:
        monitor_enum_proc = ctypes.WINFUNCTYPE(
            ctypes.c_int,
            ctypes.c_ulong, ctypes.c_ulong, ctypes.POINTER(ctypes.wintypes.RECT), ctypes.c_double,
        )

        def callback(hmonitor, hdc, lprect, lparam):
            info = ctypes.wintypes.RECT()
            # MONITORINFO struct: cbSize (DWORD), rcMonitor (RECT), rcWork (RECT), dwFlags (DWORD)
            class MONITORINFO(ctypes.Structure):
                _fields_ = [
                    ("cbSize", ctypes.wintypes.DWORD),
                    ("rcMonitor", ctypes.wintypes.RECT),
                    ("rcWork", ctypes.wintypes.RECT),
                    ("dwFlags", ctypes.wintypes.DWORD),
                ]
            mi = MONITORINFO()
            mi.cbSize = ctypes.sizeof(MONITORINFO)
            if ctypes.windll.user32.GetMonitorInfoW(hmonitor, ctypes.byref(mi)):
                rc = mi.rcWork
                areas.append((rc.left, rc.top, rc.right, rc.bottom))
            return 1  # continue enumeration

        ctypes.windll.user32.EnumDisplayMonitors(
            None, None, monitor_enum_proc(callback), 0,
        )
    except Exception:
        pass
    return areas


def _rect_overlaps(
    x: int, y: int, w: int, h: int,
    areas: list[tuple[int, int, int, int]],
    min_visible: int = 100,
) -> bool:
    """Check if at least min_visible pixels of the window overlap any monitor."""
    for left, top, right, bottom in areas:
        overlap_x = max(0, min(x + w, right) - max(x, left))
        overlap_y = max(0, min(y + h, bottom) - max(y, top))
        if overlap_x >= min_visible and overlap_y >= min(50, min_visible):
            return True
    return False


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------
class MainWindow:
    def __init__(self, config_mgr: ConfigManager, event_queue: queue.Queue):
        self._config_mgr  = config_mgr
        self._event_queue = event_queue
        self._pollers: dict[int, WorkflowPoller] = {}
        self._states:  dict[tuple[int, Optional[str]], WorkflowState]  = {}
        self._rows:    dict[tuple[int, Optional[str]], WorkflowRow]     = {}
        self._tray: Optional[TrayManager] = None
        self._sections: list[tk.Frame] = []           # section header+container frames
        self._wid_container: dict[int, tk.Frame] = {} # wid → section content frame
        self._section_content: dict[str, tk.Frame] = {}    # title → content frame
        self._section_indicators: dict[str, tk.Label] = {} # title → indicator label
        self._collapsed: dict[str, bool] = {}              # title → collapsed flag

        self._root = tk.Tk()
        self._root.title(APP_NAME)
        _generate_app_ico()
        if APP_ICO.exists():
            self._root.iconbitmap(str(APP_ICO))
        # Also set via iconphoto for taskbar/alt-tab on Windows
        try:
            self._app_icon_photos = [
                ImageTk.PhotoImage(_make_base_icon(s)) for s in (256, 64, 48, 32, 16)
            ]
            self._root.wm_iconphoto(True, *self._app_icon_photos)
        except Exception:
            pass
        self._root.configure(bg=BG_DARK)
        self._root.resizable(True, True)
        self._root.geometry("560x420")
        self._root.minsize(400, 200)
        self._restore_window_state()
        self._restore_collapse_state()

        _init_status_icons()
        self._build_ui()
        self._root.protocol("WM_DELETE_WINDOW", self._hide_window)
        self._root.bind("<Unmap>", self._on_unmap)

        self._start_pollers()
        self._root.after(500, self._drain_queue)
        self._root.after(5000, self._watch_config)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self):
        # Dark ttk scrollbar style
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Dark.Vertical.TScrollbar",
                        background=BG_ROW, troughcolor=BG_DARK,
                        bordercolor=BG_DARK, arrowcolor=FG_MUTED,
                        lightcolor=BG_DARK, darkcolor=BG_DARK)
        style.map("Dark.Vertical.TScrollbar",
                  background=[("active", FG_MUTED), ("!active", BG_ROW)])

        # Title bar area
        header = tk.Frame(self._root, bg=BG_DARK, height=46)
        header.pack(fill=tk.X)
        header.pack_propagate(False)
        tk.Label(
            header, text=APP_NAME, font=("Segoe UI", 12),
            bg=BG_DARK, fg=FG_TEXT,
        ).pack(side=tk.LEFT, padx=16, pady=10)

        refresh_btn = tk.Label(
            header, text="Refresh", font=("Segoe UI", 9),
            bg="#44403C", fg=FG_TEXT, padx=12, pady=4, cursor="hand2",
        )
        refresh_btn.pack(side=tk.RIGHT, padx=(0, 16), pady=8)
        refresh_btn.bind("<Button-1>", lambda _: self._refresh_all())

        # Thin warm separator line under header
        tk.Frame(self._root, bg="#44403C", height=1).pack(fill=tk.X)

        # Column headers
        hdr = tk.Frame(self._root, bg=BG_DARK)
        hdr.pack(fill=tk.X, padx=14, pady=(6, 2))
        tk.Label(hdr, text="STATUS / WORKFLOW", font=("Segoe UI", 7, "bold"),
                 bg=BG_DARK, fg=FG_MUTED, anchor="w").pack(side=tk.LEFT, expand=True, fill=tk.X)
        tk.Label(hdr, text="POLL", font=("Segoe UI", 7, "bold"),
                 bg=BG_DARK, fg=FG_MUTED, width=12, anchor="e").pack(side=tk.RIGHT)

        # Scrollable workflow list
        container = tk.Frame(self._root, bg=BG_DARK)
        container.pack(fill=tk.BOTH, expand=True, padx=8)

        canvas = tk.Canvas(container, bg=BG_DARK, highlightthickness=0)
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview,
                                  style="Dark.Vertical.TScrollbar")
        canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._list_frame = tk.Frame(canvas, bg=BG_DARK)
        self._canvas_window = canvas.create_window((0, 0), window=self._list_frame, anchor="nw")

        def _on_canvas_configure(e):
            canvas.itemconfig(self._canvas_window, width=e.width)
        canvas.bind("<Configure>", _on_canvas_configure)

        def _on_frame_configure(_e):
            # Use after_idle so geometry is fully resolved before updating scroll region
            canvas.after_idle(lambda: canvas.configure(
                scrollregion=(0, 0, self._list_frame.winfo_reqwidth(),
                              self._list_frame.winfo_reqheight())))
        self._list_frame.bind("<Configure>", _on_frame_configure)

        def _on_mousewheel(e):
            canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        self._canvas = canvas

        # Footer
        footer = tk.Frame(self._root, bg=ACCENT)
        footer.pack(fill=tk.X, side=tk.BOTTOM)

        # Thin separator above footer
        tk.Frame(footer, bg="#44403C", height=1).pack(fill=tk.X)

        # Row 1: config hint + open button
        footer_row1 = tk.Frame(footer, bg=ACCENT)
        footer_row1.pack(fill=tk.X, padx=14, pady=(8, 2))

        tk.Label(
            footer_row1,
            text="Edit config.yaml to add/change workflows.",
            font=("Segoe UI", 8), bg=ACCENT, fg=FG_MUTED,
        ).pack(side=tk.LEFT)

        open_btn = tk.Label(
            footer_row1, text="Open config ↗", font=("Segoe UI", 8, "bold"),
            bg=ACCENT, fg=FG_LINK, cursor="hand2",
        )
        open_btn.pack(side=tk.RIGHT)
        open_btn.bind("<Button-1>", lambda _: ConfigManager.open_in_editor())

        # Row 2: startup checkbox (Windows only)
        footer_row2 = tk.Frame(footer, bg=ACCENT)
        footer_row2.pack(fill=tk.X, padx=14, pady=(0, 8))

        if IS_WINDOWS:
            self._startup_var = tk.BooleanVar(value=StartupManager.is_enabled())
            startup_cb = tk.Checkbutton(
                footer_row2,
                text="Start with Windows",
                variable=self._startup_var,
                command=self._toggle_startup,
                font=("Segoe UI", 8),
                bg=ACCENT, fg=FG_MUTED,
                activebackground=ACCENT, activeforeground=FG_TEXT,
                selectcolor=BG_DARK,
                relief=tk.FLAT, bd=0,
            )
            startup_cb.pack(side=tk.LEFT)
        else:
            tk.Label(
                footer_row2, text="", bg=ACCENT, font=("Segoe UI", 8),
            ).pack(side=tk.LEFT)

    # ------------------------------------------------------------------
    # Startup toggle
    # ------------------------------------------------------------------
    def _toggle_startup(self):
        if self._startup_var.get():
            StartupManager.enable()
        else:
            StartupManager.disable()

    # ------------------------------------------------------------------
    # Sections
    # ------------------------------------------------------------------
    def _create_section(self, title: str) -> tk.Frame:
        """Create a collapsible section header + content frame and return the content frame."""
        section = tk.Frame(self._list_frame, bg=BG_DARK)
        section.pack(fill=tk.X)
        self._sections.append(section)

        is_collapsed = self._collapsed.get(title, False)

        hdr = tk.Frame(section, bg=BG_DARK, cursor="hand2")
        hdr.pack(fill=tk.X, padx=12, pady=(10, 4))

        indicator = tk.Label(hdr, text="▸" if is_collapsed else "▾",
                             font=("Segoe UI", 9, "bold"),
                             bg=BG_DARK, fg=FG_LINK, anchor="w")
        indicator.pack(side=tk.LEFT, padx=(0, 4))
        self._section_indicators[title] = indicator

        title_lbl = tk.Label(hdr, text=title, font=("Segoe UI", 9, "bold"),
                             bg=BG_DARK, fg=FG_LINK, anchor="w")
        title_lbl.pack(side=tk.LEFT)

        # Horizontal rule — warm tone
        sep = tk.Frame(hdr, bg="#44403C", height=1)
        sep.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(10, 0), pady=1)

        content = tk.Frame(section, bg=BG_DARK)
        if not is_collapsed:
            content.pack(fill=tk.X)
        self._section_content[title] = content

        # Bind click on all header widgets
        def toggle(_e=None, t=title):
            self._toggle_section(t)
        for widget in (hdr, indicator, title_lbl, sep):
            widget.bind("<Button-1>", toggle)

        return content

    def _toggle_section(self, title: str):
        """Toggle collapse/expand for a section."""
        is_collapsed = not self._collapsed.get(title, False)
        self._collapsed[title] = is_collapsed

        content = self._section_content.get(title)
        indicator = self._section_indicators.get(title)

        if content:
            if is_collapsed:
                content.pack_forget()
            else:
                content.pack(fill=tk.X)
        if indicator:
            indicator.config(text="▸" if is_collapsed else "▾")

        self._save_collapse_state()

    def _save_collapse_state(self):
        """Persist collapsed sections to state.json."""
        try:
            state = {}
            if STATE_FILE.exists():
                with open(STATE_FILE, encoding="utf-8") as fh:
                    state = json.load(fh)
            collapsed = [t for t, c in self._collapsed.items() if c]
            if collapsed:
                state["collapsed_sections"] = collapsed
            else:
                state.pop("collapsed_sections", None)
            with open(STATE_FILE, "w", encoding="utf-8") as fh:
                json.dump(state, fh, indent=2)
        except Exception:
            pass

    def _destroy_sections(self):
        for sec in self._sections:
            sec.destroy()
        self._sections.clear()
        self._wid_container.clear()
        self._section_content.clear()
        self._section_indicators.clear()

    # ------------------------------------------------------------------
    # Pollers
    # ------------------------------------------------------------------
    def _start_pollers(self):
        cfg      = self._config_mgr.get()
        notif_cfg = cfg.get("notifications", {})
        NOTIF.set_batch_window(float(notif_cfg.get("batch_window", 3)))
        workflows = cfg.get("workflows") or []

        # Build sections: branch-mode entries share one section; PR/actor each get their own
        branch_container = None
        for wid, entry in enumerate(workflows):
            mode = entry.get("mode", "branch")
            if mode in ("pr", "actor"):
                name = entry.get("name") or entry.get("url", "PR Workflows" if mode == "pr" else "My Runs")
                container = self._create_section(name)
            else:
                if branch_container is None:
                    branch_container = self._create_section("Workflows")
                container = branch_container
            self._wid_container[wid] = container

        for wid, entry in enumerate(workflows):
            self._add_poller(wid, entry)

    def _add_poller(self, wid: int, entry: dict):
        if wid in self._pollers:
            return
        mode = entry.get("mode", "branch")
        url = entry.get("url", "")
        try:
            _, _, wf_file, url_branch = parse_workflow_url(url)
        except ValueError:
            wf_file = url
            url_branch = None

        container = self._wid_container.get(wid, self._list_frame)

        if mode == "pr":
            # PR mode: rows are created dynamically, no initial row
            poller = PRWorkflowPoller(wid, entry, self._config_mgr, self._event_queue)
        elif mode == "actor":
            # Actor mode: rows are created dynamically, no initial row
            poller = ActorWorkflowPoller(wid, entry, self._config_mgr, self._event_queue)
        else:
            branch   = entry.get("branch") or url_branch
            name     = entry.get("name") or wf_file or url
            state    = WorkflowState(name=name, url=url, branch=branch)
            key = (wid, None)
            self._states[key] = state

            alt = len(self._rows) % 2 == 1
            jira_url = self._config_mgr.get().get("jira_base_url", "")
            row = WorkflowRow(container, wid, state, alt, jira_base_url=jira_url)
            poll_rate = int(entry.get("polling_rate", POLL_DEFAULT))
            row.update(state, poll_rate, jira_base_url=jira_url)
            self._rows[key] = row

            poller = WorkflowPoller(wid, entry, self._config_mgr, self._event_queue)

        self._pollers[wid] = poller
        poller.start()

    def _stop_all_pollers(self):
        for p in self._pollers.values():
            p.stop()
        self._pollers.clear()

    def _refresh_all(self):
        """Trigger an immediate re-poll of all workflows."""
        for p in self._pollers.values():
            p.trigger_poll()

    # ------------------------------------------------------------------
    # Queue drain (called periodically on main thread)
    # ------------------------------------------------------------------
    def _drain_queue(self):
        try:
            while True:
                event: StatusEvent = self._event_queue.get_nowait()
                self._apply_event(event)
        except queue.Empty:
            pass
        finally:
            self._root.after(500, self._drain_queue)

    def _apply_event(self, event: StatusEvent):
        key = (event.workflow_id, event.sub_key)
        cfg      = self._config_mgr.get()
        workflows = cfg.get("workflows") or []
        entry    = workflows[event.workflow_id] if event.workflow_id < len(workflows) else {}
        poll_rate = int(entry.get("polling_rate", POLL_DEFAULT))
        jira_url  = cfg.get("jira_base_url", "")

        if event.removed:
            # Remove a stale PR row
            row = self._rows.pop(key, None)
            if row:
                row.frame.destroy()
            self._states.pop(key, None)
            self._restripe_rows()
        else:
            self._states[key] = event.new_state
            row = self._rows.get(key)
            if row:
                row.update(event.new_state, poll_rate, jira_base_url=jira_url)
            elif event.sub_key is not None:
                # Dynamically create a new PR row inside its section container
                container = self._wid_container.get(event.workflow_id, self._list_frame)
                alt = len(self._rows) % 2 == 1
                new_row = WorkflowRow(container, event.workflow_id, event.new_state, alt,
                                      jira_base_url=jira_url)
                new_row.update(event.new_state, poll_rate, jira_base_url=jira_url)
                self._rows[key] = new_row

        if self._tray:
            self._tray.update(list(self._states.values()))

    def _restripe_rows(self):
        """Recalculate alternating row backgrounds after a row is removed."""
        for i, row in enumerate(self._rows.values()):
            bg = BG_ROW_ALT if i % 2 == 1 else BG_ROW
            row._bg = bg
            row.frame.config(bg=bg)
            for widget in row.frame.winfo_children():
                try:
                    widget.config(bg=bg)
                except tk.TclError:
                    pass

    # ------------------------------------------------------------------
    # Config hot-reload
    # ------------------------------------------------------------------
    def _watch_config(self):
        changed = self._config_mgr.load()
        if changed:
            self._reload_pollers()
        self._root.after(2000, self._watch_config)


    def _reload_pollers(self):
        global _cached_github_username
        self._stop_all_pollers()
        self._rows.clear()
        self._states.clear()
        self._destroy_sections()
        # Reset cached username so a token change takes effect
        with _github_username_lock:
            _cached_github_username = None
        self._start_pollers()

    # ------------------------------------------------------------------
    # Window / tray behaviour
    # ------------------------------------------------------------------
    def set_tray(self, tray: TrayManager):
        self._tray = tray

    # ------------------------------------------------------------------
    # Window state persistence
    # ------------------------------------------------------------------
    def _save_window_state(self):
        """Save current window geometry to state.json."""
        try:
            state = {}
            if STATE_FILE.exists():
                with open(STATE_FILE, encoding="utf-8") as fh:
                    state = json.load(fh)
            state["window"] = {
                "x": self._root.winfo_x(),
                "y": self._root.winfo_y(),
                "width": self._root.winfo_width(),
                "height": self._root.winfo_height(),
            }
            collapsed = [t for t, c in self._collapsed.items() if c]
            if collapsed:
                state["collapsed_sections"] = collapsed
            else:
                state.pop("collapsed_sections", None)
            with open(STATE_FILE, "w", encoding="utf-8") as fh:
                json.dump(state, fh, indent=2)
        except Exception as exc:
            print(f"[State] Save error: {exc}")

    def _restore_collapse_state(self):
        """Load collapsed section titles from state.json."""
        try:
            if not STATE_FILE.exists():
                return
            with open(STATE_FILE, encoding="utf-8") as fh:
                state = json.load(fh)
            for title in state.get("collapsed_sections", []):
                self._collapsed[title] = True
        except Exception:
            pass

    def _restore_window_state(self):
        """Restore window geometry from state.json, clamped to visible monitors."""
        try:
            if not STATE_FILE.exists():
                return
            with open(STATE_FILE, encoding="utf-8") as fh:
                state = json.load(fh)
            win = state.get("window")
            if not win:
                return

            x = int(win["x"])
            y = int(win["y"])
            w = max(int(win["width"]), 400)
            h = max(int(win["height"]), 200)

            # Check visibility against monitor work areas
            areas = _get_monitor_work_areas()
            if areas and not _rect_overlaps(x, y, w, h, areas):
                # Window would be off-screen — keep size but reset position
                self._root.geometry(f"{w}x{h}")
                return

            if not areas:
                # Fallback: single-monitor check via tkinter
                sw = self._root.winfo_screenwidth()
                sh = self._root.winfo_screenheight()
                if x + w < 100 or x > sw - 100 or y + h < 50 or y > sh - 50:
                    self._root.geometry(f"{w}x{h}")
                    return

            self._root.geometry(f"{w}x{h}+{x}+{y}")
        except Exception as exc:
            print(f"[State] Restore error: {exc}")

    def _hide_window(self):
        self._root.withdraw()

    def _show_window(self):
        self._root.deiconify()
        self._root.lift()
        self._root.focus_force()

    def _on_unmap(self, event):
        if event.widget is self._root:
            self._root.withdraw()

    def _quit(self):
        self._save_window_state()
        self._stop_all_pollers()
        if self._tray:
            self._tray.stop()
        self._root.destroy()

    def run(self):
        self._root.mainloop()

    # Expose callbacks for tray
    @property
    def show_callback(self):
        return lambda: self._root.after(0, self._show_window)

    @property
    def quit_callback(self):
        return lambda: self._root.after(0, self._quit)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
    config_mgr  = ConfigManager()

    # Check for updates before starting the main UI
    new_version = UpdateChecker.check()
    if new_version:
        root = tk.Tk()
        root.withdraw()
        _show_update_dialog(root, new_version)
        root.destroy()

    event_queue: queue.Queue = queue.Queue()

    win  = MainWindow(config_mgr, event_queue)
    tray = TrayManager(win.show_callback, win.quit_callback)
    win.set_tray(tray)
    tray.start()

    # Update tray icon immediately with initial (unknown) states
    tray.update(list(win._states.values()))

    win.run()


if __name__ == "__main__":
    main()
