"""Update flow — release check, download/extract/swap, restart helper, dialog.

Self-contained: no compile-time main imports. PyInstaller re-executes the
entry script as both `__main__` and `main` when something does
`from main import ...`, which causes a circular reload. Instead, main.py
calls `update.configure(...)` once at startup to inject the handful of
constants + the `_ClickableLabel` widget class this module needs.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from pathlib import Path
from typing import Optional

import requests

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication, QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton,
    QVBoxLayout,
)


# ---------------------------------------------------------------------------
# Configuration injected by main at startup
# ---------------------------------------------------------------------------
APP_NAME: str = ""
BUILD_COMMIT: str = "dev"
IS_WINDOWS: bool = False

# Theme colours — populated by configure().
FG_TEXT = FG_MUTED = FG_LINK = BG_ROW = ""
_COLOR_SUCCESS = ""
_COLOR_FAILURE = ""

# Widget class — populated by configure().
_ClickableLabel = None


def configure(*, app_name: str, build_commit: str, is_windows: bool,
              fg_text: str, fg_muted: str, fg_link: str, bg_row: str,
              color_success: str, color_failure: str,
              clickable_label_cls) -> None:
    """Inject main.py constants + widget class. Call once before any update flow runs."""
    global APP_NAME, BUILD_COMMIT, IS_WINDOWS
    global FG_TEXT, FG_MUTED, FG_LINK, BG_ROW
    global _COLOR_SUCCESS, _COLOR_FAILURE, _ClickableLabel
    APP_NAME       = app_name
    BUILD_COMMIT   = build_commit
    IS_WINDOWS     = is_windows
    FG_TEXT        = fg_text
    FG_MUTED       = fg_muted
    FG_LINK        = fg_link
    BG_ROW         = bg_row
    _COLOR_SUCCESS = color_success
    _COLOR_FAILURE = color_failure
    _ClickableLabel = clickable_label_cls


# ---------------------------------------------------------------------------
# Install-source detection
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


def _cleanup_stale_mei_dirs(min_age_seconds: int = 86400) -> None:
    """Remove `_MEI*` dirs left over from force-killed PyInstaller processes.

    `os._exit(0)` and `taskkill /F` skip PyInstaller's atexit cleanup hook, so
    `restart_app()` and the helper batch's force-kill leave temp dirs behind.
    Skips the live `_MEI` (this process's extraction), skips dirs newer than
    `min_age_seconds` to avoid racing concurrent launches, and swallows every
    OS error so a locked dir can't crash startup.
    """
    if not getattr(sys, "frozen", False):
        return
    try:
        tmp_dir = Path(tempfile.gettempdir())
        live_mei = Path(getattr(sys, "_MEIPASS", "")).resolve() if getattr(sys, "_MEIPASS", None) else None
        cutoff = time.time() - min_age_seconds
        for entry in tmp_dir.glob("_MEI*"):
            try:
                if not entry.is_dir():
                    continue
                if live_mei and entry.resolve() == live_mei:
                    continue
                if entry.stat().st_mtime > cutoff:
                    continue
                shutil.rmtree(entry, ignore_errors=True)
            except OSError:
                pass
    except Exception:
        pass


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
        """Download the latest release zip and extract to a staging dir.

        Does NOT swap files — swap happens in a detached helper script launched
        by restart_app() after the current process has exited. The running exe
        and its mapped DLLs in `_internal/` are locked while we're alive, so
        all moves are deferred to the helper.
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

            asset_name = "ActionsMonitor.zip" if IS_WINDOWS else "ActionsMonitor-linux.zip"
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
            install_dir = current_exe.parent
            # Stage on the same volume as the install dir so the helper's
            # rename/move ops are atomic instead of cross-volume copy+delete.
            zip_path = install_dir / ".am_update.zip"
            staging_root = install_dir / ".am_update_staging"

            # Clear any leftovers from a previous failed attempt.
            try:
                zip_path.unlink(missing_ok=True)
            except OSError:
                pass
            shutil.rmtree(staging_root, ignore_errors=True)

            bytes_written = 0
            hasher = hashlib.sha256() if expected_sha256 else None
            if progress_cb:
                progress_cb(0, expected_size)
            # (connect_timeout, read_timeout) — read timeout is per-chunk, so a
            # slow proxy stalling mid-download trips after 60s instead of pinning
            # the dialog at 100% until the full 120s hits.
            dl = requests.get(download_url, stream=True, timeout=(15, 60))
            try:
                dl.raise_for_status()
                with open(zip_path, "wb") as f:
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
                    zip_path.unlink(missing_ok=True)
                except OSError:
                    pass
                return False, (
                    f"Download size mismatch (got {bytes_written}, expected {expected_size})"
                )

            if hasher:
                actual_sha256 = hasher.hexdigest()
                if actual_sha256 != expected_sha256:
                    try:
                        zip_path.unlink(missing_ok=True)
                    except OSError:
                        pass
                    return False, (
                        f"Checksum mismatch (got {actual_sha256[:12]}…, "
                        f"expected {expected_sha256[:12]}…)"
                    )

            # Extract zip into staging. Expected layout per the build pipeline:
            # `<staging_root>/<wrapper>/<exe>` + `<staging_root>/<wrapper>/_internal/...`
            # where <wrapper> is `ActionsMonitor` (Windows) or `ActionsMonitor-linux`
            # (Linux). Locate the wrapper by searching for the exe — robust to
            # future zip-layout tweaks.
            try:
                staging_root.mkdir(parents=True, exist_ok=True)
                with zipfile.ZipFile(zip_path) as zf:
                    zf.extractall(staging_root)
            except (zipfile.BadZipFile, OSError) as exc:
                shutil.rmtree(staging_root, ignore_errors=True)
                try:
                    zip_path.unlink(missing_ok=True)
                except OSError:
                    pass
                return False, f"Failed to extract update zip: {exc}"

            new_exe = next(
                (p for p in staging_root.rglob(current_exe.name) if p.is_file()),
                None,
            )
            if new_exe is None or not (new_exe.parent / "_internal").is_dir():
                shutil.rmtree(staging_root, ignore_errors=True)
                try:
                    zip_path.unlink(missing_ok=True)
                except OSError:
                    pass
                return False, "Update zip layout unexpected (missing exe or _internal/)"

            if not IS_WINDOWS:
                try:
                    new_exe.chmod(new_exe.stat().st_mode | stat.S_IEXEC)
                except OSError:
                    pass

            # Drop the now-redundant zip — staging dir holds the extracted files.
            try:
                zip_path.unlink(missing_ok=True)
            except OSError:
                pass

            # Helper consumes new_exe.parent (the wrapper dir containing the
            # exe + `_internal/`), not the staging root.
            UpdateChecker._update_path = new_exe.parent
            UpdateChecker._release_data = None
            return True, "Update downloaded"
        except Exception as exc:
            return False, str(exc)

    @staticmethod
    def restart_app():
        """Exit the current process and let a detached helper swap + relaunch.

        Onedir layout means the swap touches two things — the exe and the
        `_internal/` directory beside it. Both are locked while we're alive,
        so all moves run in the helper after our PID exits. Other files in the
        install dir (`config.yaml`, `state.json`, `app.ico`, `_focus.vbs`) are
        left untouched.
        """
        update_path = UpdateChecker._update_path
        staged = update_path is not None and Path(update_path).is_dir()

        if not staged:
            # No update to apply — fall back to a plain relaunch.
            if IS_WINDOWS:
                subprocess.Popen([sys.executable] + sys.argv[1:], close_fds=True)
            else:
                os.execv(sys.executable, [sys.executable] + sys.argv)
            os._exit(0)

        current_exe = Path(sys.executable)
        install_dir = current_exe.parent
        src_exe = update_path / current_exe.name
        src_internal = update_path / "_internal"
        dst_internal = install_dir / "_internal"
        old_exe = install_dir / (current_exe.name + ".old")
        old_internal = install_dir / "_internal.old"
        staging_root = update_path.parent  # `.am_update_staging`
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
                f'echo install_dir={install_dir} >> "%LOG%"\r\n'
                f'echo current_exe={current_exe} >> "%LOG%"\r\n'
                f'echo src_exe={src_exe} >> "%LOG%"\r\n'
                f'echo src_internal={src_internal} >> "%LOG%"\r\n'
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
                # Step 1: rename old _internal aside (atomic dir rename, same
                # volume). Retry briefly because Defender can hold a directory
                # lock for a beat after the process exits.
                "set /a tries=0\r\n"
                ":tryren_internal\r\n"
                f'move /y "{dst_internal}" "{old_internal}" >> "%LOG%" 2>&1\r\n'
                "if errorlevel 1 (\r\n"
                '  echo [rename _internal-^>_internal.old failed, try=%tries%] >> "%LOG%"\r\n'
                "  ping -n 3 127.0.0.1 >nul\r\n"
                "  set /a tries+=1\r\n"
                "  if %tries% LSS 30 goto tryren_internal\r\n"
                '  echo [FAILED: could not rename _internal after 30 tries] >> "%LOG%"\r\n'
                "  exit /b 1\r\n"
                ")\r\n"
                # Step 2: rename old exe aside.
                "set /a tries=0\r\n"
                ":tryren_exe\r\n"
                f'move /y "{current_exe}" "{old_exe}" >> "%LOG%" 2>&1\r\n'
                "if errorlevel 1 (\r\n"
                '  echo [rename exe-^>exe.old failed, try=%tries%] >> "%LOG%"\r\n'
                "  ping -n 3 127.0.0.1 >nul\r\n"
                "  set /a tries+=1\r\n"
                "  if %tries% LSS 30 goto tryren_exe\r\n"
                '  echo [FAILED: could not rename exe; restoring _internal] >> "%LOG%"\r\n'
                f'  move /y "{old_internal}" "{dst_internal}" >> "%LOG%" 2>&1\r\n'
                "  exit /b 1\r\n"
                ")\r\n"
                # Step 3: move new exe into place.
                f'move /y "{src_exe}" "{current_exe}" >> "%LOG%" 2>&1\r\n'
                "if errorlevel 1 (\r\n"
                '  echo [FAILED: move new exe; restoring backups] >> "%LOG%"\r\n'
                f'  move /y "{old_exe}" "{current_exe}" >> "%LOG%" 2>&1\r\n'
                f'  move /y "{old_internal}" "{dst_internal}" >> "%LOG%" 2>&1\r\n'
                "  exit /b 1\r\n"
                ")\r\n"
                # Step 4: move new _internal into place.
                f'move /y "{src_internal}" "{dst_internal}" >> "%LOG%" 2>&1\r\n'
                "if errorlevel 1 (\r\n"
                '  echo [FAILED: move new _internal; restoring backups] >> "%LOG%"\r\n'
                f'  move /y "{current_exe}" "{src_exe}" >> "%LOG%" 2>&1\r\n'
                f'  move /y "{old_exe}" "{current_exe}" >> "%LOG%" 2>&1\r\n'
                f'  move /y "{old_internal}" "{dst_internal}" >> "%LOG%" 2>&1\r\n'
                "  exit /b 1\r\n"
                ")\r\n"
                'echo [swap complete; cleaning up backups + staging] >> "%LOG%"\r\n'
                f'del /q "{old_exe}" >nul 2>&1\r\n'
                f'rmdir /s /q "{old_internal}" 2>nul\r\n'
                f'rmdir /s /q "{staging_root}" 2>nul\r\n'
                # Warmup read forces a synchronous AV scan of the freshly
                # swapped exe + _internal contents before launch. Without it
                # Defender can lock or quarantine `python312.dll` mid-load and
                # the relaunch dies with "Failed to load Python DLL".
                'echo [warming new exe + _internal for AV scan] >> "%LOG%"\r\n'
                f'type "{current_exe}" > nul 2>&1\r\n'
                f'for %%F in ("{dst_internal}\\*.dll" "{dst_internal}\\*.pyd") do (type "%%F" > nul 2>&1)\r\n'
                'ping -n 3 127.0.0.1 >nul\r\n'
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
                f'echo "install_dir={install_dir}"\n'
                f'echo "current_exe={current_exe}"\n'
                f'echo "src_exe={src_exe}"\n'
                f'echo "src_internal={src_internal}"\n'
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
                # Step 1: rename _internal aside.
                f'if ! mv -f "{dst_internal}" "{old_internal}"; then\n'
                "  echo '[FAILED: rename _internal->_internal.old]'\n"
                "  exit 1\n"
                "fi\n"
                # Step 2: rename exe aside.
                f'if ! mv -f "{current_exe}" "{old_exe}"; then\n'
                "  echo '[FAILED: rename exe; restoring _internal]'\n"
                f'  mv -f "{old_internal}" "{dst_internal}"\n'
                "  exit 1\n"
                "fi\n"
                # Step 3: move new exe in.
                f'if ! mv -f "{src_exe}" "{current_exe}"; then\n'
                "  echo '[FAILED: move new exe; restoring backups]'\n"
                f'  mv -f "{old_exe}" "{current_exe}"\n'
                f'  mv -f "{old_internal}" "{dst_internal}"\n'
                "  exit 1\n"
                "fi\n"
                # Step 4: move new _internal in.
                f'if ! mv -f "{src_internal}" "{dst_internal}"; then\n'
                "  echo '[FAILED: move new _internal; restoring backups]'\n"
                f'  mv -f "{current_exe}" "{src_exe}"\n'
                f'  mv -f "{old_exe}" "{current_exe}"\n'
                f'  mv -f "{old_internal}" "{dst_internal}"\n'
                "  exit 1\n"
                "fi\n"
                f'chmod +x "{current_exe}"\n'
                "echo '[swap complete; cleaning up backups + staging]'\n"
                f'rm -f "{old_exe}"\n'
                f'rm -rf "{old_internal}"\n'
                f'rm -rf "{staging_root}"\n'
                # Warmup read + brief settle — mirror of the Windows helper.
                # Most Linux AVs are passive but the read keeps inotify watchers
                # quiet and gives the FS a moment to flush after the rename.
                "echo '[warming new exe]'\n"
                f'cat "{current_exe}" > /dev/null 2>&1\n'
                "sleep 1\n"
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
        self.setWindowTitle(f"{APP_NAME} - Update Available")

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
        self._status_lbl.setStyleSheet(f"color: {_COLOR_SUCCESS}; font-size: 12px;")

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
            self._status_lbl.setText("Update complete - restarting...")
            self._status_lbl.setStyleSheet(f"color: {_COLOR_SUCCESS}; font-size: 12px;")
            QTimer.singleShot(500, UpdateChecker.restart_app)
        else:
            self._progress_bar.hide()
            self._status_lbl.setText(f"Update failed: {msg}")
            self._status_lbl.setStyleSheet(f"color: {_COLOR_FAILURE}; font-size: 12px;")
            self._skip_btn.setEnabled(True)
