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
from datetime import datetime
from pathlib import Path
from typing import Optional
import base64
import io

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
    from PIL import Image
except ImportError:
    _missing.append("Pillow")

if _missing:
    _app = QApplication(sys.argv)
    QMessageBox.critical(
        None,
        "Actions Monitor - Missing Dependencies",
        "Please install the required packages:\n\n"
        f"  pip install {' '.join(_missing)}\n\n"
        "Then restart the application.",
    )
    sys.exit(1)

from icons import (
    _pil_to_qpixmap,
    _make_base_icon,
    _make_icon_image,
    _make_refresh_icon,
    _make_update_icon,
    _make_help_icon,
    _reviewer_icon_b64,
    _init_snooze_icons,
    _init_status_icons,
    _generate_app_ico,
    _generate_check_glyph,
    _snooze_qpixmaps,
    _status_qpixmaps,
)

import update
from update import (
    UpdateChecker,
    UpdateDialog,
    _detect_install_source,
    _cleanup_stale_mei_dirs,
)

import gh_api
from gh_api import (
    _gh_headers,
    parse_workflow_url,
    _build_workflow_url,
    _build_branch_url,
    parse_actor_url,
    _github_api_get,
    _github_graphql_post,
    RateLimited,
    _friendly_error,
    fetch_latest_run,
    fetch_pr_runs,
    fetch_actor_runs,
    fetch_github_username,
    _prune_cache,
    _compile_bot_regex,
    _aggregate_review_status,
    _cached_review_fetch,
    _cached_unresolved_fetch,
    _PR_CACHE_MAX,
    _REVIEW_CACHE_MAX,
    _DEFAULT_BOT_PATTERN,
)

IS_WINDOWS = platform.system() == "Windows"
IS_LINUX   = platform.system() == "Linux"

if IS_WINDOWS:
    import winreg
    # Tell Windows to identify this process as "Actions Monitor" rather than "Python"
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("WizX20.ActionsMonitor")

import notifications
from notifications import NOTIF, _ensure_focus_vbs, LINUX_MISSING

import pollers
from pollers import (
    ActorWorkflowPoller,
    POLL_DEFAULT,
    PRWorkflowPoller,
    StatusEvent,
    URLQueryPoller,
    WorkflowPoller,
    WorkflowState,
    _combined_status,
    _deep_merge,
    section_flags,
    _STATUS_PRIORITY,
    ST_FAILURE,
    ST_SUCCESS,
    ST_UNKNOWN,
)

from widgets import (
    ACCENT,
    BG_DARK,
    BG_ROW,
    BG_ROW_ALT,
    COLOUR,
    FG_LINK,
    FG_MUTED,
    FG_TEXT,
    UI_FONT,
    WorkflowRow,
    _ClickableLabel,
)

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


def _bundled(name: str) -> Path:
    """Resolve a bundled data file (e.g. config.template.yaml).

    Onefile PyInstaller extracts data files to `_APP_DIR` next to the exe (legacy
    layout) or to `sys._MEIPASS` (the runtime extraction dir). Onedir bundles
    them inside `_internal/`, which `_MEIPASS` points at. Source runs find them
    next to the project root. Try `_APP_DIR` first so user-overridable copies win,
    then fall back to `_MEIPASS`. Caller checks `.exists()` on the result.
    """
    primary = _APP_DIR / name
    if primary.exists():
        return primary
    mei = getattr(sys, "_MEIPASS", None)
    if mei:
        bundled = Path(mei) / name
        if bundled.exists():
            return bundled
    return primary

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


# Wire notification module with paths/icons resolved above.
notifications.configure(
    app_name=APP_NAME,
    app_ico=APP_ICO,
    focus_vbs=_FOCUS_VBS,
    focus_signal=_FOCUS_SIGNAL,
)


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
        template = _bundled("config.template.yaml")
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


# Dataclasses (WorkflowState, StatusEvent), poller classes, and the
# NotificationManager singleton now live in pollers.py / notifications.py.


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
# Update flow — inject constants now that they're all defined
# ---------------------------------------------------------------------------
update.configure(
    app_name=APP_NAME,
    build_commit=BUILD_COMMIT,
    is_windows=IS_WINDOWS,
    fg_text=FG_TEXT,
    fg_muted=FG_MUTED,
    fg_link=FG_LINK,
    bg_row=BG_ROW,
    color_success=COLOUR[ST_SUCCESS],
    color_failure=COLOUR[ST_FAILURE],
    clickable_label_cls=_ClickableLabel,
)

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
        self.setMaximumWidth(720)
        self.resize(560, 420)

        _generate_app_ico(APP_ICO)
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
        # Sections with `include_in_tray_status: false` are excluded from the
        # combined tray status (e.g. URL inboxes for other people's PRs).
        excluded_wids = {
            wid for wid, p in self._pollers.items()
            if not section_flags(p.cfg_entry)["include_in_tray_status"]
        }
        unsnoozed = [
            s for (wid, sk), s in self._states.items()
            if (wid, sk) not in self._snoozed and wid not in excluded_wids
        ]
        combined = _combined_status(unsnoozed)
        if combined == self._prev_tray_status:
            return
        self._prev_tray_status = combined
        self._tray.setIcon(self._tray_icons.get(combined, self._tray_icons[ST_UNKNOWN]))
        self._tray.setToolTip(f"{APP_NAME} - {combined.replace('_', ' ').title()}")

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
            w = min(max(int(win["width"]), 400), 720)
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
        """Rebuild self._snoozed + the pollers snooze registry from state.json using stable
        workflow keys. Must run after self._wid_stable_keys is populated. Branch-mode rows
        that already exist get set_snoozed(True); dynamic rows pick it up when created via
        _drain_queue."""
        state = self._load_state()
        snoozed_cfg = state.get("snoozed") or {}
        if not snoozed_cfg:
            return
        stable_to_wid = {sk: wid for wid, sk in self._wid_stable_keys.items()}
        for sk, sub_keys in snoozed_cfg.items():
            wid = stable_to_wid.get(sk)
            if wid is None:
                continue
            for sub_key in sub_keys:
                key = (wid, sub_key)
                self._snoozed.add(key)
                pollers.add_snooze(wid, sub_key)
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

            row = self._rows.get(key)
            if row:
                # Update widget before committing state so a failure here doesn't
                # leave _states out of sync with what the UI is showing.
                row.update(event.new_state, poll_rate, jira_base_url=jira_url)
                self._states[key] = event.new_state
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
                self._states[key] = event.new_state
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
            pollers.add_snooze(*key)
        row = self._rows.get(key)
        if row:
            row.set_snoozed(key in self._snoozed)
        self._update_tray()
        self._save_snoozed_state()

    def _unsnooze(self, key: tuple[int, Optional[str]]):
        self._snoozed.discard(key)
        pollers.discard_snooze(*key)
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
        pollers.clear_snooze()
        self._destroy_sections()
        gh_api.reset_username_cache()
        self._start_pollers()
        # Restore snooze state using new wid mapping
        stable_to_wid = {sk: wid for wid, sk in self._wid_stable_keys.items()}
        for sk, sub_key in saved_by_stable:
            wid = stable_to_wid.get(sk)
            if wid is None:
                continue
            key = (wid, sub_key)
            self._snoozed.add(key)
            pollers.add_snooze(wid, sub_key)

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
        exe = Path(sys.executable)
        install_dir = exe.parent
        # Remove leftovers from prior update attempts: legacy onefile sidecars
        # (`exe.old`, `exe.update`), the new onedir backups (`exe.exe.old`,
        # `_internal.old`), staging artifacts (`.am_update.zip`,
        # `.am_update_staging/`), and any stale `_MEI*` dirs in temp.
        for suffix in (".old", ".update"):
            try:
                exe.with_suffix(suffix).unlink(missing_ok=True)
            except OSError:
                pass
        for leftover in (
            install_dir / (exe.name + ".old"),
            install_dir / ".am_update.zip",
        ):
            try:
                leftover.unlink(missing_ok=True)
            except OSError:
                pass
        for leftover_dir in (
            install_dir / "_internal.old",
            install_dir / ".am_update_staging",
        ):
            shutil.rmtree(leftover_dir, ignore_errors=True)
        _cleanup_stale_mei_dirs()

    if IS_WINDOWS:
        _ensure_focus_vbs()

    app = QApplication(sys.argv)
    _generate_check_glyph(_CHECK_PNG)
    app.setStyleSheet(DARK_STYLESHEET)

    # Warn about missing Linux sound tools
    if IS_LINUX and LINUX_MISSING:
        QMessageBox.warning(
            None,
            "Actions Monitor - Missing System Libraries",
            "The following system packages are missing:\n\n"
            + "\n".join(f"  • {p}" for p in LINUX_MISSING)
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
