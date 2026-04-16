#!/usr/bin/env python3
"""
Actions Monitor — Lightweight GitHub Actions workflow status monitor.
"""

from __future__ import annotations

import ctypes
try:
    import ctypes.wintypes  # Windows-only; used by _get_monitor_work_areas()
except (ImportError, ValueError):
    pass
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
import math
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, parse_qs, unquote
import stat
import base64
import io

import tkinter as tk
from tkinter import ttk

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
    # Tell Windows to identify this process as "Actions Monitor" rather than "Python"
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Summit.ActionsMonitor")

# Linux system dependency check — warn about missing libs needed for tray/notifications
_LINUX_MISSING: list[str] = []
if IS_LINUX:
    import importlib
    for _gi_mod, _pkg in [("gi", "gir1.2-gtk-3.0"),
                          ("gi.repository.Gtk", "gir1.2-gtk-3.0"),
                          ("gi.repository.AyatanaAppIndicator3", "gir1.2-ayatanaappindicator3-0.1")]:
        try:
            importlib.import_module(_gi_mod)
        except (ImportError, ValueError):
            if _pkg not in _LINUX_MISSING:
                _LINUX_MISSING.append(_pkg)
    if not shutil.which("paplay") and not shutil.which("aplay"):
        _LINUX_MISSING.append("pulseaudio-utils (paplay) or alsa-utils (aplay)")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
APP_NAME    = "Actions Monitor"
APP_VERSION = "1.0"

try:
    from version import BUILD_COMMIT
except ImportError:
    BUILD_COMMIT = "dev"

# When frozen by PyInstaller, __file__ points to a temp dir.
# Use the executable's directory instead so config/state live next to the .exe.
# When running from source in src/, go up one level to the project root.
if getattr(sys, "frozen", False):
    _APP_DIR = Path(sys.executable).parent
else:
    _APP_DIR = Path(__file__).resolve().parent.parent

# Summit logo (docs/summit.png exported at 56px height, base64-encoded to avoid bundling issues)
_SUMMIT_LOGO_B64 = (
    "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"
)

CONFIG_FILE    = _APP_DIR / "config.yaml"
STATE_FILE     = _APP_DIR / "state.json"
APP_ICO        = _APP_DIR / "app.ico"
_FOCUS_VBS     = _APP_DIR / "_focus.vbs"
_FOCUS_SIGNAL  = _APP_DIR / "_focus_signal"


def _ensure_focus_vbs():
    """Create a small VBScript that writes a signal file when executed (silent, no CMD flash)."""
    script = (
        'Set fso = CreateObject("Scripting.FileSystemObject")\n'
        f'fso.CreateTextFile "{_FOCUS_SIGNAL}", True\n'
    )
    _FOCUS_VBS.write_text(script, encoding="utf-8")

POLL_DEFAULT = 60  # seconds

# Status values
ST_UNKNOWN    = "unknown"
ST_QUEUED     = "queued"
ST_RUNNING    = "in_progress"
ST_SUCCESS    = "success"
ST_FAILURE    = "failure"
ST_CANCELLED  = "cancelled"
ST_SKIPPED    = "skipped"

# Sort priority: higher = more urgent (used for status-based row sorting)
_STATUS_PRIORITY = {
    ST_FAILURE: 4, ST_RUNNING: 3, ST_QUEUED: 2, ST_SUCCESS: 1,
    ST_UNKNOWN: 0, ST_CANCELLED: 0, ST_SKIPPED: 0,
}

# Review status badge config: state → (label, bg_colour, fg_colour)
_REVIEW_BADGE_CFG = {
    "approved":          ("APPROVED",          "#1C3A2A", "#4ADE80"),
    "changes_requested": ("CHANGES REQUESTED", "#3A1C1C", "#F87171"),
    "commented":         ("IN REVIEW",         "#1C2A3A", "#60A5FA"),
    "pending":           ("REVIEW PENDING",    "#3D3530", "#FBBF24"),
}

# Staleness badge config: level → (bg_colour, fg_colour)
_STALENESS_BADGE_CFG = {
    "slightly_stale":   ("#3D3520", "#EAB308"),
    "moderately_stale": ("#3A2A1C", "#F97316"),
    "very_stale":       ("#3A1C1C", "#EF4444"),
}

# Snoozed row keys — shared between MainWindow and pollers (thread-safe)
_snoozed_keys: set[tuple[int, Optional[str]]] = set()
_snoozed_lock = threading.Lock()

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


def _gh_headers(token: str) -> dict[str, str]:
    """Build standard GitHub API request headers."""
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _resolve_status(api_status: str, conclusion: Optional[str]) -> str:
    """Map GitHub API status/conclusion to an internal status constant."""
    if api_status == "completed":
        return CONCLUSION_MAP.get(conclusion, ST_UNKNOWN)
    if api_status == "in_progress":
        return ST_RUNNING
    if api_status == "queued":
        return ST_QUEUED
    return ST_UNKNOWN


# UI colours — warm dark base
BG_DARK    = "#1C1917"   # stone-900
BG_ROW     = "#292524"   # stone-800
BG_ROW_ALT = "#231F1E"   # between stone-800 and 900
FG_TEXT    = "#E7E5E4"   # stone-200
FG_MUTED   = "#A8A29E"   # stone-400
FG_LINK    = "#FBBF24"   # amber-400 (primary accent)
ACCENT     = "#292524"   # stone-800
UI_FONT    = "Segoe UI" if IS_WINDOWS else "DejaVu Sans"

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
        "max_notification_age": "1h",
        "new_run":  {"enabled": True,  "sound": "default" if IS_LINUX else "whistle"},
        "failure":  {"enabled": True,  "sound": "default"},
        "success":  {"enabled": True,  "sound": "none"},
    },
    "staleness_thresholds": {
        "slightly_stale": "1d",
        "moderately_stale": "3d",
        "very_stale": "5d",
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
            # On Linux, replace Windows-only named sounds with cross-platform defaults
            if IS_LINUX:
                try:
                    text = CONFIG_FILE.read_text(encoding="utf-8")
                    text = text.replace("sound: whistle", "sound: default")
                    CONFIG_FILE.write_text(text, encoding="utf-8")
                except Exception:
                    pass
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

    resp = requests.get(api_url, params=params, headers=_gh_headers(token), timeout=15)
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
    resp = requests.get("https://api.github.com/user", headers=_gh_headers(token), timeout=15)
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
    resp = requests.get(api_url, params=params, headers=_gh_headers(token), timeout=15)
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
    resp = requests.get(api_url, params=params, headers=_gh_headers(token), timeout=15)
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


# Duration parsing
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
    run_updated_at: Optional[str] = None  # ISO 8601 from GitHub run API (last status change)
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
    review_status: Optional[str] = None   # "approved" | "changes_requested" | "commented" | "pending" | None
    pr_target:     Optional[str] = None   # target branch (e.g. "acceptance", "production")
    jira_key:      Optional[str] = None
    staleness_level: Optional[str] = None  # "slightly_stale" | "moderately_stale" | "very_stale"
    pr_updated_at:   Optional[str] = None  # ISO 8601 from GitHub PR API


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
    row_keys:   list[tuple[int, Optional[str]]]


class NotificationManager:
    def __init__(self):
        self._lock = threading.Lock()
        self._pending: list[_PendingNotification] = []
        self._flush_timer: Optional[threading.Timer] = None
        self._batch_window: float = 3.0
        self._recently_notified: set[tuple[int, Optional[str]]] = set()
        self._notified_lock = threading.Lock()

    def set_batch_window(self, seconds: float):
        with self._lock:
            self._batch_window = max(seconds, 0.0)

    def drain_recently_notified(self) -> set[tuple[int, Optional[str]]]:
        with self._notified_lock:
            result = set(self._recently_notified)
            self._recently_notified.clear()
            return result

    def notify(self, title: str, message: str, sound_cfg: str,
               url: Optional[str] = None, notif_type: str = "new_run",
               row_keys: Optional[list[tuple[int, Optional[str]]]] = None):
        with self._lock:
            if self._batch_window <= 0:
                # Batching disabled — fire immediately (old behaviour)
                threading.Thread(
                    target=self._send,
                    args=(title, message, sound_cfg, url, row_keys or []),
                    daemon=True,
                ).start()
                return
            self._pending.append(_PendingNotification(notif_type, title, message, sound_cfg, url, row_keys or []))
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
                args=(item.title, item.message, item.sound_cfg, item.url, item.row_keys),
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

        # Collect all row keys from batched notifications
        all_keys: list[tuple[int, Optional[str]]] = []
        for item in batch:
            all_keys.extend(item.row_keys)

        threading.Thread(
            target=self._send,
            args=(title, body, sound, url, all_keys),
            daemon=True,
        ).start()

    # -- low-level send / sound ----------------------------------------------
    def _send(self, title: str, message: str, sound_cfg: str,
              url: Optional[str] = None,
              row_keys: Optional[list[tuple[int, Optional[str]]]] = None):
        # Record which rows were notified (for blink-on-focus)
        if row_keys:
            with self._notified_lock:
                self._recently_notified.update(row_keys)
        sound_coupled = False
        if IS_WINDOWS and WINOTIFY_AVAILABLE:
            try:
                toast = _WinNotification(
                    app_id="Summit.ActionsMonitor",
                    title=title,
                    msg=message,
                    duration="short",
                    icon=str(APP_ICO) if APP_ICO.exists() else "",
                    launch=str(_FOCUS_VBS) if _FOCUS_VBS.exists() else "",
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

        state.status = _resolve_status(api_status, conclusion)

        state.run_id    = run_id
        state.run_url   = run.get("html_url")
        state.run_number = run.get("run_number")
        state.started_at = run.get("run_started_at") or run.get("created_at")
        state.run_updated_at = run.get("updated_at")
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

        self.event_queue.put(StatusEvent(self.wid, state, notif_type))

        # Fire notification
        if notif_type:
            self._fire_notification(notif_type, state, notif_cfg)

    def _fire_notification(self, notif_type: str, state: WorkflowState, global_notif: dict,
                           is_pr: bool = False, sub_key: Optional[str] = None):
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
        NOTIF.notify(titles[notif_type], messages[notif_type], sound, url=url, notif_type=notif_type,
                     row_keys=[(self.wid, sub_key)])


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

    def _cache_pr(self, pr_num: int, pr_data: dict):
        """Update the PR cache from a PR API response dict."""
        self._pr_cache[pr_num] = {
            "draft": pr_data.get("draft", False),
            "title": pr_data.get("title", ""),
            "base_ref": pr_data.get("base", {}).get("ref", ""),
            "updated_at": pr_data.get("updated_at", ""),
        }

    def _poll(self):
        cfg   = self.config_mgr.get()
        token = cfg.get("github_token", "")
        notif_cfg = cfg.get("notifications", {})

        # Staleness thresholds (sorted descending so highest is checked first)
        stale_cfg = cfg.get("staleness_thresholds", {})
        staleness_thresholds = sorted(
            [
                (parse_duration(stale_cfg.get("very_stale", "5d")), "very_stale"),
                (parse_duration(stale_cfg.get("moderately_stale", "3d")), "moderately_stale"),
                (parse_duration(stale_cfg.get("slightly_stale", "1d")), "slightly_stale"),
            ],
            key=lambda t: t[0],
            reverse=True,
        )

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

        # Fetch the user's open PRs — used to discover branches with old runs
        # AND to filter out branches whose PRs have been closed/merged.
        branches_with_runs = {r.get("head_branch") for r in all_runs}
        try:
            open_prs = self._fetch_user_open_prs(username, token)
        except Exception:
            open_prs = []
        open_pr_branches = {pr["branch"] for pr in open_prs}
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

        # Drop runs for branches that no longer have an open PR
        if open_pr_branches:
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
                    st = _resolve_status(api_status, conclusion)
                    run_statuses.append(st)

                    p = _STATUS_PRIORITY.get(st, 0)
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
                state.run_updated_at = run.get("updated_at")
                state.conclusion = run.get("conclusion")

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
                    state.review_status = self._fetch_pr_review_status(pr_num, token)

                    # Compute PR staleness from updated_at
                    updated_at_str = self._pr_cache.get(pr_num, {}).get("updated_at", "")
                    if updated_at_str:
                        state.pr_updated_at = updated_at_str
                        try:
                            updated_dt = datetime.fromisoformat(updated_at_str.replace("Z", "+00:00"))
                            age_secs = (datetime.now(updated_dt.tzinfo) - updated_dt).total_seconds()
                            for threshold_secs, level in staleness_thresholds:
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

                if prev_rids and cur_run_ids != prev_rids and not cur_run_ids.issubset(prev_rids):
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
            elapsed = (now - self._last_seen[sk]).total_seconds()
            if elapsed >= self._stale_after:
                branch_part = sk.split("#")[0] if "#" in sk else sk
                dummy = WorkflowState(name=self.name_display, url=self.cfg_entry.get("url", ""), branch=branch_part)
                self.event_queue.put(StatusEvent(self.wid, dummy, sub_key=sk, removed=True))
                del self._last_seen[sk]
                self._prev_run_ids.pop(sk, None)
                self._prev_statuses.pop(sk, None)

    def _fetch_user_open_prs(self, username: str, token: str) -> list[dict]:
        """Fetch open PRs authored by the user. Returns list of {number, branch, base_ref}."""
        url = (
            f"https://api.github.com/repos/{self.owner}/{self.repo}"
            f"/pulls?state=open&sort=updated&direction=desc&per_page=50"
        )
        resp = requests.get(url, headers=_gh_headers(token), timeout=15)
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
                self._cache_pr(pr_num, pr)
                results.append({"number": pr_num, "branch": branch, "base_ref": base_ref})
        return results

    def _fetch_branch_runs(self, wf_file: str, branch: str, token: str) -> list[dict]:
        """Fetch latest workflow runs for a specific branch."""
        url = (
            f"https://api.github.com/repos/{self.owner}/{self.repo}"
            f"/actions/workflows/{wf_file}/runs"
        )
        params = {"branch": branch, "per_page": 1}
        resp = requests.get(url, params=params, headers=_gh_headers(token), timeout=15)
        resp.raise_for_status()
        return resp.json().get("workflow_runs", [])

    def _fetch_prs_for_branch(self, branch: str, token: str) -> list[dict]:
        """Fetch open PRs for a head branch. Returns list of {number, base_ref}."""
        try:
            url = (
                f"https://api.github.com/repos/{self.owner}/{self.repo}"
                f"/pulls?head={self.owner}:{branch}&state=open&per_page=10"
            )
            resp = requests.get(url, headers=_gh_headers(token), timeout=15)
            resp.raise_for_status()
            results = []
            for pr in resp.json():
                pr_num = pr.get("number")
                if pr_num:
                    self._cache_pr(pr_num, pr)
                    results.append({"number": pr_num, "base_ref": pr.get("base", {}).get("ref", "")})
            return results
        except Exception:
            return []

    def _fetch_pr_review_status(self, pr_number: int, token: str) -> Optional[str]:
        """Fetch the aggregate review status for a PR.
        Returns 'approved', 'changes_requested', 'commented', 'pending', or None."""
        try:
            url = (
                f"https://api.github.com/repos/{self.owner}/{self.repo}"
                f"/pulls/{pr_number}/reviews"
            )
            resp = requests.get(url, headers=_gh_headers(token), timeout=15)
            resp.raise_for_status()
            reviews = resp.json()

            # Keep only the latest review per reviewer (ignore PENDING/DISMISSED)
            latest: dict[str, str] = {}
            has_comments = False
            for r in reviews:
                user = r.get("user", {}).get("login", "")
                state = r.get("state", "")
                if state in ("APPROVED", "CHANGES_REQUESTED"):
                    latest[user] = state
                elif state == "COMMENTED":
                    has_comments = True

            if not latest:
                return "commented" if has_comments else "pending"
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

            state.status = _resolve_status(api_status, conclusion)

            state.run_id     = run_id
            state.run_url    = run.get("html_url")
            state.run_number = run.get("run_number")
            state.started_at = run.get("run_started_at") or run.get("created_at")
            state.run_updated_at = run.get("updated_at")
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

            self.event_queue.put(StatusEvent(self.wid, state, notif_type, sub_key=composite_key))

            if notif_type:
                self._fire_notification(notif_type, state, notif_cfg, is_pr=False, sub_key=composite_key)

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
    fsize = int(hi * 0.52)
    font = None
    for fname in ("segoeuib.ttf", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf", "FreeSansBold.ttf"):
        try:
            font = ImageFont.truetype(fname, fsize)
            break
        except Exception:
            continue
    if font is None:
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


# --- Refresh icon (Lucide rotate-cw) for header button ---

def _make_refresh_icon(size: int = 16, colour: str = FG_LINK) -> Image.Image:
    """Lucide rotate-cw icon: circular arrow in the given colour."""
    ss = 4
    hi = size * ss
    img = Image.new("RGBA", (hi, hi), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    sw = max(3, round(hi / 16 * 2.2))
    cx, cy = hi / 2, hi / 2
    r = hi * 0.36
    # Arc: nearly full circle, leave gap at top-right for arrowhead
    draw.arc([cx - r, cy - r, cx + r, cy + r], start=-30, end=300,
             fill=colour, width=sw)
    # Arrowhead at the end of the arc (top-right, pointing clockwise)
    angle = math.radians(-30)
    ax = cx + r * math.cos(angle)
    ay = cy + r * math.sin(angle)
    arrow_len = hi * 0.18
    draw.polygon([
        (ax, ay),
        (ax - arrow_len, ay - arrow_len * 0.15),
        (ax - arrow_len * 0.15, ay - arrow_len),
    ], fill=colour)
    return img.resize((size, size), Image.LANCZOS)


# --- Snooze button icon (crescent moon) ---

_SNOOZE_ICON_SIZE = 24

def _make_snooze_icon(size: int = _SNOOZE_ICON_SIZE, bg_colour: str = "#3D3530",
                      fg_colour: str = "#A8A29E") -> Image.Image:
    """Zzz icon on a filled circle background for the snooze button."""
    ss = 4
    hi = size * ss
    img = Image.new("RGBA", (hi, hi), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # Background circle
    pad = int(hi * 0.02)
    draw.ellipse([pad, pad, hi - pad, hi - pad], fill=bg_colour)
    # Draw three Z letters inside the circle
    sw = max(2, round(hi / 16 * 1.3))
    c = fg_colour
    # Inset for the Z glyphs (inside the circle)
    inset = int(hi * 0.18)
    iw = hi - 2 * inset  # usable area
    # Large Z (bottom-left area)
    zw, zh = int(iw * 0.50), int(iw * 0.32)
    zx, zy = inset, inset + int(iw * 0.55)
    draw.line([(zx, zy), (zx + zw, zy)], fill=c, width=sw)
    draw.line([(zx + zw, zy), (zx, zy + zh)], fill=c, width=sw)
    draw.line([(zx, zy + zh), (zx + zw, zy + zh)], fill=c, width=sw)
    # Medium Z (middle area)
    zw2, zh2 = int(zw * 0.60), int(zh * 0.60)
    zx2, zy2 = inset + int(iw * 0.28), inset + int(iw * 0.22)
    draw.line([(zx2, zy2), (zx2 + zw2, zy2)], fill=c, width=sw)
    draw.line([(zx2 + zw2, zy2), (zx2, zy2 + zh2)], fill=c, width=sw)
    draw.line([(zx2, zy2 + zh2), (zx2 + zw2, zy2 + zh2)], fill=c, width=sw)
    # Small Z (top-right area)
    zw3, zh3 = int(zw * 0.35), int(zh * 0.35)
    zx3, zy3 = inset + int(iw * 0.52), inset + int(iw * 0.02)
    draw.line([(zx3, zy3), (zx3 + zw3, zy3)], fill=c, width=sw)
    draw.line([(zx3 + zw3, zy3), (zx3, zy3 + zh3)], fill=c, width=sw)
    draw.line([(zx3, zy3 + zh3), (zx3 + zw3, zy3 + zh3)], fill=c, width=sw)
    return img.resize((size, size), Image.LANCZOS)


_snooze_tk_icons: dict[str, ImageTk.PhotoImage] = {}


def _init_snooze_icons():
    """Generate snooze/unsnooze button icons (normal + hover). Call after Tk root exists."""
    if _snooze_tk_icons:
        return
    # Snooze (muted) — normal and hover
    _snooze_tk_icons["normal"] = ImageTk.PhotoImage(
        _make_snooze_icon(bg_colour="#3D3530", fg_colour="#A8A29E"))
    _snooze_tk_icons["hover"] = ImageTk.PhotoImage(
        _make_snooze_icon(bg_colour="#4A3728", fg_colour="#FBBF24"))
    # Unsnooze (active/amber) — normal and hover
    _snooze_tk_icons["active"] = ImageTk.PhotoImage(
        _make_snooze_icon(bg_colour="#92400E", fg_colour="#FEF3C7"))
    _snooze_tk_icons["active_hover"] = ImageTk.PhotoImage(
        _make_snooze_icon(bg_colour="#78350F", fg_colour="#FFFFFF"))


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


_base_icon_cache: dict[int, Image.Image] = {}


def _make_icon_image(colour: str, size: int = 64) -> Image.Image:
    """Base icon with a coloured status dot in the bottom-right corner."""
    if size not in _base_icon_cache:
        _base_icon_cache[size] = _make_base_icon(size)
    img = _base_icon_cache[size].copy()
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
    """Generate app.ico with multiple sizes for crisp display at all scales.
    Skips regeneration if the file already exists."""
    if APP_ICO.exists():
        return
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
                 jira_base_url: str = "", sub_key: Optional[str] = None,
                 snooze_cb: Optional[callable] = None):
        self.wid    = wid
        self._sub_key = sub_key
        self._state = state
        self._jira_base_url = jira_base_url
        self._snooze_cb = snooze_cb
        self._snoozed = False
        bg = BG_ROW_ALT if alt else BG_ROW

        self.frame = tk.Frame(parent, bg=bg)
        self.frame.pack(fill=tk.X, padx=4, pady=(2, 0))

        # Left accent bar (coloured strip indicating status)
        self._accent = tk.Frame(self.frame, bg=COLOUR[state.status], width=3)
        self._accent.pack(side=tk.LEFT, fill=tk.Y)

        # Left column: status icon + snooze button stacked vertically
        self._left_col = tk.Frame(self.frame, bg=bg)
        self._left_col.pack(side=tk.LEFT, padx=(12, 10), pady=(8, 4))

        # Status icon (Lucide-style image)
        icon = _status_tk_icons.get(state.status, _status_tk_icons.get(ST_UNKNOWN))
        self._icon_lbl = tk.Label(self._left_col, image=icon, bg=bg)
        self._icon_lbl.image = icon  # prevent GC
        self._icon_lbl.pack()

        # Snooze button (Zzz icon) — shown only for failed rows
        self._snooze_btn = tk.Label(
            self._left_col, image=_snooze_tk_icons.get("normal"), bg=bg, cursor="hand2",
        )
        self._snooze_btn.image = _snooze_tk_icons.get("normal")
        self._snooze_btn.bind("<Button-1>", lambda _: self._toggle_snooze())
        self._snooze_btn.bind("<Enter>", self._snooze_hover_enter)
        self._snooze_btn.bind("<Leave>", self._snooze_hover_leave)
        _attach_tooltip(self._snooze_btn, "Snooze — dim this row and exclude from tray status")
        # (packed/hidden dynamically in _update_labels based on status)

        # Right side — polling rate (pack before centre so it reserves space)
        self._poll_lbl = tk.Label(
            self.frame, text="", font=(UI_FONT, 8),
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
            self._top_row, text=state.name, font=(UI_FONT, 9),
            bg=bg, fg=FG_TEXT, cursor="hand2", anchor="w",
        )
        self._name_lbl.pack(side=tk.LEFT)
        self._name_lbl.bind("<Button-1>", self._open_url)

        # Separator " / " between workflow name and PR info (hidden for non-PR)
        self._sep_lbl = tk.Label(
            self._top_row, text=" / ", font=(UI_FONT, 9),
            bg=bg, fg=FG_MUTED, anchor="w",
        )

        # PR number + branch short name (subtitle in PR mode, opens build run)
        self._branch_lbl = tk.Label(
            self._top_row, text="", font=(UI_FONT, 8),
            bg=bg, fg=FG_MUTED, cursor="hand2", anchor="w",
        )
        self._branch_lbl.bind("<Button-1>", self._open_url)

        # Line 2 (optional): badges row — prefix badge + DRAFT badge
        self._badge_row = tk.Frame(centre, bg=bg)
        # (only packed when badges are present)

        self._prefix_lbl = tk.Label(
            self._badge_row, text="", font=(UI_FONT, 7),
            bg="#3D3530", fg="#FBBF24", anchor="w", padx=3, pady=0,
        )

        self._draft_lbl = tk.Label(
            self._badge_row, text="DRAFT", font=(UI_FONT, 7, "bold"),
            bg="#92400E", fg="#FEF3C7", anchor="w", padx=4, pady=0,
        )

        self._jira_lbl = tk.Label(
            self._badge_row, text="", font=(UI_FONT, 7),
            bg="#302830", fg="#A78BFA", anchor="w", padx=3, pady=0,
            cursor="hand2",
        )
        self._jira_lbl.bind("<Button-1>", self._open_jira)

        # Review status badge (APPROVED / CHANGES REQUESTED / REVIEW PENDING)
        self._review_lbl = tk.Label(
            self._badge_row, text="", font=(UI_FONT, 7),
            anchor="w", padx=3, pady=0,
        )

        # Staleness badge (STALE 3d)
        self._stale_lbl = tk.Label(
            self._badge_row, text="", font=(UI_FONT, 7, "bold"),
            anchor="w", padx=3, pady=0,
        )

        # PR title (becomes the main title for PR-mode rows, opens PR page)
        self._pr_title_lbl = tk.Label(
            centre, text="", font=(UI_FONT, 9),
            bg=bg, fg=FG_TEXT, anchor="w", cursor="hand2",
        )
        self._pr_title_lbl.bind("<Button-1>", self._open_pr)

        # Line 3: status text
        self._info_lbl = tk.Label(
            centre, text="", font=(UI_FONT, 8),
            bg=bg, fg=FG_MUTED, anchor="w",
        )
        self._info_lbl.pack(fill=tk.X)

        # Snooze badge (shown in badge row when snoozed)
        self._snooze_lbl = tk.Label(
            self._badge_row, text="SNOOZED", font=(UI_FONT, 7, "bold"),
            bg="#3D3530", fg="#A8A29E", anchor="w", padx=4, pady=0,
        )

        self._bg = bg
        self._update_labels()

        # Right-click context menu
        self._ctx_menu = tk.Menu(self.frame, tearoff=0, bg=BG_ROW, fg=FG_TEXT,
                                 activebackground="#4A3728", activeforeground=FG_TEXT,
                                 font=(UI_FONT, 9))
        self._ctx_menu.add_command(label="Snooze", command=self._toggle_snooze)
        self.frame.bind("<Button-3>", self._show_ctx_menu)
        # Bind on all child widgets too so right-click works anywhere on the row
        for widget in self.frame.winfo_children():
            widget.bind("<Button-3>", self._show_ctx_menu)
            if isinstance(widget, tk.Frame):
                for child in widget.winfo_children():
                    child.bind("<Button-3>", self._show_ctx_menu)

    def _show_ctx_menu(self, event):
        label = "Unsnooze" if self._snoozed else "Snooze"
        self._ctx_menu.entryconfigure(0, label=label)
        self._ctx_menu.tk_popup(event.x_root, event.y_root)

    def _toggle_snooze(self):
        if self._snooze_cb:
            self._snooze_cb((self.wid, self._sub_key))

    def _snooze_hover_enter(self, _event=None):
        key = "active_hover" if self._snoozed else "hover"
        icon = _snooze_tk_icons.get(key)
        if icon:
            self._snooze_btn.config(image=icon)
            self._snooze_btn.image = icon

    def _snooze_hover_leave(self, _event=None):
        key = "active" if self._snoozed else "normal"
        icon = _snooze_tk_icons.get(key)
        if icon:
            self._snooze_btn.config(image=icon)
            self._snooze_btn.image = icon

    def set_snoozed(self, snoozed: bool):
        self._snoozed = snoozed
        if snoozed:
            # Dim accent bar and text
            self._accent.config(bg="#57534E")  # stone-600
            self._icon_lbl.config(state="disabled")
            self._info_lbl.config(fg="#78716C")  # stone-500
            self._name_lbl.config(fg="#78716C")
            self._poll_lbl.config(fg="#78716C")
            self._branch_lbl.config(fg="#78716C")
            self._pr_title_lbl.config(fg="#78716C")
        else:
            # Restore normal colours
            self._accent.config(bg=COLOUR.get(self._state.status, COLOUR[ST_UNKNOWN]))
            self._icon_lbl.config(state="normal")
            self._info_lbl.config(fg=FG_MUTED)
            self._name_lbl.config(fg=FG_TEXT)
            self._poll_lbl.config(fg=FG_MUTED)
            self._branch_lbl.config(fg=FG_MUTED)
            self._pr_title_lbl.config(fg=FG_TEXT)
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
        if not self._snoozed:
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
                text, bg_col, fg_col = _REVIEW_BADGE_CFG.get(
                    s.review_status, ("REVIEW PENDING", "#3D3530", "#FBBF24")
                )
                self._review_lbl.config(text=text, bg=bg_col, fg=fg_col)
                self._review_lbl.pack(side=tk.LEFT, padx=(0, 4))
                has_badges = True
            else:
                self._review_lbl.pack_forget()

            if s.staleness_level and s.pr_updated_at:
                bg_col, fg_col = _STALENESS_BADGE_CFG.get(s.staleness_level, ("#3D3520", "#EAB308"))
                age = _format_age(s.pr_updated_at)
                self._stale_lbl.config(text=f"STALE {age}" if age else "STALE", bg=bg_col, fg=fg_col)
                self._stale_lbl.pack(side=tk.LEFT, padx=(0, 4))
                has_badges = True
            else:
                self._stale_lbl.pack_forget()

            if self._snoozed:
                self._snooze_lbl.pack(side=tk.LEFT, padx=(0, 4))
                has_badges = True
            else:
                self._snooze_lbl.pack_forget()

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
            self._stale_lbl.pack_forget()
            self._pr_title_lbl.pack_forget()

            # For non-PR rows, show SNOOZED badge if needed
            if self._snoozed:
                self._snooze_lbl.pack(side=tk.LEFT, padx=(0, 4))
                self._badge_row.pack(fill=tk.X, pady=(2, 0), before=self._info_lbl)
            else:
                self._snooze_lbl.pack_forget()
                self._badge_row.pack_forget()

        # Show snooze button below status icon for failed/snoozed rows
        if self._snoozed:
            icon = _snooze_tk_icons.get("active")
            self._snooze_btn.config(image=icon)
            self._snooze_btn.image = icon
            self._snooze_btn.pack(pady=(4, 0))
        elif s.status == ST_FAILURE:
            icon = _snooze_tk_icons.get("normal")
            self._snooze_btn.config(image=icon)
            self._snooze_btn.image = icon
            self._snooze_btn.pack(pady=(4, 0))
        else:
            self._snooze_btn.pack_forget()


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
        if getattr(sys, "frozen", False):
            # Frozen .exe — just run the executable directly
            return f'"{sys.executable}"'
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
    RELEASES_API = "https://api.github.com/repos/summitnl/ActionsMonitor/releases/latest"

    # Populated by _check_release() for use in apply_update() and the dialog.
    _release_data: Optional[dict] = None

    @staticmethod
    def check() -> Optional[str]:
        """Returns a version string if an update is available, None otherwise.

        Frozen builds check GitHub Releases; source builds use git.
        """
        if getattr(sys, "frozen", False):
            return UpdateChecker._check_release()
        return UpdateChecker._check_git()

    @staticmethod
    def _check_git() -> Optional[str]:
        """Git-based check for source installs."""
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
    def _check_release() -> Optional[str]:
        """GitHub Releases check for frozen builds."""
        if BUILD_COMMIT == "dev":
            return None
        try:
            resp = requests.get(
                UpdateChecker.RELEASES_API,
                headers={"Accept": "application/vnd.github+json"},
                timeout=15,
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            commitish = data.get("target_commitish", "")
            # target_commitish may be a branch name (e.g. "main") or a SHA.
            # Only compare as SHA if it looks like one (hex, >= 7 chars).
            if re.fullmatch(r"[0-9a-f]{7,}", commitish):
                release_sha = commitish[:7]
            else:
                # Branch name — can't compare to BUILD_COMMIT, treat as new release
                release_sha = None
            if release_sha is None or release_sha != BUILD_COMMIT:
                UpdateChecker._release_data = data
                return data.get("tag_name", release_sha)
        except Exception:
            pass
        return None

    @staticmethod
    def apply_update() -> tuple[bool, str]:
        """Download/pull latest. Returns (success, message)."""
        if getattr(sys, "frozen", False):
            return UpdateChecker._apply_release_update()
        return UpdateChecker._apply_git_update()

    @staticmethod
    def _apply_git_update() -> tuple[bool, str]:
        """Pull latest and install deps (source installs)."""
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
    def _apply_release_update() -> tuple[bool, str]:
        """Download the latest release binary and replace the running executable."""
        try:
            data = UpdateChecker._release_data
            if not data:
                resp = requests.get(
                    UpdateChecker.RELEASES_API,
                    headers={"Accept": "application/vnd.github+json"},
                    timeout=15,
                )
                if resp.status_code != 200:
                    return False, f"Failed to fetch release (HTTP {resp.status_code})"
                data = resp.json()

            asset_name = "ActionsMonitor.exe" if IS_WINDOWS else "ActionsMonitor-linux"
            asset = next((a for a in data.get("assets", []) if a["name"] == asset_name), None)
            if not asset:
                return False, f"Asset '{asset_name}' not found in release"

            download_url = asset["browser_download_url"]
            current_exe = Path(sys.executable)
            tmp_path = current_exe.with_suffix(".update")

            with requests.get(download_url, stream=True, timeout=120) as dl:
                dl.raise_for_status()
                with open(tmp_path, "wb") as f:
                    for chunk in dl.iter_content(chunk_size=65536):
                        f.write(chunk)

            if IS_WINDOWS:
                old_path = current_exe.with_suffix(".old")
                try:
                    old_path.unlink(missing_ok=True)
                except OSError:
                    pass
                current_exe.rename(old_path)
                tmp_path.rename(current_exe)
            else:
                tmp_path.chmod(tmp_path.stat().st_mode | stat.S_IEXEC)
                tmp_path.rename(current_exe)

            return True, "Update complete"
        except Exception as exc:
            return False, str(exc)

    @staticmethod
    def restart_app():
        """Re-launch the app and exit the current process."""
        if getattr(sys, "frozen", False) and IS_WINDOWS:
            subprocess.Popen([sys.executable] + sys.argv[1:])
            sys.exit(0)
        else:
            os.execv(sys.executable, [sys.executable] + sys.argv)


def _show_update_dialog(root: tk.Tk, commit_hash: str):
    """Show a modal dark-themed update dialog."""
    dlg = tk.Toplevel(root)
    dlg.title(f"{APP_NAME} — Update Available")
    if APP_ICO.exists() and IS_WINDOWS:
        dlg.iconbitmap(str(APP_ICO))
    dlg.configure(bg=BG_DARK)
    dlg.resizable(False, False)

    pad = {"padx": 20, "pady": 6}

    tk.Label(
        dlg, text="A new version of Actions Monitor is available.",
        font=(UI_FONT, 11, "bold"), bg=BG_DARK, fg=FG_TEXT,
    ).pack(**pad, pady=(16, 6))

    tk.Label(
        dlg, text=f"New version: {commit_hash}",
        font=(UI_FONT, 9), bg=BG_DARK, fg=FG_MUTED,
    ).pack(**pad, pady=(0, 4))

    if getattr(sys, "frozen", False):
        link_text, link_url = "View release on GitHub", f"{UpdateChecker.REPO_URL}/releases/tag/{commit_hash}"
    else:
        link_text, link_url = "View README on GitHub", f"{UpdateChecker.REPO_URL}#readme"
    link = tk.Label(
        dlg, text=link_text,
        font=(UI_FONT, 9, "underline"), bg=BG_DARK, fg=FG_LINK,
        cursor="hand2",
    )
    link.pack(**pad, pady=(0, 10))
    link.bind("<Button-1>", lambda _: webbrowser.open(link_url))

    status_lbl = tk.Label(dlg, text="", font=(UI_FONT, 9), bg=BG_DARK, fg=FG_MUTED)
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
        btn_frame, text="Update", font=(UI_FONT, 10),
        bg=ACCENT, fg=FG_TEXT, activebackground=BG_ROW, activeforeground=FG_TEXT,
        relief=tk.FLAT, padx=16, pady=4, cursor="hand2", command=do_update,
    )
    update_btn.pack(side=tk.LEFT, padx=(0, 8))

    skip_btn = tk.Button(
        btn_frame, text="Skip", font=(UI_FONT, 10),
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
# Tooltip helper
# ---------------------------------------------------------------------------
def _attach_tooltip(widget: tk.Widget, text: str, delay: int = 400):
    """Show a small tooltip after hovering for *delay* ms."""
    tip: tk.Toplevel | None = None
    after_id: str | None = None

    def _show(e):
        nonlocal tip, after_id
        def _create():
            nonlocal tip
            tip = tk.Toplevel(widget)
            tip.wm_overrideredirect(True)
            lbl = tk.Label(tip, text=text, bg="#292524", fg=FG_TEXT,
                           font=(UI_FONT, 8), padx=6, pady=3,
                           relief="solid", borderwidth=1, highlightthickness=0)
            lbl.pack()
            tip.update_idletasks()
            # Position below the widget, clamped to screen
            wx = widget.winfo_rootx()
            wy = widget.winfo_rooty() + widget.winfo_height() + 4
            tw = tip.winfo_reqwidth()
            sw = widget.winfo_screenwidth()
            if wx + tw > sw:
                wx = sw - tw - 4
            tip.wm_geometry(f"+{wx}+{wy}")
        after_id = widget.after(delay, _create)

    def _hide(_e=None):
        nonlocal tip, after_id
        if after_id:
            widget.after_cancel(after_id)
            after_id = None
        if tip:
            tip.destroy()
            tip = None

    widget.bind("<Enter>", _show)
    widget.bind("<Leave>", _hide)


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
        self._snoozed: set[tuple[int, Optional[str]]] = set()
        self._tray: Optional[TrayManager] = None
        self._sections: list[tk.Frame] = []           # section header+container frames
        self._wid_container: dict[int, tk.Frame] = {} # wid → section content frame
        self._section_content: dict[str, tk.Frame] = {}    # title → content frame
        self._section_indicators: dict[str, tk.Label] = {} # title → indicator label
        self._collapsed: dict[str, bool] = {}              # title → collapsed flag
        self._section_sort: dict[str, Optional[str]] = {}  # title → sort mode or None
        self._sort_labels: dict[str, dict[str, tk.Label]] = {}  # title → {key: label}

        self._root = tk.Tk()
        self._root.title(APP_NAME)
        _generate_app_ico()
        if APP_ICO.exists() and IS_WINDOWS:
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
        self._restore_all_state()

        _init_status_icons()
        _init_snooze_icons()
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

        # Summit logo
        logo_data = base64.b64decode(_SUMMIT_LOGO_B64)
        logo_img = Image.open(io.BytesIO(logo_data))
        # Scale to 28px height for the header
        scale = 28 / logo_img.height
        logo_img = logo_img.resize(
            (round(logo_img.width * scale), 28), Image.LANCZOS,
        )
        self._summit_logo = ImageTk.PhotoImage(logo_img)
        logo_lbl = tk.Label(
            header, image=self._summit_logo, bg=BG_DARK, cursor="hand2",
        )
        logo_lbl.pack(side=tk.LEFT, padx=(14, 0), pady=9)
        logo_lbl.bind("<Button-1>", lambda _: webbrowser.open("https://summit.nl"))
        _attach_tooltip(logo_lbl, "summit.nl")

        tk.Label(
            header, text=APP_NAME, font=(UI_FONT, 12),
            bg=BG_DARK, fg=FG_TEXT,
        ).pack(side=tk.LEFT, padx=(10, 16), pady=10)

        self._refresh_icon = ImageTk.PhotoImage(_make_refresh_icon(24))
        refresh_btn = tk.Label(
            header, image=self._refresh_icon,
            bg=BG_DARK, cursor="hand2", padx=8, pady=4,
        )
        refresh_btn.pack(side=tk.RIGHT, padx=(0, 14), pady=8)
        refresh_btn.bind("<Button-1>", lambda _: self._refresh_all())
        _attach_tooltip(refresh_btn, "Refresh all workflows")

        # Thin warm separator line under header
        tk.Frame(self._root, bg="#44403C", height=1).pack(fill=tk.X)

        # Column headers
        hdr = tk.Frame(self._root, bg=BG_DARK)
        hdr.pack(fill=tk.X, padx=14, pady=(6, 2))
        tk.Label(hdr, text="STATUS / WORKFLOW", font=(UI_FONT, 7, "bold"),
                 bg=BG_DARK, fg=FG_MUTED, anchor="w").pack(side=tk.LEFT, expand=True, fill=tk.X)
        tk.Label(hdr, text="POLL", font=(UI_FONT, 7, "bold"),
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

        def _update_scroll_region():
            req_h = self._list_frame.winfo_reqheight()
            vis_h = canvas.winfo_height()
            canvas.itemconfig(self._canvas_window, width=canvas.winfo_width(),
                              height=max(req_h, vis_h))
            canvas.configure(scrollregion=(0, 0, self._list_frame.winfo_reqwidth(),
                                           max(req_h, vis_h)))

        def _on_canvas_configure(e):
            canvas.after_idle(_update_scroll_region)
        canvas.bind("<Configure>", _on_canvas_configure)

        def _on_frame_configure(_e):
            canvas.after_idle(_update_scroll_region)
        self._list_frame.bind("<Configure>", _on_frame_configure)

        def _on_mousewheel(e):
            canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        def _on_mousewheel_linux(e, direction):
            canvas.yview_scroll(direction, "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)
        if IS_LINUX:
            canvas.bind_all("<Button-4>", lambda e: _on_mousewheel_linux(e, -3))
            canvas.bind_all("<Button-5>", lambda e: _on_mousewheel_linux(e, 3))

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
            font=(UI_FONT, 8), bg=ACCENT, fg=FG_MUTED,
        ).pack(side=tk.LEFT)

        open_btn = tk.Label(
            footer_row1, text="Open config ↗", font=(UI_FONT, 8, "bold"),
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
                font=(UI_FONT, 8),
                bg=ACCENT, fg=FG_MUTED,
                activebackground=ACCENT, activeforeground=FG_TEXT,
                selectcolor=BG_DARK,
                relief=tk.FLAT, bd=0,
            )
            startup_cb.pack(side=tk.LEFT)
        else:
            tk.Label(
                footer_row2, text="", bg=ACCENT, font=(UI_FONT, 8),
            ).pack(side=tk.LEFT)

        self._aot_var = tk.BooleanVar(value=self._root.attributes('-topmost'))
        aot_cb = tk.Checkbutton(
            footer_row2,
            text="Always on top",
            variable=self._aot_var,
            command=self._toggle_always_on_top,
            font=(UI_FONT, 8),
            bg=ACCENT, fg=FG_MUTED,
            activebackground=ACCENT, activeforeground=FG_TEXT,
            selectcolor=BG_DARK,
            relief=tk.FLAT, bd=0,
        )
        aot_cb.pack(side=tk.LEFT, padx=(12, 0))

    # ------------------------------------------------------------------
    # Startup toggle
    # ------------------------------------------------------------------
    def _toggle_startup(self):
        if self._startup_var.get():
            StartupManager.enable()
        else:
            StartupManager.disable()

    # ------------------------------------------------------------------
    # Always on top
    # ------------------------------------------------------------------
    def _toggle_always_on_top(self):
        on_top = self._aot_var.get()
        self._root.attributes('-topmost', on_top)
        try:
            state = self._load_state()
            state["always_on_top"] = on_top
            self._write_state(state)
        except Exception:
            pass

    def _restore_all_state(self):
        """Restore window geometry, collapse state, and always-on-top from a single state.json read."""
        try:
            state = self._load_state()
        except Exception:
            return
        # Collapse state
        for title in state.get("collapsed_sections", []):
            self._collapsed[title] = True
        # Always on top
        on_top = state.get("always_on_top", False)
        self._root.attributes('-topmost', on_top)
        # Window geometry
        win = state.get("window")
        if not win:
            return
        try:
            x = int(win["x"])
            y = int(win["y"])
            w = max(int(win["width"]), 400)
            h = max(int(win["height"]), 200)
            areas = _get_monitor_work_areas() if IS_WINDOWS else []
            if areas and not _rect_overlaps(x, y, w, h, areas):
                self._root.geometry(f"{w}x{h}")
                return
            if not areas:
                sw = self._root.winfo_screenwidth()
                sh = self._root.winfo_screenheight()
                if x + w < 100 or x > sw - 100 or y + h < 50 or y > sh - 50:
                    self._root.geometry(f"{w}x{h}")
                    return
            self._root.geometry(f"{w}x{h}+{x}+{y}")
        except Exception as exc:
            print(f"[State] Restore error: {exc}")

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
                             font=(UI_FONT, 9, "bold"),
                             bg=BG_DARK, fg=FG_LINK, anchor="w")
        indicator.pack(side=tk.LEFT, padx=(0, 4))
        self._section_indicators[title] = indicator

        title_lbl = tk.Label(hdr, text=title, font=(UI_FONT, 9, "bold"),
                             bg=BG_DARK, fg=FG_LINK, anchor="w")
        title_lbl.pack(side=tk.LEFT)

        # Horizontal rule — warm tone
        sep = tk.Frame(hdr, bg="#44403C", height=1)
        sep.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(10, 0), pady=1)

        content = tk.Frame(section, bg=BG_DARK)
        if not is_collapsed:
            content.pack(fill=tk.X)
        self._section_content[title] = content

        # Sort bar — inside content, above the rows
        sort_bar = tk.Frame(content, bg=BG_ROW)
        sort_bar.pack(fill=tk.X, padx=4, pady=(2, 0))

        tk.Label(sort_bar, text="SORT:", font=(UI_FONT, 8, "bold"),
                 bg=BG_ROW, fg=FG_TEXT, padx=6, pady=3).pack(side=tk.LEFT)

        labels: dict[str, tk.Label] = {}
        for sk in ("status", "updated", "created"):
            lbl = tk.Label(sort_bar, text=f"{sk.capitalize()} ·", font=(UI_FONT, 8),
                           bg=BG_ROW, fg=FG_MUTED, cursor="hand2", padx=6, pady=3)
            lbl.pack(side=tk.LEFT)
            lbl.bind("<Button-1>", lambda _e, t=title, k=sk: self._cycle_sort(t, k))
            labels[sk] = lbl
        self._sort_labels[title] = labels

        # Clear button
        clear_lbl = tk.Label(sort_bar, text="✕", font=(UI_FONT, 8),
                             bg=BG_ROW, fg=FG_MUTED, cursor="hand2", padx=8, pady=3)
        clear_lbl.pack(side=tk.RIGHT)
        clear_lbl.bind("<Button-1>", lambda _e, t=title: self._clear_sort(t))

        # Bind click on all header widgets (collapse/expand)
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
            state = self._load_state()
            self._persist_collapsed(state)
            self._write_state(state)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Section sorting
    # ------------------------------------------------------------------
    def _cycle_sort(self, title: str, sort_key: str):
        """Cycle sort for a section+key: None → asc → desc → None. Only one sort active globally."""
        current = self._section_sort.get(title)
        prefix = f"{sort_key}_"

        # Determine next state for this key
        if current == f"{prefix}asc":
            new_sort = f"{prefix}desc"
        elif current == f"{prefix}desc":
            new_sort = None
        elif current is None or not current.startswith(prefix):
            new_sort = f"{prefix}asc"
        else:
            new_sort = None

        # Clear all other sorts globally (only one active at a time)
        prev_sorted_titles = [t for t, s in self._section_sort.items() if s is not None and t != title]
        for t in self._section_sort:
            self._section_sort[t] = None
        self._section_sort[title] = new_sort

        self._update_sort_labels()

        # Re-sort affected sections
        self._sort_section(title)
        for t in prev_sorted_titles:
            self._sort_section(t)

        self._save_sort_state()

    def _sort_section(self, title: str):
        """Re-order rows within a section based on the active sort."""
        content = self._section_content.get(title)
        if not content:
            return
        sort_mode = self._section_sort.get(title)

        # Collect rows belonging to this section
        section_rows: list[tuple[tuple[int, Optional[str]], WorkflowRow]] = []
        for key, row in self._rows.items():
            wid = key[0]
            if self._wid_container.get(wid) is content:
                section_rows.append((key, row))

        if not section_rows:
            return

        # Sort
        if sort_mode == "status_asc":
            section_rows.sort(key=lambda kr: _STATUS_PRIORITY.get(
                self._states.get(kr[0], WorkflowState(name="", url="", branch=None)).status, 0), reverse=True)
        elif sort_mode == "status_desc":
            section_rows.sort(key=lambda kr: _STATUS_PRIORITY.get(
                self._states.get(kr[0], WorkflowState(name="", url="", branch=None)).status, 0))
        elif sort_mode in ("updated_asc", "updated_desc"):
            def _updated_key(kr):
                s = self._states.get(kr[0])
                ts = (s.run_updated_at or s.started_at or "") if s else ""
                return ts
            section_rows.sort(key=_updated_key, reverse=(sort_mode == "updated_asc"))
        elif sort_mode in ("created_asc", "created_desc"):
            def _created_key(kr):
                s = self._states.get(kr[0])
                return (s.started_at or "") if s else ""
            section_rows.sort(key=_created_key, reverse=(sort_mode == "created_asc"))
        else:
            # Default: insertion order (sort by key tuple)
            section_rows.sort(key=lambda kr: (kr[0][0], kr[0][1] or ""))

        # Re-pack in new order
        for _key, row in section_rows:
            row.frame.pack_forget()
        for i, (_key, row) in enumerate(section_rows):
            row.frame.pack(fill=tk.X, padx=4, pady=(2, 0))
            bg = BG_ROW_ALT if i % 2 == 1 else BG_ROW
            row._bg = bg
            self._set_row_bg(row, bg)

    def _update_sort_labels(self):
        """Refresh all sort label text and colors to reflect current state."""
        _ARROWS = {"asc": "▲", "desc": "▼"}
        for title, labels in self._sort_labels.items():
            current = self._section_sort.get(title)
            for sk, lbl in labels.items():
                if current and current.startswith(f"{sk}_"):
                    direction = current.split("_", 1)[1]
                    lbl.config(text=f"{sk.capitalize()} {_ARROWS[direction]}", fg=FG_LINK)
                else:
                    lbl.config(text=f"{sk.capitalize()} ·", fg=FG_MUTED)

    def _clear_sort(self, title: str):
        """Clear sorting for a section and restore default order."""
        if not self._section_sort.get(title):
            return
        self._section_sort[title] = None
        self._update_sort_labels()
        self._sort_section(title)
        self._save_sort_state()

    def _save_sort_state(self):
        """Persist section sort preferences to state.json."""
        try:
            state = self._load_state()
            sorts = {t: s for t, s in self._section_sort.items() if s is not None}
            if sorts:
                state["section_sort"] = sorts
            else:
                state.pop("section_sort", None)
            self._write_state(state)
        except Exception:
            pass

    def _restore_sort_state(self):
        """Restore section sort preferences from state.json."""
        state = self._load_state()
        for title, sort_mode in state.get("section_sort", {}).items():
            self._section_sort[title] = sort_mode
        self._update_sort_labels()

    def _resort_section_for_wid(self, wid: int):
        """Re-sort the section containing the given workflow id, if it has an active sort."""
        container = self._wid_container.get(wid)
        if not container:
            return
        for title, content in self._section_content.items():
            if content is container and self._section_sort.get(title):
                self._sort_section(title)
                break

    def _destroy_sections(self):
        for sec in self._sections:
            sec.destroy()
        self._sections.clear()
        self._wid_container.clear()
        self._section_content.clear()
        self._section_indicators.clear()
        self._sort_labels.clear()

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

        self._restore_sort_state()

        for wid, entry in enumerate(workflows):
            self._add_poller(wid, entry, cfg)

    def _add_poller(self, wid: int, entry: dict, cfg: Optional[dict] = None):
        if wid in self._pollers:
            return
        if cfg is None:
            cfg = self._config_mgr.get()
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
            jira_url = cfg.get("jira_base_url", "")
            row = WorkflowRow(container, wid, state, alt, jira_base_url=jira_url,
                              sub_key=None, snooze_cb=self._toggle_snooze)
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
        if IS_WINDOWS:
            self._check_focus_signal()
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
            self._unsnooze(key)
            self._restripe_rows()
            self._resort_section_for_wid(event.workflow_id)
        else:
            # Auto-clear snooze when a new run starts
            prev = self._states.get(key)
            if (key in self._snoozed and prev is not None
                    and event.new_state.run_id is not None
                    and event.new_state.run_id != prev.run_id):
                self._unsnooze(key)
                row = self._rows.get(key)
                if row:
                    row.set_snoozed(False)

            self._states[key] = event.new_state
            row = self._rows.get(key)
            if row:
                row.update(event.new_state, poll_rate, jira_base_url=jira_url)
            elif event.sub_key is not None:
                # Dynamically create a new PR row inside its section container
                container = self._wid_container.get(event.workflow_id, self._list_frame)
                alt = len(self._rows) % 2 == 1
                new_row = WorkflowRow(container, event.workflow_id, event.new_state, alt,
                                      jira_base_url=jira_url, sub_key=event.sub_key,
                                      snooze_cb=self._toggle_snooze)
                new_row.update(event.new_state, poll_rate, jira_base_url=jira_url)
                self._rows[key] = new_row
            self._resort_section_for_wid(event.workflow_id)

        if self._tray:
            unsnoozed = [s for k, s in self._states.items() if k not in self._snoozed]
            self._tray.update(unsnoozed)

    def _toggle_snooze(self, key: tuple[int, Optional[str]]):
        """Toggle snooze state for a row."""
        if key in self._snoozed:
            self._unsnooze(key)
        else:
            self._snoozed.add(key)
            with _snoozed_lock:
                _snoozed_keys.add(key)
        row = self._rows.get(key)
        if row:
            row.set_snoozed(key in self._snoozed)
        # Refresh tray icon with snoozed rows excluded
        if self._tray:
            unsnoozed = [s for k, s in self._states.items() if k not in self._snoozed]
            self._tray.update(unsnoozed)

    def _unsnooze(self, key: tuple[int, Optional[str]]):
        """Remove snooze state for a key."""
        self._snoozed.discard(key)
        with _snoozed_lock:
            _snoozed_keys.discard(key)

    def _restripe_rows(self):
        """Recalculate alternating row backgrounds per-section after a row is removed."""
        # Group rows by their section container
        section_rows: dict[int, list[WorkflowRow]] = {}
        for (wid, _sub), row in self._rows.items():
            cid = id(self._wid_container.get(wid, self._list_frame))
            section_rows.setdefault(cid, []).append(row)
        for rows in section_rows.values():
            for i, row in enumerate(rows):
                bg = BG_ROW_ALT if i % 2 == 1 else BG_ROW
                row._bg = bg
                self._set_row_bg(row, bg)

    # ------------------------------------------------------------------
    # Config hot-reload
    # ------------------------------------------------------------------
    def _watch_config(self):
        changed = self._config_mgr.load()
        if changed:
            self._reload_pollers()
        self._root.after(5000, self._watch_config)


    def _reload_pollers(self):
        global _cached_github_username
        self._stop_all_pollers()
        self._rows.clear()
        self._states.clear()
        self._snoozed.clear()
        with _snoozed_lock:
            _snoozed_keys.clear()
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
    @staticmethod
    def _load_state() -> dict:
        """Load state.json, returning an empty dict on any error."""
        if STATE_FILE.exists():
            with open(STATE_FILE, encoding="utf-8") as fh:
                return json.load(fh)
        return {}

    @staticmethod
    def _write_state(state: dict):
        """Write state dict to state.json."""
        with open(STATE_FILE, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2)

    def _persist_collapsed(self, state: dict):
        """Update the collapsed_sections key in a state dict."""
        collapsed = [t for t, c in self._collapsed.items() if c]
        if collapsed:
            state["collapsed_sections"] = collapsed
        else:
            state.pop("collapsed_sections", None)

    def _save_window_state(self):
        """Save current window geometry to state.json."""
        try:
            state = self._load_state()
            state["window"] = {
                "x": self._root.winfo_x(),
                "y": self._root.winfo_y(),
                "width": self._root.winfo_width(),
                "height": self._root.winfo_height(),
            }
            self._persist_collapsed(state)
            # Persist sort state
            sorts = {t: s for t, s in self._section_sort.items() if s is not None}
            if sorts:
                state["section_sort"] = sorts
            else:
                state.pop("section_sort", None)
            self._write_state(state)
        except Exception as exc:
            print(f"[State] Save error: {exc}")

    def _hide_window(self):
        if self._tray:
            self._root.withdraw()
        else:
            self._root.iconify()

    def _show_window(self):
        self._root.deiconify()
        self._root.lift()
        self._root.focus_force()

    def _check_focus_signal(self):
        if not _FOCUS_SIGNAL.exists():
            return
        try:
            _FOCUS_SIGNAL.unlink()
        except OSError:
            return
        self._show_window()
        recently = NOTIF.drain_recently_notified()
        for key in recently:
            row = self._rows.get(key)
            if row:
                self._blink_row(row)

    _BLINK_COLOR = "#4A3728"
    _BLINK_STEPS = 6       # 3 on/off cycles
    _BLINK_MS    = 150

    def _blink_row(self, row, remaining: int = _BLINK_STEPS):
        if remaining <= 0:
            self._set_row_bg(row, row._bg)
            return
        color = self._BLINK_COLOR if remaining % 2 == 0 else row._bg
        self._set_row_bg(row, color)
        self._root.after(self._BLINK_MS, self._blink_row, row, remaining - 1)

    @staticmethod
    def _set_row_bg(row, color: str):
        row.frame.config(bg=color)
        for widget in row.frame.winfo_children():
            if widget is row._accent:
                continue
            try:
                widget.config(bg=color)
            except tk.TclError:
                pass
            if isinstance(widget, tk.Frame):
                for child in widget.winfo_children():
                    try:
                        child.config(bg=color)
                    except tk.TclError:
                        pass

    def _on_unmap(self, event):
        if event.widget is self._root and self._tray:
            self._root.withdraw()

    def _quit(self):
        self._save_window_state()
        self._stop_all_pollers()
        if self._tray:
            self._tray.stop()
        if IS_WINDOWS:
            for f in (_FOCUS_SIGNAL, _FOCUS_VBS):
                try:
                    f.unlink(missing_ok=True)
                except OSError:
                    pass
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
    # Clean up leftover files from a previous binary update
    if getattr(sys, "frozen", False):
        for suffix in (".old", ".update"):
            try:
                Path(sys.executable).with_suffix(suffix).unlink(missing_ok=True)
            except OSError:
                pass

    if IS_WINDOWS:
        _ensure_focus_vbs()

    # Warn about missing Linux system libraries (non-blocking — user can dismiss)
    if IS_LINUX and _LINUX_MISSING:
        _warn_root = tk.Tk()
        _warn_root.withdraw()
        import tkinter.messagebox as _mb
        _mb.showwarning(
            "Actions Monitor — Missing System Libraries",
            "The following system packages are missing or could not be loaded:\n\n"
            + "\n".join(f"  • {p}" for p in _LINUX_MISSING)
            + "\n\nThe app will still start, but the tray icon and/or notification "
            "sounds may not work.\n\n"
            "Install with:\n"
            "  sudo apt-get install " + " ".join(
                p for p in _LINUX_MISSING if not p.startswith("pulseaudio")
                and not p.startswith("alsa")
            ).strip()
            + ("\n  sudo apt-get install pulseaudio-utils  # or alsa-utils"
               if any("paplay" in p or "aplay" in p for p in _LINUX_MISSING) else ""),
        )
        _warn_root.destroy()

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
    try:
        tray = TrayManager(win.show_callback, win.quit_callback)
        win.set_tray(tray)
        tray.start()
        # Update tray icon immediately with initial (unknown) states
        tray.update(list(win._states.values()))
    except Exception as exc:
        print(f"[Tray] Failed to start tray icon: {exc}")
        print("[Tray] App will run without a system tray icon.")

    win.run()


if __name__ == "__main__":
    main()
