#!/usr/bin/env python3
"""
Actions Monitor — Lightweight GitHub Actions workflow status monitor.
"""

from __future__ import annotations

import os
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
    from PIL import Image, ImageDraw, ImageFont
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
CONFIG_FILE    = Path(__file__).parent / "config.yaml"
CONFIG_TEMPLATE = Path(__file__).parent / "config.template.yaml"

POLL_DEFAULT = 60  # seconds

# Status values
ST_UNKNOWN    = "unknown"
ST_QUEUED     = "queued"
ST_RUNNING    = "in_progress"
ST_SUCCESS    = "success"
ST_FAILURE    = "failure"
ST_CANCELLED  = "cancelled"
ST_SKIPPED    = "skipped"

# Colour palette
COLOUR = {
    ST_UNKNOWN:   "#95A5A6",  # grey
    ST_QUEUED:    "#F39C12",  # orange
    ST_RUNNING:   "#F39C12",  # orange
    ST_SUCCESS:   "#2ECC71",  # green
    ST_FAILURE:   "#E74C3C",  # red
    ST_CANCELLED: "#95A5A6",  # grey
    ST_SKIPPED:   "#95A5A6",  # grey
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

# UI colours
BG_DARK    = "#1E1E2E"
BG_ROW     = "#2A2A3E"
BG_ROW_ALT = "#252535"
FG_TEXT    = "#CDD6F4"
FG_MUTED   = "#7F849C"
FG_LINK    = "#89B4FA"
ACCENT     = "#313244"

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DEFAULT_CONFIG: dict = {
    "github_token": "",
    "notifications": {
        "new_run":  {"enabled": True,  "sound": "default"},
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
        if CONFIG_TEMPLATE.exists():
            import shutil
            shutil.copy(CONFIG_TEMPLATE, CONFIG_FILE)
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


# ---------------------------------------------------------------------------
# Events put on the queue by pollers
# ---------------------------------------------------------------------------
@dataclass
class StatusEvent:
    workflow_id: int
    new_state:   WorkflowState
    notif_type:  Optional[str] = None   # "new_run" | "success" | "failure" | None


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------
class NotificationManager:
    def notify(self, title: str, message: str, sound_cfg: str, url: Optional[str] = None):
        threading.Thread(
            target=self._send,
            args=(title, message, sound_cfg, url),
            daemon=True,
        ).start()

    def _send(self, title: str, message: str, sound_cfg: str, url: Optional[str] = None):
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
        # Sound
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

    def run(self):
        while not self._stop_evt.is_set():
            self._poll()
            poll_rate = int(self.cfg_entry.get("polling_rate", POLL_DEFAULT))
            self._stop_evt.wait(poll_rate)

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

    def _fire_notification(self, notif_type: str, state: WorkflowState, global_notif: dict):
        # Per-workflow override or fall back to global
        wf_notif   = self.cfg_entry.get("notifications", {})
        section    = _deep_merge(
            global_notif.get(notif_type, {}),
            wf_notif.get(notif_type, {}),
        )
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
        NOTIF.notify(titles[notif_type], messages[notif_type], sound, url=url)


# ---------------------------------------------------------------------------
# Icon creation helpers
# ---------------------------------------------------------------------------
def _make_icon_image(colour: str, size: int = 64) -> Image.Image:
    img  = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    pad  = size // 8
    draw.ellipse([pad, pad, size - pad, size - pad], fill=colour)
    return img


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

STATUS_SYMBOL = {
    ST_UNKNOWN:  "●",
    ST_QUEUED:   "●",
    ST_RUNNING:  "◉",
    ST_SUCCESS:  "●",
    ST_FAILURE:  "●",
    ST_CANCELLED:"●",
    ST_SKIPPED:  "●",
}


class WorkflowRow:
    HEIGHT = 52

    def __init__(self, parent: tk.Frame, wid: int, state: WorkflowState, alt: bool):
        self.wid    = wid
        self._state = state
        bg = BG_ROW_ALT if alt else BG_ROW

        self.frame = tk.Frame(parent, bg=bg, height=self.HEIGHT)
        self.frame.pack(fill=tk.X, padx=0, pady=1)
        self.frame.pack_propagate(False)

        # Status dot
        self._dot = tk.Label(self.frame, text="●", font=("Segoe UI", 16),
                             bg=bg, fg=COLOUR[state.status], width=2)
        self._dot.pack(side=tk.LEFT, padx=(10, 4))

        # Centre column
        centre = tk.Frame(self.frame, bg=bg)
        centre.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, pady=4)

        self._name_lbl = tk.Label(
            centre, text=state.name, font=("Segoe UI", 10, "bold"),
            bg=bg, fg=FG_LINK, cursor="hand2", anchor="w",
        )
        self._name_lbl.pack(fill=tk.X)
        self._name_lbl.bind("<Button-1>", self._open_url)

        self._info_lbl = tk.Label(
            centre, text="", font=("Segoe UI", 8),
            bg=bg, fg=FG_MUTED, anchor="w",
        )
        self._info_lbl.pack(fill=tk.X)

        # Right column — polling rate
        poll_rate = 60  # placeholder; updated when we have the config entry
        self._poll_lbl = tk.Label(
            self.frame, text="", font=("Segoe UI", 8),
            bg=bg, fg=FG_MUTED, width=12, anchor="e",
        )
        self._poll_lbl.pack(side=tk.RIGHT, padx=(4, 10))

        self._bg = bg
        self._update_labels()

    def _open_url(self, _event=None):
        url = self._state.run_url or self._state.url
        if url:
            webbrowser.open(url)

    def update(self, state: WorkflowState, poll_rate: int):
        self._state = state
        self._dot.config(fg=COLOUR.get(state.status, COLOUR[ST_UNKNOWN]))
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
        if s.last_check:
            self._dot.config(
                text=STATUS_SYMBOL.get(s.status, "●"),
            )


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
# Main window
# ---------------------------------------------------------------------------
class MainWindow:
    def __init__(self, config_mgr: ConfigManager, event_queue: queue.Queue):
        self._config_mgr  = config_mgr
        self._event_queue = event_queue
        self._pollers: dict[int, WorkflowPoller] = {}
        self._states:  dict[int, WorkflowState]  = {}
        self._rows:    dict[int, WorkflowRow]     = {}
        self._tray: Optional[TrayManager] = None

        self._root = tk.Tk()
        self._root.title(APP_NAME)
        self._root.configure(bg=BG_DARK)
        self._root.resizable(True, True)
        self._root.geometry("560x420")
        self._root.minsize(400, 200)

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
        # Title bar area
        header = tk.Frame(self._root, bg=BG_DARK, height=48)
        header.pack(fill=tk.X)
        header.pack_propagate(False)
        tk.Label(
            header, text=APP_NAME, font=("Segoe UI", 13, "bold"),
            bg=BG_DARK, fg=FG_TEXT,
        ).pack(side=tk.LEFT, padx=14, pady=10)

        # Column headers
        hdr = tk.Frame(self._root, bg=BG_DARK)
        hdr.pack(fill=tk.X, padx=10, pady=(0, 2))
        tk.Label(hdr, text="  Status / Workflow", font=("Segoe UI", 8, "bold"),
                 bg=BG_DARK, fg=FG_MUTED, anchor="w").pack(side=tk.LEFT, expand=True, fill=tk.X)
        tk.Label(hdr, text="Poll rate", font=("Segoe UI", 8, "bold"),
                 bg=BG_DARK, fg=FG_MUTED, width=12, anchor="e").pack(side=tk.RIGHT)

        # Scrollable workflow list
        container = tk.Frame(self._root, bg=BG_DARK)
        container.pack(fill=tk.BOTH, expand=True, padx=6)

        canvas = tk.Canvas(container, bg=BG_DARK, highlightthickness=0)
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._list_frame = tk.Frame(canvas, bg=BG_DARK)
        self._canvas_window = canvas.create_window((0, 0), window=self._list_frame, anchor="nw")

        def _on_resize(e):
            canvas.itemconfig(self._canvas_window, width=e.width)
        canvas.bind("<Configure>", _on_resize)

        def _on_frame_configure(_e):
            canvas.configure(scrollregion=canvas.bbox("all"))
        self._list_frame.bind("<Configure>", _on_frame_configure)

        def _on_mousewheel(e):
            canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        self._canvas = canvas

        # Footer
        footer = tk.Frame(self._root, bg=ACCENT)
        footer.pack(fill=tk.X, side=tk.BOTTOM)

        # Row 1: config hint + open button
        footer_row1 = tk.Frame(footer, bg=ACCENT)
        footer_row1.pack(fill=tk.X, padx=10, pady=(6, 2))

        tk.Label(
            footer_row1,
            text="Edit config.yaml to add/change workflows. The app reloads it automatically.",
            font=("Segoe UI", 8), bg=ACCENT, fg=FG_MUTED,
        ).pack(side=tk.LEFT)

        open_btn = tk.Label(
            footer_row1, text="Open config ↗", font=("Segoe UI", 8, "underline"),
            bg=ACCENT, fg=FG_LINK, cursor="hand2",
        )
        open_btn.pack(side=tk.RIGHT)
        open_btn.bind("<Button-1>", lambda _: ConfigManager.open_in_editor())

        # Row 2: startup checkbox (Windows only)
        footer_row2 = tk.Frame(footer, bg=ACCENT)
        footer_row2.pack(fill=tk.X, padx=10, pady=(0, 6))

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
    # Pollers
    # ------------------------------------------------------------------
    def _start_pollers(self):
        cfg      = self._config_mgr.get()
        workflows = cfg.get("workflows") or []
        for wid, entry in enumerate(workflows):
            self._add_poller(wid, entry)

    def _add_poller(self, wid: int, entry: dict):
        if wid in self._pollers:
            return
        url = entry.get("url", "")
        try:
            _, _, wf_file, url_branch = parse_workflow_url(url)
        except ValueError:
            wf_file = url
            url_branch = None
        branch   = entry.get("branch") or url_branch
        name     = entry.get("name") or wf_file or url
        state    = WorkflowState(name=name, url=url, branch=branch)
        self._states[wid] = state

        alt = len(self._rows) % 2 == 1
        row = WorkflowRow(self._list_frame, wid, state, alt)
        poll_rate = int(entry.get("polling_rate", POLL_DEFAULT))
        row.update(state, poll_rate)
        self._rows[wid] = row

        poller = WorkflowPoller(wid, entry, self._config_mgr, self._event_queue)
        self._pollers[wid] = poller
        poller.start()

    def _stop_all_pollers(self):
        for p in self._pollers.values():
            p.stop()
        self._pollers.clear()

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
        self._states[event.workflow_id] = event.new_state
        cfg      = self._config_mgr.get()
        workflows = cfg.get("workflows") or []
        entry    = workflows[event.workflow_id] if event.workflow_id < len(workflows) else {}
        poll_rate = int(entry.get("polling_rate", POLL_DEFAULT))

        row = self._rows.get(event.workflow_id)
        if row:
            row.update(event.new_state, poll_rate)

        if self._tray:
            self._tray.update(list(self._states.values()))

    # ------------------------------------------------------------------
    # Config hot-reload
    # ------------------------------------------------------------------
    def _watch_config(self):
        changed = self._config_mgr.load()
        if changed:
            self._reload_pollers()
        self._root.after(2000, self._watch_config)

    def _reload_pollers(self):
        self._stop_all_pollers()
        for row in self._rows.values():
            row.frame.destroy()
        self._rows.clear()
        self._states.clear()
        self._start_pollers()

    # ------------------------------------------------------------------
    # Window / tray behaviour
    # ------------------------------------------------------------------
    def set_tray(self, tray: TrayManager):
        self._tray = tray

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
