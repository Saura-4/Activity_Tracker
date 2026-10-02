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
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
from collections import defaultdict
from typing import List, Dict, Any, Tuple, Optional

# Add parent directory to path so we can import collector modules
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from collector.config import get_config

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
    """Remove duplicate raw events by ID, preserving first occurrence."""
    seen = set()
    unique = []
    for event in events:
        eid = event.get("id")
        if eid and eid not in seen:
            seen.add(eid)
            unique.append(event)
    return unique


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
            ctx.get("file"),
            ctx.get("language"),
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
            ctx.get("title"),
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
                    "context": event.get("context", {}),
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
            else:
                sessions.append({
                    "source": event["source"],
                    "context": event.get("context", {}),
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
        if "file" in ctx:
            clean["file"] = ctx["file"]
        if "language" in ctx:
            clean["language"] = ctx["language"]
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


def aggregate_events(
    events: List[Dict[str, Any]],
    merge_gap_seconds: float = DEFAULT_SESSION_MERGE_GAP_SECONDS,
    min_session_duration: float = 0.0,
) -> Dict[str, Any]:
    """Aggregate raw activity events into a structured, compact report.
    
    All aggregations (total duration, domain/workspace stats, timeline,
    and context switches) are computed from logical sessions.
    Irrelevant fields (URL, tab IDs) are omitted from the report.
    """
    events = deduplicate_events(events)
    if not events:
        return _empty_report()

    report_tz = get_report_timezone(events)
    logical_sessions = sessionize_events(events, merge_gap_seconds=merge_gap_seconds)
    if min_session_duration > 0:
        logical_sessions = [s for s in logical_sessions if float(s.get("duration_seconds", 0.0)) >= min_session_duration]
    if not logical_sessions:
        return _empty_report()

    total_seconds = 0.0
    browser_seconds = 0.0
    vscode_seconds = 0.0
    mobile_seconds = 0.0
    desktop_seconds = 0.0
    manual_seconds = 0.0

    # Collect all time intervals for wall-clock union calculation
    all_intervals = []
    screen_intervals = []

    source_counts = defaultdict(lambda: {"duration": 0.0, "count": 0})
    domain_stats = defaultdict(lambda: {"duration": 0.0, "count": 0})
    title_stats = defaultdict(lambda: {"duration": 0.0, "count": 0, "domain": ""})
    app_stats = defaultdict(lambda: {"duration": 0.0, "count": 0, "package": ""})
    desktop_app_stats = defaultdict(lambda: {"duration": 0.0, "count": 0})
    manual_activity_stats = defaultdict(lambda: {"duration": 0.0, "count": 0, "category": ""})
    workspace_stats = defaultdict(lambda: {
        "duration": 0.0,
        "count": 0,
        "languages": defaultdict(float),
        "files": set(),
    })
    language_stats = defaultdict(lambda: {"duration": 0.0, "count": 0})
    hourly = defaultdict(lambda: {"active": 0.0, "browser": 0.0, "vscode": 0.0, "mobile": 0.0, "desktop": 0.0, "manual": 0.0})

    timeline = []

    for s in logical_sessions:
        dur = float(s["duration_seconds"])
        source = s["source"]
        ctx = s.get("context", {})
        cleaned_ctx = clean_context_for_report(source, ctx)

        # Collect raw event intervals for wall-clock union (cross-device de-overlap without gap inflation)
        for raw_e in s["raw_events"]:
            all_intervals.append((raw_e["_start_dt"], raw_e["_end_dt"]))
            if source != "manual":
                screen_intervals.append((raw_e["_start_dt"], raw_e["_end_dt"]))

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
            lang = ctx.get("language", "unknown")
            f = ctx.get("file", "")

            workspace_stats[ws]["duration"] += dur
            workspace_stats[ws]["count"] += 1
            workspace_stats[ws]["languages"][lang] += dur
            if f:
                workspace_stats[ws]["files"].add(f)

            language_stats[lang]["duration"] += dur
            language_stats[lang]["count"] += 1

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
                hour_buckets = split_duration_by_hour(raw_start_local, raw_end_local)
                for h, secs in hour_buckets.items():
                    if source == "manual":
                        hourly[h]["manual"] += secs
                    else:
                        hourly[h]["active"] += secs
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

        # Timeline entry for logical session (clean, compact)
        timeline.append({
            "start": s["start_dt"].astimezone(report_tz).isoformat(),
            "end": s["end_dt"].astimezone(report_tz).isoformat(),
            "duration_seconds": round(dur, 1),
            "source": source,
            "context": cleaned_ctx,
            "raw_event_count": s["raw_event_count"],
        })

    # Summary metrics
    earliest_start = min(s["start_dt"] for s in logical_sessions)
    latest_end = max(s["end_dt"] for s in logical_sessions)

    # Compute total active time using interval union (prevents double-counting
    # when PC and mobile sessions overlap in time)
    screen_seconds = compute_union_seconds(screen_intervals) if screen_intervals else 0.0
    total_accounted_seconds = compute_union_seconds(all_intervals) if all_intervals else 0.0
    total_seconds = screen_seconds if screen_intervals or not all_intervals else total_accounted_seconds
    unobserved_seconds = max(0.0, 86400.0 - total_accounted_seconds)

    # Per-source seconds (naive sums — they represent time on that specific device)
    browser_seconds = source_counts.get("browser", {}).get("duration", 0.0)
    vscode_seconds = source_counts.get("vscode", {}).get("duration", 0.0)
    mobile_seconds = source_counts.get("mobile", {}).get("duration", 0.0)
    desktop_seconds = source_counts.get("desktop", {}).get("duration", 0.0)
    manual_seconds = source_counts.get("manual", {}).get("duration", 0.0)

    # Cap hourly active_seconds at 3600 (can't have more than 60 min in an hour)
    for h in hourly:
        hourly[h]["active"] = min(3600.0, hourly[h]["active"])
        hourly[h]["manual"] = min(3600.0, hourly[h]["manual"])
    observed_span_seconds = max(0.0, (latest_end - earliest_start).total_seconds())

    # Calculate actual logical context switches
    context_switches = 0
    for i in range(len(logical_sessions) - 1):
        if logical_sessions[i]["context_key"] != logical_sessions[i + 1]["context_key"]:
            context_switches += 1

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
                "languages": {k: round(v, 1) for k, v in st["languages"].items()},
                "files_touched": len(st["files"]),
            }
            for ws, st in workspace_stats.items()
        ],
        key=lambda x: x["duration_seconds"],
        reverse=True,
    )

    languages = sorted(
        [
            {
                "language": lang,
                "duration_seconds": round(st["duration"], 1),
                "session_count": st["count"],
            }
            for lang, st in language_stats.items()
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

    return {
        "summary": {
            "total_active_seconds": round(total_seconds, 1),
            "screen_seconds": round(screen_seconds, 1),
            "browser_seconds": round(browser_seconds, 1),
            "vscode_seconds": round(vscode_seconds, 1),
            "mobile_seconds": round(mobile_seconds, 1),
            "desktop_seconds": round(desktop_seconds, 1),
            "manual_seconds": round(manual_seconds, 1),
            "total_accounted_seconds": round(total_accounted_seconds, 1),
            "unobserved_seconds": round(unobserved_seconds, 1),
            "session_count": len(logical_sessions),
            "context_switches": context_switches,
            "first_activity": earliest_start.astimezone(report_tz).isoformat(),
            "last_activity": latest_end.astimezone(report_tz).isoformat(),
            "observed_span_seconds": round(observed_span_seconds, 1),
            "active_span_seconds": round(observed_span_seconds, 1),  # Backwards compatibility alias
        },
        "sources": sources,
        "domains": domains,
        "titles": titles,
        "workspaces": workspaces,
        "languages": languages,
        "apps": apps,
        "desktop_apps": desktop_apps,
        "manual_activities": manual_activities,
        "longest_sessions": longest_sessions,
        "timeline": timeline,
        "hourly_breakdown": hourly_breakdown,
    }


def _empty_report() -> Dict[str, Any]:
    """Return an empty report structure."""
    return {
        "summary": {
            "total_active_seconds": 0.0,
            "screen_seconds": 0.0,
            "browser_seconds": 0.0,
            "vscode_seconds": 0.0,
            "mobile_seconds": 0.0,
            "desktop_seconds": 0.0,
            "manual_seconds": 0.0,
            "total_accounted_seconds": 0.0,
            "unobserved_seconds": 86400.0,
            "session_count": 0,
            "context_switches": 0,
            "first_activity": None,
            "last_activity": None,
            "observed_span_seconds": 0.0,
            "active_span_seconds": 0.0,
        },
        "sources": {},
        "domains": [],
        "titles": [],
        "workspaces": [],
        "languages": [],
        "apps": [],
        "desktop_apps": [],
        "manual_activities": [],
        "longest_sessions": [],
        "timeline": [],
        "hourly_breakdown": [],
    }


def read_day_events(data_directory: str, date_str: str) -> List[Dict[str, Any]]:
    """Read events for a date from structured raw/YYYY/mmm/daily/YYYY-MM-DD.jsonl,
    with backward-compatible fallback to legacy raw/ locations, and merges
    manual offline activities from Record/manual/..."""
    events = []

    # 1. Check structured directory: raw/YYYY/mmm/daily/YYYY-MM-DD.jsonl
    try:
        d = date.fromisoformat(date_str)
        year = str(d.year)
        month = d.strftime("%b").lower()
        structured_file = Path(data_directory) / "raw" / year / month / "daily" / f"{date_str}.jsonl"
        if structured_file.exists():
            events.extend(read_events(str(structured_file)))
    except Exception:
        structured_file = None

    # 2. Check legacy paths for backward compatibility if structured file did not exist
    raw_dir = Path(data_directory) / "raw"
    if not events:
        legacy_pc_file = raw_dir / f"{date_str}.jsonl"
        if legacy_pc_file.exists():
            events.extend(read_events(str(legacy_pc_file)))

        legacy_mobile_file = raw_dir / "mobile" / f"{date_str}.jsonl"
        if legacy_mobile_file.exists():
            events.extend(read_events(str(legacy_mobile_file)))

        legacy_desktop_file = raw_dir / "desktop" / f"{date_str}.jsonl"
        if legacy_desktop_file.exists():
            events.extend(read_events(str(legacy_desktop_file)))

    # 3. Read manual offline activities from Record/manual/...
    try:
        from collector.manual_storage import read_manual_events
        manual_evts = read_manual_events(data_directory, date_str)
        if manual_evts:
            events.extend(manual_evts)
    except Exception:
        pass

    return events


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
    report = aggregate_events(events, merge_gap_seconds=merge_gap_seconds, min_session_duration=min_session_duration)
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
        day_report = aggregate_events(events, merge_gap_seconds=merge_gap_seconds, min_session_duration=min_session_duration)
        daily_summaries.append({
            "date": date_str,
            **day_report["summary"],
        })

        all_events.extend(events)
        current += timedelta(days=1)

    report = aggregate_events(all_events, merge_gap_seconds=merge_gap_seconds, min_session_duration=min_session_duration)
    report["generated_at"] = datetime.now().astimezone().isoformat()
    report["from"] = from_date
    report["to"] = to_date
    report["daily_summary"] = daily_summaries
    return report


def write_report(config, report: Dict[str, Any], filename: str) -> str:
    """Safely write JSON report to structured Record/report/YYYY/mmm/daily/ directory
    and mirror to Record/reports/ for backward compatibility.
    """
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

    # Backward compatibility mirror
    legacy_dir = Path(config.data_directory) / "reports"
    legacy_dir.mkdir(parents=True, exist_ok=True)
    legacy_path = legacy_dir / filename
    with open(legacy_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)

    return str(hierarchical_path if hierarchical_path else legacy_path)


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

    span = s.get("observed_span_seconds", 0)
    sh, sm = int(span // 3600), int((span % 3600) // 60)
    print(f"Observed span:         {sh}h {sm}m ({round(span, 1)}s)")

    print(f"Logical sessions:      {s.get('session_count', 0)}")
    print(f"Context switches:      {s.get('context_switches', 0)}")

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
            print(f"  {w['workspace']:30s} {wm}m {ws_sec:02d}s ({w['session_count']} sessions, {w['files_touched']} files)")

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
            name = ctx.get("title") or ctx.get("file") or ctx.get("app") or ctx.get("domain") or "unknown"
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
