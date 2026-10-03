"""Pure functions for Typical Day dashboard view and comparison calculations.

Handles:
- Day inclusion / exclusion criteria and data quality checks
- Circular wrap-aware statistics (bedtime, wake time, median, IQR, regularity)
- Axis rotation (00:00, 06:00, 12:00, 18:00) and bin projections (15, 30, 60 min)
- Multi-day bin array aggregation (Activity, Sleep, Device, Label layers)
- Dual range comparison (Range A, Range B, Delta, Plain-word shifts)
- Peak 1-hour windows (Activity, Work, Leisure)
"""

import math
from datetime import datetime, date, timedelta, timezone
from typing import Dict, Any, List, Optional, Tuple


ALLOWED_LABELS = [
    "build",
    "practice",
    "learn",
    "stay-current",
    "career",
    "comms",
    "leisure",
    "rest",
    "eat",
    "walk",
    "social",
    "other",
]


# =============================================================================
# 1. Day Inclusion Criteria
# =============================================================================

def evaluate_day_inclusion(
    report: Dict[str, Any],
    min_accounted_seconds: float = 1800.0,
    offline_threshold_seconds: float = 60000.0,
) -> Dict[str, Any]:
    """Determine whether a daily report has sufficient tracking coverage to include.
    
    A day counts only if it has real tracker coverage:
    - Exclude if session_count == 0
    - Exclude if total_accounted_seconds < 1800 (30 min)
    - Flag if data_quality indicates watcher/collector offline for most of the day
    """
    summary = report.get("summary", {})
    session_count = int(summary.get("session_count", 0))
    accounted_seconds = float(summary.get("total_accounted_seconds", 0.0))
    
    # Offline checks from data_quality
    dq = report.get("data_quality", {})
    watcher_offline = float(dq.get("watcher_offline_seconds", 0.0))
    collector_offline = float(dq.get("collector_offline_seconds", 0.0))
    offline_flag = (watcher_offline >= offline_threshold_seconds or collector_offline >= offline_threshold_seconds)

    if session_count == 0:
        return {
            "included": False,
            "reason": "No sessions recorded",
            "offline_flag": offline_flag,
            "session_count": session_count,
            "accounted_seconds": accounted_seconds,
        }

    if accounted_seconds < min_accounted_seconds:
        return {
            "included": False,
            "reason": f"Accounted time ({accounted_seconds / 60:.1f}m) below 30m threshold",
            "offline_flag": offline_flag,
            "session_count": session_count,
            "accounted_seconds": accounted_seconds,
        }

    return {
        "included": True,
        "reason": "OK",
        "offline_flag": offline_flag,
        "session_count": session_count,
        "accounted_seconds": accounted_seconds,
    }


def filter_included_days(
    reports: Dict[str, Dict[str, Any]],
    date_keys: List[str],
    day_type_filter: str = "all",  # "all", "weekdays", "weekends"
) -> Tuple[List[str], List[Dict[str, Any]]]:
    """Filter date keys based on inclusion criteria and weekday/weekend filter.
    
    Returns (included_dates, excluded_records).
    """
    included = []
    excluded = []

    for d_str in date_keys:
        try:
            d_obj = date.fromisoformat(d_str)
            # Python weekday: Mon=0, Sun=6. Sat=5, Sun=6 are weekends.
            is_weekend = d_obj.weekday() >= 5
            if day_type_filter == "weekdays" and is_weekend:
                continue
            if day_type_filter == "weekends" and not is_weekend:
                continue
        except Exception:
            pass

        rep = reports.get(d_str)
        if not rep:
            excluded.append({"date": d_str, "reason": "No report data found"})
            continue

        eval_res = evaluate_day_inclusion(rep)
        if eval_res["included"]:
            included.append(d_str)
        else:
            excluded.append({"date": d_str, "reason": eval_res["reason"], "offline_flag": eval_res["offline_flag"]})

    return included, excluded


# =============================================================================
# 2. Circular / Wrap-Aware Math (Midnight Crossing)
# =============================================================================

def time_str_to_seconds(ts_str: Optional[str]) -> Optional[float]:
    """Parse ISO-8601 string or HH:MM(:SS) into seconds from local midnight [0, 86400)."""
    if not ts_str:
        return None
    try:
        if "T" in ts_str:
            dt = datetime.fromisoformat(ts_str)
            return dt.hour * 3600.0 + dt.minute * 60.0 + dt.second + dt.microsecond / 1e6
        parts = ts_str.split(":")
        h = int(parts[0])
        m = int(parts[1]) if len(parts) > 1 else 0
        s = float(parts[2]) if len(parts) > 2 else 0.0
        return (h * 3600.0 + m * 60.0 + s) % 86400.0
    except Exception:
        return None


def seconds_to_time_str(seconds: Optional[float], include_seconds: bool = False) -> str:
    """Format seconds from midnight [0, 86400) to HH:MM or HH:MM:SS."""
    if seconds is None:
        return "--:--"
    total_secs = int(round(seconds)) % 86400
    h = total_secs // 3600
    m = (total_secs % 3600) // 60
    s = total_secs % 60
    if include_seconds:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{h:02d}:{m:02d}"


def circular_mean_and_median_seconds(
    seconds_list: List[float],
) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """Compute circular mean, circular median, and interquartile range (IQR) for times of day.
    
    Returns (mean_seconds, median_seconds, iqr_seconds).
    Properly handles midnight crossing without distortion.
    """
    if not seconds_list:
        return None, None, None

    # Step 1: Angular representation of seconds on a 24h circle
    sin_sum = 0.0
    cos_sum = 0.0
    for s in seconds_list:
        theta = 2.0 * math.pi * (s % 86400.0) / 86400.0
        sin_sum += math.sin(theta)
        cos_sum += math.cos(theta)

    n = len(seconds_list)
    mean_theta = math.atan2(sin_sum / n, cos_sum / n)
    if mean_theta < 0:
        mean_theta += 2.0 * math.pi
    mean_seconds = (mean_theta / (2.0 * math.pi)) * 86400.0

    # Step 2: Linearize points relative to mean angle (cut opposite to mean)
    # Range is [-43200, +43200)
    relative_offsets = []
    for s in seconds_list:
        diff = (s - mean_seconds + 43200.0) % 86400.0 - 43200.0
        relative_offsets.append(diff)

    relative_offsets.sort()

    # Median
    mid = len(relative_offsets) // 2
    if len(relative_offsets) % 2 == 1:
        med_rel = relative_offsets[mid]
    else:
        med_rel = (relative_offsets[mid - 1] + relative_offsets[mid]) / 2.0

    median_seconds = (mean_seconds + med_rel + 86400.0) % 86400.0

    # IQR: Q3 - Q1
    def percentile(sorted_arr, p):
        k = (len(sorted_arr) - 1) * p
        f = math.floor(k)
        c = math.ceil(k)
        if f == c:
            return sorted_arr[int(k)]
        return sorted_arr[int(f)] * (c - k) + sorted_arr[int(c)] * (k - f)

    q1 = percentile(relative_offsets, 0.25)
    q3 = percentile(relative_offsets, 0.75)
    iqr_seconds = max(0.0, q3 - q1)

    return mean_seconds, median_seconds, iqr_seconds


def format_delta_time(
    seconds_a: Optional[float],
    seconds_b: Optional[float],
    is_time_of_day: bool = True,
) -> str:
    """Format difference between Range B and Range A with plain words.
    
    E.g. "+1h 30m later", "-45m earlier", "+1.5h", "-20m".
    """
    if seconds_a is None or seconds_b is None:
        return "--"

    if is_time_of_day:
        # Circular difference on 24h clock: (B - A) in [-43200, 43200]
        diff_sec = (seconds_b - seconds_a + 43200.0) % 86400.0 - 43200.0
        if abs(diff_sec) < 60.0:
            return "0m (same)"
        sign = "+" if diff_sec > 0 else "-"
        direction = "later" if diff_sec > 0 else "earlier"
        abs_m = int(round(abs(diff_sec) / 60.0))
        h = abs_m // 60
        m = abs_m % 60
        if h > 0:
            return f"{sign}{h}h {m:02d}m {direction}"
        return f"{sign}{m}m {direction}"
    else:
        # Linear duration difference (B - A)
        diff_sec = seconds_b - seconds_a
        if abs(diff_sec) < 60.0:
            return "0m (same)"
        sign = "+" if diff_sec > 0 else "-"
        abs_m = int(round(abs(diff_sec) / 60.0))
        h = abs_m // 60
        m = abs_m % 60
        if h > 0:
            return f"{sign}{h}h {m:02d}m"
        return f"{sign}{m}m"


# =============================================================================
# 3. Axis Projection & Bin Mapping
# =============================================================================

def project_interval_to_bins(
    start_sec_from_midnight: float,
    end_sec_from_midnight: float,
    bin_minutes: int = 15,
    axis_start_hour: int = 0,
) -> List[float]:
    """Map a time interval onto a 24-hour binned strip.
    
    Returns an array of bin overlaps in seconds, of length (1440 / bin_minutes).
    Handles intervals crossing midnight and rotated axis start seamlessly.
    """
    total_bins = 1440 // bin_minutes
    bin_width_sec = bin_minutes * 60.0
    axis_start_sec = (axis_start_hour * 3600.0) % 86400.0
    overlaps = [0.0] * total_bins

    # Ensure start and end are normalized
    dur = end_sec_from_midnight - start_sec_from_midnight
    if dur <= 0:
        return overlaps

    # Map start onto axis coordinate: [0, 86400)
    s_axis = (start_sec_from_midnight - axis_start_sec + 86400.0) % 86400.0
    e_axis = s_axis + dur

    # The interval in axis space spans [s_axis, e_axis].
    # It might exceed 86400 if it wraps around the axis end.
    # Split into sub-intervals if e_axis > 86400
    sub_intervals = []
    if e_axis <= 86400.0:
        sub_intervals.append((s_axis, e_axis))
    else:
        sub_intervals.append((s_axis, 86400.0))
        remaining = e_axis - 86400.0
        while remaining > 0:
            chunk = min(86400.0, remaining)
            sub_intervals.append((0.0, chunk))
            remaining -= chunk

    for sub_s, sub_e in sub_intervals:
        start_bin = int(sub_s // bin_width_sec)
        end_bin = int(min(total_bins - 1, sub_e // bin_width_sec))
        for b in range(start_bin, end_bin + 1):
            b_s = b * bin_width_sec
            b_e = (b + 1) * bin_width_sec
            overlap = max(0.0, min(sub_e, b_e) - max(sub_s, b_s))
            if overlap > 0:
                overlaps[b] += overlap

    return overlaps


# =============================================================================
# 4. Per-Day Binned Array Precomputation (Cacheable)
# =============================================================================

def compute_day_bins_cache(
    report: Dict[str, Any],
    bin_minutes: int = 15,
) -> Dict[str, Any]:
    """Compute canonical 00:00-anchored bin arrays for a single day report.
    
    This can be computed once and cached per day!
    When axis start or bin size changes in UI, rotate or combine these cached bins in O(bins).
    """
    total_bins = 1440 // bin_minutes
    bin_width_sec = bin_minutes * 60.0

    pc_sec = [0.0] * total_bins
    mobile_sec = [0.0] * total_bins
    screen_sec = [0.0] * total_bins
    label_sec = {lbl: [0.0] * total_bins for lbl in ALLOWED_LABELS}
    planned_label_sec = {lbl: [0.0] * total_bins for lbl in ALLOWED_LABELS}
    unplanned_label_sec = {lbl: [0.0] * total_bins for lbl in ALLOWED_LABELS}

    # Timeline intervals for screen and device activity
    timeline = report.get("timeline", [])
    for entry in timeline:
        src = entry.get("source")
        start_str = entry.get("start")
        end_str = entry.get("end")

        s_sec = time_str_to_seconds(start_str)
        e_sec = time_str_to_seconds(end_str)
        if s_sec is None or e_sec is None:
            continue

        # Handle midnight wrap within day
        dur = float(entry.get("duration_seconds", 0.0))
        if e_sec < s_sec:
            e_sec = s_sec + dur

        overlaps = project_interval_to_bins(s_sec, s_sec + dur, bin_minutes=bin_minutes, axis_start_hour=0)

        is_screen = (src in ["browser", "vscode", "desktop", "mobile"])
        is_pc = (src in ["browser", "vscode", "desktop"])
        is_mobile = (src == "mobile")

        for b in range(total_bins):
            ov = overlaps[b]
            if ov <= 0:
                continue
            if is_screen:
                screen_sec[b] += ov
            if is_pc:
                pc_sec[b] += ov
            if is_mobile:
                mobile_sec[b] += ov

    # Cap screen_sec per bin at bin_width_sec to avoid multi-event overlap overflow
    for b in range(total_bins):
        screen_sec[b] = min(bin_width_sec, screen_sec[b])
        pc_sec[b] = min(bin_width_sec, pc_sec[b])
        mobile_sec[b] = min(bin_width_sec, mobile_sec[b])

    # Label projection: prefer precise time-slice segments if present, else fallback to timeline entries
    segments = report.get("label_segments") or report.get("labels", {}).get("segments")
    if segments:
        for seg in segments:
            lbl = seg.get("label")
            if not lbl or lbl not in label_sec:
                continue
            is_planned = bool(seg.get("planned", False))
            s_sec = time_str_to_seconds(seg.get("start"))
            dur = float(seg.get("duration_seconds", 0.0))
            if s_sec is None or dur <= 0:
                continue
            overlaps = project_interval_to_bins(s_sec, s_sec + dur, bin_minutes=bin_minutes, axis_start_hour=0)
            for b in range(total_bins):
                ov = overlaps[b]
                if ov > 0:
                    label_sec[lbl][b] += ov
                    if is_planned:
                        planned_label_sec[lbl][b] += ov
                    else:
                        unplanned_label_sec[lbl][b] += ov
    else:
        for entry in timeline:
            lbl = entry.get("label")
            if not lbl or lbl not in label_sec:
                continue
            is_planned = bool(entry.get("planned", False))
            s_sec = time_str_to_seconds(entry.get("start"))
            dur = float(entry.get("duration_seconds", 0.0))
            if s_sec is None or dur <= 0:
                continue
            overlaps = project_interval_to_bins(s_sec, s_sec + dur, bin_minutes=bin_minutes, axis_start_hour=0)
            for b in range(total_bins):
                ov = overlaps[b]
                if ov > 0:
                    label_sec[lbl][b] += ov
                    if is_planned:
                        planned_label_sec[lbl][b] += ov
                    else:
                        unplanned_label_sec[lbl][b] += ov

    for lbl in ALLOWED_LABELS:
        for b in range(total_bins):
            label_sec[lbl][b] = min(bin_width_sec, label_sec[lbl][b])
            planned_label_sec[lbl][b] = min(bin_width_sec, planned_label_sec[lbl][b])
            unplanned_label_sec[lbl][b] = min(bin_width_sec, unplanned_label_sec[lbl][b])

    # Sleep interval projection for this night
    sleep_sec = [0.0] * total_bins
    sleep_info = report.get("daily_metrics", {}).get("sleep", {})
    if sleep_info.get("status") == "ok" and sleep_info.get("bedtime") and sleep_info.get("wake_time"):
        b_sec = time_str_to_seconds(sleep_info.get("bedtime"))
        w_sec = time_str_to_seconds(sleep_info.get("wake_time"))
        dur = float(sleep_info.get("duration_seconds", 0.0))
        if b_sec is not None and dur > 0:
            sleep_overlaps = project_interval_to_bins(b_sec, b_sec + dur, bin_minutes=bin_minutes, axis_start_hour=0)
            for b in range(total_bins):
                sleep_sec[b] = min(bin_width_sec, sleep_overlaps[b])

    coverage_pct = float(
        report.get("label_coverage_pct", report.get("labels", {}).get("label_coverage_pct", 0.0))
    )

    return {
        "date": report.get("date"),
        "bin_minutes": bin_minutes,
        "total_bins": total_bins,
        "screen_seconds": screen_sec,
        "pc_seconds": pc_sec,
        "mobile_seconds": mobile_sec,
        "sleep_seconds": sleep_sec,
        "label_seconds": label_sec,
        "planned_label_seconds": planned_label_sec,
        "unplanned_label_seconds": unplanned_label_sec,
        "coverage_pct": coverage_pct,
        "sleep_metrics": sleep_info,
    }


# =============================================================================
# 5. Range Aggregation & Comparison Strips
# =============================================================================

def rotate_and_aggregate_bins(
    cached_days: List[Dict[str, Any]],
    bin_minutes: int = 15,
    axis_start_hour: int = 0,
    device_filter: str = "all",  # "all", "pc", "phone"
    selected_labels: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Aggregate precomputed day bins across an included range with axis rotation.
    
    Produces layers:
    - Activity: percentage of included days with screen activity in bin, avg active minutes
    - Sleep: percentage of included nights asleep, overlay bedtime/wake medians & IQR
    - Device: PC share vs Phone share
    - Label: dominant label and average labeled minutes
    """
    total_bins = 1440 // bin_minutes
    bin_width_sec = bin_minutes * 60.0
    shift_bins = (axis_start_hour * 60 // bin_minutes) % total_bins

    n_days = len(cached_days)
    if n_days == 0:
        return {
            "n_days": 0,
            "total_bins": total_bins,
            "bin_minutes": bin_minutes,
            "axis_start_hour": axis_start_hour,
            "activity": {"pct": [0.0] * total_bins, "avg_minutes": [0.0] * total_bins},
            "sleep": {"pct": [0.0] * total_bins, "manual_count": 0, "inferred_count": 0},
            "device": {"pc_pct": [0.0] * total_bins, "phone_pct": [0.0] * total_bins},
            "label": {"dominant": ["unlabeled"] * total_bins, "avg_minutes": [0.0] * total_bins},
            "coverage_pct": 0.0,
        }

    # Bins accumulation
    days_with_activity = [0] * total_bins
    total_active_sec = [0.0] * total_bins
    total_pc_sec = [0.0] * total_bins
    total_phone_sec = [0.0] * total_bins
    days_asleep = [0] * total_bins
    labels_sum = {lbl: [0.0] * total_bins for lbl in ALLOWED_LABELS}

    manual_sleep_count = 0
    inferred_sleep_count = 0
    bedtimes = []
    wake_times = []
    sleep_durations = []

    for d in cached_days:
        # Rotate bins from 00:00 to axis_start_hour
        def rotate(arr):
            return arr[shift_bins:] + arr[:shift_bins]

        d_screen = rotate(d["screen_seconds"])
        d_pc = rotate(d["pc_seconds"])
        d_mobile = rotate(d["mobile_seconds"])
        d_sleep = rotate(d["sleep_seconds"])

        for b in range(total_bins):
            # Apply device filter
            if device_filter == "pc":
                act_sec = d_pc[b]
            elif device_filter == "phone":
                act_sec = d_mobile[b]
            else:
                act_sec = d_screen[b]

            if act_sec >= 30.0:  # Active threshold for bin (e.g. >= 30s)
                days_with_activity[b] += 1
            total_active_sec[b] += act_sec
            total_pc_sec[b] += d_pc[b]
            total_phone_sec[b] += d_mobile[b]

            if d_sleep[b] >= (bin_width_sec * 0.4):  # Asleep for at least 40% of bin
                days_asleep[b] += 1

            for lbl in ALLOWED_LABELS:
                d_lbl = rotate(d["label_seconds"][lbl])
                labels_sum[lbl][b] += d_lbl[b]

        # Sleep stats
        sm = d.get("sleep_metrics", {})
        if sm.get("status") == "ok":
            if sm.get("source") == "manual":
                manual_sleep_count += 1
            else:
                inferred_sleep_count += 1
            bt_sec = time_str_to_seconds(sm.get("bedtime"))
            wt_sec = time_str_to_seconds(sm.get("wake_time"))
            if bt_sec is not None:
                bedtimes.append(bt_sec)
            if wt_sec is not None:
                wake_times.append(wt_sec)
            if sm.get("duration_seconds"):
                sleep_durations.append(float(sm["duration_seconds"]))

    # Layers calculation
    activity_pct = [round((days_with_activity[b] / n_days) * 100.0, 1) for b in range(total_bins)]
    activity_avg_min = [round((total_active_sec[b] / n_days) / 60.0, 1) for b in range(total_bins)]

    sleep_pct = [round((days_asleep[b] / n_days) * 100.0, 1) for b in range(total_bins)]

    device_pc_pct = []
    device_phone_pct = []
    for b in range(total_bins):
        tot_dev = total_pc_sec[b] + total_phone_sec[b]
        if tot_dev > 0:
            device_pc_pct.append(round((total_pc_sec[b] / tot_dev) * 100.0, 1))
            device_phone_pct.append(round((total_phone_sec[b] / tot_dev) * 100.0, 1))
        else:
            device_pc_pct.append(0.0)
            device_phone_pct.append(0.0)

    # Label layer
    active_labels = selected_labels if selected_labels is not None else ALLOWED_LABELS
    dominant_labels = []
    dominant_avg_min = []
    total_screen_all = sum(total_active_sec)
    total_labeled_all = 0.0

    for b in range(total_bins):
        best_lbl = "unlabeled"
        best_sec = 0.0
        for lbl in active_labels:
            s = labels_sum[lbl][b]
            if s > best_sec:
                best_sec = s
                best_lbl = lbl
        dominant_labels.append(best_lbl)
        dominant_avg_min.append(round((best_sec / n_days) / 60.0, 1))

    for lbl in ALLOWED_LABELS:
        total_labeled_all += sum(labels_sum[lbl])

    coverage_pct = round((total_labeled_all / max(1.0, total_screen_all)) * 100.0, 1) if total_screen_all > 0 else 0.0

    # Bedtime and wake medians + IQR
    _, median_bedtime, bedtime_iqr = circular_mean_and_median_seconds(bedtimes)
    _, median_wake, wake_iqr = circular_mean_and_median_seconds(wake_times)

    return {
        "n_days": n_days,
        "total_bins": total_bins,
        "bin_minutes": bin_minutes,
        "axis_start_hour": axis_start_hour,
        "activity": {
            "pct": activity_pct,
            "avg_minutes": activity_avg_min,
        },
        "sleep": {
            "pct": sleep_pct,
            "manual_count": manual_sleep_count,
            "inferred_count": inferred_sleep_count,
            "median_bedtime": median_bedtime,
            "median_wake": median_wake,
            "bedtime_iqr": bedtime_iqr,
            "wake_iqr": wake_iqr,
            "avg_duration": sum(sleep_durations) / len(sleep_durations) if sleep_durations else None,
        },
        "device": {
            "pc_pct": device_pc_pct,
            "phone_pct": device_phone_pct,
        },
        "label": {
            "dominant": dominant_labels,
            "avg_minutes": dominant_avg_min,
        },
        "coverage_pct": coverage_pct,
    }


def compute_difference_strip(
    agg_a: Dict[str, Any],
    agg_b: Dict[str, Any],
    layer: str = "activity",  # "activity", "sleep", "device", "label"
) -> List[float]:
    """Compute B minus A difference values for each bin."""
    total_bins = agg_a.get("total_bins", 96)
    diff = [0.0] * total_bins

    if agg_a.get("n_days", 0) == 0 or agg_b.get("n_days", 0) == 0:
        return diff

    if layer == "activity":
        p_a = agg_a["activity"]["pct"]
        p_b = agg_b["activity"]["pct"]
        for b in range(total_bins):
            diff[b] = round(p_b[b] - p_a[b], 1)
    elif layer == "sleep":
        p_a = agg_a["sleep"]["pct"]
        p_b = agg_b["sleep"]["pct"]
        for b in range(total_bins):
            diff[b] = round(p_b[b] - p_a[b], 1)
    elif layer == "device":
        p_a = agg_a["device"]["phone_pct"]
        p_b = agg_b["device"]["phone_pct"]
        for b in range(total_bins):
            diff[b] = round(p_b[b] - p_a[b], 1)
    elif layer == "label":
        m_a = agg_a["label"]["avg_minutes"]
        m_b = agg_b["label"]["avg_minutes"]
        for b in range(total_bins):
            diff[b] = round(m_b[b] - m_a[b], 1)

    return diff


# =============================================================================
# 6. Comparison Table Metrics
# =============================================================================

def find_peak_1h_window(
    bin_values: List[float],
    bin_minutes: int,
    axis_start_hour: int,
) -> Tuple[str, float]:
    """Find rolling 1-hour window with highest sum."""
    bins_per_hour = 60 // bin_minutes
    total_bins = len(bin_values)
    best_sum = -1.0
    best_start_bin = 0

    for i in range(total_bins):
        win_sum = 0.0
        for j in range(bins_per_hour):
            idx = (i + j) % total_bins
            win_sum += bin_values[idx]
        if win_sum > best_sum:
            best_sum = win_sum
            best_start_bin = i

    start_sec = ((axis_start_hour * 3600.0) + (best_start_bin * bin_minutes * 60.0)) % 86400.0
    end_sec = (start_sec + 3600.0) % 86400.0
    win_str = f"{seconds_to_time_str(start_sec)} - {seconds_to_time_str(end_sec)}"
    return win_str, best_sum


def compute_comparison_metrics(
    reports: Dict[str, Dict[str, Any]],
    cached_days_a: List[Dict[str, Any]],
    cached_days_b: Optional[List[Dict[str, Any]]] = None,
    bin_minutes: int = 15,
    axis_start_hour: int = 0,
) -> Dict[str, Any]:
    """Compute detailed comparison table metrics for Range A and Range B."""
    agg_a = rotate_and_aggregate_bins(cached_days_a, bin_minutes=bin_minutes, axis_start_hour=axis_start_hour)
    agg_b = rotate_and_aggregate_bins(cached_days_b, bin_minutes=bin_minutes, axis_start_hour=axis_start_hour) if cached_days_b else None

    def extract_stats(cached_days, agg):
        if not cached_days or agg["n_days"] == 0:
            return {}

        dates = [d["date"] for d in cached_days if d.get("date")]
        first_acts = []
        last_acts = []
        active_hours_list = []
        phone_shares = []
        late_night_mins = []

        for d_str in dates:
            rep = reports.get(d_str, {})
            dm = rep.get("daily_metrics", {})
            summ = rep.get("summary", {})

            fa_sec = time_str_to_seconds(dm.get("first_activity") or summ.get("first_activity"))
            if fa_sec is not None:
                first_acts.append(fa_sec)
            la_sec = time_str_to_seconds(dm.get("last_activity") or summ.get("last_activity"))
            if la_sec is not None:
                last_acts.append(la_sec)

            act_sec = float(summ.get("total_active_seconds", 0.0))
            active_hours_list.append(act_sec / 3600.0)

            pc_s = float(summ.get("pc_active_seconds", 0.0))
            mob_s = float(summ.get("mobile_seconds", 0.0))
            if (pc_s + mob_s) > 0:
                phone_shares.append((mob_s / (pc_s + mob_s)) * 100.0)

            late_night_mins.append(float(dm.get("late_night_screen_seconds", 0.0)) / 60.0)

        _, avg_first_act, _ = circular_mean_and_median_seconds(first_acts)
        _, avg_last_act, _ = circular_mean_and_median_seconds(last_acts)

        # Peak windows
        peak_act_win, _ = find_peak_1h_window(agg["activity"]["avg_minutes"], bin_minutes, axis_start_hour)

        # Work window: build + practice + learn
        total_bins = agg["total_bins"]
        work_mins = [0.0] * total_bins
        for d in cached_days:
            shift = (axis_start_hour * 60 // bin_minutes) % total_bins
            for w_lbl in ["build", "practice", "learn"]:
                w_arr = d["label_seconds"][w_lbl][shift:] + d["label_seconds"][w_lbl][:shift]
                for b in range(total_bins):
                    work_mins[b] += (w_arr[b] / len(cached_days)) / 60.0
        peak_work_win, _ = find_peak_1h_window(work_mins, bin_minutes, axis_start_hour)

        # Leisure window
        leisure_mins = [0.0] * total_bins
        for d in cached_days:
            shift = (axis_start_hour * 60 // bin_minutes) % total_bins
            l_arr = d["label_seconds"]["leisure"][shift:] + d["label_seconds"]["leisure violent"] if "leisure violent" in d["label_seconds"] else d["label_seconds"]["leisure"][shift:] + d["label_seconds"]["leisure"][:shift]
            for b in range(total_bins):
                leisure_mins[b] += (l_arr[b] / len(cached_days)) / 60.0
        peak_leisure_win, _ = find_peak_1h_window(leisure_mins, bin_minutes, axis_start_hour)

        return {
            "n_days": agg["n_days"],
            "median_bedtime": agg["sleep"]["median_bedtime"],
            "median_wake": agg["sleep"]["median_wake"],
            "avg_sleep_duration": agg["sleep"]["avg_duration"],
            "bedtime_regularity_iqr": agg["sleep"]["bedtime_iqr"],
            "avg_first_activity": avg_first_act,
            "avg_last_activity": avg_last_act,
            "avg_active_hours": sum(active_hours_list) / len(active_hours_list) if active_hours_list else 0.0,
            "phone_share_pct": sum(phone_shares) / len(phone_shares) if phone_shares else 0.0,
            "peak_activity_window": peak_act_win,
            "peak_work_window": peak_work_win,
            "peak_leisure_window": peak_leisure_win,
            "avg_late_night_mins": sum(late_night_mins) / len(late_night_mins) if late_night_mins else 0.0,
            "label_coverage_pct": agg["coverage_pct"],
        }

    stats_a = extract_stats(cached_days_a, agg_a)
    stats_b = extract_stats(cached_days_b, agg_b) if (cached_days_b and agg_b) else {}

    # Build comparison rows
    rows = []

    def make_row(label, key, is_time=False, is_dur=False, is_pct=False, unit=""):
        val_a = stats_a.get(key)
        val_b = stats_b.get(key) if stats_b else None

        # Display text A
        if val_a is None:
            disp_a = "--"
        elif is_time:
            disp_a = seconds_to_time_str(val_a)
        elif is_dur:
            hrs = int(val_a // 3600)
            mins = int((val_a % 3600) // 60)
            disp_a = f"{hrs}h {mins:02d}m"
        elif is_pct:
            disp_a = f"{val_a:.1f}%"
        else:
            disp_a = f"{val_a:.1f}{unit}" if isinstance(val_a, float) else str(val_a)

        # Display text B
        if val_b is None:
            disp_b = "--"
            delta_str = "--"
        elif is_time:
            disp_b = seconds_to_time_str(val_b)
            delta_str = format_delta_time(val_a, val_b, is_time_of_day=True)
        elif is_dur:
            hrs = int(val_b // 3600)
            mins = int((val_b % 3600) // 60)
            disp_b = f"{hrs}h {mins:02d}m"
            delta_str = format_delta_time(val_a, val_b, is_time_of_day=False)
        elif is_pct:
            disp_b = f"{val_b:.1f}%"
            diff = val_b - (val_a or 0.0)
            sign = "+" if diff >= 0 else ""
            delta_str = f"{sign}{diff:.1f}%"
        else:
            disp_b = f"{val_b:.1f}{unit}" if isinstance(val_b, float) else str(val_b)
            if isinstance(val_a, float) and isinstance(val_b, float):
                diff = val_b - val_a
                sign = "+" if diff >= 0 else ""
                delta_str = f"{sign}{diff:.1f}{unit}"
            else:
                delta_str = "changed" if val_a != val_b else "same"

        return {
            "metric": label,
            "range_a": disp_a,
            "range_b": disp_b,
            "delta": delta_str,
        }

    rows.append(make_row("Median Bedtime", "median_bedtime", is_time=True))
    rows.append(make_row("Median Wake Time", "median_wake", is_time=True))
    rows.append(make_row("Avg Sleep Duration", "avg_sleep_duration", is_dur=True))
    rows.append(make_row("Bedtime Regularity (IQR)", "bedtime_regularity_iqr", is_dur=True))
    rows.append(make_row("Avg First Activity", "avg_first_activity", is_time=True))
    rows.append(make_row("Avg Last Activity", "avg_last_activity", is_time=True))
    rows.append(make_row("Avg Active Hours", "avg_active_hours", unit="h"))
    rows.append(make_row("Phone Share", "phone_share_pct", is_pct=True))
    rows.append(make_row("Peak Activity Window", "peak_activity_window"))
    rows.append(make_row("Peak Work Window", "peak_work_window"))
    rows.append(make_row("Peak Leisure Window", "peak_leisure_window"))
    rows.append(make_row("Avg Late-Night Screen", "avg_late_night_mins", unit="m"))

    return {
        "stats_a": stats_a,
        "stats_b": stats_b,
        "comparison_table": rows,
    }


# =============================================================================
# 7. Focus vs Drift Layer & Summary Table
# =============================================================================

def find_top_contiguous_windows(
    bin_values: List[float],
    bin_minutes: int,
    axis_start_hour: int,
    top_k: int = 3,
    min_window_hours: float = 1.0,
    min_rate_minutes_per_hour: float = 5.0,
) -> List[Dict[str, Any]]:
    """Find top K disjoint contiguous windows of at least min_window_hours with highest average.
    
    Returns a list of window dicts:
    [
        {
            "start_time": "09:30",
            "end_time": "11:30",
            "duration_hours": 2.0,
            "avg_minutes_per_hour": 48.0,
            "total_minutes": 96.0,
            "display": "09:30 - 11:30 (48m/h)"
        },
        ...
    ]
    """
    total_bins = len(bin_values)
    if total_bins == 0:
        return []
    min_bins = max(1, int(round((min_window_hours * 60.0) / bin_minutes)))

    remaining_values = list(bin_values)
    windows = []

    for _ in range(top_k):
        best_avg = -1.0
        best_start = -1
        best_len = -1

        # Search for best initial 1-hour window among unmasked bins
        for i in range(total_bins):
            is_valid = True
            win_sum = 0.0
            for j in range(min_bins):
                val = remaining_values[(i + j) % total_bins]
                if val < 0:
                    is_valid = False
                    break
                win_sum += val

            if is_valid:
                avg = win_sum / min_window_hours
                if avg > best_avg:
                    best_avg = avg
                    best_start = i
                    best_len = min_bins

        if best_start == -1 or best_avg < min_rate_minutes_per_hour:
            break

        # Greedily extend window forward and backward into contiguous unmasked active bins
        cur_start = best_start
        cur_len = best_len
        threshold = max(2.0, best_avg * (bin_minutes / 60.0) * 0.3)

        # Extend forward
        while cur_len < total_bins:
            next_idx = (cur_start + cur_len) % total_bins
            val = remaining_values[next_idx]
            if val >= threshold:
                cur_len += 1
            else:
                break

        # Extend backward
        while cur_len < total_bins:
            prev_idx = (cur_start - 1 + total_bins) % total_bins
            val = remaining_values[prev_idx]
            if val >= threshold:
                cur_start = prev_idx
                cur_len += 1
            else:
                break

        tot_mins = sum(bin_values[(cur_start + j) % total_bins] for j in range(cur_len))
        dur_hours = round(cur_len * bin_minutes / 60.0, 1)
        avg_rate = round(tot_mins / dur_hours, 1) if dur_hours > 0 else 0.0

        start_sec = ((axis_start_hour * 3600.0) + (cur_start * bin_minutes * 60.0)) % 86400.0
        end_sec = ((axis_start_hour * 3600.0) + ((cur_start + cur_len) * bin_minutes * 60.0)) % 86400.0
        start_str = seconds_to_time_str(start_sec)
        end_str = seconds_to_time_str(end_sec)
        disp = f"{start_str} - {end_str} ({avg_rate:.0f}m/h)"

        windows.append({
            "start_time": start_str,
            "end_time": end_str,
            "duration_hours": dur_hours,
            "avg_minutes_per_hour": avg_rate,
            "total_minutes": round(tot_mins, 1),
            "display": disp,
        })

        for j in range(cur_len):
            remaining_values[(cur_start + j) % total_bins] = -1.0

    return windows


def aggregate_focus_vs_drift(
    cached_days: List[Dict[str, Any]],
    bin_minutes: int = 15,
    axis_start_hour: int = 0,
    min_coverage_pct: float = 60.0,
    unplanned_only: bool = True,
) -> Dict[str, Any]:
    """Aggregate Focus vs Drift layer for Typical Day.
    
    Focus: build + practice + learn
    Drift: leisure (unplanned only if unplanned_only=True, else all leisure)
    Neutral: stay-current + career + comms + other (+ planned leisure if unplanned_only=True)
    Unlabeled: remaining screen time
    
    Only days with coverage >= min_coverage_pct count.
    """
    total_bins = 1440 // bin_minutes
    shift_bins = (axis_start_hour * 60 // bin_minutes) % total_bins
    n_total = len(cached_days)

    qualified_days = [
        d for d in cached_days
        if float(d.get("coverage_pct", 0.0)) >= min_coverage_pct
    ]
    n_qual = len(qualified_days)

    if n_qual == 0:
        return {
            "n_days": 0,
            "total_days": n_total,
            "qualified_days_count": 0,
            "min_coverage_pct": min_coverage_pct,
            "unplanned_only": unplanned_only,
            "total_bins": total_bins,
            "bin_minutes": bin_minutes,
            "axis_start_hour": axis_start_hour,
            "avg_focus_minutes": [0.0] * total_bins,
            "avg_drift_minutes": [0.0] * total_bins,
            "avg_neutral_minutes": [0.0] * total_bins,
            "avg_unlabeled_minutes": [0.0] * total_bins,
            "avg_focus_hours": 0.0,
            "avg_drift_hours": 0.0,
            "avg_unlabeled_hours": 0.0,
            "label_coverage_pct": 0.0,
            "top_focus_windows": [],
            "top_drift_windows": [],
        }

    total_focus_sec = [0.0] * total_bins
    total_drift_sec = [0.0] * total_bins
    total_neutral_sec = [0.0] * total_bins
    total_unlabeled_sec = [0.0] * total_bins

    for d in qualified_days:
        def rotate(arr):
            return arr[shift_bins:] + arr[:shift_bins]

        d_screen = rotate(d["screen_seconds"])

        # Focus: build, practice, learn
        f_sec = [0.0] * total_bins
        for f_lbl in ["build", "practice", "learn"]:
            arr = rotate(d["label_seconds"].get(f_lbl, [0.0] * total_bins))
            for b in range(total_bins):
                f_sec[b] += arr[b]

        # Drift: leisure
        d_sec = [0.0] * total_bins
        if unplanned_only:
            arr = rotate(d.get("unplanned_label_seconds", {}).get("leisure", [0.0] * total_bins))
            for b in range(total_bins):
                d_sec[b] += arr[b]
        else:
            arr = rotate(d["label_seconds"].get("leisure", [0.0] * total_bins))
            for b in range(total_bins):
                d_sec[b] += arr[b]

        # Neutral: stay-current, career, comms, other, rest, eat, walk, social (+ planned leisure if unplanned_only)
        neut_sec = [0.0] * total_bins
        for n_lbl in ["stay-current", "career", "comms", "other", "rest", "eat", "walk", "social"]:
            arr = rotate(d["label_seconds"].get(n_lbl, [0.0] * total_bins))
            for b in range(total_bins):
                neut_sec[b] += arr[b]
        if unplanned_only:
            arr = rotate(d.get("planned_label_seconds", {}).get("leisure", [0.0] * total_bins))
            for b in range(total_bins):
                neut_sec[b] += arr[b]

        # Unlabeled: screen time minus all labeled time in bin
        u_sec = [0.0] * total_bins
        for b in range(total_bins):
            labeled_in_bin = f_sec[b] + d_sec[b] + neut_sec[b]
            u_sec[b] = max(0.0, d_screen[b] - labeled_in_bin)

            total_focus_sec[b] += f_sec[b]
            total_drift_sec[b] += d_sec[b]
            total_neutral_sec[b] += neut_sec[b]
            total_unlabeled_sec[b] += u_sec[b]

    avg_f_min = [round((total_focus_sec[b] / n_qual) / 60.0, 1) for b in range(total_bins)]
    avg_d_min = [round((total_drift_sec[b] / n_qual) / 60.0, 1) for b in range(total_bins)]
    avg_n_min = [round((total_neutral_sec[b] / n_qual) / 60.0, 1) for b in range(total_bins)]
    avg_u_min = [round((total_unlabeled_sec[b] / n_qual) / 60.0, 1) for b in range(total_bins)]

    avg_focus_hours = round((sum(total_focus_sec) / n_qual) / 3600.0, 2)
    avg_drift_hours = round((sum(total_drift_sec) / n_qual) / 3600.0, 2)
    avg_unlabeled_hours = round((sum(total_unlabeled_sec) / n_qual) / 3600.0, 2)

    total_labeled = sum(total_focus_sec) + sum(total_drift_sec) + sum(total_neutral_sec)
    total_screen = total_labeled + sum(total_unlabeled_sec)
    overall_cov_pct = round((total_labeled / total_screen * 100.0), 1) if total_screen > 0 else 0.0

    top_f_windows = find_top_contiguous_windows(avg_f_min, bin_minutes, axis_start_hour, top_k=3, min_window_hours=1.0)
    top_d_windows = find_top_contiguous_windows(avg_d_min, bin_minutes, axis_start_hour, top_k=3, min_window_hours=1.0)

    return {
        "n_days": n_qual,
        "total_days": n_total,
        "qualified_days_count": n_qual,
        "min_coverage_pct": min_coverage_pct,
        "unplanned_only": unplanned_only,
        "total_bins": total_bins,
        "bin_minutes": bin_minutes,
        "axis_start_hour": axis_start_hour,
        "avg_focus_minutes": avg_f_min,
        "avg_drift_minutes": avg_d_min,
        "avg_neutral_minutes": avg_n_min,
        "avg_unlabeled_minutes": avg_u_min,
        "avg_focus_hours": avg_focus_hours,
        "avg_drift_hours": avg_drift_hours,
        "avg_unlabeled_hours": avg_unlabeled_hours,
        "label_coverage_pct": overall_cov_pct,
        "top_focus_windows": top_f_windows,
        "top_drift_windows": top_d_windows,
    }


def compute_focus_drift_comparison(
    agg_a: Dict[str, Any],
    agg_b: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Compute summary table and delta strips for Focus vs Drift."""
    total_bins = agg_a.get("total_bins", 96)
    delta_focus = [0.0] * total_bins
    delta_drift = [0.0] * total_bins
    delta_unlabeled = [0.0] * total_bins

    if agg_b and agg_a.get("n_days", 0) > 0 and agg_b.get("n_days", 0) > 0:
        for b in range(total_bins):
            delta_focus[b] = round(agg_b["avg_focus_minutes"][b] - agg_a["avg_focus_minutes"][b], 1)
            delta_drift[b] = round(agg_b["avg_drift_minutes"][b] - agg_a["avg_drift_minutes"][b], 1)
            delta_unlabeled[b] = round(agg_b["avg_unlabeled_minutes"][b] - agg_a["avg_unlabeled_minutes"][b], 1)

    rows = []

    # 1. Qualified Days
    q_a = f"{agg_a.get('qualified_days_count', 0)} / {agg_a.get('total_days', 0)}"
    if agg_b:
        q_b = f"{agg_b.get('qualified_days_count', 0)} / {agg_b.get('total_days', 0)}"
        diff_q = agg_b.get("qualified_days_count", 0) - agg_a.get("qualified_days_count", 0)
        d_q = f"{'+' if diff_q >= 0 else ''}{diff_q} days"
    else:
        q_b = "--"
        d_q = "--"
    rows.append({"metric": "Qualified Days", "range_a": q_a, "range_b": q_b, "delta": d_q})

    # 2. Label Coverage
    cov_a = f"{agg_a.get('label_coverage_pct', 0.0):.1f}%"
    if agg_b:
        cov_b = f"{agg_b.get('label_coverage_pct', 0.0):.1f}%"
        diff_cov = agg_b.get("label_coverage_pct", 0.0) - agg_a.get("label_coverage_pct", 0.0)
        d_cov = f"{'+' if diff_cov >= 0 else ''}{diff_cov:.1f}%"
    else:
        cov_b = "--"
        d_cov = "--"
    rows.append({"metric": "Label Coverage", "range_a": cov_a, "range_b": cov_b, "delta": d_cov})

    # 3. Avg Focus Hours
    f_hrs_a = f"{agg_a.get('avg_focus_hours', 0.0):.1f}h"
    if agg_b:
        f_hrs_b = f"{agg_b.get('avg_focus_hours', 0.0):.1f}h"
        diff_f = agg_b.get("avg_focus_hours", 0.0) - agg_a.get("avg_focus_hours", 0.0)
        d_f = f"{'+' if diff_f >= 0 else ''}{diff_f:.1f}h"
    else:
        f_hrs_b = "--"
        d_f = "--"
    rows.append({"metric": "Avg Focus Hours / Day", "range_a": f_hrs_a, "range_b": f_hrs_b, "delta": d_f})

    # 4. Avg Drift Hours
    d_hrs_a = f"{agg_a.get('avg_drift_hours', 0.0):.1f}h"
    if agg_b:
        d_hrs_b = f"{agg_b.get('avg_drift_hours', 0.0):.1f}h"
        diff_d = agg_b.get("avg_drift_hours", 0.0) - agg_a.get("avg_drift_hours", 0.0)
        d_d = f"{'+' if diff_d >= 0 else ''}{diff_d:.1f}h"
    else:
        d_hrs_b = "--"
        d_d = "--"
    rows.append({"metric": "Avg Drift Hours / Day", "range_a": d_hrs_a, "range_b": d_hrs_b, "delta": d_d})

    # Top 3 Focus Windows
    for idx in range(3):
        win_a = agg_a.get("top_focus_windows", [])[idx]["display"] if idx < len(agg_a.get("top_focus_windows", [])) else "--"
        win_b = agg_b.get("top_focus_windows", [])[idx]["display"] if (agg_b and idx < len(agg_b.get("top_focus_windows", []))) else "--"
        delta_str = "--"
        if agg_b and idx < len(agg_a.get("top_focus_windows", [])) and idx < len(agg_b.get("top_focus_windows", [])):
            diff_rate = agg_b["top_focus_windows"][idx]["avg_minutes_per_hour"] - agg_a["top_focus_windows"][idx]["avg_minutes_per_hour"]
            delta_str = f"{'+' if diff_rate >= 0 else ''}{diff_rate:.0f}m/h"
        rows.append({"metric": f"Top Focus Window #{idx + 1}", "range_a": win_a, "range_b": win_b, "delta": delta_str})

    # Top 3 Drift Windows
    for idx in range(3):
        win_a = agg_a.get("top_drift_windows", [])[idx]["display"] if idx < len(agg_a.get("top_drift_windows", [])) else "--"
        win_b = agg_b.get("top_drift_windows", [])[idx]["display"] if (agg_b and idx < len(agg_b.get("top_drift_windows", []))) else "--"
        delta_str = "--"
        if agg_b and idx < len(agg_a.get("top_drift_windows", [])) and idx < len(agg_b.get("top_drift_windows", [])):
            diff_rate = agg_b["top_drift_windows"][idx]["avg_minutes_per_hour"] - agg_a["top_drift_windows"][idx]["avg_minutes_per_hour"]
            delta_str = f"{'+' if diff_rate >= 0 else ''}{diff_rate:.0f}m/h"
        rows.append({"metric": f"Top Drift Window #{idx + 1}", "range_a": win_a, "range_b": win_b, "delta": delta_str})

    return {
        "delta_focus_minutes": delta_focus,
        "delta_drift_minutes": delta_drift,
        "delta_unlabeled_minutes": delta_unlabeled,
        "comparison_table": rows,
    }
