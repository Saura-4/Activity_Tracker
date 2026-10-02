"""
Unobserved Gap Annotator & Manual Activity Logger

Finds unobserved gaps (where neither PC nor mobile was active) in daily timelines,
and allows the user to label them (e.g. Afternoon nap, Sleep, Dinner, Workout)
either interactively or via CLI arguments.
"""

import argparse
import sys
from pathlib import Path
from datetime import datetime, date, timedelta, timezone
from typing import List, Dict, Any, Tuple, Optional

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collector.config import get_config
from collector.manual_storage import (
    read_manual_events,
    save_manual_event,
    create_manual_event,
    infer_category,
    DEFAULT_TZ,
)
from reporting.generate_report import (
    read_day_events,
    get_report_timezone,
    parse_to_utc,
    sessionize_events,
    generate_single_day_report,
    write_report,
)
from reporting.generate_dashboard import generate_dashboard_files


def find_unobserved_gaps(
    events: List[Dict[str, Any]],
    target_date: str,
    tz: timezone,
    min_gap_seconds: float = 10 * 60,
    include_day_boundaries: bool = True,
) -> List[Dict[str, Any]]:
    """Scan day's events, merge active device & manual intervals, and return unobserved gaps."""
    d = date.fromisoformat(target_date)
    day_start_dt = datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=tz).astimezone(timezone.utc)
    day_end_dt = datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=tz).astimezone(timezone.utc)

    if not events:
        # Whole day is a gap
        dur = (day_end_dt - day_start_dt).total_seconds()
        return [{
            "start_dt": day_start_dt,
            "end_dt": day_end_dt,
            "duration_seconds": dur,
            "preceded_by": "Day start",
            "followed_by": "Day end",
        }]

    # Exclude idle, locked, sleep, and no_tracked_foreground status events from coverage
    active_events = []
    for ev in events:
        ctx = ev.get("context", {})
        status = (ctx.get("status") or "").lower()
        app = (ctx.get("app") or "").lower()
        if status in ("idle", "locked", "sleep", "no_tracked_foreground") or app in ("idle", "locked", "sleep", "no tracked foreground"):
            continue
        active_events.append(ev)

    # Build active intervals with context
    parsed_sessions = sessionize_events(active_events)
    if not parsed_sessions:
        return []

    # Flatten into intervals
    intervals = []
    for s in parsed_sessions:
        intervals.append({
            "start": s["start_dt"],
            "end": s["end_dt"],
            "source": s["source"],
            "context": s.get("context", {}),
        })

    intervals.sort(key=lambda x: (x["start"], x["end"]))

    # Sweep-line union
    merged = []
    for item in intervals:
        if not merged:
            merged.append(item)
            continue
        prev = merged[-1]
        if item["start"] <= prev["end"]:
            # Extend end
            if item["end"] > prev["end"]:
                prev["end"] = item["end"]
                # Keep latest context
                prev["followed_source"] = item["source"]
                prev["followed_context"] = item["context"]
        else:
            merged.append(item)

    gaps = []

    # 1. Day start boundary gap
    if include_day_boundaries and merged:
        first_act = merged[0]["start"]
        dur = (first_act - day_start_dt).total_seconds()
        if dur >= min_gap_seconds:
            gaps.append({
                "start_dt": day_start_dt,
                "end_dt": first_act,
                "duration_seconds": dur,
                "preceded_by": "Midnight (00:00)",
                "followed_by": _format_context_brief(merged[0]["source"], merged[0]["context"]),
            })

    # 2. Inter-activity gaps
    for i in range(len(merged) - 1):
        g_start = merged[i]["end"]
        g_end = merged[i + 1]["start"]
        dur = (g_end - g_start).total_seconds()
        if dur >= min_gap_seconds:
            gaps.append({
                "start_dt": g_start,
                "end_dt": g_end,
                "duration_seconds": dur,
                "preceded_by": _format_context_brief(
                    merged[i].get("followed_source", merged[i]["source"]),
                    merged[i].get("followed_context", merged[i]["context"]),
                ),
                "followed_by": _format_context_brief(merged[i + 1]["source"], merged[i + 1]["context"]),
            })

    # 3. Day end boundary gap
    if include_day_boundaries and merged:
        last_act = merged[-1]["end"]
        # If target date is today, cap end at current time
        now_utc = datetime.now(timezone.utc)
        boundary_end = min(day_end_dt, now_utc) if d == date.today() else day_end_dt
        dur = (boundary_end - last_act).total_seconds()
        if dur >= min_gap_seconds:
            gaps.append({
                "start_dt": last_act,
                "end_dt": boundary_end,
                "duration_seconds": dur,
                "preceded_by": _format_context_brief(
                    merged[-1].get("followed_source", merged[-1]["source"]),
                    merged[-1].get("followed_context", merged[-1]["context"]),
                ),
                "followed_by": "Current Time" if d == date.today() else "Midnight (24:00)",
            })

    return gaps


def _format_context_brief(source: str, ctx: Dict[str, Any]) -> str:
    """Format a session's source and title into a brief readable string."""
    if source == "browser":
        title = ctx.get("title") or ctx.get("domain") or "Web browsing"
        return f"Browser: {title[:32]}"
    elif source == "vscode":
        ws = ctx.get("workspace") or "Code editor"
        return f"VS Code: {ws[:32]}"
    elif source == "mobile":
        app = ctx.get("app") or ctx.get("package") or "Mobile phone"
        return f"Mobile: {app[:32]}"
    elif source == "desktop":
        app = ctx.get("app") or "Desktop"
        title = ctx.get("title", "")
        return f"Desktop: {app} ({title[:25]})" if title else f"Desktop: {app}"
    elif source == "manual":
        act = ctx.get("activity") or ctx.get("title") or "Offline"
        return f"Manual: {act}"
    return source


def format_duration(seconds: float) -> str:
    s = int(seconds)
    hours = s // 3600
    minutes = (s % 3600) // 60
    if hours > 0:
        return f"{hours}h {minutes:02d}m"
    return f"{minutes}m"


def main():
    parser = argparse.ArgumentParser(description="Find and annotate unobserved offline gaps in activity timeline.")
    parser.add_argument("--date", help="Date in YYYY-MM-DD (default: today)")
    parser.add_argument("--min-gap", type=int, default=10, help="Minimum gap in minutes to prompt for (default: 10)")
    parser.add_argument("--list", action="store_true", help="List unobserved gaps without prompting")
    parser.add_argument("--add", help="Add manual event via shorthand time e.g. '13:00-15:00'")
    parser.add_argument("--activity", help="Activity name when using --add (e.g. 'Afternoon nap')")
    parser.add_argument("--category", help="Category when using --add (e.g. 'rest', 'meal', 'fitness')")
    parser.add_argument("--notes", default="", help="Optional notes")
    parser.add_argument("--no-report", action="store_true", help="Skip regenerating report and dashboard")
    args = parser.parse_args()

    config = get_config()
    target_date = args.date or datetime.now().strftime("%Y-%m-%d")

    # Non-interactive CLI addition
    if args.add:
        if not args.activity:
            print("Error: --activity is required when using --add", file=sys.stderr)
            sys.exit(1)
        times = [t.strip() for t in args.add.replace("to", "-").split("-")]
        if len(times) != 2:
            print("Error: --add format should be 'START-END' (e.g. '13:00-15:00')", file=sys.stderr)
            sys.exit(1)

        evt = create_manual_event(
            date_str=target_date,
            start_time=times[0],
            end_time=times[1],
            activity=args.activity,
            category=args.category,
            notes=args.notes,
        )
        saved_file = save_manual_event(config.data_directory, target_date, evt)
        print(f"Logged manual event: {args.activity} ({times[0]} - {times[1]}, {format_duration(evt['duration_seconds'])})")
        print(f"Saved to: {saved_file}")

        if not args.no_report:
            print("Regenerating report and dashboard...")
            rep = generate_single_day_report(config, target_date)
            write_report(config, rep, f"{target_date}.json")
            generate_dashboard_files(config.data_directory)
            print("Done!")
        return

    # Load existing events and gaps
    events = read_day_events(config.data_directory, target_date)
    report_tz = get_report_timezone(events) or DEFAULT_TZ
    existing_manual = read_manual_events(config.data_directory, target_date, tz=report_tz)

    gaps = find_unobserved_gaps(
        events=events,
        target_date=target_date,
        tz=report_tz,
        min_gap_seconds=args.min_gap * 60,
    )

    print("\n" + "=" * 65)
    print(f"UNOBSERVED TIMELINE DETECTOR — {target_date}")
    print("=" * 65)

    if existing_manual:
        print(f"\nExisting manual annotations ({len(existing_manual)}):")
        for me in existing_manual:
            s_loc = datetime.fromisoformat(me["start"]).astimezone(report_tz).strftime("%H:%M")
            e_loc = datetime.fromisoformat(me["end"]).astimezone(report_tz).strftime("%H:%M")
            act = me["context"].get("activity", "Offline")
            cat = me["context"].get("category", "")
            dur_str = format_duration(me["duration_seconds"])
            print(f"  • {s_loc} - {e_loc} ({dur_str}): {act} [{cat}]")

    if not gaps:
        print(f"\nNo unobserved gaps >= {args.min_gap} minutes found for {target_date}.")
        return

    print(f"\nFound {len(gaps)} unobserved gap(s) >= {args.min_gap} minutes:\n")

    if args.list:
        for i, g in enumerate(gaps, 1):
            s_str = g["start_dt"].astimezone(report_tz).strftime("%H:%M")
            e_str = g["end_dt"].astimezone(report_tz).strftime("%H:%M")
            dur_str = format_duration(g["duration_seconds"])
            print(f"[{i}] {s_str} - {e_str} ({dur_str})")
            print(f"    Between: {g['preceded_by']}  ->  {g['followed_by']}")
        return

    # Interactive Annotation
    added_count = 0
    for i, g in enumerate(gaps, 1):
        s_str = g["start_dt"].astimezone(report_tz).strftime("%H:%M")
        e_str = g["end_dt"].astimezone(report_tz).strftime("%H:%M")
        dur_str = format_duration(g["duration_seconds"])

        print("-" * 65)
        print(f"Gap {i}/{len(gaps)}: {s_str} – {e_str}  ({dur_str})")
        print(f"  • Prior activity: {g['preceded_by']}")
        print(f"  • Next activity:  {g['followed_by']}")

        # Auto-suggest if night time
        sh = g["start_dt"].astimezone(report_tz).hour
        default_suggestion = "Sleep" if (sh >= 23 or sh < 6) and g["duration_seconds"] >= 4 * 3600 else ""
        if default_suggestion:
            prompt_str = f"  Label [default: {default_suggestion}] (Enter=skip, q=quit): "
        else:
            prompt_str = "  Label (e.g. 'Afternoon nap', 'Dinner') (Enter=skip, q=quit): "

        try:
            choice = input(prompt_str).strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting.")
            break

        if choice.lower() == "q":
            break

        if not choice:
            if default_suggestion:
                choice = default_suggestion
            else:
                continue

        # Optional category or custom time refinement
        activity_name = choice
        cat = infer_category(activity_name)

        evt = create_manual_event(
            date_str=target_date,
            start_time=s_str,
            end_time=e_str,
            activity=activity_name,
            category=cat,
            tz=report_tz,
        )
        save_manual_event(config.data_directory, target_date, evt)
        added_count += 1
        print(f"  ✓ Saved '{activity_name}' [{cat}]")

    print("\n" + "=" * 65)
    print(f"Saved {added_count} new offline annotation(s).")

    if added_count > 0 and not args.no_report:
        print("\nUpdating activity report and dashboard...")
        rep = generate_single_day_report(config, target_date)
        write_report(config, rep, f"{target_date}.json")
        generate_dashboard_files(config.data_directory)
        print("Report and dashboard successfully updated!")
    print("=" * 65)


if __name__ == "__main__":
    main()
