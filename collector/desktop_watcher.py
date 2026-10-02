"""
Windows Desktop Activity Watcher

Monitors the active foreground window on Windows using native Win32 APIs (via ctypes).
Ignores browsers (Chrome, Brave) and VS Code (which have dedicated rich extensions).
Tracks all other desktop applications (Antigravity IDE, VLC, Codex, Discord, Obsidian, Terminal, etc.)
with global idle detection (GetLastInputInfo).
"""

import sys
import os
import time
import json
import uuid
import ctypes
import threading
import urllib.request
from ctypes import wintypes
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, Tuple

# Add parent directory to path so we can import collector modules
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from collector.config import get_config

# Win32 API functions
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# Structures
class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


# Friendly app name mapping (lowercase process name -> display name)
KNOWN_APPS = {
    "chrome.exe": "Google Chrome",
    "brave.exe": "Brave Browser",
    "msedge.exe": "Microsoft Edge",
    "code.exe": "Code",
    "antigravity.exe": "Antigravity",
    "vlc.exe": "VLC Media Player",
    "mpv.exe": "MPV",
    "wmplayer.exe": "Windows Media Player",
    "potplayer.exe": "PotPlayer",
    "potplayermini64.exe": "PotPlayer",
    "windowsterminal.exe": "Windows Terminal",
    "powershell.exe": "PowerShell",
    "cmd.exe": "Command Prompt",
    "discord.exe": "Discord",
    "slack.exe": "Slack",
    "obsidian.exe": "Obsidian",
    "notion.exe": "Notion",
    "notepad.exe": "Notepad",
    "notepad++.exe": "Notepad++",
    "spotify.exe": "Spotify",
    "telegram.exe": "Telegram",
    "acrord32.exe": "Adobe Acrobat",
    "acrobat.exe": "Adobe Acrobat",
    "codex.exe": "Codex",
    "postman.exe": "Postman",
    "dbeaver.exe": "DBeaver",
    "steam.exe": "Steam",
    "figma.exe": "Figma",
}

# Processes to ignore (OS background chrome)
IGNORED_PROCESSES = {
    "lockapp.exe",
    "searchhost.exe",
    "shellexperiencehost.exe",
    "startmenuexperiencehost.exe",
    "taskmgr.exe",
}

MEDIA_PLAYERS = {
    "vlc.exe",
    "mpv.exe",
    "wmplayer.exe",
    "potplayer.exe",
    "potplayermini64.exe",
}


def attach_to_desktop():
    """Ensure current thread is attached to the interactive desktop (WinSta0\\Default)."""
    try:
        hwinsta = user32.OpenWindowStationW("WinSta0", False, 0x037F)
        if hwinsta:
            user32.SetProcessWindowStation(hwinsta)
            hdesk = user32.OpenDesktopW("Default", 0, False, 0x01FF)
            if hdesk:
                user32.SetThreadDesktop(hdesk)
    except Exception:
        pass


def get_foreground_window_info() -> Tuple[Optional[str], Optional[str], Optional[str], bool]:
    """Retrieve active window process name, friendly app name, window title, and fullscreen status.
    
    Returns:
        (process_name, app_name, window_title, is_fullscreen)
    """
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        attach_to_desktop()
        hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None, None, None, False

    # Get window title
    length = user32.GetWindowTextLengthW(hwnd)
    title = ""
    if length > 0:
        buff = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buff, length + 1)
        title = buff.value.strip()

    # Get process ID and executable name
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value:
        return None, None, None, False

    h_proc = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    proc_name = ""
    if h_proc:
        exe_buff = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(1024)
        if kernel32.QueryFullProcessImageNameW(h_proc, 0, exe_buff, ctypes.byref(size)):
            proc_name = Path(exe_buff.value).name.lower()
        kernel32.CloseHandle(h_proc)

    if not proc_name:
        return None, None, None, False

    # Check fullscreen status
    rect = wintypes.RECT()
    is_fullscreen = False
    if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        screen_w = user32.GetSystemMetrics(0)  # SM_CXSCREEN
        screen_h = user32.GetSystemMetrics(1)  # SM_CYSCREEN
        is_fullscreen = (rect.left <= 0 and rect.top <= 0 and rect.right >= screen_w and rect.bottom >= screen_h)

    # Determine friendly app name
    if proc_name in KNOWN_APPS:
        app_name = KNOWN_APPS[proc_name]
    else:
        # Fallback: strip .exe and format nicely
        base = proc_name.replace(".exe", "")
        app_name = base.replace("_", " ").replace("-", " ").title()

    return proc_name, app_name, title, is_fullscreen


def get_idle_seconds() -> float:
    """Return number of seconds since last user keyboard or mouse input across the entire system."""
    lii = LASTINPUTINFO()
    lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
    if user32.GetLastInputInfo(ctypes.byref(lii)):
        tick = kernel32.GetTickCount64()
        return max(0.0, (tick - lii.dwTime) / 1000.0)
    return 0.0


def emit_desktop_event(event: Dict[str, Any], collector_url: str, data_directory: str):
    """Deliver desktop event to collector HTTP endpoint, or append to raw daily file if offline."""
    raw_min = getattr(get_config(), "raw_min_duration_seconds", 2.0)
    if float(event.get("duration_seconds", 0.0)) < raw_min:
        return

    # Attempt HTTP delivery first (thread-safe centralized queue)
    delivered = False
    try:
        headers = {"Content-Type": "application/json"}
        token = getattr(get_config(), "auth_token", None)
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(
            f"{collector_url}/event",
            data=json.dumps(event).encode("utf-8"),
            headers=headers
        )
        with urllib.request.urlopen(req, timeout=1.0) as resp:
            if resp.status == 200:
                delivered = True
    except Exception:
        delivered = False

    # If collector is offline or not running, write to structured raw daily file
    if not delivered:
        try:
            start_dt = datetime.fromisoformat(event["start"].replace('Z', '+00:00'))
            date_str = start_dt.strftime("%Y-%m-%d")
            year = str(start_dt.year)
            month = start_dt.strftime("%b").lower()
            out_dir = Path(data_directory) / "raw" / year / month / "daily"
            out_dir.mkdir(parents=True, exist_ok=True)
            out_file = out_dir / f"{date_str}.jsonl"
            with open(out_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(event) + "\n")
        except Exception as e:
            print(f"[DesktopWatcher] Error writing offline event: {e}", file=sys.stderr)


class DesktopWatcher:
    """Monitors Windows active application in the background."""

    def __init__(
        self,
        collector_url: str = "http://127.0.0.1:8765",
        data_directory: str = "S:\\project\\AW\\Record",
        idle_threshold_seconds: float = 300.0,  # 5 minutes
        poll_interval: float = 1.0,
        min_session_duration: float = 2.0
    ):
        self.collector_url = collector_url
        self.data_directory = data_directory
        self.idle_threshold_seconds = idle_threshold_seconds
        self.poll_interval = poll_interval
        self.min_session_duration = min_session_duration

        self.running = False
        self.current_session = None  # {id, app, title, proc_name, start_dt, key, title_durations, last_title, last_title_time, last_checkpoint_mono}
        self.is_idle = False
        self.idle_start_dt = None
        self.is_locked = False
        self.lock_start_dt = None
        self._last_tick_mono = None

        # Untracked foreground interval tracking
        self.untracked_start_dt = None
        self.untracked_id = None
        self.untracked_last_checkpoint_mono = None

    def start(self):
        """Start the desktop watching loop."""
        self.running = True
        attach_to_desktop()
        print(f"[DesktopWatcher] Started Windows active window monitor (Idle cutoff: {int(self.idle_threshold_seconds)}s)")

        while self.running:
            try:
                self._tick()
            except Exception as e:
                # Catch-all to keep watcher alive
                pass
            time.sleep(self.poll_interval)

    def stop(self):
        """Stop watching and flush current session."""
        self.running = False
        self._end_current_session()
        self._end_untracked_session()

    def _checkpoint_current_session(self):
        """Emit periodic checkpoint for ongoing session with deterministic ID."""
        if not self.current_session:
            return

        now_dt = datetime.now().astimezone()
        now_mono = time.monotonic()
        start_dt = self.current_session["start_dt"]
        duration = (now_dt - start_dt).total_seconds()

        if duration >= self.min_session_duration:
            if "last_title" in self.current_session and "last_title_time" in self.current_session:
                dt = max(0.0, now_mono - self.current_session["last_title_time"])
                self.current_session["title_durations"][self.current_session["last_title"]] = (
                    self.current_session["title_durations"].get(self.current_session["last_title"], 0.0) + dt
                )
                self.current_session["last_title_time"] = now_mono

            best_title = self.current_session.get("title", "")
            if self.current_session.get("title_durations"):
                best_title = max(self.current_session["title_durations"].items(), key=lambda x: x[1])[0]

            event = {
                "id": self.current_session["id"],
                "start": start_dt.isoformat(),
                "end": now_dt.isoformat(),
                "duration_seconds": round(duration, 1),
                "source": "desktop",
                "context": {
                    "app": self.current_session["app"],
                    "title": best_title,
                    "proc_name": self.current_session.get("proc_name", "")
                }
            }
            emit_desktop_event(event, self.collector_url, self.data_directory)
            self.current_session["last_checkpoint_mono"] = now_mono

    def _end_current_session(self, explicit_end_time: Optional[datetime] = None):
        """End the current active session and emit final event."""
        if not self.current_session:
            return

        now_dt = explicit_end_time or datetime.now().astimezone()
        start_dt = self.current_session["start_dt"]
        duration = (now_dt - start_dt).total_seconds()

        # Finalize title durations
        now_mono = time.monotonic()
        if "last_title" in self.current_session and "last_title_time" in self.current_session:
            dt = max(0.0, now_mono - self.current_session["last_title_time"])
            self.current_session["title_durations"][self.current_session["last_title"]] = (
                self.current_session["title_durations"].get(self.current_session["last_title"], 0.0) + dt
            )

        best_title = self.current_session.get("title", "")
        if self.current_session.get("title_durations"):
            best_title = max(self.current_session["title_durations"].items(), key=lambda x: x[1])[0]

        if duration >= self.min_session_duration:
            start_iso = start_dt.isoformat()
            end_iso = now_dt.isoformat()

            event = {
                "id": self.current_session["id"],
                "start": start_iso,
                "end": end_iso,
                "duration_seconds": round(duration, 1),
                "source": "desktop",
                "context": {
                    "app": self.current_session["app"],
                    "title": best_title,
                    "proc_name": self.current_session.get("proc_name", "")
                }
            }
            emit_desktop_event(event, self.collector_url, self.data_directory)

        self.current_session = None

    def _end_untracked_session(self, now_dt: Optional[datetime] = None):
        """End current untracked foreground session and emit explicit event."""
        if not self.untracked_start_dt:
            return
        now_dt = now_dt or datetime.now().astimezone()
        dur = (now_dt - self.untracked_start_dt).total_seconds()
        if dur >= self.min_session_duration:
            event = {
                "id": self.untracked_id,
                "start": self.untracked_start_dt.isoformat(),
                "end": now_dt.isoformat(),
                "duration_seconds": round(dur, 1),
                "source": "desktop",
                "context": {
                    "status": "no_tracked_foreground",
                    "app": "No Tracked Foreground"
                }
            }
            emit_desktop_event(event, self.collector_url, self.data_directory)
        self.untracked_start_dt = None
        self.untracked_id = None
        self.untracked_last_checkpoint_mono = None

    def _tick(self):
        now_dt = datetime.now().astimezone()
        now_mono = time.monotonic()

        # OS Suspend / Sleep detection:
        if self._last_tick_mono is not None and (now_mono - self._last_tick_mono) > 10.0:
            sleep_gap = now_mono - self._last_tick_mono
            sleep_start = now_dt - timedelta(seconds=sleep_gap)
            if self.current_session:
                self._end_current_session(explicit_end_time=sleep_start)
            # Emit explicit non-foreground sleep event
            s_iso = sleep_start.isoformat()
            e_iso = now_dt.isoformat()
            clean_ts = s_iso.replace(":", "-").replace("+", "_")
            sleep_event = {
                "id": f"desktop-sleep-{clean_ts}",
                "start": s_iso,
                "end": e_iso,
                "duration_seconds": round(sleep_gap, 1),
                "source": "desktop",
                "context": {
                    "status": "sleep",
                    "app": "Sleep"
                }
            }
            emit_desktop_event(sleep_event, self.collector_url, self.data_directory)
        self._last_tick_mono = now_mono

        idle_secs = get_idle_seconds()
        proc_name, app_name, title, is_fullscreen = get_foreground_window_info()

        # Handle explorer background / taskbar with empty title
        if proc_name == "explorer.exe" and (not title or title in ("Program Manager", "Task Switching")):
            proc_name = None

        # Lock screen detection
        if proc_name == "lockapp.exe":
            if self.current_session:
                self._end_current_session()
            if not self.is_locked:
                self.is_locked = True
                self.lock_start_dt = now_dt
            return
        elif self.is_locked:
            self.is_locked = False
            lock_end_dt = now_dt
            lock_dur = (lock_end_dt - self.lock_start_dt).total_seconds()
            if lock_dur >= self.min_session_duration:
                s_iso = self.lock_start_dt.isoformat()
                e_iso = lock_end_dt.isoformat()
                clean_ts = s_iso.replace(":", "-").replace("+", "_")
                lock_event = {
                    "id": f"desktop-locked-{clean_ts}",
                    "start": s_iso,
                    "end": e_iso,
                    "duration_seconds": round(lock_dur, 1),
                    "source": "desktop",
                    "context": {
                        "status": "locked",
                        "app": "Locked"
                    }
                }
                emit_desktop_event(lock_event, self.collector_url, self.data_directory)

        # Check if current app is an ignored OS chrome app
        is_ignored_app = bool(proc_name and proc_name in IGNORED_PROCESSES)

        # Media player hands-free watching exemption
        is_media_active = bool(
            proc_name in MEDIA_PLAYERS and (is_fullscreen or idle_secs < 1800.0)  # up to 30m hands-off
        )

        # Check idle state
        if idle_secs >= self.idle_threshold_seconds and not is_media_active:
            if not self.is_idle:
                self.is_idle = True
                self.idle_start_dt = now_dt - timedelta(seconds=idle_secs)
                self._end_current_session(explicit_end_time=self.idle_start_dt)
            return

        # User resumed from idle -> emit non-foreground idle event
        if self.is_idle:
            self.is_idle = False
            if self.idle_start_dt:
                idle_end_dt = now_dt
                idle_dur = (idle_end_dt - self.idle_start_dt).total_seconds()
                if idle_dur >= self.min_session_duration:
                    s_iso = self.idle_start_dt.isoformat()
                    e_iso = idle_end_dt.isoformat()
                    clean_ts = s_iso.replace(":", "-").replace("+", "_")
                    idle_event = {
                        "id": f"desktop-idle-{clean_ts}",
                        "start": s_iso,
                        "end": e_iso,
                        "duration_seconds": round(idle_dur, 1),
                        "source": "desktop",
                        "context": {
                            "status": "idle",
                            "app": "Idle"
                        }
                    }
                    emit_desktop_event(idle_event, self.collector_url, self.data_directory)
                self.idle_start_dt = None

        if is_ignored_app or not proc_name:
            if self.current_session:
                self._end_current_session()
            if not self.untracked_start_dt:
                self.untracked_start_dt = now_dt
                self.untracked_last_checkpoint_mono = now_mono
                clean_ts = now_dt.isoformat().replace(":", "-").replace("+", "_")
                self.untracked_id = f"desktop-untracked-{clean_ts}"
            elif (now_mono - self.untracked_last_checkpoint_mono) >= 60.0:
                dur = (now_dt - self.untracked_start_dt).total_seconds()
                if dur >= self.min_session_duration:
                    event = {
                        "id": self.untracked_id,
                        "start": self.untracked_start_dt.isoformat(),
                        "end": now_dt.isoformat(),
                        "duration_seconds": round(dur, 1),
                        "source": "desktop",
                        "context": {
                            "status": "no_tracked_foreground",
                            "app": "No Tracked Foreground"
                        }
                    }
                    emit_desktop_event(event, self.collector_url, self.data_directory)
                self.untracked_last_checkpoint_mono = now_mono
            return

        # Tracked app active: end untracked session if running
        if self.untracked_start_dt:
            self._end_untracked_session(now_dt)

        # Desktop sessions key on app name only, not app plus title.
        context_key = app_name

        if not self.current_session:
            title_durations = {title: 0.0}
            clean_ts = now_dt.isoformat().replace(":", "-").replace("+", "_")
            clean_app = app_name.replace(" ", "_").lower()
            self.current_session = {
                "id": f"desktop-{clean_app}-{clean_ts}",
                "app": app_name,
                "title": title,
                "proc_name": proc_name,
                "start_dt": now_dt,
                "key": context_key,
                "title_durations": title_durations,
                "last_title": title,
                "last_title_time": now_mono,
                "last_checkpoint_mono": now_mono
            }
        elif self.current_session["key"] != context_key:
            # Switched to different app
            self._end_current_session()
            title_durations = {title: 0.0}
            clean_ts = now_dt.isoformat().replace(":", "-").replace("+", "_")
            clean_app = app_name.replace(" ", "_").lower()
            self.current_session = {
                "id": f"desktop-{clean_app}-{clean_ts}",
                "app": app_name,
                "title": title,
                "proc_name": proc_name,
                "start_dt": now_dt,
                "key": context_key,
                "title_durations": title_durations,
                "last_title": title,
                "last_title_time": now_mono,
                "last_checkpoint_mono": now_mono
            }
        else:
            # Same app: update title duration tracking if title changed
            if title != self.current_session["last_title"]:
                dt = max(0.0, now_mono - self.current_session["last_title_time"])
                self.current_session["title_durations"][self.current_session["last_title"]] = (
                    self.current_session["title_durations"].get(self.current_session["last_title"], 0.0) + dt
                )
                self.current_session["last_title"] = title
                self.current_session["last_title_time"] = now_mono
                self.current_session["title"] = title

            # Checkpoint session every ~60s
            if (now_mono - self.current_session.get("last_checkpoint_mono", now_mono)) >= 60.0:
                self._checkpoint_current_session()


def run_standalone():
    cfg = get_config()
    collector_url = f"http://{cfg.collector_host}:{cfg.collector_port}"
    data_dir = cfg.data_directory
    min_dur = getattr(cfg, "raw_min_duration_seconds", 2.0)
    watcher = DesktopWatcher(collector_url=collector_url, data_directory=data_dir, min_session_duration=min_dur)
    try:
        watcher.start()
    except KeyboardInterrupt:
        watcher.stop()
        print("\n[DesktopWatcher] Stopped.")


if __name__ == "__main__":
    run_standalone()
