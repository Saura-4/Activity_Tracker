#!/usr/bin/env python3
"""Generate a synthetic dataset demonstrating Range A vs Range B comparison.

Range B shifts sleep bedtime and wake time by ~2 hours later.
Verifies and prints the comparison table and difference strip.
"""

import sys
from datetime import date, timedelta
from pathlib import Path

# Ensure repo root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from reporting.typical_day import (
    compute_day_bins_cache,
    rotate_and_aggregate_bins,
    compute_difference_strip,
    compute_comparison_metrics,
    seconds_to_time_str,
)


def create_synthetic_day(date_str: str, bedtime_str: str, wake_str: str, work_start_str: str, work_end_str: str, leisure_start_str: str, leisure_end_str: str, is_shifted: bool = False):
    """Create a synthetic daily report with realistic sessions, sleep, and labels."""
    def to_iso(t_str, next_day=False):
        d = date_str
        if next_day:
            d = (date.fromisoformat(date_str) + timedelta(days=1)).isoformat()
        return f"{d}T{t_str}:00+05:30"

    # Sleep metrics
    # If bedtime is 01:30 or 03:30, it is on date_str
    # wake is on date_str morning
    # For daily_metrics.sleep: bedtime is morning of date_str, wake is morning of date_str
    b_hour = int(bedtime_str.split(":")[0])
    w_hour = int(wake_str.split(":")[0])
    b_min = int(bedtime_str.split(":")[1])
    w_min = int(wake_str.split(":")[1])

    b_secs = b_hour * 3600 + b_min * 60
    w_secs = w_hour * 3600 + w_min * 60
    sleep_dur = (w_secs - b_secs + 86400) % 86400

    timeline = [
        # Work block (PC, build/learn)
        {
            "start": to_iso(work_start_str),
            "end": to_iso(work_end_str),
            "duration_seconds": 3.0 * 3600.0,
            "source": "browser",
            "label": "build",
            "context": {"domain": "github.com"},
        },
        # Leisure block (PC & Mobile)
        {
            "start": to_iso(leisure_start_str),
            "end": to_iso(leisure_end_str),
            "duration_seconds": 2.5 * 3600.0,
            "source": "mobile",
            "label": "leisure",
            "context": {"app": "Twitter / X", "package": "com.twitter.android"},
        },
    ]

    total_screen = 5.5 * 3600.0
    late_night = 3600.0 if is_shifted else 0.0

    return {
        "date": date_str,
        "summary": {
            "session_count": 25,
            "total_active_seconds": total_screen,
            "pc_active_seconds": 3.0 * 3600.0,
            "mobile_seconds": 2.5 * 3600.0,
            "total_accounted_seconds": total_screen + sleep_dur,
            "first_activity": to_iso(work_start_str),
            "last_activity": to_iso(leisure_end_str),
        },
        "daily_metrics": {
            "first_activity": to_iso(work_start_str),
            "last_activity": to_iso(leisure_end_str),
            "active_seconds": total_screen,
            "pc_seconds": 3.0 * 3600.0,
            "mobile_seconds": 2.5 * 3600.0,
            "phone_share": 0.455,
            "late_night_screen_seconds": late_night,
            "sleep": {
                "status": "ok",
                "bedtime": to_iso(bedtime_str),
                "wake_time": to_iso(wake_str),
                "duration_seconds": sleep_dur,
                "source": "inferred",
            },
        },
        "timeline": timeline,
    }


def generate_demo_dataset():
    # 7 days Range A (baseline): Bedtime 01:30, Wake 08:30
    # 7 days Range B (shifted ~2h later): Bedtime 03:30, Wake 10:30
    reports = {}
    cached_a = []
    cached_b = []

    # Range A: 2026-09-01 to 2026-09-07
    start_a = date(2026, 9, 1)
    for i in range(7):
        d_str = (start_a + timedelta(days=i)).isoformat()
        # Slight jitter (+/- 10 min)
        min_offset = (i % 3 - 1) * 10
        b_min = 30 + min_offset
        w_min = 30 + min_offset
        b_str = f"01:{b_min:02d}"
        w_str = f"08:{w_min:02d}"
        rep = create_synthetic_day(
            d_str,
            bedtime_str=b_str,
            wake_str=w_str,
            work_start_str="13:30",
            work_end_str="16:30",
            leisure_start_str="20:30",
            leisure_end_str="23:00",
            is_shifted=False,
        )
        reports[d_str] = rep
        cached_a.append(compute_day_bins_cache(rep, bin_minutes=15))

    # Range B: 2026-09-08 to 2026-09-14 (Shifted by 2 hours)
    start_b = date(2026, 9, 8)
    for i in range(7):
        d_str = (start_b + timedelta(days=i)).isoformat()
        min_offset = (i % 3 - 1) * 10
        b_min = 30 + min_offset
        w_min = 30 + min_offset
        b_str = f"03:{b_min:02d}"
        w_str = f"10:{w_min:02d}"
        rep = create_synthetic_day(
            d_str,
            bedtime_str=b_str,
            wake_str=w_str,
            work_start_str="15:30",
            work_end_str="18:30",
            leisure_start_str="22:30",
            leisure_end_str="01:00",
            is_shifted=True,
        )
        reports[d_str] = rep
        cached_b.append(compute_day_bins_cache(rep, bin_minutes=15))

    return reports, cached_a, cached_b


def main():
    print("==================================================")
    print("TYPICAL DAY SYNTHETIC DEMO: RANGE A vs RANGE B (~2h SLEEP SHIFT)")
    print("==================================================")

    reports, cached_a, cached_b = generate_demo_dataset()
    print(f"Generated {len(cached_a)} baseline days in Range A (2026-09-01 to 2026-09-07)")
    print(f"Generated {len(cached_b)} shifted days in Range B (2026-09-08 to 2026-09-14)")

    # Aggregate and compute comparison metrics (axis starting at 18:00 to keep night contiguous)
    metrics = compute_comparison_metrics(
        reports,
        cached_a,
        cached_b,
        bin_minutes=15,
        axis_start_hour=18,
    )

    print("\n--- COMPARISON TABLE ---")
    print(f"  {'Metric':<26} | {'Range A':<12} | {'Range B':<12} | {'Delta'}")
    print(f"  {'-'*26}-|-{'-'*12}-|-{'-'*12}-|------------------")
    for r in metrics["comparison_table"]:
        print(f"  {r['metric']:<26} | {r['range_a']:<12} | {r['range_b']:<12} | {r['delta']}")

    # Verify key assertions
    bt_row = next(r for r in metrics["comparison_table"] if r["metric"] == "Median Bedtime")
    wt_row = next(r for r in metrics["comparison_table"] if r["metric"] == "Median Wake Time")
    
    print("\n--- VERIFICATION CHECKS ---")
    print(f"  Bedtime delta:   '{bt_row['delta']}'")
    print(f"  Wake time delta: '{wt_row['delta']}'")

    assert "later" in bt_row["delta"], f"Expected 'later' in bedtime delta, got: {bt_row['delta']}"
    assert "2h" in bt_row["delta"], f"Expected ~2h in bedtime delta, got: {bt_row['delta']}"
    assert "later" in wt_row["delta"], f"Expected 'later' in wake delta, got: {wt_row['delta']}"
    assert "2h" in wt_row["delta"], f"Expected ~2h in wake delta, got: {wt_row['delta']}"
    print("  [PASS] Bedtime and wake time properly shift ~+2h later with plain-word shifts.")

    # Sleep difference strip
    agg_a = rotate_and_aggregate_bins(cached_a, bin_minutes=15, axis_start_hour=18)
    agg_b = rotate_and_aggregate_bins(cached_b, bin_minutes=15, axis_start_hour=18)
    diff_sleep = compute_difference_strip(agg_a, agg_b, layer="sleep")

    print("\n--- SLEEP DIFFERENCE STRIP (B minus A) SAMPLES ---")
    # Axis starts at 18:00.
    # 02:00 is 8 hours after 18:00 (bin 32). In Range A, asleep. In Range B, awake. diff should be negative!
    # 09:30 is 15.5 hours after 18:00 (bin 62). In Range A, awake. In Range B, asleep. diff should be positive!
    bin_0200 = 8 * 4  # bin 32
    bin_0930 = int(15.5 * 4)  # bin 62
    print(f"  Bin 02:00 (Range B awake, Range A asleep): Diff = {diff_sleep[bin_0200]}% (Expected negative)")
    print(f"  Bin 09:30 (Range B asleep, Range A awake):  Diff = +{diff_sleep[bin_0930]}% (Expected positive)")

    assert diff_sleep[bin_0200] <= -50.0, f"Expected strong negative diff at 02:00, got {diff_sleep[bin_0200]}"
    assert diff_sleep[bin_0930] >= 50.0, f"Expected strong positive diff at 09:30, got {diff_sleep[bin_0930]}"
    print("  [PASS] Sleep difference strip clearly highlights shifted sleep window!")

    print("\n==================================================")
    print("ALL CHECKS PASSED SUCCESSFULLY!")
    print("==================================================")


if __name__ == "__main__":
    main()
