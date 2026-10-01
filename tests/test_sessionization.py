"""
Test suite for the activity tracker's sessionization and report generation logic.

Tests the core invariant: ONLY the currently active/focused context receives active
duration. Background tabs/windows must NOT accumulate active time.

All tests work by creating mock JSONL data, feeding it through the report generator
functions, and verifying the output.
"""

import json
import sys
import os
from pathlib import Path
from datetime import datetime, timezone, timedelta

import pytest

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reporting.generate_report import (
    read_events,
    deduplicate_events,
    aggregate_events,
    split_duration_by_hour,
    parse_timestamp,
    sessionize_events,
    generate_single_day_report,
    write_report,
)
from tests.conftest import make_browser_event, make_vscode_event, write_events_to_jsonl


# Fixed timezone for all test timestamps: IST +05:30
TZ = "+05:30"


def ts(hour, minute=0, second=0):
    """Helper to create ISO-8601 timestamp strings for 2026-09-29."""
    return f"2026-09-29T{hour:02d}:{minute:02d}:{second:02d}{TZ}"


# =============================================================================
# Test: Tab A -> Tab B switch
# =============================================================================
class TestTabSwitch:
    def test_tab_switch(self):
        """Tab A active 10:00-10:15, Tab B active 10:15-10:30. Each gets 15 min."""
        events = [
            make_browser_event(ts(10, 0), ts(10, 15), "github.com", "GitHub", tab_id=1),
            make_browser_event(ts(10, 15), ts(10, 30), "chatgpt.com", "ChatGPT", tab_id=2),
        ]

        report = aggregate_events(events)

        assert report["summary"]["total_active_seconds"] == 1800  # 30 min
        assert report["summary"]["session_count"] == 2
        assert report["summary"]["browser_seconds"] == 1800

        # Each domain gets exactly 15 min
        domain_map = {d["domain"]: d for d in report["domains"]}
        assert domain_map["github.com"]["duration_seconds"] == 900
        assert domain_map["chatgpt.com"]["duration_seconds"] == 900


# =============================================================================
# Test: Browser -> VS Code transition
# =============================================================================
class TestBrowserToVscode:
    def test_browser_to_vscode(self):
        """Browser 10:00-10:15, VS Code 10:15-10:30. Each gets 15 min."""
        events = [
            make_browser_event(ts(10, 0), ts(10, 15), "github.com", "GitHub"),
            make_vscode_event(ts(10, 15), ts(10, 30), "RAG-Studio", "src/main.py", "python"),
        ]

        report = aggregate_events(events)

        assert report["summary"]["total_active_seconds"] == 1800
        assert report["summary"]["browser_seconds"] == 900
        assert report["summary"]["vscode_seconds"] == 900
        assert report["summary"]["session_count"] == 2
        assert report["summary"]["context_switches"] == 1


# =============================================================================
# Test: VS Code file switch
# =============================================================================
class TestVscodeFileSwitch:
    def test_vscode_file_switch(self):
        """File A active 10:00-10:20, File B active 10:20-10:40. Each gets 20 min."""
        events = [
            make_vscode_event(ts(10, 0), ts(10, 20), "RAG-Studio", "src/retriever.py", "python"),
            make_vscode_event(ts(10, 20), ts(10, 40), "RAG-Studio", "src/evaluator.py", "python"),
        ]

        report = aggregate_events(events)

        assert report["summary"]["total_active_seconds"] == 2400  # 40 min
        assert report["summary"]["vscode_seconds"] == 2400
        assert report["summary"]["session_count"] == 2

        # Both files should be in the workspace
        ws = report["workspaces"][0]
        assert ws["workspace"] == "RAG-Studio"
        assert ws["duration_seconds"] == 2400
        assert ws["files_touched"] == 2


# =============================================================================
# Test: Browser focus loss (gap in activity)
# =============================================================================
class TestBrowserFocusLoss:
    def test_browser_focus_loss(self):
        """Browser 10:00-10:15, gap (lost focus) 10:15-10:20, browser 10:20-10:30.
        Total should be 25 min, NOT 30 min."""
        events = [
            make_browser_event(ts(10, 0), ts(10, 15), "github.com", "GitHub"),
            make_browser_event(ts(10, 20), ts(10, 30), "github.com", "GitHub"),
        ]

        report = aggregate_events(events)

        # Only 25 min of active time (the gap is not counted)
        assert report["summary"]["total_active_seconds"] == 1500  # 25 min
        assert report["summary"]["session_count"] == 2


# =============================================================================
# Test: Browser regains focus creates new session
# =============================================================================
class TestBrowserRegainsFocus:
    def test_browser_regains_focus(self):
        """After losing and regaining focus, a NEW session starts (not extending old)."""
        events = [
            make_browser_event(ts(10, 0), ts(10, 15), "github.com", "GitHub"),
            make_browser_event(ts(10, 20), ts(10, 30), "github.com", "GitHub"),
        ]

        report = aggregate_events(events)

        # Two separate sessions, even though same domain/title
        assert report["summary"]["session_count"] == 2
        assert len(report["timeline"]) == 2
        assert report["timeline"][0]["end"] != report["timeline"][1]["start"]


# =============================================================================
# Test: Repeated same tab activation
# =============================================================================
class TestRepeatedSameTab:
    def test_repeated_same_tab(self):
        """Same tab active 10:00-10:10, away, back 10:20-10:30.
        Two sessions of 10 min each = 20 min total (not 30)."""
        events = [
            make_browser_event(ts(10, 0), ts(10, 10), "github.com", "GitHub", tab_id=1),
            make_browser_event(ts(10, 20), ts(10, 30), "github.com", "GitHub", tab_id=1),
        ]

        report = aggregate_events(events)

        assert report["summary"]["total_active_seconds"] == 1200  # 20 min
        assert report["summary"]["session_count"] == 2

        # Domain aggregation should sum both
        domain_map = {d["domain"]: d for d in report["domains"]}
        assert domain_map["github.com"]["duration_seconds"] == 1200
        assert domain_map["github.com"]["session_count"] == 2


# =============================================================================
# Test: Multiple tabs - only active counts
# =============================================================================
class TestMultipleTabsOnlyActiveCounts:
    def test_multiple_tabs_only_active_counts(self):
        """5 tabs open (implied), but only 1 active at a time.
        Total = sum of active sessions only."""
        events = [
            make_browser_event(ts(10, 0), ts(10, 5), "github.com", "GitHub", tab_id=1),
            make_browser_event(ts(10, 5), ts(10, 10), "chatgpt.com", "ChatGPT", tab_id=2),
            make_browser_event(ts(10, 10), ts(10, 15), "stackoverflow.com", "Stack Overflow", tab_id=3),
            make_browser_event(ts(10, 15), ts(10, 20), "docs.python.org", "Python Docs", tab_id=4),
            make_browser_event(ts(10, 20), ts(10, 25), "youtube.com", "YouTube", tab_id=5),
        ]

        report = aggregate_events(events)

        # Total = 25 min (5 sessions × 5 min each)
        assert report["summary"]["total_active_seconds"] == 1500
        assert report["summary"]["session_count"] == 5
        assert len(report["domains"]) == 5

        # Each domain gets exactly 5 min
        for d in report["domains"]:
            assert d["duration_seconds"] == 300


# =============================================================================
# Test: Multiple windows
# =============================================================================
class TestMultipleWindows:
    def test_multiple_windows(self):
        """Window 1 active 10:00-10:15, Window 2 active 10:15-10:30.
        Each window's active tab gets its time."""
        events = [
            make_browser_event(ts(10, 0), ts(10, 15), "github.com", "GitHub",
                              tab_id=1, window_id=1),
            make_browser_event(ts(10, 15), ts(10, 30), "chatgpt.com", "ChatGPT",
                              tab_id=5, window_id=2),
        ]

        report = aggregate_events(events)

        assert report["summary"]["total_active_seconds"] == 1800
        assert report["summary"]["session_count"] == 2


# =============================================================================
# Test: Midnight rollover
# =============================================================================
class TestMidnightRollover:
    def test_midnight_rollover(self):
        """Session starts at 23:55, ends at 00:05 next day.
        The session should be included in the report."""
        events = [
            make_browser_event(
                "2026-09-29T23:55:00+05:30",
                "2026-09-30T00:05:00+05:30",
                "github.com", "GitHub"
            ),
        ]

        report = aggregate_events(events)

        assert report["summary"]["total_active_seconds"] == 600  # 10 min
        assert report["summary"]["session_count"] == 1


# =============================================================================
# Test: Duplicate events
# =============================================================================
class TestDuplicateEvents:
    def test_duplicate_events(self):
        """Same event ID submitted twice. Should count only once."""
        eid = "dup-event-001"
        events = [
            make_browser_event(ts(10, 0), ts(10, 15), "github.com", "GitHub",
                              event_id=eid),
            make_browser_event(ts(10, 0), ts(10, 15), "github.com", "GitHub",
                              event_id=eid),
        ]

        deduped = deduplicate_events(events)
        report = aggregate_events(deduped)

        assert report["summary"]["session_count"] == 1
        assert report["summary"]["total_active_seconds"] == 900  # 15 min, not 30


# =============================================================================
# Test: Concurrent browser + VS Code (sequential, not overlapping)
# =============================================================================
class TestConcurrentBrowserVscode:
    def test_concurrent_browser_vscode(self):
        """Browser and VS Code events are sequential (focus switches).
        No overlap should occur."""
        events = [
            make_browser_event(ts(10, 0), ts(10, 10), "github.com", "GitHub"),
            make_vscode_event(ts(10, 10), ts(10, 20), "RAG-Studio", "src/main.py", "python"),
            make_browser_event(ts(10, 20), ts(10, 30), "chatgpt.com", "ChatGPT"),
            make_vscode_event(ts(10, 30), ts(10, 40), "RAG-Studio", "src/test.py", "python"),
        ]

        report = aggregate_events(events)

        assert report["summary"]["total_active_seconds"] == 2400  # 40 min
        assert report["summary"]["browser_seconds"] == 1200  # 20 min
        assert report["summary"]["vscode_seconds"] == 1200  # 20 min
        assert report["summary"]["session_count"] == 4
        assert report["summary"]["context_switches"] == 3


# =============================================================================
# Test: Domain aggregation
# =============================================================================
class TestDomainAggregation:
    def test_domain_aggregation(self):
        """Multiple sessions on github.com with different pages.
        Domain total = sum of all github.com sessions."""
        events = [
            make_browser_event(ts(10, 0), ts(10, 10), "github.com", "Pull Requests",
                              url="https://github.com/pulls"),
            make_browser_event(ts(10, 15), ts(10, 25), "github.com", "Issues",
                              url="https://github.com/issues"),
            make_browser_event(ts(10, 30), ts(10, 40), "github.com", "Code",
                              url="https://github.com/repo/code"),
        ]

        report = aggregate_events(events)

        domain_map = {d["domain"]: d for d in report["domains"]}
        assert domain_map["github.com"]["duration_seconds"] == 1800  # 30 min
        assert domain_map["github.com"]["session_count"] == 3


# =============================================================================
# Test: Workspace aggregation
# =============================================================================
class TestWorkspaceAggregation:
    def test_workspace_aggregation(self):
        """Multiple files in same workspace. Workspace total = sum of file sessions."""
        events = [
            make_vscode_event(ts(10, 0), ts(10, 15), "RAG-Studio", "src/retriever.py", "python"),
            make_vscode_event(ts(10, 15), ts(10, 30), "RAG-Studio", "src/evaluator.py", "python"),
            make_vscode_event(ts(10, 30), ts(10, 45), "RAG-Studio", "src/app.ts", "typescript"),
        ]

        report = aggregate_events(events)

        ws = report["workspaces"][0]
        assert ws["workspace"] == "RAG-Studio"
        assert ws["duration_seconds"] == 2700  # 45 min
        assert ws["session_count"] == 3
        assert ws["files_touched"] == 3
        assert ws["languages"]["python"] == 1800  # 30 min
        assert ws["languages"]["typescript"] == 900  # 15 min


# =============================================================================
# Test: Malformed event skipped
# =============================================================================
class TestMalformedEventSkipped:
    def test_malformed_event_skipped(self, tmp_data_dir):
        """A malformed JSON line doesn't crash processing."""
        filepath = tmp_data_dir / "raw" / "2026-09-29.jsonl"

        good_event = make_browser_event(ts(10, 0), ts(10, 15), "github.com", "GitHub")

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(json.dumps(good_event) + "\n")
            f.write("THIS IS NOT VALID JSON\n")
            f.write('{"incomplete": true}\n')  # Missing required fields
            f.write(json.dumps(good_event) + "\n")  # Duplicate of first

        events = read_events(str(filepath))

        # Should have read the good events (both copies have same data,
        # but read_events doesn't deduplicate - that's done separately)
        assert len(events) >= 1

        # After dedup, should have 1
        deduped = deduplicate_events(events)
        report = aggregate_events(deduped)
        assert report["summary"]["session_count"] == 1


# =============================================================================
# Test: Empty day
# =============================================================================
class TestEmptyDay:
    def test_empty_day(self, tmp_data_dir):
        """No events for a date produces a valid empty report."""
        filepath = tmp_data_dir / "raw" / "2026-09-29.jsonl"
        # File doesn't exist

        events = read_events(str(filepath))
        report = aggregate_events(events)

        assert report["summary"]["total_active_seconds"] == 0
        assert report["summary"]["session_count"] == 0
        assert report["summary"]["context_switches"] == 0
        assert report["domains"] == []
        assert report["workspaces"] == []
        assert report["timeline"] == []

    def test_empty_file(self, tmp_data_dir):
        """Empty JSONL file produces a valid empty report."""
        filepath = tmp_data_dir / "raw" / "2026-09-29.jsonl"
        filepath.touch()

        events = read_events(str(filepath))
        report = aggregate_events(events)

        assert report["summary"]["total_active_seconds"] == 0
        assert report["summary"]["session_count"] == 0


# =============================================================================
# Test: Context switches count
# =============================================================================
class TestContextSwitches:
    def test_context_switches(self):
        """N sessions = N-1 context switches."""
        events = [
            make_browser_event(ts(10, 0), ts(10, 5), "a.com", "A"),
            make_vscode_event(ts(10, 5), ts(10, 10), "Proj", "f1.py", "python"),
            make_browser_event(ts(10, 10), ts(10, 15), "b.com", "B"),
            make_vscode_event(ts(10, 15), ts(10, 20), "Proj", "f2.py", "python"),
            make_browser_event(ts(10, 20), ts(10, 25), "c.com", "C"),
        ]

        report = aggregate_events(events)

        assert report["summary"]["session_count"] == 5
        assert report["summary"]["context_switches"] == 4

    def test_single_session_zero_switches(self):
        """1 session = 0 context switches."""
        events = [
            make_browser_event(ts(10, 0), ts(10, 30), "github.com", "GitHub"),
        ]

        report = aggregate_events(events)

        assert report["summary"]["session_count"] == 1
        assert report["summary"]["context_switches"] == 0


# =============================================================================
# Test: Hourly breakdown
# =============================================================================
class TestHourlyBreakdown:
    def test_hourly_breakdown(self):
        """Sessions bucketed correctly into hours."""
        events = [
            # Entirely within hour 10
            make_browser_event(ts(10, 10), ts(10, 40), "github.com", "GitHub"),
            # Spans hour 10 -> 11
            make_vscode_event(ts(10, 45), ts(11, 15), "Proj", "f.py", "python"),
        ]

        report = aggregate_events(events)

        hourly = {h["hour"]: h for h in report["hourly_breakdown"]}

        # Hour 10: 30 min of browser + 15 min of vscode = 45 min
        assert hourly[10]["browser_seconds"] == 1800  # 30 min
        assert hourly[10]["vscode_seconds"] == 900  # 15 min
        assert hourly[10]["active_seconds"] == 2700  # 45 min

        # Hour 11: 15 min of vscode
        assert hourly[11]["vscode_seconds"] == 900  # 15 min
        assert hourly[11]["active_seconds"] == 900

    def test_single_hour_session(self):
        """A session fully within one hour lands in the right bucket."""
        events = [
            make_browser_event(ts(14, 0), ts(14, 30), "docs.python.org", "Docs"),
        ]

        report = aggregate_events(events)

        hourly = {h["hour"]: h for h in report["hourly_breakdown"]}
        assert 14 in hourly
        assert hourly[14]["active_seconds"] == 1800
        assert hourly[14]["browser_seconds"] == 1800


# =============================================================================
# Test: Longest sessions
# =============================================================================
class TestLongestSessions:
    def test_longest_sessions_ordering(self):
        """Longest sessions should be sorted by duration descending."""
        events = [
            make_browser_event(ts(10, 0), ts(10, 5), "a.com", "A"),        # 5 min
            make_browser_event(ts(10, 5), ts(10, 35), "b.com", "B"),       # 30 min
            make_vscode_event(ts(10, 35), ts(10, 50), "P", "f.py", "py"),  # 15 min
        ]

        report = aggregate_events(events)

        longest = report["longest_sessions"]
        assert len(longest) == 3
        assert longest[0]["duration_seconds"] == 1800  # 30 min
        assert longest[1]["duration_seconds"] == 900   # 15 min
        assert longest[2]["duration_seconds"] == 300   # 5 min


# =============================================================================
# Test: Timeline ordering
# =============================================================================
class TestTimeline:
    def test_timeline_chronological(self):
        """Timeline entries must be in chronological order."""
        events = [
            make_vscode_event(ts(10, 30), ts(10, 45), "P", "f2.py", "python"),
            make_browser_event(ts(10, 0), ts(10, 15), "a.com", "A"),
            make_browser_event(ts(10, 15), ts(10, 30), "b.com", "B"),
        ]

        report = aggregate_events(events)

        timeline = report["timeline"]
        assert len(timeline) == 3
        # Should be sorted by start time
        assert timeline[0]["source"] == "browser"
        assert timeline[0]["context"]["domain"] == "a.com"
        assert timeline[1]["context"]["domain"] == "b.com"
        assert timeline[2]["source"] == "vscode"


# =============================================================================
# Test: Read events from JSONL file
# =============================================================================
class TestReadEvents:
    def test_read_valid_jsonl(self, tmp_data_dir):
        """Reading a well-formed JSONL file returns all events."""
        events = [
            make_browser_event(ts(10, 0), ts(10, 15), "github.com", "GitHub"),
            make_vscode_event(ts(10, 15), ts(10, 30), "Proj", "f.py", "python"),
        ]

        filepath = tmp_data_dir / "raw" / "2026-09-29.jsonl"
        write_events_to_jsonl(str(filepath), events)

        loaded = read_events(str(filepath))
        assert len(loaded) == 2

    def test_read_nonexistent_file(self, tmp_data_dir):
        """Reading a non-existent file returns empty list (doesn't crash)."""
        filepath = tmp_data_dir / "raw" / "1999-01-01.jsonl"
        events = read_events(str(filepath))
        assert events == []


# =============================================================================
# Test: Language aggregation
# =============================================================================
class TestLanguageAggregation:
    def test_language_breakdown(self):
        """Languages are aggregated across workspaces."""
        events = [
            make_vscode_event(ts(10, 0), ts(10, 20), "ProjA", "a.py", "python"),
            make_vscode_event(ts(10, 20), ts(10, 35), "ProjA", "b.ts", "typescript"),
            make_vscode_event(ts(10, 35), ts(10, 55), "ProjB", "c.py", "python"),
        ]

        report = aggregate_events(events)

        lang_map = {l["language"]: l for l in report["languages"]}
        assert lang_map["python"]["duration_seconds"] == 2400  # 40 min
        assert lang_map["python"]["session_count"] == 2
        assert lang_map["typescript"]["duration_seconds"] == 900  # 15 min
        assert lang_map["typescript"]["session_count"] == 1


# =============================================================================
# Test: Source breakdown
# =============================================================================
class TestSourceBreakdown:
    def test_source_counts(self):
        """Sources dict contains correct duration and session counts."""
        events = [
            make_browser_event(ts(10, 0), ts(10, 10), "a.com", "A"),
            make_browser_event(ts(10, 10), ts(10, 20), "b.com", "B"),
            make_vscode_event(ts(10, 20), ts(10, 30), "P", "f.py", "python"),
        ]

        report = aggregate_events(events)

        assert report["sources"]["browser"]["duration_seconds"] == 1200
        assert report["sources"]["browser"]["session_count"] == 2
        assert report["sources"]["vscode"]["duration_seconds"] == 600
        assert report["sources"]["vscode"]["session_count"] == 1


# =============================================================================
# Requirement 13A: Same context, small gap
# =============================================================================
class TestRequirement13A_SameContextSmallGap:
    def test_same_context_small_gap_merged(self):
        """Events: 10:00–10:10 (600s), 10:10:05–10:15:05 (300s).
        Expected: 1 logical session, 15 minutes active (900s), 5s gap not counted as active.
        """
        e1 = make_vscode_event(ts(10, 0, 0), ts(10, 10, 0), "RAG-Studio", "src/main.py", "python")
        e2 = make_vscode_event(ts(10, 10, 5), ts(10, 15, 5), "RAG-Studio", "src/main.py", "python")

        report = aggregate_events([e1, e2], merge_gap_seconds=30.0)

        # 1 logical session
        assert report["summary"]["session_count"] == 1
        # Active duration is 600s + 300s = 900s (15 min); 5s gap is excluded
        assert report["summary"]["total_active_seconds"] == 900.0
        assert report["summary"]["vscode_seconds"] == 900.0
        # Observed span is wall-clock time from 10:00:00 to 10:15:05 (905s)
        assert report["summary"]["observed_span_seconds"] == 905.0
        assert report["summary"]["context_switches"] == 0
        assert report["timeline"][0]["raw_event_count"] == 2


# =============================================================================
# Requirement 13B: Same context, large gap
# =============================================================================
class TestRequirement13B_SameContextLargeGap:
    def test_same_context_large_gap_not_merged(self):
        """Events: 10:00–10:10, 10:11–10:15.
        With a 30s threshold, gap is 60s > 30s, so they remain 2 logical sessions.
        """
        e1 = make_vscode_event(ts(10, 0, 0), ts(10, 10, 0), "RAG-Studio", "src/main.py", "python")
        e2 = make_vscode_event(ts(10, 11, 0), ts(10, 15, 0), "RAG-Studio", "src/main.py", "python")

        report = aggregate_events([e1, e2], merge_gap_seconds=30.0)

        assert report["summary"]["session_count"] == 2
        # Total active is 600s + 240s = 840s (14 min)
        assert report["summary"]["total_active_seconds"] == 840.0
        # Inactive gap (60s) is not active time
        assert report["summary"]["observed_span_seconds"] == 900.0  # 10:00 to 10:15 = 15 min
        # Same context paused and resumed: 0 context switches
        assert report["summary"]["context_switches"] == 0


# =============================================================================
# Requirement 13C: Context switch (ChatGPT -> YouTube)
# =============================================================================
class TestRequirement13C_ContextSwitchChatGPTToYouTube:
    def test_chatgpt_to_youtube_switch(self):
        """ChatGPT -> YouTube.
        Expected: 2 sessions, 1 context switch.
        """
        e1 = make_browser_event(ts(10, 0, 0), ts(10, 10, 0), "chatgpt.com", "ChatGPT", "https://chatgpt.com/")
        e2 = make_browser_event(ts(10, 10, 0), ts(10, 20, 0), "youtube.com", "YouTube", "https://youtube.com/")

        report = aggregate_events([e1, e2], merge_gap_seconds=30.0)

        assert report["summary"]["session_count"] == 2
        assert report["summary"]["context_switches"] == 1
        assert len(report["domains"]) == 2
        domain_names = {d["domain"] for d in report["domains"]}
        assert domain_names == {"chatgpt.com", "youtube.com"}


# =============================================================================
# Requirement 13D: Browser -> VS Code
# =============================================================================
class TestRequirement13D_BrowserToVSCode:
    def test_browser_to_vscode_switch(self):
        """Browser -> VS Code.
        Expected: 2 sessions, 1 context switch.
        """
        e1 = make_browser_event(ts(10, 0, 0), ts(10, 10, 0), "chatgpt.com", "ChatGPT")
        e2 = make_vscode_event(ts(10, 10, 0), ts(10, 20, 0), "RAG-Studio", "src/retriever.py", "python")

        report = aggregate_events([e1, e2], merge_gap_seconds=30.0)

        assert report["summary"]["session_count"] == 2
        assert report["summary"]["context_switches"] == 1
        assert report["summary"]["browser_seconds"] == 600.0
        assert report["summary"]["vscode_seconds"] == 600.0


# =============================================================================
# Requirement 13E: Same VS Code file with fragmented events
# =============================================================================
class TestRequirement13E_SameVSCodeFileFragmentedEvents:
    def test_fragmented_vscode_events_merge(self):
        """Several short events for requirements-dev.txt with gaps below threshold.
        Expected: 1 logical session with exact active sum, no gap time added.
        """
        events = [
            make_vscode_event(ts(21, 27, 56), ts(21, 28, 16), "activity-tracker", "requirements-dev.txt", "pip-requirements"),
            make_vscode_event(ts(21, 28, 18), ts(21, 28, 34), "activity-tracker", "requirements-dev.txt", "pip-requirements"),
            make_vscode_event(ts(21, 28, 47), ts(21, 29, 22), "activity-tracker", "requirements-dev.txt", "pip-requirements"),
        ]

        report = aggregate_events(events, merge_gap_seconds=30.0)

        # All 3 belong to the exact same context with gaps of 2s and 13s (< 30s)
        assert report["summary"]["session_count"] == 1
        # Active duration is 20s + 16s + 35s = 71.0s (not 86s wall-clock)
        assert report["summary"]["total_active_seconds"] == 71.0
        assert report["summary"]["context_switches"] == 0
        assert report["timeline"][0]["raw_event_count"] == 3


# =============================================================================
# Requirement 13F: Different VS Code files
# =============================================================================
class TestRequirement13F_DifferentVSCodeFiles:
    def test_different_vscode_files_not_merged(self):
        """requirements-dev.txt -> generate_report.py.
        Expected: 2 logical sessions, 1 context switch even with small gap.
        """
        e1 = make_vscode_event(ts(10, 0, 0), ts(10, 10, 0), "AW", "requirements-dev.txt", "pip-requirements")
        e2 = make_vscode_event(ts(10, 10, 5), ts(10, 20, 0), "AW", "generate_report.py", "python")

        report = aggregate_events([e1, e2], merge_gap_seconds=30.0)

        assert report["summary"]["session_count"] == 2
        assert report["summary"]["context_switches"] == 1
        assert len(report["timeline"]) == 2
        assert report["timeline"][0]["context"]["file"] == "requirements-dev.txt"
        assert report["timeline"][1]["context"]["file"] == "generate_report.py"


# =============================================================================
# Requirement 13G: Mixed timestamp formats
# =============================================================================
class TestRequirement13G_MixedTimestampFormats:
    def test_mixed_timestamp_formats(self):
        """Test both UTC 'Z' and '+05:30' timestamps.
        15:43:00Z is 21:13:00+05:30.
        Gap between 15:43:00Z and 21:13:10+05:30 is 10 seconds.
        """
        e1 = {
            "id": "e-utc-1",
            "start": "2026-09-29T15:40:00Z",
            "end": "2026-09-29T15:43:00Z",
            "duration_seconds": 180.0,
            "source": "browser",
            "context": {"browser": "chrome", "domain": "chatgpt.com", "title": "ChatGPT", "url": "https://chatgpt.com/"}
        }
        e2 = {
            "id": "e-ist-2",
            "start": "2026-09-29T21:13:10+05:30",
            "end": "2026-09-29T21:20:00+05:30",
            "duration_seconds": 410.0,
            "source": "vscode",
            "context": {"workspace": "AW", "file": "src/main.py", "language": "python"}
        }

        report = aggregate_events([e1, e2], merge_gap_seconds=30.0)

        assert report["summary"]["session_count"] == 2
        assert report["summary"]["total_active_seconds"] == 590.0
        assert report["summary"]["browser_seconds"] == 180.0
        assert report["summary"]["vscode_seconds"] == 410.0
        assert report["summary"]["context_switches"] == 1
        # Chronological order verified: browser first, then vscode
        assert report["timeline"][0]["source"] == "browser"
        assert report["timeline"][1]["source"] == "vscode"


# =============================================================================
# Requirement 13H: Report regeneration
# =============================================================================
class TestRequirement13H_ReportRegeneration:
    def test_report_regeneration_complete_day(self, tmp_data_dir):
        """Generate a report, append another raw event, generate again.
        Verify the new report contains the new event and does not duplicate previous activity.
        """
        from dataclasses import dataclass
        @dataclass
        class MockConfig:
            data_directory: str = str(tmp_data_dir)
            session_merge_gap_seconds: float = 30.0

        cfg = MockConfig()
        date_str = "2026-09-29"
        raw_file = tmp_data_dir / "raw" / f"{date_str}.jsonl"

        # Step 1: Initial event
        e1 = make_browser_event(ts(10, 0, 0), ts(10, 15, 0), "github.com", "GitHub", event_id="init-1")
        write_events_to_jsonl(str(raw_file), [e1])

        # Generate report 1
        rep1 = generate_single_day_report(cfg, date_str)
        write_report(cfg, rep1, f"{date_str}.json")

        assert rep1["summary"]["session_count"] == 1
        assert rep1["summary"]["total_active_seconds"] == 900.0

        # Step 2: Append another event to the raw file (simulating later activity)
        e2 = make_vscode_event(ts(10, 20, 0), ts(10, 40, 0), "RAG-Studio", "src/main.py", "python", event_id="later-2")
        with open(raw_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(e2) + "\n")

        # Generate report 2
        rep2 = generate_single_day_report(cfg, date_str)
        write_report(cfg, rep2, f"{date_str}.json")

        # Verify completely regenerated, not appended or duplicated
        assert rep2["summary"]["session_count"] == 2
        assert rep2["summary"]["total_active_seconds"] == 2100.0  # 900s + 1200s
        assert rep2["summary"]["browser_seconds"] == 900.0
        assert rep2["summary"]["vscode_seconds"] == 1200.0
        assert rep2["summary"]["context_switches"] == 1
        # Read saved report from disk to ensure clean overwrite
        saved_report_path = tmp_data_dir / "reports" / f"{date_str}.json"
        with open(saved_report_path, "r", encoding="utf-8") as f:
            disk_report = json.load(f)
        assert disk_report["summary"]["session_count"] == 2
        assert disk_report["summary"]["total_active_seconds"] == 2100.0


# =============================================================================
# Mobile Screen Time & Multi-Source Tests
# =============================================================================
class TestMobileSessionization:
    def test_mobile_session_merge(self):
        """Consecutive events of same mobile app within 30s merge without adding gap."""
        from tests.conftest import make_mobile_event
        events = [
            make_mobile_event(ts(14, 0, 0), ts(14, 5, 0), "WhatsApp", "com.whatsapp"),
            make_mobile_event(ts(14, 5, 20), ts(14, 10, 0), "WhatsApp", "com.whatsapp"),  # 20s gap
        ]

        report = aggregate_events(events, merge_gap_seconds=30.0)

        assert report["summary"]["session_count"] == 1
        assert report["summary"]["total_active_seconds"] == 580.0  # 300s + 280s (gap not added)
        assert report["summary"]["mobile_seconds"] == 580.0
        assert len(report["apps"]) == 1
        assert report["apps"][0]["app"] == "WhatsApp"
        assert report["apps"][0]["duration_seconds"] == 580.0

    def test_multisource_browser_vscode_mobile(self):
        """Report combines browser, VS Code, and mobile sources cleanly."""
        from tests.conftest import make_mobile_event
        events = [
            make_browser_event(ts(10, 0, 0), ts(10, 30, 0), "github.com", "GitHub"),
            make_vscode_event(ts(10, 30, 0), ts(11, 0, 0), "activity-tracker", "main.py", "python"),
            make_mobile_event(ts(11, 0, 0), ts(11, 20, 0), "Twitter / X", "com.twitter.android"),
        ]

        report = aggregate_events(events)

        assert report["summary"]["session_count"] == 3
        assert report["summary"]["context_switches"] == 2
        assert report["summary"]["browser_seconds"] == 1800.0
        assert report["summary"]["vscode_seconds"] == 1800.0
        assert report["summary"]["mobile_seconds"] == 1200.0
        assert report["summary"]["total_active_seconds"] == 4800.0

        # Timeline has clean context without url/tab_id
        assert report["timeline"][2]["source"] == "mobile"
        assert report["timeline"][2]["context"]["app"] == "Twitter / X"
        assert report["timeline"][2]["context"]["package"] == "com.twitter.android"

        # Apps section populated
        assert len(report["apps"]) == 1
        assert report["apps"][0]["app"] == "Twitter / X"
        assert report["apps"][0]["duration_seconds"] == 1200.0


# =============================================================================
# Desktop Application & 4-Source Tests
# =============================================================================
class TestDesktopSessionization:
    def test_desktop_session_merge(self):
        """Consecutive events of same desktop app within 30s merge without adding gap."""
        from tests.conftest import make_desktop_event
        events = [
            make_desktop_event(ts(14, 0, 0), ts(14, 15, 0), "Antigravity", "AW - Antigravity"),
            make_desktop_event(ts(14, 15, 10), ts(14, 30, 0), "Antigravity", "AW - Antigravity"),  # 10s gap
        ]

        report = aggregate_events(events, merge_gap_seconds=30.0)

        assert report["summary"]["session_count"] == 1
        assert report["summary"]["total_active_seconds"] == 1790.0  # 900s + 890s (gap not added)
        assert report["summary"]["desktop_seconds"] == 1790.0
        assert len(report["desktop_apps"]) == 1
        assert report["desktop_apps"][0]["app"] == "Antigravity"
        assert report["desktop_apps"][0]["duration_seconds"] == 1790.0

    def test_complete_4source_unification(self):
        """Report seamlessly unifies all 4 sources: browser, vscode, desktop, and mobile."""
        from tests.conftest import make_mobile_event, make_desktop_event
        events = [
            make_browser_event(ts(10, 0, 0), ts(10, 30, 0), "github.com", "GitHub"),
            make_vscode_event(ts(10, 30, 0), ts(11, 0, 0), "activity-tracker", "main.py", "python"),
            make_desktop_event(ts(11, 0, 0), ts(11, 45, 0), "Antigravity", "activity-tracker"),
            make_mobile_event(ts(11, 45, 0), ts(12, 0, 0), "WhatsApp", "com.whatsapp"),
        ]

        report = aggregate_events(events)

        assert report["summary"]["session_count"] == 4
        assert report["summary"]["context_switches"] == 3
        assert report["summary"]["browser_seconds"] == 1800.0
        assert report["summary"]["vscode_seconds"] == 1800.0
        assert report["summary"]["desktop_seconds"] == 2700.0
        assert report["summary"]["mobile_seconds"] == 900.0
        assert report["summary"]["total_active_seconds"] == 7200.0  # exactly 2 hours total

        # Contexts are clean
        assert report["timeline"][2]["source"] == "desktop"
        assert report["timeline"][2]["context"] == {"app": "Antigravity", "title": "activity-tracker"}

        # Desktop apps breakdown
        assert len(report["desktop_apps"]) == 1
        assert report["desktop_apps"][0]["app"] == "Antigravity"
        assert report["desktop_apps"][0]["duration_seconds"] == 2700.0


# =============================================================================
# Cross-Device Overlap and Interleaving Tests
# =============================================================================
class TestCrossDeviceOverlapAndInterleaving:
    def test_overlapping_mobile_and_pc_no_double_counting(self):
        """User is working in VS Code from 10:00 to 11:00 (3600s),
        while simultaneously checking WhatsApp on mobile from 10:15 to 10:45 (1800s).
        Expected:
        - total_active_seconds = 3600.0 (true wall-clock union, NOT 5400s)
        - vscode_seconds = 3600.0
        - mobile_seconds = 1800.0
        """
        from tests.conftest import make_mobile_event
        events = [
            make_vscode_event(ts(10, 0, 0), ts(11, 0, 0), "activity-tracker", "main.py", "python"),
            make_mobile_event(ts(10, 15, 0), ts(10, 45, 0), "WhatsApp", "com.whatsapp"),
        ]

        report = aggregate_events(events)

        assert report["summary"]["total_active_seconds"] == 3600.0
        assert report["summary"]["vscode_seconds"] == 3600.0
        assert report["summary"]["mobile_seconds"] == 1800.0
        assert report["summary"]["session_count"] == 2

    def test_mobile_interleaving_does_not_fragment_pc_session(self):
        """User works in VS Code from 10:00 to 10:20, checks phone 10:20:05 to 10:20:15,
        and continues in the exact same VS Code file from 10:20:10 to 10:40.
        VS Code events should merge into 1 continuous logical session rather than being
        fragmented by the mobile event into separate sessions.
        """
        from tests.conftest import make_mobile_event
        events = [
            make_vscode_event(ts(10, 0, 0), ts(10, 20, 0), "activity-tracker", "main.py", "python"),
            make_mobile_event(ts(10, 20, 5), ts(10, 20, 15), "Telegram", "org.telegram.messenger"),
            make_vscode_event(ts(10, 20, 10), ts(10, 40, 0), "activity-tracker", "main.py", "python"),
        ]

        report = aggregate_events(events, merge_gap_seconds=30.0)

        # VS Code events merged into 1 session; mobile is 1 session -> 2 sessions total
        assert report["summary"]["session_count"] == 2
        assert report["summary"]["vscode_seconds"] == 2390.0  # 1200s + 1190s (10s gap excluded)
        assert report["summary"]["mobile_seconds"] == 10.0


# =============================================================================
# Requirement: Minimum Duration Filtering (Under 40s discarded)
# =============================================================================
class TestMinimumDurationFiltering:
    def test_aggregate_events_filters_sub_40s_sessions(self):
        """Sessions under 40 seconds should be excluded when min_session_duration=40.0."""
        events = [
            # 15s session -> should be filtered
            make_browser_event(ts(10, 0, 0), ts(10, 0, 15), "quick-glance.com", "Quick Glance"),
            # 50s session -> should be kept
            make_browser_event(ts(10, 5, 0), ts(10, 5, 50), "deep-read.com", "Deep Read"),
            # 20s + 25s merged session (same context, 2s gap) -> total 45s -> should be kept
            make_vscode_event(ts(10, 10, 0), ts(10, 10, 20), "proj", "file.py", "python"),
            make_vscode_event(ts(10, 10, 22), ts(10, 10, 47), "proj", "file.py", "python"),
        ]

        report = aggregate_events(events, merge_gap_seconds=30.0, min_session_duration=40.0)

        # Only deep-read (50s) and merged vscode (45s) remain
        assert report["summary"]["session_count"] == 2
        assert len(report["timeline"]) == 2
        domains = [d["domain"] for d in report["domains"]]
        assert "quick-glance.com" not in domains
        assert "deep-read.com" in domains
        assert report["summary"]["total_active_seconds"] == 95.0

    def test_storage_append_event_discards_sub_40s(self, tmp_path):
        """Storage append_event should discard events with duration_seconds < min_duration_seconds."""
        from collector.storage import append_event
        from collector.config import Config

        cfg = Config(data_directory=str(tmp_path), min_duration_seconds=40.0)

        short_event = {
            "id": "short-1",
            "start": ts(10, 0, 0),
            "end": ts(10, 0, 15),
            "duration_seconds": 15.0,
            "source": "browser",
            "context": {"domain": "short.com"}
        }
        long_event = {
            "id": "long-1",
            "start": ts(10, 1, 0),
            "end": ts(10, 2, 0),
            "duration_seconds": 60.0,
            "source": "browser",
            "context": {"domain": "long.com"}
        }

        assert append_event(cfg, short_event) is False
        assert append_event(cfg, long_event) is True




