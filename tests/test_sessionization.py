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
        assert "context_switches" not in report["summary"]


# =============================================================================
# Test: VS Code file switch
# =============================================================================
class TestVscodeFileSwitch:
    def test_vscode_file_switch_same_workspace(self):
        """File A active 10:00-10:20, File B active 10:20-10:40 within same workspace merge into 1 session."""
        events = [
            make_vscode_event(ts(10, 0), ts(10, 20), "RAG-Studio", "src/retriever.py", "python"),
            make_vscode_event(ts(10, 20), ts(10, 40), "RAG-Studio", "src/evaluator.py", "python"),
        ]

        report = aggregate_events(events)

        assert report["summary"]["total_active_seconds"] == 2400  # 40 min
        assert report["summary"]["vscode_seconds"] == 2400
        assert report["summary"]["session_count"] == 1

        ws = report["workspaces"][0]
        assert ws["workspace"] == "RAG-Studio"
        assert ws["duration_seconds"] == 2400
        assert ws["session_count"] == 1


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
        assert "context_switches" not in report["summary"]


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
        """Contiguous events in same workspace merge into 1 session without language/files_touched."""
        events = [
            make_vscode_event(ts(10, 0), ts(10, 15), "RAG-Studio", "src/retriever.py", "python"),
            make_vscode_event(ts(10, 15), ts(10, 30), "RAG-Studio", "src/evaluator.py", "python"),
            make_vscode_event(ts(10, 30), ts(10, 45), "RAG-Studio", "src/app.ts", "typescript"),
        ]

        report = aggregate_events(events)

        ws = report["workspaces"][0]
        assert ws["workspace"] == "RAG-Studio"
        assert ws["duration_seconds"] == 2700  # 45 min
        assert ws["session_count"] == 1
        assert "files_touched" not in ws
        assert "languages" not in ws


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
        assert "context_switches" not in report["summary"]
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
        assert "context_switches" not in report["summary"]


# =============================================================================
# Test: Context switches removed per Phase 5
# =============================================================================
class TestContextSwitchesRemoved:
    def test_context_switches_not_in_summary(self):
        """context_switches has been removed from summary per Phase 5."""
        events = [
            make_browser_event(ts(10, 0), ts(10, 5), "a.com", "A"),
            make_vscode_event(ts(10, 5), ts(10, 10), "Proj"),
            make_browser_event(ts(10, 10), ts(10, 15), "b.com", "B"),
            make_vscode_event(ts(10, 15), ts(10, 20), "Proj"),
            make_browser_event(ts(10, 20), ts(10, 25), "c.com", "C"),
        ]

        report = aggregate_events(events)

        assert report["summary"]["session_count"] == 5
        assert "context_switches" not in report["summary"]

    def test_single_session_no_context_switches(self):
        """1 session = no context_switches key."""
        events = [
            make_browser_event(ts(10, 0), ts(10, 30), "github.com", "GitHub"),
        ]

        report = aggregate_events(events)

        assert report["summary"]["session_count"] == 1
        assert "context_switches" not in report["summary"]


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
            make_vscode_event(ts(10, 45), ts(11, 15), "Proj"),
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

    def test_overlapping_pc_and_mobile_hourly_union(self):
        """PC and mobile overlapping in one hour should have hourly active_seconds
        computed as the interval union, not naive sum capped at 3600."""
        from tests.conftest import make_mobile_event
        events = [
            # PC: 10:00 to 10:40 (40 min = 2400s)
            make_browser_event(ts(10, 0), ts(10, 40), "github.com", "GitHub"),
            # Mobile: 10:20 to 10:50 (30 min = 1800s)
            make_mobile_event(ts(10, 20), ts(10, 50), "WhatsApp", "com.whatsapp"),
        ]
        report = aggregate_events(events)
        hourly = {h["hour"]: h for h in report["hourly_breakdown"]}
        assert 10 in hourly
        assert hourly[10]["browser_seconds"] == 2400.0
        assert hourly[10]["mobile_seconds"] == 1800.0
        # Union of [10:00, 10:40] and [10:20, 10:50] is [10:00, 10:50] = 50 min = 3000s
        # (NOT 2400 + 1800 = 4200, and NOT capped 3600)
        assert hourly[10]["active_seconds"] == 3000.0


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
class TestWorkspaceMergeAcrossWorkspaces:
    def test_workspace_merge_and_no_languages_section(self):
        """Old events with file and language still merge by workspace; report drops languages section."""
        events = [
            make_vscode_event(ts(10, 0), ts(10, 20), "ProjA", "a.py", "python"),
            make_vscode_event(ts(10, 20), ts(10, 35), "ProjA", "b.ts", "typescript"),
            make_vscode_event(ts(10, 35), ts(10, 55), "ProjB", "c.py", "python"),
        ]

        report = aggregate_events(events)

        assert "languages" not in report
        ws_map = {w["workspace"]: w for w in report["workspaces"]}
        assert ws_map["ProjA"]["duration_seconds"] == 2100  # 35 min
        assert ws_map["ProjA"]["session_count"] == 1
        assert ws_map["ProjB"]["duration_seconds"] == 1200  # 20 min
        assert ws_map["ProjB"]["session_count"] == 1


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
        assert "context_switches" not in report["summary"]
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
        # Same context paused and resumed: no context switches key
        assert "context_switches" not in report["summary"]


# =============================================================================
# Requirement 13C: Context switch (ChatGPT -> YouTube)
# =============================================================================
class TestRequirement13C_ContextSwitchChatGPTToYouTube:
    def test_chatgpt_to_youtube_switch(self):
        """ChatGPT -> YouTube.
        Expected: 2 sessions.
        """
        e1 = make_browser_event(ts(10, 0, 0), ts(10, 10, 0), "chatgpt.com", "ChatGPT", "https://chatgpt.com/")
        e2 = make_browser_event(ts(10, 10, 0), ts(10, 20, 0), "youtube.com", "YouTube", "https://youtube.com/")

        report = aggregate_events([e1, e2], merge_gap_seconds=30.0)

        assert report["summary"]["session_count"] == 2
        assert "context_switches" not in report["summary"]
        assert len(report["domains"]) == 2
        domain_names = {d["domain"] for d in report["domains"]}
        assert domain_names == {"chatgpt.com", "youtube.com"}


# =============================================================================
# Requirement 13D: Browser -> VS Code
# =============================================================================
class TestRequirement13D_BrowserToVSCode:
    def test_browser_to_vscode_switch(self):
        """Browser -> VS Code.
        Expected: 2 sessions.
        """
        e1 = make_browser_event(ts(10, 0, 0), ts(10, 10, 0), "chatgpt.com", "ChatGPT")
        e2 = make_vscode_event(ts(10, 10, 0), ts(10, 20, 0), "RAG-Studio", "src/retriever.py", "python")

        report = aggregate_events([e1, e2], merge_gap_seconds=30.0)

        assert report["summary"]["session_count"] == 2
        assert "context_switches" not in report["summary"]
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
        assert "context_switches" not in report["summary"]
        assert report["timeline"][0]["raw_event_count"] == 3


# =============================================================================
# Requirement 13F: Different VS Code files
# =============================================================================
class TestRequirement13F_DifferentVSCodeFiles:
    def test_same_workspace_different_files_merged(self):
        """requirements-dev.txt -> generate_report.py in same workspace 'AW'.
        Expected: 1 logical session (context is workspace only), context in report has workspace only.
        """
        e1 = make_vscode_event(ts(10, 0, 0), ts(10, 10, 0), "AW", "requirements-dev.txt", "pip-requirements")
        e2 = make_vscode_event(ts(10, 10, 5), ts(10, 20, 0), "AW", "generate_report.py", "python")

        report = aggregate_events([e1, e2], merge_gap_seconds=30.0)

        assert report["summary"]["session_count"] == 1
        assert "context_switches" not in report["summary"]
        assert len(report["timeline"]) == 1
        assert report["timeline"][0]["context"] == {"workspace": "AW"}

    def test_different_workspaces_not_merged(self):
        """Different workspaces remain separate sessions."""
        e1 = make_vscode_event(ts(10, 0, 0), ts(10, 10, 0), "AW", "requirements-dev.txt", "pip-requirements")
        e2 = make_vscode_event(ts(10, 10, 5), ts(10, 20, 0), "OtherProject", "generate_report.py", "python")

        report = aggregate_events([e1, e2], merge_gap_seconds=30.0)

        assert report["summary"]["session_count"] == 2
        assert "context_switches" not in report["summary"]


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
        assert "context_switches" not in report["summary"]
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
        assert "context_switches" not in rep2["summary"]
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
        assert "context_switches" not in report["summary"]
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
        assert "context_switches" not in report["summary"]
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
        assert report["summary"]["brief_seconds"] == 15.0
        assert report["summary"]["brief_session_count"] == 1

    def test_storage_append_event_discards_sub_raw_min(self, tmp_path):
        """Storage append_event should discard events with duration_seconds < raw_min_duration_seconds."""
        from collector.storage import append_event
        from collector.config import Config

        cfg = Config(data_directory=str(tmp_path), raw_min_duration_seconds=2.0)

        sub_raw_event = {
            "id": "sub-raw-1",
            "start": ts(10, 0, 0),
            "end": ts(10, 0, 1),
            "duration_seconds": 1.0,
            "source": "browser",
            "context": {"domain": "glitch.com"}
        }
        valid_raw_event = {
            "id": "raw-1",
            "start": ts(10, 0, 0),
            "end": ts(10, 0, 20),
            "duration_seconds": 20.0,
            "source": "browser",
            "context": {"domain": "valid.com"}
        }

        assert append_event(cfg, sub_raw_event) is False
        assert append_event(cfg, valid_raw_event) is True

    def test_raw_storage_keeps_sub_40s_fragments_and_merges_to_71s(self, tmp_path):
        """Fragments of 20s, 16s and 35s are kept in raw storage and merge into one 71s session in report."""
        from collector.storage import append_event, read_events
        from collector.config import Config

        cfg = Config(data_directory=str(tmp_path), raw_min_duration_seconds=2.0, min_duration_seconds=40.0)

        # Three raw fragments under 40s each, but >= raw_min_duration_seconds (2s)
        frag1 = {
            "id": "frag-1",
            "start": ts(10, 0, 0),
            "end": ts(10, 0, 20),
            "duration_seconds": 20.0,
            "source": "browser",
            "context": {"browser": "chrome", "domain": "github.com", "title": "Repo", "url": "https://github.com"}
        }
        frag2 = {
            "id": "frag-2",
            "start": ts(10, 0, 22),
            "end": ts(10, 0, 38),
            "duration_seconds": 16.0,
            "source": "browser",
            "context": {"browser": "chrome", "domain": "github.com", "title": "Repo", "url": "https://github.com"}
        }
        frag3 = {
            "id": "frag-3",
            "start": ts(10, 0, 40),
            "end": ts(10, 1, 15),
            "duration_seconds": 35.0,
            "source": "browser",
            "context": {"browser": "chrome", "domain": "github.com", "title": "Repo", "url": "https://github.com"}
        }

        # All 3 fragments must be kept in raw storage
        assert append_event(cfg, frag1) is True
        assert append_event(cfg, frag2) is True
        assert append_event(cfg, frag3) is True

        stored_events = read_events(cfg, "2026-09-29")
        assert len(stored_events) == 3

        # When aggregated with 40s min_duration_seconds, they merge into one 71s session
        report = aggregate_events(stored_events, merge_gap_seconds=30.0, min_session_duration=40.0)
        assert report["summary"]["session_count"] == 1
        assert report["summary"]["total_active_seconds"] == 71.0
        assert report["summary"]["brief_seconds"] == 0.0
        assert report["summary"]["brief_session_count"] == 0
        assert len(report["timeline"]) == 1
        assert report["timeline"][0]["duration_seconds"] == 71.0
        assert report["timeline"][0]["raw_event_count"] == 3


# =============================================================================
# Test: Manual Offline Activities & Unobserved Gap Detection
# =============================================================================
class TestManualActivityAndGapAnnotation:
    def test_manual_model_validation(self):
        """Event validation accepts 'manual' source."""
        from collector.models import validate_and_create_event
        data = {
            "start": ts(13, 0),
            "end": ts(15, 0),
            "duration_seconds": 7200,
            "source": "manual",
            "context": {"activity": "Afternoon nap", "category": "rest"}
        }
        evt = validate_and_create_event(data)
        assert evt.source == "manual"
        assert evt.context["activity"] == "Afternoon nap"

    def test_manual_storage_parsing_and_inference(self, tmp_path):
        """create_manual_event and parse_text_line parse shorthand and infer category."""
        from collector.manual_storage import parse_text_line, infer_category, save_manual_event, read_manual_events

        assert infer_category("Afternoon nap") == "rest"
        assert infer_category("Quick lunch") == "meal"
        assert infer_category("Gym workout") == "fitness"

        evt = parse_text_line("13:00 - 15:00 | Afternoon nap", "2026-09-29")
        assert evt is not None
        assert evt["source"] == "manual"
        assert evt["duration_seconds"] == 7200.0
        assert evt["context"]["activity"] == "Afternoon nap"
        assert evt["context"]["category"] == "rest"

        # Save and read back
        save_manual_event(str(tmp_path), "2026-09-29", evt)
        loaded = read_manual_events(str(tmp_path), "2026-09-29")
        assert len(loaded) == 1
        assert loaded[0]["context"]["activity"] == "Afternoon nap"

    def test_aggregate_events_with_manual_activity(self):
        """Screen time and manual offline time are separated and accounted cleanly."""
        from collector.manual_storage import create_manual_event

        events = [
            # 1 hour of VS Code
            make_vscode_event(ts(10, 0), ts(11, 0), "RAG-Studio", "main.py", "python"),
            # 2 hours of Afternoon Nap
            create_manual_event("2026-09-29", "13:00", "15:00", "Afternoon nap", "rest"),
        ]

        report = aggregate_events(events)

        # Screen time is strictly 1 hour
        assert report["summary"]["total_active_seconds"] == 3600.0
        assert report["summary"]["screen_seconds"] == 3600.0
        assert report["summary"]["vscode_seconds"] == 3600.0

        # Manual time is 2 hours
        assert report["summary"]["manual_seconds"] == 7200.0
        # Total accounted union = 3600 + 7200 = 10800
        assert report["summary"]["total_accounted_seconds"] == 10800.0
        assert report["summary"]["unobserved_seconds"] == 86400.0 - 10800.0

        # Manual activities table
        assert len(report["manual_activities"]) == 1
        assert report["manual_activities"][0]["activity"] == "Afternoon nap"
        assert report["manual_activities"][0]["duration_seconds"] == 7200.0

        # Timeline has 2 sessions
        assert len(report["timeline"]) == 2
        sources = [t["source"] for t in report["timeline"]]
        assert "vscode" in sources
        assert "manual" in sources

    def test_overlap_between_manual_nap_and_quick_mobile_check(self):
        """A quick 2-minute mobile check during a 2-hour nap does not double count union time."""
        from collector.manual_storage import create_manual_event
        from tests.conftest import make_mobile_event

        events = [
            create_manual_event("2026-09-29", "13:00", "15:00", "Afternoon nap", "rest"),
            make_mobile_event(ts(13, 30), ts(13, 32), "WhatsApp", "com.whatsapp"), # 2 min = 120s
        ]

        report = aggregate_events(events)

        assert report["summary"]["screen_seconds"] == 120.0
        assert report["summary"]["mobile_seconds"] == 120.0
        assert report["summary"]["manual_seconds"] == 7200.0
        # Sweep line union covers 13:00 to 15:00 = 7200s
        assert report["summary"]["total_accounted_seconds"] == 7200.0

    def test_find_unobserved_gaps(self):
        """Gap detector finds unobserved periods between active sessions."""
        from reporting.annotate_gaps import find_unobserved_gaps
        from reporting.generate_report import get_report_timezone

        events = [
            make_vscode_event(ts(10, 0), ts(11, 0), "RAG-Studio", "main.py", "python"),
            make_vscode_event(ts(13, 0), ts(14, 0), "RAG-Studio", "eval.py", "python"),
        ]
        tz = get_report_timezone(events)
        gaps = find_unobserved_gaps(events, "2026-09-29", tz, min_gap_seconds=30 * 60, include_day_boundaries=False)

        # There is a 2-hour gap between 11:00 and 13:00
        assert len(gaps) == 1
        assert gaps[0]["duration_seconds"] == 7200.0

    def test_manual_event_seconds_precision(self):
        """Manual activity parses and retains exact seconds without losing them."""
        from collector.manual_storage import parse_time_str, create_manual_event, parse_text_line

        h, m, s = parse_time_str("23:25:51")
        assert (h, m, s) == (23, 25, 51)

        # Event creation
        evt = create_manual_event("2026-10-01", "23:25:51", "23:44:23", "Walk", "fitness")
        assert evt["start"] == "2026-10-01T23:25:51+05:30"
        assert evt["end"] == "2026-10-01T23:44:23+05:30"
        assert evt["duration_seconds"] == 1112.0  # 18 minutes 32 seconds

        # Text line parsing
        parsed = parse_text_line("23:25:51 - 23:44:23: Walk", "2026-10-01")
        assert parsed is not None
        assert parsed["duration_seconds"] == 1112.0
        assert parsed["context"]["activity"] == "Walk"

    def test_manual_hourly_separation(self):
        """Hours with only manual events report 0 active screen time in hourly breakdown."""
        from collector.manual_storage import create_manual_event

        events = [
            create_manual_event("2026-10-01", "02:00:00", "10:00:00", "Sleep", "rest"),
            make_vscode_event(ts(10, 15, 0), ts(10, 45, 0), "AW", "main.py", "python"),
        ]

        report = aggregate_events(events)
        hourly = {h["hour"]: h for h in report.get("hourly_breakdown", [])}

        # Hours 2 through 9 must have active_seconds == 0.0 and manual_seconds == 3600.0
        for h in range(2, 10):
            assert hourly[h]["active_seconds"] == 0.0
            assert hourly[h]["manual_seconds"] == 3600.0

        # Hour 10 has screen active time
        assert hourly[10]["active_seconds"] == 1800.0


# =============================================================================
# Requirement Phase 2: Android Screen State Accuracy & Mobile Sync Separation
# =============================================================================
class TestAndroidScreenStateAndIdleAccuracy:
    def test_session_clamped_by_screen_non_interactive(self):
        """A session must clamp to the screen-off timestamp if screen turned off before pause."""
        from collector.android_collector import parse_usagestats_events
        dev_tz = timezone(timedelta(hours=5, minutes=30))
        sample_dumpsys = """
time="2026-09-29 10:00:00" type=SCREEN_INTERACTIVE package=android
time="2026-09-29 10:00:05" type=KEYGUARD_HIDDEN package=android
time="2026-09-29 10:00:10" type=ACTIVITY_RESUMED package=com.whatsapp
time="2026-09-29 10:05:00" type=SCREEN_NON_INTERACTIVE package=android
time="2026-09-29 10:10:00" type=ACTIVITY_PAUSED package=com.whatsapp
"""
        sessions = parse_usagestats_events(sample_dumpsys, dev_tz, min_duration_seconds=2.0)
        assert len(sessions) == 1
        s = sessions[0]
        assert s["context"]["app"] == "WhatsApp"
        # Must be clamped at 10:05:00, not 10:10:00!
        assert s["start"] == "2026-09-29T10:00:10+05:30"
        assert s["end"] == "2026-09-29T10:05:00+05:30"
        assert s["duration_seconds"] == 290.0

    def test_session_clamped_by_keyguard_shown(self):
        """A session must clamp to KEYGUARD_SHOWN timestamp."""
        from collector.android_collector import parse_usagestats_events
        dev_tz = timezone(timedelta(hours=5, minutes=30))
        sample_dumpsys = """
time="2026-09-29 10:00:00" type=SCREEN_INTERACTIVE package=android
time="2026-09-29 10:00:05" type=KEYGUARD_HIDDEN package=android
time="2026-09-29 10:00:10" type=ACTIVITY_RESUMED package=com.twitter.android
time="2026-09-29 10:04:00" type=KEYGUARD_SHOWN package=com.android.systemui
time="2026-09-29 10:15:00" type=ACTIVITY_PAUSED package=com.twitter.android
"""
        sessions = parse_usagestats_events(sample_dumpsys, dev_tz, min_duration_seconds=2.0)
        assert len(sessions) == 1
        s = sessions[0]
        assert s["start"] == "2026-09-29T10:00:10+05:30"
        assert s["end"] == "2026-09-29T10:04:00+05:30"
        assert s["duration_seconds"] == 230.0

    def test_open_session_never_ends_at_now_if_screen_off(self):
        """An open session must clamp to the last screen-off time and NEVER end at now if screen is currently off."""
        from collector.android_collector import parse_usagestats_events
        dev_tz = timezone(timedelta(hours=5, minutes=30))
        sample_dumpsys = """
time="2026-09-29 10:00:00" type=SCREEN_INTERACTIVE package=android
time="2026-09-29 10:00:05" type=KEYGUARD_HIDDEN package=android
time="2026-09-29 10:00:10" type=ACTIVITY_RESUMED package=com.reddit.frontpage
time="2026-09-29 10:05:00" type=SCREEN_NON_INTERACTIVE package=android
"""
        # Current time is 10:30:00, but screen turned off at 10:05:00
        now_dt = datetime(2026, 9, 29, 10, 30, 0, tzinfo=dev_tz)
        sessions = parse_usagestats_events(sample_dumpsys, dev_tz, min_duration_seconds=2.0, now_dt=now_dt)
        assert len(sessions) == 1
        s = sessions[0]
        # Must end at 10:05:00, NOT now_dt (10:30:00)
        assert s["end"] == "2026-09-29T10:05:00+05:30"
        assert s["duration_seconds"] == 290.0

    def test_open_session_ends_at_now_if_screen_on(self):
        """An open session ends at now_dt if the screen is currently interactive."""
        from collector.android_collector import parse_usagestats_events
        dev_tz = timezone(timedelta(hours=5, minutes=30))
        sample_dumpsys = """
time="2026-09-29 10:00:00" type=SCREEN_INTERACTIVE package=android
time="2026-09-29 10:00:05" type=KEYGUARD_HIDDEN package=android
time="2026-09-29 10:00:10" type=ACTIVITY_RESUMED package=com.reddit.frontpage
"""
        now_dt = datetime(2026, 9, 29, 10, 10, 10, tzinfo=dev_tz)
        sessions = parse_usagestats_events(sample_dumpsys, dev_tz, min_duration_seconds=2.0, now_dt=now_dt)
        assert len(sessions) == 1
        s = sessions[0]
        assert s["end"] == "2026-09-29T10:10:10+05:30"
        assert s["duration_seconds"] == 600.0


class TestMobileSyncSeparation:
    def test_read_day_events_reads_both_pc_and_mobile_files(self, tmp_path):
        """read_day_events reads both raw/YYYY/mmm/daily/DATE.jsonl and raw/YYYY/mmm/daily/mobile/DATE.jsonl."""
        from reporting.generate_report import read_day_events
        data_dir = tmp_path
        
        # Prepare daily directory
        daily_dir = data_dir / "raw" / "2026" / "sep" / "daily"
        mobile_dir = daily_dir / "mobile"
        mobile_dir.mkdir(parents=True, exist_ok=True)

        pc_file = daily_dir / "2026-09-29.jsonl"
        mob_file = mobile_dir / "2026-09-29.jsonl"

        pc_event = make_browser_event(ts(10, 0), ts(10, 15), "github.com", "GitHub", event_id="pc-1")
        mob_event = {
            "id": "mob-1",
            "start": ts(10, 5),
            "end": ts(10, 10),
            "duration_seconds": 300.0,
            "source": "mobile",
            "context": {"app": "WhatsApp", "package": "com.whatsapp"}
        }

        with open(pc_file, "w", encoding="utf-8") as f:
            f.write(json.dumps(pc_event) + "\n")

        with open(mob_file, "w", encoding="utf-8") as f:
            f.write(json.dumps(mob_event) + "\n")

        events = read_day_events(str(data_dir), "2026-09-29")
        assert len(events) == 2
        sources = {e["source"] for e in events}
        assert sources == {"browser", "mobile"}


class TestPhase3DesktopWatcherMasterTimeline:
    def test_alt_tab_away_from_chrome_with_extension_reporting(self):
        """Alt-Tab away from Chrome clips extension event to Chrome foreground; Discord gets remaining time."""
        from tests.conftest import make_browser_event, make_desktop_event

        events = [
            # Watcher says Chrome foreground 10:00 to 10:05
            make_desktop_event(ts(10, 0), ts(10, 5), "Google Chrome", "GitHub - PR #42"),
            # User Alt-Tabs to Discord 10:05 to 10:10
            make_desktop_event(ts(10, 5), ts(10, 10), "Discord", "Discord | #dev"),
            # Browser extension lagged / kept reporting 10:00 to 10:10
            make_browser_event(ts(10, 0), ts(10, 10), "github.com", "GitHub - PR #42"),
        ]

        report = aggregate_events(events)

        assert report["summary"]["total_active_seconds"] == 600.0
        assert report["summary"]["pc_active_seconds"] == 600.0
        assert report["summary"]["browser_seconds"] == 300.0
        assert report["summary"]["desktop_seconds"] == 300.0

        # Timeline has 2 sessions: Chrome then Discord
        assert len(report["timeline"]) == 2
        assert report["timeline"][0]["source"] == "browser"
        assert report["timeline"][0]["duration_seconds"] == 300.0
        assert report["timeline"][1]["source"] == "desktop"
        assert report["timeline"][1]["duration_seconds"] == 300.0

    def test_idle_clipping(self):
        """Idle periods recorded by desktop watcher clip foreground browser extension time."""
        from tests.conftest import make_browser_event, make_desktop_event

        events = [
            # Chrome foreground 10:00 to 10:05
            make_desktop_event(ts(10, 0), ts(10, 5), "Google Chrome", "Python Docs"),
            # Idle event 10:05 to 10:10
            {
                "id": "idle-1",
                "start": ts(10, 5),
                "end": ts(10, 10),
                "duration_seconds": 300.0,
                "source": "desktop",
                "context": {"status": "idle", "app": "Idle"}
            },
            # Browser extension reported 10:00 to 10:10
            make_browser_event(ts(10, 0), ts(10, 10), "docs.python.org", "Python Docs"),
        ]

        report = aggregate_events(events)

        # Active time is only 300s (idle is not active screen time)
        assert report["summary"]["total_active_seconds"] == 300.0
        assert report["summary"]["pc_active_seconds"] == 300.0
        assert report["summary"]["browser_seconds"] == 300.0
        assert len(report["timeline"]) == 1
        assert report["timeline"][0]["duration_seconds"] == 300.0

    def test_watcher_offline_fallback(self):
        """When watcher was offline, extension events fall back unclipped and are flagged in data_quality."""
        from tests.conftest import make_browser_event

        events = [
            # No desktop events at all (watcher offline)
            make_browser_event(ts(14, 10), ts(14, 30), "github.com", "GitHub", event_id="b-1"),
        ]

        report = aggregate_events(events)

        assert report["summary"]["total_active_seconds"] == 1200.0
        assert report["summary"]["browser_seconds"] == 1200.0
        assert len(report["data_quality"]["fallback_ranges"]) > 0
        fb = report["data_quality"]["fallback_ranges"][0]
        assert fb["duration_seconds"] == 1200.0

    def test_two_browser_profiles_overlap_resolution(self):
        """Two browser profiles overlapping are resolved chronologically by watcher foreground without double counting."""
        from tests.conftest import make_desktop_event

        events = [
            # Watcher: Chrome foreground 10:00 to 10:10 (600s)
            make_desktop_event(ts(10, 0), ts(10, 10), "Google Chrome", "Chrome Window"),
            # Profile 1 (Work): 10:00 to 10:06 (github.com)
            {
                "id": "p1-1",
                "start": ts(10, 0),
                "end": ts(10, 6),
                "duration_seconds": 360.0,
                "source": "browser",
                "context": {"browser": "chrome", "domain": "github.com", "title": "GitHub"}
            },
            # Profile 2 (Personal): 10:04 to 10:10 (youtube.com)
            {
                "id": "p2-1",
                "start": ts(10, 4),
                "end": ts(10, 10),
                "duration_seconds": 360.0,
                "source": "browser",
                "context": {"browser": "chrome", "domain": "youtube.com", "title": "YouTube"}
            },
        ]

        report = aggregate_events(events)

        # Non-overlapping PC timeline: 10:00-10:04 (Profile 1, 240s) + 10:04-10:10 (Profile 2, 360s) = 600s
        assert report["summary"]["total_active_seconds"] == 600.0
        assert report["summary"]["pc_active_seconds"] == 600.0
        assert report["summary"]["browser_seconds"] == 600.0

        domains = {d["domain"]: d["duration_seconds"] for d in report["domains"]}
        assert domains["github.com"] == 240.0
        assert domains["youtube.com"] == 360.0

    def test_leftover_unknown_page_time(self):
        """Leftover foreground time with no matching extension event becomes unknown page / no workspace."""
        from tests.conftest import make_desktop_event, make_browser_event

        events = [
            # Chrome foreground 10:00 to 10:10 (600s)
            make_desktop_event(ts(10, 0), ts(10, 10), "Google Chrome", "Chrome"),
            # Extension event only 10:02 to 10:07 (300s)
            make_browser_event(ts(10, 2), ts(10, 7), "github.com", "GitHub"),
            # VS Code foreground 10:10 to 10:20 (600s) with no VS Code extension events
            make_desktop_event(ts(10, 10), ts(10, 20), "Code", "Visual Studio Code"),
        ]

        report = aggregate_events(events)

        assert report["summary"]["total_active_seconds"] == 1200.0
        assert report["summary"]["browser_seconds"] == 600.0
        assert report["summary"]["vscode_seconds"] == 600.0

        titles = {t["title"]: t["duration_seconds"] for t in report["titles"]}
        assert "Chrome (unknown page)" in titles
        # 10:00-10:02 (120s) + 10:07-10:10 (180s) = 300s
        assert titles["Chrome (unknown page)"] == 300.0
        assert titles["GitHub"] == 300.0

        workspaces = {w["workspace"]: w["duration_seconds"] for w in report["workspaces"]}
        assert "VS Code (no workspace)" in workspaces
        assert workspaces["VS Code (no workspace)"] == 600.0

    def test_no_double_counting_across_pc_sources(self):
        """Simultaneous browser and VS Code extension events are gated by watcher foreground; no double counting."""
        from tests.conftest import make_desktop_event, make_browser_event, make_vscode_event

        events = [
            # Watcher says Chrome 10:00 to 10:05, Code 10:05 to 10:10
            make_desktop_event(ts(10, 0), ts(10, 5), "Google Chrome", "Chrome"),
            make_desktop_event(ts(10, 5), ts(10, 10), "Code", "VS Code"),
            # Both extensions reported the entire 10:00 to 10:10 span
            make_browser_event(ts(10, 0), ts(10, 10), "github.com", "GitHub"),
            make_vscode_event(ts(10, 0), ts(10, 10), "repo", "main.py", "python"),
        ]

        report = aggregate_events(events)

        # Exactly 600s total, 300s browser, 300s vscode
        assert report["summary"]["total_active_seconds"] == 600.0
        assert report["summary"]["pc_active_seconds"] == 600.0
        assert report["summary"]["browser_seconds"] == 300.0
        assert report["summary"]["vscode_seconds"] == 300.0

    def test_desktop_session_keys_on_app_name_only_and_keeps_longest_held_title(self):
        """Desktop sessions key on app name only and preserve longest-held title despite unread count changes."""
        from tests.conftest import make_desktop_event

        events = [
            make_desktop_event(ts(10, 0), ts(10, 5), "Discord", "Discord | #general"),     # 300s
            make_desktop_event(ts(10, 5), ts(10, 6), "Discord", "Discord | (1) #general"), # 60s
            make_desktop_event(ts(10, 6), ts(10, 10), "Discord", "Discord | #general"),    # 240s
        ]

        report = aggregate_events(events)

        # Merges into 1 session because context key is ("desktop", "Discord")
        assert report["summary"]["session_count"] == 1
        assert report["summary"]["desktop_seconds"] == 600.0
        assert report["timeline"][0]["context"]["title"] == "Discord | #general"

    def test_mobile_overlaps_pc_timeline_with_pc_only_total(self):
        """Mobile is a separate lane overlapping PC timeline; pc_active_seconds and total_active_seconds match union."""
        from tests.conftest import make_desktop_event, make_mobile_event

        events = [
            # PC active 10:00 to 11:00 (3600s)
            make_desktop_event(ts(10, 0), ts(11, 0), "Antigravity", "IDE"),
            # Mobile active 10:30 to 11:30 (3600s)
            make_mobile_event(ts(10, 30), ts(11, 30), "YouTube", "com.google.android.youtube"),
        ]

        report = aggregate_events(events)

        assert report["summary"]["pc_active_seconds"] == 3600.0
        assert report["summary"]["desktop_seconds"] == 3600.0
        assert report["summary"]["mobile_seconds"] == 3600.0
        # Union covers 10:00 to 11:30 = 5400s
        assert report["summary"]["screen_seconds"] == 5400.0
        assert report["summary"]["total_active_seconds"] == 5400.0


# =============================================================================
# Phase 5 Tests: Report Cleanup, Hourly Interval Union, Storage FIFO, Phone IP
# =============================================================================
class TestPhase5ReportCleanupAndStorage:
    def test_storage_recent_ids_ordered_fifo(self, tmp_data_dir):
        """Storage _recent_ids uses an OrderedDict that preserves true FIFO order and evicts oldest."""
        import collector.storage as storage
        from collector.config import Config

        cfg = Config(data_directory=str(tmp_data_dir), raw_min_duration_seconds=2.0)

        # Clear existing state
        storage._recent_ids.clear()

        # Add 3 events
        e1 = {"id": "evt-1", "start": "2026-09-29T10:00:00+05:30", "duration_seconds": 10.0, "source": "desktop", "context": {}}
        e2 = {"id": "evt-2", "start": "2026-09-29T10:00:10+05:30", "duration_seconds": 10.0, "source": "desktop", "context": {}}
        e3 = {"id": "evt-3", "start": "2026-09-29T10:00:20+05:30", "duration_seconds": 10.0, "source": "desktop", "context": {}}

        assert storage.append_event(cfg, e1) is True
        assert storage.append_event(cfg, e2) is True
        assert storage.append_event(cfg, e3) is True

        # Duplicate ID should be rejected
        assert storage.append_event(cfg, e1) is False

        # Verify OrderedDict keys preserve insertion order
        keys = list(storage._recent_ids.keys())
        assert keys == ["evt-1", "evt-2", "evt-3"]

        # Simulate popitem eviction
        storage._recent_ids.popitem(last=False)
        assert "evt-1" not in storage._recent_ids
        assert "evt-2" in storage._recent_ids
        assert "evt-3" in storage._recent_ids

    def test_android_collector_requires_configured_phone_ip(self, monkeypatch):
        """sync_mobile_activity raises ValueError if device_ip / phone_ip is not configured."""
        from collector.android_collector import sync_mobile_activity

        monkeypatch.setattr("collector.android_collector.get_config", lambda: {"android": {}})
        monkeypatch.setattr("collector.android_collector.find_adb_executable", lambda: "fake_adb")

        import pytest
        with pytest.raises(ValueError, match="Android phone IP is not configured"):
            sync_mobile_activity(device_ip=None)

    def test_hourly_manual_seconds_union(self):
        """Overlapping manual events in an hour should have hourly manual_seconds
        computed by interval union, not sum."""
        events = [
            # Manual event 1: 14:00 to 14:30 (30 min = 1800s)
            {
                "id": "man-1",
                "start": ts(14, 0),
                "end": ts(14, 30),
                "duration_seconds": 1800.0,
                "source": "manual",
                "context": {"activity": "Reading", "category": "offline_study"}
            },
            # Manual event 2: 14:15 to 14:45 (30 min = 1800s)
            {
                "id": "man-2",
                "start": ts(14, 15),
                "end": ts(14, 45),
                "duration_seconds": 1800.0,
                "source": "manual",
                "context": {"activity": "Notes", "category": "offline_study"}
            },
        ]
        report = aggregate_events(events)
        hourly = {h["hour"]: h for h in report["hourly_breakdown"]}
        assert 14 in hourly
        # Union of [14:00, 14:30] and [14:15, 14:45] is [14:00, 14:45] = 45 min = 2700s
        assert hourly[14]["manual_seconds"] == 2700.0

    def test_data_quality_block_contents(self, tmp_data_dir):
        """data_quality contains sources_present, last_mobile_sync, fallback_ranges, watcher_offline_ranges, collector_offline_ranges."""
        from tests.conftest import make_desktop_event, make_mobile_event

        events = [
            make_desktop_event(ts(10, 0), ts(10, 10), "Antigravity", "IDE"),
            make_mobile_event(ts(12, 0), ts(12, 10), "WhatsApp", "com.whatsapp"),
        ]

        report = aggregate_events(events, data_directory=str(tmp_data_dir))
        dq = report["data_quality"]

        assert set(dq["sources_present"]) == {"desktop", "mobile"}
        assert "last_mobile_sync" in dq
        assert "watcher_offline_ranges" in dq
        assert "collector_offline_ranges" in dq
        assert "fallback_ranges" in dq
        assert isinstance(dq["collector_offline_ranges"], list)
        assert "context_switches" not in report["summary"]


# =============================================================================
# Phase 6 Tests: Shared-Secret Token Authentication & Restricted CORS
# =============================================================================
class TestPhase6SharedSecretAuthAndRestrictedCors:
    def test_restricted_cors_origins(self):
        """CORS allows known extension/webview/localhost origins and blocks unauthorized origins."""
        from collector.main import cors_headers
        from unittest.mock import Mock

        # Known browser extension origin
        req_chrome = Mock()
        req_chrome.headers = {"Origin": "chrome-extension://nkbihfbeogaeaoehlefnkodbefgpgknn"}
        h_chrome = cors_headers(req_chrome)
        assert h_chrome.get("Access-Control-Allow-Origin") == "chrome-extension://nkbihfbeogaeaoehlefnkodbefgpgknn"

        # Known VS Code webview origin
        req_vscode = Mock()
        req_vscode.headers = {"Origin": "vscode-webview://12345"}
        h_vscode = cors_headers(req_vscode)
        assert h_vscode.get("Access-Control-Allow-Origin") == "vscode-webview://12345"

        # Localhost origin
        req_local = Mock()
        req_local.headers = {"Origin": "http://localhost:3000"}
        h_local = cors_headers(req_local)
        assert h_local.get("Access-Control-Allow-Origin") == "http://localhost:3000"

        # Malicious / unauthorized external origin
        req_evil = Mock()
        req_evil.headers = {"Origin": "https://malicious-site.example.com"}
        h_evil = cors_headers(req_evil)
        assert "Access-Control-Allow-Origin" not in h_evil

    def test_auth_token_enforcement(self, monkeypatch):
        """When auth_token is configured, requests without it or with wrong token are rejected with 401."""
        import asyncio
        import collector.main as main_mod
        from aiohttp import web
        from unittest.mock import Mock

        async def _test():
            monkeypatch.setattr(main_mod.config, "auth_token", "super-secret-token-123")

            handler_called = False
            async def dummy_handler(req):
                nonlocal handler_called
                handler_called = True
                return web.json_response({"status": "ok"})

            # 1. Request without token -> 401
            req_no_auth = Mock(spec=web.Request)
            req_no_auth.method = "POST"
            req_no_auth.path = "/event"
            req_no_auth.headers = {}
            req_no_auth.query = {}

            resp1 = await main_mod.auth_and_cors_middleware(req_no_auth, dummy_handler)
            assert resp1.status == 401
            assert not handler_called

            # 2. Request with invalid token -> 401
            req_bad_auth = Mock(spec=web.Request)
            req_bad_auth.method = "POST"
            req_bad_auth.path = "/event"
            req_bad_auth.headers = {"Authorization": "Bearer wrong-token"}
            req_bad_auth.query = {}

            resp2 = await main_mod.auth_and_cors_middleware(req_bad_auth, dummy_handler)
            assert resp2.status == 401
            assert not handler_called

            # 3. Request with valid Authorization: Bearer -> 200
            req_valid_bearer = Mock(spec=web.Request)
            req_valid_bearer.method = "POST"
            req_valid_bearer.path = "/event"
            req_valid_bearer.headers = {"Authorization": "Bearer super-secret-token-123"}
            req_valid_bearer.query = {}

            resp3 = await main_mod.auth_and_cors_middleware(req_valid_bearer, dummy_handler)
            assert resp3.status == 200
            assert handler_called

            # 4. Request with valid X-Auth-Token header -> 200
            handler_called = False
            req_valid_x_auth = Mock(spec=web.Request)
            req_valid_x_auth.method = "POST"
            req_valid_x_auth.path = "/event"
            req_valid_x_auth.headers = {"X-Auth-Token": "super-secret-token-123"}
            req_valid_x_auth.query = {}

            resp4 = await main_mod.auth_and_cors_middleware(req_valid_x_auth, dummy_handler)
            assert resp4.status == 200
            assert handler_called

            # 5. Public health check does not require token -> 200
            handler_called = False
            req_health = Mock(spec=web.Request)
            req_health.method = "GET"
            req_health.path = "/health"
            req_health.headers = {}
            req_health.query = {}

            resp5 = await main_mod.auth_and_cors_middleware(req_health, dummy_handler)
            assert resp5.status == 200
            assert handler_called

        asyncio.run(_test())

