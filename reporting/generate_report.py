"""
Activity Tracker Report Generator

Reads raw JSONL activity data and produces compact, agent-friendly JSON reports.

Key Concepts:
--------------
1. Raw Event:
   A single immutable event recorded by a client (Chromium extension or VS Code
   extension) and stored in `raw/YYYY-MM-DD.jsonl`. Raw events are the source of
   truth and are never rewritten, merged, or deleted on disk.

2. Logical Session:
   A continuous block of activity within the same application context.
   Consecutive raw events with identical context are merged into a single logical
   session if the gap between them is <= SESSION_MERGE_GAP_SECONDS.

3. SESSION_MERGE_GAP_SECONDS:
   Configurable threshold (default 30 seconds). Consecutive raw events of the same
   context separated by an inactive pause below this threshold merge into one logical
   session. Inactive gap time is NEVER added to active duration.

4. Context Equality:
   - For VS Code: workspace, file, and language must all match.
   - For Browser: browser, domain, title, and url must all match.
   If any context attribute changes, a new logical session is started immediately.

5. Context Switches:
   Count of transitions where the logical context changes to a different context
   (e.g., ChatGPT -> YouTube, Browser -> VS Code, or fileA -> fileB). Pauses within
   the same context do not count as context switches.

6. total_active_seconds vs observed_span_seconds:
   - total_active_seconds: Sum of actual activity durations across all logical sessions.
     Does not include inactivity gaps.
   - observed_span_seconds: Wall-clock duration spanning from the start of the first
     activity to the end of the last activity (last_activity_end - first_activity_start).
     Includes inactivity gaps.
"""

import argparse
import json
import sys
import os
import re
from datetime import datetime, date, time, timedelta, timezone
from pathlib import Path
from collections import defaultdict
from typing import List, Dict, Any, Tuple, Optional

# Add parent directory to path so we can import collector modules
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from collector.config import get_config, ALLOWED_LABELS

DEFAULT_SESSION_MERGE_GAP_SECONDS = 30.0


def read_events(filepath: str) -> List[Dict[str, Any]]:
    """Read raw activity events from a daily JSONL file.
    
    The raw file is treated as immutable and read-only.
    Malformed lines are safely skipped without failing.
    """
    events = []
    malformed_count = 0

    path = Path(filepath)
    if not path.exists():
        return events

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
                required = ["id", "start", "end", "duration_seconds", "source"]
                if all(r in event for r in required):
                    events.append(event)
                else:
                    malformed_count += 1
            except json.JSONDecodeError:
                malformed_count += 1

    if malformed_count > 0:
        print(f"  Warning: skipped {malformed_count} malformed line(s) in {filepath}")

    return events


def deduplicate_events(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Remove duplicate raw events by ID, preserving the latest / highest-duration occurrence."""
    by_id = {}
    ordered_ids = []
    for event in events:
        eid = event.get("id")
        if not eid:
            ordered_ids.append(event)
            continue
        if eid not in by_id:
            ordered_ids.append(eid)
            by_id[eid] = event
        else:
            prev = by_id[eid]
            if float(event.get("duration_seconds", 0.0)) >= float(prev.get("duration_seconds", 0.0)):
                by_id[eid] = event

    result = []
    for item in ordered_ids:
        if isinstance(item, dict):
            result.append(item)
        else:
            result.append(by_id[item])
    return result


def parse_to_utc(ts: str) -> datetime:
    """Parse an ISO-8601 timestamp string into a timezone-aware UTC datetime.
    
    Handles 'Z' suffixes and numeric timezone offsets (+HH:MM, -HH:MM).
    """
    ts_clean = ts.replace("Z", "+00:00")
    dt = datetime.fromisoformat(ts_clean)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# Alias for backward compatibility with existing tests and scripts
parse_timestamp = parse_to_utc


def get_report_timezone(events: List[Dict[str, Any]]) -> timezone:
    """Determine the consistent timezone to use for report output.
    
    Prefers the local non-UTC offset found in the raw events (e.g. +05:30),
    falling back to the local system timezone.
    """
    for e in events:
        ts_str = e.get("start", "")
        if ts_str and not ts_str.endswith("Z"):
            try:
                dt = datetime.fromisoformat(ts_str)
                if dt.tzinfo is not None and dt.utcoffset() != timedelta(0):
                    return dt.tzinfo
            except Exception:
                pass
    return datetime.now().astimezone().tzinfo


def get_context_key(event: Dict[str, Any]) -> Tuple:
    """Generate a deterministic, hashable key representing the activity context.
    
    Context equality rules:
    - For VS Code: (source, workspace, file, language)
    - For Browser: (source, browser, domain, title, url)
    - For other sources: (source, sorted key-value pairs of context)
    """
    source = event.get("source", "")
    ctx = event.get("context", {})
    if source == "vscode":
        return (
            "vscode",
            ctx.get("workspace"),
        )
    elif source == "browser":
        return (
            "browser",
            ctx.get("browser"),
            ctx.get("domain"),
            ctx.get("title"),
            ctx.get("url"),
        )
    elif source == "mobile":
        return (
            "mobile",
            ctx.get("app"),
            ctx.get("package"),
        )
    elif source == "desktop":
        return (
            "desktop",
            ctx.get("app"),
        )
    elif source == "manual":
        return (
            "manual",
            ctx.get("activity") or ctx.get("title"),
            ctx.get("category"),
        )
    return (source, tuple(sorted((k, str(v)) for k, v in ctx.items())))


def sessionize_events(
    raw_events: List[Dict[str, Any]],
    merge_gap_seconds: float = DEFAULT_SESSION_MERGE_GAP_SECONDS,
) -> List[Dict[str, Any]]:
    """Group consecutive raw events into logical sessions.
    
    Merge Invariants:
    1. Source and activity context must match identically.
    2. Gap between previous event's end and next event's start must be <= merge_gap_seconds.
    3. Inactivity gap duration is NEVER added to active duration.
    4. Overlapping intervals are merged without double-counting active time.
    5. Each source is sessionized independently to prevent cross-device events
       from fragmenting continuous sessions (e.g., a mobile notification check
       should not split a VS Code coding session into two separate sessions).
    """
    if not raw_events:
        return []

    # Parse and normalize timestamps to UTC
    parsed = []
    for e in raw_events:
        try:
            s_dt = parse_to_utc(e["start"])
            e_dt = parse_to_utc(e["end"])
            dur = float(e.get("duration_seconds", (e_dt - s_dt).total_seconds()))
            parsed.append({
                **e,
                "_start_dt": s_dt,
                "_end_dt": e_dt,
                "_duration_seconds": max(0.0, dur),
                "_ctx_key": get_context_key(e),
            })
        except Exception:
            continue

    # Partition events by source for independent sessionization
    by_source = defaultdict(list)
    for event in parsed:
        by_source[event["source"]].append(event)

    all_sessions = []
    for source, source_events in by_source.items():
        # Sort chronologically within this source
        source_events.sort(key=lambda x: (x["_start_dt"], x["_end_dt"]))

        sessions = []
        for event in source_events:
            if not sessions:
                sessions.append({
                    "source": event["source"],
                    "context": dict(event.get("context", {})),
                    "context_key": event["_ctx_key"],
                    "start_dt": event["_start_dt"],
                    "end_dt": event["_end_dt"],
                    "duration_seconds": event["_duration_seconds"],
                    "raw_event_count": 1,
                    "raw_events": [event],
                })
                continue

            prev = sessions[-1]
            gap = (event["_start_dt"] - prev["end_dt"]).total_seconds()

            # Check merge condition
            if prev["context_key"] == event["_ctx_key"] and gap <= merge_gap_seconds:
                # Overlap handling: only add non-overlapping active extension
                if gap >= 0:
                    prev["duration_seconds"] += event["_duration_seconds"]
                else:
                    additional = max(0.0, (event["_end_dt"] - max(prev["end_dt"], event["_start_dt"])).total_seconds())
                    prev["duration_seconds"] += additional

                prev["end_dt"] = max(prev["end_dt"], event["_end_dt"])
                prev["raw_event_count"] += 1
                prev["raw_events"].append(event)

                # Keep longest-held title for desktop sessions
                if event["source"] == "desktop":
                    if "_title_durations" not in prev:
                        prev["_title_durations"] = defaultdict(float)
                        first_title = prev["raw_events"][0].get("context", {}).get("title", "")
                        prev["_title_durations"][first_title] = prev["raw_events"][0].get("_duration_seconds", 0.0)
                    evt_title = event.get("context", {}).get("title", "")
                    prev["_title_durations"][evt_title] += event.get("_duration_seconds", 0.0)
                    best_title = max(prev["_title_durations"].items(), key=lambda x: x[1])[0]
                    prev["context"]["title"] = best_title
            else:
                sessions.append({
                    "source": event["source"],
                    "context": dict(event.get("context", {})),
                    "context_key": event["_ctx_key"],
                    "start_dt": event["_start_dt"],
                    "end_dt": event["_end_dt"],
                    "duration_seconds": event["_duration_seconds"],
                    "raw_event_count": 1,
                    "raw_events": [event],
                })

        all_sessions.extend(sessions)

    # Merge all sessions into a unified chronological timeline
    all_sessions.sort(key=lambda x: (x["start_dt"], x["end_dt"]))
    return all_sessions


def clean_context_for_report(source: str, ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Strip irrelevant/high-entropy fields (url, tab_id, window_id) from context in reports.
    
    Keeps only the human-relevant identifiers: title, domain, file, workspace, language.
    """
    if source == "browser":
        clean = {}
        if "title" in ctx:
            clean["title"] = ctx["title"]
        if "domain" in ctx:
            clean["domain"] = ctx["domain"]
        return clean
    elif source == "vscode":
        clean = {}
        if "workspace" in ctx:
            clean["workspace"] = ctx["workspace"]
        return clean
    elif source == "mobile":
        clean = {}
        if "app" in ctx:
            clean["app"] = ctx["app"]
        if "package" in ctx:
            clean["package"] = ctx["package"]
        return clean
    elif source == "desktop":
        clean = {}
        if "app" in ctx:
            clean["app"] = ctx["app"]
        if "title" in ctx:
            clean["title"] = ctx["title"]
        return clean
    elif source == "manual":
        clean = {}
        if "activity" in ctx:
            clean["activity"] = ctx["activity"]
        elif "title" in ctx:
            clean["activity"] = ctx["title"]
        if "category" in ctx:
            clean["category"] = ctx["category"]
        if "notes" in ctx and ctx["notes"]:
            clean["notes"] = ctx["notes"]
        return clean
    return {k: v for k, v in ctx.items() if k not in ("url", "tab_id", "window_id")}


def split_duration_by_hour(start_dt: datetime, end_dt: datetime) -> Dict[int, float]:
    """Split a continuous time span into per-hour buckets.
    
    Returns a dict mapping hour (0-23) -> seconds spent in that hour.
    """
    buckets = defaultdict(float)
    current = start_dt
    while current < end_dt:
        next_hour = current.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        segment_end = min(next_hour, end_dt)
        seconds = (segment_end - current).total_seconds()
        buckets[current.hour] += seconds
        current = segment_end
    return dict(buckets)


def split_interval_by_hour(start_dt: datetime, end_dt: datetime) -> List[Tuple[int, datetime, datetime]]:
    """Split an interval into per-hour segments.
    
    Returns a list of (hour, segment_start, segment_end).
    """
    segments = []
    current = start_dt
    while current < end_dt:
        next_hour = current.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        segment_end = min(next_hour, end_dt)
        segments.append((current.hour, current, segment_end))
        current = segment_end
    return segments

def compute_union_seconds(intervals: List[Tuple[datetime, datetime]]) -> float:
    """Compute total wall-clock seconds covered by a set of potentially overlapping intervals.
    
    Uses the sweep-line / interval union algorithm:
    1. Sort intervals by start time.
    2. Merge overlapping/adjacent intervals.
    3. Sum the merged interval durations.
    
    This guarantees total_active_seconds <= observed_span_seconds, even when
    PC and mobile sessions overlap (e.g., phone use while PC session is open).
    """
    if not intervals:
        return 0.0
    
    sorted_intervals = sorted(intervals, key=lambda x: x[0])
    merged = [sorted_intervals[0]]
    
    for start, end in sorted_intervals[1:]:
        prev_start, prev_end = merged[-1]
        if start <= prev_end:
            # Overlapping or adjacent — extend
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))
    
    return sum((end - start).total_seconds() for start, end in merged)


def classify_desktop_app(app: str, proc: str = "") -> str:
    """Classify a desktop application as chrome, brave, edge, vscode, or generic desktop."""
    app_lower = (app or "").lower()
    proc_lower = (proc or "").lower()
    if "brave" in app_lower or "brave" in proc_lower:
        return "brave"
    if "chrome" in app_lower or "chrome" in proc_lower:
        return "chrome"
    if "msedge" in proc_lower or app_lower in ("microsoft edge", "edge"):
        return "edge"
    if proc_lower in ("code.exe", "code") or app_lower in ("code", "visual studio code", "vs code"):
        return "vscode"
    return "desktop"


def subtract_intervals(
    base_intervals: List[Tuple[datetime, datetime]],
    blacklist: List[Tuple[datetime, datetime]]
) -> List[Tuple[datetime, datetime]]:
    """Subtract blacklist intervals from base intervals.
    Returns a sorted list of non-overlapping sub-intervals."""
    if not base_intervals:
        return []
    if not blacklist:
        return sorted(base_intervals, key=lambda x: x[0])

    bl_sorted = sorted(blacklist, key=lambda x: x[0])
    bl_merged = [bl_sorted[0]]
    for s, e in bl_sorted[1:]:
        if s <= bl_merged[-1][1]:
            bl_merged[-1] = (bl_merged[-1][0], max(bl_merged[-1][1], e))
        else:
            bl_merged.append((s, e))

    result = []
    for b_start, b_end in base_intervals:
        curr = b_start
        for bl_s, bl_e in bl_merged:
            if bl_e <= curr:
                continue
            if bl_s >= b_end:
                break
            if bl_s > curr:
                result.append((curr, min(bl_s, b_end)))
            curr = max(curr, bl_e)
            if curr >= b_end:
                break
        if curr < b_end:
            result.append((curr, b_end))

    return [r for r in result if (r[1] - r[0]).total_seconds() > 0.001]


def find_recent_vscode_workspace(
    s: datetime,
    all_vscode_events: List[Dict[str, Any]],
    max_gap_seconds: float = 1800.0,
) -> Optional[str]:
    """Find the most recent workspace name from VS Code events within max_gap_seconds before s."""
    candidates = []
    for ev in all_vscode_events:
        ws = ev.get("context", {}).get("workspace")
        if not ws or ws == "VS Code (no workspace)":
            continue
        ev_s = ev.get("_start_dt")
        ev_e = ev.get("_end_dt")
        if not ev_s or not ev_e:
            continue
        if ev_s <= s <= ev_e:
            candidates.append((0.0, ev_e, ws))
        elif ev_e <= s:
            gap = (s - ev_e).total_seconds()
            if gap <= max_gap_seconds:
                candidates.append((gap, ev_e, ws))
    if candidates:
        candidates.sort(key=lambda x: (x[0], -x[1].timestamp()))
        return candidates[0][2]
    return None


def carve_window_with_extension_events(
    win_start: datetime,
    win_end: datetime,
    ext_events: List[Dict[str, Any]],
    fg_type: str,
    app_name: str,
) -> List[Dict[str, Any]]:
    """Carve a desktop foreground window [win_start, win_end] with matching extension events.
    Resolves overlaps between events (e.g. multiple profiles) chronologically by giving precedence
    to the most recently started event. Leftover time becomes unknown page / inherits workspace."""
    dur = (win_end - win_start).total_seconds()
    if dur <= 0.001:
        return []

    clipped = []
    for ev in ext_events:
        s = max(win_start, ev["_start_dt"])
        e = min(win_end, ev["_end_dt"])
        if (e - s).total_seconds() > 0.001:
            clipped.append((s, e, ev))

    disp_name = (
        "Chrome" if "chrome" in fg_type.lower()
        else ("Brave" if "brave" in fg_type.lower()
        else ("Edge" if "edge" in fg_type.lower()
        else app_name))
    )

    def make_leftover(s: datetime, e: datetime) -> Dict[str, Any]:
        d = (e - s).total_seconds()
        s_iso = s.isoformat()
        e_iso = e.isoformat()
        if fg_type == "vscode":
            inherited_ws = find_recent_vscode_workspace(s, ext_events)
            ws_name = inherited_ws if inherited_ws else "VS Code (no workspace)"
            return {
                "id": f"vscode-{s.strftime('%H%M%S%f')}",
                "source": "vscode",
                "start": s_iso,
                "end": e_iso,
                "duration_seconds": round(d, 1),
                "_start_dt": s,
                "_end_dt": e,
                "_duration_seconds": d,
                "context": {
                    "workspace": ws_name
                }
            }
        else:
            return {
                "id": f"browser-unknown-{s.strftime('%H%M%S%f')}",
                "source": "browser",
                "start": s_iso,
                "end": e_iso,
                "duration_seconds": round(d, 1),
                "_start_dt": s,
                "_end_dt": e,
                "_duration_seconds": d,
                "context": {
                    "browser": fg_type,
                    "domain": "unknown",
                    "title": f"{disp_name} (unknown page)",
                    "url": ""
                }
            }

    if not clipped:
        return [make_leftover(win_start, win_end)]

    points = {win_start, win_end}
    for s, e, _ in clipped:
        points.add(s)
        points.add(e)
    sorted_points = sorted(list(points))

    raw_segments = []
    for p_curr, p_next in zip(sorted_points[:-1], sorted_points[1:]):
        seg_dur = (p_next - p_curr).total_seconds()
        if seg_dur <= 0.001:
            continue
        covering = [ev for s, e, ev in clipped if s <= p_curr and e >= p_next]
        if not covering:
            raw_segments.append((p_curr, p_next, None))
        elif len(covering) == 1:
            raw_segments.append((p_curr, p_next, covering[0]))
        else:
            # Overlap between profiles/tabs: most recently started event wins
            winner = max(covering, key=lambda ev: (ev["_start_dt"], ev["_end_dt"]))
            raw_segments.append((p_curr, p_next, winner))

    merged = []
    for s, e, owner in raw_segments:
        if merged and merged[-1][2] is owner:
            merged[-1] = (merged[-1][0], e, owner)
        else:
            merged.append((s, e, owner))

    results = []
    for s, e, owner in merged:
        d = (e - s).total_seconds()
        if d <= 0.001:
            continue
        if owner is None:
            results.append(make_leftover(s, e))
        else:
            evt = dict(owner)
            s_iso = s.isoformat()
            e_iso = e.isoformat()
            evt["id"] = f"{owner.get('id', 'ext')}-clip-{s.strftime('%H%M%S%f')}"
            evt["start"] = s_iso
            evt["end"] = e_iso
            evt["duration_seconds"] = round(d, 1)
            evt["_start_dt"] = s
            evt["_end_dt"] = e
            evt["_duration_seconds"] = d
            results.append(evt)

    return results


def build_pc_timeline(
    events: List[Dict[str, Any]],
    merge_gap_seconds: float = DEFAULT_SESSION_MERGE_GAP_SECONDS,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Construct a unified, non-overlapping PC timeline anchored by desktop watcher events.
    
    Returns:
        (pc_timeline_events, fallback_events, watcher_offline_ranges, fallback_ranges)
    """
    parsed = []
    for e in events:
        try:
            s_dt = parse_to_utc(e["start"])
            e_dt = parse_to_utc(e["end"])
            dur = float(e.get("duration_seconds", (e_dt - s_dt).total_seconds()))
            if e_dt > s_dt:
                parsed.append({
                    **e,
                    "_start_dt": s_dt,
                    "_end_dt": e_dt,
                    "_duration_seconds": max(0.0, dur),
                })
        except Exception:
            continue

    desktop_events = [e for e in parsed if e.get("source") == "desktop"]
    browser_events = [e for e in parsed if e.get("source") == "browser"]
    vscode_events = [e for e in parsed if e.get("source") == "vscode"]

    # If NO desktop events exist at all (watcher offline whole day / uninstrumented environment):
    if not desktop_events:
        fallback_ranges = []
        ext_events = browser_events + vscode_events
        if ext_events:
            min_s = min(e["_start_dt"] for e in ext_events)
            max_e = max(e["_end_dt"] for e in ext_events)
            fallback_ranges.append({
                "start": min_s.isoformat(),
                "end": max_e.isoformat(),
                "duration_seconds": round((max_e - min_s).total_seconds(), 1),
            })
        return [], ext_events, fallback_ranges, fallback_ranges

    # Desktop watcher events present.
    # 1. Separate non-foreground (idle, locked, sleep, no_tracked_foreground) and foreground desktop events
    non_fg_events = []
    fg_events = []
    for e in desktop_events:
        ctx = e.get("context", {})
        status = (ctx.get("status") or "").lower()
        app = (ctx.get("app") or "").lower()
        if status in ("idle", "locked", "sleep", "no_tracked_foreground") or app in ("idle", "locked", "sleep", "no tracked foreground"):
            non_fg_events.append(e)
        else:
            fg_events.append(e)

    hard_clip_intervals = []  # locked and sleep ALWAYS clip
    idle_intervals = []       # idle clips unless audible media exemption applies
    for e in non_fg_events:
        ctx = e.get("context", {})
        st = (ctx.get("status") or "").lower()
        ap = (ctx.get("app") or "").lower()
        if st in ("locked", "sleep") or ap in ("locked", "sleep"):
            hard_clip_intervals.append((e["_start_dt"], e["_end_dt"]))
        elif st == "idle" or ap == "idle":
            idle_intervals.append((e["_start_dt"], e["_end_dt"]))

    # Compute watcher online spans (union of all desktop intervals merged with gap <= 30.0s)
    all_watcher_intervals = sorted([(e["_start_dt"], e["_end_dt"]) for e in desktop_events], key=lambda x: x[0])
    watcher_online_spans = []
    if all_watcher_intervals:
        curr_s, curr_e = all_watcher_intervals[0]
        for s, e in all_watcher_intervals[1:]:
            if (s - curr_e).total_seconds() <= 30.0:
                curr_e = max(curr_e, e)
            else:
                watcher_online_spans.append((curr_s, curr_e))
                curr_s, curr_e = s, e
        watcher_online_spans.append((curr_s, curr_e))

    # Identify watcher offline ranges
    watcher_offline_ranges = []
    fallback_ranges = []
    for i in range(len(watcher_online_spans) - 1):
        gap_s = watcher_online_spans[i][1]
        gap_e = watcher_online_spans[i + 1][0]
        gap_dur = (gap_e - gap_s).total_seconds()
        if gap_dur > 30.0:
            watcher_offline_ranges.append({
                "start": gap_s.isoformat(),
                "end": gap_e.isoformat(),
                "duration_seconds": round(gap_dur, 1),
            })

    # Fallback for extension events falling outside watcher online spans
    fallback_events = []
    for ext_e in browser_events + vscode_events:
        e_s, e_e = ext_e["_start_dt"], ext_e["_end_dt"]
        outside_pieces = subtract_intervals([(e_s, e_e)], watcher_online_spans)
        for out_s, out_e in outside_pieces:
            out_dur = (out_e - out_s).total_seconds()
            if out_dur > 0.001:
                fb_evt = dict(ext_e)
                fb_evt["id"] = f"{ext_e.get('id', 'ext')}-fb-{out_s.strftime('%H%M%S%f')}"
                fb_evt["start"] = out_s.isoformat()
                fb_evt["end"] = out_e.isoformat()
                fb_evt["duration_seconds"] = round(out_dur, 1)
                fb_evt["_start_dt"] = out_s
                fb_evt["_end_dt"] = out_e
                fb_evt["_duration_seconds"] = out_dur
                fallback_events.append(fb_evt)
                fallback_ranges.append({
                    "start": out_s.isoformat(),
                    "end": out_e.isoformat(),
                    "duration_seconds": round(out_dur, 1),
                })

    # Now carve foreground intervals
    pc_timeline_events = []
    MEDIA_IDLE_OVERRIDE_CAP_SECONDS = 7200.0  # Cap on how long audible media can override idle
    KNOWN_MEDIA_DOMAINS = {"youtube.com", "netflix.com", "twitch.tv", "vimeo.com", "bilibili.com", "primevideo.com", "disneyplus.com", "hulu.com", "spotify.com"}

    for fg_e in fg_events:
        ctx = fg_e.get("context", {})
        app = ctx.get("app", "")
        proc = ctx.get("proc_name", "")
        title = ctx.get("title", "")
        app_type = classify_desktop_app(app, proc)

        # Locked and sleep ALWAYS clip foreground intervals unconditionally
        base_pieces = subtract_intervals([(fg_e["_start_dt"], fg_e["_end_dt"])], hard_clip_intervals)

        for p_start, p_end in base_pieces:
            p_dur = (p_end - p_start).total_seconds()
            if p_dur <= 0.001:
                continue

            if app_type == "desktop":
                # Regular non-browser, non-VS-Code desktop app: subtract idle intervals
                active_pieces = subtract_intervals([(p_start, p_end)], idle_intervals)
                for s_act, e_act in active_pieces:
                    dur_act = (e_act - s_act).total_seconds()
                    if dur_act <= 0.001:
                        continue
                    evt = dict(fg_e)
                    evt["id"] = f"desktop-{app.replace(' ', '_').lower()}-{s_act.strftime('%H%M%S%f')}"
                    evt["start"] = s_act.isoformat()
                    evt["end"] = e_act.isoformat()
                    evt["duration_seconds"] = round(dur_act, 1)
                    evt["_start_dt"] = s_act
                    evt["_end_dt"] = e_act
                    evt["_duration_seconds"] = dur_act
                    evt["context"] = {"app": app, "title": title}
                    pc_timeline_events.append(evt)

            elif app_type in ("chrome", "brave", "edge"):
                # Requirement 5: Any browser extension event fills any browser foreground window
                matching = browser_events

                # Requirement 2: Browser media hands-off audible video overrides idle up to cap
                is_media_window = False
                for be in browser_events:
                    b_s = max(p_start, be["_start_dt"])
                    b_e = min(p_end, be["_end_dt"])
                    if (b_e - b_s).total_seconds() > 0.001:
                        b_ctx = be.get("context", {})
                        if b_ctx.get("audible") is True or any(d in (b_ctx.get("domain") or "").lower() for d in KNOWN_MEDIA_DOMAINS):
                            is_media_window = True
                            break

                if is_media_window:
                    # Idle is overridden up to MEDIA_IDLE_OVERRIDE_CAP_SECONDS
                    effective_idle_clips = []
                    for id_s, id_e in idle_intervals:
                        int_s = max(p_start, id_s)
                        int_e = min(p_end, id_e)
                        id_dur = (int_e - int_s).total_seconds()
                        if id_dur > MEDIA_IDLE_OVERRIDE_CAP_SECONDS:
                            clip_start = int_s + timedelta(seconds=MEDIA_IDLE_OVERRIDE_CAP_SECONDS)
                            effective_idle_clips.append((clip_start, int_e))
                    active_pieces = subtract_intervals([(p_start, p_end)], effective_idle_clips)
                else:
                    active_pieces = subtract_intervals([(p_start, p_end)], idle_intervals)

                for s_act, e_act in active_pieces:
                    carved = carve_window_with_extension_events(s_act, e_act, matching, app_type, app)
                    pc_timeline_events.extend(carved)

            elif app_type == "vscode":
                active_pieces = subtract_intervals([(p_start, p_end)], idle_intervals)
                for s_act, e_act in active_pieces:
                    carved = carve_window_with_extension_events(s_act, e_act, vscode_events, "vscode", app)
                    pc_timeline_events.extend(carved)

    pc_timeline_events.sort(key=lambda x: (x["_start_dt"], x["_end_dt"]))
    return pc_timeline_events, fallback_events, watcher_offline_ranges, fallback_ranges


def get_pc_focus_context(event: Dict[str, Any]) -> Tuple[str, str]:
    """Extract (type, name) focus context from a PC timeline event.
    
    Types: 'workspace', 'domain', 'app'.
    """
    source = event.get("source", "")
    ctx = event.get("context", {})
    if source == "vscode":
        ws = ctx.get("workspace")
        if ws and ws != "No Workspace":
            return ("workspace", ws)
        return ("app", "VS Code")
    elif source == "browser":
        dom = ctx.get("domain") or "browser"
        return ("domain", dom)
    elif source == "desktop":
        app = ctx.get("app") or "desktop"
        return ("app", app)
    return ("app", ctx.get("app") or source or "desktop")


def compute_focus_blocks(
    pc_events: List[Dict[str, Any]],
    report_tz: timezone,
    gap_threshold: float = 60.0,
) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    """Compute consecutive PC time on the same app, workspace or domain,
    tolerating interruptions up to gap_threshold (default 60s).
    
    Returns (longest_focus_block, top_3_focus_blocks).
    """
    if not pc_events:
        return None, []

    sorted_evts = sorted(pc_events, key=lambda x: (x["_start_dt"], x["_end_dt"]))

    by_context = defaultdict(list)
    for evt in sorted_evts:
        dur = float(evt.get("_duration_seconds", evt.get("duration_seconds", 0.0)))
        if dur <= 0.001:
            continue
        key = get_pc_focus_context(evt)
        by_context[key].append((evt["_start_dt"], evt["_end_dt"], dur))

    all_blocks = []
    for (ctx_type, ctx_name), intervals in by_context.items():
        if not intervals:
            continue
        intervals.sort(key=lambda x: x[0])
        curr_s, curr_e, curr_dur = intervals[0]
        for s, e, d in intervals[1:]:
            gap = (s - curr_e).total_seconds()
            if gap <= gap_threshold:
                curr_e = max(curr_e, e)
                curr_dur += d
            else:
                all_blocks.append({
                    "start": curr_s.astimezone(report_tz).isoformat(),
                    "end": curr_e.astimezone(report_tz).isoformat(),
                    "duration_seconds": round(curr_dur, 1),
                    "duration": round(curr_dur, 1),
                    "type": ctx_type,
                    "name": ctx_name,
                })
                curr_s, curr_e, curr_dur = s, e, d
        all_blocks.append({
            "start": curr_s.astimezone(report_tz).isoformat(),
            "end": curr_e.astimezone(report_tz).isoformat(),
            "duration_seconds": round(curr_dur, 1),
            "duration": round(curr_dur, 1),
            "type": ctx_type,
            "name": ctx_name,
        })

    if not all_blocks:
        return None, []

    all_blocks.sort(key=lambda x: x["duration_seconds"], reverse=True)
    top_3 = all_blocks[:3]
    longest = top_3[0] if top_3 else None
    return longest, top_3


def compute_late_night_seconds(
    screen_intervals: List[Tuple[datetime, datetime]],
    report_tz: timezone,
    date_str: str,
) -> float:
    """Compute screen union seconds between 00:00 and 05:00 local time for date_str."""
    if not screen_intervals or not date_str:
        return 0.0

    try:
        d = date.fromisoformat(date_str)
        w_start = datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=report_tz)
        w_end = datetime(d.year, d.month, d.day, 5, 0, 0, tzinfo=report_tz)
    except Exception:
        return 0.0

    clipped = []
    for s_dt, e_dt in screen_intervals:
        s_loc = s_dt.astimezone(report_tz)
        e_loc = e_dt.astimezone(report_tz)
        if e_loc <= w_start or s_loc >= w_end:
            continue
        c_s = max(s_loc, w_start)
        c_e = min(e_loc, w_end)
        if c_e > c_s:
            clipped.append((c_s, c_e))

    return round(compute_union_seconds(clipped), 1)


def compute_sleep_metrics(
    date_str: str,
    report_tz: timezone,
    data_directory: Optional[str] = None,
    events: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Compute sleep metrics for the night ending on date_str morning.
    
    Night window: [(D-1) 20:00, D 12:00) local time.
    1. A manual 'Sleep' event wins.
    2. Otherwise infer as the longest stretch with no PC and no phone activity
       overlapping the night window (minimum 3 hours).
    3. If data is insufficient, say so explicitly instead of guessing.
    """
    insufficient = {
        "status": "insufficient_data",
        "reason": "Insufficient activity data to determine sleep boundaries",
        "bedtime": None,
        "wake_time": None,
        "duration_seconds": None,
        "duration": None,
        "source": None,
        "last_phone_use_before_bedtime": None,
        "first_phone_use_after_waking": None,
    }

    if not date_str:
        insufficient["reason"] = "No date provided"
        return insufficient

    try:
        d = date.fromisoformat(date_str)
    except Exception:
        insufficient["reason"] = f"Invalid date: {date_str}"
        return insufficient

    prev_d = d - timedelta(days=1)
    prev_date_str = prev_d.isoformat()

    w_start = datetime(prev_d.year, prev_d.month, prev_d.day, 20, 0, 0, tzinfo=report_tz)
    w_end = datetime(d.year, d.month, d.day, 12, 0, 0, tzinfo=report_tz)

    all_evts = []
    if data_directory:
        all_evts.extend(_read_raw_files_for_date(data_directory, prev_date_str))
        all_evts.extend(_read_raw_files_for_date(data_directory, date_str))
    if events:
        all_evts.extend(events)

    all_evts = deduplicate_events(all_evts)

    # 1. Check for manual sleep
    manual_sleep_candidates = []
    for e in all_evts:
        if e.get("source") != "manual":
            continue
        ctx = e.get("context", {})
        cat = (ctx.get("category") or "").lower()
        act = (ctx.get("activity") or ctx.get("title") or "").lower()
        if "sleep" in cat or "sleep" in act or (cat == "rest" and "sleep" in act):
            try:
                s_dt = parse_to_utc(e["start"]).astimezone(report_tz)
                e_dt = parse_to_utc(e["end"]).astimezone(report_tz)
                if e_dt > w_start and s_dt < w_end:
                    dur = float(e.get("duration_seconds", (e_dt - s_dt).total_seconds()))
                    manual_sleep_candidates.append((s_dt, e_dt, dur))
            except Exception:
                pass

    mobile_events = []
    for e in all_evts:
        if e.get("source") == "mobile":
            try:
                s_dt = parse_to_utc(e["start"]).astimezone(report_tz)
                e_dt = parse_to_utc(e["end"]).astimezone(report_tz)
                mobile_events.append((s_dt, e_dt))
            except Exception:
                pass

    def get_phone_boundaries(bed_dt: datetime, wake_dt: datetime) -> Tuple[Optional[str], Optional[str]]:
        last_before = None
        for s_m, e_m in mobile_events:
            if e_m <= bed_dt and (bed_dt - e_m).total_seconds() <= 14400.0:
                if last_before is None or e_m > last_before:
                    last_before = e_m
        first_after = None
        for s_m, e_m in mobile_events:
            if s_m >= wake_dt and (s_m - wake_dt).total_seconds() <= 14400.0:
                if first_after is None or s_m < first_after:
                    first_after = s_m
        return (
            last_before.isoformat() if last_before else None,
            first_after.isoformat() if first_after else None,
        )

    if manual_sleep_candidates:
        manual_sleep_candidates.sort(key=lambda x: x[2], reverse=True)
        m_s, m_e, m_dur = manual_sleep_candidates[0]
        phone_before, phone_after = get_phone_boundaries(m_s, m_e)
        return {
            "status": "ok",
            "bedtime": m_s.isoformat(),
            "wake_time": m_e.isoformat(),
            "duration_seconds": round(m_dur, 1),
            "duration": round(m_dur, 1),
            "source": "manual",
            "last_phone_use_before_bedtime": phone_before,
            "first_phone_use_after_waking": phone_after,
        }

    # 2. Inferred sleep
    screen_pieces = []
    has_prev_evening_activity = False
    has_morning_activity = False
    midnight = datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=report_tz)

    for e in all_evts:
        src = e.get("source")
        if src not in ("browser", "vscode", "desktop", "mobile"):
            continue
        if src == "desktop":
            ctx = e.get("context", {})
            st = (ctx.get("status") or "").lower()
            ap = (ctx.get("app") or "").lower()
            if st in ("idle", "locked", "sleep", "no_tracked_foreground") or ap in ("idle", "locked", "sleep", "no tracked foreground"):
                continue
        try:
            s_dt = parse_to_utc(e["start"]).astimezone(report_tz)
            e_dt = parse_to_utc(e["end"]).astimezone(report_tz)
            if e_dt <= w_start or s_dt >= w_end:
                continue

            if s_dt < midnight:
                has_prev_evening_activity = True
            if e_dt >= midnight:
                has_morning_activity = True

            c_s = max(s_dt, w_start)
            c_e = min(e_dt, w_end)
            if c_e > c_s:
                screen_pieces.append((c_s, c_e))
        except Exception:
            pass

    if not has_prev_evening_activity or not has_morning_activity or not screen_pieces:
        insufficient["reason"] = "Missing evening activity before midnight or morning activity after midnight to bound sleep"
        return insufficient

    screen_pieces.sort(key=lambda x: x[0])
    merged_screen = [screen_pieces[0]]
    for s_int, e_int in screen_pieces[1:]:
        if s_int <= merged_screen[-1][1]:
            merged_screen[-1] = (merged_screen[-1][0], max(merged_screen[-1][1], e_int))
        else:
            merged_screen.append((s_int, e_int))

    gaps = []
    for i in range(len(merged_screen) - 1):
        g_s = merged_screen[i][1]
        g_e = merged_screen[i + 1][0]
        dur = (g_e - g_s).total_seconds()
        if dur >= 10800.0:  # Minimum 3 hours
            gaps.append((g_s, g_e, dur))

    if not gaps:
        insufficient["reason"] = "No inactive gap >= 3 hours found across the night window"
        return insufficient

    gaps.sort(key=lambda x: x[2], reverse=True)
    best_s, best_e, best_dur = gaps[0]
    phone_before, phone_after = get_phone_boundaries(best_s, best_e)

    return {
        "status": "ok",
        "bedtime": best_s.isoformat(),
        "wake_time": best_e.isoformat(),
        "duration_seconds": round(best_dur, 1),
        "duration": round(best_dur, 1),
        "source": "inferred",
        "last_phone_use_before_bedtime": phone_before,
        "first_phone_use_after_waking": phone_after,
    }


def strip_labels_block(md_text: str) -> str:
    """Strip the hidden <!-- labels ... --> comment block from markdown before rendering."""
    if not md_text:
        return ""
    return re.sub(r'<!--\s*labels\b.*?-->', '', md_text, flags=re.DOTALL | re.IGNORECASE).strip()


def parse_labels_from_markdown(
    md_text: Optional[str],
    date_str: str,
    report_tz: timezone,
    allowed_labels: Optional[List[str]] = None,
) -> Tuple[Optional[int], List[Dict[str, Any]], List[str]]:
    """Parse <!-- labels ... --> JSON block from analysis markdown.
    
    Returns (energy, label_intervals, warnings).
    Does NOT crash on malformed data; produces warnings instead.
    """
    if not md_text:
        return None, [], []

    match = re.search(r'<!--\s*labels\s*(\{.*?\})\s*-->', md_text, flags=re.DOTALL | re.IGNORECASE)
    if not match:
        return None, [], []

    json_str = match.group(1)
    warnings = []
    try:
        data = json.loads(json_str)
    except Exception as e:
        warnings.append(f"Malformed JSON in labels block: {e}")
        return None, [], warnings

    energy = data.get("energy")
    if energy is not None:
        try:
            energy = int(energy)
            if energy < 1 or energy > 5:
                warnings.append(f"Energy value {energy} out of range [1, 5]")
                energy = max(1, min(5, energy))
        except Exception:
            warnings.append(f"Invalid energy value: {data.get('energy')}")
            energy = None

    raw_labels = data.get("labels", [])
    if not isinstance(raw_labels, list):
        warnings.append("'labels' field in labels block must be a list")
        return energy, [], warnings

    try:
        d = date.fromisoformat(date_str)
    except Exception as e:
        warnings.append(f"Invalid date_str for labels parsing: {date_str}")
        return energy, [], warnings

    parsed_intervals = []
    for idx, item in enumerate(raw_labels):
        if not isinstance(item, dict):
            warnings.append(f"Label item #{idx} is not an object")
            continue

        lbl = str(item.get("label", "")).strip().lower()
        if not lbl:
            warnings.append(f"Label item #{idx} missing 'label' name")
            continue

        start_str = str(item.get("start", "")).strip()
        end_str = str(item.get("end", "")).strip()
        if not start_str or not end_str:
            warnings.append(f"Label item #{idx} missing 'start' or 'end'")
            continue

        try:
            s_parts = [int(p) for p in start_str.split(":")]
            e_parts = [int(p) for p in end_str.split(":")]
            s_time = time(s_parts[0], s_parts[1], s_parts[2] if len(s_parts) > 2 else 0)
            e_time = time(e_parts[0], e_parts[1], e_parts[2] if len(e_parts) > 2 else 0)

            dt_s = datetime.combine(d, s_time).replace(tzinfo=report_tz)
            dt_e = datetime.combine(d, e_time).replace(tzinfo=report_tz)
            if dt_e <= dt_s:
                dt_e += timedelta(days=1)

            parsed_intervals.append({
                "label": lbl,
                "start_dt": dt_s,
                "end_dt": dt_e,
                "planned": bool(item.get("planned", False)),
                "note": str(item.get("note", "")),
                "_order": idx,
            })
        except Exception as e:
            warnings.append(f"Label item #{idx} invalid time format ({start_str} - {end_str}): {e}")

    return energy, parsed_intervals, warnings


def resolve_label_intervals(
    label_intervals: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Resolve overlapping label ranges using 'later entry wins' rule.
    
    Returns a sorted list of non-overlapping time intervals.
    """
    if not label_intervals:
        return []

    ordered = sorted(label_intervals, key=lambda x: x.get("_order", 0))

    resolved: List[Dict[str, Any]] = []
    for item in ordered:
        new_s = item["start_dt"]
        new_e = item["end_dt"]
        if new_e <= new_s:
            continue

        updated = []
        for prev in resolved:
            p_s = prev["start_dt"]
            p_e = prev["end_dt"]

            # No overlap
            if p_e <= new_s or p_s >= new_e:
                updated.append(prev)
                continue

            # Full coverage: prev completely covered by new item
            if new_s <= p_s and new_e >= p_e:
                continue

            # Trim right
            if p_s < new_s and p_e <= new_e:
                trimmed = dict(prev)
                trimmed["end_dt"] = new_s
                updated.append(trimmed)
            # Trim left
            elif p_s >= new_s and p_e > new_e:
                trimmed = dict(prev)
                trimmed["start_dt"] = new_e
                updated.append(trimmed)
            # Split in two
            elif p_s < new_s and p_e > new_e:
                p1 = dict(prev)
                p1["end_dt"] = new_s
                p2 = dict(prev)
                p2["start_dt"] = new_e
                updated.append(p1)
                updated.append(p2)

        updated.append(item)
        resolved = updated

    resolved.sort(key=lambda x: x["start_dt"])
    return resolved


def overlay_labels_on_screen_time(
    screen_intervals: List[Tuple[datetime, datetime]],
    resolved_labels: List[Dict[str, Any]],
    allowed_labels: Optional[List[str]] = None,
) -> Tuple[Dict[str, Dict[str, float]], float, float, float, List[str]]:
    """Overlay resolved label intervals on screen intervals.
    
    Returns:
        (label_totals, labeled_seconds, unlabeled_seconds, label_coverage_pct, warnings)
    """
    if allowed_labels is None:
        allowed_labels = list(ALLOWED_LABELS)
    allowed_set = set(allowed_labels)

    label_totals = {
        lbl: {"duration_seconds": 0.0, "planned_seconds": 0.0}
        for lbl in allowed_labels
    }
    warnings = []

    total_screen_seconds = compute_union_seconds(screen_intervals) if screen_intervals else 0.0
    if not screen_intervals or not resolved_labels:
        return label_totals, 0.0, total_screen_seconds, 0.0, warnings

    labeled_intervals = []

    for lbl_item in resolved_labels:
        lbl_name = lbl_item["label"]
        l_s = lbl_item["start_dt"]
        l_e = lbl_item["end_dt"]
        is_planned = lbl_item.get("planned", False)

        overlapping_pieces = []
        for s_s, s_e in screen_intervals:
            int_s = max(s_s, l_s)
            int_e = min(s_e, l_e)
            if int_e > int_s:
                overlapping_pieces.append((int_s, int_e))
                labeled_intervals.append((int_s, int_e))

        dur = compute_union_seconds(overlapping_pieces)
        if dur > 0.001:
            target_key = lbl_name
            if target_key not in allowed_set:
                target_key = "other"
                warn_msg = f"Unknown label '{lbl_name}' treated as 'other'"
                if warn_msg not in warnings:
                    warnings.append(warn_msg)

            label_totals[target_key]["duration_seconds"] += dur
            if is_planned:
                label_totals[target_key]["planned_seconds"] += dur

    for lbl in label_totals:
        label_totals[lbl]["duration_seconds"] = round(label_totals[lbl]["duration_seconds"], 1)
        label_totals[lbl]["planned_seconds"] = round(label_totals[lbl]["planned_seconds"], 1)

    labeled_seconds = round(compute_union_seconds(labeled_intervals), 1)
    unlabeled_seconds = max(0.0, round(total_screen_seconds - labeled_seconds, 1))
    label_coverage_pct = round(labeled_seconds / total_screen_seconds * 100, 1) if total_screen_seconds > 0 else 0.0

    return label_totals, labeled_seconds, unlabeled_seconds, label_coverage_pct, warnings


def read_analysis_for_date(data_directory: Optional[str], date_str: str) -> Optional[str]:
    """Find and read the analysis markdown file for date_str."""
    if not date_str:
        return None
    try:
        d = date.fromisoformat(date_str)
        year = str(d.year)
        month = d.strftime("%b").lower()
    except Exception:
        return None

    candidate_paths = []
    if data_directory:
        dd = Path(data_directory)
        candidate_paths.extend([
            dd / "analysis" / year / month / "daily" / f"{date_str}.md",
            dd / "analysis" / f"{date_str}.md",
        ])

    base_dirs = [
        Path.cwd() / "Record",
        Path(__file__).resolve().parent.parent.parent / "Record",
    ]
    for b in base_dirs:
        candidate_paths.extend([
            b / "analysis" / year / month / "daily" / f"{date_str}.md",
            b / "analysis" / f"{date_str}.md",
        ])

    for cp in candidate_paths:
        if cp.exists():
            try:
                with open(cp, "r", encoding="utf-8") as f:
                    return f.read()
            except Exception:
                pass
    return None


def aggregate_events(
    events: List[Dict[str, Any]],
    merge_gap_seconds: float = DEFAULT_SESSION_MERGE_GAP_SECONDS,
    min_session_duration: float = 0.0,
    data_directory: Optional[str] = None,
    date_str: Optional[str] = None,
    analysis_text: Optional[str] = None,
) -> Dict[str, Any]:
    """Aggregate raw activity events into a structured, compact report.
    
    All aggregations (total duration, domain/workspace stats, timeline,
    and context switches) are computed from logical sessions.
    Irrelevant fields (URL, tab IDs) are omitted from the report.
    """
    passed_data_directory = data_directory
    events = deduplicate_events(events)
    if not events:
        return _empty_report(date_str=date_str)

    report_tz = get_report_timezone(events)

    # 1. Build non-overlapping PC timeline
    pc_events, fallback_events, watcher_offline_ranges, fallback_ranges = build_pc_timeline(
        events, merge_gap_seconds=merge_gap_seconds
    )

    # 2. Extract mobile and manual events as separate lanes
    mobile_events = [e for e in events if e.get("source") == "mobile"]
    manual_events = [e for e in events if e.get("source") == "manual"]

    combined_events = pc_events + fallback_events + mobile_events + manual_events
    logical_sessions = sessionize_events(combined_events, merge_gap_seconds=merge_gap_seconds)
    brief_sessions = []
    kept_sessions = []
    if min_session_duration > 0:
        for s in logical_sessions:
            if s.get("source") != "manual" and float(s.get("duration_seconds", 0.0)) < min_session_duration:
                brief_sessions.append(s)
            else:
                kept_sessions.append(s)
    else:
        kept_sessions = list(logical_sessions)

    brief_seconds = round(sum(float(s["duration_seconds"]) for s in brief_sessions), 1)
    brief_session_count = len(brief_sessions)

    if not kept_sessions:
        empty = _empty_report(date_str=date_str, report_tz=report_tz)
        empty["summary"]["brief_seconds"] = brief_seconds
        empty["summary"]["brief_session_count"] = brief_session_count
        return empty

    logical_sessions = kept_sessions

    total_seconds = 0.0
    browser_seconds = 0.0
    vscode_seconds = 0.0
    mobile_seconds = 0.0
    desktop_seconds = 0.0
    manual_seconds = 0.0

    # Collect time intervals for wall-clock union calculation
    all_intervals = []
    screen_intervals = []
    pc_intervals = []
    mobile_intervals = []

    source_counts = defaultdict(lambda: {"duration": 0.0, "count": 0})
    domain_stats = defaultdict(lambda: {"duration": 0.0, "count": 0})
    title_stats = defaultdict(lambda: {"duration": 0.0, "count": 0, "domain": ""})
    app_stats = defaultdict(lambda: {"duration": 0.0, "count": 0, "package": ""})
    desktop_app_stats = defaultdict(lambda: {"duration": 0.0, "count": 0})
    manual_activity_stats = defaultdict(lambda: {"duration": 0.0, "count": 0, "category": ""})
    workspace_stats = defaultdict(lambda: {
        "duration": 0.0,
        "count": 0,
    })
    hourly = defaultdict(lambda: {"active": 0.0, "browser": 0.0, "vscode": 0.0, "mobile": 0.0, "desktop": 0.0, "manual": 0.0})
    hourly_screen_intervals = defaultdict(list)
    hourly_manual_intervals = defaultdict(list)

    timeline = []

    for s in logical_sessions:
        dur = float(s["duration_seconds"])
        source = s["source"]
        ctx = s.get("context", {})
        cleaned_ctx = clean_context_for_report(source, ctx)

        # Collect raw event intervals for wall-clock union (cross-device de-overlap without gap inflation)
        for raw_e in s["raw_events"]:
            intv = (raw_e["_start_dt"], raw_e["_end_dt"])
            all_intervals.append(intv)
            if source in ("browser", "vscode", "desktop"):
                pc_intervals.append(intv)
                screen_intervals.append(intv)
            elif source == "mobile":
                mobile_intervals.append(intv)
                screen_intervals.append(intv)

        source_counts[source]["duration"] += dur
        source_counts[source]["count"] += 1

        if source == "browser":
            browser_seconds += dur
            domain = ctx.get("domain", "unknown")
            title = ctx.get("title", "")
            domain_stats[domain]["duration"] += dur
            domain_stats[domain]["count"] += 1
            if title:
                title_stats[title]["duration"] += dur
                title_stats[title]["count"] += 1
                title_stats[title]["domain"] = domain

        elif source == "vscode":
            vscode_seconds += dur
            ws = ctx.get("workspace", "No Workspace")
            workspace_stats[ws]["duration"] += dur
            workspace_stats[ws]["count"] += 1

        elif source == "mobile":
            mobile_seconds += dur
            app = ctx.get("app", "unknown")
            app_stats[app]["duration"] += dur
            app_stats[app]["count"] += 1
            app_stats[app]["package"] = ctx.get("package", "")

        elif source == "desktop":
            desktop_seconds += dur
            app = ctx.get("app", "unknown")
            desktop_app_stats[app]["duration"] += dur
            desktop_app_stats[app]["count"] += 1

        elif source == "manual":
            manual_seconds += dur
            act = ctx.get("activity") or ctx.get("title", "Offline Activity")
            cat = ctx.get("category", "other")
            manual_activity_stats[act]["duration"] += dur
            manual_activity_stats[act]["count"] += 1
            manual_activity_stats[act]["category"] = cat

        # Hourly breakdown: bucket each raw event's active duration into hours
        for raw_e in s["raw_events"]:
            try:
                raw_start_local = raw_e["_start_dt"].astimezone(report_tz)
                raw_end_local = raw_e["_end_dt"].astimezone(report_tz)
                segments = split_interval_by_hour(raw_start_local, raw_end_local)
                for h, seg_start, seg_end in segments:
                    secs = (seg_end - seg_start).total_seconds()
                    if source == "manual":
                        hourly_manual_intervals[h].append((seg_start, seg_end))
                    else:
                        hourly_screen_intervals[h].append((seg_start, seg_end))
                        if source == "browser":
                            hourly[h]["browser"] += secs
                        elif source == "vscode":
                            hourly[h]["vscode"] += secs
                        elif source == "mobile":
                            hourly[h]["mobile"] += secs
                        elif source == "desktop":
                            hourly[h]["desktop"] += secs
            except Exception:
                pass

        # (timeline constructed after label resolution)

    # Summary metrics
    earliest_start = min(s["start_dt"] for s in logical_sessions)
    latest_end = max(s["end_dt"] for s in logical_sessions)

    # Compute total active time using interval union (prevents double-counting
    # when PC and mobile sessions overlap in time)
    pc_active_seconds = compute_union_seconds(pc_intervals) if pc_intervals else 0.0
    screen_seconds = compute_union_seconds(screen_intervals) if screen_intervals else 0.0
    total_accounted_seconds = compute_union_seconds(all_intervals) if all_intervals else 0.0
    total_seconds = screen_seconds if screen_intervals or not all_intervals else total_accounted_seconds
    now_local = datetime.now(report_tz)
    today_str = now_local.strftime("%Y-%m-%d")
    day_span_seconds = 86400.0
    if date_str and date_str == today_str:
        day_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        day_span_seconds = max(0.0, min(86400.0, (now_local - day_start).total_seconds()))
    unobserved_seconds = max(0.0, day_span_seconds - total_accounted_seconds)

    # Per-source seconds (naive sums — they represent time on that specific device)
    browser_seconds = source_counts.get("browser", {}).get("duration", 0.0)
    vscode_seconds = source_counts.get("vscode", {}).get("duration", 0.0)
    mobile_seconds = source_counts.get("mobile", {}).get("duration", 0.0)
    desktop_seconds = source_counts.get("desktop", {}).get("duration", 0.0)
    manual_seconds = source_counts.get("manual", {}).get("duration", 0.0)

    # Compute hourly active_seconds and manual_seconds by interval union per hour
    all_hours = set(hourly.keys()) | set(hourly_screen_intervals.keys()) | set(hourly_manual_intervals.keys())
    for h in all_hours:
        hourly[h]["active"] = compute_union_seconds(hourly_screen_intervals[h])
        hourly[h]["manual"] = compute_union_seconds(hourly_manual_intervals[h])

    observed_span_seconds = max(0.0, (latest_end - earliest_start).total_seconds())

    base_calc_seconds = screen_seconds if screen_seconds > 0 else total_seconds

    # Sorted aggregations
    domains = sorted(
        [
            {
                "domain": d,
                "duration_seconds": round(st["duration"], 1),
                "session_count": st["count"],
                "percentage": round(st["duration"] / base_calc_seconds * 100, 1) if base_calc_seconds > 0 else 0,
            }
            for d, st in domain_stats.items()
        ],
        key=lambda x: x["duration_seconds"],
        reverse=True,
    )

    # Top 15 most significant titles
    titles = sorted(
        [
            {
                "title": t,
                "domain": st["domain"],
                "duration_seconds": round(st["duration"], 1),
                "session_count": st["count"],
            }
            for t, st in title_stats.items()
        ],
        key=lambda x: x["duration_seconds"],
        reverse=True,
    )[:15]

    workspaces = sorted(
        [
            {
                "workspace": ws,
                "duration_seconds": round(st["duration"], 1),
                "session_count": st["count"],
            }
            for ws, st in workspace_stats.items()
        ],
        key=lambda x: x["duration_seconds"],
        reverse=True,
    )

    apps = sorted(
        [
            {
                "app": a,
                "package": st["package"],
                "duration_seconds": round(st["duration"], 1),
                "session_count": st["count"],
                "percentage": round(st["duration"] / base_calc_seconds * 100, 1) if base_calc_seconds > 0 else 0,
            }
            for a, st in app_stats.items()
        ],
        key=lambda x: x["duration_seconds"],
        reverse=True,
    )

    desktop_apps = sorted(
        [
            {
                "app": a,
                "duration_seconds": round(st["duration"], 1),
                "session_count": st["count"],
                "percentage": round(st["duration"] / base_calc_seconds * 100, 1) if base_calc_seconds > 0 else 0,
            }
            for a, st in desktop_app_stats.items()
        ],
        key=lambda x: x["duration_seconds"],
        reverse=True,
    )

    sources = {
        src: {
            "duration_seconds": round(st["duration"], 1),
            "session_count": st["count"],
        }
        for src, st in source_counts.items()
    }

    manual_activities = sorted(
        [
            {
                "activity": act,
                "category": st["category"],
                "duration_seconds": round(st["duration"], 1),
                "session_count": st["count"],
            }
            for act, st in manual_activity_stats.items()
        ],
        key=lambda x: x["duration_seconds"],
        reverse=True,
    )

    # Top 10 longest logical sessions (clean context, screen sessions only)
    longest_sessions = sorted(
        [
            {
                "start": s["start_dt"].astimezone(report_tz).isoformat(),
                "end": s["end_dt"].astimezone(report_tz).isoformat(),
                "duration_seconds": round(float(s["duration_seconds"]), 1),
                "source": s["source"],
                "context": clean_context_for_report(s["source"], s.get("context", {})),
                "raw_event_count": s["raw_event_count"],
            }
            for s in logical_sessions
            if s["source"] != "manual"
        ],
        key=lambda x: x["duration_seconds"],
        reverse=True,
    )[:10]

    hourly_breakdown = sorted(
        [
            {
                "hour": h,
                "active_seconds": round(st["active"], 1),
                "browser_seconds": round(st["browser"], 1),
                "vscode_seconds": round(st["vscode"], 1),
                "mobile_seconds": round(st["mobile"], 1),
                "desktop_seconds": round(st["desktop"], 1),
                "manual_seconds": round(st["manual"], 1),
            }
            for h, st in hourly.items()
        ],
        key=lambda x: x["hour"],
    )

    # Data quality metrics
    last_mobile_sync = None
    if not data_directory:
        try:
            cfg = get_config()
            data_directory = cfg.data_directory
        except Exception:
            pass

    if not date_str and events:
        try:
            date_str = parse_to_utc(events[0]["start"]).astimezone(report_tz).strftime("%Y-%m-%d")
        except Exception:
            pass

    if data_directory and date_str:
        try:
            d = date.fromisoformat(date_str)
            m_path = Path(data_directory) / "raw" / str(d.year) / d.strftime("%b").lower() / "daily" / "mobile" / f"{date_str}.jsonl"
            if m_path.exists():
                mtime = os.path.getmtime(m_path)
                last_mobile_sync = datetime.fromtimestamp(mtime, tz=report_tz).isoformat()
            else:
                legacy_m = Path(data_directory) / "raw" / "mobile" / f"{date_str}.jsonl"
                if legacy_m.exists():
                    mtime = os.path.getmtime(legacy_m)
                    last_mobile_sync = datetime.fromtimestamp(mtime, tz=report_tz).isoformat()
        except Exception:
            pass

    collector_offline_ranges = []
    if all_intervals:
        sorted_acc = sorted(all_intervals, key=lambda x: x[0])
        merged_acc = [sorted_acc[0]]
        for s_int, e_int in sorted_acc[1:]:
            if s_int <= merged_acc[-1][1]:
                merged_acc[-1] = (merged_acc[-1][0], max(merged_acc[-1][1], e_int))
            else:
                merged_acc.append((s_int, e_int))
        for i in range(len(merged_acc) - 1):
            gap_s = merged_acc[i][1]
            gap_e = merged_acc[i + 1][0]
            dur = (gap_e - gap_s).total_seconds()
            if dur >= 3600.0:
                collector_offline_ranges.append({
                    "start": gap_s.astimezone(report_tz).isoformat(),
                    "end": gap_e.astimezone(report_tz).isoformat(),
                    "duration_seconds": round(dur, 1),
                })

    formatted_watcher_offline = []
    for r in watcher_offline_ranges:
        s_dt = parse_to_utc(r["start"]) if isinstance(r["start"], str) else r["start"]
        e_dt = parse_to_utc(r["end"]) if isinstance(r["end"], str) else r["end"]
        formatted_watcher_offline.append({
            "start": s_dt.astimezone(report_tz).isoformat(),
            "end": e_dt.astimezone(report_tz).isoformat(),
            "duration_seconds": r["duration_seconds"],
        })

    formatted_fallback = []
    for r in fallback_ranges:
        s_dt = parse_to_utc(r["start"]) if isinstance(r["start"], str) else r["start"]
        e_dt = parse_to_utc(r["end"]) if isinstance(r["end"], str) else r["end"]
        formatted_fallback.append({
            "start": s_dt.astimezone(report_tz).isoformat(),
            "end": e_dt.astimezone(report_tz).isoformat(),
            "duration_seconds": r["duration_seconds"],
        })

    # Focus blocks (PC timeline)
    pc_timeline_events = pc_events + fallback_events
    longest_focus_block, top_3_focus_blocks = compute_focus_blocks(
        pc_timeline_events, report_tz=report_tz, gap_threshold=60.0
    )

    # Screen activity boundaries (screen activity only)
    first_screen_activity = (
        min(s[0] for s in screen_intervals).astimezone(report_tz).isoformat()
        if screen_intervals else None
    )
    last_screen_activity = (
        max(s[1] for s in screen_intervals).astimezone(report_tz).isoformat()
        if screen_intervals else None
    )

    calc_date_str = date_str
    if not calc_date_str and events:
        try:
            calc_date_str = parse_to_utc(events[0]["start"]).astimezone(report_tz).strftime("%Y-%m-%d")
        except Exception:
            calc_date_str = ""

    # Late night screen seconds (00:00 - 05:00 local, PC plus mobile screen union)
    late_night_screen_seconds = compute_late_night_seconds(
        screen_intervals, report_tz=report_tz, date_str=calc_date_str
    )

    # Sleep metrics (night ending on date_str morning)
    sleep_metrics = compute_sleep_metrics(
        calc_date_str, report_tz=report_tz, data_directory=passed_data_directory, events=events
    )

    mobile_screen_seconds = compute_union_seconds(mobile_intervals) if mobile_intervals else 0.0

    daily_metrics = {
        "first_activity": first_screen_activity,
        "last_activity": last_screen_activity,
        "active_seconds": round(screen_seconds, 1),
        "pc_seconds": round(pc_active_seconds, 1),
        "mobile_seconds": round(mobile_screen_seconds, 1),
        "phone_share": round(mobile_screen_seconds / screen_seconds, 3) if screen_seconds > 0 else 0.0,
        "longest_focus_block": longest_focus_block,
        "top_3_focus_blocks": top_3_focus_blocks,
        "late_night_screen_seconds": round(late_night_screen_seconds, 1),
        "sleep": sleep_metrics,
    }

    # Labels parsing & overlay (Screen time only)
    if analysis_text is None and calc_date_str and passed_data_directory:
        analysis_text = read_analysis_for_date(passed_data_directory, calc_date_str)

    energy, raw_label_intervals, parse_warnings = parse_labels_from_markdown(
        analysis_text, calc_date_str, report_tz=report_tz
    )
    resolved_labels = resolve_label_intervals(raw_label_intervals)
    label_totals, labeled_seconds, unlabeled_seconds, label_coverage_pct, overlay_warnings = overlay_labels_on_screen_time(
        screen_intervals, resolved_labels
    )
    label_warnings = parse_warnings + overlay_warnings

    # Timeline entry for logical session with label
    timeline = []
    allowed_set = set(ALLOWED_LABELS)
    for s in logical_sessions:
        dur = float(s["duration_seconds"])
        source = s["source"]
        ctx = s.get("context", {})
        cleaned_ctx = clean_context_for_report(source, ctx)

        if source == "manual":
            entry_label = None
        else:
            s_int = s["start_dt"]
            e_int = s["end_dt"]
            matching_labels = [
                lbl["label"] for lbl in resolved_labels
                if lbl["start_dt"] <= s_int and lbl["end_dt"] >= e_int
            ]
            if len(matching_labels) == 1:
                matched = matching_labels[0]
                entry_label = matched if matched in allowed_set else "other"
            else:
                entry_label = "unlabeled"

        timeline.append({
            "start": s["start_dt"].astimezone(report_tz).isoformat(),
            "end": s["end_dt"].astimezone(report_tz).isoformat(),
            "duration_seconds": round(dur, 1),
            "source": source,
            "context": cleaned_ctx,
            "raw_event_count": s["raw_event_count"],
            "label": entry_label,
        })

    return {
        "summary": {
            "total_active_seconds": round(total_seconds, 1),
            "screen_seconds": round(screen_seconds, 1),
            "pc_active_seconds": round(pc_active_seconds, 1),
            "browser_seconds": round(browser_seconds, 1),
            "vscode_seconds": round(vscode_seconds, 1),
            "mobile_seconds": round(mobile_seconds, 1),
            "desktop_seconds": round(desktop_seconds, 1),
            "manual_seconds": round(manual_seconds, 1),
            "brief_seconds": round(brief_seconds, 1),
            "brief_session_count": brief_session_count,
            "total_accounted_seconds": round(total_accounted_seconds, 1),
            "unobserved_seconds": round(unobserved_seconds, 1),
            "session_count": len(logical_sessions),
            "first_activity": earliest_start.astimezone(report_tz).isoformat(),
            "last_activity": latest_end.astimezone(report_tz).isoformat(),
            "observed_span_seconds": round(observed_span_seconds, 1),
        },
        "daily_metrics": daily_metrics,
        "labels": {
            "energy": energy,
            "label_totals": label_totals,
            "labeled_seconds": labeled_seconds,
            "unlabeled_seconds": unlabeled_seconds,
            "label_coverage_pct": label_coverage_pct,
        },
        "label_totals": label_totals,
        "labeled_seconds": labeled_seconds,
        "unlabeled_seconds": unlabeled_seconds,
        "label_coverage_pct": label_coverage_pct,
        "data_quality": {
            "sources_present": sorted(list(set(e.get("source") for e in events if e.get("source")))),
            "last_mobile_sync": last_mobile_sync,
            "watcher_offline_ranges": formatted_watcher_offline,
            "collector_offline_ranges": collector_offline_ranges,
            "fallback_ranges": formatted_fallback,
            "label_warnings": label_warnings,
        },
        "sources": sources,
        "domains": domains,
        "titles": titles,
        "workspaces": workspaces,
        "apps": apps,
        "desktop_apps": desktop_apps,
        "manual_activities": manual_activities,
        "longest_sessions": longest_sessions,
        "timeline": timeline,
        "hourly_breakdown": hourly_breakdown,
    }


def _empty_report(date_str: Optional[str] = None, report_tz: Optional[timezone] = None) -> Dict[str, Any]:
    """Return an empty report structure."""
    day_span_seconds = 86400.0
    if date_str:
        try:
            if report_tz is None:
                report_tz = datetime.now().astimezone().tzinfo or timezone.utc
            now_local = datetime.now(report_tz)
            if date_str == now_local.strftime("%Y-%m-%d"):
                day_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
                day_span_seconds = max(0.0, min(86400.0, (now_local - day_start).total_seconds()))
        except Exception:
            pass

    empty_label_totals = {lbl: {"duration_seconds": 0.0, "planned_seconds": 0.0} for lbl in ALLOWED_LABELS}

    return {
        "summary": {
            "total_active_seconds": 0.0,
            "screen_seconds": 0.0,
            "pc_active_seconds": 0.0,
            "browser_seconds": 0.0,
            "vscode_seconds": 0.0,
            "mobile_seconds": 0.0,
            "desktop_seconds": 0.0,
            "manual_seconds": 0.0,
            "brief_seconds": 0.0,
            "brief_session_count": 0,
            "total_accounted_seconds": 0.0,
            "unobserved_seconds": round(day_span_seconds, 1),
            "session_count": 0,
            "first_activity": None,
            "last_activity": None,
            "observed_span_seconds": 0.0,
        },
        "daily_metrics": {
            "first_activity": None,
            "last_activity": None,
            "active_seconds": 0.0,
            "pc_seconds": 0.0,
            "mobile_seconds": 0.0,
            "phone_share": 0.0,
            "longest_focus_block": None,
            "top_3_focus_blocks": [],
            "late_night_screen_seconds": 0.0,
            "sleep": {
                "status": "insufficient_data",
                "reason": "No events recorded",
                "bedtime": None,
                "wake_time": None,
                "duration_seconds": None,
                "duration": None,
                "source": None,
                "last_phone_use_before_bedtime": None,
                "first_phone_use_after_waking": None,
            },
        },
        "labels": {
            "energy": None,
            "label_totals": empty_label_totals,
            "labeled_seconds": 0.0,
            "unlabeled_seconds": 0.0,
            "label_coverage_pct": 0.0,
        },
        "label_totals": empty_label_totals,
        "labeled_seconds": 0.0,
        "unlabeled_seconds": 0.0,
        "label_coverage_pct": 0.0,
        "data_quality": {
            "sources_present": [],
            "last_mobile_sync": None,
            "watcher_offline_ranges": [],
            "collector_offline_ranges": [],
            "fallback_ranges": [],
            "label_warnings": [],
        },
        "sources": {},
        "domains": [],
        "titles": [],
        "workspaces": [],
        "apps": [],
        "desktop_apps": [],
        "manual_activities": [],
        "longest_sessions": [],
        "timeline": [],
        "hourly_breakdown": [],
    }


def clip_events_to_day(
    events: List[Dict[str, Any]],
    date_str: str,
    report_tz: Optional[timezone] = None
) -> List[Dict[str, Any]]:
    """Clip every event to [D 00:00, D+1 00:00) in local report timezone.
    Events ending <= D 00:00 or starting >= D+1 00:00 are excluded."""
    if not events:
        return []
    if report_tz is None:
        report_tz = get_report_timezone(events)

    d = date.fromisoformat(date_str)
    day_start = datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=report_tz)
    day_end = day_start + timedelta(days=1)

    clipped = []
    for e in events:
        try:
            s_dt = parse_to_utc(e["start"]).astimezone(report_tz)
            e_dt = parse_to_utc(e["end"]).astimezone(report_tz)
            if e_dt <= day_start or s_dt >= day_end:
                continue

            s_clipped = max(s_dt, day_start)
            e_clipped = min(e_dt, day_end)
            dur = (e_clipped - s_clipped).total_seconds()
            if dur <= 0.001:
                continue

            evt = dict(e)
            evt["start"] = s_clipped.isoformat()
            evt["end"] = e_clipped.isoformat()
            evt["duration_seconds"] = round(dur, 1)
            if "_start_dt" in evt:
                evt["_start_dt"] = s_clipped.astimezone(timezone.utc)
            if "_end_dt" in evt:
                evt["_end_dt"] = e_clipped.astimezone(timezone.utc)
            if "_duration_seconds" in evt:
                evt["_duration_seconds"] = dur
            clipped.append(evt)
        except Exception:
            continue

    return clipped


def _read_raw_files_for_date(data_directory: str, dt_str: str) -> List[Dict[str, Any]]:
    """Read raw PC, mobile, legacy and manual activity events for a specific single date."""
    events = []
    try:
        d = date.fromisoformat(dt_str)
        year = str(d.year)
        month = d.strftime("%b").lower()
        daily_dir = Path(data_directory) / "raw" / year / month / "daily"

        structured_file = daily_dir / f"{dt_str}.jsonl"
        if structured_file.exists():
            events.extend(read_events(str(structured_file)))

        mobile_file = daily_dir / "mobile" / f"{dt_str}.jsonl"
        if mobile_file.exists():
            events.extend(read_events(str(mobile_file)))
    except Exception:
        pass

    raw_dir = Path(data_directory) / "raw"
    legacy_pc_file = raw_dir / f"{dt_str}.jsonl"
    if legacy_pc_file.exists():
        events.extend(read_events(str(legacy_pc_file)))

    legacy_mobile_file = raw_dir / "mobile" / f"{dt_str}.jsonl"
    if legacy_mobile_file.exists():
        events.extend(read_events(str(legacy_mobile_file)))

    legacy_desktop_file = raw_dir / "desktop" / f"{dt_str}.jsonl"
    if legacy_desktop_file.exists():
        events.extend(read_events(str(legacy_desktop_file)))

    try:
        from collector.manual_storage import read_manual_events
        manual_evts = read_manual_events(data_directory, dt_str)
        if manual_evts:
            events.extend(manual_evts)
    except Exception:
        pass

    return events


def read_day_events(data_directory: str, date_str: str) -> List[Dict[str, Any]]:
    """Read events for date D, also reading D-1's raw files (PC and mobile),
    and clips every event to [D 00:00, D+1 00:00) local before aggregation."""
    d = date.fromisoformat(date_str)
    prev_d = d - timedelta(days=1)
    prev_date_str = prev_d.isoformat()

    prev_events = _read_raw_files_for_date(data_directory, prev_date_str)
    day_events = _read_raw_files_for_date(data_directory, date_str)

    all_raw = deduplicate_events(prev_events + day_events)
    if not all_raw:
        return []

    report_tz = get_report_timezone(all_raw)
    return clip_events_to_day(all_raw, date_str, report_tz=report_tz)


def generate_single_day_report(
    config,
    date_str: str,
    merge_gap_seconds: Optional[float] = None,
    min_session_duration: Optional[float] = None,
) -> Dict[str, Any]:
    """Generate a daily report from the complete day's raw JSONL data.
    
    Reads all events in raw/YYYY/mmm/daily/YYYY-MM-DD.jsonl
    and fully materializes a fresh report. Overwrites previous reports cleanly.
    """
    if merge_gap_seconds is None:
        merge_gap_seconds = getattr(config, "session_merge_gap_seconds", DEFAULT_SESSION_MERGE_GAP_SECONDS)
    if min_session_duration is None:
        min_session_duration = getattr(config, "min_duration_seconds", 40.0)

    try:
        d = date.fromisoformat(date_str)
        filepath = Path(config.data_directory) / "raw" / str(d.year) / d.strftime("%b").lower() / "daily" / f"{date_str}.jsonl"
    except Exception:
        filepath = Path(config.data_directory) / "raw" / f"{date_str}.jsonl"

    if not filepath.exists():
        legacy_path = Path(config.data_directory) / "raw" / f"{date_str}.jsonl"
        if legacy_path.exists():
            filepath = legacy_path

    print(f"Reading: {filepath}")

    events = read_day_events(config.data_directory, date_str)
    report = aggregate_events(
        events,
        merge_gap_seconds=merge_gap_seconds,
        min_session_duration=min_session_duration,
        data_directory=config.data_directory,
        date_str=date_str,
    )
    report["generated_at"] = datetime.now().astimezone().isoformat()
    report["date"] = date_str
    return report


def generate_range_report(
    config,
    from_date: str,
    to_date: str,
    merge_gap_seconds: Optional[float] = None,
    min_session_duration: Optional[float] = None,
) -> Dict[str, Any]:
    """Generate an aggregate report for a date range."""
    if merge_gap_seconds is None:
        merge_gap_seconds = getattr(config, "session_merge_gap_seconds", DEFAULT_SESSION_MERGE_GAP_SECONDS)
    if min_session_duration is None:
        min_session_duration = getattr(config, "min_duration_seconds", 40.0)

    start = date.fromisoformat(from_date)
    end = date.fromisoformat(to_date)

    all_events = []
    daily_summaries = []
    current = start

    while current <= end:
        date_str = current.isoformat()
        try:
            d = current
            filepath = Path(config.data_directory) / "raw" / str(d.year) / d.strftime("%b").lower() / "daily" / f"{date_str}.jsonl"
        except Exception:
            filepath = Path(config.data_directory) / "raw" / f"{date_str}.jsonl"

        if not filepath.exists():
            legacy_path = Path(config.data_directory) / "raw" / f"{date_str}.jsonl"
            if legacy_path.exists():
                filepath = legacy_path

        print(f"Reading: {filepath}")

        events = read_day_events(config.data_directory, date_str)
        day_report = aggregate_events(
            events,
            merge_gap_seconds=merge_gap_seconds,
            min_session_duration=min_session_duration,
            data_directory=config.data_directory,
            date_str=date_str,
        )
        daily_summaries.append({
            "date": date_str,
            **day_report["summary"],
        })

        all_events.extend(events)
        current += timedelta(days=1)

    report = aggregate_events(
        all_events,
        merge_gap_seconds=merge_gap_seconds,
        min_session_duration=min_session_duration,
        data_directory=config.data_directory,
    )
    report["generated_at"] = datetime.now().astimezone().isoformat()
    report["from"] = from_date
    report["to"] = to_date
    report["daily_summary"] = daily_summaries
    return report


def write_report(config, report: Dict[str, Any], filename: str) -> str:
    """Safely write JSON report to structured Record/report/YYYY/mmm/daily/ directory."""
    target_date_str = report.get("date")
    hierarchical_path = None

    if target_date_str:
        try:
            d = date.fromisoformat(target_date_str)
            year = str(d.year)
            month = d.strftime("%b").lower()  # e.g. 'sep'
            structured_dir = Path(config.data_directory) / "report" / year / month / "daily"
            structured_dir.mkdir(parents=True, exist_ok=True)
            hierarchical_path = structured_dir / filename
            with open(hierarchical_path, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False, default=str)
            print(f"\nReport written to: {hierarchical_path}")
        except ValueError:
            pass

    if hierarchical_path:
        return str(hierarchical_path)

    fallback_dir = Path(config.data_directory) / "report"
    fallback_dir.mkdir(parents=True, exist_ok=True)
    fallback_path = fallback_dir / filename
    with open(fallback_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)
    return str(fallback_path)


def print_summary(report: Dict[str, Any]):
    """Print human-readable summary of the report to console."""
    s = report.get("summary", {})
    print("\n" + "=" * 55)
    print("ACTIVITY REPORT SUMMARY (LOGICAL SESSIONS)")
    print("=" * 55)

    total = s.get("total_active_seconds", 0)
    hours = int(total // 3600)
    mins = int((total % 3600) // 60)
    secs = int(total % 60)
    print(f"Total active time:     {hours}h {mins}m {secs}s ({round(total, 1)}s)")

    browser = s.get("browser_seconds", 0)
    bh, bm = int(browser // 3600), int((browser % 3600) // 60)
    print(f"Browser time:          {bh}h {bm}m ({round(browser, 1)}s)")

    vscode = s.get("vscode_seconds", 0)
    vh, vm = int(vscode // 3600), int((vscode % 3600) // 60)
    print(f"VS Code time:          {vh}h {vm}m ({round(vscode, 1)}s)")

    mobile = s.get("mobile_seconds", 0)
    if mobile > 0:
        mh, mm = int(mobile // 3600), int((mobile % 3600) // 60)
        print(f"Mobile screen time:    {mh}h {mm}m ({round(mobile, 1)}s)")

    desktop = s.get("desktop_seconds", 0)
    if desktop > 0:
        dh, dm = int(desktop // 3600), int((desktop % 3600) // 60)
        print(f"Desktop app time:      {dh}h {dm}m ({round(desktop, 1)}s)")

    brief = s.get("brief_seconds", 0)
    if brief > 0:
        print(f"Brief sessions:        {s.get('brief_session_count', 0)} ({round(brief, 1)}s excluded by min-duration)")

    span = s.get("observed_span_seconds", 0)
    sh, sm = int(span // 3600), int((span % 3600) // 60)
    print(f"Observed span:         {sh}h {sm}m ({round(span, 1)}s)")

    print(f"Logical sessions:      {s.get('session_count', 0)}")

    if s.get("first_activity"):
        print(f"First activity:        {s['first_activity']}")
    if s.get("last_activity"):
        print(f"Last activity:         {s['last_activity']}")

    domains = report.get("domains", [])
    if domains:
        print(f"\nTop domains:")
        for d in domains[:5]:
            dm = int(d['duration_seconds'] // 60)
            ds = int(d['duration_seconds'] % 60)
            print(f"  {d['domain']:30s} {dm}m {ds:02d}s ({d['session_count']} sessions, {d['percentage']}%)")

    titles = report.get("titles", [])
    if titles:
        print(f"\nTop titles:")
        for t in titles[:5]:
            tm = int(t['duration_seconds'] // 60)
            ts_sec = int(t['duration_seconds'] % 60)
            print(f"  {t['title'][:35]:35s} {tm}m {ts_sec:02d}s ({t['session_count']} sessions)")

    workspaces = report.get("workspaces", [])
    if workspaces:
        print(f"\nTop workspaces:")
        for w in workspaces[:5]:
            wm = int(w['duration_seconds'] // 60)
            ws_sec = int(w['duration_seconds'] % 60)
            print(f"  {w['workspace']:30s} {wm}m {ws_sec:02d}s ({w['session_count']} sessions)")

    apps = report.get("apps", [])
    if apps:
        print(f"\nTop mobile apps:")
        for a in apps[:5]:
            am = int(a['duration_seconds'] // 60)
            as_sec = int(a['duration_seconds'] % 60)
            print(f"  {a['app']:30s} {am}m {as_sec:02d}s ({a['session_count']} sessions, {a['percentage']}%)")

    desktop_apps = report.get("desktop_apps", [])
    if desktop_apps:
        print(f"\nTop desktop apps:")
        for a in desktop_apps[:5]:
            am = int(a['duration_seconds'] // 60)
            as_sec = int(a['duration_seconds'] % 60)
            print(f"  {a['app']:30s} {am}m {as_sec:02d}s ({a['session_count']} sessions, {a['percentage']}%)")

    longest = report.get("longest_sessions", [])
    if longest:
        print(f"\nLongest logical sessions:")
        for idx, ls in enumerate(longest[:5], 1):
            dur_m = round(ls['duration_seconds'] / 60, 1)
            ctx = ls.get("context", {})
            name = ctx.get("title") or ctx.get("workspace") or ctx.get("app") or ctx.get("domain") or "unknown"
            print(f"  {idx}. {ls['source']:7s} | {dur_m:4.1f}m ({ls['duration_seconds']}s) | {name[:35]}")

    print("=" * 55)


def main():
    parser = argparse.ArgumentParser(
        description="Generate activity reports from raw JSONL data using logical sessions"
    )
    parser.add_argument(
        "--date",
        help="Generate report for a single date (YYYY-MM-DD). Defaults to today if omitted.",
    )
    parser.add_argument(
        "--yesterday", action="store_true",
        help="Generate report for yesterday's date.",
    )
    parser.add_argument(
        "--weekly", action="store_true",
        help="Generate weekly report for the past 7 days up to today.",
    )
    parser.add_argument(
        "--from", dest="from_date",
        help="Start date for range report (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--to", dest="to_date",
        help="End date for range report (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--merge-gap", dest="merge_gap", type=float, default=None,
        help="Maximum gap in seconds between consecutive events of same context to merge (default from config or 30)",
    )
    parser.add_argument(
        "--min-duration", dest="min_duration", type=float, default=None,
        help="Minimum session duration in seconds to include in report (default from config or 40.0)",
    )

    args = parser.parse_args()

    config = get_config()
    print(f"Data directory: {config.data_directory}")

    merge_gap = args.merge_gap
    if merge_gap is None:
        merge_gap = getattr(config, "session_merge_gap_seconds", DEFAULT_SESSION_MERGE_GAP_SECONDS)

    min_dur = args.min_duration
    if min_dur is None:
        min_dur = getattr(config, "min_duration_seconds", 40.0)

    is_weekly = False
    if args.weekly:
        end_d = date.today()
        start_d = end_d - timedelta(days=6)
        report = generate_range_report(config, start_d.isoformat(), end_d.isoformat(), merge_gap_seconds=merge_gap, min_session_duration=min_dur)
        week_num = end_d.isocalendar()[1]
        filename = f"{end_d.year}-W{week_num:02d}.json"
        is_weekly = True
    elif args.yesterday:
        target_date = (date.today() - timedelta(days=1)).isoformat()
        report = generate_single_day_report(config, target_date, merge_gap_seconds=merge_gap, min_session_duration=min_dur)
        filename = f"{target_date}.json"
    elif args.from_date and args.to_date:
        try:
            d1 = date.fromisoformat(args.from_date)
            d2 = date.fromisoformat(args.to_date)
        except ValueError as e:
            parser.error(f"Invalid date format: {e}. Use YYYY-MM-DD.")

        if d1 > d2:
            parser.error("--from date must be before --to date")

        report = generate_range_report(config, args.from_date, args.to_date, merge_gap_seconds=merge_gap, min_session_duration=min_dur)
        filename = f"{args.from_date}_to_{args.to_date}.json"
        is_weekly = True
    else:
        # Default to today if no date specified
        target_date = args.date or date.today().isoformat()
        try:
            date.fromisoformat(target_date)
        except ValueError:
            parser.error(f"Invalid date format: {target_date}. Use YYYY-MM-DD.")

        report = generate_single_day_report(config, target_date, merge_gap_seconds=merge_gap, min_session_duration=min_dur)
        filename = f"{target_date}.json"

    write_report(config, report, filename)
    print_summary(report)

    # Automatically regenerate dashboard HTML so the new report is immediately visualised
    try:
        from reporting.generate_dashboard import generate_dashboard_files
        generate_dashboard_files(config.data_directory)
    except Exception as e:
        print(f"Notice: Could not automatically update dashboard: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
