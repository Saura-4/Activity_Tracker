"""Unit tests for Typical Day math, circular statistics, axis wrapping, and range comparisons."""

import pytest
from datetime import datetime, timezone, timedelta
from reporting.typical_day import (
    evaluate_day_inclusion,
    filter_included_days,
    time_str_to_seconds,
    seconds_to_time_str,
    circular_mean_and_median_seconds,
    format_delta_time,
    project_interval_to_bins,
    compute_day_bins_cache,
    rotate_and_aggregate_bins,
    compute_difference_strip,
    find_peak_1h_window,
    compute_comparison_metrics,
    find_top_contiguous_windows,
    aggregate_focus_vs_drift,
    compute_focus_drift_comparison,
)


class TestDayInclusion:
    def test_day_inclusion_criteria(self):
        """Days with 0 sessions or <30m accounted time are excluded; offline days flagged."""
        # Case 1: 0 sessions
        r1 = {"summary": {"session_count": 0, "total_accounted_seconds": 0.0}}
        res1 = evaluate_day_inclusion(r1)
        assert not res1["included"]
        assert "No sessions" in res1["reason"]

        # Case 2: < 30m (1200s = 20m)
        r2 = {"summary": {"session_count": 5, "total_accounted_seconds": 1200.0}}
        res2 = evaluate_day_inclusion(r2)
        assert not res2["included"]
        assert "below 30m" in res2["reason"]

        # Case 3: Adequate coverage (3600s = 60m)
        r3 = {"summary": {"session_count": 12, "total_accounted_seconds": 3600.0}}
        res3 = evaluate_day_inclusion(r3)
        assert res3["included"]
        assert not res3["offline_flag"]

        # Case 4: Adequate coverage but watcher offline for most of the day
        r4 = {
            "summary": {"session_count": 8, "total_accounted_seconds": 4000.0},
            "data_quality": {"watcher_offline_seconds": 70000.0},
        }
        res4 = evaluate_day_inclusion(r4)
        assert res4["included"]
        assert res4["offline_flag"]

    def test_filter_included_days_weekdays_and_weekends(self):
        """Weekday and weekend filters correctly segment dates."""
        reports = {
            "2026-10-02": {"summary": {"session_count": 10, "total_accounted_seconds": 3600.0}},  # Friday
            "2026-10-03": {"summary": {"session_count": 10, "total_accounted_seconds": 3600.0}},  # Saturday
            "2026-10-04": {"summary": {"session_count": 10, "total_accounted_seconds": 3600.0}},  # Sunday
        }
        dates = ["2026-10-02", "2026-10-03", "2026-10-04"]

        all_inc, _ = filter_included_days(reports, dates, "all")
        assert all_inc == ["2026-10-02", "2026-10-03", "2026-10-04"]

        wd_inc, _ = filter_included_days(reports, dates, "weekdays")
        assert wd_inc == ["2026-10-02"]

        we_inc, _ = filter_included_days(reports, dates, "weekends")
        assert we_inc == ["2026-10-03", "2026-10-04"]


class TestWrapAwareCircularMath:
    def test_time_conversions(self):
        """Parsing time strings to seconds and formatting back."""
        assert time_str_to_seconds("00:00:00") == 0.0
        assert time_str_to_seconds("01:30:00") == 5400.0
        assert time_str_to_seconds("23:45:00") == 85500.0
        assert seconds_to_time_str(5400.0) == "01:30"
        assert seconds_to_time_str(85500.0) == "23:45"

    def test_circular_median_across_midnight(self):
        """Times cluster around midnight: 23:30, 23:45, 00:15, 00:30, 01:00."""
        # In linear arithmetic, naive average would be ~11:00 AM (disaster!).
        # Circular median should be 00:15 (900 seconds from midnight).
        times = [
            time_str_to_seconds("23:30"),  # -30m
            time_str_to_seconds("23:45"),  # -15m
            time_str_to_seconds("00:15"),  # +15m
            time_str_to_seconds("00:30"),  # +30m
            time_str_to_seconds("01:00"),  # +60m
        ]
        mean_s, med_s, iqr_s = circular_mean_and_median_seconds(times)
        assert med_s is not None
        # Median must be around 00:15 (900s) +/- 60s
        assert abs(med_s - 900.0) < 60.0
        # IQR is between Q3 (~00:30) and Q1 (~23:45) = ~45m = 2700s
        assert abs(iqr_s - 2700.0) < 300.0

    def test_plain_word_delta_formatting(self):
        """Deltas format with plain words like '+1h 30m later' or '-45m earlier'."""
        # Later bedtime
        t_a = time_str_to_seconds("01:30")
        t_b = time_str_to_seconds("03:00")
        assert format_delta_time(t_a, t_b, is_time_of_day=True) == "+1h 30m later"

        # Earlier bedtime across midnight: from 01:00 to 23:30
        t_a2 = time_str_to_seconds("01:00")
        t_b2 = time_str_to_seconds("23:30")
        assert format_delta_time(t_a2, t_b2, is_time_of_day=True) == "-1h 30m earlier"

        # Duration delta
        d_a = 7.0 * 3600.0
        d_b = 8.5 * 3600.0
        assert format_delta_time(d_a, d_b, is_time_of_day=False) == "+1h 30m"


class TestAxisProjectionAndBins:
    def test_interval_projection_onto_axis(self):
        """Interval from 23:30 to 07:00 when axis starts at 18:00 forms contiguous block."""
        s = time_str_to_seconds("23:30")
        dur = 7.5 * 3600.0  # ends at 07:00 next day
        # 15 min bins, axis starts at 18:00 (hour 18)
        overlaps = project_interval_to_bins(s, s + dur, bin_minutes=15, axis_start_hour=18)
        assert len(overlaps) == 96

        # When axis starts at 18:00:
        # 18:00 is bin 0.
        # 23:30 is 5.5 hours after 18:00 -> bin 5.5 * 4 = 22.
        # 07:00 is 13 hours after 18:00 -> bin 13.0 * 4 = 52.
        # So bins 22 through 51 should have overlap > 0!
        assert overlaps[21] == 0.0
        assert overlaps[22] == 900.0  # 23:30 to 23:45 is full 15m = 900s
        assert overlaps[23] == 900.0
        assert overlaps[51] == 900.0
        assert overlaps[52] == 0.0  # 07:00 ends at start of bin 52

        # Crucially, bins before 22 and after 52 are 0 (it did NOT split across 00:00 midnight!)
        assert sum(overlaps[:22]) == 0.0
        assert sum(overlaps[52:]) == 0.0
        assert abs(sum(overlaps) - dur) < 1.0

    def test_compute_difference_strip(self):
        """Difference strip computes B minus A accurately."""
        agg_a = {
            "n_days": 7,
            "total_bins": 4,
            "activity": {"pct": [10.0, 50.0, 80.0, 20.0]},
        }
        agg_b = {
            "n_days": 7,
            "total_bins": 4,
            "activity": {"pct": [20.0, 40.0, 80.0, 50.0]},
        }
        diff = compute_difference_strip(agg_a, agg_b, layer="activity")
        assert diff == [10.0, -10.0, 0.0, 30.0]

    def test_peak_1h_window(self):
        """Peak 1-hour window locates the maximal rolling sum."""
        # 15 min bins = 96 bins. Axis start 00:00.
        vals = [0.0] * 96
        # Spike at 14:00 (bins 56, 57, 58, 59)
        vals[56] = 15.0
        vals[57] = 15.0
        vals[58] = 15.0
        vals[59] = 15.0
        win_str, best_sum = find_peak_1h_window(vals, bin_minutes=15, axis_start_hour=0)
        assert win_str == "14:00 - 15:00"
        assert best_sum == 60.0


class TestFocusVsDrift:
    def test_find_top_contiguous_windows(self):
        """Top contiguous windows (>=1h) with highest average are found and masked without overlap."""
        # 96 bins (15 min each), axis starts at 00:00
        vals = [0.0] * 96

        # Window 1: 09:00 to 11:00 (bins 36 to 43, 8 bins = 2 hours)
        # 12 minutes per 15-minute bin = 48 m/h average rate
        for b in range(36, 44):
            vals[b] = 12.0

        # Window 2: 14:00 to 15:00 (bins 56 to 59, 4 bins = 1 hour)
        # 10 minutes per bin = 40 m/h average rate
        for b in range(56, 60):
            vals[b] = 10.0

        windows = find_top_contiguous_windows(vals, bin_minutes=15, axis_start_hour=0, top_k=3, min_window_hours=1.0)
        assert len(windows) == 2
        # First window is the 2-hour morning block
        assert windows[0]["start_time"] == "09:00"
        assert windows[0]["end_time"] == "11:00"
        assert windows[0]["duration_hours"] == 2.0
        assert windows[0]["avg_minutes_per_hour"] == 48.0
        assert "09:00 - 11:00 (48m/h)" in windows[0]["display"]

        # Second window is the afternoon 1-hour block
        assert windows[1]["start_time"] == "14:00"
        assert windows[1]["end_time"] == "15:00"
        assert windows[1]["duration_hours"] == 1.0
        assert windows[1]["avg_minutes_per_hour"] == 40.0
        assert "14:00 - 15:00 (40m/h)" in windows[1]["display"]

    def test_focus_vs_drift_coverage_threshold(self):
        """Only days meeting min_coverage_pct (default 60%) count; qualified days count reported."""
        day_qualified = {
            "date": "2026-10-01",
            "coverage_pct": 75.0,
            "screen_seconds": [900.0] * 96,
            "label_seconds": {"build": [600.0] * 96, "leisure": [0.0] * 96},
            "planned_label_seconds": {},
            "unplanned_label_seconds": {},
        }
        day_disqualified = {
            "date": "2026-10-02",
            "coverage_pct": 45.0,  # Below 60%
            "screen_seconds": [900.0] * 96,
            "label_seconds": {"build": [300.0] * 96, "leisure": [0.0] * 96},
            "planned_label_seconds": {},
            "unplanned_label_seconds": {},
        }

        # Threshold 60% -> only 1 qualifies
        res60 = aggregate_focus_vs_drift([day_qualified, day_disqualified], min_coverage_pct=60.0)
        assert res60["n_days"] == 1
        assert res60["qualified_days_count"] == 1
        assert res60["total_days"] == 2

        # Threshold adjusted down to 40% -> both qualify
        res40 = aggregate_focus_vs_drift([day_qualified, day_disqualified], min_coverage_pct=40.0)
        assert res40["n_days"] == 2
        assert res40["qualified_days_count"] == 2
        assert res40["total_days"] == 2

    def test_focus_vs_drift_unplanned_only_vs_all_leisure(self):
        """Unplanned-only toggle treats planned leisure as neutral; all leisure treats both as drift."""
        # Setup day with:
        # - Focus: build (900s in bin 10)
        # - Planned leisure: 900s in bin 20
        # - Unplanned leisure: 900s in bin 30
        day = {
            "date": "2026-10-01",
            "coverage_pct": 100.0,
            "screen_seconds": [0.0] * 96,
            "label_seconds": {
                "build": [0.0] * 96,
                "practice": [0.0] * 96,
                "learn": [0.0] * 96,
                "leisure": [0.0] * 96,
                "stay-current": [0.0] * 96,
                "career": [0.0] * 96,
                "comms": [0.0] * 96,
                "other": [0.0] * 96,
            },
            "planned_label_seconds": {
                "leisure": [0.0] * 96,
            },
            "unplanned_label_seconds": {
                "leisure": [0.0] * 96,
            },
        }
        day["screen_seconds"][10] = 900.0
        day["screen_seconds"][20] = 900.0
        day["screen_seconds"][30] = 900.0

        day["label_seconds"]["build"][10] = 900.0
        day["label_seconds"]["leisure"][20] = 900.0
        day["planned_label_seconds"]["leisure"][20] = 900.0
        day["label_seconds"]["leisure"][30] = 900.0
        day["unplanned_label_seconds"]["leisure"][30] = 900.0

        # 1. Unplanned only = True (default)
        agg_unplanned = aggregate_focus_vs_drift([day], min_coverage_pct=60.0, unplanned_only=True)
        # Focus is 15 min at bin 10
        assert agg_unplanned["avg_focus_minutes"][10] == 15.0
        # Planned leisure at bin 20 is neutral, NOT drift
        assert agg_unplanned["avg_drift_minutes"][20] == 0.0
        assert agg_unplanned["avg_neutral_minutes"][20] == 15.0
        # Unplanned leisure at bin 30 IS drift
        assert agg_unplanned["avg_drift_minutes"][30] == 15.0
        # Total drift hours = 0.25h (15m)
        assert agg_unplanned["avg_drift_hours"] == 0.25

        # 2. Unplanned only = False (All leisure)
        agg_all = aggregate_focus_vs_drift([day], min_coverage_pct=60.0, unplanned_only=False)
        # Focus remains identical
        assert agg_all["avg_focus_minutes"][10] == 15.0
        # Both bins 20 and 30 are now drift!
        assert agg_all["avg_drift_minutes"][20] == 15.0
        assert agg_all["avg_drift_minutes"][30] == 15.0
        assert agg_all["avg_neutral_minutes"][20] == 0.0
        # Total drift hours = 0.5h (30m)
        assert agg_all["avg_drift_hours"] == 0.5

    def test_focus_vs_drift_comparison_table_and_deltas(self):
        """Dual range comparison computes delta strips and formatted summary table."""
        day_a = {
            "date": "2026-10-01",
            "coverage_pct": 80.0,
            "screen_seconds": [0.0] * 96,
            "label_seconds": {
                "build": [0.0] * 96, "practice": [0.0] * 96, "learn": [0.0] * 96,
                "leisure": [0.0] * 96, "stay-current": [0.0] * 96, "career": [0.0] * 96,
                "comms": [0.0] * 96, "other": [0.0] * 96,
            },
            "planned_label_seconds": {"leisure": [0.0] * 96},
            "unplanned_label_seconds": {"leisure": [0.0] * 96},
        }
        # A: 2h focus (bins 36-43)
        for b in range(36, 44):
            day_a["screen_seconds"][b] = 900.0
            day_a["label_seconds"]["build"][b] = 900.0

        day_b = {
            "date": "2026-10-02",
            "coverage_pct": 90.0,
            "screen_seconds": [0.0] * 96,
            "label_seconds": {
                "build": [0.0] * 96, "practice": [0.0] * 96, "learn": [0.0] * 96,
                "leisure": [0.0] * 96, "stay-current": [0.0] * 96, "career": [0.0] * 96,
                "comms": [0.0] * 96, "other": [0.0] * 96,
            },
            "planned_label_seconds": {"leisure": [0.0] * 96},
            "unplanned_label_seconds": {"leisure": [0.0] * 96},
        }
        # B: 3h focus (bins 36-47)
        for b in range(36, 48):
            day_b["screen_seconds"][b] = 900.0
            day_b["label_seconds"]["build"][b] = 900.0

        agg_a = aggregate_focus_vs_drift([day_a], min_coverage_pct=60.0)
        agg_b = aggregate_focus_vs_drift([day_b], min_coverage_pct=60.0)

        comp = compute_focus_drift_comparison(agg_a, agg_b)
        assert len(comp["delta_focus_minutes"]) == 96
        # At bin 45 (11:15), A has 0m focus, B has 15m focus -> delta is +15.0m
        assert comp["delta_focus_minutes"][45] == 15.0

        table_rows = comp["comparison_table"]
        metric_map = {r["metric"]: r for r in table_rows}
        assert "Qualified Days" in metric_map
        assert "Label Coverage" in metric_map
        assert "Avg Focus Hours / Day" in metric_map
        assert "Top Focus Window #1" in metric_map

        assert metric_map["Avg Focus Hours / Day"]["range_a"] == "2.0h"
        assert metric_map["Avg Focus Hours / Day"]["range_b"] == "3.0h"
        assert metric_map["Avg Focus Hours / Day"]["delta"] == "+1.0h"

