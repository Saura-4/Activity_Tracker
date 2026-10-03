#!/usr/bin/env python3
"""Diagnostic tool to inspect raw browser values and per-app mobile totals for a given day."""

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Dict, Any, List

# Ensure repo root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from collector.config import get_config
from reporting.generate_report import read_day_events


def format_duration(seconds: float) -> str:
    """Format seconds into HH:MM:SS or MM:SS."""
    secs = int(round(seconds))
    h = secs // 3600
    m = (secs % 3600) // 60
    s = secs % 60
    if h > 0:
        return f"{h}h {m:02d}m {s:02d}s"
    elif m > 0:
        return f"{m}m {s:02d}s"
    else:
        return f"{s}s"


def diagnose_day(date_str: str, data_dir: str):
    print(f"\n==================================================")
    print(f"DIAGNOSTIC REPORT FOR: {date_str}")
    print(f"Data directory: {data_dir}")
    print(f"==================================================")

    # 1. Read events using standard reader (includes previous day boundary events and mobile)
    events = read_day_events(data_dir, date_str)
    print(f"Total raw events loaded for {date_str} (clipped to day): {len(events)}")

    # (a) Distinct browser values seen in raw browser events
    browser_events = [e for e in events if e.get("source") == "browser"]
    print(f"\n--- (a) BROWSER EVENTS (Total count: {len(browser_events)}) ---")

    browser_values: Dict[str, Dict[str, Any]] = {}
    for e in browser_events:
        ctx = e.get("context", {})
        # Check both ctx.browser and top-level browser if any
        b_val = ctx.get("browser") or e.get("browser") or "<unspecified>"
        if b_val not in browser_values:
            browser_values[b_val] = {
                "count": 0,
                "total_seconds": 0.0,
                "domains": set(),
                "profiles": set(),
            }
        browser_values[b_val]["count"] += 1
        browser_values[b_val]["total_seconds"] += float(e.get("duration_seconds", 0.0))
        if ctx.get("domain"):
            browser_values[b_val]["domains"].add(ctx.get("domain"))
        if ctx.get("profile"):
            browser_values[b_val]["profiles"].add(ctx.get("profile"))

    if not browser_values:
        print("  No browser events found for this day.")
    else:
        print(f"  Distinct browser values found: {len(browser_values)}")
        for b_name, stats in sorted(browser_values.items(), key=lambda x: x[1]["total_seconds"], reverse=True):
            profiles_str = ", ".join(sorted(stats["profiles"])) if stats["profiles"] else "none"
            top_domains = list(stats["domains"])[:5]
            domains_str = ", ".join(top_domains) + ("..." if len(stats["domains"]) > 5 else "")
            print(f"  * Browser: '{b_name}'")
            print(f"      Sessions: {stats['count']}")
            print(f"      Total Duration: {format_duration(stats['total_seconds'])} ({stats['total_seconds']:.1f}s)")
            print(f"      Profiles: {profiles_str}")
            print(f"      Sample Domains: {domains_str or 'none'}")

    # (b) Per-app mobile totals
    mobile_events = [e for e in events if e.get("source") == "mobile"]
    print(f"\n--- (b) PER-APP MOBILE TOTALS (Total count: {len(mobile_events)}) ---")

    app_totals: Dict[str, Dict[str, Any]] = {}
    for e in mobile_events:
        ctx = e.get("context", {})
        app_name = ctx.get("app") or "Unknown"
        pkg = ctx.get("package") or "unknown.package"
        dur = float(e.get("duration_seconds", 0.0))
        key = (app_name, pkg)
        if key not in app_totals:
            app_totals[key] = {
                "app": app_name,
                "package": pkg,
                "count": 0,
                "total_seconds": 0.0,
            }
        app_totals[key]["count"] += 1
        app_totals[key]["total_seconds"] += dur

    if not app_totals:
        print("  No mobile events found for this day.")
    else:
        sorted_apps = sorted(app_totals.values(), key=lambda x: x["total_seconds"], reverse=True)
        total_mobile_sec = sum(a["total_seconds"] for a in sorted_apps)
        print(f"  Total mobile screen time: {format_duration(total_mobile_sec)} ({total_mobile_sec:.1f}s)")
        print(f"  {'App Name':<28} | {'Package':<35} | {'Sessions':<8} | {'Total Time':<12} | {'Seconds'}")
        print(f"  {'-'*28}-|-{'-'*35}-|-{'-'*8}-|-{'-'*12}-|--------")
        for a in sorted_apps:
            print(f"  {a['app']:<28} | {a['package']:<35} | {a['count']:<8} | {format_duration(a['total_seconds']):<12} | {a['total_seconds']:.1f}s")

    print(f"==================================================\n")


def main():
    parser = argparse.ArgumentParser(description="Diagnose raw browser contexts and mobile per-app totals.")
    parser.add_argument("--date", type=str, default=None, help="Target date YYYY-MM-DD (defaults to today)")
    parser.add_argument("--data-dir", type=str, default=None, help="ActivityTracker data directory (default: from config)")
    args = parser.parse_args()

    cfg = get_config()
    data_dir = args.data_dir or cfg.data_directory
    target_date = args.date or date.today().isoformat()

    diagnose_day(target_date, data_dir)


if __name__ == "__main__":
    main()
