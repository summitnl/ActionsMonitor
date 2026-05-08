"""Notification batching, sound, and toast IPC.

Self-contained from main.py. Platform-specific deps (winotify, plyer, winsound)
are imported here. Per-process paths (APP_ICO, _FOCUS_VBS) are injected via
configure() because they depend on _APP_DIR resolution that lives in main.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

IS_WINDOWS = platform.system() == "Windows"
IS_LINUX   = platform.system() == "Linux"

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

if IS_WINDOWS:
    import winsound

# Linux system dependency check — surfaced by main.py for the user-facing dialog.
LINUX_MISSING: list[str] = []
if IS_LINUX:
    if not shutil.which("paplay") and not shutil.which("aplay"):
        LINUX_MISSING.append("pulseaudio-utils (paplay) or alsa-utils (aplay)")

# ---- configure() injection ---------------------------------------------------
APP_NAME: str = "Actions Monitor"
APP_ICO: Optional[Path] = None
_FOCUS_VBS: Optional[Path] = None
_FOCUS_SIGNAL: Optional[Path] = None


def configure(*, app_name: str, app_ico: Path, focus_vbs: Path, focus_signal: Path):
    global APP_NAME, APP_ICO, _FOCUS_VBS, _FOCUS_SIGNAL
    APP_NAME = app_name
    APP_ICO = app_ico
    _FOCUS_VBS = focus_vbs
    _FOCUS_SIGNAL = focus_signal


def _ensure_focus_vbs():
    """Create a small VBScript that writes a signal file when executed (silent, no CMD flash)."""
    if _FOCUS_VBS is None or _FOCUS_SIGNAL is None:
        return
    script = (
        'Set fso = CreateObject("Scripting.FileSystemObject")\n'
        f'fso.CreateTextFile "{_FOCUS_SIGNAL}", True\n'
    )
    _FOCUS_VBS.write_text(script, encoding="utf-8")


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
    line:       Optional[str] = None   # single-line summary for multi-event toasts


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
               row_keys: Optional[list[tuple[int, Optional[str]]]] = None,
               line: Optional[str] = None):
        with self._lock:
            if self._batch_window <= 0:
                # Batching disabled — fire immediately (old behaviour)
                threading.Thread(
                    target=self._send,
                    args=(title, message, sound_cfg, url, row_keys or []),
                    daemon=True,
                ).start()
                return
            self._pending.append(_PendingNotification(
                notif_type, title, message, sound_cfg, url, row_keys or [], line))
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

        # Multiple notifications — combine into one with summary header + per-event lines
        counts: dict[str, int] = {}
        for item in batch:
            counts[item.notif_type] = counts.get(item.notif_type, 0) + 1

        type_labels = {
            "failure": "\u2717 {n} failed",
            "new_run": "\u25b6 {n} started",
            "success": "\u2713 {n} succeeded",
        }
        summary_parts = []
        for ntype in ("failure", "new_run", "success"):
            if ntype in counts:
                summary_parts.append(type_labels[ntype].format(n=counts[ntype]))
        summary = "  \u2022  ".join(summary_parts)

        title = f"{sum(counts.values())} workflow updates"

        # Sort events by priority (failure first) for the per-line list, then
        # truncate so winotify body stays readable (~4 visible lines on Win 11).
        prio = _NOTIF_TYPE_PRIORITY
        ordered = sorted(batch, key=lambda i: -prio.get(i.notif_type, 0))
        max_lines = 4
        event_lines = [(it.line or it.message.splitlines()[0]) for it in ordered]
        body_lines = [summary]
        if len(event_lines) <= max_lines:
            body_lines.extend(event_lines)
        else:
            body_lines.extend(event_lines[:max_lines])
            body_lines.append(f"\u2026 and {len(event_lines) - max_lines} more")
        body = "\n".join(body_lines)

        # Pick sound from highest-priority notification type
        best = max(batch, key=lambda i: prio.get(i.notif_type, 0))
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
                    icon=str(APP_ICO) if (APP_ICO and APP_ICO.exists()) else "",
                    launch=str(_FOCUS_VBS) if (_FOCUS_VBS and _FOCUS_VBS.exists()) else "",
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
