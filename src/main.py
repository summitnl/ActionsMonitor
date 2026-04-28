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
    "VXRvlmUAAAAASUVORK5CYII="
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
                    app_id="WizX20.ActionsMonitor",
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
                snoozed_state = WorkflowState(
                    name=run.get("name", "unknown"),
                    url=self.cfg_entry.get("url", ""),
                    branch=hb_snz,
                    head_branch=hb_snz,
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
    "iVBORw0KGgoAAAANSUhEUgAAAQAAAAEACAYAAABccqhmAACWM0lEQVR42u29d5wkVbk+/rynqrp7"
    "8myCJeeccwYBEbx4FUX0qteEKAIqCCgKSBJBQEUlCCKo6DVgzoqIpCXnnHNednfyTHdVnff3R6VT"
    "1ZW7enbx+1s/88Hd6VB16oQ3PIEAMEr8obJvdN8LEEAAc9lPqeBPJzeR44OInDvt1j2S+9/lOIIr"
    "6PPo7BrImZhdHVt3aqDs1KhqqLoz5BV9atrHEFFXN4/lPReX3/cX++ZKn0P0q4nKr5ASY9i2oXb4"
    "/Sv6XgcAInkbpNwD5v1/InL+jcO/a38fdXzhsZOOyj8Mirx9eT8criAyKHIaEZH7yLktgqGUuVBm"
    "8VPSNUR/wxz73ZT0GcHNOBtTiTHnyPdHx6Lbz5dSnp+/vlaEjSgp/HTGafmeztGNO2sj73Yo3Y3d"
    "fjZPkDzf5Y9hzgsrezpHnxMB4Jh4Ou/hnffZlxnvogEExdxbmYOhyLXmvsZuh9zdmq3RB5w4OAQQ"
    "d37ycsWJIjGnb3aztRFkfFGRhRR7cGRt6hmnJncYgczaZloy98+7wSY+h+i6cNfzrKYiXUyp2u4x"
    "16m1PDe1Tk7KLp2yVSwsrmgiUIHTDh0sKi65AbW9XrmnbkSU3YpSRacJHBUoFiW9mirMd9MGitzc"
    "MC5/pUo2OMp/rTmfJHdQIOC4iKJAHskFnxHnvncu9VnV5sDhGgEXvB6O3pe3+N3aA1e89DkjAmqv"
    "Z1H+QxlFwrdoft2lEKJoDocC0UXSNXd8YroXzVk3pHxRp+2gTjer2YiAnFtPH92yzySrcdBRlOem"
    "YMuzMEzuDXIXX888S2FHt/ONPNebZ0JQzhONYxZ/ocO6QE4Uve6278sqdMb8vlixiMCRmVUohFZe"
    "kCtSyHhORZ8RxZzanHB9yHHacqdrIMfgJ26KbY/eeSVn3X9MnStlCnYJIuB+IWWEmZwXtMHlHkjc"
    "yUsd9ICrrCekjnwXCilphbnoZpZUqeacn1ukmJdW/6CE68kX+bAfkeQuEieNiRrNZWwyK2IdoAuF"
    "6+SFkDh3S1bg2zaMhC+oanEWOjG79Nrl9adwS8tfaOXGw5sUZdJNKrDpdDz+y/HhVXEWdLsw/x8P"
    "b6WYsIVT+tOZJ2QOzMKK0LadredU+fdQGKjGnXSacqY13by/spFQd9HwHeQ3b0Z8bfH8NlyoWREj"
    "AIqEWFkned5/L1LcZZSNHooVhVfEjTAdBp98b36uD6+8z6lweorDFhC6XwwpU6UuE8oVrXYXeX3s"
    "g8gB3pl1sEnMwORbVB4UmHNHJf74JUQ+ear0eZ5BN7on7VyAzsFhVW9a2REipS76mPkePF2epVO6"
    "irAHKdViyihK+X1gcpFQHVRjvd9WCfnk5Zx+VXcNwZ1SZmVfea2yupO6h+0LgUCYnY23VESSs0vC"
    "JSKn1PZzxh/B7hvj3swFyTQoS7rwTs6S76cCD42VNkwQJpUDJTEjdvOJp5gmb3wcvba4+kLFkVXa"
    "uHIRgFfWkyLls2PIPRQzKszsjGvMnEg++bnwnEhdjBHQWBpAiiiLPEf55lIc0IiQOAZJ9x5/P4gZ"
    "+4KHfDcjgrKwz9LFj8iuSZGJzzlbj0Urzm+GkkdRMMkKXVV+E3Zcqk61KeaDOEAMBinA8hqctl6s"
    "MgO5SzTdov3fbk6+KsUdssFH8Xlt10FaESBkFYCtbvBHqmLcFa49LSc2auHvbctVUnf8BKWcmN59"
    "GxLLD/84FsGW+0G19W286+dS1X3qkDoat/EgqTAWGdyukXNSJq66EPPWKtpQizETpQwYKF9xMKZ4"
    "TBSGMuXIl/1DCHFFSi8KDdc4OFK/aLvPOCRep/WwBG5LJQdfGnU2hH7K35zOVyFXBioeAut9MRfq"
    "gSbljxQqDLa/IK3Xqk6u5CJNdsWaUr6QO2W9JVbenQAwuqF735GG2kyK1LjCPMGHO6cUuSgyyHEd"
    "hbiFQUkgDqQX21gVK5mF9I8yUs0iuJC28SEVmpyy82efvuHLiJNWIvfUpaA9mdG+S0YNqkQa5rID"
    "H1bAiWNEJdUJuqeyUhR+XFxwAi6mnzgZPw5qTxgLwWOzJnNoriWPFnV4MiYjUnPwQZKiDQ9IFI0q"
    "oBxIEYZd7vpSwbQxCwGbt3jPuZFFs1ThKQUWcRlnWT3r8rmP22iKqZeE8tss0o17alLORcWxHxiz"
    "i8aEmNQlxdfkidx+ELB6cibw5ePxFOX60m05PbWfnRwBSRBx+6GUFC3GXAOnPRYv6vWZhel9ekr4"
    "3HyRn8JviCFvlap9UUoMwhwOAwvvbkpcG4484N9IErXWH0ZO7jtzTA5atPBUVF4p2qHIwlfE1lQS"
    "BjJVFisjnKKUHJHiYHeUlPuGw+CyfXFO6Ti0bRjkzoa46yk67wqAe8IRS0I9ICk1Sqh3qFkHw4mM"
    "w4hLLrg/u5Esc2ZNhqID7q+joqy5uBBKaY8hphDSlmKUqD4qGLNc4J04JhtyhoahAC9lBw5225QT"
    "LmPRltVRzB1S+mKtnKv4Ft2Eo4SrvEhH8k9czn3N6hZOhNjnoRaO20/o4joHWeOf1EbrJCVJzOlj"
    "0s44+Hh7wVghUSXcf2h+t0mCJTyZtipsDr30KqrVecg0cayzvMXHPGFovkIL+QXJxNwyB205Ke2J"
    "a1MBxSrJFattF8qro4XCMsKu4Y05niWIgm3DIoVZjiv6qvMpcvjlOeQKiq/HplZlhFMSC5dUcoej"
    "lApsNz0BynxfZgRQUg+AMjjzswkGmc3+eZqGAOfs/FDe51HyEMFyAibFCkB1WTewTEGt47kazeOr"
    "FKKs+qQqLP6gxF/cieJkhzJdSRN5RfIxSBLJXN66CLMtCU8o0efvwo0X4SAsN+RmmS/P0zLMu9BD"
    "70t5CPSfZL+VFwDD+Xv6VbAfO1mIpQQ/Kpr5VCJa5ooUkau4PsEJBANKCPOr1GXtQKsx9XOipBrO"
    "8/0FrFryqtNSmhNPF3b6asaS24gpqY4+kQ8h1SWKKLeKLRIINYFjUTpJqo3oQsmPlirkETOyry00"
    "L0sqIlfpQKRO6Y72QepU0y9Vxqs8IaXTk2V5qRLlFaZckUgzlCLhnacajYwWLApi9YvWQLolFxa3"
    "ETBXo2dQek7Hj3uyHkDxHKOz4CUOFxBbBa0IEjtb0tuxPd4CQzWr103ZKM22Ts0sk3Y6iZC4w85G"
    "VtES6B6LsqODKemgrRi+/R9HHy0KTpvtesFsRiudPKvlrlnX4djScijkVfWcKAGMxFzAGSiuyLa8"
    "89cqr6Ujx14qIWee5biUkkNniqsUjE0p54AWBV+VfVapAjNu/YVm6XlzxnXlfU5Vb0xUIPWIvscR"
    "sikPic9htBkH26Q2nbgqXEyT+79UmCIJJCKLKz1pqw6d0/LwMhTRrjgmxSARqQR0nLmLEUbMQMyG"
    "ToI6+bjQe5JBR+TSdLkNi5l3Dc9qaNmJfVO8MUOuPnpJLbVC5hEVSEd3pXjXobJSVQ673VbVXd42"
    "6lVjNZLQiZyR30cJa97mkYfy3xX55aoefBJIkjKIGEmLshNVmDxqvFXl2LNhs8YrhDR5hcjGDlyV"
    "lyuqsItSfPF04A6/MQ1D3TWYakUSzrkk0QvSlcsaSHSaJeQx5Uz60rwHAHdZaViFqHOXC8kU09XK"
    "Sy/vBLiGLoGfkBM0x7PZjuFZQVblIY6nU2Q7nZT/qX+okqgtwokv0hItWzdaAUKaNs5IEuWal2/a"
    "0i4vQOUQC2Vprh2rwVSYd1EOVBWXSFVUqmsx7Ha80MObaxPJp+DfLaJZGWMVQjYmoKo5W31qnPxH"
    "ZLe9uF3hIjepJSrOmA45buPvU3LeQjF4WlIEDlj9DAq+O65lQ2lYU0pvtXHOp8pRHfcEK3HOGpcY"
    "nG7SfXWzXZrxdantsbxl1059KSgZYZwINSZBoTaZ+mCyxpg7GPVEb4gC917m4EsToFnubjR5HIAy"
    "T4iY3btzxmJR+6XO+Q/drqDTCtrx6Qa9OWncNI1g24w5fRr6ezW8sLiV6ciTWX2vsMXaDUciwVWY"
    "DnQAZOAUIkhoV0w4MTNXFYflxor6vyedYFzYQSifnh06dVgq49hEFIivlAD3FHOF4nyEqRj4NHUJ"
    "4AMAdUPAthlrrNyDkw7fEEIjaBpBpAKjODMS4A5qZp2kBQy3mE/pB5KYrVwldFpHB8m1giqDqOIC"
    "ffw0lePuEnAo12dX/d2cu0rPbQCtvNdUdIITF8MUFPLWK5nKNGoCTVNi9y0W4E/n747f/Ot1PPdq"
    "E0SAlMW37CLXwl2cD8TtoKboeSkqg8MWwBNTwR21zOZEBU0nVEU1qjwi4lmLsPLWWEL3yZ1dLaGz"
    "tC/PIqAkCHUHqZUQBEMTmGlJHLzXGvj35fvh0t8/j1vuW4KeugbLylLv7V7SxBV6PWbS4rvxQxm/"
    "I4CJqPLPno0f6sI1JH2ei6BWXkeVfPesjCF19n0U83mUMP5FP18IsK458++TB67DfNcH+dyjt2QA"
    "bOiCBVHo+pN/KPO6qeK50zYnKGWNZb0//YXU/qFUdBJQ6YWe+bkVTXbKs2FRdxYTVbVRLOdNseh1"
    "03K8jrouWBDY0AR/44jNme84hH925o5MBK4Zwt8Yluf4tG0clDwHiZC5WVHyd+QmsFUCAKqit5us"
    "Ihx2YinkgZdD3z3OW6AoHbiUX18CfaMsLqETMYo3Kx3cG5e64eT7K8+t48df2QX7770a7rrvJex1"
    "xCI0mxaYGbZcMYBTIcs6xDt2FUGlxpmSZHpKpANSkmdRrE5fxWotbya0e3GOwfKBrlHFrMA8Rqmo"
    "+HOT5mNNJzRNxo4b9uHHp2+LjdddGa+9MYW3fu4GPPjUBOo1gVZLdrBgwwsVFWgldo0X4f7RURLp"
    "lnUhUc8+Lugk0/3pz7O6XXDh1/Jy2eK6WZWOXlMnbD0uWOwTBDRNxiF7L8T3vrg5ehp9sGZm8Llv"
    "3YMHn5pAzSA0W7KjseWQwShX/1ySqL/lXNTydwEI5aq/3MHD4yrEIwpUTFOaOl2r96oIvtj7oPL3"
    "FDKozPhY6kLFnxIXyWy0XYM/mnCQfpbNOPXQDfDLr++Ceq0Pvb2E8372BK761yto1AQsi0ttQKVa"
    "1znahlTg/VxIvIa6f9AWEQqZfcRbAg49r2baCqgRniaDngeVlsYAzbI1m5W0qOQXGrqAbUsYOuHC"
    "47bAYQevh2UjFuYM1fCH657HISfeCUGEliVLU9p5OUu1tTt3oSBKtaK0om1hRUDGVFqYsQrqZHBt"
    "QsXNK08paunsAYziiIaUU7mXSt5vNwREypCWkpR8EhWhOyDH5DFSLfI6r9g3f04dP/7KVvivPVbB"
    "kiU25gwaePj5Uexx2I0YmTBR0wVMm3MvAlIeEPMsCt90aYfNtL0DV0kDrXBSFxB3IDcMtG0uBRYh"
    "AlgCchaNJLp9gvisQoT5/0U7BEUmdaGCYNlokYCa7iz+XbeYg+9/eQtstu4Qlo6Y6G00MN408Zaj"
    "bsQjT41B1wim9SamVXbCsXGHV59NbCpX2TLKpvtDEMGWDJaBzfRKc2pYd7UBLJhTx2orCQihQ5AG"
    "BkEjiVZL4qnnJ/Hy0mm88NoMRiettnzStstXd3mWxio/LDpccvQs7PNuVMyc+8VpRT+uANonBEEX"
    "QNOUeN/eq+LyU7ZCr6FjZLQJXdPRqAt8/Mz78PCTY07F35TLNVXr5qHJWd/PMV2AtE23K4KRKV8Y"
    "+7mcT5ZLI4IlGTYzGjUdu281D2/beWXstMVcrLtaH+YN19EwCCSk82YbgLTdY16iZUpMNC28MWrj"
    "/qdncNMDS/GvO17Dg0+O+F+iEWBL/o+T66AUoZPECZwVYqppTUS5qSoZNE04bemWxfjihzfA1z61"
    "EZpNiTHTBDFhsL+G0y57FL+45kX01jVMNe1ZG2XqgBRUZY2Bu2UOmqbUWsSMs0wBQP0OXSNYbpi/"
    "9iq9+Mj+a+DgvVbFxuv0oNZjQNoCpskwbQkpGSylb4UFl5AEduoEmhDQazoadQNUMzA22sKN972K"
    "H/35WfzlplcwbbJfT6h6IyimOEQuCKwa3f1uS7d1A/hjaATTZvTUNXzzs5vjiINXx8ioBaEJsBQY"
    "GjbwxxtexEFfvNPZKGLAPpn6jrPhx4hqVI8L4nmImd/ceZAgR7vNlsCC4Ro+d8g6+OS71sLK8+qw"
    "mhYmmxakBEgIN4wXIaAGu4jugBIbZFCSndzf0Aj9PQKSCfc9sgTn/vwp/Pq6V2BJwNCdjWc2EW0o"
    "KeOOChGdK4LRR00ntCzG6gvquPIrW2PvHVfByEgTQnM25qG+Gu5+dAneduxtmJhy0rkieT8lCH0Q"
    "ePk2g5aDuSlWRIydLgQsdkL5D+6/Jr562PpYd/VeTE1aMC0GaQRBGlSFdFKBSoSQpkpIaUhpC0hm"
    "2LYDuR7orUEYGq6783V86eKHcNvDy7oWDSwvh+A4rTrOIYubFwHXuddAUOzbfYs5uPKULbH2qoMY"
    "Gbeh6QJsWzA0DdOmwN5H3oAHnhmFobcX/Yqq/ebWtqwACVhG+LPt3zLEcpdHYb6yC/Ae6NyBGi76"
    "4jb4n7cuRLPZwvS0hK6L0GIOTvhon42CxBfR9qDaBmM/2Ga3UjbQp2NmxsLZVz6Bs658HJZ0IgVL"
    "tkcD8RbV+TsZKGCMkvfz4lIMdfGnpwOU6ApZtnWXd35owqnBtGzG+/dbDZcdvznqOjA5Y0PXNTAJ"
    "gIH+HoF3felO/Pnm19BTF5huyje1NVvna6j9lZ3V8HISX7oREXh93k3XHsBPz9gR22wyiLGRGbcI"
    "KELQTH8HVFB3jjMPBaGA8jR9cRL2rj/cVCFXbM4yJQQx+gd1XHf7Mhxz/j247+kJ6JqjK/efEA1U"
    "nU5Qh1VwL4eXDJz6iQ1xysc2wMy0iZbN0DUBJoJla5gzp4HTL70Pp13xJGqGgFkS7JMXt8ErIg4g"
    "R9ZAxZy8o3Yys39DRM7J3zIZ2280jN+dtxNWnVfD2HgLhi6UgVZhmkEoRuypg3oPzqkfwN8UXMnw"
    "kGUOhcvjHMQDTmogMdRnYGzSwmlXPIbv/PIpSAC6TrEQ07xOsFUU54rahiVasGUVe1NAQ1WdmF7E"
    "199r4KIvboWPvH11jI2aDs5DEMA2LFNieLiBX/z9BXzwtLtQqwnYFsOSjMot8Iqm57OQG1PMxadp"
    "Gqba1Pm/TGP9RXq8Rd1Tkjzgkz7HK/psu8Eg/vHd3TDUKzA5bcLQKQjZVY1BUk9wEVIcJgZkCN3H"
    "YHIlN9wF70UPCs0DUSa1hzU3dA09/Qb+cfNr+Py37sUjz09A05xNJU80EKfQWsTqy9v02tF47TLk"
    "yyscpZKuS17Et8HqffjRqdti182HMTJqQdd1kBDuM7DR39Bw9+NLsM9nb8XMjA2buU3Wq4irFZUk"
    "LrWtqZhcnGJk8xM3yJQvT/5VerGSAGgATosjo1AGmCCV4FKSJJH1bTVdwJbAqvNq+N05O2D1lfsw"
    "OWWGTn7nNHBu3dnhyC3uOZMEgoINgTh4XQQe7J1qahThfqovJe38VwACEJqjyjAzbWOz9Yfxvreu"
    "ipHxGdz56KiDuNIIWXsA0Sy6HVORZ0rx/z+FgERUzf0Qkb/4991+Hn53zvbYZI0+jIw1YRiaLzzE"
    "klHTaxiZmME7j78NL7/RdLsz1ZGc8kmhF3+eca+LrkWKXESsU3EJUlxoAygmKkGJk0EV0vAXSklF"
    "VPW/mnBEGn98yjbYY5s5GBtroaZrzsIUBJCAEAIg4Sxyb0PwEW4UEUYMdkgObV4AE4cG3WfukbJh"
    "+KlEkAgKAmamm+irC7x771Ww5XrDuOvhpVgyZkLXKAWamUzfI6K2yZWICaB4SfU4FliRxRC3qccd"
    "GqknmRKN+WOdch2a5tyPaTE++4H1ccWp26O/ZmB6RsLQNUVQ1gFx1XXCx752D268bynqukCzCzDf"
    "rMWayqnIcouOjq/yT5zEAE30A6fQuku6An8DqEr2uVDumHOL1AShXtPQNCVOOXQjfPo9a2LZshnU"
    "DOEvflJumEAgIZSqnlLCU8g8gfBGkL8Q0Fb2I4XcSggWKlF8zis0gpQSM02JrTeag/e9bXUsXjqD"
    "ex4fA7vAFclFTyUKm12gvCQ7uiT3HlroFI2g0t2jon90V6NfI8L5n98Cpx22PpqTJmy32OdPcCFg"
    "ScLQoIGvXv4Ivvf751E3RLgTk3AAUY7TPGmx56Vul/FByBN1ECUbD1KS7Xn8pt4OBCqGMQiKaGmu"
    "u520UwzdqeLutvU8XP3dXSGbZlDsUEJyVXbca9mR0urz2ndqnM8hCzR28v+wjElgsslKJkhokxRr"
    "uxsCbItRa+ioNwz87C9P4wsXPIiXlzSdlEAyJK84VOLUglAXq9vRZ+897/lz6vj+l7fGu/dagLGl"
    "kyBNgxAaAM1NvQimTRiaU8efr30eB51wOwyd0DRlm5kVFzLvjKFklnXBTjCFocgv87Ve05GKqVZl"
    "CQ5/pHTDC2n1qRu3P3kUOhlVJIekac6OVq8J/OuSt2CHDQYxMdmCEwEGbDa3AgaQy3FjajNiJBIA"
    "u9KyXujv0gHIW9MCEMQBKCg4990/UjH5YGUr9h6CBzjyvlxCukzCwUEDTzw1huMueBB/uvl1J61R"
    "4MtFC21F4KoUM9lydwxQvddikvJCo+bIdG+9/jB+/LUdseW6gxhZNglDE05nxgF0AGBYDPT11PDI"
    "C2M44Ohb8MobM9CF2/LrUoU/Vu4u0gqMbbdRqHlWuiWZJA1WdhPWCHRa1WF/cgGp+PvrNQ0tU+Kw"
    "g9bG4e9ZB6OjTbfir/ToQ/16ZeFS+90wAFsCmqahUTfQ6DVQr+uoNwRqBoElw7TcyEJTogsRmAyS"
    "jxgUSribYIbqdhQEMaYmmpg/JPCh/VfHgsE6bn5wCaaaEoYucu34ah2AlDiQ8m4akdme10Ogao/B"
    "uPklBNzTm/GePVbBr87eBess7MXohAlD10OdHAYgpYQhgInpFt79hTvw+AuTTnvY4uJqUHGelWnp"
    "SyjdrK6zR1Syl1+gm5FfvKcke6iob3yqb5kLP+2rC9xy+Z7YcI0+NJs2NBHeTaNhfRTR57XHLAk0"
    "DA21PgOTUxZeeGkSj700hamWhZbFWHWegS3X6cPK83sBFpicMMHC1QRg5dD3Yw8ORYrUZhrmnFb+"
    "4maGlAxAYmCoB48+NY4vXvQQ/rToVQhyvicuGlgBRYgq/aNCdE/8yPo47dD1YdkM0wZ0XXcjsGBz"
    "ZzBYAn29Gg456Tb8+tqXuwr26aYDcXmjZ5od3chwNTMl5EywUO7kwupuOPi+fVfFL766A8bHZ6Dp"
    "ShEucvySF8NH2HGSJaTNGOw38PIbJn7+z+fwi3++hCeenwjx/QFgrYU92GPbefjfA9fG/juvBKsp"
    "MTXZclMRCtnTUIxgY7BDUDwX3v0/tk3o62tAaDou/tWj+MolD2DZhOUo1FjyTbPgO4XC1nSBluUA"
    "qX5wwjZ471tXwtj4NMAEITT3FHaiLXJEHmBZAoNz6jj3Rw/jhAsfRG9dYKopMXt24elHbhFp9lg4"
    "dqHxpFICt6gKpRsNk6raADRBMAwBy5L47Tk74cCd52NisglNE35fP1j0FCkABg9MSifJ720QfviX"
    "53D6FU/ihdemQ0xCJ0R3/u6dwIIIB+2zEF//3ObYYM1hjC2dhnBFJ0LFT44gDX3aESFoGKhJYpCs"
    "2NK5xoFBHfc8uARHnHc/bntkmc9tl8uxQhgFQGY5OJcp+uruZrfRGgP40Wk7Yeet5mJs6SSE8KIr"
    "BaHpvseSjKH+Ov500ys46Eu3u1FiObWn5U3Ky4PSpALRdF6JOjUyzmwD5ul3IoGVRGltjIycRxME"
    "05LYeoNBnHrYRrBM9gt5/skf3QA4IqzNAEhDb18PTvzeQzjhokcwNmnB0ESkskt+YU8IgqELkCA8"
    "9OQ4rrr6RSyY14OdtpwPIh2mBWi6ptQZlIiAKKg7ULh9CCWQDXYqBkFiarKJNVdu4EP7rQbbYtz2"
    "yDIXWUg+iq1buTcKeChmA2HyLxpPkWfv7VbC78/bCRuv1YvRsWln7BVwltfqg2vU2dNj4MmXp/Ge"
    "E27DTMv2UZjdGIduyHOhAwXu0gaoavEwDQdQZIJ02+BSkDP5D33HGnj7bgsxPc3Qdd05gYUI7Tje"
    "QUyRmWvbwMCghhMufADn/uQJ9DY0SAnYHLGdVrofHolHSmcBjk3a+P2/X8JDT45gl63mYKWVejEz"
    "ZQJsRzoQSq/eLyBxsBGqD4A51J/RNAfpBkgcuMdK2HWTObjniXG8sqTpdDtcbsN/wh9NOCd/05Q4"
    "8uB18aOTtkCvAUxONWFoAEv2O0gBTsQZN13XYbLAfx93M558ccI5JGyelcJlt0BEiYY7mJ3KYggJ"
    "WEiLPwfIIw6ZnOc9DpuO0TA0nH74xlhtfi9sW70Xbj/t1X8mwLaAwX4df73lRXzm3Ad9taAiDD0p"
    "nfs0DIEHnxzDVde8iJXm6Nhhi3kgm9AybQjNKWH70YlQKsRChFkEvvoIhVuLXjeRCVPTNjZddxAf"
    "2H9dzLRM3PHQMtjSyZWXV0pQDazbKfbZtrOcz/nMZvja4Zui2bRgS8DQ9ACw44NwyB0rCUhGX7+G"
    "Q8+4C1ff9jp66pq7aVZ7n+W8I2LBlonvpW6PdYGPaEsBVoTdUtOc03/leXUc/5GN0aMbLh9f+tx8"
    "MEc4PwLsFgCZGToYky0THzj1Xrwxarb124uEgVIydF1gdMLE7/79Ch57fhw7bz0HK82tY3rGdMNU"
    "rQ0Az3BPs9DuxFAymBDukIggNA3TJqNRA96xz5rYafM5uPvRUby6dAY1t13IsxmqUkriXwDzX3Mr"
    "/YP9NfzfGdvhE+9eC2NjJoRwIiBy6zrCD/0FoBEEOUW/gfm9uOhXT+GcHz/htvvkrIfnXe3vYXmp"
    "aZV0sunqRQkHKrvx2n1YechAq2U5ITerubQXtrsVYq9dJxxBiJ6hHvz6+tfx0FPjqBsiVCTKC0FW"
    "b9WypO8v94u/v4jdD70Ov/v3ixicU3PyUMv25cVYOpuQt/gppDZE0daJW+QWLqvN8ayXDEyMtLD/"
    "zqvihh/sg6Pes65vYOFxCvKAtPJDdxNCT475qIJsz5oh0LIYm6/Tj39dsDPeved8jCyehAYLxNIR"
    "ZIUEWDotPp9jIWG2bAwOGbj2tldxwgUPo2YIP+vqqBYSUzTOl0fnKIYhn8IxrQDbl8h6thS5D85x"
    "M0QpfPEsmypydn0A6K1rECTB0nQmB8M55cldLELzF44HyvEovLJp49fXvOwXiVRNfxUSTAkPmmKe"
    "G7OjOqtrhBdea+I9J9yJz55zHywiDAw2HO4/uxuUSxlWCURQ9Ai9LgG59+Joijm34V2AJmyMj06g"
    "j1q48PhN8cOTt8FKcxuwbEZNTyYHcU7Z9FArKhbSnMP+jSMljah2g0FomRJv234Orv7uTthuw36M"
    "jLZgGDpAGqTKx3CjJHajPMtm9PYIPPbcMnzk5Nsdeq/NhYt+seSoElZ1jBR5Xy5efOSO1zhXsAFk"
    "nOhldOzbFk7KLtimA+CG9gCw1moDDgPQO/1JofiGGDGsPBdGo0Z45vUZ3PHICMCAFef3zJxsEaac"
    "hnGjY9nONeoa4cKrnsUeh16Hf93+CgbnaABLJ9og4a9mH2vtGnB4m4EvSqAsAX8MXDKLEAKWzRgb"
    "N/GxA1fHDRfuhLfvOM9BvOWIBrIWbtpz7ETOWhPOtbVMxmffty7+8K1dMHewgfEpoF5vgITD4xf+"
    "Jq45P5rD6GQS0DQDTQl86qx78dIbTdQMyq6D5MjjmTlxw0OX7Wi5G0YSlA+FG1enEFwwPEmMgKiz"
    "wESl33gPec2Vep1TVAiQpoJC3JPCkex1/+tIfEtJ0GsGXl7awvikk/snbkpxRovcJv+RuIC8Vt39"
    "T41j/8/chC995z7AkOjv02DZNpjY6aVToEkAQYr6sJPCcGhFsi9CCnaiGSKCJggjI9NYa6Uafn/2"
    "drj42C0wf6iWGQ3MtpGLE/I7KRwzcOFxW+C7x20Mq9lEc6YFjSTYtkMpnbo8vDTKtgi9wzpOuOhB"
    "3HDPMtQNwnQzB0CK422+0oxq8xT+qBCTcHbSfsq4OWZuj9Q4pzsw59nFiGJD/iQaYt5B8S5y7oAO"
    "CAERusxAlst72E4Iyi7UVgI64a4nlsK0JeqGKHU65n1+lsXQBEFoAuf8+Cnsd8Qi3PHEUgzMa/iE"
    "JHJFSBjwNysHpcRODhxiiZDLTFSBRABIwNANNG0NTVvgiA9sgOsv2RP77TAfLYshiPzNbnkVvYgI"
    "NUNDy2QM9xv4zVnb4KhDVsXo0imwZAjBihS7MhuZnY3QnSAtS2Jwjo5Lf/k0LrzqWTRqArbdveyY"
    "mVMPtbiTm1M/L1/btlM8AlcwDqKjthBzajgJLnmD5EF4OVxi9k4M8sECLkQ0IAU5F2PD5M5mfJHT"
    "z2bHbKSmE25+YAR7f/ImfPtnj6AxqKO3YcByK9YUlzf7piROEQyQfj/Dpzp7YbImoBs6NN0xKtlo"
    "rX78/Tt74JtHb4WeugbbZtR0ASynHreuAU3TxlbrDeC6i3fGO/dYiNERCV2vQ9NrEMLwQ3//nlyg"
    "j3dq2raNoX6B2+5fgi9e8JCr/ygLa/pxwYXB+Wt3OcaCc4nglE2vyo9D+zWJMp2KJDHJuM/gggNK"
    "UdUef4EEtQTJEgwZiGOQ2qHwJUGUAld3B9hN49Fyo4GZlsTnz30Q+x95Ax5+cRT9c2qQbDvcfyFA"
    "pPmIRhbqwAX1DaYwAzC4N6eqoGvA1HQL09NNHPuhdXHzpXti1y3momVJ6JqTMsyW56Bw6yGmxXjv"
    "Wxbimot2wxbrDWNsCqjVaxCaHpixELsLBD4eIgBuMWo1HS8snsEHTroDY5OmAwjj7i2MIuC3uC4A"
    "xaBeWXGX7kb0VT69iBGvybs4KePbuQsLjQM/7yicKLSwY228uTxGvWhopn6HLZ383dAJ/7z1dez+"
    "0X/jB799Fr2DDdR0htk0lfxXAVV53Qy3AEZ+EdHVLgilPA4wxvvt2LJJbL5uD6757m445WMbuTwD"
    "Rt1Q+uoVTS6i8DgZmoDmLv4vf3gDXHX2Dujv0TA+0YIOCWnbzo+UYDf1YbduI10/RskSkhmCdGiG"
    "gc+c+wCeeXnK1wLsBP7aySlMCXp8UW4EJ83BrqUs1dUQBJVJkLuIYvK9+kJSXE5rUFDA/vO+S7rV"
    "8qBFKQHYftuvaE+cM0MzyuEI4+jYaRph2YSFT55xJ95z3CK8vHQKg8M6bNuZ8OzqBfiFQGp3641q"
    "EPoxgO9pSNA1DVPTzkI5/TOb47pLdse2Gw2jaUroumOiwSUeL1G7/JhTH3H+VjMEbLfteekJW+Os"
    "ozbG+PgMWjMtaORsVKQUVLhN3ixgckoJ9PYSjj//XvzpplfRqDlEoSoq7lQy9+a2BZ7O3Y3baCkS"
    "PSStEV4OfAQGILiI1njCsHkTtGrZaclKZdhzsye4qj+sDDqFNdIYkJLiC5EVxCVpE0gN/WylXfi7"
    "f7+MXT5xE375z5fQP68X9brhdDtcwAskg23pogelWxyU/pg6eCcCaU6kIDTNz6OhaRC6AENidOkU"
    "dt1sCNecvyMOf9fafv5s6JTKuwhSDZUbEdQqOBJI1tzTed5gDX84d3t86l2rYHTZpKty5KQ5EBpY"
    "wWp4eI1wtANYpo2BPuDHf34K3/nl0+itO58tufMTNKmAx12AP8ftD9EIoYyvAxVS/G3HmqVtMIJy"
    "FkicjZwDrHZbUYurY2NRUp9DCZtDll754/1O/eg80iEXsNq2bAc89PLiGfzPiXfiQyfdhtcnTPQP"
    "98B2Fz0HimN+yO+cODII/6PUMEFKh8G5MEMjjIybqNUIFx+3GX59xjZYe2EDpsVtDzuEvQhEz1Of"
    "j2fM0jQldthkGNdcuAsO2HkBRsdtGEbN0ezzqNrwQF2qZgOFslEpgaGBBu57dBxHnvuQzwIt+qC4"
    "ZPpWtDMw23/SItJAIJaSU/GMcRScMpipvdZQmMrVAiI4ZiPiALHmtf3alVkVjT6q2LK7YJ0jCqLx"
    "wEOGTvjZX5/Hzh+9Br+77hn0D+nQdCeUhnsqgrQASEQKPVYBsbCUDvbBdnJr9lIhEAzdgEQNYzMC"
    "B++3Hm68ZB988l3roW447siCwhu7dKMt9ae9wEU+Vdq0GIfstxr++d2dsNmafc7i17XgWv22rPS7"
    "G+RtYm4twLHoZtR0Ha+NtHDoWQ9gpiVdhl+5jZoLxAZUUSehXXBu9igAflTRwbGWGwfgYcU548VU"
    "YcKStdhC0nuRi6AsHYOYp0MU8+CISkUOSW0l04MSvzqN9xx3Bz55xp0Ym25hcKgXNmtgYYA0r13m"
    "hviqWKvLMXDESW33v24L0S+wOX/XNGDpeAtzhnrx/W/tjsMPXttZdIYW1FRybdIEXZCL7JM49oPr"
    "4henb4kabExOtmAIDgBU5OkcIFSvYSUK8H8kUDMYR51zD+5+Yhl0nWC6qE2qDG0XL4LIJRdqEShv"
    "pyrCeesV7a+hzjeAdh4A5/psTsH4F82rJEdgsmprzDfBoHBawAogKKUNGIsW45gHx1x5Fdey2W+d"
    "/eCPL2LvTy/CtXe9joHhOgQsWGbL7RTIEGRZNScBBAgamLQQkQgkvOAa0mrBkC30NSR++MOH8bO/"
    "vQhDE7AlB0hkyua3GAbBlg4K78ITtsI3j94MU+MmLMkQOiIdioCvAbfdGZCeAoEPWxIG5tRxymUP"
    "4zfXvYLehkDL5FBnp/ojkzteqHHmqFyltBqXSFspCuFOB+CokYteOATifNJInGPBZd8Xx2J4WSX+"
    "h2C7QRzAcnYtnovKTEsHr4SaLvDwMxN42xHX47PvXxdfOWw9zO3RMeb63BNp7mey4vxDQQ1AycCY"
    "GMJFEtq2jUZNQNeBz55/Ly686ung4LXjC0XE7dGXV+ybP1zH5adsi3e+ZRWMvdGEptchXPYexfhY"
    "kZcqeh/KcCIVAJYFDA7X8afrX8LZP34Shu5gJzpSqy2pl1dWE6+INFoeGXLuoGbFMRE4cfL4sfJ7"
    "0ZXNlaqGnbp9AAYklFAzBtHvTUYRMgdNtrLy9TupGtEMLlShZrQs6dCYQfj2z5/GvkfcihsfWILB"
    "uQYgJaRlOe00lf7s3xcHu71wb14TsGFgcKgfiycJB37xTlx41dN+F8APjDgGH+4jKp06ge4W+7Zc"
    "pxdXn7893rnTMJa9Ng5NOGhFuGQe+BV/ETKTVTs1Xn3DZmCgV8M9jy3Gh0+7y39OUQNPTho/rhbP"
    "yZ06X+WIBLJqcpSWlnbAqUl7AXcCBc57FZWYSBCrNJFAHjphcnhddF81jJPzwxDFs4KqcdlcUUqn"
    "IKbrhHsfH8dbj7oDp132FPT+HvQP9sGGBnbbfr4phA+scWoALG0wS5iWxOCwgTsffQ37HnUD/nHL"
    "YvTUtcyIyE/hiaBrArWaBtNivHPPVfDPi3bBluv2OTRezTM7cb9XITCRgopkpWfjYQeYBQy9hpFp"
    "E4d+9T6MjltgwJcEr6pzQyjeKpxNwlTioq2o88AFXiBWZFETD/pLrAhqqkcWBcU/9kQ23ZknNFFo"
    "B42zTJpNJh27obGuEWwJnP79R/HOYxfh4VdnMLDyHAAGpKcl4PYiHS0NdiMFG2yZGOpn/PwvT2Kf"
    "Ty/C489NOIAa0w3VlW5C8jUzSEjMNG2c+JGN8Ntv7IrBgQFMmjXUGg6NN4J5VQAy4UKfqrUo2QZL"
    "Rr0GHPq1+3DvE+PoqYtCar7UIc+eVyDBQEoB51SyweSMJkTewtxyEaV0q8gcwQD4C58dCzC/IOjV"
    "ByhChQyDiHOBPbiCuVH4/RSIXdRrGq6+5Q3s/pFrcOHP7kPvoIFGXXdML4UO0nS/+GezhC4IvQ0N"
    "p3zvYXzwK3dhYtryc2ubGdI1KElrGRk6wZYMywYuOH4rfO2YzTA93oTZshzdAR+y7BF5RJtcbbuD"
    "soM28QRaz7ziUfz++ldQ0wVmCmr552KoFn0enK/K3lFqSNnXTB1gZyhjwaY5GIlMS6qYFgN1EG6h"
    "VI9SCftDctte4c9LEgIyjWS02T5xSL8/uzDZ6Z7HhTsg5PMJmi0bukZYNtbCZ8+6H4d88UY8//o4"
    "BgY12KYFKQGhOf3+/r5+NFnDB8+4D1/90VOoGcK31Y4CtbyCoSDlRwB1w+nvzxus4Vdn7YjPvHcN"
    "LHttDGybEGyD2Ukx/C6M8CzZKRStqTRfzyvSsoHBwRr+dNOrOO2Hj6NmCB8KXSUijwpUyos8Z+4E"
    "3MZcCqBGWRsGUaH3ggiapkHXNGjKj8g0PYjpq3KJxV+kDUiRCycKI7s5BunNnjFnxLUXGco3VOCh"
    "Ukf8hvT9nmLCLLVd+Ot/voSdPnItrvjDM+jrZdR0GzMzJvr76njujSYOOOZm/PKfL/khv5TZp47z"
    "2QI9rvX6dhsM48bv74v3vGUhRkaaMHQNgoSvXQDJbYIpodNeqdl4329bjL464cFnluKjp90NQQzb"
    "lpmyXlSie8QlfplTHjLzvVlKYUXhvJmLOmVcOGETtW0blm3DVn70TsJ+LgSCKfMg2QeVeECkNrEu"
    "4sCRhxBr65zW6+EE+XIGl5LGCjlLU/5eKqe0C6ULJV48YuITX70Pf1/0Os4+agust84gbrj1eXzo"
    "1Lvw4uIZ9NUEmiZn9rZU5pogYHLGxkF7roIrTt0RwwMNjE1Mo9ZowJP14Wiw6pmpkNdzdguTnn+B"
    "59LMBE1oGG9a+PDJd2PZWAuNmkDT4lkpruWdbFxhnSezzUcpLbqUth6XFtgVPiZmt113xVprrQXT"
    "tPxcWl8RLJKysPSs9ME5sf0WXvFMncwJzh0lxKMXqkKzBNPJiwaEIPzq2ldw8wPLcNC+q+KK3z2H"
    "6aYNQxeYMoMSfFZ/WwhAFw6y73OHrIdvfG5TSJYYH5sMiEPCaTtSBJ7NRAH2gKNtWBe1QA7OoW9A"
    "w6Gn3ot7n3TUmXP3+2fJw5ArqvRSRRtOFp4GRC4SNPsehHD0FYeGhnDZ9y/Du9/zbggRDvr1Kgpc"
    "3KUiYagpwuHwiNycX0UokjedqHjuyDl7xVygHdi5kzLHRgOaRnhp8Qwu+sXT/piEqLMUHq/od9Vc"
    "Zx4Jwvmf3xLHvH9NTIxOu0KcOtgmfwx9+rEbiTGH263+qJNisUaAZQJDQwbO+78n8Mt/PI96TcCK"
    "4fZzRQAdUlcOJWtAxkqic3X1nk4PxMzTv23xEyIOlP7iNwwDzWYTJ590Mg5+78FomSZgWdA0rfMN"
    "YDZ2bWbyUTpq6dGX/6LgtonDgJ4iGwAXYJuVHaM4Z+Wi9uve7zyasRDk6yFkIk/cBV03BKabNuYP"
    "1vB/Z+yAt+2+EKNLJ6FrBgT50KI28ShCGFjFUVFpCpyPLUtiaLCGP9/4Ck763sNouD6AktNdcuOA"
    "LJQbDcexC5ByAGM4xf8kiWBExKl4l7jFX8g1OOVQZcVAVE1WOWSuo4GZ0d/Xh7e//e2wbdsRcKnV"
    "Qtetqzsnl241Uogl2MmOHupTk1Q49kpiTRxm/TA5CEEF2pZGdKG8ldO8fWQu30alDqTXbZtzKd6o"
    "lmvTTRtbbDCMH5+yLbbZeAgjy6aha0JBA6oTWzFgCWA9/sJiRYbRQ1TZEuhr6HjyhUkcce59ME0J"
    "0oOuTBssNrJLqsVQjnRS8tSRKBJmc4bVd5LlPaU+Hy53uufZ+Fj10eDMDS/rMoSuQ9M1aJpTC5Ay"
    "DP3U02TBOad6LlN2DsBFKuYIS3kTqO2BheWZokkvFaqSpmnix4WZXPDELjIuVbAO4zn8zin8jt1W"
    "xo9O3wFz+3WMjZqo6ZorQhLJs0iZg6QQrXzbc25Ly8AEXQi0JHD4Offixdenw7JelG41nnaApD3P"
    "vMQcR1+Q2zdmar88LoHnT0vvqLA+JitpLcqL7YRx3iECXW4kIM0iSqjdQhsRp1gP/KNu9xQpsxa/"
    "JC7Z4QhLaNHyqWRn2Kx5yrqffNda+M3Xt8WAbmF8bAa6YF8MBKoKsRLyt213qnefqlkgNEgW6O3T"
    "8aUL78e1dy52LMDV2gQXM6CtsvinCWfxD/cJrLFyLVZvhitGdhYRBY2tqXFcC7nYiLWraYbdqkSe"
    "EJhzwi6pInfg9pYTh/TYWAH9EAgkODxhEwgAVMqqnFLx/gE1mUqpImVaqnUAlKnp7jUx4YxPb4xL"
    "v7Q5zKaFlunwDkLAHfLaeBQKR1UEDZMqzBIeb7NlY6Bfw4VXPYELfvUsehsaWqZMhVh7ajZx98Al"
    "tPuSflc3HAr0avN78Y8r9sZ/772Kb0Jb/PkQciP2KT8egDuWJIvfbnwvimg0xSppjsJw2diBoHA/"
    "nChGOoqS3+vRVZnbb47SGE1xzEJB/qbAsZVTR2wicaLEXDsltRc5eR9npT4RuzkoACjKI/XEYU23"
    "PEjCeIl2p9jXshjz+nX8/rwd8ZVPbYSJSQsgA5qmAyxcN17lGhXJ7pAAJoULTZIR4v+bFjDUV8MN"
    "97yO4777EDTNYRHmQ8CFbboo04SGUhcKBdID0ASh4YKcttpgEP/89h7YcYuVMD5hK++l/FqCEXPA"
    "uEcScsjiooKz+WMOyuTncFIY4EK6ndfozFGwC8e3Mji+W06RF4VANEQh7r7P7uN8MEjyJqGnk++1"
    "o6RbpxZCqUN4+amIxQtk5ZqcognH0Xgx1BNvf3M4GuCMglK7qWeb01KRyIIAQwOapsQmaw/gJ6du"
    "ie02n4fRN5rQDeF7LDhjKh3rNf94V3UH3FqMO64CgSIUiUCERTLQqBl4dXwGh599Hyxb+p6ARTwk"
    "PXxBdu7GqWPj/VWD45Q007Lxjj1WweVf3gq9hg7rjTFfLCKP1hOn9OrjhWaKFYEoo4sQApZF25Yl"
    "hQwoaCVA928mD0MurkehLpTIVXFEnTDkgKW2aFS9u9AGpFJNRURKGgoLACFhjKiwIJFa7KFQYYSo"
    "vXePhNM5rwsvMwdtmpS8lzzkXIEGVBpwxPPla7YY+26/AD85fRusPKeOsRELNUP3xTuCTYsUc45g"
    "sw3Hgi7zkJTfezsfOfUYUWMcevLdePS5CdT05MWf3WblWMWdwDSWAtZnSk1BECA0RstkfOzANXHh"
    "sZsCNjA9Y6F/sA5N1xJsMig09zjh2XNWfze6iGPUeYnD0XTbgZNUXuPyrsLe+lILi4I5LQyOx7Sr"
    "0teZAgQJFxNKPSILn0GqZrWazQTVTDU1UeYv0owhlXyBSKktJPjAtYfulNgCbSsAcjaasA1Xn3Hi"
    "xzovcVDkqhkCzRbj0P9eE384d1vM7yOMTzSha4olOim6v6qMn5prKXgA5oiktatUDJawWjb6exhn"
    "//BB/O3Gl9Fb12DanGH/nsy3YE56DuHxolhLcvJbnR6O4dwjN8ZlX9octmXDtAFd19zwN0mxxquF"
    "sOrTGh9qt9lXhdM+RFK5iPdrZJFzcuGQSpqQclKLXcFzkAcFThDRDT0QTj6bOPF041h5Is7ZZPcf"
    "VDQzJA8k5HEEOHKqIRMK7N8bJyMZQ5GBatoRCv9YOfXbaICxtQHOUWsgUFu6lBQdBzRexjlHbYIv"
    "/O/6mJ5uYqbFMDThhrzCB1eRksOyItVFFMZzkDs4XirACN5r2sDQcB1X3/IyTv3+YzB0gRnTVqK8"
    "8H0l3SennJqcYjdPMSS1ek2g2ZKYO1THFSdtjnftsQAjI00IIaAJhmW3AEsLMAnupKHoIZGnyRVT"
    "JefIGzj1+eYDPKnjyZGdoz1Cz5FBReo7ehhC2f4JuSGVKSwuLqCbFjpJiZQTn8IVTAoIQnA9C5go"
    "HmjBSWFl8qhFq//MKTJgKv01YfA4qWuSJFTptjeJ0kEnNd1ptQ336bjylG3x3/suxORoCwzhGHRE"
    "eQ2+Rp/CeFAa/uzVV7yN1kvPSPinmy0ZvXUdjz0/hk+efY+jFQAOMRCj7MckiDSV4PdHUyci+DyD"
    "HTebhx+cvDU2X7OOpcuazgbo1jQEESCg4OGLAeCiFmFpGBq1SByL8gvVe8g/kJI+00sROKX2lBvS"
    "qnTTwkAg5twDkHihaZjoHKw8VpAZ/r7EQSU6WocI6ggilHCpe1q0zhFi93F80TMX8IS5FO47DlCU"
    "WCPnbHDPRmv042dnbIttNx7E2JIpaJrmXpN0FzCF703t8xOB1AxcIfoEkt7BWDvQY4Jl2zj0tDvx"
    "/CvTvjFo7sJdAR584mKgQNRS1xzhk/fsvQZ+cNK2GOphjE6YqNcaSltYuq4r7Ec8pZF8JXEvnFhP"
    "4Hzw4RgvHJQARlBA3ogHArXnFpTfUik21KYi2gjthkCRfmJYhQ4+DZhiTt9CCqxcDuRRGHTUIXCK"
    "vJPflHjbjivj2kv2xDYbz8XYuISu11wlYc2VDnd2esnqhuK1LtU0lkLy6z5OV9EdtKUJ2zQx0CNw"
    "0qWP4uYHljq25JI7wFnko9jGPSvNbV+2LMYJH90Evzh7ZzQMDeNTDEPXQ7UiZ35IQNqKFkE2DqBS"
    "nkyH8GHm9DXEBXciSqIDM6dLsRaF2arhS+GFwqyKgUV2RfcsYyXnV+zEi9qDU4l6POXGflNbWkSR"
    "L+CcVtyGy+b74P5r4Ptf3BJ1gzAxafptPoqYOsaNXBBLsh8OUiyNOGjZ2KbA0JCBn/z1WZz/c0fZ"
    "p6Uw/LgMv4HLLShDI8fzUBO44LhtccR718TY+CQAAU0gADcpTFHfnIRF18lu3IGpCJVIS7jElTA4"
    "hQ2YlDcjpnCSt8ddkKPNSX17lY/ua+VzSJcSEUkw5oIaBjndxfI+SG5reieTUJI+05v0TVPi1I+v"
    "j1M+sRFmZlqYmXbZX1IETyeWEs1+IdAvKLW11FxEoN/xc6C+NoC+gRoee34xjr/wYRiaWxuQXFgo"
    "g2L2l7zPhkCo15yQf/UFDVxx0tbYb8cFGFk65pqSiihww90AXNs13XBrFsWXOZUkzBU1O+l0XSFB"
    "ws/r4KlHgl5YkADxxRxWxCCyVHY5b0HRD/sVhV+iEDctJBCKaL8lg1bpVVLiijrcnVMACaJFnPGw"
    "a4bTXx/s03HxCVvhQweuiYkRE0QGNB0huRRWwSIego5VxCeHBJU4Jm8jX5DVSR8MXQeTxOFnPYDX"
    "l5rO6W/JckzGzHZVMpmnXnPozDtvPg8/OX1HrL96D0ZGZqDrNd9JKY4Ho+IchKBKiVfJ7FJ3O46Y"
    "cRTqAlQgvpOEKCWO2QCK5MHoQKcsbbeiOBml0PeIADQSEoFQJV4phHxKVBLqlppJxmSJY54lnZy6"
    "C65ZeU4dvzp7O+yxw0KMLbNhGG6e70qne7Ba4nAKFRRuKcRhUCm4TOFJG8IpMEPAxufOvQ/X37sY"
    "PXVH0beUXr+3gaeECXG/EwRoGjDdtPHOPVbFladvj76ajtExEzVDc/0RycnzfS+CYMNjeLqGErYs"
    "RzgK4U1yUcc5pDrMGZsipXhjUgfiO1E0i5oe62kkForhJOf58tgdivI5FqjFPWo3CvM/RHKE2hiu"
    "aIUI3XEtk1zccipGxaQcnRBuhwrE9r6Fe2+eFff2mw7jytO2xyarNzDyxiRqNR2QFFa7Jc8qXCKK"
    "nQpVm9UTiqIaDAqIgpwaYKMm8PjzY/jp314C4MmTEewUI4tE12kfYxCLLk+ULxPkdBqOOWQdnPnp"
    "TSG4icmJKeia5igYRU84z5jU95FmxwubJSTbpYJ65nJ5ABf9N85H9eEKdPxSZcF9s8eohVSWpj5X"
    "U1UhBYbmbw2MCIUV7ZMagQV2ntYF5VbzLcdK45xJXLT4puuOccbbd16AP35rT2y01jBGJgHd0H0X"
    "YLadH1+5lwMenbogKOTbQaE8J4TwVB1/WEKQxEyziXVW6cFNF++Fd+++CkyLYTM72oGkdmWyh1tt"
    "5VKOY1h3aw1SAmd/ehOcf8wmkLYJ03SsxD13JLfXEUKpelXNEH1ZCGixVOfyq5lyxBLUDdOcDvXS"
    "ybFxRSVWWEA3NQEpBKEMbz4JzOskQ8CcD2y2TGSSeQIMy5bYYNUafv+NLbDKfA3Llk1AF1HXYOdH"
    "uou2TX7cn/xuLYViXO29he//uNZjruUYEcGyCZuuP4Rfn7UTfnnqDthkjX6n988ODBmFpK4UDoei"
    "gEO+5ylBI6BhCFg2o79Hwy++uh2+9LH1MTJuOhu8pgOkgzTN0SMgAUCEC8f+ZmYrNmbdeIZc2FU4"
    "r+139zy3OJ8gSJyZZhkLsTYMeIZkV6hdwWFiBoMjkT8pbR6vPChSwiku5XuWVJDRBEETlNs+LUqh"
    "jsPHs2vQ+fTrJg78/H24/b7FmDesQ1gzsFozYLbdsRA+AxIUptiykgGDglC6jePdxgVwt1/pwWUB"
    "IRgzM01MTDfxvv0W4obv7YYzD9sQc/p1x9dQc8cAyX371KnIrPgTArWahhlTYs2V+/C37+yGQw5Y"
    "B0vHCaLWcG3HPbyK444U8idQNkeWLv5HOpuZs7GVX2DUoUcexxxbVLLD1OmhxZxjAwgVKigbNMGc"
    "rsGWSXiJeS8pBJYQoQHkGFfEfQLlf8pFc3y1MMXsOPnYrjhnntOQY5xjKORW7KjXWDaj1ZK45o4l"
    "2PvIm3HSRQ9jyiYMDzUgWYOEDpBw237ef8kh75LwEYBqLUMt7Hk/PtFP+Z9HwfaLgywhBEMIwthk"
    "C329Gk761Ja45Yq34iMHrAHbdsbA0EU4xC/qpuOKnU43bWy70RCuuXgX7LTpfCxb1oImNNR1Hf39"
    "NUDTQJrmzgcOmKPMyl4YToEIDEjEipN2HPlSAbeskspRVCoFoJiUNtjsRScmCrmskQtiPdtFIMLf"
    "wkqxy4EHc5sgJBRdwTI1gETxjUhuKt2Fe+anNsIXPrgOagLuIiBoIsEhKc6ePJo/RwBDmiBMtyTO"
    "+snT2PXTt+PX/34VA4M1NBqai2pzFzxpbjTg2XdFZw27YT23uSn7LLgIgceXjxIaiDSHWGMYkBAY"
    "H5vBuqv24MenbY8/nrcDNltnAC1LQjIrrLzIY4x51t4mJQShpguYlsS791yIf168G9aar2N0dBQw"
    "JzBgtPDakgkcff6DWDrRhO7Zkfs36mhEtKU4EbOZMpEaZW1gHC9uSwnU5jIIxDL7lsrbDYRfguBP"
    "lAlvKDN/peQbK9K/lAh5+rX1kplCPVdWpVIKeDK1vTShuu19T113ctOV5tTx+/N2wkmf2BjnHr01"
    "rr90T7xtpwVOkUw6iD1RgU6gLZ2VauiEJ56fwCEn3YN3f/E2PPPaJIYWDIK0BmxogNAAdxPw1Yok"
    "Ky6+5MODFdE5PxcPewkEIbXjA+iyM0VAx9YEMD3dxNjYDN6x60LcfNme+NqnNsJQvw7LdqIBTSNw"
    "xibM7NmUOUImX/jfdfGr83ZHb6MP01YNWq0Xc+YN4YGnJ7DvZxfhB398DtK2Ic0ZwGo61uhS8S3w"
    "rpkc2XLPw5BIc+nl+UhAnKMKzykkoNiiKBUrJFOHsOSoulSouB/dAPKGwlwiTOIS+RSzHcB9VVvs"
    "WIZiMueQcnq8cQbYAwTX2kpimw2G8K8Ld8c791wdo6M2xsdt7Lz5SvjrN3fF5V/eFuss7HGAMu5p"
    "mJgypZyQ0Xs0LfZ5/3+44VXs9onrcP6PH4TQbQz06zBNG9K2g2KerVT3VWo3hTqEQXqnGIGQYrvq"
    "ZwxQDEY9HQJNQNM1jE87sNwTD9sUN160K96z50KYluMBqGsxdQ6lTlvTHc0+ywLO/9yGOPczG2Fy"
    "YgbNmRZ0zcDgnEFcde1i7Pf52/D0S1NYaa4B6Z4OXjfE4ys4numsIBQVIUyRL1RPlRwrKhvf4THe"
    "Ce+nzUcj5s5z2YPHFwKzVUiRQ3Yr/U0UKvZxSc9uzqhKcqS+EdtXEB7rzMZBuy/A1d/aHpuubmBk"
    "6Rh0MiG4ibHRMUxNTOHQ/16Imy/dFUe/dx3ogmDZzsJVEWih78j5lL0TzrYYdUNg6ZiFY8+/H2/5"
    "5DX4243PYqgfqGuMlmlB2m5RTaoEIOn3Vrw830HGCQgSilpsMPSkCoeqD0EoEQI5BUDblhhZNomN"
    "16zjV2dujV+ethU2X6cXlnsthkZOhd8tGOqaQE9dR8uSWHmOgd+dsy2Oef+6WPLGBMyZCdS4iR6t"
    "ibMuvRvv//KNGJ1oQtec7zFqGkgzwEIPBEy4HTfCIZBTu6Zj0Zyfq2gdlTzSqaQwCCd4oDt7InPm"
    "9XDsjsTxAoVEJSqlKSKhktuFCSmxupJ/dFUasMIbQUIvWkrnBP7KxzfAL7+2Pfr7dUw0GUZNB4QG"
    "Eho0Q4cwDIyOmxge0PDt4zbFDZfsgXftvhC2ZEi3PpAqRhoZU7VoDwIkOz34pulEF4ZOuO3hUfzX"
    "sXfgw6fehSdfmcScYQMCEtK2fSJMKCP1ePFE7cEsh5mCUHJ0/9RW1JQkBxRbAkPXdMxYGiabjPcd"
    "sDZu+eF++OYxW2GlOXWYNkMTzkHsREbAdNPC1hsM4C/f2Q3v3HsNLBlnkDAw1FvDjEl4/yn34KRL"
    "H3FqCm7Bld20iEOy5F43RAQOUV6cK4PNUOUJdBpWU56olpN1+Sgnci9OISlaeGfOSm/b5fzYxUZ1"
    "HGYwwjz6wvLYSbtsyPdPycvzuKIUtAaLy+WInPDUshlzB+v43Xm74Iwjt4ApNdhsQDcMN88MJKCI"
    "CIZuwGYd45OMnbaYj99/c3f84dxdsek6QzAtZwJ7aUFI01BZaBwSnqRYcI+jyBtEFz/9x0vY9ZM3"
    "4rTLH4UlJAYHDViSHdck4akAC1fikwLtu5A8uFJGaVNL8mTCpLIXq0VH5/OFZkAz6picJhiagWM/"
    "ugnu/PFe+NgBq8G0GabN0HWB6ZbE/tvPxd+/vTO223AYy0YkNL0XcxfMxwPPN7HXUYvw63+/hJpB"
    "oU6LZAJL8sN8couAQjgbAfmdIYqVGpbcWaeduXMX7HRaL+d6L5ddrFTQGARdxsVz1k7IaKMEq3DZ"
    "sOtJ2SikHVXoqe1svu4grr14dxy010KMLZsCbBMkLbBtuQUoN+/mYHYRCJoQmJyyMDHRwjv3WQ03"
    "Xb4PTvrYhhjqE35urAsKCoXsnPDRQWEEOP+4DdaLLnSNMDJh4fTLnsA+R92Kv976Oobm9aPR04Bl"
    "u9VyogT+ASn9+KBdSC5SR6kI+KmCVxB0Nhfy+0oEAFKCYMMypzH+xihWGdLxw1O2wd+/uRt22HAQ"
    "zZbE4QethT9+a1fMHezB6LiJui4wPKeB31/7PN529C144OkxNOqag91nJ2IJidLE0NRDsqKU5PnM"
    "xduTFWMEKKOlnvRZpaY1t2fV3o/eOd+43EBxHkUcpTomfD96ldVG7QwKiuzE3C6RnsXAUjn3B+62"
    "Cq44eUvMH9AxunQCmi4iLLMwmIb9FqVbKScJBmF8ZAq9NR1nHrMt/veAdXDWDx/Cz//5IizpavrZ"
    "wclUdqwt1zRU1wTufmwM7zj2dnzioNfxlcM2w5qr9mJqrAlbKlgFbk/w2kqpsl2rnNrw1xxVZvWh"
    "3EQEoWtoWoQZm7H/Xitjl63n4sZ7R3DAbivBMi1MzTTRVyNIMnHCdx7GuVc+7isezbRsEIdNSYUb"
    "8bgg4aj7VUw4TCFocBmLjVIGpVntcUUNu03vMEZfvOzibwe+BZVf0UkVkroOI2ZFEDGyeN0bo5AL"
    "AKXKNGe1drx8H8Ih4HzpoxviN+fuhDl9dUxOA0a97qjtCM0PNUkF3gjhtJ80V0pLBIU2XddhS2Bi"
    "6Qw2WHMQV56xA/587g7YbqNBmJZDufVw72VyUlIQhZYloQuHS/CD3z+LXT56Db75o0dAmkR/v4Bl"
    "WWDLdtGEHCokURSZSGGBxcAHUPEHVNWFRYC5h6a58EMNQnO86sfGWjB0xoG7zcHk5CSmpycxPAC8"
    "OjqJ/T9/K8698nHU3DqJaamphrrROprFPvZHrUzJyN5MFFZDJhHmQpRUKaqk4K8k75Qhq5eV6xdd"
    "f15XpyNvwKTWnurOEtf+yRt+ebm16lBFSsgfXuftCLdiJUjHTceyGX0G4cqvbI2zj9oErRkTTVM6"
    "VlpwkHAUqs6FQ03hc+8DRJ2DQJMgKSFgYWpyEmMj09h/5wW4/sLdcfFxm2HthXWnWq7UBzIBS23Y"
    "8uBfbOl0Cwxd4OUlTRz/3Qex16eux18XvYiBfoGGwbBMO+RhwCEOBbUDR4RQeO0ckaniUIoZLDLh"
    "jId05LgES1gtE0uXTQK2heHBOv54w2Ls+ek7cf1dS1CvCX8cKOJGpBI+pSRFFcL9H6suTEq/ioqV"
    "/dKk8osehBRrhxazhqj9d9EDsxQmIOPFourWpafaywk7FmdFYW0FCgoPDEV02IUyNIoYSKjFSMkP"
    "RrgtrEbNCfm332QOrr9sT3z4v1bDyJJpkJSKMm/Mh3FYVFVGSDpBTu31qRlCI+i6hrFpAIJxxPvX"
    "xS3f3x1f+NB66K0Lv22oUcQw1SXKCK9uQGjD//sDTAwmhmlJN5wm3PHIOA78/J344Kl34cnFMxic"
    "14Aghul2C0IwYvcU93D2oQhAjQrIdxBwZcWUDVhyQMKhYIuybaCvp456vYYTLngMB51wN559eQp1"
    "Q6SIi7KizkxtD5KpfYWION/wgrErd6BjSAn6kZwSDKQyKYkqwwUo8586zucLA4Uy7cEDL8GAspoA"
    "S1Yr1MFRlc93lLwo1envf/zAdXDt9/bA1uv3Y9mIBd3FtZN00YESbb1m/8QhBJ4rvpahQsgh5frc"
    "IFYTzgMdXdbCnMEazj16c9xyxVvw/reu7lS9GajrAs4apLYuSxusP2JCoZ6YXrdA1wg//8fL2OXQ"
    "G/C1HzwKSxMYHK5DIuASqButdFtnrLAIydVhDMkuqK1Ub8NTkIYMApOAJXUMDw/gjTEL7zzhDpz7"
    "f09CczkGTdPxr5cpi8H3pSQRiVIi9SAKKyJVQa+jIqI5Scd5J/Qe5urECakMF6BDWjBRPhdWFQIQ"
    "rV4yxzuvhqDG7KBiU/uqDBjCEZmwbcbph22CS7+8NXRIjIyZMGq6Ax31MHHMkK6sdGhD8ha2Qmtl"
    "T2RFekQfhZRD4bSa2KkPmLaG0VGJzdadh198fXf87rzdsPm6/WhaElJ6QpfBApfMheezZx6ia4SR"
    "MQsnX/Io9j1iEf5+22L0zxlAb28dlu1ChVwmkC8L7qLrmMOazKxAtaG0DlVSkYNfkGBJGBpu4M83"
    "vYTdDr8RV9+6GDWdYEtHbjzXyeUrQHNYnp1ZATlxLEa/KP2WChbCKSbPLtNVqJQGTJwabQhm7sqF"
    "xUYGXMxHPeTGqrhYI+Q+Q2FDUsWkNC0Pq+kE02assaAHfzhnJ5x86PoYG5+AZdmYM1AHmMBCgDSl"
    "uEeRHooS1gYnELejzkgJ4xUEHnmf74b1hkGYmm5ibHQGB+29Gm74/ltw2qEbYrDfuVZNU4ROCuI3"
    "1Eu2XUWfmiFwx8MjePtRi/A/X7gODzw9goF5PTB03UXvqQsrWPispjkKSMvP/71CoHufli1RNwDd"
    "sHH25Q/hoC/egudemXZ0Du3iMnR+FERRUA21wcPVAjFnVALisSCUYVKSDi+m3Isn2Uins40h2Yyc"
    "WHHeqxzGnJLsx+GrOckkJKJCxIKCcFQBNQTwVrcCHXH2IQHogtAQAobmWGd/YN/VcMNFu+OAnefh"
    "tTem0Ndbw5QpcO0DY+gfMtCoG7AluaYjYR4CxcwEpiBPU2G1voW4GkT7kNugKs1SQkBCIwujS8dR"
    "I8aph2+Kmy7ZCwfvuRCWrXQLKHuhC3I2DKGy+ph8RKFpOt0CQyP88p8vY7eP/wsnfPNOvDE+gYFB"
    "AkkLtluJl56gCFOMr26wK6r1DoaD7x/s78FrYy38zyl34sRLHoJwU5GWyZkVN6I4VWMEKQaFHXPi"
    "WCBqvdb5CxcAuHWmCMWKoA0V3KwZ1XQj4ta4R4kSXPJjifK5oBDK212H4atoF7REMBHC2HoKP2Ny"
    "2kO6RmhKJzQ/5/BN8dMzdsHKKzWweKyJ+UM1vLp4Gu//8q044KgbcNiZd+OZVyYw0AfANGG1mpDS"
    "VpJTochsubGvKz7R1kIjRESo2k/OCB8YuiYgAYyMzGDjNRv41Znb4Hdf2xY7bDzkY+tjSUYB0ldp"
    "7QVfwBSOjizJfnQxOSNx7pVPYuePXY9LfvssRL2G/l4By7Qc2TFvwxKaD3/2W6LCg+E6nQIpbdit"
    "FgZ7gWvueBl7fOJ6/OG6V1E3hI/qy6LUtlfk26tvzrBzKP8LoNMc1rAogAAs5GvA2ZTcTHIqUeHI"
    "jjpQLPLSWoGUVl4qvZDzbwRZGgpJNxumdkdAKuHZ7fLcLcCeAawZmJYd+nDDIMyYEmuvUsdfvrUT"
    "vnjYZhibNjExzVg4tx/3PD6GfT5zM66/dwkAxuV/eA67fuI6nPd/T4F0xmC/BltKH/nmFRspwrkG"
    "WBG+ZJ+HHSj/OIswMGlUwmwfweiSdIhg6AJTMxbGp20ctPdCXHfRLvj25zbGavNqjjine5oKV/HH"
    "j1RcGy9H3ct1BvKj9nZ6tW07b9I1wvOvNXHE2fdjn6Nuwr/ufR2Dc2uou9EQlEUf7fOSAAQJ2KxB"
    "1w0M9Ndw9pWPYv/PLcKzr8744Cop1QIiFeK2M4LIxutKkOJ1yCGPWCW6yu05VB3KNboxp8LuY/0p"
    "05k+VXQDRBpQIPM6O5QmzXqrJlT/etGuFegp2vjoKQmGDUjbl37WtSDcfP8+a+D67++Ht+62DpaO"
    "AiQMLFjQh3/d9ToO/MKdeObVJho1zeWyE94YbeGLFzyEA467Hdc/NI6h+UMwGn0wUQM0AxCOIo+A"
    "CFkuh3m3FC8tzYEOR1QojvwinPMZmtCg6TrGJhzoxtEf2Qy3X/k2HHXIhjA0BwFYMzS/ny8V3oua"
    "RWXxPlhBExo64eb7lmD/z96Ow868H88tszCwYAiaVoNlKRqCtgOFlq6WoGVJDPTVMWERPn72vTjx"
    "e49BE04R07RkDBSZyzHsBMUYyUYIMi7+IlptJup8CWXZdkfbd2qRuFC3oSr0T1x03UkXgGJsv7Po"
    "iVRyg6AQCYaC3rpCV3VKDgJEBqAb0AzhtPdMCZbAtz6zIX721W2wYEjD0mVTqGmMocEazv/pIzjw"
    "2FswMm6ix+3BC3KgubomUDc03HjPUux31M34/DfuxNJpC0NzGg7t3HImvvR4AEr7i4JCup8XI1QZ"
    "ZgUopLQ4mMOwVe9oFxqMmgEhahgfs7FgTi8uPHEH/OvivbH7VvMx07L9Cn8VbV3bdgqlQhAu/8Oz"
    "2OXDV+Nrl9yLGWmif4AgW03YZhMsLV9vz2y1MNBHuOfR1/DWw/+NH/3peTRqwm9pJjkmF89mOab9"
    "oxwOFAi7sOdMrPREi0iCUYmOXFudKKRpyaUAduiCLGhiBNBpSyApL+KSH01qwsccmQqKHhBJH5de"
    "1wlSMtZfpQf/+PYO+PwH1sPY6AQmRkfRwBR0MY3Pf+MOHPvt+/2GlrOIpEOuYUeVt2XaPhX12z9/"
    "Bjt/+G/4/q8fQK02hd6aBbvVBEvTFaXgSPvIbVepkFSgrdfun/oKyYZcgo0HyglEOyU0wWjNTGNs"
    "yQh223wA/7xgN3zvC1tjtfkNmDY7JhqCEseVUslZgVS4aTknuhMNmTj54gew20evxs+vfg49Azr6"
    "+htgGGCqQYg6hhb04bI/Po89D78R9z05CsN17ZUyWswteSioLs8Ukd3yO47c5oAc7X8xc+laQCr3"
    "PifJbTYXetyFKHCU4htAmtMvVXRz3OaQIn22XZip5rXoNEDTQcJwZKKFwPSUhbduOwfXXLAL9t5u"
    "JSwdsyGhY6i/gYmWxH8ffxu+/YsnYOgEy1WuiRM09cJi73R97pUZHH7m/dj/c7fijscXY2DYgC4Y"
    "trRdsI/weer+4lUkuSlicaLKRynpfwjcolqcS+k59jrc+vHJFuyWiU+/d23c8oO34JP/vQ5qbqEt"
    "xDSMqA8Jt8agctsDjH/4x7Q8khHhoWcm8MGT7sI7j78ddz0xgv7hOvr76tBqwOfOvRef+vo9mG5K"
    "xzLc5szTk4sw3UKcJGrnfyjiHwS3AOjbJFEhHCAl4XpyROScIQiqlq86xOHl5om004m5HB2YU0IY"
    "zjm6ee9Z2uRP9mgCxwhD3ggCJHToRgOtJuF/9l0Nvzp3F8yfU8fouAkBwtzhBp553cKBx9+Ja+54"
    "AzUX+y8jlWZBHmM+WCRETsVckNM2+/edy7Dn4Xfgy5c8jglbYHC4HyANkt0NybXiYg7bRDGropuh"
    "BprvogylzUUqDTjEvCEQNGiaAdJ0jE1IrDSvju+fsg2uvWBX7Lv9fEcLgMOSXGHsfiC3liVly4xQ"
    "0fGvixZjz0/cgM98/U7c8OAreOfnb8IFv3gKuiuPbtnFj4BMmLiPNaBQ/z2kW8AOejGcPwftQs9j"
    "MNaKhdLUqwpU5xMEUL1dPM5sJ24zoI6kLrgNkcguVN1RUHPGSXQS9TPKuaRwkfYFq71zlfjhFpBI"
    "LUg4mnBWy8Y6K/WhbtQwbQoIoWN4bh1/u/Vl7PvZG3Hno6Oo1xxr6zauAtxBUjj46rqT7LbNhFNY"
    "/PoPn8DOh96I7//+WWiGwECvBqtlOdp8bAfafK5JBTm4WgXuHDz9kBUZh5GP/m36ohcUan3pgmG2"
    "LIwum8ROmw3hb+fvgl+euSO2Wn/Qj27UEz8wEuI21FqCs6SzKbtoQk0QZizgol8/i7ccdiOuvuMN"
    "aK78mS1j1HEpHzo2E3vP4XIJK48/YI+qnSMKKR2lzUBmdCjLRbFkojwWc/G1PortyOW7zuC+hRBh"
    "41e/QF1wA+BZcAwKMdyE03JzgDhe6O8029mTkvZkoXxdP+fUbLZs2LaEgIHBeQO4/M8v4t1fuhsv"
    "vj7j+O21ZG7Vlrid3+tj6xrhyRcmcfhZd2O/z9yIf971CgaGdNQEYLUcwRCHo+oJUwoIjXy0XJAi"
    "qBOcfQPNAD0Y8fBT6iIsGWxLEABd1zE5AzRNwvv2Xw83Xf42nH3kxlhjQd3pXmbI1HFOHLot2TdF"
    "YRfJaEtObQWXnRrM8ZYxpERIcG2vfUBYTPfDpxUSV965UiO7TsBEyQSoYpG0ZCdam5icxEMPPdSm"
    "b0kuv2S5KgIlqeSyygaMwEr9/Nqt7kpFjYeUsMqSNnTY0HUbx51/Hw776t0OBNbF/1dVX/EENmoG"
    "4aZ7l+KAz9yKT5/zAF6ZlBhcaQCGYfiy2og6EkeKUszsd/9CS50iajbMCLHgvW6By+bTNB0kCCNj"
    "EyDZxJeO3RwfOXAN5+ROQBEmQbKznGVs6eAekrD8HCmMcpVGahwwwoKWJwUiry4gjFhBjlbh+z4r"
    "SAJkQJApk1QHEGzbxrPPPuNvCkQqFJ2yFYHyuP+SC4kryivgGGtk1feHmXxGkKq0w77dLTn0U/KI"
    "KgAgYdo2+hvAWJPx4VPuwl9uetVV3Qny/XC4xgXdfim0u3vsNUN3qvaX/vop/Om6F3HCoRvh/fus"
    "joG621dTUI0caWqprUDfzSaq10nR8BCBVHpEBF7aEg1doNaj4ytnP4Tzfvo0aoaz+cU9puBzOM7M"
    "L9WXnnPCQsh/jgnXkGeT8MdE+kSk0Dnm6RqyaxzD4a4hyEUO5rIxzz69OcsVOwH+nvW5lIM1mxU2"
    "ea+Znm6G/LVJeWCCUvr4pLjDqByYOI6/IyyRfHJEKZtJOOc2YAjB8XxX8lVi6V8bCwGG5xDjtK2G"
    "Bup4+rUWDjzudvzlJg9+GmYXhmyyIhtZttsvh3rLXmRpWgzTtFE3BF5+o4mjz70f9zy8FI2GAcnC"
    "P6WD3NDR3BPkFakorOHu7ixqe4sQhtAGHYQANmnZjN5GDSYL/O8pd+LMyx9xahdW++lHMTRsRLQB"
    "ozTYJFVczuhthzwAUztWlLEwOND7djeDEFOeA1Cw0ykil1oePWLSr4Nze1jGMA/bMErJmo5pi7+s"
    "PqFkhm07aNgbb7oxiNhs2y8CM7MTAVCMaEHcXwKftcB0Pu6l3i6vAoXUUJAzfAPbxEU44PuRYhhK"
    "IRSAgM0Cg/MbuOa2V/GJr96D51+ZQqOmYaZl59pdHd0KDpWXi0aLqujqlz++IQ7Ya01MjFvQagLE"
    "UoH/SpfSS22W3UERMKAaQ1k8PgmGFS0C1+nRNC0M9Rt45tVRfOCku3DbQ8t85mMgppEExsmWUWs/"
    "9ahd046ozeIstWLepoXIbZ8b1ZJkD1LN8J2Q4JO3XelxZY46ReQCpfwE5em462p79pyynnKc9Jyh"
    "T5hXV0NKCUGE+++7D6+++ioWLFgAy7KgabqzpogDWfBYB19Q7MnHcSdG2+mR3TkIt0HaRSctv+ct"
    "w3EBhYtokhwE4MD8Pnzvt8/iwGNuwQuvTqFmiLbFn+UHyBy+z/y9VrjKQhpmWhJv23EhvnbkNpie"
    "aEGQCUgTUlqAtBVmoFKVh1vgZLXExYpkuhdBiVDYLxEchpbJGBruwc2PjOAtR9yM2x5a5qvshKXT"
    "sowr2ntSlLBgYwtfCRW/aBRI5AmFhHv0HoMyLexlT5Qk4nrjGYS0z1HKNLnN2wanlIgnCuSMc5ei"
    "pHQnKnASM3aFZPyZUWs08PLLL+Puu++GJjRYLkfGo3KI9hNQlVni1GMu6SJJxUATlS55SHZpfGxF"
    "wO1BLGoxwdDr6Bms44Rv34Mjv3aXw/wTAqYp8wud5nErzsBtCwIsW2LNlRu4+AtboDU1Abs5DZim"
    "b00tvaq9IktEigBHWPwiSG2IwrOIXQUfArmfCQzOq+FX/3wBbztyEZ5/ZQo1l3zDKSQv4va+eqi/"
    "1kbRzlcojIHpx6YUxOyrB1MMeSw2nQwdTqpkemQeUph84WsE5PCVIMpX+eOsFCLaYeEMQpBSGKa4"
    "tDOLhxDZXDQhIKXETYsW+RbxRCmagKxiTdLaD5FchiJCDb5Pe/SiE+oEcRFDTXdXFWluIyDQqAck"
    "TNNCT01idGYC7zr2Wpz7w0ecYp90YLwchYlS2CMnV3snZoeOa3FpWtAV+M6xW2C9VWtoTpsQmtvF"
    "YOGz05ydVwSbLHNQGFNsvNT2lj/VZaCMQm47ThNAvQc4+cL78D8n3oaZpglNI7QsGXGQ4VhfRT/l"
    "4LACMPK0nxKa+2ls0SgSkGNQQJRg7hyKnKhd517VhFTbqIxibhpxvXyKSnoT5XL0DbkgFxE+KSCs"
    "k3S4WZYFAPjrX/+KmZkm6vWGz13hJFlwNdzI5aYbSiMCYYg4cESmpTgFHm+ORLcOCB1EjkSXB/+1"
    "bMZgv47n3pjCAUffjD9d94oDgbWDlhS1aeRF2mcxNkttStg5/3gOQl/5+EY4aJ81MTbJ0Ot1kNAd"
    "+qwmAM3TshN+eE8cVrCRFBH3UwdLBlqG5CrtNAwBSYxPnHkXvnb5E9B1x7bctrkQt5yjQJG8ohWR"
    "kzcZ4BKQuZJ0JNU9IBGur1oZe881tAOQoq+gYAQo/bApLAyitm/b5n9ylJgFdOKC1f62uRu5UdM0"
    "oWkC9917L/71r2shhECz2XTRkpxGB+bMEIgTLlgVrWwzV8xIQdXXS6kKfjpFHwkHiTYwpwc3PbAY"
    "ex12E+5+aBkaBqFlykxzjUSIJ0WUXDnfuBCAukGYbkrsu8N8nPjR9TA5OgVNc1tVIfkslbgUVnl1"
    "CnpCkbYOFowvc0GB9ZVpMwb763h9bBr7H3UTfvKXF1HTRUybr3rFJ0559skhNecgJMelZvFVs5DY"
    "lwe5ZpVYhRD5StVwLIu/55hUl2K0AOPWSSYEmjrn+lAM21JKCV3TQUS44orL/eIgPIOVIpJgpPSL"
    "q7It4lSnG3LqYi4ZyLYssGljYEjDT/78FPb/7C14cfGMU+wzOdHii3I7qBTHiOi601tfe5Ve/PDk"
    "bcC2Qw8mtUTnoZTbYl8OFaYCoRC0n2IIfmfZwNCcHtz62FLs8ambsOiBEdQM4dqR5x9hys2Ao47A"
    "XdGCb6f0dlZ1FVX6r1IAdMOkEL4kyBlEZ4YfajE8FT2ZYy3lPBgLbwakojYlajUDf/rTH3HjjTei"
    "r6/PAdAx55cEoxwJSBq4o8hNeQNjec17acMyLegAenoJx5//ID5yyt2+1HXLlJlU126gtzyacG9D"
    "wxWnbIvV5zfQsgm67pqGQmsTEg3jHCjsaYBooU/hCBDBdluig3Ma+PnfnsF+R9yAZ16ecsQ1Tdnx"
    "5pu0zjmHg3SnY55vj6GQxH+oDBitLRGHdYC8kz+CxUAX8a2Zh2tCukUdDDZFiFXkRgHSdtKBM8/8"
    "GqTtibfYBaDACaYEeYqlRe+HI90GmzX09Q/A0nrwga/cg2/+9EnXJz7A5HMRvkIpLnr74/TYhGd8"
    "akPsve08jI6b0AQC+U8/5xXtrR2K8WjhQDmYhGK+SQ6KUdc09Pc1cNIF9+KDJ92BmaZ0in1mRdDm"
    "DHQed0BD5wok7309Twqo2qr9eXjhtC9AjileV3lQhA+77FSHkW4SUhV8WEoJy7bQ09ODf/7zavzq"
    "179GrV6DabYcJGCeBRoHyiicK8YZTKbcRs1gWNyLobnz8dziJvY/ZhGuuvZlNGqaw9jLUbAqE9Zn"
    "zVBBQL0mMDVj43/2Xx1Hvns9jC1zSEaqbDYrcqVRn3ZqL18HSEQKJ4+WxehtGJixbHzoK4tw1g8f"
    "Q80VPLFtrvQ0phwF30p57FQw9FatwJL4+RQvD593IlCHY1XpvEtNIfLPfXaRgUSEL3/5y1i6ZCka"
    "jUYABOKipJ0cvdQ0cVBOlHoLdm7LYuhzCdfc8Rz2+tQ/cfN9r6FuCDRbtl8g5A5mFhOVikw04bAJ"
    "d9lsGBcfvyWkBIRuhAxDFVhKBBjjTcqYWevzfILioWUxBgd0vLR0Am898nr87B8voGY4RUDJxZRq"
    "ciHIck2mDqyq0+CzoNyq9lIV/6QAeRNt13H0ojmi3BxzI5xQYKOCU43yyDBlJA5E6V2TIn9arRYM"
    "w8AzzzyNz3z2MxBCFCMDMYrZiFNOqGn0pqR7Z0PDdfzuz0/iAyfcjKblkG2aOXNdihGbjMI0y2ia"
    "1nSCJRlzBwxcduLWGGzomJqxoemO5j77ZhWkKBepbS5qSynYR1YrSC+WYFticKiOf9+5BB897Q68"
    "8Pq0U+xzx4BSADp5CCrJ9RdGDq5JRwSyeD8Izp5zpGJVWGkLRshMIalwb4eU8RtXjpvhrFQ1CeLL"
    "8TwBTvh7dAziBHi4g6iBbRv1eg0///nPseWWW+bbAKikvhmXPBKcnJZw4S8fx72PjqNloTCNl9MU"
    "ZyIgpSJ/hCBIi3Hh8dtis7UHMTrehFFzgD7B6ifFxCLcl2VSjCJUQVC3cC3gbDAAMDhk4Hu/eRrH"
    "fPNBtCyJmh4u9nFRQAtF/RSr13MovGFQPMEs+XzkkG28ippTsQOeAUocdZioetmtOIBV3rGI1n/z"
    "trAp88CNUX2WNoQlUavVcNppp+XbALjMTlOBcvjtD475A5zLOy7ztCPfsLLo6ejk/RqmmzZO+MiG"
    "+MABq2Fs2SR0nVxiRQCdprSEklXCUKBYw25qYNtArVZDvaHhs+fdhQuvcnQLNUFodahjwLOiQtk+"
    "D3zPROZY85jC2zpHgEKq3p/PL0hOmmVG+kqFHbFzAShjo9DY6KYAgaq4YI8HEnM4AXpaxTvuNKAE"
    "D7WkSjyXFgx1xDvSFFGKT3AuvSB0XWC6aWP/XVfGGZ/eDBMTJjRDd0E9HvJRTcQpwnb0w48Aiy4B"
    "JtuPAlqmjYFeA6PT0/jI6ffgqmteQqPmgHtkgcq1cF2HEzdNKlD04XgWHBXsulAF6UnU988n/bqK"
    "UT4IyLNloQgoP8IFKHvgRRmtWVX7UIhfsACTh11IOSIEimwwtm231wBIbZXkRdJlUCTbPNKyxBhU"
    "zTrJhV1VueTv0yaj12dfb9VeXPbl7SAtV99PqBqdKoWYQicCtZHoAz8hcncC05IYGtTwyLPL8P6T"
    "7sYDT467uoWB+QkyThkh3M6Au/C1BJmu3CccJ+einBDKJ4Gq4tl9xcLrgBQe0MR9CKf7XzXF8vUD"
    "KdDAqyIM4oIbmeJjWlgAJc/l5m59c3t7UBB1LuXNua2qOZ8OH5e8pgKuK3kHWrjFubpB+MHJ22D1"
    "uTpaMy0IT2VWeJzKZOo0VBsAH4nmcQIItiQMzanj6ltexx6fuhkPPDkOQxcutJkDy0FuM8fxcS26"
    "JiAlo6YRzjpiPeyz3TzYkiFE4BGQJOiSF82X+kw4LNRZVXuwbS6ws9GRRopOpCKnrqhHq14M7Iqu"
    "gKgcDiSBJp93T4lFV1LnY5XW/cnz2SLr4vOCeLhkezeOiFP2ySRFIXHMsihIKe4rNQJqNQHTkvjG"
    "MVvgLdvNx9ikBU3TXCKlYvpNYf/6kKWJuygkKZNTCEjoIK2Ogfk9+MZPHsc7jrsdS8ZMGDrBtGQC"
    "cy/MFSIi185MYqPVe3HNxXvhy5/aGn86fw98/ait0FvTYEtGTReZ7V5KaP1RxQWzXHs2J8uCC1eE"
    "lCIiNT4fIIZP7CMH3E23I5QdOsdeFEltU1uiOTagkDtyNF1El4A0nGWWmMrNx+xYI2UYNmoaYaYp"
    "cei718Fn3r8exsZM6LoIQ5w4qE37Vf9QRcjjq4dltlomo17ToemEY867B1/4zsMgIVDTBGwr/xGt"
    "a4Tppo2377oKrvv+fthj29UwtkwD0MAJn9wK1126L3bcZC5aloSuOXZpxbT4qNLHkVUBzwPK8bon"
    "gd4EK639NgOEtqIUdTJn8kKbO2jddXKiJ+ChYnEDHN0ACOiaU0lelBR3sCNSVT1rAD01gZbF2H2r"
    "OfjuMVtgarQFQRLwZb45pGFIsQlyEO4HnH6JZquFgQbwxsgo3nHMv/Gd/3sSPXUNUrqGGhQvqBHl"
    "IRCApilx9CFr47df2xZz+jSMjk5BFxKQFsbeGMN2G/Xjmot2x7EfWA8sHZuumiFyFWUpx/KvFBBI"
    "+eaQdDdVijP3UBCVvkJwYouOSs/jOBOcjpyxqLz+XxYyMa3uJbLQRaqxQ9K3UUmDkKwQvGiUwRVM"
    "SgI5akIWY8HcBi45aVsYZMEyTcVlJqIYG+Glky9ZRiF6KhNgW4w5c2u475lx7HPkIlxz+xuoGc4p"
    "btluzs9Ba0kIJ9zVhONIVBPkOxj31AV+dPLW+PYxm6DVmsHM1Dg0OQNuTYPNaegwMT4+jRpZ+OZx"
    "W+Gai/bAFusNoGVK1AzNcfHJI+RZcepHFI/Tj4sGOKY7ZdsSMmL/Tm2fE2gvklv4YMmlAvg0WVBS"
    "nKNC6G7KvxEQUVh8p0IeQFY0JrIw/YEGYEqFODFbyx7QQhpnGVyEouGWz5hSKthCA3QDsBm47MQt"
    "sOkaDUxOWdB0DUSae6JTYNzpef6RglBXGrWebLlkAeY6Blfqx8/+/hL2/ewiPPrchAvuYWQoRPlb"
    "as0gzLRsbLTmIP75vbfgoweth5EJApEOoQu30CUVxyANNguMjdh4yw4LceOl++Cog9dH07RhM6Fm"
    "iI5qP1ky2clzqpgUu8+eczEhts2KfiPahEkVAEIkEwgJz3e2sBRXJf85Ubu4SV6OQ9xaoAy4OnUY"
    "mQlOoIBRBxMhy9OMS9pWU1ZbqUz1X0WUuvc93ZQ4/bD18a49VsHImI2aYTiqPkLzVYmAMOafFdln"
    "KRX/NQZsC9CEjv5+A+dc9iA+fMqdGB1voVF3TnLKVHd1JMIkARNNif/aZQH+fdFu2GXTuRhZZqJm"
    "6NC0GjTNgNB0kPsDofumKrqQGBuZRF2zceEXNsNVp2+NlYd1NE0JXac2x94qyCxlHG04V5ysak+6"
    "pyeT6w3BsfJins8jqiQyFTA+7eQDOYMX0Uk0INLEMdJEBsraJ3WixsodbDx5vrrh0nvfuftCnPjR"
    "TTAxbqNm6KGFrv74JxkHD4ojiZdlSzRqBIaJT55xM7504UMwdA2aIJimDELIlOvy2niWxTjug+vh"
    "N2dti7m9NkaXjsEQJsC2rxFIXoVcwKUUB09F0wiWZWJsdByH7LcQiy7ZFQfvtYoPsdY1Kr9BF3R/"
    "Kp3jsgJq8Tj/Xjlb0XwMWT5we9iOSjsbVFgohUrWzqp+MqIqKCklyEhXV0CiQhVTovhectIfQydM"
    "tyQ2W2cAl5+yPVqmF0oqtuSuwSe7uWXYWERxpnM9AC0bGOyt4dWRJt5+7CL84E/PoVEXaJk2WqaE"
    "7YJ2ZCQCEeTk/BoJ1HXH6nvuQA2/+cYe+MYxW8G0BZqWBl3Xff4B+9cpXdFH6WwMLBVBDA2kG9CM"
    "HoxOENZcZQC/PmdnXPalbdBTczY/h9JcvA+dp1bQcUShuOw6eTOFhF7bEvCqik3IL2NXVk4N3fIG"
    "z/gm0SnnOFEMsoKiBeUxreBkzwFwvm3E0JxTc6hPw5WnbonhHkKz1YSA3eYC5EcUfuHHQ6A4zj/k"
    "wXBtR6P/zsfGsdenb8QNd72Bmu60FZONUMKONLrhqABtt/EQFl2xP96zzzoYnSKQ3gO9VgdpWqB3"
    "x+om4G5W7g9ksGk5obBArVZD0xIYn2Ic9t4NsOgH+2LPrebBtBwItqZR7kOhDDOwk20/JGJBgQQY"
    "ZSx65vyzM4mG2xG+pVPMRIExpJyIr9QiIMcpqMYqv3IibyDup1RBqaI2FMf0+snl9599xKbYdsO5"
    "GJ9oOuEwU1gWWtGiFmhX+SEXvsySMTBHx8W/ehx7H3kdnnl5EoZWhMyj1BOYYRgaWnYTaE1Cs2YA"
    "ewZgy+l+uyaPpJimUqhPpUCUpQTbnmW5BWILglsYXTqOrdbtwdXf3hmnfmx9GMIhjNQNEb8IqBMU"
    "XSfPi/1ISShwXyjSK23v4RJVuZQ5zRH3p6yTngqkoNH1Fde+pLzpNHdSBEyT0eL8OQ/H/Ch1nEK5"
    "UyfFjjS4ZM2F3B753vVwxMHrYmy8hVrNrfiLQIZcLT758miecZE7CS2bUdM11OoCXzj/Phx17r2Y"
    "blowNMeaKzUnJHVhOdLeLVNCEHDrA0ux00euwaW/ewy9DQsG2Wi1Zhx1V6/07F+nAIRwowNHoATC"
    "XchCvfYgsjEEY2yiCcs2cdoRG+HaC3bFVusOoGlKaAqUGBny1mWEYcpL86Y4dajiH+C2UJYqwJnk"
    "Jqjl5TzEqPrGYQS44pagKFq0YHBHnHEOGfzMDj81Lkz1WmrTTRu7bTGMc47a0BX2MNxKP7lrSfU1"
    "cC3KWLpsswDk3zIt9NaB0YlpvOeLN+MbP33KP0Gji58UvIC/6lkpvioXbLmW5s0W49PnPIiDT74P"
    "r4zbGB6oQZotSGk6+b7KM/btnxWzIVVqnJSIRghAaK6NeQ1j44xdt56H6y/ZA8e8bz3YtlOn0BNq"
    "AxQzScsusDwviMK6OUQTdv0CVQsyimBTAlHgbBJSRQDVvFB6poTDqqRidWqQQQWKgNyFynCq6ypR"
    "1zcFTSPYElhrYQ+uPH1b1ARB2jLQr+fAeCIiiBUYdLr/ZFoSw4M6Hnl2BHt/ZhH+cvNiNGqOLVeU"
    "jedXskPGFdFvCI+3lG4qoBN+f92r2O2wRfjV9a9haG4NmqbBdg0y4ZmyehLiUZaOv7m4fnwU4Ba8"
    "NEfXNYxPSTTqBs4/YTv8+Vt7YqM1+mFZDEOj9mggZpJWdkpx/IySjERlE7XL37aOKL9eP3N1c5ML"
    "uAt3QljMzdtRHpLo5OKpIn/z6K6X6YaiGigSFb4+XSMXB8249IStsO4q/ZiesSEEK+AO15SUpe9A"
    "6wxXgPBjOP3+4eEe/HnRYux3zG146OkJGDphpiXbJ2YC9yBPm5Vd+3FdI7y8eBrvO/EuHH7OwzA1"
    "HYPDA7DYDf+9Y18y4NYjVFtq9pDzyixgdtiGUkrAltDgSEiPLhnHf+06Dzdfthc+/l9rwHSjAUMv"
    "b65BhI4qg8wqASjtOjgivupujAqMmyoknM0Gcq8bnynKVCwpIhFOSRLMJXYoSkH5kQLBZU5XWEg7"
    "iRxJccZJH9sI+++6EkZHZ6BrIkinPSgvohj1YOORzCBi9Pfr+O7PHsc7j78Nry5pQdeSpMs4l0tR"
    "1vhbtuMFWDMEvv/b57DHof/GTfe/jsF5DUftRXJgKc6R0fDhqkKRI4vHdBMRdE1gdHQGvTXgilO3"
    "w5Unb4tV5tZ8PwZBnQFlKGePmSg8YoIcxGYb4y/Ot1EJTby2biRxAGZf4Dgd60QFAXIdAOwExej9"
    "c0FAgFqDjVaIo3/nHK28xOor58/K4swViIC6ITDTkjhoz4U4+ePrY3RZ06X3khsTKFBfF/0X2Em5"
    "ebkk1I06anUdn/3GfTj6/AegCWdRWDaXLgblBcrY0ikQGrrAA09N4K2H/xtnfv8+6A1CT0OHaVoO"
    "HiDavlT1MZUH41hEhfUJPXdio2bAhoaJCYkPv3Nd3Hr5W3DwnivDsh0Gnq5RNadVWjeKE54tBaka"
    "JfX6FbgwJGfzVKiD6KSKjaBgCpCHVkwpRCNRZt/gDOYdJ/ydqVq9ukx5JW5H1Fk2Y91VevDd4zZH"
    "qyn9ya/KeId8DRk+958JaFo2Bnp0LBmfxgGfW4SLfv006gbBiZ656+GbOoSmJd17Ar5y0SM48HM3"
    "4uHnl2BoyIC0bEhpBVRkqMU/JQjmcFLIfufMlSFxbc6IGKOjM1g4r45ffX1XXPKFrbFg0PDBQ4K6"
    "pRoaF0EyVPSUr6+o4CAQEgpRtlapek7mV5Mlyv9guEv6ih0X3mM3AJ7F/IWrNVoqEip5J5UQhO+d"
    "sDXWmNeAabJf5Q9Zn7FUioBOdCOZYVkSc4bruP3hZdj9sOtx7Z1vOD4FZlijvyuAroQhtF3egaET"
    "/nXHG9jjE4vwnV8+jb4BDXWDYEnpxsxOO9C3HFMsh1kGKEfvt6SIl3jkWl0wZpo2xiemcfjBa2DR"
    "JbvjbTvM9w1JNUFd13AAOZBoCQfqrDb3iMmzBwgKm37kKAOtyRLWYFX13YsW86jLEhmCK0ZuVWWt"
    "1AaKiOGPZfmkRzcAy2acecSmeNvOCzA61nI59eTxbiGEh+ZzC33uwnH6/YSheb248i8vYv9jFuFp"
    "15OvWcKTDxXqHHr36hUIxyYtHPPN+/HeL92Jl5dZGB7ucSQMOGLNzXHUVhEoHfl2ZkEhhEhAExo0"
    "TcPoqIV1VhvAn8/fHRd+fkv092hBgTDVYYc6mGQOPmLdVXuxoL8Gi4WbpgnfSs0BRanqH+wjNoVw"
    "JNcXL53pGuehUzZlp/j/ol0KgRLa8oHEUn5lFCRCGoNJySlfXHYwBQGNmpP3f+K/VscXP7whRsck"
    "jHrdqSS57bNwUBSAZmzJ0ISOwaEenPWDR/HR0+7AxJRZqSdfVZGTZTuT3dAJv7vhNex1xE246l8v"
    "YHB+P3Rdd05OqaCXJPuFz2gBsJ0Z6m3B0ldJnmpamJkxcdT/bohrv7c7dth4yC8QaoISJjInu1mm"
    "TGAPsgAA2244jEbDgG1Ltfrkk4C8Nm1Qd3Ga/5peQ8sEXnltpmP7NMp4A3cgk5eXVp2Eyi26Poqn"
    "apzT+5wiarGxzz2o6FMOIUpK8XentknsVLKbpsQ2Gwzh3M9vjalJC0K4TDLmsNEUu5LR7jWZpomG"
    "LjE508THTr0NJ138oJNKEGDbK9Ta98dMshMi13SBF16bwfu/fBeO+trtGG9OY7CPYLUsSLe1yTFi"
    "xSTCnRafU8Be3h3k2Bo5uf/okilsu8EQrr1wVxz7/nV8kpOhUbbEV86wTkWO7rvDArAtQbAdhSbb"
    "BksH4uyRtChUv/GceCVMm2FK5PKUzEK3hiDunMZGpdzSanH8G86g1xaN0KlIhEmzJ9NXYVAMl+Hn"
    "KOUO9uq4/tK3YNM1+zA5NR1SyWU3AuFQNOIIgQ72aXhpZAbvOeFO3P7AEtQN598lV3N9ed6VJrke"
    "a8emCMkLNxy2bMaGa/biO1/cAgfstBKmRk3YEH73g4j9EiApFlteETTJzELtGli2DUGE/n4DV9/6"
    "Go6/4GE88NQYDF2AFalyrxhMkQ3IZzUmjE+9JmCajM3XH8T1l+6JGhjMNohlmykIXLYGXNEWhtO2"
    "7akLPPDEUuz6qZtgsxPdeeaq1M4antVJn0davxsrqGuioN2rfnKh8MaWjO8csym2WLsHExNT0DwD"
    "TxcvL/y/O7kkk5MnDs7rxaKHRrHnJ2/yF3/TlDmKfVwxjJkLSXb5CjVugdCyGYZBePz5Kfz3Mbfj"
    "yxc9AtR19PfWYdtOqsMKsSZURXcjJGaFgktOrYSE8HtIDEeWHBAYHZd42y6rYdFl++Lo960Hy5Kw"
    "ZEAzjroBRUP2OOyHcElOkhnHf2g9DPfrsGzbPVPV2gb57UtSeA/e7Qld4PEXJjDTcuTS08Q7iDEr"
    "WohpHoCVgayiNmxZNQCqsJJJFRZE8vv3AT11Z8F+9uA18eF3rIHRiSb0mqPsA3exOwQaHaQ5pB/J"
    "BJbAwKCGS656FAccfROefmkSutZZsa8NG5G0I1N25b/MOJqmIwbCEvj6j57E/kffigdenMDAgj6w"
    "dE5CdjXzQiG/S3OO1gRYaZeSJ3vGAJF0lIfGZqBjBt8+blP88dwdscHq/WhZDE2nsBFF0nxRWpVE"
    "jEbdkUHbZ/uVcchbFmJyZBIabGcjoYAJCXfhkwKDZrbB0oK0LRAYNz+4DCHdwJIYBS6wGJNT1nbK"
    "cRTdmje8pwh5IdYZLSaK0wCc1o7yow4kvwJThurIC8kqLpTQ8muajP/aeWVc/pXt0JyWEJpQypbs"
    "/3/pnmGWJWEYAvW6huMveBAnX/yIY6xB1HF/v8qqbdkOjVfuqOmEZ16awi/+9jxqhsCuWw1Dh0Sz"
    "ZfrPLyANUcjEAqS47cToJHi/F5CwpcTMZAtbbjCAQ/ZbA8tGWrjrsVGwm5p5kY3abfT+PyuAJQ9W"
    "vfGaA7jq7O3Qp0nYDAjhsR21oPLvz7twHYOkDRAgLcYZVzyGl99ogtCOB4gTK6WEwnVF2KEUNCAl"
    "zhMKweHzpelJl9O2AeSenGr1iDqbsBRrHBBuJ3HOz6sZApbFWGeVXvz2m7uhr8eAbbHr8CMDoI9S"
    "RDEtG4N9NSyZtHHoGXfjij88C0N3Qk4pO5S5LiD3TBkw0CQefvtkQSqK0PESkPjHLa/ijoeWYNdt"
    "FmDVBQ00p0yQEBCa7moeKlqMrMTFzKrmptN+A4VmmqM+pGOmCfT3GHjP/utgq/UGcPcjS7F4tAVd"
    "E9A1EXNSEYRLOiIAlg3svuU8/Pac7bDaHB1NE9B0t3YhnGIC+a7L8IFBKvhHMqPRMHD34xM47/+e"
    "Aphhc34qea41QRSidXtt1/BnUD4YcLuviX9/UdV5cDaOIG39aER0Wp4dKHn1kq8R0Bb25ImDMkaf"
    "UngF8S0NQk0n/Pa8nbDZmj2YmpiBRuFqrI+KEw4jcGhOA/c/PY6DT7gF19252NlEXNXZ7vMSlQcW"
    "8/CT+KnqpCIk+/bFPUfpRvc1Q+Cx5ybxu3+/gpXn17H91vPBUoMtPRq0u7jcOgAxBzRo9wQSrkoy"
    "hPd3lXosoGk6bGhotYCtNp6P9791TUxNzuChZycw3bJ9QF8UMi0ZmDNQx/EfXh/f+9L2mDvQgxkT"
    "0A3N/WxGhAkc7E8yUFUiQZAs0Ntfx2W/fxbX3rkYPXWtnNNyykoqEvEmLa0gRKfYKIMQ1TWgfAdH"
    "wpfGbg6lXWD9G1BhtXGVXSokyxTHHFQtmb1facKRuJ5u2rjwuC1w1CFrYdmyGdR0LTDn8N7s9qhZ"
    "EvqHavjbopfxkVPvwhsjTdRrAs2W7LAR4aUZSTbQ7W6SlEUbpfw+8lFX2bTXGi5AigEcetDaOOuo"
    "zbDy3F6ML5tx2mwhZCAC41NPy548ejH87oFX0PD1+N3JaloSNUOgp8a474lJ/P6m13DL/Yvx7KtT"
    "WDpuQRBh4dw61ly5gd23nIP/3nMVbLLuAKYmGBIER5eF/RoEhx3D3c0KEZF+R73JkhZ2+eQNePgZ"
    "R4q9aeaYlRTvO1C2U0DK8c7c/vlcEiHL0VODQ7bOCMHpuIOeFaW6Ard/lO/QooI8VJnjilof5OaV"
    "LUvi4+9YA1ecvB3Gx1pO4cs/OQMDBwfcQ+jpM3D+zx7D8d95yD3Eksk8edo23k6r4hq4gtZqdNyy"
    "diUq4DXvbZ5COAt0vVV7cNbntsT79lkFzfEmmpbttAuVJN0v0rkdB0FhTz4GRayp2S+6SUlgluht"
    "aNBrOmyTsWzCxsQMgwRjuBcYbDBISDRnbEzNMHRdd7s15Kv/etsrsQjj8F2QmifYalmMoaEGrvzL"
    "U/joGfc5TFDJYF6+LT2K5L4c02elnAdvODIM92w56/XRAjTHnLRIUGFK2k1mEztAINRrAjMtGztv"
    "MRd/+85uqLmQUU0EVlLOVUlYlu3YfknGiZc8gguuegaGLmBLGZvv5zlpQ6mC+/B9bEGG3XrcCZGm"
    "p88ZlurlDyjyTUkB4BPvXh3nHLEJ5vU3MDppQdc1p7cebUAyJzgEKQEmM5gJRBLMrmgqJGAzSBA0"
    "IXxshi0lLNv2x1RQUPTybL59eTNmv/IfJqqRz+FgW4JIYM+jFuHex0egCSTQtQuG75y8Dqrs88dF"
    "wXmtyEKX6tdyuI25yMXdUSsEJHiV5sgiUTcTzlD2AQNzBg1cd8nu2HCVBqZnbOhuoQiKkaRpMYb6"
    "a3h5yTg+dMqduO7upajpBNOePXmyokXEuACrmxgVQc6YmhZj03X6cemJW2D3HVbDzJiEaVnQNcfw"
    "xDM99cA31Oa6ygGOwXsGPrjI2Yz9jTEUFar1EPInAYUKw2FrbXKZmn41xH1vy5IYHq7jsl89hU+d"
    "ey8art+j7EJXp02LwD10vFpF0NmgBEp98Uiy6IaBBAfs06ptYVAx4YMOnoUmnNDfsoGfnr4d9thi"
    "GOP+aUUhnKZtEQbn9uL2B0dw4LG34J7HR1EzHL2+qtc+zSowqtr3sdseM3SB15Y28bO/v4SWydhj"
    "u5XQZwCTU00I4sCAI+Rvx2HstxIZsfse4SUJFFVcVjoI6lX7NUbP2YeUQhlCObXq+Cwlo6du4NXX"
    "W/joV+/ExIwFRyGdK5PmrrQITNUzSPN8puAOuflU4M3UgfBB7EklnB7xFz68Id6120KMjM44cl9E"
    "YBfoI93JMDBMuOSXj+CAz12Hp1+aQM1wyDzdOPg552BRJ+YYBVd40du0LIauCdiS8NXLHsFen7gG"
    "tz28GMNzCGybsKXtilgqNl1EEWG7YAfwNBCl6+TDbtygdmYoRDGjtsXhvJeVckTgcO9HDgqMWdcl"
    "jv/uPXj+9SnU9HJ4jrYUWNFxTfMOoAKLJpdyMBXDjeTVFkzFAWRfD2X2peOQgHl7q2n3Wq9paJoS"
    "B++5Ki754taYnGxB1zRf8pXIkf2qGQK9DYGvXPowTrjwUZiWTJHtWrFAPqjAWKKTS5BuaF43BJ5/"
    "bQY//cfLqAnGHtutDEOroWUBQteVRRzRiSJKVmdyY3Wm8MoiorCqb6DTFtICbEPOuaxOJoJlAkPz"
    "DJz9o0fx3auegaFXx9zMI79FuaX1KjP4KfSh1A3KQ9HKc2cVf8dkY+v1B3DtRbujYRiwpISXaYIc"
    "Jt9Ar4bRKQuf/PqD+O11r6BuOJ2CTlRXEy2xCcmV1+VURSDiJJn5RKoqp9Va4BiGHLDLQlx88nZY"
    "Z/UhTC5tAmSDIBH4mitWuRSRkfLZnx5qj0NyUc41cxu+wcvxo7ubSgACGGaLMbSggav+8hw+dOpd"
    "0AT5nIjlwWHhgq8pU2dLKthzjs5B7g1ARetVpW1XLu8naALo69Hx74v2wBbr9GFi2oamCb9HbVoS"
    "w0M6HnxqFB865S7c/+S4U+yzuDNt94KVXKL8phBlZKS5KxzKfO3WhfPrOO/zW+N/D1wLrfEZzEy3"
    "oAvNWdB+fad9A/AgwN4S9zYKHy1AAXiBw+XFoCCoFAFVyLJpMgbnNnD1ra/ikBNux+SU6Ss3r1DF"
    "3RWIXRtbBCyL1acuh7aaa9RhWozLTtwWb9t5FUxMOBV/z+yBJTA4p4G/LVqMd3/pdjzz0pRTKOxg"
    "8ZdRf8mz+KmChRkV9e02clFKJ60am7Tx23+9iCefG8Fu2y7A/Hl9mJ5qOVBi0pzcXGtHqlFYsFux"
    "RQrAReyCiyhUQPCgv2rYT25z10H7Dczpwe//9QLef+LtmJw23dN/eTJXO5vx1CEJr/QhlRSacMnB"
    "4Ip2wZ6awHRL4ugPrIdvH70FxkZb0AwdBILNjlx2b4/AeT99HF+59FE0Ten2tlesFh8y0GZoB3OB"
    "ufOjvKooAJ57sUZotmysvWofvnfiVjhgp5UwM2GiZTEM3Y0GZLhs6fX32e0aONoAFAQLfp86pPMT"
    "2kG8th/AMC0bDUNDrV7Hpb95Fkeffy8s6TBCqwj7q8qRqYvpcRLVICc+gZjjdJczqvmcc2RKD2Bk"
    "YdRcPv7uW8/D37+9K2RLAsQQQsC2gZ6GDkkSn/vm/fj+75+FrjuuubbNXWmcJ+XRlZzmnALsyJmG"
    "5I1AOh0WT2uRAHzyoDVw1lEbY95QAxNjjk25FqrYUxD6E9AmS6SWr6k9xPFDf3aEPIiA/gENry2Z"
    "xJHnPoLfXvcKDLfanxb2p45NCsGGK6zH0HJKA9q4IomVolm6RC9XTAvQPROKuYMGbrh0d6y1cj+a"
    "TQnSANuSGB6o4aXXJvD+U+7EogdGOi72VVUDWL56SMURaVTeXMKHWG+2Th/OOHwTvHPvtaFrGqbH"
    "mrBMC6QhRNuNasYH18QhDAcp/E2WgM2Mmq6j0V+H1ZL4yV+exJk/fBRPvzyTG+ZLVEKKnlaExD3f"
    "RRRqGngbQF7kXekw3t12i46jJ+fNzPjDudvhv3ZeFaOTtuPtZ0sMz2ngxnuX4mOn34GnX5pCzXDc"
    "flfkBUmxlV9Suiicq2LfbZupohu5oTkbLwC8dYcFOPy96+HtO62Mvl4Ja8bGTAuw2PUvJHJhvWrH"
    "3y0gckD3YVeiXRCjt65BNDRMTDD+eutruPCXT+HG+5aGIpEVudiX1kXi5bSNOJkYtUNx815YwH3m"
    "riwYj533tSM3wYkf3QCjo7ZjCyUlBgZ0XPnXl3DkefdjctoqNAnidO5y3W+3jB8UTgFX7ikQjnk5"
    "IxyO9p1zj5GP2Avy703X7sN79l6Id79lITZeew56B+pOgbDlKBDNtCywreB9mSA0p+2okwRpEiCJ"
    "6UkTDz8/iT/c9Dp+9a+X8eizE357Usr87c7l1JD1U5duFRq5qgNsxRk0R857uiXxof1WwU/O2BHj"
    "k44MlGEY6GkInHb5Azj9ssdBhFRbruV5KnIUEjuLkcjyfJae4YoHve0xNGy63gB23WoONlt/PjZd"
    "fy7qNYG1F+hoGA5ZSAgNmm5gZgZYNtLEGyPTePT5Mdz20Ou465ER3PPEKEw3uvNkx6Xk2X+m3N10"
    "kZJk4LpQSMxVnOw47yyxy3in+ebrDeLq7+6G4R4N002J4b4aljUJh599F35z7fOouUy+Kts9nUQC"
    "pfLLMhtKp/WIinaH2OtQPlsIgkaAFTmlNdeSbdUFDfT26P79aZrA5LSNJUunMdW0YUY2dV1zbNgk"
    "r8CdnZJsTOQgfJcBF81qRNtp1d/RgXPkvIf7dVx9wR7Yct0BLBudwfzhGh59YQLvO/luPPDkKBpu"
    "esA56LRVtcD4zVArSrqeHBeXj4OefGykaSCQAAQ5eoB5cfmaCGojLDsEcsWoJXGGK7HK4uM3waZT"
    "dA6KIljxWMBLjAUvdcCgIQQ93POP2QrbbL4KRiZ1zF84B3+7cxT7fOZmPPDkqC8WmdcujLMw+yEl"
    "1niSB6dpr1E69p+IZg18QkkTnuPVYgvnksylDDWkBCxb+ovfd19zmX6a+19V7NLT7peSyzn2pPyS"
    "8zJwYmS7E1zVcwrnostmMpQbDKSny3uly3/FPXJW3Eq4YFJK5BT9ppsSx7x/fXzgbWth2RszmDdf"
    "w7f/72GccMFDMC07EdyTdzdP0t7nuIedElVw25pI0fAvYO5R5JlwzkVIBV47WydT0AXk3GcEpTxI"
    "LsDqy6PUlCSNxx0wQosGEXn4/RRjv8YKwJI5ebOPBwJV2T8tMDl03XHe2Xf7efjdOTtDZwC6wPEX"
    "PYiLf/UMNM2JODw3F+60BVKBZBd10Q6aO0lFcjyrPCFwWMwCXdFO4FlAy3VaGKOCmoyzmUYXRe62"
    "8bPSKo+cg6JYoAsYLzpKQE0XaFqMjVdr4O/f2Rtrrj6EV5eM4fCz78KfbnwVNd1x7OkGsYMKSCR1"
    "DSfRhcnRzcU1Wzlx0nWvaLWWKrs0lUG2k1JXJapNEa4NSxIVnsxZ4b6iHuXlfboArvn2Htht73Xw"
    "4IOv45ATFuHRZ0bRMARmOgT3vJmKOG8WdlnspKbigjL/eU9lOcvHFRxjzvqhHK8p+yMI3NvQGACf"
    "d9RWzE9+nH95zs68yvwaA+C6Qbk/q5vX2ekPKddHbdfa+T2SIz7XvTEg3w9shRjDbnz2bN6Hej/+"
    "D+V4BrHPvtz9KV3lCh4GUdtkzPMZhu689iNvXYX5gf/hsz+7FbsaD6xrlPi9lHmTVM3Dou5OQHWs"
    "qIIFkDQ+NMuTezbGyFs04UVEXdsAu/XZVHJuUY75muP98S+OG0yq9CET12uCAfAeW8zjiZsO5qM+"
    "sAEDYE0jFoKWz0Sk6hZA2ka1IkcraddJRCvctVMHm6Z3P0U3TlpBNtIK5lKx05BSQg/KsSC8/++d"
    "7qvOr/Hdv3kbv/Ota7khv2AhZmtyU2r4RCkhl/dT9UZEyykEzpu65I3yonOlyk2YaPktvLzPnqo6"
    "RLoYgVKe+n3udlSB6o9wIZ+DvRq+8MkN8Lt/L8Ztdy/OZ8vVieMqh6v9qKiiHzJEyYMVz3D6KVOx"
    "76gYmOQWU7JqnT5n0qnfK3TxM9UbsLoui+8zOBtdloqL+4VaOxuu0QsG4YkXJrtK50xi/rU5ITFm"
    "yc0oX4uVl7fUTCfdliRhjZTNr0inZkXT1pvNzkaWI1BRolFlG0DZuSgEdZXVpZJoqgI1UQVApKKb"
    "VipKzNNbiPMs7DKAJy+VuOsn55ugpdjJ/UbxKqWJQcpF5KIgEfIhxoo8+CKLMP/r0s1KO1U7Xh5n"
    "R6cEpCIOxR0ToXJKo+eVrC6nYJQicpXib1Hew7o8aQxlnlsFF0NZtmOEEmIQy1H5JBvSqvxe5TEs"
    "x+i5jDZ/0qqjFL5BUQGJLDNKXh5OulXqG0bw8WX4F8sjSpkVyPkKlk4WoBBnTKKMkKfT/L9oaPZm"
    "CmuLbPqxNZYcBLA4OQG82eZiwfGsouY0WxT3XA+MqygwFJ1cFQl9gl0bq4okm7rq6tKlAlE3celd"
    "qTVULYU1C6d/t2DrZTfpNy0UO6mSXFUEsyJXmGfj+qvmTXQS9s4mdbnT6nrb+zzvg250tSqoWQXW"
    "qgXdZ6oROKDS7+WEQS1W+CnhwBu97zhn2Mi/UZdcYChDIZg7sKdWC0RUgVtN2XnKXVr8lIMUU8mn"
    "JgjtdvpH5fdTBU5C3KkbCXN2IanTwuBsF6fKijNUMRk5T0jahQSwqhSOulDdfrOyBtPWQr42aQAK"
    "oi5thlzFol+R+qlU4clRPKeP6B0UGKs4G2heAVOLIu2rygVlV/AeP9D+/LvhGk15Nw/m7o1vt4p8"
    "K54oRfUnf54aR5k+cRXFPCoLMIlDWHYBOIYYN7FOQVVvRthgEbGUxNdGyxTJ10O+5l1aG6MbyrlU"
    "CFFGYW0+FwbICSXdxLYg0g1PqppUbbjvzFWRPhrO53FiaE8Kaou5WrWkKs/rqOElx4JZEAucQkYU"
    "lqbzGNa7bL8trkjem1eA0MbXDEzbEqhtVaAdNUUKGSYLNah8VqFWR2QmquvFv66ExRMHBc4+0cJD"
    "Q2rpNXL9sbyCHMVJynBPRgrcljPQckU3qLyncd7Uq4xIaaaOXclNt6jtXSZYS0XSRedWKmGovXuV"
    "ZSFGkbI/d5jutqeoeURBY+DARO3DlNOOOGHhe10B7iAsjB8odeCrIqO0fa63MSFbCg0ZYTIVXDjJ"
    "8GZqs+bOcrGhNmfC4Epio4vIYvAGYzZrRLkXQciHsL3jwZXkJwkA5aTWtXKgUeSUy+UCHVFMZo8P"
    "ohQOOUMpnWPxwYmnadyFkbITcmZhRK1okzJzwiYMCKUcqZZJMTt8GaXULDRfWs6FJNVYCluD5S8G"
    "qf7owbSNVpM552ZbBQssmkWRMnETo6FEQoobanvPXhnA9hA9DtDuOYwrOP4U8E6VFfROxFYpYTJx"
    "ZjpXbXrFiqsHlyk6xIadeSKhnGKhSHO3QbWFhtCOGTnFi8grg/Lv3Kk3GpkcoVt2sf9R74LwQi8C"
    "eO/esUxKvsYZBVWKaYPkKXDFmdNGo5KyKMu89m+UsYgRl1JH3sgdO28jtV7FiAclFfIFqMIWOxeF"
    "MYMBhkjBL43VlSVJzlkoK5VsUxB+lViQCp12HRZTY9leylhwcS8A5gwtheipl7JSqCR2Iwyo4tmj"
    "M2fUMIIsp4CwiTeHIp2dePRgxMyDIhtNxdwJ9/DLUqhJht7mPvGSNgJS/s75ij5ZYSUXbBOlTooI"
    "kQgJOXxsISfm9Omkxx/XHsxMaxIWoRf1pEUTeZ1u4+oIKLDZh/xsuHhLkrtt1BEX+bZnaKmzKbqp"
    "5mldMnfCoMxfQ+AVWQShCo7ACsWamwXd/EJt07wpWWjCx6PbuMsEFErYWbgL6MP8ghvhSIDiDEi7"
    "JDZR9p4zU3V/R8/Zc6EYdgKXqH4XEXBARgCWdJOVE10yWoJFMARFVF5WFJRg1obWafGRSs4X+g+j"
    "E3eipUizITxSBX1zxVLn6V4lOVoHmE1K7vJeGFWIgpauj9B/qMhAnlpOGqakVAEhJfmKBTzkQFOl"
    "ttNmSSOgextAVXq48ZP8P8liizKKcFmkKXA53EAVkO8sYM9/DBLZD2MTinhJPdN4WOdsnvrFbrlM"
    "ykAJE6tMfUKthhfCAOQMvYuF1dWkT1UJYy4vLQdaQclaZTapXOag3bjptgdVunWdXwSy6EZTBZMt"
    "tmsQ7Q1TNeIOKCirzWX75ImS31n3kfKsSgx22foCpewS3EUVojJiJ5WqX6UVZMvQXuMADh3rlFd1"
    "ysz6Dt39ILwTamnypFag3AUWclWj+2ZwbU7rsydv8mkkJp5VRSUuEwFUTTNNA1iUqfSW6iAUJchU"
    "M8XjGWsJJ08nNs+zQZCZ7b2QOugcdVNcVMVYZNUN/p81MaEOpaKoQHjUyUkSpZa2pTsdjlIuXkKn"
    "6JDCKPAVZ0LGFet94mWOML9bKkN5XRpmcyyr/q6OplSeHnClIotl3HMUiCDz8kkb3gwio9X3gx3s"
    "OYqe2CXo4p2p2kSQnhHoLXdFiXrF6UbmhnWv6L11LKciymz32N8srezEgmuaZgNXD3Ip4lJUtpCK"
    "N5spQZmYpuOKeJUTt4z4fgL7TGUBJm3NXAJgkdW7pwq0/6gC/f8yp24negVVq0GVqUFxlyS2l0dr"
    "sAjBLkmPgP9T0U9lceoglf335gPMFLU+5xXcFLOrCyenNfp/6h/xn3QzSRNMFT/IQpix+znMamm+"
    "C1psBU0RYl8eYtJFC5dUSrOfaHafTdxuRrMxVxIGIIsiTF24vrJjTm/6DYCK/5pKDwSXZE7RcuiP"
    "tL88Kj6hGqTEUZjLdkQUycOuLMjEja+os3QHZipFQ/UoX58TN/UubY4lumiU/3k4DPqiF9HtkI5W"
    "gIIbKoDOLi968n+iyQb+X+uj5/nejIVQqobSJsHFK3b1uYg23v/LnoErdt2GyqglvikW8oq84f7/"
    "h8H//+f///P/8J//D3DhZ//f5xohAAAAAElFTkSuQmCC"
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
    """App icon: WizX20 bolt mark on dark rounded-rect background."""
    img, draw, hi = _icon_base(size)

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
        self._pr_title_lbl.setStyleSheet(f"color: {FG_TEXT}; font-size: 12px;")
        self._pr_title_lbl.setMinimumWidth(0)
        self._pr_title_lbl.setWordWrap(True)
        self._pr_title_lbl.setVisible(False)
        centre.addWidget(self._pr_title_lbl)

        # Top row: name + branch
        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(0)

        self._name_lbl = _ClickableLabel(
            state.name, url_fn=lambda: self._state.run_url or self._state.url)
        self._name_lbl.setStyleSheet(f"color: {FG_TEXT}; font-size: 12px;")
        self._name_lbl.setMinimumWidth(0)
        self._name_lbl.setWordWrap(True)
        top_row.addWidget(self._name_lbl, 1)

        self._branch_lbl = _ClickableLabel(
            url_fn=lambda: self._state.run_url or self._state.url)
        self._branch_lbl.setStyleSheet(f"color: {FG_MUTED}; font-size: 11px;")
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
            self._name_lbl.setStyleSheet(f"color: {dim_text}; font-size: 12px;")
            self._poll_lbl.setStyleSheet(f"color: {dim_muted}; font-size: 11px;")
            self._branch_lbl.setStyleSheet(f"color: {dim_muted}; font-size: 11px;")
            self._pr_title_lbl.setStyleSheet(f"color: {dim_text}; font-size: 12px;")
            if self._icon_opacity is None:
                self._icon_opacity = QGraphicsOpacityEffect(self._icon_lbl)
                self._icon_lbl.setGraphicsEffect(self._icon_opacity)
            self._icon_opacity.setOpacity(0.35)
        else:
            self._accent.setStyleSheet(
                f"background-color: {COLOUR.get(self._state.status, COLOUR[ST_UNKNOWN])};")
            self._info_lbl.setStyleSheet(f"color: {FG_MUTED}; font-size: 11px;")
            self._name_lbl.setStyleSheet(f"color: {FG_TEXT}; font-size: 12px;")
            self._poll_lbl.setStyleSheet(f"color: {FG_MUTED}; font-size: 11px;")
            self._branch_lbl.setStyleSheet(f"color: {FG_MUTED}; font-size: 11px;")
            self._pr_title_lbl.setStyleSheet(f"color: {FG_TEXT}; font-size: 12px;")
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
            self._name_lbl.setVisible(False)


            if s.pr_title:
                self._pr_title_lbl.setText(s.pr_title)
                self._pr_title_lbl.setVisible(True)
            else:
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
                ":waitpid\r\n"
                f'tasklist /FI "PID eq {pid}" 2>nul | findstr /C:"{pid}" >nul\r\n'
                "if %errorlevel% EQU 0 (\r\n"
                "  ping -n 2 127.0.0.1 >nul\r\n"
                "  goto waitpid\r\n"
                ")\r\n"
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
            DETACHED_PROCESS = 0x00000008
            CREATE_NO_WINDOW = 0x08000000
            subprocess.Popen(
                ["cmd", "/c", str(script)],
                creationflags=DETACHED_PROCESS | CREATE_NO_WINDOW,
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
                f"while kill -0 {pid} 2>/dev/null; do sleep 0.5; done\n"
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
        header.setFixedHeight(46)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(14, 0, 14, 0)

        # WizX20 logo
        logo_data = base64.b64decode(_WIZX20_LOGO_B64)
        logo_img = Image.open(io.BytesIO(logo_data))
        scale = 28 / logo_img.height
        logo_img = logo_img.resize((round(logo_img.width * scale), 28), Image.LANCZOS)
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
            self._tray_icons = {
                s: QIcon(_pil_to_qpixmap(_make_icon_image(c))) for s, c in COLOUR.items()
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
