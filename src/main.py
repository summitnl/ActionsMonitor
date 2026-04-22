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
import tempfile

from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QLabel,
    QVBoxLayout, QHBoxLayout, QFrame, QScrollArea, QCheckBox, QMenu,
    QDialog, QSystemTrayIcon, QMessageBox, QPushButton, QSizePolicy,
    QGraphicsOpacityEffect)
from PySide6.QtCore import Qt, QTimer, QPoint, QSize, QEvent
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
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Summit.ActionsMonitor")

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

# Summit logo (docs/summit.png exported at 56px height, base64-encoded to avoid bundling issues)
_SUMMIT_LOGO_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAOgAAAA4CAYAAAD3l7RXAAAABmJLR0QA/wD/AP+gvaeTAAARuUlE"
    "QVR4nO2deZwU1bXHv6dnhk1AtkRjIouyGVAkLDMoEXFH4/bcNcZEY1yiAsZETXwJLjFG82TALfEj"
    "RvMSTVxiMIoR4gNcYAAN4BoRRFBRCDsJA8xM/94ft0eb6lvV1T0LKPX9fOaPuXWXU9196t577jmn"
    "ICEhISEhISEhIeFzhYVemTd+H+rsZLAKoCuoBGwd0muU2NMMWTcdG5duPlETEnY9chV01u09sdSt"
    "GCcCqYimiyD9EyrGPtZ04iUk7Npsr6BVE84E3QfsFr8HzcQYw9CxCxpZtoSEXZ5PFXRO5bcQDxC1"
    "7A0nDUyiruY6Dv7hqkaSLSFhl8cp46yJA0mlq4AWDexuA3AT7dZNpN+4bQ2WLiFhFyeFZKTS9+BT"
    "TvE60oWQ6keJ9iVto4A/4mZMD9oddBubOrzO7NuPb0rBExKaEkktJA2V1GNHymHMnXA4af0954qY"
    "RFnrSxh8UU3OtbmVQxCViIOiu9dUKBlLxRVvNpbACQnFIKkzcDbwBWCamb3gqfNV4GJgKHAg0BI4"
    "z8x+15yyZmPMrrwP44JA+Uss32sEp59eF9pSMuZOPAvpFmDviDFqMd1DncZx0JVrG0PohIRCkNQL"
    "eB7YM6v4BjP7WaDeBcB9geY7VEFTGMNzSo0bI5UTwEyUj36I0tZ9ka4HNofULEV2OanUO8ypvIzp"
    "40obLnZCQkH8gu2VE+A6SfvuCGEKIYXRPVBWx5rUjNg9DL5oM8PGjiNV1xd4GFBIzU6IO2jdYQFV"
    "lUcWJW1CQnHs7ylLhZTvVKQQLQNl1Rx7xdaCexr6g/epGHM2aRuOmBdRsx8wlarKyVRN6FXwOE2A"
    "pDJJHSUVc8SUsPPjs4EIeCNG27JGlqUgjKpK34y3JxVjVhbdq8almNvxXKRfAF+KqLkNNJHSrTcx"
    "+JoNRY9XqHhSC+AU4FSgAtgrc6kOWArMBp4AnjKzXCOZ66MEOBKYa2YF760lDQC2AW+bWajLpKSD"
    "gI/N7N2Q6wYcDIzAGUA2AW8DU80s9ExaUstMm8GZdnXAR8A8YJaZ1RZwL8cAr5jZv0KutwJGAV8D"
    "2gFrgPnAc2ZWHdFvJ9xn3A/olLm394CXzOz1AuTbH3gB2D2r+A4zuyJQz7cHrTSzsXHHamxCFNTG"
    "UDF6QoN7n35XW1rVXItxJdAqouZKpOuo2HB/U/v3SjocuBfYJ0b15cDPgAfNbLvPKfMD35L59x3c"
    "D/t5M/tNTDkqgdHAhkzbOcD9QUWU9DRwLLAamJv5u9PM1mTu5XbgAM8QNcCfgGvN7IOs/loBPwDG"
    "AF1CxFsJ3AmMN7P/xLiXrbhjuqWZ+5htZhMlpXBW0XG4h0CQ9cAE4JfZiirpy8CNwDmEn82/BtwC"
    "PBz8bkJk7AZchJswngEe9XynPgVdBexrZv/ON0ZTEDaDrqGudBAHX7asUUaZc0cPlL4VdGoeaeY7"
    "t8ExzzfKuAEkXQjcA5QU2PQZ4FwzW5PVV7aC1vORme1FDLIUNJtzzez3gXr1CprNEOBE4Cfk9/xa"
    "D5xhZlMzP9In8Su0j3czbV+OqpSloPX8G7cq+RNu5szH68A3zGyZpKNwZ+0dY8o4Ffhm2OxdCCEK"
    "CvAQ7rtp9uCQMGf4zpTUzmB2ZXmjjFJ++VIqRp9GOnUoEO6zKwaSZmZJ1YTHmD2+e6OMXd+1NJLi"
    "lBNgZ7P23QxcRzy3zA7Ak5JOB2YQXznBrTJmSjq0QPlKgCnEU06A/sB0SWfgHiBxlRPgKOBFSUEr"
    "bWNyNvCMpP5NOIaXiGgVumPMpqryEV6e0LVRRjvoipmUrx+EcR5uGeWlDp1Slip995A3H53xw6XT"
    "G/zBZ/ZpE/Er5z+AXwHXALfh9p/Zq4rVwHHZs+dOQKFW8Ja42ax7EWO1AZ6QFGdLUE9r8BzfRdMD"
    "N3MGjZZx6A38RZLXoCPpAEkPSxorabikNkWMcRTwmqQlkmZKmtYcRsV8Z5IGnEatRlE1/maqO4xn"
    "5HeCy7rCsHFpSfNX11b/85crXt5j4scL2abcI9ca1dnzGz8c8Xb1ug8vWDLtN5P2PfLSBow6GPeU"
    "zqYaOMfMnghWzhgVJgDDgJPMbHEDxm5KaoBHcLPVKuDLwAnASUQ/fOtZBDyA28+V4jxozgf2CNTr"
    "APwa9yMtlHXAb4GXcGflfYBv4QxGcXged4/v4vbMhwFnkavI5cBY4FZPH22BMzN/ALWSJpnZxfFv"
    "4xP24VP7hRF+rNgohO1Bw1gK+lGxMaCSugA3AN8jM5u9s2U9Vy1/gSfXeY2Un3Bchx4L2/TZOuhR"
    "y+NA4R/3YtzyNpvrzWxcRJsUcICZeZfkO3gPCrACON7M/uHpewTwZ5zlM4z/Aa4JWmsltQcexCl5"
    "kENCXOSCe9B6XgBODVqTMzPPWNzKJWwW2gp8x8we9ozXF5iMmzmzWQt0DRq2MpbwlwJ1nzKz4wP1"
    "wvagYZQ09b40zlM2mx5gjzJn/Azmjj8wbqPMOeNo3BP7ErKWmr1adWBy7+OZ1vdk+rfuHNrH0+uX"
    "Dti6qNXsAuWtx2dBXhTVwMzSYcq5E7ANONannABmNhN3jBT28H3QzK7yHaWY2UbgdKDK0+7bBci4"
    "GLc1yDnqMTOZ2e3AzyPaX+xTzkz7fwJH4yzg2XTCGc8ak/m4I6gdgk9B12IcA7wV2ko2grS9QlXl"
    "vbx02xejBpA0CngVqCRi83/E7l2X/2P/s6b/Yu+Dl3cu9Z/IPLnu3SGXvPvcdVHjhfChp+yCsD3L"
    "Z4DfmdnCqApmNgNncAmyDbg6T9uakDpHxBUQt0LZlKfOzbg9fpBXcbN4KGb2Hm4bEuTwWNLF51e4"
    "ZfmNuBXBB7hl+7pGHseLfwYtH/Mspa0HIEbjlg1hbS+kpMUiqiZcxRvjtlviSOqbWZ5NAfpGyDAL"
    "GG5m3VqkSg+79stDul21x5BeR3fotsC39pm6cfl/j9P0Qv15Z+B+mNkcBjy3IyxzjYBP8Xz81VM2"
    "x8ziOKG8QO5331VSnGwbChl7OzJnn9M8lybHOdvELXOD7BejXUGY2RIz+6mZHWJme5tZp8xfkx+7"
    "hC9xB19Uw7AxE7HS3mB3ASGeJZ/EgL7B7MoTMi5z43FPQd/eqZ73cebr4Wa23f7g2r0HLX6278kD"
    "z+zSJ+cpumTLhharlkbPAEEyZ2S+vcXXgYWSJks6OrPv/CzwUcx6vpXDijgNMwria98hRvPNZhbX"
    "M+wDT1nc+/O1LeSIZqcn/w+y/LI1VIy+jFT6QPxPu3p6Ykwe+dbjK1+vXjOGcB/GzTjPkr5mFukF"
    "8nDPUd8+qN2Xcn4kS7duOCuv3LlcA/iWhSmc5fNvwGJJP5bk83rZmYhr2PM94QsxCvrax3mINXSM"
    "hrT9rDxkYxH/ZoZe+QYVY45C6RNwrm1eZmz8oGzgaw/x/fems6Z2OyOncB4ZfczsejMLC0/bjv1b"
    "d6kMlr2/bVP32HJnyOyHjgBmRlTrgTNcLJd0p6TgcUNCQrNS+NNm2JV/pd36/sBVKfxGgFqluXvl"
    "q/Ra+AATPl7ANtXNAw42s3Oy/ULj0KakxZ+DZWtrt0b59YZiZqtxRoTLiXCUwFl9vw+8LqmxrYIJ"
    "CbEpajmgr/6spcpHf2HF177b8ntf7E+J+Y+y1tVuZcyymbSce2c7q6qMs3fJoazOPEtlFX04bGZ1"
    "ZnYnzqvmuxAZGtcF+HPGhzchodkpSEElpSSdjztDvHqPsjYtftPjcF7pfzaHtv9KVNO+mE2hqnIK"
    "s+6Isujm8B9qTguWdS5rFRqiFBcz22Jmk8ysPv/MXbhwpiAp4G5JQxs6ZsIOw/dA/0zE/sZWUEnD"
    "caFOkwikjxjQpgvT9zuFx3odpz3LdosKTxpFqu5VqsZX8sLdsaxtC6v/dUWwrHvL9kvjyh0HM1to"
    "ZpfhcivdjHOhy6YUlzYjIaFZyaugkrpK+iPOJ3JQRNVXTunU85CPN5Z2AbsW/2wEUAY2mrJt71BV"
    "eWlUjqLzF0+b/OKmFTkW1W4tdn8gn9zFYGYbzOwnwDHkKulISdlOGb5jp0LyCvv20Uku4YTtCFVQ"
    "SbvJJQP7J3AG4UuCj3EO1kPN7EVGfmcLFaNvoVR9cE7SYWb0zsBdtOown9mVJ/DII5+4/523+NlB"
    "o956YtH9q984IdioT6uO1V26j2h4MHkEZvZ/wB+CxWQ53JtZHRCMQeycCTaOwwBPWdzzv4RdBK+C"
    "SjoHp5g/xYUO+diCi2jvbWa/zfGqGDz2IyrGnI+ly8l1VP4Uoz/GZLquWGtVExZ0nPfrNb9b/dbL"
    "z2xYlpOvKIVxTMdu14wrwoNDUntJ90qKe5C9xFMW9KLx+cJ+L4YsA3DRF9nU4j+nTdiF2U5BS7AP"
    "p/Q5cTnweyDK6vM40M/Mrs3rb1l+5cuUj/462FmI5RE12wsNWFe3pVOYifbMzn2mTeh26MTI8Txk"
    "lqYzgAuBZwNL1TBGesqCM5zP1exHkoZFyNIevO/AmZ5xVE/Ycfi2Le2bXYosPlHQllay9L2B56dG"
    "degeFaWyABhpZqeGJbHyYiYqRv8RpfvicvzkzXOzXXPg7M59pj/U65iC4xEldQdeBAZmioYA8yWd"
    "4gu4lVQq6Wacr242m3Bxk9n8gVyn6VbAVEkXZZKTZfddH/bk+4zviHE7CU2LbwI5LegCKql3c2WA"
    "LAUwbMOrB3yTr7RoG5aBbxUuxcb9mb1XcRx0ZTVwA1UT79+tpOT2zXW1p4roG+3Rsn3NSR33vWF8"
    "9xE3FTnqjUBwubwX8BiwSNJkXPrFOpyj9elAT08/fzCz7dKRmtlGST8lV7na4gKcfy5pHi44vB+5"
    "8Yv1PGdmeZ3LE5qcKtyDuF1W2WHAHElT+DSofSTwX8QPWiiaUoCr9xo0v3erDod6rm/DpQq5qQDn"
    "50gyIV6nAEe8vWWdTVr1BlM3LOPN6rXUyG0tv1S2G+Vt96w9cLcujw9s2fHCE7/QN1/YUhSXAt1w"
    "jvFBegM/jNHHGuD6kGt34b7Ekz3XOuMswlF8RGFxlglNhJlVS7oXl/Uwm8GZv2x+TDMoKGVzJi6r"
    "Tae3KZf5cu+0aDQkjZL0lmcs1SmttTVbtLmuJi3pfwuwhsYZt5Wk+3zjxuDfkg7J039rSX8tou/3"
    "JfXL0/fTnnZRx13ZbY/ytPUGQYe0X+Bpn/MeHklbA3ViP1Al3eIZ45KYbbt42r7tqTfMU++pkD7b"
    "SXrbU99HIfGxRZE6qWPPd0osx51uGXC4mYU6xReCXGzoFCJiQ1MYHUtbVrVOlQ4zs3PNzBfqVBQZ"
    "r6Hv4rLMxU54jAuZG25mkWlAM3GNJ+GeqnG9nJ4ABplZnOzm9awCniL3eCcONTi3xqhggSg+wMmc"
    "T/kW47YPxbARmE68jO9B0rgM8vlmtTrcb8D7OWSMnocDr8QYs8kVlGfXvzff82Q4tzH6losNrZTk"
    "m6GzeV/SN9UMG29JJulIuRl1iUeWjZKeknSGXPb4QvvfS9KNkt709L1K0oOKsPJ6+vuWpNPljF2F"
    "ytJH0uWSyuVyKBXa/hJJJ0qKzLMkF6J3jNwr/godY5Sk8yTtpwLjcSW1lXS1pJFy1vGwevtIukrS"
    "CEltY/ZdKulCSbMk1WR9h+sl/UUuU0jTs7a2enXgR1Qb9ybCyNzcpZKCfQfZLOl6xYvSbxIktcl8"
    "gT0zytVoDwm5s9d+kgZKinoFRsJOTOb33FFSUQEfDSLtFDKb4t/JAsjNTq/lUcy0XJ7Sxsm3m5Dw"
    "eUXSpoDybFERybQk9ZJLHZKPeZIObop7SUj43CG/pS525nJJu0u6TbmWvCArJH1bn528PwkJOx5J"
    "d3iUaZakyMx5kkrkNtEr8yhmtaSb1cB9bULCLomkihDF+r3cq+p8bQ6VOyfNx2OSejT3PSUkfK6Q"
    "9PcQBVsi98KZCkmDJJ0l6ZkYijlf7vUDCQkJDUXO+TdoLCqGlXLL3mSfmZDQmEj6hvI7FISxVdKt"
    "knbPP1JCQkJRSDpCztulEP4iyRf9kZCQ0NhI+qKke+Ssr1HMktTYL6pJSEjIItStTVIn4Bu4l9h2"
    "w73KYRUuLcffzOzVZpEwISEhISEhISEhISEh4fPC/wPjBi9j/xs8xgAAAABJRU5ErkJggg=="
)

CONFIG_FILE    = _APP_DIR / "config.yaml"
STATE_FILE     = _APP_DIR / "state.json"
APP_ICO        = _APP_DIR / "app.ico"
_FOCUS_VBS     = _APP_DIR / "_focus.vbs"
_FOCUS_SIGNAL  = _APP_DIR / "_focus_signal"


_FOCUS_SH = _APP_DIR / "_focus.sh"


def _ensure_focus_vbs():
    """Create a small VBScript that writes a signal file when executed (silent, no CMD flash)."""
    script = (
        'Set fso = CreateObject("Scripting.FileSystemObject")\n'
        f'fso.CreateTextFile "{_FOCUS_SIGNAL}", True\n'
    )
    _FOCUS_VBS.write_text(script, encoding="utf-8")


def _ensure_focus_sh():
    """Create a small shell script that writes a signal file when executed (Linux).
    Note: currently unused — plyer notifications on Linux don't support a launch
    callback, so clicking a toast won't trigger this script. Created for future
    use when a Linux notification backend with launch support is added."""
    script = f'#!/bin/sh\ntouch "{_FOCUS_SIGNAL}"\n'
    _FOCUS_SH.write_text(script, encoding="utf-8")
    _FOCUS_SH.chmod(_FOCUS_SH.stat().st_mode | stat.S_IEXEC)

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


def _github_api_get(url: str, token: str, session: Optional[requests.Session] = None,
                    params: Optional[dict] = None, timeout: int = 15):
    """Perform a GitHub API GET request with standard headers."""
    _get = (session or requests).get
    resp = _get(url, params=params, headers=_gh_headers(token), timeout=timeout)
    resp.raise_for_status()
    return resp.json()


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

    def _poll(self):
        cfg   = self.config_mgr.get()
        token = cfg.get("github_token", "")
        notif_cfg = cfg.get("notifications", {})

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

            # Fallback: query the Pulls API when workflow runs lack PR data
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
                agg_status = _worst_status(set(run_statuses))

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
        url = (
            f"https://api.github.com/repos/{self.owner}/{self.repo}"
            f"/actions/workflows/{wf_file}/runs"
        )
        params = {"branch": branch, "per_page": 1}
        return _github_api_get(url, token, self._session, params).get("workflow_runs", [])

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

    @staticmethod
    def _pr_num_from_sub_key(sk: str) -> Optional[int]:
        """Extract the PR number from a sub_key like 'branch#123'."""
        if "#" in sk:
            try:
                return int(sk.rsplit("#", 1)[1])
            except (ValueError, IndexError):
                pass
        return None

    def _fetch_pr_review_status(self, pr_number: int, token: str) -> Optional[str]:
        """Fetch the aggregate review status for a PR.
        Returns 'approved', 'changes_requested', 'commented', 'pending', or None.
        Cached for _review_cache_ttl seconds to reduce API calls."""
        cached = self._review_cache.get(pr_number)
        if cached is not None:
            status, fetch_time = cached
            if time.monotonic() - fetch_time < self._review_cache_ttl:
                return status
        try:
            url = (
                f"https://api.github.com/repos/{self.owner}/{self.repo}"
                f"/pulls/{pr_number}/reviews"
            )
            reviews = _github_api_get(url, token, self._session)

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
                result = "commented" if has_comments else "pending"
            elif "CHANGES_REQUESTED" in latest.values():
                result = "changes_requested"
            else:
                result = "approved"
            self._review_cache[pr_number] = (result, time.monotonic())
            return result
        except Exception:
            return cached[0] if cached else None


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


# --- Snooze button icon (crescent moon) ---

_SNOOZE_ICON_SIZE = 24


def _draw_z_glyph(draw: ImageDraw.Draw, x: int, y: int, w: int, h: int,
                   colour: str, width: int):
    """Draw a single Z glyph (three strokes: top, diagonal, bottom)."""
    draw.line([(x, y), (x + w, y)], fill=colour, width=width)
    draw.line([(x + w, y), (x, y + h)], fill=colour, width=width)
    draw.line([(x, y + h), (x + w, y + h)], fill=colour, width=width)


def _make_snooze_icon(size: int = _SNOOZE_ICON_SIZE, bg_colour: str = "#3D3530",
                      fg_colour: str = "#A8A29E") -> Image.Image:
    """Zzz icon on a filled circle background for the snooze button."""
    img, draw, hi = _icon_base(size)
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
    _draw_z_glyph(draw, zx, zy, zw, zh, c, sw)
    # Medium Z (middle area)
    zw2, zh2 = int(zw * 0.60), int(zh * 0.60)
    zx2, zy2 = inset + int(iw * 0.28), inset + int(iw * 0.22)
    _draw_z_glyph(draw, zx2, zy2, zw2, zh2, c, sw)
    # Small Z (top-right area)
    zw3, zh3 = int(zw * 0.35), int(zh * 0.35)
    zx3, zy3 = inset + int(iw * 0.52), inset + int(iw * 0.02)
    _draw_z_glyph(draw, zx3, zy3, zw3, zh3, c, sw)
    return img.resize((size, size), Image.LANCZOS)


def _pil_to_qpixmap(pil_img: Image.Image) -> QPixmap:
    """Convert a PIL Image to a QPixmap."""
    img = pil_img.convert("RGBA")
    data = img.tobytes("raw", "RGBA")
    qimg = QImage(data, img.width, img.height, img.width * 4, QImage.Format.Format_RGBA8888)
    return QPixmap.fromImage(qimg)


_snooze_qpixmaps: dict[str, QPixmap] = {}


_SNOOZE_ICON_STYLES = {
    "normal":       ("#3D3530", "#A8A29E"),
    "hover":        ("#4A3728", "#FBBF24"),
    "active":       ("#92400E", "#FEF3C7"),
    "active_hover": ("#78350F", "#FFFFFF"),
}


def _init_snooze_icons():
    """Generate snooze/unsnooze button icons (normal + hover). Call after QApplication exists."""
    if _snooze_qpixmaps:
        return
    for key, (bg, fg) in _SNOOZE_ICON_STYLES.items():
        _snooze_qpixmaps[key] = _pil_to_qpixmap(
            _make_snooze_icon(bg_colour=bg, fg_colour=fg))


# --- App / tray icon (play triangle on dark rounded rect + status dot) ---

def _make_base_icon(size: int = 64) -> Image.Image:
    """App icon: amber play triangle on dark rounded-rect background."""
    img, draw, hi = _icon_base(size)

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
        f"padding: 0px 3px; border-radius: 2px;"
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

        # Snooze button
        self._snooze_btn = QLabel()
        self._snooze_btn.setPixmap(_snooze_qpixmaps.get("normal", QPixmap()))
        self._snooze_btn.setFixedSize(24, 24)
        self._snooze_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._snooze_btn.setToolTip("Snooze — dim this row and exclude from tray status")
        self._snooze_btn.mousePressEvent = lambda e: self._toggle_snooze()
        self._snooze_btn.enterEvent = lambda e: self._snooze_hover_enter()
        self._snooze_btn.leaveEvent = lambda e: self._snooze_hover_leave()
        self._snooze_btn.setVisible(False)
        left_col.addWidget(self._snooze_btn, 0, Qt.AlignmentFlag.AlignHCenter)
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
        top_row.addWidget(self._name_lbl, 1)

        self._branch_lbl = _ClickableLabel(
            url_fn=lambda: self._state.run_url or self._state.url)
        self._branch_lbl.setStyleSheet(f"color: {FG_MUTED}; font-size: 11px;")
        self._branch_lbl.setMinimumWidth(0)
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

        self._jira_lbl = _make_badge("", "#302830", "#A78BFA")
        self._jira_lbl.setCursor(Qt.CursorShape.PointingHandCursor)
        self._jira_lbl.mousePressEvent = lambda e: self._open_jira()
        badge_layout.addWidget(self._jira_lbl)

        self._review_lbl = _make_badge("", "#3D3530", "#FBBF24")
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
        centre.addWidget(self._info_lbl)

        main_layout.addLayout(centre, 1)

        # Right column: poll rate (fixed width, never pushed off-screen)
        self._poll_lbl = QLabel()
        self._poll_lbl.setStyleSheet(f"color: {FG_MUTED}; font-size: 11px;")
        self._poll_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        self._poll_lbl.setContentsMargins(4, 10, 12, 0)
        self._poll_lbl.setMinimumWidth(70)
        self._poll_lbl.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        main_layout.addWidget(self._poll_lbl)

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
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
                f"font-weight: {weight}; padding: 0px 3px; border-radius: 2px;")

    def _restyle_static_badges(self):
        self._prefix_lbl.setStyleSheet(self._badge_css("#3D3530", "#FBBF24"))
        self._draft_lbl.setStyleSheet(self._badge_css("#92400E", "#FEF3C7", bold=True))
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
        self._poll_lbl.setText(f"every {poll_rate}s")
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

            if s.jira_key and self._jira_base_url:
                self._jira_lbl.setText(s.jira_key)
                self._jira_lbl.setVisible(True)
                has_badges = True
            else:
                self._jira_lbl.setVisible(False)

            if s.review_status:
                text, bg_col, fg_col = _REVIEW_BADGE_CFG.get(
                    s.review_status, ("REVIEW PENDING", "#3D3530", "#FBBF24"))
                self._review_lbl.setText(text)
                self._review_lbl.setStyleSheet(self._badge_css(bg_col, fg_col))
                self._review_lbl.setVisible(True)
                has_badges = True
            else:
                self._review_lbl.setVisible(False)

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
            self._jira_lbl.setVisible(False)
            self._review_lbl.setVisible(False)
            self._stale_lbl.setVisible(False)
            self._pr_title_lbl.setVisible(False)

            self._snooze_lbl.setVisible(self._snoozed)
            self._badge_widget.setVisible(self._snoozed)

        # Snooze button visibility
        if self._snoozed:
            self._snooze_btn.setPixmap(_snooze_qpixmaps.get("active", QPixmap()))
            self._snooze_btn.setVisible(True)
        elif s.status == ST_FAILURE:
            self._snooze_btn.setPixmap(_snooze_qpixmaps.get("normal", QPixmap()))
            self._snooze_btn.setVisible(True)
        else:
            self._snooze_btn.setVisible(False)


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
    def apply_update() -> tuple[bool, str]:
        """Download latest release binary. Returns (success, message)."""
        return UpdateChecker._apply_release_update()

    @staticmethod
    def _apply_release_update() -> tuple[bool, str]:
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
            expected_size = asset.get("size")
            current_exe = Path(sys.executable)
            tmp_path = current_exe.with_suffix(".update")

            bytes_written = 0
            with requests.get(download_url, stream=True, timeout=120) as dl:
                dl.raise_for_status()
                with open(tmp_path, "wb") as f:
                    for chunk in dl.iter_content(chunk_size=65536):
                        f.write(chunk)
                        bytes_written += len(chunk)

            if expected_size and bytes_written != expected_size:
                try:
                    tmp_path.unlink(missing_ok=True)
                except OSError:
                    pass
                return False, (
                    f"Download size mismatch (got {bytes_written}, expected {expected_size})"
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
            script.write_text(
                "@echo off\r\n"
                ":waitpid\r\n"
                f'tasklist /FI "PID eq {pid}" 2>nul | findstr /C:"{pid}" >nul\r\n'
                "if %errorlevel% EQU 0 (\r\n"
                "  ping -n 2 127.0.0.1 >nul\r\n"
                "  goto waitpid\r\n"
                ")\r\n"
                "set /a tries=0\r\n"
                ":tryrename\r\n"
                f'move /y "{current_exe}" "{old_path}" >nul 2>&1\r\n'
                "if errorlevel 1 (\r\n"
                "  ping -n 2 127.0.0.1 >nul\r\n"
                "  set /a tries+=1\r\n"
                "  if %tries% LSS 10 goto tryrename\r\n"
                "  exit /b 1\r\n"
                ")\r\n"
                f'move /y "{update_path}" "{current_exe}" >nul 2>&1\r\n'
                f'start "" "{current_exe}"\r\n'
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
            script.write_text(
                "#!/bin/sh\n"
                f"while kill -0 {pid} 2>/dev/null; do sleep 0.5; done\n"
                f'mv -f "{current_exe}" "{old_path}"\n'
                f'mv -f "{update_path}" "{current_exe}"\n'
                f'chmod +x "{current_exe}"\n'
                f'nohup "{current_exe}" >/dev/null 2>&1 &\n'
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
    def __init__(self, commit_hash: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{APP_NAME} — Update Available")
        self.setFixedSize(420, 240)

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

        self._status_lbl = QLabel("")
        self._status_lbl.setStyleSheet(f"color: {FG_MUTED}; font-size: 12px;")
        layout.addWidget(self._status_lbl)

        layout.addStretch()

        btn_layout = QHBoxLayout()
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

    def _do_update(self):
        self._update_btn.setEnabled(False)
        self._skip_btn.setEnabled(False)
        self._status_lbl.setText("Updating...")
        self._status_lbl.setStyleSheet(f"color: {FG_TEXT}; font-size: 12px;")

        def _run():
            ok, msg = UpdateChecker.apply_update()
            QTimer.singleShot(0, lambda: self._on_result(ok, msg))

        threading.Thread(target=_run, daemon=True).start()

    def _on_result(self, ok, msg):
        if ok:
            self._status_lbl.setText("Update complete — restarting...")
            self._status_lbl.setStyleSheet(f"color: {COLOUR[ST_SUCCESS]}; font-size: 12px;")
            QTimer.singleShot(500, UpdateChecker.restart_app)
        else:
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
    QCheckBox {{ color: {FG_MUTED}; font-size: 11px; spacing: 4px; }}
    QCheckBox::indicator {{ width: 14px; height: 14px; }}
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
        self._tray: Optional[QSystemTrayIcon] = None
        self._tray_icons: dict[str, QIcon] = {}
        self._prev_tray_status: Optional[str] = None
        self._sections: list[QWidget] = []
        self._wid_container: dict[int, QWidget] = {}
        self._section_content: dict[str, QWidget] = {}
        self._section_content_layout: dict[str, QVBoxLayout] = {}
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

        # Summit logo
        logo_data = base64.b64decode(_SUMMIT_LOGO_B64)
        logo_img = Image.open(io.BytesIO(logo_data))
        scale = 28 / logo_img.height
        logo_img = logo_img.resize((round(logo_img.width * scale), 28), Image.LANCZOS)
        logo_lbl = _ClickableLabel(url_fn=lambda: "https://summit.nl")
        logo_lbl.setPixmap(_pil_to_qpixmap(logo_img))
        logo_lbl.setToolTip("summit.nl")
        header_layout.addWidget(logo_lbl)

        title_lbl = QLabel(APP_NAME)
        title_lbl.setStyleSheet(f"color: {FG_TEXT}; font-size: 15px;")
        title_lbl.setContentsMargins(10, 0, 16, 0)
        header_layout.addWidget(title_lbl)
        header_layout.addStretch()

        refresh_pm = _pil_to_qpixmap(_make_refresh_icon(24))
        refresh_btn = QLabel()
        refresh_btn.setPixmap(refresh_pm)
        refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh_btn.setToolTip("Refresh all workflows")
        refresh_btn.mousePressEvent = lambda e: self._refresh_all()
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
        row1_layout.setContentsMargins(14, 10, 14, 6)
        row1_layout.setSpacing(18)

        state = self._load_state()

        if IS_WINDOWS:
            self._startup_cb = QCheckBox("Start with Windows")
            self._startup_cb.setChecked(StartupManager.is_enabled())
            self._startup_cb.toggled.connect(self._toggle_startup)
            row1_layout.addWidget(self._startup_cb)

        self._aot_cb = QCheckBox("Always on top")
        self._aot_cb.setChecked(state.get("always_on_top", False))
        self._aot_cb.toggled.connect(self._toggle_always_on_top)
        row1_layout.addWidget(self._aot_cb)

        self._min_tray_cb = QCheckBox("Minimize to tray on close")
        self._min_tray_cb.setChecked(state.get("minimize_to_tray", True))
        self._min_tray_cb.toggled.connect(self._toggle_minimize_to_tray)
        row1_layout.addWidget(self._min_tray_cb)

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

    def _resort_section_for_wid(self, wid: int):
        container = self._wid_container.get(wid)
        if not container:
            return
        for title, content in self._section_content.items():
            if content is container and self._section_sort.get(title):
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
        self._section_indicators.clear()
        self._sort_labels.clear()

    # ------------------------------------------------------------------
    # Pollers
    # ------------------------------------------------------------------
    def _start_pollers(self):
        cfg = self._config_mgr.get()
        notif_cfg = cfg.get("notifications", {})
        NOTIF.set_batch_window(float(notif_cfg.get("batch_window", 3)))
        workflows = cfg.get("workflows") or []

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

        container = self._wid_container.get(wid, self._scroll_content)

        if mode == "pr":
            poller = PRWorkflowPoller(wid, entry, self._config_mgr, self._event_queue)
        elif mode == "actor":
            poller = ActorWorkflowPoller(wid, entry, self._config_mgr, self._event_queue)
        else:
            branch = entry.get("branch") or url_branch
            name = entry.get("name") or wf_file or url
            state = WorkflowState(name=name, url=url, branch=branch)
            key = (wid, None)
            self._states[key] = state

            alt = len(self._rows) % 2 == 1
            jira_url = cfg.get("jira_base_url", "")
            content_layout = self._section_content_layout.get(
                next((t for t, c in self._section_content.items() if c is container), ""))
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
        for p in self._pollers.values():
            p.trigger_poll()

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
            elif event.sub_key is not None:
                container = self._wid_container.get(event.workflow_id, self._scroll_content)
                content_layout = self._section_content_layout.get(
                    next((t for t, c in self._section_content.items() if c is container), ""))
                alt = len(self._rows) % 2 == 1
                new_row = WorkflowRow(None, event.workflow_id, event.new_state, alt,
                                      jira_base_url=jira_url, sub_key=event.sub_key,
                                      snooze_cb=self._show_row_ctx_menu)
                if content_layout:
                    content_layout.addWidget(new_row)
                new_row.update(event.new_state, poll_rate, jira_base_url=jira_url)
                self._rows[key] = new_row
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

    def _unsnooze(self, key: tuple[int, Optional[str]]):
        self._snoozed.discard(key)
        with _snoozed_lock:
            _snoozed_keys.discard(key)

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
        # Preserve snooze state across config hot-reloads
        saved_snoozed = set(self._snoozed)
        saved_snoozed_keys = set()
        with _snoozed_lock:
            saved_snoozed_keys = set(_snoozed_keys)
        self._stop_all_pollers()
        self._rows.clear()
        self._states.clear()
        self._snoozed.clear()
        with _snoozed_lock:
            _snoozed_keys.clear()
        self._destroy_sections()
        with _github_username_lock:
            _cached_github_username = None
        self._start_pollers()
        # Restore snooze state
        self._snoozed = saved_snoozed
        with _snoozed_lock:
            _snoozed_keys.update(saved_snoozed_keys)

    # ------------------------------------------------------------------
    # Window state persistence
    # ------------------------------------------------------------------
    @staticmethod
    def _load_state() -> dict:
        if STATE_FILE.exists():
            with open(STATE_FILE, encoding="utf-8") as fh:
                return json.load(fh)
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
        for f in [_FOCUS_SIGNAL, _FOCUS_VBS, _FOCUS_SH]:
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
    elif IS_LINUX:
        _ensure_focus_sh()

    app = QApplication(sys.argv)
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
    def _check_for_updates():
        new_version = UpdateChecker.check()
        if new_version:
            UpdateDialog(new_version, parent=win).exec()

    QTimer.singleShot(1500, _check_for_updates)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
