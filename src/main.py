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
from urllib.parse import urlparse, parse_qs, unquote, quote
import stat
import base64
import functools
import hashlib
import io
import tempfile

from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QLabel,
    QVBoxLayout, QHBoxLayout, QFrame, QScrollArea, QCheckBox, QMenu,
    QDialog, QSystemTrayIcon, QMessageBox, QPushButton, QSizePolicy,
    QGraphicsOpacityEffect, QProgressBar)
from PySide6.QtCore import Qt, QTimer, QPoint, QSize, QEvent, Signal
from PySide6.QtGui import QPixmap, QImage, QIcon, QCursor, QFont, QColor, QMouseEvent

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
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    _missing.append("Pillow")

if _missing:
    _app = QApplication(sys.argv)
    QMessageBox.critical(
        None,
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
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("WizX20.ActionsMonitor")

# Linux system dependency check — warn about missing sound tools
_LINUX_MISSING: list[str] = []
if IS_LINUX:
    if not shutil.which("paplay") and not shutil.which("aplay"):
        _LINUX_MISSING.append("pulseaudio-utils (paplay) or alsa-utils (aplay)")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
APP_NAME    = "Actions Monitor"

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

# WizX20 logo (docs/wizx20.png resized to 56px height, base64-encoded to avoid bundling issues)
_WIZX20_LOGO_B64 = (
    "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"
)

CONFIG_FILE    = _APP_DIR / "config.yaml"
STATE_FILE     = _APP_DIR / "state.json"
APP_ICO        = _APP_DIR / "app.ico"
_CHECK_PNG     = _APP_DIR / "_check.png"
_CHECK_PNG_URL = _CHECK_PNG.as_posix()  # QSS requires forward slashes on Windows
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


def _is_snoozed(wid: int, sub_key: Optional[str]) -> bool:
    """Thread-safe check whether a (wid, sub_key) row is currently snoozed."""
    with _snoozed_lock:
        return (wid, sub_key) in _snoozed_keys

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
    "bot_pattern": r"\[bot\]$",
    "notifications": {
        "batch_window": 1,
        "max_notification_age": "1h",
        "duration": "short",
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


def _build_workflow_url(owner: str, repo: str, wf_file: str, branch: Optional[str] = None) -> str:
    """Construct a GitHub workflow overview URL, optionally filtered by branch."""
    if not (owner and repo and wf_file):
        return ""
    base = f"https://github.com/{owner}/{repo}/actions/workflows/{wf_file}"
    if branch:
        base += f"?query=branch%3A{quote(branch, safe='')}"
    return base


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


def _github_api_get(url: str, token: str, session: Optional[requests.Session] = None,
                    params: Optional[dict] = None, timeout: int = 15):
    """GET with ETag conditional-request cache + rate-limit cooldown gate.

    - Sends `If-None-Match` when a prior ETag is cached; on 304 returns the
      cached JSON (these don't count against GitHub's primary rate limit).
    - On 429 or secondary 403 (rate-limit messages), or when X-RateLimit-Remaining
      hits 0, advances a module-level cooldown so all pollers throttle together.
    - While in cooldown, raises `RateLimited` without hitting the network.
    """
    # Cooldown short-circuit — skip the call entirely.
    remaining, reason = _cooldown_remaining()
    if remaining > 0:
        raise RateLimited(remaining, reason or "cooldown")

    cache_key = (url, _params_key(params))
    with _etag_lock:
        cached = _etag_cache.get(cache_key)

    headers = _gh_headers(token)
    if cached:
        headers["If-None-Match"] = cached[0]

    _get = (session or requests).get
    resp = _get(url, params=params, headers=headers, timeout=timeout)
    status = resp.status_code

    # 304 Not Modified — free, return cached payload.
    if status == 304:
        if cached:
            return cached[1]
        # Server sent 304 but our cache is gone (race/protocol-violation) —
        # retry without If-None-Match so we get a real body back.
        headers.pop("If-None-Match", None)
        resp = _get(url, params=params, headers=headers, timeout=timeout)
        status = resp.status_code

    # 429 or secondary-limit 403: trip cooldown and raise.
    if status == 429 or (
        status == 403
        and "rate limit" in (resp.text or "").lower()
    ):
        wait = _parse_retry_after(resp)
        _set_cooldown(wait, f"HTTP {status}")
        raise RateLimited(wait, f"HTTP {status}")

    # 401 Unauthorized — token revoked/rotated. Invalidate the cached username
    # so the next poll re-resolves against the current token instead of loop-
    # ing with a stale login in actor= params.
    if status == 401:
        global _cached_github_username
        with _github_username_lock:
            _cached_github_username = None

    resp.raise_for_status()
    data = resp.json()

    # Primary limit exhausted — set cooldown until reset even though this call succeeded.
    remaining_hdr = resp.headers.get("X-RateLimit-Remaining")
    if remaining_hdr is not None:
        try:
            if int(remaining_hdr) == 0:
                reset_hdr = resp.headers.get("X-RateLimit-Reset")
                if reset_hdr:
                    wait = max(0.0, int(reset_hdr) - time.time())
                    _set_cooldown(wait, "primary limit exhausted")
        except ValueError:
            pass

    # Cache ETag + parsed body so the next identical request can 304.
    etag = resp.headers.get("ETag")
    if etag:
        with _etag_lock:
            _etag_cache[cache_key] = (etag, data)
            _prune_cache(_etag_cache, _ETAG_CACHE_MAX)
    return data


_DEFAULT_BOT_PATTERN = r"\[bot\]$"


@functools.lru_cache(maxsize=8)
def _compile_bot_regex(pattern: str) -> re.Pattern:
    """Compile bot-detection regex; silently fall back to default on bad input."""
    try:
        return re.compile(pattern or _DEFAULT_BOT_PATTERN)
    except re.error:
        return re.compile(_DEFAULT_BOT_PATTERN)


def _aggregate_review_status(reviews: list[dict],
                             bot_regex: Optional[re.Pattern] = None) -> tuple[str, bool]:
    """Collapse a PR reviews list to (status, by_bot).

    status ∈ 'approved' | 'changes_requested' | 'commented' | 'pending'.
    by_bot is True iff every reviewer whose latest state equals the winning state
    matches bot_regex. Human wins on mixed reviewers. Always False for
    commented/pending.
    """
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
        return ("commented" if has_comments else "pending", False)
    winning = "CHANGES_REQUESTED" if "CHANGES_REQUESTED" in latest.values() else "APPROVED"
    status = "changes_requested" if winning == "CHANGES_REQUESTED" else "approved"
    if bot_regex is None:
        return (status, False)
    winners = [u for u, st in latest.items() if st == winning]
    by_bot = bool(winners) and all(bot_regex.search(u) for u in winners)
    return (status, by_bot)


def _cached_review_fetch(url: str, token: str, session: Optional[requests.Session],
                         cache: dict, key, ttl: float,
                         bot_regex: Optional[re.Pattern] = None
                         ) -> tuple[Optional[str], bool]:
    """Fetch+aggregate PR review status with per-key TTL cache. Returns stale value on API error."""
    cached = cache.get(key)
    if cached is not None:
        value, fetch_time = cached
        if time.monotonic() - fetch_time < ttl:
            return value
    try:
        reviews = _github_api_get(url, token, session)
        result = _aggregate_review_status(reviews, bot_regex)
        cache[key] = (result, time.monotonic())
        _prune_cache(cache, _REVIEW_CACHE_MAX)
        return result
    except Exception:
        return cached[0] if cached else (None, False)


# GraphQL query — counts unresolved review threads for a single PR.
# REST doesn't expose `isResolved`, so GraphQL is required here.
_UNRESOLVED_THREADS_QUERY = """
query($owner:String!,$repo:String!,$num:Int!){
  repository(owner:$owner,name:$repo){
    pullRequest(number:$num){
      reviewThreads(first:100){nodes{isResolved}}
    }
  }
}
"""


def _cached_unresolved_fetch(owner: str, repo: str, pr_number: int, token: str,
                             session: Optional[requests.Session],
                             cache: dict, key, ttl: float) -> int:
    """Fetch count of unresolved review threads for a PR with per-key TTL cache.
    Returns stale value on API error, 0 when no prior value exists."""
    cached = cache.get(key)
    if cached is not None:
        count, fetch_time = cached
        if time.monotonic() - fetch_time < ttl:
            return count
    try:
        data = _github_graphql_post(
            _UNRESOLVED_THREADS_QUERY,
            {"owner": owner, "repo": repo, "num": pr_number},
            token, session,
        )
        pr = (data.get("repository") or {}).get("pullRequest") or {}
        nodes = ((pr.get("reviewThreads") or {}).get("nodes")) or []
        count = sum(1 for n in nodes if not n.get("isResolved"))
        cache[key] = (count, time.monotonic())
        _prune_cache(cache, _REVIEW_CACHE_MAX)
        return count
    except Exception:
        return cached[0] if cached else 0


# Cache caps — prevent unbounded growth over long sessions
_PR_CACHE_MAX = 200
_REVIEW_CACHE_MAX = 200
_ETAG_CACHE_MAX = 300


def _prune_cache(cache: dict, max_size: int):
    """Drop oldest entries (dict insertion order) until cache size <= max_size."""
    excess = len(cache) - max_size
    if excess <= 0:
        return
    for k in list(cache.keys())[:excess]:
        cache.pop(k, None)


# ETag / conditional-request cache — 304 responses don't count against
# GitHub's primary rate limit, so every hit here is a free poll.
# Keyed by (url, sorted-params-tuple) → (etag, parsed_json).
_etag_cache: dict = {}
_etag_lock = threading.Lock()

# Rate-limit cooldown gate. When GitHub returns 429 / secondary 403 /
# primary-limit exhaustion, _rate_limit_until (monotonic seconds) is advanced;
# subsequent _github_api_get calls short-circuit with RateLimited until it lapses.
_rate_limit_until: float = 0.0
_rate_limit_reason: str = ""
_rate_limit_lock = threading.Lock()


class RateLimited(Exception):
    """Raised by _github_api_get while the cooldown gate is active."""
    def __init__(self, retry_after: float, reason: str = ""):
        super().__init__(
            f"GitHub rate limited — retry in {int(retry_after)}s ({reason})"
        )
        self.retry_after = retry_after
        self.reason = reason


def _params_key(params: Optional[dict]) -> tuple:
    if not params:
        return ()
    return tuple(sorted((str(k), str(v)) for k, v in params.items()))


def _parse_retry_after(resp) -> float:
    """Seconds to wait before retrying. Prefers Retry-After, falls back to X-RateLimit-Reset."""
    ra = resp.headers.get("Retry-After")
    if ra:
        try:
            return max(0.0, float(ra))
        except ValueError:
            pass  # HTTP-date form — ignore, fall through to Reset
    reset = resp.headers.get("X-RateLimit-Reset")
    if reset:
        try:
            return max(0.0, int(reset) - time.time())
        except ValueError:
            pass
    return 60.0  # conservative default when GitHub gives no hint


def _set_cooldown(seconds: float, reason: str):
    global _rate_limit_until, _rate_limit_reason
    if seconds <= 0:
        return
    with _rate_limit_lock:
        new_until = time.monotonic() + seconds
        if new_until > _rate_limit_until:
            _rate_limit_until = new_until
            _rate_limit_reason = reason


def _cooldown_remaining() -> tuple[float, str]:
    with _rate_limit_lock:
        return max(0.0, _rate_limit_until - time.monotonic()), _rate_limit_reason


def _github_graphql_post(query: str, variables: dict, token: str,
                         session: Optional[requests.Session] = None,
                         timeout: int = 15) -> dict:
    """POST to GitHub's GraphQL API with the same cooldown gate + 401 handling
    as _github_api_get. No ETag cache — GraphQL doesn't honour If-None-Match.
    Returns the `data` payload; raises RateLimited when the cooldown is active
    and RuntimeError when the response contains `errors`."""
    remaining, reason = _cooldown_remaining()
    if remaining > 0:
        raise RateLimited(remaining, reason or "cooldown")

    _post = (session or requests).post
    resp = _post(
        "https://api.github.com/graphql",
        headers=_gh_headers(token),
        json={"query": query, "variables": variables},
        timeout=timeout,
    )
    status = resp.status_code

    if status == 429 or (
        status == 403
        and "rate limit" in (resp.text or "").lower()
    ):
        wait = _parse_retry_after(resp)
        _set_cooldown(wait, f"HTTP {status}")
        raise RateLimited(wait, f"HTTP {status}")

    if status == 401:
        global _cached_github_username
        with _github_username_lock:
            _cached_github_username = None

    resp.raise_for_status()
    payload = resp.json()

    remaining_hdr = resp.headers.get("X-RateLimit-Remaining")
    if remaining_hdr is not None:
        try:
            if int(remaining_hdr) == 0:
                reset_hdr = resp.headers.get("X-RateLimit-Reset")
                if reset_hdr:
                    wait = max(0.0, int(reset_hdr) - time.time())
                    _set_cooldown(wait, "primary limit exhausted")
        except ValueError:
            pass

    if "errors" in payload:
        raise RuntimeError(f"GraphQL errors: {payload['errors']}")
    return payload.get("data") or {}


def fetch_latest_run(
    owner: str,
    repo: str,
    workflow_file: str,
    branch: Optional[str],
    token: str,
    session: Optional[requests.Session] = None,
) -> Optional[dict]:
    """Fetch the latest workflow run from the GitHub API."""
    api_url = (
        f"https://api.github.com/repos/{owner}/{repo}"
        f"/actions/workflows/{workflow_file}/runs"
    )
    params: dict = {"per_page": 1}
    if branch:
        params["branch"] = branch
    runs = _github_api_get(api_url, token, session, params).get("workflow_runs", [])
    return runs[0] if runs else None


# ---------------------------------------------------------------------------
# GitHub username (cached)
# ---------------------------------------------------------------------------
_cached_github_username: Optional[str] = None
_github_username_lock = threading.Lock()


def fetch_github_username(token: str, session: Optional[requests.Session] = None) -> Optional[str]:
    """Fetch the authenticated user's login via GET /user. Cached after first call."""
    global _cached_github_username
    if not token:
        return None
    with _github_username_lock:
        if _cached_github_username is not None:
            return _cached_github_username
        # Hold lock through fetch to prevent duplicate API calls from concurrent pollers
        login = _github_api_get("https://api.github.com/user", token, session).get("login")
        _cached_github_username = login
        return login


def fetch_pr_runs(
    owner: str,
    repo: str,
    workflow_file: str,
    actor: str,
    token: str,
    per_page: int = 10,
    session: Optional[requests.Session] = None,
) -> list[dict]:
    """Fetch recent workflow runs filtered by actor and pull_request event."""
    api_url = (
        f"https://api.github.com/repos/{owner}/{repo}"
        f"/actions/workflows/{workflow_file}/runs"
    )
    params = {"actor": actor, "event": "pull_request", "per_page": per_page}
    return _github_api_get(api_url, token, session, params).get("workflow_runs", [])


def fetch_actor_runs(
    owner: str,
    repo: str,
    actor: str,
    token: str,
    per_page: int = 20,
    conclusion: Optional[str] = None,
    session: Optional[requests.Session] = None,
) -> list[dict]:
    """Fetch recent workflow runs for a user across all workflows in a repo."""
    api_url = f"https://api.github.com/repos/{owner}/{repo}/actions/runs"
    params: dict = {"actor": actor, "per_page": per_page}
    if conclusion:
        params["conclusion"] = conclusion
    return _github_api_get(api_url, token, session, params).get("workflow_runs", [])


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
    workflow_url: Optional[str] = None  # GitHub workflow overview URL (filtered by branch when known)
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

# Candidate default sound files for Linux, searched in XDG data dirs
_LINUX_SOUND_CANDIDATES = [
    "sounds/freedesktop/stereo/message.oga",
    "sounds/freedesktop/stereo/complete.oga",
    "sounds/alsa/Front_Left.wav",
]
_linux_default_sound_cache: Optional[str] = None


def _find_linux_default_sound() -> Optional[str]:
    """Search XDG data dirs for a usable notification sound file."""
    global _linux_default_sound_cache
    if _linux_default_sound_cache is not None:
        return _linux_default_sound_cache or None
    xdg_dirs = os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":")
    for d in xdg_dirs:
        for candidate in _LINUX_SOUND_CANDIDATES:
            path = os.path.join(d, candidate)
            if os.path.isfile(path):
                _linux_default_sound_cache = path
                return path
    _linux_default_sound_cache = ""  # sentinel: searched but not found
    return None


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
        self._duration: str = "short"
        self._recently_notified: set[tuple[int, Optional[str]]] = set()
        self._notified_lock = threading.Lock()

    def set_batch_window(self, seconds: float):
        with self._lock:
            self._batch_window = max(seconds, 0.0)

    def set_duration(self, duration: str):
        d = (duration or "short").strip().lower()
        if d not in ("short", "long"):
            d = "short"
        with self._lock:
            self._duration = d

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
        with self._lock:
            duration = self._duration
        plyer_timeout = 15 if duration == "long" else 5
        if IS_WINDOWS and WINOTIFY_AVAILABLE:
            try:
                toast = _WinNotification(
                    app_id="WizX20.ActionsMonitor",
                    title=title,
                    msg=message,
                    duration=duration,
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
                    timeout=plyer_timeout,
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
                sound_file = _find_linux_default_sound()
                if sound_file:
                    for player in ("paplay", "aplay"):
                        try:
                            subprocess.Popen([player, sound_file],
                                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                            break
                        except FileNotFoundError:
                            continue
            else:
                for player in ("paplay", "aplay"):
                    try:
                        subprocess.Popen([player, sound_cfg],
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        break
                    except FileNotFoundError:
                        continue


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

    def _emit_error(self, error: str = "", branch=None, sub_key=None):
        """Emit a ST_UNKNOWN state with an optional error message."""
        state = WorkflowState(
            name=self.name_display,
            url=self.cfg_entry.get("url", ""),
            branch=branch,
            workflow_url=_build_workflow_url(self.owner, self.repo, self.wf_file, branch or self.branch),
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
        )

        if not self.owner:
            self._emit_error("Invalid workflow URL in config", branch=self.branch)
            return

        try:
            run = fetch_latest_run(self.owner, self.repo, self.wf_file, self.branch, token, session=self._session)
        except requests.HTTPError as exc:
            self._emit_error(f"HTTP {exc.response.status_code}", branch=self.branch)
            return
        except Exception as exc:
            self._emit_error(str(exc), branch=self.branch)
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
            self._emit_error(f"Cannot resolve GitHub user: {exc}")
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
            except requests.HTTPError as exc:
                if not all_runs and wf_file == self.wf_file:
                    self._emit_error(f"HTTP {exc.response.status_code}")
                    return
                # Extra workflow failed — skip silently
            except Exception as exc:
                if not all_runs and wf_file == self.wf_file:
                    self._emit_error(str(exc))
                    return

        # Fetch the user's open PRs — used to discover branches with old runs
        # AND to filter out branches whose PRs have been closed/merged.
        branches_with_runs = {r.get("head_branch") for r in all_runs}
        open_prs_ok = False
        try:
            open_prs = self._fetch_user_open_prs(username, token)
            open_prs_ok = True
        except Exception:
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
                except Exception:
                    pass
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
        Returns (status, by_bot) where status ∈ {'approved','changes_requested',
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
        Cached for _mergeable_cache_ttl seconds. GitHub computes mergeable lazily —
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
            # GitHub computes mergeable lazily; "unknown" means not ready yet —
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
            self._emit_error(f"Cannot resolve GitHub user: {exc}")
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
        except requests.HTTPError as exc:
            self._emit_error(f"HTTP {exc.response.status_code}")
            return
        except Exception as exc:
            self._emit_error(str(exc))
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


class URLQueryPoller(WorkflowPoller):
    """Poller that runs an arbitrary GitHub Search API query and renders each PR result.

    Uses GET /search/issues?q=<query> — supports the full GitHub PR filter syntax
    (see https://docs.github.com/en/search-github/searching-on-github/searching-issues-and-pull-requests).
    Only pull-request results are rendered; issue-only hits are skipped.

    The row status comes from the review state rather than CI: approved → success icon,
    changes-requested → failure icon, anything else → unknown icon. This keeps URL
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
                self._emit_error(f"Cannot resolve @me: {exc}")
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
        except requests.HTTPError as exc:
            self._emit_error(f"HTTP {exc.response.status_code}")
            return
        except Exception as exc:
            self._emit_error(str(exc))
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

            row_status = ST_UNKNOWN
            if review_status == "approved":
                row_status = ST_SUCCESS
            elif review_status == "changes_requested":
                row_status = ST_FAILURE

            head_branch = (pr_detail or {}).get("head_ref", "")

            state = WorkflowState(
                name=f"{owner}/{repo}",
                url=item.get("html_url", ""),
                branch=head_branch or None,
                head_branch=head_branch or None,
            )
            state.last_check    = now
            state.status        = row_status
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
            "mergeable_state": data.get("mergeable_state", "unknown"),
        }
        self._pr_cache[key] = detail
        _prune_cache(self._pr_cache, _PR_CACHE_MAX)
        return detail

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
    img, draw, hi = _icon_base(size)
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


def _make_update_icon(size: int = 16, colour: str = FG_LINK) -> Image.Image:
    """Lucide arrow-down-to-line icon: downward arrow above a short baseline."""
    img, draw, hi = _icon_base(size)
    sw = max(3, round(hi / 16 * 2.2))
    cx = hi / 2
    top_y = hi * 0.22
    bot_y = hi * 0.70
    draw.line([(cx, top_y), (cx, bot_y)], fill=colour, width=sw)
    head = hi * 0.18
    draw.polygon([
        (cx, bot_y + head * 0.6),
        (cx - head, bot_y - head * 0.2),
        (cx + head, bot_y - head * 0.2),
    ], fill=colour)
    base_y = hi * 0.86
    draw.line([(cx - hi * 0.26, base_y), (cx + hi * 0.26, base_y)],
              fill=colour, width=sw)
    return img.resize((size, size), Image.LANCZOS)


def _make_help_icon(size: int = 16, colour: str = FG_LINK) -> Image.Image:
    """Lucide circle-help icon: question mark inside an outlined circle."""
    img, draw, hi = _icon_base(size)
    sw = max(3, round(hi / 16 * 2.2))
    cx, cy = hi / 2, hi / 2
    r = hi * 0.42
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=colour, width=sw)
    fsize = int(hi * 0.58)
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
    draw.text((tx, ty), "?", fill=colour, font=font)
    return img.resize((size, size), Image.LANCZOS)


# --- Reviewer icons (Lucide user + bot), rendered inline inside review badges ---

def _make_user_icon(size: int, colour: str) -> Image.Image:
    """Lucide user icon: circle head + bust arc. No background."""
    img, draw, hi = _icon_base(size)
    sw = max(2, round(hi / 24 * 2.2))
    cx = hi / 2
    head_cy = hi * 0.33
    head_r  = hi * 0.20
    draw.ellipse([cx - head_r, head_cy - head_r,
                  cx + head_r, head_cy + head_r],
                 outline=colour, width=sw)
    bust_r  = hi * 0.40
    bust_cy = hi * 1.00
    draw.arc([cx - bust_r, bust_cy - bust_r,
              cx + bust_r, bust_cy + bust_r],
             start=180, end=360, fill=colour, width=sw)
    return img.resize((size, size), Image.LANCZOS)


def _make_bot_icon(size: int, colour: str) -> Image.Image:
    """Lucide bot icon: antenna + rounded-rect head + two eyes. No background."""
    img, draw, hi = _icon_base(size)
    sw = max(2, round(hi / 24 * 2.0))
    cx = hi / 2
    top = hi * 0.10
    antenna_end = hi * 0.26
    draw.line([(cx, top), (cx, antenna_end)], fill=colour, width=sw)
    dot_r = max(sw * 0.7, 1.5)
    draw.ellipse([cx - dot_r, top - dot_r, cx + dot_r, top + dot_r], fill=colour)
    head_left  = hi * 0.16
    head_right = hi * 0.84
    head_top   = antenna_end + sw
    head_bot   = hi * 0.84
    try:
        draw.rounded_rectangle(
            [head_left, head_top, head_right, head_bot],
            radius=hi * 0.13, outline=colour, width=sw,
        )
    except AttributeError:
        draw.rectangle([head_left, head_top, head_right, head_bot],
                       outline=colour, width=sw)
    eye_cy = (head_top + head_bot) / 2
    eye_r  = max(hi * 0.055, 1.5)
    for ex in (cx - hi * 0.15, cx + hi * 0.15):
        draw.ellipse([ex - eye_r, eye_cy - eye_r,
                      ex + eye_r, eye_cy + eye_r], fill=colour)
    return img.resize((size, size), Image.LANCZOS)


_REVIEWER_ICON_B64: dict[tuple[str, str, int], str] = {}


def _reviewer_icon_b64(kind: str, colour: str, px: int = 12) -> str:
    """Render reviewer glyph at `px` pixels in `colour`, return base64 PNG.
    kind: 'bot' | 'user'. Cached per (kind, colour, px)."""
    key = (kind, colour, px)
    cached = _REVIEWER_ICON_B64.get(key)
    if cached is not None:
        return cached
    img = _make_bot_icon(px, colour) if kind == "bot" else _make_user_icon(px, colour)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    data = base64.b64encode(buf.getvalue()).decode("ascii")
    _REVIEWER_ICON_B64[key] = data
    return data


# --- Snooze button icon (bell / bell-off) ---

_SNOOZE_ICON_SIZE = 16


def _draw_bell_glyph(draw: ImageDraw.Draw, hi: int, fg_colour: str):
    """Draw a filled bell glyph centred in a hi x hi canvas."""
    cx = hi / 2
    # Dome (top half of ellipse blended into body)
    dome_w = hi * 0.48
    dome_top = hi * 0.20
    dome_h = hi * 0.50
    draw.ellipse([cx - dome_w / 2, dome_top,
                  cx + dome_w / 2, dome_top + dome_h], fill=fg_colour)
    # Body: rectangle blending dome into rim
    body_w = hi * 0.42
    body_top = dome_top + dome_h * 0.45
    body_bot = hi * 0.66
    draw.rectangle([cx - body_w / 2, body_top,
                    cx + body_w / 2, body_bot], fill=fg_colour)
    # Flared rim (wider)
    rim_w = hi * 0.56
    rim_top = body_bot
    rim_bot = hi * 0.74
    draw.rectangle([cx - rim_w / 2, rim_top,
                    cx + rim_w / 2, rim_bot], fill=fg_colour)
    # Top pin
    pin_w = hi * 0.14
    pin_top = hi * 0.08
    pin_h = hi * 0.12
    draw.ellipse([cx - pin_w / 2, pin_top,
                  cx + pin_w / 2, pin_top + pin_h], fill=fg_colour)
    # Clapper (small circle below rim)
    cl_w = hi * 0.16
    cl_top = hi * 0.78
    draw.ellipse([cx - cl_w / 2, cl_top,
                  cx + cl_w / 2, cl_top + cl_w], fill=fg_colour)


def _make_snooze_icon(size: int = _SNOOZE_ICON_SIZE, bg_colour: str = "#3D3530",
                      fg_colour: str = "#A8A29E", off: bool = False) -> Image.Image:
    """Bell icon on a filled circle background. When `off`, adds a diagonal slash."""
    img, draw, hi = _icon_base(size)
    pad = int(hi * 0.02)
    draw.ellipse([pad, pad, hi - pad, hi - pad], fill=bg_colour)
    _draw_bell_glyph(draw, hi, fg_colour)
    if off:
        slash_start = (hi * 0.20, hi * 0.22)
        slash_end = (hi * 0.80, hi * 0.82)
        gap_w = max(4, round(hi / 16 * 5.0))
        line_w = max(2, round(hi / 16 * 2.2))
        draw.line([slash_start, slash_end], fill=bg_colour, width=gap_w)
        draw.line([slash_start, slash_end], fill=fg_colour, width=line_w)
    return img.resize((size, size), Image.LANCZOS)


def _pil_to_qpixmap(pil_img: Image.Image) -> QPixmap:
    """Convert a PIL Image to a QPixmap."""
    img = pil_img.convert("RGBA")
    data = img.tobytes("raw", "RGBA")
    qimg = QImage(data, img.width, img.height, img.width * 4, QImage.Format.Format_RGBA8888)
    return QPixmap.fromImage(qimg)


_snooze_qpixmaps: dict[str, QPixmap] = {}


_SNOOZE_ICON_STYLES = {
    "normal":       ("#3D3530", "#A8A29E", False),
    "hover":        ("#4A3728", "#FBBF24", False),
    "active":       ("#92400E", "#FEF3C7", True),
    "active_hover": ("#78350F", "#FFFFFF", True),
}


def _init_snooze_icons():
    """Generate snooze/unsnooze button icons (normal + hover). Call after QApplication exists."""
    if _snooze_qpixmaps:
        return
    for key, (bg, fg, off) in _SNOOZE_ICON_STYLES.items():
        _snooze_qpixmaps[key] = _pil_to_qpixmap(
            _make_snooze_icon(bg_colour=bg, fg_colour=fg, off=off))


# WizX20 logo mark (lightning bolt) — rendered from docs/wizx20-mark.png
# 256×256 RGBA PNG, embedded so no asset file needs bundling.
_WIZX20_MARK_B64 = (
    "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"
    "YII="
)

_wizx20_mark_cache: dict[int, "Image.Image"] = {}

def _load_wizx20_mark(height: int) -> "Image.Image":
    """Decode the embedded WizX20 mark PNG and scale to the given height."""
    if height in _wizx20_mark_cache:
        return _wizx20_mark_cache[height]
    import base64, io
    data = base64.b64decode(_WIZX20_MARK_B64)
    mark = Image.open(io.BytesIO(data)).convert("RGBA")
    w = int(mark.width * height / mark.height)
    mark = mark.resize((w, height), Image.LANCZOS)
    _wizx20_mark_cache[height] = mark
    return mark

# --- App / tray icon (WizX20 bolt mark on dark rounded rect + status dot) ---

def _make_base_icon(size: int = 64) -> Image.Image:
    """App icon: WizX20 bolt mark on dark rounded-rect background.
    At ≤32px the full mark fuses into a blob, so a simplified amber ">" chevron
    is drawn instead — readable in toasts and the taskbar."""
    img, draw, hi = _icon_base(size)

    if size <= 32:
        # Simplified amber chevron, no chrome — fills the icon area cleanly.
        cx, cy = hi // 2, hi // 2
        arm = int(hi * 0.35)
        sw = max(2, int(hi * 0.18))
        tip = (cx + arm // 2, cy)
        top = (cx - arm // 2, cy - arm)
        bot = (cx - arm // 2, cy + arm)
        draw.line([top, tip, bot], fill="#FBBF24", width=sw, joint="curve")
        return img.resize((size, size), Image.LANCZOS)

    pad = hi // 16
    radius = hi // 4
    draw.rounded_rectangle([pad, pad, hi - pad, hi - pad],
                           radius=radius, fill="#252220")
    inner_pad = pad + hi // 32
    inner_radius = radius - hi // 32
    draw.rounded_rectangle([inner_pad, inner_pad, hi - inner_pad, hi - inner_pad],
                           radius=inner_radius, fill="#2D2926")

    # WizX20 bolt mark — composited from embedded PNG
    mark_pad = hi // 10
    mark_h = hi - 2 * (inner_pad + mark_pad)
    mark = _load_wizx20_mark(mark_h)
    mx = (hi - mark.width) // 2
    my = (hi - mark.height) // 2
    img.paste(mark, (mx, my), mark)

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
    Regenerated every startup so icon design changes take effect without
    requiring users to delete the existing file."""
    try:
        sizes = [256, 48, 32, 16]  # largest first for proper ICO embedding
        images = [_make_base_icon(s) for s in sizes]
        images[0].save(str(APP_ICO), format="ICO",
                       sizes=[(s, s) for s in sizes],
                       append_images=images[1:])
    except Exception as exc:
        print(f"[Icon] Generate error: {exc}")


def _generate_check_glyph() -> None:
    """Generate a white check-mark PNG used as the QCheckBox indicator image
    in the dark-theme stylesheet. Rendered at 4x supersample + LANCZOS for
    clean edges at 14x14 display size. Regenerated every startup."""
    try:
        size, scale = 14, 4
        hi = size * scale
        img = Image.new("RGBA", (hi, hi), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        sw = max(2, int(hi * 0.16))
        pts = [
            (hi * 0.22, hi * 0.54),
            (hi * 0.44, hi * 0.74),
            (hi * 0.80, hi * 0.30),
        ]
        draw.line(pts, fill="#FFFFFF", width=sw, joint="curve")
        img.resize((size, size), Image.LANCZOS).save(str(_CHECK_PNG), format="PNG")
    except Exception as exc:
        print(f"[Check glyph] Generate error: {exc}")


def _worst_status(statuses: set[str]) -> str:
    """Return the highest-priority status from a set (failure > running > queued > success)."""
    if ST_FAILURE  in statuses: return ST_FAILURE
    if ST_RUNNING  in statuses: return ST_RUNNING
    if ST_QUEUED   in statuses: return ST_QUEUED
    if ST_SUCCESS  in statuses: return ST_SUCCESS
    return ST_UNKNOWN


def _combined_status(states: list[WorkflowState]) -> str:
    return _worst_status({s.status for s in states})


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

# Pre-generated status icon QPixmaps (populated once QApplication exists)
_status_qpixmaps: dict[str, QPixmap] = {}
_ICON_SIZE = 24  # px for row status icons


def _init_status_icons():
    """Generate and cache QPixmap icons for all statuses. Call after QApplication exists."""
    if _status_qpixmaps:
        return
    for st in (ST_UNKNOWN, ST_QUEUED, ST_RUNNING, ST_SUCCESS,
               ST_FAILURE, ST_CANCELLED, ST_SKIPPED):
        img = _make_status_icon(st, _ICON_SIZE)
        _status_qpixmaps[st] = _pil_to_qpixmap(img)


class _ClickableLabel(QLabel):
    """QLabel that opens a URL on click and shows a hand cursor."""
    def __init__(self, *args, url_fn=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._url_fn = url_fn
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._url_fn:
            url = self._url_fn()
            if url:
                webbrowser.open(url)


def _link_css(color: str, size: int, hover: str = FG_LINK) -> str:
    """Stylesheet for a clickable label: base color + amber hover via :hover pseudo-state."""
    return (f"QLabel {{ color: {color}; font-size: {size}px; }} "
            f"QLabel:hover {{ color: {hover}; text-decoration: underline; }}")


def _make_badge(text: str, bg: str, fg: str, bold: bool = False) -> QLabel:
    """Create a small badge label with styled background."""
    lbl = QLabel(text)
    weight = "bold" if bold else "normal"
    lbl.setStyleSheet(
        f"background-color: {bg}; color: {fg}; font-size: 9px; font-weight: {weight}; "
        f"padding: 1px 3px; border-radius: 2px;"
    )
    lbl.setVisible(False)
    return lbl


class WorkflowRow(QWidget):

    def __init__(self, parent: QWidget, wid: int, state: WorkflowState, alt: bool,
                 jira_base_url: str = "", sub_key: Optional[str] = None,
                 snooze_cb: Optional[callable] = None):
        super().__init__(parent)
        self.wid = wid
        self._sub_key = sub_key
        self._state = state
        self._jira_base_url = jira_base_url
        self._snooze_cb = snooze_cb
        self._snoozed = False
        self._icon_opacity: Optional[QGraphicsOpacityEffect] = None
        self._bg = BG_ROW_ALT if alt else BG_ROW
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_right_click)

        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Left accent bar
        self._accent = QFrame()
        self._accent.setFixedWidth(3)
        self._accent.setStyleSheet(f"background-color: {COLOUR[state.status]};")
        main_layout.addWidget(self._accent)

        # Left column: icon + snooze
        left_col = QVBoxLayout()
        left_col.setContentsMargins(12, 8, 10, 4)
        left_col.setSpacing(4)

        self._icon_lbl = QLabel()
        pixmap = _status_qpixmaps.get(state.status, _status_qpixmaps.get(ST_UNKNOWN))
        self._icon_lbl.setPixmap(pixmap)
        self._icon_lbl.setFixedSize(24, 24)
        left_col.addWidget(self._icon_lbl, 0, Qt.AlignmentFlag.AlignHCenter)
        main_layout.addLayout(left_col)

        # Centre column
        centre = QVBoxLayout()
        centre.setContentsMargins(0, 8, 0, 6)
        centre.setSpacing(0)

        # PR title (shown above top_row for PR mode)
        self._pr_title_lbl = _ClickableLabel(
            url_fn=lambda: self._state.pr_url)
        self._pr_title_lbl.setStyleSheet(_link_css(FG_TEXT, 12))
        self._pr_title_lbl.setToolTip("Open PR on GitHub")
        self._pr_title_lbl.setMinimumWidth(0)
        self._pr_title_lbl.setWordWrap(True)
        self._pr_title_lbl.setVisible(False)
        centre.addWidget(self._pr_title_lbl)

        # Top row: name + branch
        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(0)

        self._name_lbl = _ClickableLabel(state.name, url_fn=self._name_url)
        self._name_lbl.setStyleSheet(_link_css(FG_TEXT, 12))
        self._name_lbl.setMinimumWidth(0)
        self._name_lbl.setWordWrap(True)
        top_row.addWidget(self._name_lbl, 1)

        self._branch_lbl = _ClickableLabel(url_fn=self._branch_url)
        self._branch_lbl.setStyleSheet(_link_css(FG_MUTED, 11))
        self._branch_lbl.setToolTip("Open latest run on GitHub")
        self._branch_lbl.setMinimumWidth(0)
        self._branch_lbl.setWordWrap(True)
        self._branch_lbl.setVisible(False)
        top_row.addWidget(self._branch_lbl, 1)

        top_row.addStretch()
        centre.addLayout(top_row)

        # Badge row
        badge_layout = QHBoxLayout()
        badge_layout.setContentsMargins(0, 2, 0, 0)
        badge_layout.setSpacing(4)

        self._prefix_lbl = _make_badge("", "#3D3530", "#FBBF24")
        badge_layout.addWidget(self._prefix_lbl)

        self._draft_lbl = _make_badge("DRAFT", "#92400E", "#FEF3C7", bold=True)
        badge_layout.addWidget(self._draft_lbl)

        self._conflict_lbl = _make_badge("\u26A0 CONFLICT", "#7F1D1D", "#FEE2E2", bold=True)
        self._conflict_lbl.setToolTip("This PR has merge conflicts that must be resolved")
        badge_layout.addWidget(self._conflict_lbl)

        self._unresolved_lbl = _make_badge("", "#4A1D1D", "#FCA5A5", bold=True)
        self._unresolved_lbl.setToolTip("Unresolved review threads on this PR")
        badge_layout.addWidget(self._unresolved_lbl)

        self._jira_lbl = _make_badge("", "#302830", "#A78BFA")
        self._jira_lbl.setCursor(Qt.CursorShape.PointingHandCursor)
        self._jira_lbl.mousePressEvent = lambda e: self._open_jira()
        badge_layout.addWidget(self._jira_lbl)

        self._review_lbl = _make_badge("", "#3D3530", "#FBBF24")
        self._review_lbl.setTextFormat(Qt.RichText)
        badge_layout.addWidget(self._review_lbl)

        self._stale_lbl = _make_badge("", "#3D3520", "#EAB308", bold=True)
        badge_layout.addWidget(self._stale_lbl)

        self._snooze_lbl = _make_badge("SNOOZED", "#3D3530", "#A8A29E", bold=True)
        badge_layout.addWidget(self._snooze_lbl)

        badge_layout.addStretch()
        self._badge_widget = QWidget()
        self._badge_widget.setLayout(badge_layout)
        self._badge_widget.setVisible(False)
        centre.addWidget(self._badge_widget)

        # Status info line
        self._info_lbl = QLabel()
        self._info_lbl.setStyleSheet(f"color: {FG_MUTED}; font-size: 11px;")
        self._info_lbl.setMinimumWidth(0)
        self._info_lbl.setWordWrap(True)
        centre.addWidget(self._info_lbl)

        main_layout.addLayout(centre, 1)

        # Right column: poll rate + compact snooze button
        right_col = QHBoxLayout()
        right_col.setContentsMargins(4, 10, 12, 0)
        right_col.setSpacing(4)

        self._poll_lbl = QLabel()
        self._poll_lbl.setStyleSheet(f"color: {FG_MUTED}; font-size: 11px;")
        self._poll_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        right_col.addWidget(self._poll_lbl)

        self._snooze_btn = QLabel()
        self._snooze_btn.setPixmap(_snooze_qpixmaps.get("normal", QPixmap()))
        self._snooze_btn.setFixedSize(16, 16)
        self._snooze_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._snooze_btn.setToolTip("Snooze — pause polling, dim the row, mute notifications")
        self._snooze_btn.mousePressEvent = lambda e: self._toggle_snooze()
        self._snooze_btn.enterEvent = lambda e: self._snooze_hover_enter()
        self._snooze_btn.leaveEvent = lambda e: self._snooze_hover_leave()
        right_col.addWidget(self._snooze_btn, 0, Qt.AlignmentFlag.AlignTop)

        right_wrap = QWidget()
        right_wrap.setLayout(right_col)
        right_wrap.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        main_layout.addWidget(right_wrap)

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self._apply_background()
        self._update_labels()

    def _apply_background(self):
        self.setStyleSheet(
            f"WorkflowRow {{ background-color: {self._bg}; }}"
        )

    def _name_url(self) -> Optional[str]:
        s = self._state
        # Name label opens workflow overview when both links are distinct;
        # otherwise it's the only click target so it falls back to the run.
        if s.workflow_url and (s.run_url or s.url):
            return s.workflow_url
        return s.run_url or s.url

    def _branch_url(self) -> Optional[str]:
        s = self._state
        return s.run_url or s.url

    def _on_right_click(self, pos):
        if self._snooze_cb:
            self._snooze_cb((self.wid, self._sub_key), self.mapToGlobal(pos))

    def _toggle_snooze(self):
        if self._snooze_cb:
            self._snooze_cb((self.wid, self._sub_key), None)

    def _snooze_hover_enter(self):
        key = "active_hover" if self._snoozed else "hover"
        pm = _snooze_qpixmaps.get(key)
        if pm:
            self._snooze_btn.setPixmap(pm)

    def _snooze_hover_leave(self):
        key = "active" if self._snoozed else "normal"
        pm = _snooze_qpixmaps.get(key)
        if pm:
            self._snooze_btn.setPixmap(pm)

    def set_snoozed(self, snoozed: bool):
        self._snoozed = snoozed
        self._snooze_btn.setToolTip(
            "Unsnooze — resume polling and notifications" if snoozed
            else "Snooze — pause polling, dim the row, mute notifications")
        dim_text = "#57534E"
        dim_muted = "#44403C"
        if snoozed:
            self._accent.setStyleSheet(f"background-color: #3F3B38;")
            self._info_lbl.setStyleSheet(f"color: {dim_muted}; font-size: 11px;")
            self._name_lbl.setStyleSheet(_link_css(dim_text, 12))
            self._poll_lbl.setStyleSheet(f"color: {dim_muted}; font-size: 11px;")
            self._branch_lbl.setStyleSheet(_link_css(dim_muted, 11))
            self._pr_title_lbl.setStyleSheet(_link_css(dim_text, 12))
            if self._icon_opacity is None:
                self._icon_opacity = QGraphicsOpacityEffect(self._icon_lbl)
                self._icon_lbl.setGraphicsEffect(self._icon_opacity)
            self._icon_opacity.setOpacity(0.35)
        else:
            self._accent.setStyleSheet(
                f"background-color: {COLOUR.get(self._state.status, COLOUR[ST_UNKNOWN])};")
            self._info_lbl.setStyleSheet(f"color: {FG_MUTED}; font-size: 11px;")
            self._name_lbl.setStyleSheet(_link_css(FG_TEXT, 12))
            self._poll_lbl.setStyleSheet(f"color: {FG_MUTED}; font-size: 11px;")
            self._branch_lbl.setStyleSheet(_link_css(FG_MUTED, 11))
            self._pr_title_lbl.setStyleSheet(_link_css(FG_TEXT, 12))
            if self._icon_opacity is not None:
                self._icon_opacity.setOpacity(1.0)
        self._restyle_static_badges()
        self._update_labels()

    def _badge_css(self, bg: str, fg: str, bold: bool = False) -> str:
        if self._snoozed:
            bg, fg = "#2C2825", "#57534E"
        weight = "bold" if bold else "normal"
        return (f"background-color: {bg}; color: {fg}; font-size: 9px; "
                f"font-weight: {weight}; padding: 1px 3px; border-radius: 2px;")

    def _restyle_static_badges(self):
        self._prefix_lbl.setStyleSheet(self._badge_css("#3D3530", "#FBBF24"))
        self._draft_lbl.setStyleSheet(self._badge_css("#92400E", "#FEF3C7", bold=True))
        self._conflict_lbl.setStyleSheet(self._badge_css("#7F1D1D", "#FEE2E2", bold=True))
        self._unresolved_lbl.setStyleSheet(self._badge_css("#4A1D1D", "#FCA5A5", bold=True))
        self._jira_lbl.setStyleSheet(self._badge_css("#302830", "#A78BFA"))

    def _open_jira(self):
        if self._jira_base_url and self._state.jira_key:
            webbrowser.open(f"{self._jira_base_url.rstrip('/')}/browse/{self._state.jira_key}")

    def update(self, state: WorkflowState, poll_rate: int, jira_base_url: str = ""):
        self._state = state
        self._jira_base_url = jira_base_url or self._jira_base_url
        if not self._snoozed:
            self._accent.setStyleSheet(
                f"background-color: {COLOUR.get(state.status, COLOUR[ST_UNKNOWN])};")
            pixmap = _status_qpixmaps.get(state.status, _status_qpixmaps.get(ST_UNKNOWN))
            self._icon_lbl.setPixmap(pixmap)
        self._poll_lbl.setText(f"{poll_rate}s")
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
                    dt = datetime.fromisoformat(s.started_at.replace("Z", "+00:00"))
                    dt_local = dt.astimezone()
                    status_txt += f"  ({dt_local.strftime('%d %b %H:%M')})"
                except Exception:
                    pass

        self._info_lbl.setText(status_txt)

        has_badges = False
        if s.head_branch:
            # PR mode shows the PR title as the headline; actor mode falls back
            # to the workflow name (so the title link can point at the workflow).
            if s.pr_title:
                self._name_lbl.setVisible(False)
                self._pr_title_lbl.setText(s.pr_title)
                self._pr_title_lbl.setVisible(True)
            else:
                self._name_lbl.setText(s.name)
                self._name_lbl.setVisible(True)
                self._pr_title_lbl.setVisible(False)

            branch_text = s.branch_short or s.head_branch
            if s.pr_number:
                branch_text = f"#{s.pr_number}  {branch_text}"
            if s.pr_target:
                branch_text += f" \u2192 {s.pr_target}"
            self._branch_lbl.setText(branch_text)
            self._branch_lbl.setVisible(True)

            if s.branch_prefix:
                self._prefix_lbl.setText(s.branch_prefix)
                self._prefix_lbl.setVisible(True)
                has_badges = True
            else:
                self._prefix_lbl.setVisible(False)

            self._draft_lbl.setVisible(bool(s.is_draft))
            if s.is_draft:
                has_badges = True

            self._conflict_lbl.setVisible(bool(s.has_conflict))
            if s.has_conflict:
                has_badges = True

            if s.unresolved_threads > 0:
                self._unresolved_lbl.setText(f"{s.unresolved_threads} UNRESOLVED")
                self._unresolved_lbl.setVisible(True)
                has_badges = True
            else:
                self._unresolved_lbl.setVisible(False)

            if s.jira_key and self._jira_base_url:
                self._jira_lbl.setText(s.jira_key)
                self._jira_lbl.setVisible(True)
                has_badges = True
            else:
                self._jira_lbl.setVisible(False)

            if s.review_status:
                text, bg_col, fg_col = _REVIEW_BADGE_CFG.get(
                    s.review_status, ("REVIEW PENDING", "#3D3530", "#FBBF24"))
                if s.review_status in ("approved", "changes_requested"):
                    kind = "bot" if s.review_by_bot else "user"
                    b64 = _reviewer_icon_b64(kind, fg_col, 12)
                    html = (f"<img src='data:image/png;base64,{b64}' "
                            f"width='11' height='11' "
                            f"style='vertical-align:middle' />&nbsp;{text}")
                    self._review_lbl.setText(html)
                    self._review_lbl.setToolTip(
                        "Reviewed by bot" if s.review_by_bot else "Reviewed by human")
                else:
                    self._review_lbl.setText(text)
                    self._review_lbl.setToolTip("")
                self._review_lbl.setStyleSheet(self._badge_css(bg_col, fg_col))
                self._review_lbl.setVisible(True)
                has_badges = True
            else:
                self._review_lbl.setVisible(False)
                self._review_lbl.setToolTip("")

            if s.staleness_level and s.pr_updated_at:
                bg_col, fg_col = _STALENESS_BADGE_CFG.get(s.staleness_level, ("#3D3520", "#EAB308"))
                age = _format_age(s.pr_updated_at)
                self._stale_lbl.setText(f"STALE {age}" if age else "STALE")
                self._stale_lbl.setStyleSheet(self._badge_css(bg_col, fg_col, bold=True))
                self._stale_lbl.setVisible(True)
                has_badges = True
            else:
                self._stale_lbl.setVisible(False)

            self._snooze_lbl.setVisible(self._snoozed)
            if self._snoozed:
                has_badges = True

            self._badge_widget.setVisible(has_badges)
        else:
            self._name_lbl.setVisible(True)

            # Branch mode: surface the configured branch as a subtitle so the
            # row exposes both a workflow-overview click and a run click.
            if s.branch and s.workflow_url and s.run_url:
                self._branch_lbl.setText(s.branch)
                self._branch_lbl.setVisible(True)
            else:
                self._branch_lbl.setVisible(False)
            self._prefix_lbl.setVisible(False)
            self._draft_lbl.setVisible(False)
            self._conflict_lbl.setVisible(False)
            self._unresolved_lbl.setVisible(False)
            self._jira_lbl.setVisible(False)
            self._review_lbl.setVisible(False)
            self._stale_lbl.setVisible(False)
            self._pr_title_lbl.setVisible(False)

            self._snooze_lbl.setVisible(self._snoozed)
            self._badge_widget.setVisible(self._snoozed)

        # Name-label tooltip reflects whichever URL its click currently opens.
        if s.workflow_url and (s.run_url or s.url):
            self._name_lbl.setToolTip("Open workflow on GitHub")
        else:
            self._name_lbl.setToolTip("Open latest run on GitHub")

        # Snooze button visibility (always visible)
        key = "active" if self._snoozed else "normal"
        self._snooze_btn.setPixmap(_snooze_qpixmaps.get(key, QPixmap()))
        self._snooze_btn.setVisible(True)


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
def _detect_install_source() -> str:
    """Return 'scoop', 'winget', or 'direct' based on the exe location.

    Package-manager installs should upgrade via the manager, not via the
    in-app updater — writing into scoop/winget-managed dirs causes metadata
    drift and the next manager-driven update overwrites the swap.
    """
    if not getattr(sys, "frozen", False):
        return "direct"
    exe = str(Path(sys.executable)).replace("/", "\\").lower()
    if "\\scoop\\apps\\" in exe:
        return "scoop"
    if "\\winget\\packages\\" in exe:
        return "winget"
    return "direct"


_MANAGED_UPGRADE_CMD = {
    "scoop": "scoop update actionsmonitor",
    "winget": "winget upgrade WizX20.ActionsMonitor",
}


class UpdateChecker:
    REPO_URL = "https://github.com/WizX20/ActionsMonitor"
    RELEASES_API = "https://api.github.com/repos/WizX20/ActionsMonitor/releases/latest"

    # Populated by _check_release() for use in apply_update() and the dialog.
    _release_data: Optional[dict] = None
    # Populated by _apply_release_update() once new binary is downloaded.
    _update_path: Optional[Path] = None

    @staticmethod
    def check() -> Optional[str]:
        """Returns a version string if an update is available, None otherwise.

        Only frozen builds check for updates. Source installs sync via git manually.
        """
        if not getattr(sys, "frozen", False):
            return None
        return UpdateChecker._check_release()

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
            tag_name = data.get("tag_name", "")
            if re.fullmatch(r"[0-9a-f]{7,}", commitish):
                # target_commitish is a SHA — compare directly
                if commitish[:7] == BUILD_COMMIT:
                    return None
            else:
                # target_commitish is a branch name — compare tag_name to BUILD_COMMIT
                # as a fallback (tag_name may be a version like "v1.2" or a short SHA)
                if tag_name == BUILD_COMMIT:
                    return None
            UpdateChecker._release_data = data
            return tag_name or commitish[:7]
        except Exception:
            pass
        return None

    @staticmethod
    def apply_update(progress_cb=None) -> tuple[bool, str]:
        """Download latest release binary. Returns (success, message).

        progress_cb(bytes_written, expected_size) fires after each chunk.
        expected_size may be 0 when the asset metadata omits a size.
        """
        return UpdateChecker._apply_release_update(progress_cb)

    @staticmethod
    def _apply_release_update(progress_cb=None) -> tuple[bool, str]:
        """Download the latest release binary to a staging path.

        Does NOT swap the running executable — swap happens in a detached
        helper script launched by restart_app() after the current process
        has exited. Swapping in-place while PyInstaller is still lazy-loading
        modules corrupts archive reads (zlib "incorrect header check").
        """
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
            expected_size = asset.get("size") or 0
            # GitHub Releases API exposes a "digest" field like "sha256:HEX"
            # on assets uploaded after ~2024. Verify when present; skip when not.
            expected_digest = asset.get("digest") or ""
            expected_sha256 = ""
            if expected_digest.startswith("sha256:"):
                expected_sha256 = expected_digest.split(":", 1)[1].lower()
            current_exe = Path(sys.executable)
            tmp_path = current_exe.with_suffix(".update")

            bytes_written = 0
            hasher = hashlib.sha256() if expected_sha256 else None
            if progress_cb:
                progress_cb(0, expected_size)
            dl = requests.get(download_url, stream=True, timeout=120)
            try:
                dl.raise_for_status()
                with open(tmp_path, "wb") as f:
                    for chunk in dl.iter_content(chunk_size=65536):
                        f.write(chunk)
                        if hasher:
                            hasher.update(chunk)
                        bytes_written += len(chunk)
                        if progress_cb:
                            progress_cb(bytes_written, expected_size)
            finally:
                # Close on a worker with a short timeout — Windows AV / proxy
                # can stall the socket teardown for minutes, leaving the
                # dialog pinned at 100% even though the file is fully written.
                closer = threading.Thread(target=dl.close, daemon=True)
                closer.start()
                closer.join(timeout=2.0)

            if expected_size and bytes_written != expected_size:
                try:
                    tmp_path.unlink(missing_ok=True)
                except OSError:
                    pass
                return False, (
                    f"Download size mismatch (got {bytes_written}, expected {expected_size})"
                )

            if hasher:
                actual_sha256 = hasher.hexdigest()
                if actual_sha256 != expected_sha256:
                    try:
                        tmp_path.unlink(missing_ok=True)
                    except OSError:
                        pass
                    return False, (
                        f"Checksum mismatch (got {actual_sha256[:12]}…, "
                        f"expected {expected_sha256[:12]}…)"
                    )

            if not IS_WINDOWS:
                tmp_path.chmod(tmp_path.stat().st_mode | stat.S_IEXEC)

            UpdateChecker._update_path = tmp_path
            UpdateChecker._release_data = None
            return True, "Update downloaded"
        except Exception as exc:
            return False, str(exc)

    @staticmethod
    def restart_app():
        """Exit the current process and let a detached helper swap + relaunch.

        When an update was downloaded, spawn a platform-specific script that
        waits for our PID to disappear, swaps the binary, and launches the
        new exe. Uses os._exit to bypass any Qt event-loop interference.
        """
        update_path = UpdateChecker._update_path
        staged = update_path is not None and Path(update_path).exists()

        if not staged:
            # No update to apply — fall back to a plain relaunch.
            if IS_WINDOWS:
                subprocess.Popen([sys.executable] + sys.argv[1:], close_fds=True)
            else:
                os.execv(sys.executable, [sys.executable] + sys.argv)
            os._exit(0)

        current_exe = Path(sys.executable)
        old_path = current_exe.with_suffix(".old")
        pid = os.getpid()
        tmp_dir = Path(tempfile.gettempdir())

        if IS_WINDOWS:
            script = tmp_dir / f"am_update_{pid}.bat"
            log_path = tmp_dir / "am_update.log"
            script.write_text(
                "@echo off\r\n"
                f'set "LOG={log_path}"\r\n'
                'echo === am_update helper starting === > "%LOG%"\r\n'
                'echo date=%DATE% time=%TIME% >> "%LOG%"\r\n'
                f'echo pid={pid} >> "%LOG%"\r\n'
                f'echo current_exe={current_exe} >> "%LOG%"\r\n'
                f'echo update_path={update_path} >> "%LOG%"\r\n'
                f'echo old_path={old_path} >> "%LOG%"\r\n'
                'echo [waiting for pid to exit] >> "%LOG%"\r\n'
                "set /a wait_tries=0\r\n"
                ":waitpid\r\n"
                f'tasklist /FI "PID eq {pid}" 2>nul | findstr /C:"{pid}" >nul\r\n'
                "if %errorlevel% NEQ 0 goto exited\r\n"
                "set /a wait_tries+=1\r\n"
                "if %wait_tries% GEQ 30 goto force_kill\r\n"
                "ping -n 2 127.0.0.1 >nul\r\n"
                "goto waitpid\r\n"
                ":force_kill\r\n"
                f'echo [waitpid timed out after %wait_tries% iterations; force-killing pid={pid}] >> "%LOG%"\r\n'
                f'taskkill /F /PID {pid} >> "%LOG%" 2>&1\r\n'
                "ping -n 3 127.0.0.1 >nul\r\n"
                ":exited\r\n"
                'echo [pid exited, attempting swap] >> "%LOG%"\r\n'
                "set /a tries=0\r\n"
                ":tryrename\r\n"
                f'move /y "{current_exe}" "{old_path}" >> "%LOG%" 2>&1\r\n'
                "if errorlevel 1 (\r\n"
                '  echo [rename current-^>old failed, try=%tries%] >> "%LOG%"\r\n'
                "  ping -n 3 127.0.0.1 >nul\r\n"
                "  set /a tries+=1\r\n"
                "  if %tries% LSS 30 goto tryrename\r\n"
                '  echo [FAILED: could not rename current exe after 30 tries] >> "%LOG%"\r\n'
                "  exit /b 1\r\n"
                ")\r\n"
                'echo [renamed current-^>old, moving new into place] >> "%LOG%"\r\n'
                f'move /y "{update_path}" "{current_exe}" >> "%LOG%" 2>&1\r\n'
                "if errorlevel 1 (\r\n"
                '  echo [FAILED: could not move new into place; restoring backup] >> "%LOG%"\r\n'
                f'  move /y "{old_path}" "{current_exe}" >> "%LOG%" 2>&1\r\n'
                "  exit /b 1\r\n"
                ")\r\n"
                'echo [launching new exe] >> "%LOG%"\r\n'
                f'start "" "{current_exe}"\r\n'
                'echo [done] >> "%LOG%"\r\n'
                '(goto) 2>nul & del "%~f0"\r\n',
                encoding="ascii",
            )
            # CREATE_NO_WINDOW alone — DETACHED_PROCESS is for GUI children
            # and combining the two is documented as undefined; on Win11 with
            # Windows Terminal as default, the combo can show a visible
            # terminal tab. STARTUPINFO/SW_HIDE belt-and-braces.
            CREATE_NO_WINDOW = 0x08000000
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = subprocess.SW_HIDE
            subprocess.Popen(
                ["cmd", "/c", str(script)],
                creationflags=CREATE_NO_WINDOW,
                startupinfo=si,
                close_fds=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            script = tmp_dir / f"am_update_{pid}.sh"
            log_path = tmp_dir / "am_update.log"
            script.write_text(
                "#!/bin/sh\n"
                f'LOG="{log_path}"\n'
                'exec >>"$LOG" 2>&1\n'
                'echo "=== am_update helper starting ==="\n'
                'echo "date=$(date)"\n'
                f'echo "pid={pid}"\n'
                f'echo "current_exe={current_exe}"\n'
                f'echo "update_path={update_path}"\n'
                f'echo "old_path={old_path}"\n'
                "echo '[waiting for pid to exit]'\n"
                "wait_tries=0\n"
                f"while kill -0 {pid} 2>/dev/null; do\n"
                "  wait_tries=$((wait_tries + 1))\n"
                "  if [ $wait_tries -ge 120 ]; then\n"
                f"    echo \"[waitpid timed out after $wait_tries iterations; force-killing pid={pid}]\"\n"
                f"    kill -9 {pid} 2>/dev/null\n"
                "    sleep 1\n"
                "    break\n"
                "  fi\n"
                "  sleep 0.5\n"
                "done\n"
                "echo '[pid exited, attempting swap]'\n"
                f'if ! mv -f "{current_exe}" "{old_path}"; then\n'
                "  echo '[FAILED: rename current->old]'\n"
                "  exit 1\n"
                "fi\n"
                f'if ! mv -f "{update_path}" "{current_exe}"; then\n'
                "  echo '[FAILED: move new into place; restoring backup]'\n"
                f'  mv -f "{old_path}" "{current_exe}"\n'
                "  exit 1\n"
                "fi\n"
                f'chmod +x "{current_exe}"\n'
                "echo '[launching new exe]'\n"
                f'nohup "{current_exe}" >/dev/null 2>&1 &\n'
                "echo '[done]'\n"
                'rm -- "$0"\n'
            )
            script.chmod(0o755)
            subprocess.Popen(
                ["/bin/sh", str(script)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )

        os._exit(0)


class UpdateDialog(QDialog):
    """Modal dark-themed update dialog."""

    # Signals emitted from the download thread so updates land on the Qt
    # main thread via Qt's auto queued-connection semantics. Using Signal
    # is required for both progress and result — QTimer.singleShot from a
    # thread without a Qt event loop silently never fires.
    _progress = Signal(int, int)
    _result   = Signal(bool, str)

    def __init__(self, commit_hash: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{APP_NAME} — Update Available")

        source = _detect_install_source()
        managed_cmd = _MANAGED_UPGRADE_CMD.get(source)
        self.setFixedSize(420, 280 if managed_cmd else 260)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(6)

        title = QLabel("A new version of Actions Monitor is available.")
        title.setStyleSheet(f"color: {FG_TEXT}; font-size: 14px; font-weight: bold;")
        layout.addWidget(title)

        version = QLabel(f"New version: {commit_hash}")
        version.setStyleSheet(f"color: {FG_MUTED}; font-size: 12px;")
        layout.addWidget(version)

        link_url = f"{UpdateChecker.REPO_URL}/releases/tag/{commit_hash}"
        link = _ClickableLabel("View release on GitHub", url_fn=lambda: link_url)
        link.setStyleSheet(f"color: {FG_LINK}; font-size: 12px; text-decoration: underline;")
        layout.addWidget(link)

        if managed_cmd:
            mgr_label = {"scoop": "Scoop", "winget": "winget"}[source]
            instr = QLabel(f"Installed via {mgr_label}. Run this command to upgrade:")
            instr.setStyleSheet(f"color: {FG_MUTED}; font-size: 12px; margin-top: 6px;")
            layout.addWidget(instr)

            cmd_lbl = QLabel(managed_cmd)
            cmd_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            cmd_lbl.setStyleSheet(
                f"color: {FG_TEXT}; background-color: {BG_ROW}; "
                f"font-family: Consolas, 'Courier New', monospace; font-size: 12px; "
                f"padding: 6px 8px; border-radius: 3px;"
            )
            layout.addWidget(cmd_lbl)

        self._status_lbl = QLabel("")
        self._status_lbl.setStyleSheet(f"color: {FG_MUTED}; font-size: 12px;")
        layout.addWidget(self._status_lbl)

        self._progress_bar = QProgressBar()
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setFixedHeight(6)
        self._progress_bar.setStyleSheet(
            f"QProgressBar {{ background-color: {BG_ROW}; border: none; border-radius: 3px; }}"
            f"QProgressBar::chunk {{ background-color: {FG_LINK}; border-radius: 3px; }}"
        )
        self._progress_bar.hide()
        layout.addWidget(self._progress_bar)
        self._progress.connect(self._on_progress)
        self._result.connect(self._on_result)

        layout.addStretch()

        btn_layout = QHBoxLayout()
        if managed_cmd:
            self._copy_btn = QPushButton("Copy command")
            self._copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self._copy_btn.clicked.connect(lambda: self._copy_cmd(managed_cmd))
            btn_layout.addWidget(self._copy_btn)

            self._close_btn = QPushButton("Close")
            self._close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self._close_btn.clicked.connect(self.reject)
            btn_layout.addWidget(self._close_btn)
        else:
            self._update_btn = QPushButton("Update")
            self._update_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self._update_btn.clicked.connect(self._do_update)
            btn_layout.addWidget(self._update_btn)

            self._skip_btn = QPushButton("Skip")
            self._skip_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self._skip_btn.clicked.connect(self.reject)
            btn_layout.addWidget(self._skip_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

    def _copy_cmd(self, cmd: str):
        QApplication.clipboard().setText(cmd)
        self._status_lbl.setText("Copied to clipboard.")
        self._status_lbl.setStyleSheet(f"color: {COLOUR[ST_SUCCESS]}; font-size: 12px;")

    def _do_update(self):
        self._update_btn.setEnabled(False)
        self._skip_btn.setEnabled(False)
        self._status_lbl.setText("Downloading…")
        self._status_lbl.setStyleSheet(f"color: {FG_TEXT}; font-size: 12px;")
        self._progress_bar.setRange(0, 0)  # indeterminate until first chunk
        self._progress_bar.show()

        def _run():
            ok, msg = UpdateChecker.apply_update(progress_cb=self._progress.emit)
            self._result.emit(ok, msg)

        threading.Thread(target=_run, daemon=True).start()

    def _on_progress(self, bytes_written: int, expected_size: int):
        if expected_size > 0:
            if self._progress_bar.maximum() == 0:
                self._progress_bar.setRange(0, expected_size)
            self._progress_bar.setValue(bytes_written)
            mb_done = bytes_written / (1024 * 1024)
            mb_total = expected_size / (1024 * 1024)
            pct = int(bytes_written * 100 / expected_size) if expected_size else 0
            self._status_lbl.setText(f"Downloading… {mb_done:.1f} / {mb_total:.1f} MB ({pct}%)")
        else:
            mb_done = bytes_written / (1024 * 1024)
            self._status_lbl.setText(f"Downloading… {mb_done:.1f} MB")

    def _on_result(self, ok, msg):
        if ok:
            self._progress_bar.setRange(0, 1)
            self._progress_bar.setValue(1)
            self._status_lbl.setText("Update complete — restarting...")
            self._status_lbl.setStyleSheet(f"color: {COLOUR[ST_SUCCESS]}; font-size: 12px;")
            QTimer.singleShot(500, UpdateChecker.restart_app)
        else:
            self._progress_bar.hide()
            self._status_lbl.setText(f"Update failed: {msg}")
            self._status_lbl.setStyleSheet(f"color: {COLOUR[ST_FAILURE]}; font-size: 12px;")
            self._skip_btn.setEnabled(True)


# ---------------------------------------------------------------------------
# Window state persistence
# ---------------------------------------------------------------------------
if IS_WINDOWS:
    class _MONITORINFO(ctypes.Structure):
        """Win32 MONITORINFO struct for multi-monitor work area detection."""
        _fields_ = [
            ("cbSize", ctypes.wintypes.DWORD),
            ("rcMonitor", ctypes.wintypes.RECT),
            ("rcWork", ctypes.wintypes.RECT),
            ("dwFlags", ctypes.wintypes.DWORD),
        ]


def _get_monitor_work_areas() -> list[tuple[int, int, int, int]]:
    """Return list of (left, top, right, bottom) work areas for all monitors.
    Uses Win32 API on Windows, Qt screens elsewhere."""
    areas: list[tuple[int, int, int, int]] = []
    if IS_WINDOWS:
        try:
            monitor_enum_proc = ctypes.WINFUNCTYPE(
                ctypes.c_int,
                ctypes.c_ulong, ctypes.c_ulong, ctypes.POINTER(ctypes.wintypes.RECT), ctypes.c_double,
            )

            def callback(hmonitor, hdc, lprect, lparam):
                mi = _MONITORINFO()
                mi.cbSize = ctypes.sizeof(_MONITORINFO)
                if ctypes.windll.user32.GetMonitorInfoW(hmonitor, ctypes.byref(mi)):
                    rc = mi.rcWork
                    areas.append((rc.left, rc.top, rc.right, rc.bottom))
                return 1  # continue enumeration

            ctypes.windll.user32.EnumDisplayMonitors(
                None, None, monitor_enum_proc(callback), 0,
            )
        except Exception:
            pass
    if not areas:
        # Qt fallback — works on all platforms (Linux, macOS, Windows without ctypes)
        try:
            app = QApplication.instance()
            if app:
                for screen in app.screens():
                    g = screen.availableGeometry()
                    areas.append((g.x(), g.y(), g.x() + g.width(), g.y() + g.height()))
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
# Global dark stylesheet
# ---------------------------------------------------------------------------
DARK_STYLESHEET = f"""
    * {{ font-family: '{UI_FONT}'; }}
    QMainWindow, QWidget {{ background-color: {BG_DARK}; color: {FG_TEXT}; }}
    QScrollArea {{ border: none; background-color: {BG_DARK}; }}
    QScrollBar:vertical {{
        background: {BG_DARK}; width: 10px; border: none; margin: 0;
    }}
    QScrollBar::handle:vertical {{
        background: {BG_ROW}; min-height: 30px; border-radius: 5px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {FG_MUTED}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
    QCheckBox {{ color: {FG_MUTED}; font-size: 11px; spacing: 6px; }}
    QCheckBox::indicator {{
        width: 14px; height: 14px;
        border: 1px solid #57534E;
        border-radius: 3px;
        background-color: {BG_DARK};
    }}
    QCheckBox::indicator:hover {{ border-color: {FG_LINK}; }}
    QCheckBox::indicator:checked {{
        background-color: {FG_LINK};
        border-color: {FG_LINK};
        image: url({_CHECK_PNG_URL});
    }}
    QCheckBox::indicator:checked:hover {{ background-color: #F59E0B; border-color: #F59E0B; }}
    QToolTip {{
        background-color: #292524; color: {FG_TEXT}; border: 1px solid #44403C;
        font-size: 11px; padding: 4px 6px;
    }}
    QPushButton {{
        background-color: {ACCENT}; color: {FG_TEXT}; border: none;
        padding: 4px 16px; font-size: 13px;
    }}
    QPushButton:hover {{ background-color: {BG_ROW}; }}
    QPushButton:disabled {{ color: {FG_MUTED}; }}
    QMenu {{
        background-color: {BG_ROW}; color: {FG_TEXT}; border: 1px solid #44403C;
        font-size: 12px; padding: 4px 0;
    }}
    QMenu::item {{ padding: 4px 20px; }}
    QMenu::item:selected {{ background-color: #4A3728; }}
"""


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self, config_mgr: ConfigManager, event_queue: queue.Queue):
        super().__init__()
        self._config_mgr = config_mgr
        self._event_queue = event_queue
        self._pollers: dict[int, WorkflowPoller] = {}
        self._states: dict[tuple[int, Optional[str]], WorkflowState] = {}
        self._rows: dict[tuple[int, Optional[str]], WorkflowRow] = {}
        self._snoozed: set[tuple[int, Optional[str]]] = set()
        # Stable identifier per workflow (mode:url or mode:query) — survives wid shifts on reload
        self._wid_stable_keys: dict[int, str] = {}
        self._tray: Optional[QSystemTrayIcon] = None
        self._tray_icons: dict[str, QIcon] = {}
        self._prev_tray_status: Optional[str] = None
        self._sections: list[QWidget] = []
        self._wid_container: dict[int, QWidget] = {}
        self._section_content: dict[str, QWidget] = {}
        self._section_content_layout: dict[str, QVBoxLayout] = {}
        # Reverse lookup: id(content_widget) → section title. Avoids O(n) scans in _apply_event.
        self._container_to_title: dict[int, str] = {}
        self._section_indicators: dict[str, QLabel] = {}
        self._collapsed: dict[str, bool] = {}
        self._section_sort: dict[str, Optional[str]] = {}
        self._sort_labels: dict[str, dict[str, QLabel]] = {}

        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(400, 200)
        self.resize(560, 420)

        _generate_app_ico()
        try:
            icon_pixmaps = [_pil_to_qpixmap(_make_base_icon(s)) for s in (256, 64, 48, 32, 16)]
            app_icon = QIcon()
            for pm in icon_pixmaps:
                app_icon.addPixmap(pm)
            self.setWindowIcon(app_icon)
        except Exception:
            pass

        _init_status_icons()
        _init_snooze_icons()

        self._restore_all_state()
        self._build_ui()
        self._setup_tray()

        # Shared context menu
        self._ctx_menu = QMenu(self)
        self._ctx_menu_target: Optional[tuple[int, Optional[str]]] = None
        self._ctx_snooze_action = self._ctx_menu.addAction("Snooze")
        self._ctx_snooze_action.triggered.connect(
            lambda: self._toggle_snooze(self._ctx_menu_target) if self._ctx_menu_target else None)

        self._start_pollers()
        self._restore_snoozed_state()

        # Timers
        self._drain_timer = QTimer(self)
        self._drain_timer.timeout.connect(self._drain_queue)
        self._drain_timer.start(500)

        self._config_timer = QTimer(self)
        self._config_timer.timeout.connect(self._watch_config)
        self._config_timer.start(5000)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Header
        header = QWidget()
        header.setFixedHeight(54)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(14, 0, 14, 0)

        # WizX20 logo — full bolt+wordmark at 40px in 54px header (~7px
        # padding top/bottom so the bolt tips align with the title text)
        logo_data = base64.b64decode(_WIZX20_LOGO_B64)
        logo_img = Image.open(io.BytesIO(logo_data))
        scale = 40 / logo_img.height
        logo_img = logo_img.resize((round(logo_img.width * scale), 40), Image.LANCZOS)
        logo_lbl = _ClickableLabel(url_fn=lambda: "https://github.com/WizX20")
        logo_lbl.setPixmap(_pil_to_qpixmap(logo_img))
        logo_lbl.setToolTip("github.com/WizX20")
        header_layout.addWidget(logo_lbl)

        title_lbl = QLabel(APP_NAME)
        title_lbl.setStyleSheet(f"color: {FG_TEXT}; font-size: 15px;")
        title_lbl.setContentsMargins(10, 0, 16, 0)
        header_layout.addWidget(title_lbl)
        header_layout.addStretch()

        def _mk_icon_btn(pm: QPixmap, tooltip: str, handler) -> QLabel:
            pm.setDevicePixelRatio(2.0)
            btn = QLabel()
            btn.setPixmap(pm)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip(tooltip)
            btn.setStyleSheet("background: transparent; padding: 0; margin: 0;")
            btn.mousePressEvent = lambda e: handler()
            return btn

        help_btn = _mk_icon_btn(
            _pil_to_qpixmap(_make_help_icon(48)),
            "Open README on GitHub",
            lambda: webbrowser.open(f"{UpdateChecker.REPO_URL}/blob/main/README.md"),
        )
        header_layout.addWidget(help_btn)
        header_layout.addSpacing(8)

        update_btn = _mk_icon_btn(
            _pil_to_qpixmap(_make_update_icon(48)),
            "Check for updates",
            lambda: self._check_for_updates(manual=True),
        )
        header_layout.addWidget(update_btn)
        header_layout.addSpacing(8)

        refresh_btn = _mk_icon_btn(
            _pil_to_qpixmap(_make_refresh_icon(48)),
            "Refresh all workflows",
            self._refresh_all,
        )
        header_layout.addWidget(refresh_btn)

        main_layout.addWidget(header)

        # Separator
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background-color: #44403C;")
        main_layout.addWidget(sep)

        # Column headers
        col_hdr = QWidget()
        col_hdr_layout = QHBoxLayout(col_hdr)
        col_hdr_layout.setContentsMargins(14, 6, 14, 2)
        lbl_status = QLabel("STATUS / WORKFLOW")
        lbl_status.setStyleSheet(f"color: {FG_MUTED}; font-size: 9px; font-weight: bold;")
        col_hdr_layout.addWidget(lbl_status, 1)
        lbl_poll = QLabel("POLL")
        lbl_poll.setStyleSheet(f"color: {FG_MUTED}; font-size: 9px; font-weight: bold;")
        lbl_poll.setAlignment(Qt.AlignmentFlag.AlignRight)
        col_hdr_layout.addWidget(lbl_poll)
        main_layout.addWidget(col_hdr)

        # Scrollable list
        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll_content = QWidget()
        self._scroll_layout = QVBoxLayout(self._scroll_content)
        self._scroll_layout.setContentsMargins(8, 0, 8, 8)
        self._scroll_layout.setSpacing(0)
        self._scroll_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._scroll_area.setWidget(self._scroll_content)
        main_layout.addWidget(self._scroll_area, 1)

        # Footer
        footer = QWidget()
        footer.setStyleSheet(f"background-color: {ACCENT};")
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(0, 0, 0, 0)
        footer_layout.setSpacing(0)

        footer_sep = QFrame()
        footer_sep.setFixedHeight(1)
        footer_sep.setStyleSheet("background-color: #44403C;")
        footer_layout.addWidget(footer_sep)

        # Footer row 1 — checkboxes
        row1 = QWidget()
        row1_layout = QHBoxLayout(row1)
        row1_layout.setContentsMargins(14, 14, 14, 6)
        row1_layout.setSpacing(18)

        state = self._load_state()

        if IS_WINDOWS:
            self._startup_cb = QCheckBox("Start with Windows")
            self._startup_cb.setChecked(StartupManager.is_enabled())
            self._startup_cb.toggled.connect(self._toggle_startup)
            row1_layout.addWidget(self._startup_cb)

        self._min_tray_cb = QCheckBox("Minimize to tray on close")
        self._min_tray_cb.setChecked(state.get("minimize_to_tray", True))
        self._min_tray_cb.toggled.connect(self._toggle_minimize_to_tray)
        row1_layout.addWidget(self._min_tray_cb)

        self._aot_cb = QCheckBox("Always on top")
        self._aot_cb.setChecked(state.get("always_on_top", False))
        self._aot_cb.toggled.connect(self._toggle_always_on_top)
        row1_layout.addWidget(self._aot_cb)

        row1_layout.addStretch()
        footer_layout.addWidget(row1)

        # Footer row 2 — config hint + link
        row2 = QWidget()
        row2_layout = QHBoxLayout(row2)
        row2_layout.setContentsMargins(14, 6, 14, 10)
        hint = QLabel("Edit config.yaml to add/change workflows.")
        hint.setStyleSheet(f"color: {FG_MUTED}; font-size: 11px;")
        row2_layout.addWidget(hint)
        row2_layout.addStretch()
        open_btn = _ClickableLabel("Open config ↗", url_fn=lambda: None)
        open_btn.setStyleSheet(f"color: {FG_LINK}; font-size: 11px; font-weight: bold;")
        open_btn.mousePressEvent = lambda e: ConfigManager.open_in_editor()
        row2_layout.addWidget(open_btn)
        footer_layout.addWidget(row2)

        main_layout.addWidget(footer)

    # ------------------------------------------------------------------
    # System tray
    # ------------------------------------------------------------------
    def _setup_tray(self):
        try:
            # Render at 32 so the simplified chevron path renders crisply when
            # Windows scales down to 16/24px in the tray.
            self._tray_icons = {
                s: QIcon(_pil_to_qpixmap(_make_icon_image(c, 32))) for s, c in COLOUR.items()
            }
            self._tray = QSystemTrayIcon(self._tray_icons[ST_UNKNOWN], self)
            tray_menu = QMenu()
            tray_menu.addAction("Show", self._show_window)
            tray_menu.addSeparator()
            tray_menu.addAction("Close", self._quit)
            self._tray.setContextMenu(tray_menu)
            self._tray.activated.connect(self._on_tray_activated)
            self._tray.setToolTip(APP_NAME)
            self._tray.show()
        except Exception as exc:
            print(f"[Tray] Failed to start tray icon: {exc}")
            self._tray = None

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._show_window()

    def _update_tray(self):
        if not self._tray:
            return
        unsnoozed = [s for k, s in self._states.items() if k not in self._snoozed]
        combined = _combined_status(unsnoozed)
        if combined == self._prev_tray_status:
            return
        self._prev_tray_status = combined
        self._tray.setIcon(self._tray_icons.get(combined, self._tray_icons[ST_UNKNOWN]))
        self._tray.setToolTip(f"{APP_NAME} — {combined.replace('_', ' ').title()}")

    # ------------------------------------------------------------------
    # Startup toggle
    # ------------------------------------------------------------------
    def _toggle_startup(self, checked: bool):
        if checked:
            StartupManager.enable()
        else:
            StartupManager.disable()

    # ------------------------------------------------------------------
    # Always on top
    # ------------------------------------------------------------------
    def _toggle_always_on_top(self, on_top: bool):
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, on_top)
        self.show()  # re-show after flag change
        try:
            state = self._load_state()
            state["always_on_top"] = on_top
            self._write_state(state)
        except Exception:
            pass

    def _toggle_minimize_to_tray(self, enabled: bool):
        try:
            state = self._load_state()
            state["minimize_to_tray"] = enabled
            self._write_state(state)
        except Exception:
            pass

    def _restore_all_state(self):
        try:
            state = self._load_state()
        except Exception:
            return
        for title in state.get("collapsed_sections", []):
            self._collapsed[title] = True
        on_top = state.get("always_on_top", False)
        if on_top:
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        win = state.get("window")
        if not win:
            return
        try:
            x = int(win["x"])
            y = int(win["y"])
            w = max(int(win["width"]), 400)
            h = max(int(win["height"]), 200)
            areas = _get_monitor_work_areas()
            if areas and not _rect_overlaps(x, y, w, h, areas):
                self.resize(w, h)
                return
            if not areas:
                screen = QApplication.primaryScreen()
                if screen:
                    sg = screen.geometry()
                    if x + w < 100 or x > sg.width() - 100 or y + h < 50 or y > sg.height() - 50:
                        self.resize(w, h)
                        return
            self.resize(w, h)
            self.move(x, y)
        except Exception as exc:
            print(f"[State] Restore error: {exc}")

    # ------------------------------------------------------------------
    # Sections
    # ------------------------------------------------------------------
    def _create_section(self, title: str) -> QWidget:
        section = QWidget()
        section.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        section_layout = QVBoxLayout(section)
        section_layout.setContentsMargins(0, 0, 0, 0)
        section_layout.setSpacing(0)
        self._scroll_layout.addWidget(section)
        self._sections.append(section)

        is_collapsed = self._collapsed.get(title, False)

        # Header
        hdr = QWidget()
        hdr.setCursor(Qt.CursorShape.PointingHandCursor)
        hdr_layout = QHBoxLayout(hdr)
        hdr_layout.setContentsMargins(12, 10, 0, 4)

        indicator = QLabel("▸" if is_collapsed else "▾")
        indicator.setStyleSheet(f"color: {FG_LINK}; font-size: 12px; font-weight: bold;")
        hdr_layout.addWidget(indicator)
        self._section_indicators[title] = indicator

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(f"color: {FG_LINK}; font-size: 12px; font-weight: bold;")
        hdr_layout.addWidget(title_lbl)

        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background-color: #44403C;")
        sep.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        hdr_layout.addWidget(sep, 1)

        hdr.mousePressEvent = lambda e, t=title: self._toggle_section(t)
        section_layout.addWidget(hdr)

        # Content container
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Sort bar
        sort_bar = QWidget()
        sort_bar.setStyleSheet(f"background-color: {BG_ROW};")
        sort_layout = QHBoxLayout(sort_bar)
        sort_layout.setContentsMargins(4, 0, 4, 0)
        sort_layout.setSpacing(0)

        sort_lbl = QLabel("SORT:")
        sort_lbl.setStyleSheet(f"color: {FG_TEXT}; font-size: 11px; font-weight: bold; padding: 3px 6px;")
        sort_layout.addWidget(sort_lbl)

        labels: dict[str, QLabel] = {}
        for sk in ("status", "updated", "created"):
            lbl = QLabel(f"{sk.capitalize()} ·")
            lbl.setStyleSheet(f"color: {FG_MUTED}; font-size: 11px; padding: 3px 6px;")
            lbl.setCursor(Qt.CursorShape.PointingHandCursor)
            lbl.mousePressEvent = lambda e, t=title, k=sk: self._cycle_sort(t, k)
            sort_layout.addWidget(lbl)
            labels[sk] = lbl
        self._sort_labels[title] = labels

        sort_layout.addStretch()

        clear_lbl = QLabel("✕")
        clear_lbl.setStyleSheet(f"color: {FG_MUTED}; font-size: 11px; padding: 3px 8px;")
        clear_lbl.setCursor(Qt.CursorShape.PointingHandCursor)
        clear_lbl.mousePressEvent = lambda e, t=title: self._clear_sort(t)
        sort_layout.addWidget(clear_lbl)

        content_layout.addWidget(sort_bar)

        content.setVisible(not is_collapsed)
        self._section_content[title] = content
        self._section_content_layout[title] = content_layout
        self._container_to_title[id(content)] = title
        section_layout.addWidget(content)

        return content

    def _toggle_section(self, title: str):
        is_collapsed = not self._collapsed.get(title, False)
        self._collapsed[title] = is_collapsed
        content = self._section_content.get(title)
        indicator = self._section_indicators.get(title)
        if content:
            content.setVisible(not is_collapsed)
        if indicator:
            indicator.setText("▸" if is_collapsed else "▾")
        self._save_collapse_state()

    def _save_collapse_state(self):
        try:
            state = self._load_state()
            self._persist_collapsed(state)
            self._write_state(state)
        except Exception:
            pass

    def _save_snoozed_state(self):
        try:
            state = self._load_state()
            self._persist_snoozed(state)
            self._write_state(state)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Section sorting
    # ------------------------------------------------------------------
    def _cycle_sort(self, title: str, sort_key: str):
        current = self._section_sort.get(title)
        prefix = f"{sort_key}_"
        if current == f"{prefix}asc":
            new_sort = f"{prefix}desc"
        elif current == f"{prefix}desc":
            new_sort = None
        elif current is None or not current.startswith(prefix):
            new_sort = f"{prefix}asc"
        else:
            new_sort = None

        prev_sorted_titles = [t for t, s in self._section_sort.items() if s is not None and t != title]
        for t in self._section_sort:
            self._section_sort[t] = None
        self._section_sort[title] = new_sort
        self._update_sort_labels()
        self._sort_section(title)
        for t in prev_sorted_titles:
            self._sort_section(t)
        self._save_sort_state()

    def _sort_section(self, title: str):
        content = self._section_content.get(title)
        content_layout = self._section_content_layout.get(title)
        if not content or not content_layout:
            return
        sort_mode = self._section_sort.get(title)

        section_rows: list[tuple[tuple[int, Optional[str]], WorkflowRow]] = []
        for key, row in self._rows.items():
            wid = key[0]
            if self._wid_container.get(wid) is content:
                section_rows.append((key, row))

        if not section_rows:
            return

        if sort_mode == "status_asc":
            section_rows.sort(key=lambda kr: _STATUS_PRIORITY.get(
                self._states.get(kr[0], WorkflowState(name="", url="", branch=None)).status, 0), reverse=True)
        elif sort_mode == "status_desc":
            section_rows.sort(key=lambda kr: _STATUS_PRIORITY.get(
                self._states.get(kr[0], WorkflowState(name="", url="", branch=None)).status, 0))
        elif sort_mode in ("updated_asc", "updated_desc"):
            def _updated_key(kr):
                s = self._states.get(kr[0])
                return (s.run_updated_at or s.started_at or "") if s else ""
            section_rows.sort(key=_updated_key, reverse=(sort_mode == "updated_asc"))
        elif sort_mode in ("created_asc", "created_desc"):
            def _created_key(kr):
                s = self._states.get(kr[0])
                return (s.started_at or "") if s else ""
            section_rows.sort(key=_created_key, reverse=(sort_mode == "created_asc"))
        else:
            section_rows.sort(key=lambda kr: (kr[0][0], kr[0][1] or ""))

        # Remove rows from layout (skip sort bar at index 0)
        for _key, row in section_rows:
            content_layout.removeWidget(row)
        # Re-add in sorted order
        for i, (_key, row) in enumerate(section_rows):
            content_layout.addWidget(row)
            bg = BG_ROW_ALT if i % 2 == 1 else BG_ROW
            row._bg = bg
            row._apply_background()

    def _update_sort_labels(self):
        _ARROWS = {"asc": "▲", "desc": "▼"}
        for title, labels in self._sort_labels.items():
            current = self._section_sort.get(title)
            for sk, lbl in labels.items():
                if current and current.startswith(f"{sk}_"):
                    direction = current.split("_", 1)[1]
                    lbl.setText(f"{sk.capitalize()} {_ARROWS[direction]}")
                    lbl.setStyleSheet(f"color: {FG_LINK}; font-size: 11px; padding: 3px 6px;")
                else:
                    lbl.setText(f"{sk.capitalize()} ·")
                    lbl.setStyleSheet(f"color: {FG_MUTED}; font-size: 11px; padding: 3px 6px;")

    def _clear_sort(self, title: str):
        if not self._section_sort.get(title):
            return
        self._section_sort[title] = None
        self._update_sort_labels()
        self._sort_section(title)
        self._save_sort_state()

    def _save_sort_state(self):
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
        state = self._load_state()
        for title, sort_mode in state.get("section_sort", {}).items():
            self._section_sort[title] = sort_mode
        self._update_sort_labels()

    def _restore_snoozed_state(self):
        """Rebuild self._snoozed + _snoozed_keys from state.json using stable workflow keys.
        Must run after self._wid_stable_keys is populated. Branch-mode rows that already exist
        get set_snoozed(True); dynamic rows pick it up when created via _drain_queue."""
        state = self._load_state()
        snoozed_cfg = state.get("snoozed") or {}
        if not snoozed_cfg:
            return
        stable_to_wid = {sk: wid for wid, sk in self._wid_stable_keys.items()}
        with _snoozed_lock:
            for sk, sub_keys in snoozed_cfg.items():
                wid = stable_to_wid.get(sk)
                if wid is None:
                    continue
                for sub_key in sub_keys:
                    key = (wid, sub_key)
                    self._snoozed.add(key)
                    _snoozed_keys.add(key)
        for key in self._snoozed:
            row = self._rows.get(key)
            if row:
                row.set_snoozed(True)

    def _resort_section_for_wid(self, wid: int):
        container = self._wid_container.get(wid)
        if not container:
            return
        for title, content in self._section_content.items():
            if content is container and self._section_sort.get(title):
                self._sort_section(title)
                break

    @staticmethod
    def _sort_key_changed(prev, new, sort_mode: Optional[str]) -> bool:
        """Return True when the field backing `sort_mode` differs between states.

        Skips expensive re-sorts on polls where nothing sort-relevant moved
        (most common case: a row already-green stays green across polls).
        """
        if not sort_mode or prev is None or new is None:
            return True
        if sort_mode.startswith("status_"):
            return prev.status != new.status
        if sort_mode.startswith("updated_"):
            pk = (prev.run_updated_at or prev.started_at or "")
            nk = (new.run_updated_at  or new.started_at  or "")
            return pk != nk
        if sort_mode.startswith("created_"):
            return (prev.started_at or "") != (new.started_at or "")
        return True

    def _maybe_resort_section_for_wid(self, wid: int, prev, new):
        container = self._wid_container.get(wid)
        if not container:
            return
        for title, content in self._section_content.items():
            if content is container:
                mode = self._section_sort.get(title)
                if mode and self._sort_key_changed(prev, new, mode):
                    self._sort_section(title)
                break

    def _destroy_sections(self):
        for sec in self._sections:
            sec.setParent(None)
            sec.deleteLater()
        self._sections.clear()
        self._wid_container.clear()
        self._section_content.clear()
        self._section_content_layout.clear()
        self._container_to_title.clear()
        self._section_indicators.clear()
        self._sort_labels.clear()

    # ------------------------------------------------------------------
    # Pollers
    # ------------------------------------------------------------------
    @staticmethod
    def _workflow_stable_key(entry: dict) -> str:
        """Identifier stable across wid shifts. Used to persist per-row state."""
        mode = entry.get("mode", "branch")
        if mode == "url":
            ident = entry.get("query") or ""
        else:
            ident = entry.get("url") or ""
        return f"{mode}:{ident}"

    def _start_pollers(self):
        cfg = self._config_mgr.get()
        notif_cfg = cfg.get("notifications", {})
        NOTIF.set_batch_window(float(notif_cfg.get("batch_window", 1)))
        NOTIF.set_duration(str(notif_cfg.get("duration", "short")))
        workflows = cfg.get("workflows") or []

        self._wid_stable_keys = {
            wid: self._workflow_stable_key(entry)
            for wid, entry in enumerate(workflows)
        }

        branch_container = None
        _DEFAULT_SECTION_TITLES = {
            "pr":    "PR Workflows",
            "actor": "My Runs",
            "url":   "URL Search",
        }
        for wid, entry in enumerate(workflows):
            mode = entry.get("mode", "branch")
            if mode in ("pr", "actor", "url"):
                name = entry.get("name") or entry.get("url") or _DEFAULT_SECTION_TITLES.get(mode, "Section")
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

        container = self._wid_container.get(wid, self._scroll_content)

        if mode == "pr":
            poller = PRWorkflowPoller(wid, entry, self._config_mgr, self._event_queue)
        elif mode == "actor":
            poller = ActorWorkflowPoller(wid, entry, self._config_mgr, self._event_queue)
        elif mode == "url":
            poller = URLQueryPoller(wid, entry, self._config_mgr, self._event_queue)
        else:
            branch = entry.get("branch") or url_branch
            name = entry.get("name") or wf_file or url
            state = WorkflowState(name=name, url=url, branch=branch)
            key = (wid, None)
            self._states[key] = state

            alt = len(self._rows) % 2 == 1
            jira_url = cfg.get("jira_base_url", "")
            content_layout = self._section_content_layout.get(
                self._container_to_title.get(id(container), ""))
            row = WorkflowRow(None, wid, state, alt, jira_base_url=jira_url,
                              sub_key=None, snooze_cb=self._show_row_ctx_menu)
            if content_layout:
                content_layout.addWidget(row)
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
        # Stagger wakes so N pollers don't fire a synchronized request burst.
        for i, p in enumerate(self._pollers.values()):
            QTimer.singleShot(i * 75, p.trigger_poll)

    def _check_for_updates(self, manual: bool = False):
        if not getattr(sys, "frozen", False):
            if manual:
                QMessageBox.information(
                    self, "Updates",
                    "Updates are only available in packaged builds.\n\n"
                    "Source installs: run `git pull` in the repo.",
                )
            return
        new_version = UpdateChecker.check()
        if new_version:
            UpdateDialog(new_version, parent=self).exec()
        elif manual:
            QMessageBox.information(
                self, "Up to date",
                f"You're on the latest version ({BUILD_COMMIT}).",
            )

    # ------------------------------------------------------------------
    # Queue drain
    # ------------------------------------------------------------------
    def _drain_queue(self):
        try:
            while True:
                event: StatusEvent = self._event_queue.get_nowait()
                self._apply_event(event)
        except queue.Empty:
            pass
        self._check_focus_signal()

    def _apply_event(self, event: StatusEvent):
        key = (event.workflow_id, event.sub_key)
        cfg = self._config_mgr.get()
        workflows = cfg.get("workflows") or []
        entry = workflows[event.workflow_id] if event.workflow_id < len(workflows) else {}
        poll_rate = int(entry.get("polling_rate", POLL_DEFAULT))
        jira_url = cfg.get("jira_base_url", "")

        if event.removed:
            row = self._rows.pop(key, None)
            if row:
                row.setParent(None)
                row.deleteLater()
            self._states.pop(key, None)
            self._unsnooze(key)
            self._restripe_rows()
            self._resort_section_for_wid(event.workflow_id)
        else:
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
                # Only re-sort when the active sort's backing field changed.
                self._maybe_resort_section_for_wid(event.workflow_id, prev, event.new_state)
            elif event.sub_key is not None:
                container = self._wid_container.get(event.workflow_id, self._scroll_content)
                content_layout = self._section_content_layout.get(
                    self._container_to_title.get(id(container), ""))
                alt = len(self._rows) % 2 == 1
                new_row = WorkflowRow(None, event.workflow_id, event.new_state, alt,
                                      jira_base_url=jira_url, sub_key=event.sub_key,
                                      snooze_cb=self._show_row_ctx_menu)
                if content_layout:
                    content_layout.addWidget(new_row)
                new_row.update(event.new_state, poll_rate, jira_base_url=jira_url)
                if key in self._snoozed:
                    new_row.set_snoozed(True)
                self._rows[key] = new_row
                # New row needs placement — unconditional resort.
                self._resort_section_for_wid(event.workflow_id)

        self._update_tray()

    def _show_row_ctx_menu(self, key: tuple[int, Optional[str]], event):
        if event is None:
            self._toggle_snooze(key)
            return
        self._ctx_menu_target = key
        label = "Unsnooze" if key in self._snoozed else "Snooze"
        self._ctx_snooze_action.setText(label)
        if isinstance(event, QPoint):
            self._ctx_menu.popup(event)
        else:
            self._ctx_menu.popup(QCursor.pos())

    def _toggle_snooze(self, key: tuple[int, Optional[str]]):
        if key in self._snoozed:
            self._unsnooze(key)
        else:
            self._snoozed.add(key)
            with _snoozed_lock:
                _snoozed_keys.add(key)
        row = self._rows.get(key)
        if row:
            row.set_snoozed(key in self._snoozed)
        self._update_tray()
        self._save_snoozed_state()

    def _unsnooze(self, key: tuple[int, Optional[str]]):
        self._snoozed.discard(key)
        with _snoozed_lock:
            _snoozed_keys.discard(key)
        # Wake the poller so the row refreshes immediately instead of waiting for next cycle
        poller = self._pollers.get(key[0])
        if poller:
            poller.trigger_poll()

    def _restripe_rows(self):
        section_rows: dict[int, list[WorkflowRow]] = {}
        for (wid, _sub), row in self._rows.items():
            cid = id(self._wid_container.get(wid, self._scroll_content))
            section_rows.setdefault(cid, []).append(row)
        for rows in section_rows.values():
            for i, row in enumerate(rows):
                bg = BG_ROW_ALT if i % 2 == 1 else BG_ROW
                row._bg = bg
                row._apply_background()

    # ------------------------------------------------------------------
    # Config hot-reload
    # ------------------------------------------------------------------
    def _watch_config(self):
        changed = self._config_mgr.load()
        if changed:
            self._reload_pollers()

    def _reload_pollers(self):
        global _cached_github_username
        # Snapshot snooze state by stable workflow key so wid shifts across edits don't break it
        saved_by_stable: list[tuple[str, Optional[str]]] = []
        for wid, sub_key in self._snoozed:
            sk = self._wid_stable_keys.get(wid)
            if sk:
                saved_by_stable.append((sk, sub_key))
        self._stop_all_pollers()
        # Drain any in-flight events from the old pollers — they reference stale wids
        # which would race with the new poller set and could cause KeyErrors.
        try:
            while True:
                self._event_queue.get_nowait()
        except queue.Empty:
            pass
        self._rows.clear()
        self._states.clear()
        self._snoozed.clear()
        with _snoozed_lock:
            _snoozed_keys.clear()
        self._destroy_sections()
        with _github_username_lock:
            _cached_github_username = None
        self._start_pollers()
        # Restore snooze state using new wid mapping
        stable_to_wid = {sk: wid for wid, sk in self._wid_stable_keys.items()}
        with _snoozed_lock:
            for sk, sub_key in saved_by_stable:
                wid = stable_to_wid.get(sk)
                if wid is None:
                    continue
                key = (wid, sub_key)
                self._snoozed.add(key)
                _snoozed_keys.add(key)

    # ------------------------------------------------------------------
    # Window state persistence
    # ------------------------------------------------------------------
    @staticmethod
    def _load_state() -> dict:
        if not STATE_FILE.exists():
            return {}
        try:
            with open(STATE_FILE, encoding="utf-8") as fh:
                content = fh.read().strip()
            return json.loads(content) if content else {}
        except (json.JSONDecodeError, OSError):
            return {}

    @staticmethod
    def _write_state(state: dict):
        with open(STATE_FILE, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2)

    def _persist_collapsed(self, state: dict):
        collapsed = [t for t, c in self._collapsed.items() if c]
        if collapsed:
            state["collapsed_sections"] = collapsed
        else:
            state.pop("collapsed_sections", None)

    def _persist_snoozed(self, state: dict):
        grouped: dict[str, list] = {}
        for wid, sub_key in self._snoozed:
            sk = self._wid_stable_keys.get(wid)
            if not sk:
                continue
            grouped.setdefault(sk, []).append(sub_key)
        if grouped:
            state["snoozed"] = grouped
        else:
            state.pop("snoozed", None)

    def _save_window_state(self):
        try:
            state = self._load_state()
            pos = self.pos()
            size = self.size()
            state["window"] = {
                "x": pos.x(), "y": pos.y(),
                "width": size.width(), "height": size.height(),
            }
            self._persist_collapsed(state)
            self._persist_snoozed(state)
            sorts = {t: s for t, s in self._section_sort.items() if s is not None}
            if sorts:
                state["section_sort"] = sorts
            else:
                state.pop("section_sort", None)
            self._write_state(state)
        except Exception as exc:
            print(f"[State] Save error: {exc}")

    # ------------------------------------------------------------------
    # Window / tray behaviour
    # ------------------------------------------------------------------
    def _hide_window(self):
        if self._tray:
            self.hide()
        else:
            self.showMinimized()

    def _show_window(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event):
        minimize = True
        if hasattr(self, "_min_tray_cb"):
            minimize = self._min_tray_cb.isChecked()
        if minimize and self._tray:
            event.ignore()
            self._hide_window()
        else:
            event.accept()
            self._quit()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            if self.windowState() & Qt.WindowState.WindowMinimized and self._tray:
                QTimer.singleShot(0, self.hide)

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
    _BLINK_STEPS = 6
    _BLINK_MS = 150

    def _blink_row(self, row: WorkflowRow, remaining: int = _BLINK_STEPS):
        if remaining <= 0:
            row._bg = row._bg  # restore
            row._apply_background()
            return
        color = self._BLINK_COLOR if remaining % 2 == 0 else row._bg
        row.setStyleSheet(f"WorkflowRow {{ background-color: {color}; }}")
        QTimer.singleShot(self._BLINK_MS, lambda: self._blink_row(row, remaining - 1))

    def _quit(self):
        self._save_window_state()
        self._stop_all_pollers()
        if self._tray:
            self._tray.hide()
        for f in [_FOCUS_SIGNAL, _FOCUS_VBS]:
            try:
                f.unlink(missing_ok=True)
            except OSError:
                pass
        QApplication.quit()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
    if getattr(sys, "frozen", False):
        for suffix in (".old", ".update"):
            try:
                Path(sys.executable).with_suffix(suffix).unlink(missing_ok=True)
            except OSError:
                pass

    if IS_WINDOWS:
        _ensure_focus_vbs()

    app = QApplication(sys.argv)
    _generate_check_glyph()
    app.setStyleSheet(DARK_STYLESHEET)

    # Warn about missing Linux sound tools
    if IS_LINUX and _LINUX_MISSING:
        QMessageBox.warning(
            None,
            "Actions Monitor — Missing System Libraries",
            "The following system packages are missing:\n\n"
            + "\n".join(f"  • {p}" for p in _LINUX_MISSING)
            + "\n\nNotification sounds may not work.",
        )

    config_mgr = ConfigManager()

    event_queue: queue.Queue = queue.Queue()
    win = MainWindow(config_mgr, event_queue)
    win.show()

    # Defer update check so startup isn't blocked by a modal dialog
    QTimer.singleShot(1500, win._check_for_updates)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
