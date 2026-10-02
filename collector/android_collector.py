"""
Android Screen Time Collector via Wireless ADB

Connects to an Android device over Wi-Fi, queries Android's built-in `usagestats` service,
reconstructs active foreground app sessions, and appends them to the daily raw activity log
under source="mobile". Zero apps are required on the phone.
"""

import sys
import os
import re
import json
import uuid
import shutil
import argparse
import subprocess
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional, Tuple

# Add parent directory to path so we can import collector modules
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from collector.config import get_config

# Common package to friendly app name mapping
APP_NAMES = {
    "com.whatsapp": "WhatsApp",
    "com.twitter.android": "Twitter / X",
    "com.reddit.frontpage": "Reddit",
    "com.openai.chatgpt": "ChatGPT",
    "com.google.android.gm": "Gmail",
    "com.google.android.youtube": "YouTube",
    "com.brave.browser": "Brave Browser",
    "com.android.chrome": "Google Chrome",
    "org.telegram.messenger": "Telegram",
    "com.instagram.android": "Instagram",
    "com.spotify.music": "Spotify",
    "com.discord": "Discord",
    "in.amazon.mShop.android.shopping": "Amazon",
    "com.phonepe.app": "PhonePe",
    "com.google.android.apps.nbu.paisa.user": "Google Pay",
    "com.truecaller": "Truecaller",
    "com.linkedin.android": "LinkedIn",
    "com.netflix.mediaclient": "Netflix",
    "com.microsoft.teams": "Microsoft Teams",
    "com.slack": "Slack",
    "com.google.android.apps.maps": "Google Maps",
    "com.google.android.googlequicksearchbox": "Google Search",
    "com.sec.android.gallery3d": "Samsung Gallery",
    "com.sec.android.mimage.photoretouching": "Photo Editor",
    "com.samsung.android.incallui": "Phone Call",
    "com.android.settings": "Settings",
    "com.android.settings.intelligence": "Settings Search",
    "com.github.android": "GitHub Mobile",
    "org.mozilla.firefox": "Firefox",
}

# System packages to ignore by default (e.g. launchers, wallpaper, system UI)
DEFAULT_IGNORED_PACKAGES = {
    "android",
    "com.sec.android.app.launcher",
    "com.android.systemui",
    "com.sec.android.app.clockpackage",
    "com.google.android.permissioncontroller",
}


def get_friendly_app_name(pkg: str) -> str:
    """Return friendly app name or format package name cleanly."""
    if pkg in APP_NAMES:
        return APP_NAMES[pkg]
    parts = pkg.split(".")
    # Use last segment capitalized
    last = parts[-1]
    if last.lower() in ("app", "android", "main", "ui") and len(parts) > 1:
        last = parts[-2]
    return last.replace("_", " ").replace("-", " ").title()


def find_adb_executable() -> Optional[str]:
    """Find adb executable across PATH and known installation locations."""
    # Check if adb is directly executable in PATH
    found = shutil.which("adb")
    if found:
        return found

    # Search in WinGet packages directory
    winget_dir = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
    if winget_dir.exists():
        for p in winget_dir.glob("*PlatformTools*/**/adb.exe"):
            if p.is_file():
                return str(p)

    # Search in Android SDK platform-tools
    sdk_adb = Path(os.environ.get("LOCALAPPDATA", "")) / "Android" / "Sdk" / "platform-tools" / "adb.exe"
    if sdk_adb.is_file():
        return str(sdk_adb)

    # Search common root paths
    for root_candidate in [r"C:\platform-tools\adb.exe", r"C:\Android\platform-tools\adb.exe"]:
        if Path(root_candidate).is_file():
            return root_candidate

    return None


def get_connected_devices(adb_path: str) -> List[str]:
    """Return list of connected device serials in 'device' state."""
    try:
        res = subprocess.run([adb_path, "devices"], capture_output=True, text=True, timeout=5)
        lines = res.stdout.strip().splitlines()
        devices = []
        for line in lines[1:]:
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "device":
                devices.append(parts[0])
        return devices
    except Exception:
        return []


def connect_device(adb_path: str, ip: str, port: int = 5555) -> bool:
    """Attempt wireless ADB connection to target IP and port."""
    target = f"{ip}:{port}"
    try:
        res = subprocess.run([adb_path, "connect", target], capture_output=True, text=True, timeout=8)
        output = res.stdout.strip().lower()
        if "connected" in output or "already connected" in output:
            return True
    except Exception:
        pass
    return False


def get_wifi_gateway_ip() -> Optional[str]:
    """Extract default gateway for the active Wi-Fi adapter via ipconfig."""
    try:
        out = subprocess.check_output("ipconfig", text=True, errors="replace")
        in_wifi = False
        for line in out.splitlines():
            line_lower = line.lower()
            if "wireless lan adapter wi-fi:" in line_lower or "adapter wi-fi:" in line_lower:
                in_wifi = True
                continue
            if in_wifi and line.strip() and not line.startswith(" "):
                break
            if in_wifi and "default gateway" in line_lower:
                parts = line.split(":")
                if len(parts) >= 2:
                    gw = parts[1].strip()
                    if gw and gw != "0.0.0.0":
                        return gw
    except Exception:
        pass
    return None


def get_target_device(adb_path: str, configured_ip: Optional[str] = None, port: int = 5555) -> Optional[str]:
    """Find or connect to the best available Android device."""
    devices = get_connected_devices(adb_path)
    
    # 1. Check if a wireless device is already connected
    for d in devices:
        if ":" in d:
            return d

    # 2. List candidate IPs to probe
    candidates = []
    if configured_ip:
        candidates.append(configured_ip)

    # Automatically probe Wi-Fi gateway (useful when laptop is on phone's hotspot)
    gw = get_wifi_gateway_ip()
    if gw and gw not in candidates:
        candidates.append(gw)

    # Standard Android hotspot fallback
    for fallback in ["192.168.43.1"]:
        if fallback not in candidates:
            candidates.append(fallback)

    # Try connecting to candidate IPs
    for ip in candidates:
        if connect_device(adb_path, ip, port):
            devices = get_connected_devices(adb_path)
            for d in devices:
                if ip in d:
                    return d

    # 3. If any USB device is connected, use it
    if devices:
        return devices[0]

    return None


def get_device_timezone(adb_path: str, serial: str) -> timezone:
    """Query device for current timezone offset."""
    try:
        res = subprocess.run(
            [adb_path, "-s", serial, "shell", "date +%z"],
            capture_output=True,
            text=True,
            timeout=5
        )
        tz_str = res.stdout.strip()
        if tz_str and len(tz_str) == 5 and (tz_str[0] in "+-"):
            sign = 1 if tz_str[0] == "+" else -1
            hrs = int(tz_str[1:3])
            mins = int(tz_str[3:5])
            return timezone(sign * timedelta(hours=hrs, minutes=mins))
    except Exception:
        pass
    # Default to local machine timezone
    return datetime.now().astimezone().tzinfo or timezone.utc


def fetch_usagestats(adb_path: str, serial: str) -> str:
    """Execute dumpsys usagestats on target device."""
    res = subprocess.run(
        [adb_path, "-s", serial, "shell", "dumpsys usagestats"],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=20
    )
    if res.returncode != 0:
        raise RuntimeError(f"dumpsys usagestats failed: {res.stderr}")
    return res.stdout


def parse_usagestats_events(
    dumpsys_text: str,
    device_tz: timezone,
    target_date: Optional[str] = None,
    min_duration_seconds: float = 2.0,
    ignored_packages: Optional[set] = None,
    now_dt: Optional[datetime] = None
) -> List[Dict[str, Any]]:
    """Parse discrete activity sessions from dumpsys usagestats event logs.
    
    Reconstructs sessions bounded by ACTIVITY_RESUMED and ACTIVITY_PAUSED/STOPPED,
    clamped by SCREEN_INTERACTIVE, SCREEN_NON_INTERACTIVE, and keyguard events.
    """
    if ignored_packages is None:
        ignored_packages = DEFAULT_IGNORED_PACKAGES

    if now_dt is None:
        now_dt = datetime.now(device_tz)
    elif now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=device_tz)

    event_re = re.compile(r'time="([^"]+)"\s+type=([A-Z_]+)(?:\s+package=([^\s]+))?')
    
    raw_parsed_events = []
    for line in dumpsys_text.splitlines():
        m = event_re.search(line)
        if not m:
            continue
        ts_str, evt_type, pkg = m.group(1), m.group(2), m.group(3)
        try:
            dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=device_tz)
            raw_parsed_events.append((dt, evt_type, pkg or ""))
        except Exception:
            continue

    # Chronological sort
    raw_parsed_events.sort(key=lambda x: x[0])

    screen_off_events = []
    screen_interactive = True
    keyguard_shown = False
    last_screen_off_dt = None

    for dt, evt_type, pkg in raw_parsed_events:
        if evt_type == "SCREEN_INTERACTIVE":
            screen_interactive = True
        elif evt_type == "SCREEN_NON_INTERACTIVE":
            screen_interactive = False
            screen_off_events.append(dt)
            last_screen_off_dt = dt
        elif evt_type == "KEYGUARD_SHOWN":
            keyguard_shown = True
            screen_off_events.append(dt)
            last_screen_off_dt = dt
        elif evt_type == "KEYGUARD_HIDDEN":
            keyguard_shown = False

    is_screen_currently_off = (not screen_interactive) or keyguard_shown

    def clamp_session(s_dt: datetime, e_dt: datetime) -> Optional[datetime]:
        if s_dt >= e_dt:
            return None
        # Clamp to earliest screen-off or keyguard event strictly after s_dt
        for off_dt in screen_off_events:
            if s_dt < off_dt < e_dt:
                e_dt = off_dt
                break
        return e_dt if e_dt > s_dt else None

    active_resumed = {}
    sessions = []

    for dt, evt_type, pkg in raw_parsed_events:
        if pkg in ignored_packages:
            continue

        if evt_type == "ACTIVITY_RESUMED":
            active_resumed[pkg] = dt
        elif evt_type in ("ACTIVITY_PAUSED", "ACTIVITY_STOPPED") and pkg in active_resumed:
            s_dt = active_resumed.pop(pkg)
            e_dt = dt

            clamped_end = clamp_session(s_dt, e_dt)
            if not clamped_end:
                continue

            dur = round((clamped_end - s_dt).total_seconds(), 1)
            event_date = s_dt.strftime("%Y-%m-%d")
            if target_date and event_date != target_date:
                continue

            if dur >= min_duration_seconds:
                s_iso = s_dt.isoformat()
                e_iso = clamped_end.isoformat()
                clean_id_ts = s_iso.replace(":", "-").replace("+", "_")
                app_name = get_friendly_app_name(pkg)

                sessions.append({
                    "id": f"mobile-{pkg}-{clean_id_ts}",
                    "start": s_iso,
                    "end": e_iso,
                    "duration_seconds": dur,
                    "source": "mobile",
                    "context": {
                        "app": app_name,
                        "package": pkg
                    }
                })

    # Currently active open sessions
    for pkg, s_dt in active_resumed.items():
        if pkg in ignored_packages:
            continue

        # An open session must never end at now if the screen is currently off
        if is_screen_currently_off:
            if last_screen_off_dt and last_screen_off_dt > s_dt:
                clamped_end = last_screen_off_dt
            else:
                continue
        else:
            clamped_end = clamp_session(s_dt, now_dt)

        if not clamped_end or clamped_end <= s_dt:
            continue

        dur = round((clamped_end - s_dt).total_seconds(), 1)
        event_date = s_dt.strftime("%Y-%m-%d")
        if target_date and event_date != target_date:
            continue

        if dur >= min_duration_seconds:
            s_iso = s_dt.isoformat()
            e_iso = clamped_end.isoformat()
            clean_id_ts = s_iso.replace(":", "-").replace("+", "_")
            app_name = get_friendly_app_name(pkg)

            sessions.append({
                "id": f"mobile-{pkg}-{clean_id_ts}",
                "start": s_iso,
                "end": e_iso,
                "duration_seconds": dur,
                "source": "mobile",
                "context": {
                    "app": app_name,
                    "package": pkg
                }
            })

    return sessions


def sync_mobile_activity(
    target_date: Optional[str] = None,
    adb_path: Optional[str] = None,
    device_ip: Optional[str] = None,
    port: int = 5555,
    min_duration_seconds: Optional[float] = None
) -> Dict[str, Any]:
    """Extract mobile activity and sync into raw daily JSONL storage."""
    cfg = get_config()

    if not adb_path:
        adb_path = find_adb_executable()
    if not adb_path:
        raise FileNotFoundError("ADB executable not found. Please install Android Platform-Tools or specify path.")

    # Check configuration for android settings
    android_cfg = cfg.get("android", {})
    if not device_ip:
        device_ip = android_cfg.get("device_ip") or android_cfg.get("phone_ip")
    if not device_ip:
        raise ValueError("Android phone IP is not configured. Please set 'android.device_ip' or 'android.phone_ip' in config.json or pass via --ip.")
    port = android_cfg.get("port", port)

    # Locate target device
    serial = get_target_device(adb_path, configured_ip=device_ip, port=port)
    if not serial:
        raise ConnectionError(
            f"No Android device found. Make sure your phone is connected wirelessly to {device_ip}:{port} "
            f"or connected via USB."
        )

    print(f"Connecting to Android device [{serial}]...")
    dev_tz = get_device_timezone(adb_path, serial)
    if not target_date:
        target_date = datetime.now(dev_tz).strftime("%Y-%m-%d")

    d = datetime.strptime(target_date, "%Y-%m-%d")
    year = str(d.year)
    month = d.strftime("%b").lower()
    raw_dir = Path(cfg["data_directory"]) / "raw" / year / month / "daily" / "mobile"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_file = raw_dir / f"{target_date}.jsonl"

    print(f"Querying usagestats on device for date {target_date}...")
    output = fetch_usagestats(adb_path, serial)

    # Ignored packages configuration
    ignored = set(android_cfg.get("ignore_packages", list(DEFAULT_IGNORED_PACKAGES)))
    effective_min_dur = min_duration_seconds if min_duration_seconds is not None else float(cfg.get("raw_min_duration_seconds", 2.0))
    sessions = parse_usagestats_events(output, dev_tz, target_date=target_date, min_duration_seconds=effective_min_dur, ignored_packages=ignored)

    if not sessions:
        print(f"No mobile app sessions recorded for {target_date}.")
        return {"synced_count": 0, "total_seconds": 0.0, "apps": {}}

    # Read existing events from raw file to support updating in-progress sessions
    existing_events = []
    existing_map = {}
    if raw_file.exists():
        with open(raw_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                    existing_events.append(ev)
                    if "id" in ev:
                        existing_map[ev["id"]] = len(existing_events) - 1
                except Exception:
                    pass

    # Merge / update sessions
    updated_count = 0
    new_count = 0
    for s in sessions:
        sid = s["id"]
        if sid in existing_map:
            idx = existing_map[sid]
            old_dur = float(existing_events[idx].get("duration_seconds", 0.0))
            new_dur = float(s["duration_seconds"])
            if new_dur > old_dur:
                existing_events[idx] = s
                updated_count += 1
        else:
            existing_events.append(s)
            existing_map[sid] = len(existing_events) - 1
            new_count += 1

    # Atomically rewrite raw file if any changes (write to temp, then rename)
    if updated_count > 0 or new_count > 0:
        tmp_file = str(raw_file) + ".tmp"
        with open(tmp_file, "w", encoding="utf-8") as f:
            for ev in existing_events:
                f.write(json.dumps(ev) + "\n")
        os.replace(tmp_file, raw_file)

    # Aggregate summary of synced data for output display
    app_totals = {}
    total_secs = 0.0
    for s in sessions:
        dur = s["duration_seconds"]
        app = s["context"]["app"]
        app_totals[app] = app_totals.get(app, 0.0) + dur
        total_secs += dur

    sorted_apps = sorted(app_totals.items(), key=lambda x: x[1], reverse=True)

    print("\n========================================================")
    print(f" Mobile Screen Time Sync Complete for {target_date}")
    print("========================================================")
    print(f" Total Active Screen Time : {int(total_secs // 3600)}h {int((total_secs % 3600) // 60)}m {int(total_secs % 60)}s")
    print(f" Total Sessions Found     : {len(sessions)} (New: {new_count}, Live Updated: {updated_count})")
    print(f" Target File              : {raw_file}")
    print("--------------------------------------------------------")
    print(f" {'App':<25} | {'Duration':<12} | {'Percentage':<8}")
    print("--------------------------------------------------------")
    for app, dur in sorted_apps[:15]:
        pct = (dur / total_secs * 100) if total_secs > 0 else 0
        m = int(dur // 60)
        s = int(dur % 60)
        dur_str = f"{m}m {s}s"
        print(f" {app:<25} | {dur_str:<12} | {pct:5.1f}%")
    print("========================================================\n")

    return {
        "new_count": new_count,
        "updated_count": updated_count,
        "total_sessions": len(sessions),
        "total_seconds": round(total_secs, 1),
        "apps": {app: round(dur, 1) for app, dur in sorted_apps},
        "target_file": str(raw_file)
    }


def main():
    parser = argparse.ArgumentParser(description="Sync Android screen time via Wireless ADB")
    parser.add_argument("--date", help="Target date YYYY-MM-DD (defaults to today)")
    parser.add_argument("--ip", help="Phone IP address override")
    parser.add_argument("--port", type=int, default=5555, help="Wireless ADB port (default 5555)")
    parser.add_argument("--min-duration", type=float, default=None, help="Minimum session duration in seconds (default 40.0)")
    args = parser.parse_args()

    try:
        sync_mobile_activity(target_date=args.date, device_ip=args.ip, port=args.port, min_duration_seconds=args.min_duration)
    except Exception as e:
        print(f"Error during mobile sync: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
