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
        saved_report_path = write_report(cfg, rep2, f"{date_str}.json")

        # Verify completely regenerated, not appended or duplicated
        assert rep2["summary"]["session_count"] == 2
        assert rep2["summary"]["total_active_seconds"] == 2100.0  # 900s + 1200s
        assert rep2["summary"]["browser_seconds"] == 900.0
        assert rep2["summary"]["vscode_seconds"] == 1200.0
        assert "context_switches" not in rep2["summary"]
        # Read saved report from disk to ensure clean overwrite
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

        ist = timezone(timedelta(hours=5, minutes=30))
        # Event creation
        evt = create_manual_event("2026-10-01", "23:25:51", "23:44:23", "Walk", "fitness", tz=ist)
        assert evt["start"] == "2026-10-01T23:25:51+05:30"
        assert evt["end"] == "2026-10-01T23:44:23+05:30"
        assert evt["duration_seconds"] == 1112.0  # 18 minutes 32 seconds

        # Text line parsing
        parsed = parse_text_line("23:25:51 - 23:44:23: Walk", "2026-10-01", tz=ist)
        assert parsed is not None
        assert parsed["duration_seconds"] == 1112.0
        assert parsed["context"]["activity"] == "Walk"

    def test_manual_hourly_separation(self):
        """Hours with only manual events report 0 active screen time in hourly breakdown."""
        from collector.manual_storage import create_manual_event

        ist = timezone(timedelta(hours=5, minutes=30))
        events = [
            create_manual_event("2026-10-01", "02:00:00", "10:00:00", "Sleep", "rest", tz=ist),
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

    def test_leftover_browser_time_preserves_desktop_window_title(self):
        """When extension misses events during active browser session, desktop watcher window title is preserved."""
        from tests.conftest import make_desktop_event, make_browser_event

        events = [
            # Desktop watcher says Chrome was foreground 10:00-10:15
            make_desktop_event(ts(10, 0), ts(10, 15), "Google Chrome", "Daily Analysis Prompt - Google Chrome"),
            # Extension event only recorded 10:00 to 10:05
            make_browser_event(ts(10, 0), ts(10, 5), "chatgpt.com", "Daily Analysis Prompt"),
        ]

        report = aggregate_events(events)

        assert report["summary"]["total_active_seconds"] == 900.0
        assert report["summary"]["browser_seconds"] == 900.0

        titles = {t["title"]: t["duration_seconds"] for t in report["titles"]}
        assert "Chrome (unknown page)" not in titles
        assert "Daily Analysis Prompt" in titles
        assert titles["Daily Analysis Prompt"] == 900.0

        domains = {d["domain"]: d["duration_seconds"] for d in report["domains"]}
        assert domains.get("chatgpt.com") == 900.0

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
    def test_restricted_cors_origins(self, monkeypatch):
        """Only allowed origins (browser extensions, VS Code webviews, localhost/null when auth_token set) receive Access-Control-Allow-Origin."""
        from collector.main import cors_headers
        from unittest.mock import Mock
        import collector.main as main_mod

        # Without auth_token: localhost origin is rejected
        monkeypatch.setattr(main_mod.config, "auth_token", "")
        req_local = Mock()
        req_local.headers = {"Origin": "http://localhost:3000"}
        h_local = cors_headers(req_local)
        assert "Access-Control-Allow-Origin" not in h_local

        # Known browser extension origin is allowed
        req_chrome = Mock()
        req_chrome.headers = {"Origin": "chrome-extension://nkbihfbeogaeaoehlefnkodbefgpgknn"}
        h_chrome = cors_headers(req_chrome)
        assert h_chrome.get("Access-Control-Allow-Origin") == "chrome-extension://nkbihfbeogaeaoehlefnkodbefgpgknn"

        # Known VS Code webview origin is allowed
        req_vscode = Mock()
        req_vscode.headers = {"Origin": "vscode-webview://12345"}
        h_vscode = cors_headers(req_vscode)
        assert h_vscode.get("Access-Control-Allow-Origin") == "vscode-webview://12345"

        # With auth_token set: localhost and null origins are allowed
        monkeypatch.setattr(main_mod.config, "auth_token", "super-secret-token")
        h_local_auth = cors_headers(req_local)
        assert h_local_auth.get("Access-Control-Allow-Origin") == "http://localhost:3000"

        req_null = Mock()
        req_null.headers = {"Origin": "null"}
        h_null = cors_headers(req_null)
        assert h_null.get("Access-Control-Allow-Origin") == "null"

        # Malicious / unauthorized external origin is always rejected
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


# =============================================================================
# Phase A Tests: Review Findings & Robustness
# =============================================================================
class TestPhaseADayBoundariesAndMidnightSpanning:
    def test_session_spanning_midnight_reads_d_minus_one_and_clips(self, tmp_path):
        """read_day_events for date D reads D-1 raw files and clips events to [D 00:00, D+1 00:00).
        Watcher event is in D-1 (23:50 to 00:30) and extension event is in D (00:05 to 00:25).
        """
        from reporting.generate_report import read_day_events, aggregate_events
        import json

        data_dir = tmp_path
        d_minus_1 = "2026-09-29"
        d = "2026-09-30"

        # Raw files structure
        p_raw_prev = data_dir / "raw" / "2026" / "sep" / "daily"
        p_raw_prev.mkdir(parents=True, exist_ok=True)

        # Watcher event spanning midnight: 23:50:00 on 2026-09-29 to 00:30:00 on 2026-09-30 (40 mins = 2400s)
        # Saved in D-1 raw file
        watcher_evt = {
            "id": "watcher-midnight-1",
            "start": "2026-09-29T23:50:00+05:30",
            "end": "2026-09-30T00:30:00+05:30",
            "duration_seconds": 2400.0,
            "source": "desktop",
            "context": {"app": "chrome", "process_name": "chrome.exe", "window_title": "YouTube"}
        }
        with open(p_raw_prev / f"{d_minus_1}.jsonl", "w", encoding="utf-8") as f:
            f.write(json.dumps(watcher_evt) + "\n")

        # Extension event on day D: 00:05:00 to 00:25:00 on 2026-09-30 (20 mins = 1200s)
        # Saved in D raw file
        ext_evt = {
            "id": "browser-midnight-1",
            "start": "2026-09-30T00:05:00+05:30",
            "end": "2026-09-30T00:25:00+05:30",
            "duration_seconds": 1200.0,
            "source": "browser",
            "context": {"browser": "chrome", "domain": "youtube.com", "title": "Lecture Video"}
        }
        with open(p_raw_prev / f"{d}.jsonl", "w", encoding="utf-8") as f:
            f.write(json.dumps(ext_evt) + "\n")

        # Read day D events
        events = read_day_events(str(data_dir), d)
        assert len(events) >= 2

        # The watcher event from D-1 must be clipped to start at 00:00:00 on D
        w_events = [e for e in events if e["source"] == "desktop"]
        assert len(w_events) == 1
        assert w_events[0]["start"] == "2026-09-30T00:00:00+05:30"
        assert w_events[0]["end"] == "2026-09-30T00:30:00+05:30"
        assert w_events[0]["duration_seconds"] == 1800.0  # 30 mins left on day D

        # Aggregate events for day D
        report = aggregate_events(events)
        assert report["summary"]["total_active_seconds"] == 1800.0  # 30 mins active on day D
        assert "domains" in report
        yt = next(dom for dom in report["domains"] if dom["domain"] == "youtube.com")
        assert yt["duration_seconds"] == 1200.0


class TestPhaseABrowserMediaAndAudibleOverride:
    def test_audible_media_overrides_idle_with_cap_and_locked_clips(self):
        """Audible browser video overrides idle intervals up to cap (7200s), but locked state always clips."""
        from reporting.generate_report import aggregate_events

        events = [
            # Foreground Chrome 10:00:00 to 11:30:00 (90 mins)
            {
                "id": "d-chrome",
                "start": "2026-09-29T10:00:00+05:30",
                "end": "2026-09-29T11:30:00+05:30",
                "duration_seconds": 5400.0,
                "source": "desktop",
                "context": {"app": "chrome", "process_name": "chrome.exe", "window_title": "Documentary"}
            },
            # Audible browser tab 10:00:00 to 11:30:00
            {
                "id": "b-yt",
                "start": "2026-09-29T10:00:00+05:30",
                "end": "2026-09-29T11:30:00+05:30",
                "duration_seconds": 5400.0,
                "source": "browser",
                "context": {"browser": "chrome", "domain": "youtube.com", "title": "Documentary", "audible": True}
            },
            # Idle from 10:10:00 to 11:00:00 (50 mins) - hands off keyboard/mouse
            {
                "id": "w-idle",
                "start": "2026-09-29T10:10:00+05:30",
                "end": "2026-09-29T11:00:00+05:30",
                "duration_seconds": 3000.0,
                "source": "desktop",
                "context": {"status": "idle", "app": "idle"}
            },
            # User locked screen from 11:15:00 to 11:25:00 (10 mins) - lock MUST clip
            {
                "id": "w-lock",
                "start": "2026-09-29T11:15:00+05:30",
                "end": "2026-09-29T11:25:00+05:30",
                "duration_seconds": 600.0,
                "source": "desktop",
                "context": {"status": "locked", "app": "locked"}
            }
        ]

        report = aggregate_events(events)
        # Total active time: 90 mins (5400s) minus 10 mins locked (600s) = 80 mins (4800s).
        # Idle was NOT deducted because video was audible!
        assert report["summary"]["total_active_seconds"] == 4800.0


class TestPhaseAVSCodeWorkspaceInheritance:
    def test_leftover_vscode_time_inherits_recent_workspace(self):
        """Leftover VS Code foreground time inherits most recent workspace within 30 min instead of becoming 'no workspace'."""
        from reporting.generate_report import aggregate_events

        events = [
            # Extension reported workspace 'ProjectX' from 10:00:00 to 10:15:00
            {
                "id": "v-1",
                "start": "2026-09-29T10:00:00+05:30",
                "end": "2026-09-29T10:15:00+05:30",
                "duration_seconds": 900.0,
                "source": "vscode",
                "context": {"workspace": "ProjectX"}
            },
            # Desktop watcher reports Code foreground from 10:00:00 to 10:35:00 (35 min)
            # Extension stopped sending events at 10:15:00 (e.g. reading docs or paused typing)
            # Leftover window 10:15:00 - 10:35:00 is 20 min (<= 30 min threshold)
            {
                "id": "d-code",
                "start": "2026-09-29T10:00:00+05:30",
                "end": "2026-09-29T10:35:00+05:30",
                "duration_seconds": 2100.0,
                "source": "desktop",
                "context": {"app": "code", "process_name": "code.exe", "window_title": "ProjectX - Visual Studio Code"}
            }
        ]

        report = aggregate_events(events)
        # Workspace should be ProjectX for the full 2100s, not 'no workspace'
        assert "workspaces" in report
        ws = report["workspaces"]
        assert len(ws) == 1
        assert ws[0]["workspace"] == "ProjectX"
        assert ws[0]["duration_seconds"] == 2100.0


class TestPhaseABrowserMatchingAnyBrowser:
    def test_any_browser_extension_fills_browser_foreground(self):
        """Browser extension events match any browser foreground window (e.g. Chrome extension event filling Brave window)."""
        from reporting.generate_report import aggregate_events

        events = [
            # Extension event says browser="chrome"
            {
                "id": "b-event",
                "start": "2026-09-29T10:00:00+05:30",
                "end": "2026-09-29T10:20:00+05:30",
                "duration_seconds": 1200.0,
                "source": "browser",
                "context": {"browser": "chrome", "domain": "github.com", "title": "GitHub Repo"}
            },
            # Watcher event says app="brave"
            {
                "id": "d-brave",
                "start": "2026-09-29T10:00:00+05:30",
                "end": "2026-09-29T10:20:00+05:30",
                "duration_seconds": 1200.0,
                "source": "desktop",
                "context": {"app": "brave", "process_name": "brave.exe", "window_title": "GitHub"}
            }
        ]

        report = aggregate_events(events)
        assert report["summary"]["total_active_seconds"] == 1200.0
        assert len(report["domains"]) == 1
        assert report["domains"][0]["domain"] == "github.com"
        assert report["domains"][0]["duration_seconds"] == 1200.0


class TestPhaseAAndroidMultiActivity:
    def test_android_multi_activity_transition_preserves_session(self):
        """Switching activities within same package (MainActivity -> TweetDetailActivity) does not cut session."""
        from collector.android_collector import parse_usagestats_events

        dev_tz = timezone(timedelta(hours=5, minutes=30))
        sample_dumpsys = """
time="2026-09-30 10:00:00" type=SCREEN_INTERACTIVE package=android
time="2026-09-30 10:00:05" type=KEYGUARD_HIDDEN package=android
time="2026-09-30 10:00:10" type=ACTIVITY_RESUMED package=com.twitter.android class=com.twitter.app.main.MainActivity
time="2026-09-30 10:02:00" type=ACTIVITY_PAUSED package=com.twitter.android class=com.twitter.app.main.MainActivity
time="2026-09-30 10:02:00" type=ACTIVITY_RESUMED package=com.twitter.android class=com.twitter.tweetdetail.TweetDetailActivity
time="2026-09-30 10:02:01" type=ACTIVITY_STOPPED package=com.twitter.android class=com.twitter.app.main.MainActivity
time="2026-09-30 10:05:00" type=ACTIVITY_PAUSED package=com.twitter.android class=com.twitter.tweetdetail.TweetDetailActivity
time="2026-09-30 10:05:01" type=ACTIVITY_STOPPED package=com.twitter.android class=com.twitter.tweetdetail.TweetDetailActivity
"""
        sessions = parse_usagestats_events(sample_dumpsys, dev_tz, min_duration_seconds=2.0)
        assert len(sessions) == 1
        s = sessions[0]
        assert s["context"]["app"] == "Twitter / X"
        assert s["start"] == "2026-09-30T10:00:10+05:30"
        assert s["end"] == "2026-09-30T10:05:01+05:30"
        assert s["duration_seconds"] == 291.0


class TestPhaseASecurityAndRedaction:
    def test_config_endpoint_redacts_auth_token(self):
        """The /config endpoint must redact the auth_token."""
        import asyncio
        from aiohttp import web
        from unittest.mock import Mock
        import collector.main as main_mod

        async def _test():
            orig_token = getattr(main_mod.config, "auth_token", None)
            try:
                main_mod.config.auth_token = "my-secret-token"
                req = Mock(spec=web.Request)
                req.headers = {}
                resp = await main_mod.handle_config(req)
                import json
                body = json.loads(resp.text)
                assert body["auth_token"] == "***REDACTED***"
            finally:
                main_mod.config.auth_token = orig_token

        asyncio.run(_test())


class TestPhaseAMinorRequirements:
    def test_manual_events_exempt_from_40s_filter(self):
        """Manual events with duration < 40s (e.g. 25s) are exempt from 40s min_duration filter."""
        from reporting.generate_report import aggregate_events

        events = [
            {
                "id": "manual-short-1",
                "start": "2026-09-29T10:00:00+05:30",
                "end": "2026-09-29T10:00:25+05:30",
                "duration_seconds": 25.0,
                "source": "manual",
                "context": {"activity": "Quick water break", "category": "personal"}
            }
        ]
        report = aggregate_events(events, min_session_duration=40.0)
        assert len(report["timeline"]) == 1
        assert report["timeline"][0]["context"]["activity"] == "Quick water break"
        assert report["summary"]["manual_seconds"] == 25.0

    def test_unobserved_seconds_capped_at_now_for_today(self):
        """For today, unobserved_seconds must be capped at elapsed seconds from midnight to now, not whole 86400s."""
        from reporting.generate_report import aggregate_events
        from datetime import datetime, timezone, timedelta

        now_local = datetime.now().astimezone()
        today_str = now_local.strftime("%Y-%m-%d")

        # Empty event list for today
        report = aggregate_events([], date_str=today_str)
        # Unobserved seconds should not be 86400 unless it's exactly 23:59:59
        day_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        elapsed = (now_local - day_start).total_seconds()
        assert report["summary"]["unobserved_seconds"] <= elapsed + 5.0
        assert report["summary"]["unobserved_seconds"] < 86400.0 or elapsed >= 86395.0


# =============================================================================
# Phase B Tests: Dashboard Template Refactor
# =============================================================================
class TestPhaseBDashboardTemplate:
    def test_dashboard_template_substitutes_cleanly_without_doubled_braces(self, tmp_path):
        """dashboard_template.html substitutes placeholders and contains no doubled braces."""
        from reporting.generate_dashboard import build_dashboard_html
        from pathlib import Path

        reports_data = {
            "2026-10-01": {
                "date": "2026-10-01",
                "summary": {"total_active_seconds": 3600.0, "session_count": 5},
                "timeline": [],
                "sources": {}
            }
        }
        analyses_data = {"2026-10-01": "# Test Note\nGood day."}

        html = build_dashboard_html(reports_data, analyses_data, "2026-10-01")
        assert "<!DOCTYPE html>" in html
        assert "const REPORTS_DATABASE = " in html
        assert "2026-10-01" in html
        assert "{{REPORTS_JSON}}" not in html
        assert "{{INITIAL_DATE}}" not in html

        # Check template file itself
        template_path = Path("reporting/dashboard_template.html")
        assert template_path.exists()
        with open(template_path, "r", encoding="utf-8") as f:
            template_text = f.read()

        # Placeholders exist in template
        assert "{{REPORTS_JSON}}" in template_text
        assert "{{INITIAL_DATE}}" in template_text

        # Verify no doubled braces {{ or }} in CSS/JS outside placeholders
        cleaned = template_text
        for p in ["{{REPORTS_JSON}}", "{{ANALYSES_JSON}}", "{{ANALYSES_HTML_JSON}}", "{{AUTH_TOKEN_JSON}}", "{{INITIAL_DATE}}"]:
            cleaned = cleaned.replace(p, "")
        assert "{{" not in cleaned
        assert "}}" not in cleaned


# =============================================================================
# Phase C Tests: daily_metrics in each day's report
# =============================================================================
class TestPhaseCDailyMetrics:
    def test_daily_metrics_structure_and_screen_activity(self):
        """daily_metrics contains first/last activity (screen only), active_seconds, pc_seconds, mobile_seconds, phone_share."""
        events = [
            # Manual event early morning (should NOT be first_activity)
            {
                "id": "man-1",
                "start": "2026-10-01T06:00:00+05:30",
                "end": "2026-10-01T06:30:00+05:30",
                "duration_seconds": 1800.0,
                "source": "manual",
                "context": {"activity": "Meditation", "category": "health"},
            },
            # PC screen event
            make_browser_event("2026-10-01T08:00:00+05:30", "2026-10-01T09:00:00+05:30", "github.com", "GitHub"),
            # Mobile screen event
            {
                "id": "mob-1",
                "start": "2026-10-01T09:30:00+05:30",
                "end": "2026-10-01T10:00:00+05:30",
                "duration_seconds": 1800.0,
                "source": "mobile",
                "context": {"app": "Twitter", "package": "com.twitter.android"},
            },
            # Manual event late evening (should NOT be last_activity)
            {
                "id": "man-2",
                "start": "2026-10-01T22:00:00+05:30",
                "end": "2026-10-01T22:30:00+05:30",
                "duration_seconds": 1800.0,
                "source": "manual",
                "context": {"activity": "Journaling", "category": "reflection"},
            },
        ]

        report = aggregate_events(events, date_str="2026-10-01")
        assert "daily_metrics" in report
        dm = report["daily_metrics"]

        # first_activity and last_activity are SCREEN activity only
        assert dm["first_activity"] == "2026-10-01T08:00:00+05:30"
        assert dm["last_activity"] == "2026-10-01T10:00:00+05:30"

        # Durations
        assert dm["pc_seconds"] == 3600.0
        assert dm["mobile_seconds"] == 1800.0
        assert dm["active_seconds"] == 5400.0
        assert dm["phone_share"] == round(1800.0 / 5400.0, 3)

    def test_focus_blocks_consecutive_pc_with_interruption_tolerance(self):
        """Focus block tolerates gaps/interruptions <= 60s, breaks on > 60s."""
        events = [
            # Block 1: VS Code 10:00 - 10:20 (1200s)
            make_vscode_event("2026-10-01T10:00:00+05:30", "2026-10-01T10:20:00+05:30", "my-project", "src/a.py", "python"),
            # Interruption: 30s gap (<= 60s)
            # Continuation of Block 1: VS Code 10:20:30 - 10:40:00 (1170s)
            make_vscode_event("2026-10-01T10:20:30+05:30", "2026-10-01T10:40:00+05:30", "my-project", "src/b.py", "python"),
            # Interruption: 5 minutes (> 60s)
            # Block 2: VS Code 10:45:00 - 11:00:00 (900s)
            make_vscode_event("2026-10-01T10:45:00+05:30", "2026-10-01T11:00:00+05:30", "my-project", "src/c.py", "python"),
        ]

        report = aggregate_events(events, date_str="2026-10-01")
        dm = report["daily_metrics"]
        assert dm["longest_focus_block"] is not None
        longest = dm["longest_focus_block"]
        assert longest["type"] == "workspace"
        assert longest["name"] == "my-project"
        assert longest["start"] == "2026-10-01T10:00:00+05:30"
        assert longest["end"] == "2026-10-01T10:40:00+05:30"
        assert longest["duration_seconds"] == 2370.0  # 1200 + 1170

        assert len(dm["top_3_focus_blocks"]) == 2
        assert dm["top_3_focus_blocks"][0]["duration_seconds"] == 2370.0
        assert dm["top_3_focus_blocks"][1]["duration_seconds"] == 900.0

    def test_late_night_screen_seconds(self):
        """late_night_screen_seconds measures screen union between 00:00 and 05:00 local."""
        events = [
            # PC screen 01:00 - 02:00 (3600s)
            make_browser_event("2026-10-01T01:00:00+05:30", "2026-10-01T02:00:00+05:30", "github.com", "GitHub"),
            # Mobile screen 01:30 - 02:30 (overlaps PC from 01:30 to 02:00)
            {
                "id": "mob-late",
                "start": "2026-10-01T01:30:00+05:30",
                "end": "2026-10-01T02:30:00+05:30",
                "duration_seconds": 3600.0,
                "source": "mobile",
                "context": {"app": "Reddit", "package": "com.reddit.frontpage"},
            },
            # Daytime screen 10:00 - 11:00 (outside 00:00-05:00)
            make_browser_event("2026-10-01T10:00:00+05:30", "2026-10-01T11:00:00+05:30", "docs.python.org", "Python Docs"),
        ]

        report = aggregate_events(events, date_str="2026-10-01")
        dm = report["daily_metrics"]
        # Union of 01:00-02:00 and 01:30-02:30 is 01:00-02:30 = 1.5 hours = 5400s
        assert dm["late_night_screen_seconds"] == 5400.0

    def test_sleep_inference_midnight_crossing(self):
        """Sleep inference across midnight: previous evening last activity to next morning first activity."""
        events = [
            # D-1 evening activity: ends at 23:30 (bedtime)
            make_browser_event("2026-09-30T22:30:00+05:30", "2026-09-30T23:30:00+05:30", "youtube.com", "YouTube"),
            # D-1 late phone use: ends at 23:25
            {
                "id": "mob-bed",
                "start": "2026-09-30T23:20:00+05:30",
                "end": "2026-09-30T23:25:00+05:30",
                "duration_seconds": 300.0,
                "source": "mobile",
                "context": {"app": "WhatsApp", "package": "com.whatsapp"},
            },
            # D morning phone use: starts at 07:35
            {
                "id": "mob-wake",
                "start": "2026-10-01T07:35:00+05:30",
                "end": "2026-10-01T07:45:00+05:30",
                "duration_seconds": 600.0,
                "source": "mobile",
                "context": {"app": "WhatsApp", "package": "com.whatsapp"},
            },
            # D morning PC activity: starts at 07:30 (wake time)
            make_vscode_event("2026-10-01T07:30:00+05:30", "2026-10-01T09:00:00+05:30", "my-project", "main.py", "python"),
        ]

        report = aggregate_events(events, date_str="2026-10-01")
        sleep = report["daily_metrics"]["sleep"]
        assert sleep["status"] == "ok"
        assert sleep["source"] == "inferred"
        assert sleep["bedtime"] == "2026-09-30T23:30:00+05:30"
        assert sleep["wake_time"] == "2026-10-01T07:30:00+05:30"
        assert sleep["duration_seconds"] == 8.0 * 3600  # 8 hours = 28800s
        assert sleep["last_phone_use_before_bedtime"] == "2026-09-30T23:25:00+05:30"
        assert sleep["first_phone_use_after_waking"] == "2026-10-01T07:35:00+05:30"

    def test_sleep_manual_override(self):
        """Manual 'Sleep' event wins over inferred inactive gaps."""
        events = [
            # Inferred gap would be 23:00 to 07:00
            make_browser_event("2026-09-30T22:00:00+05:30", "2026-09-30T23:00:00+05:30", "github.com", "GitHub"),
            make_browser_event("2026-10-01T07:00:00+05:30", "2026-10-01T08:00:00+05:30", "github.com", "GitHub"),
            # Explicit manual sleep event: 23:45 to 06:45
            {
                "id": "man-sleep",
                "start": "2026-09-30T23:45:00+05:30",
                "end": "2026-10-01T06:45:00+05:30",
                "duration_seconds": 7.0 * 3600,
                "source": "manual",
                "context": {"activity": "Sleep", "category": "rest"},
            }
        ]

        report = aggregate_events(events, date_str="2026-10-01")
        sleep = report["daily_metrics"]["sleep"]
        assert sleep["status"] == "ok"
        assert sleep["source"] == "manual"
        assert sleep["bedtime"] == "2026-09-30T23:45:00+05:30"
        assert sleep["wake_time"] == "2026-10-01T06:45:00+05:30"
        assert sleep["duration_seconds"] == 7.0 * 3600

    def test_sleep_insufficient_data(self):
        """Insufficient data flagged explicitly when previous evening is missing or gap < 3 hours."""
        # Only morning activity, no previous evening activity
        events = [
            make_browser_event("2026-10-01T08:00:00+05:30", "2026-10-01T10:00:00+05:30", "github.com", "GitHub"),
        ]
        report = aggregate_events(events, date_str="2026-10-01")
        sleep = report["daily_metrics"]["sleep"]
        assert sleep["status"] == "insufficient_data"
        assert "Missing" in sleep["reason"] or "Insufficient" in sleep["reason"]
        assert sleep["bedtime"] is None


# =============================================================================
# Phase D Tests: Labels (human-assigned, time-range based)
# =============================================================================
class TestPhaseDLabels:
    def test_labels_overlay_split_across_two_labels(self):
        """A single continuous session spanning two label ranges is split by time for accounting."""
        events = [
            # 2-hour continuous VS Code session: 09:00 to 11:00 (7200s)
            make_vscode_event("2026-10-01T09:00:00+05:30", "2026-10-01T11:00:00+05:30", "my-project", "main.py", "python"),
        ]
        analysis_md = """# Analysis
<!-- labels
{
  "energy": 4,
  "labels": [
    {"start": "09:00", "end": "10:00", "label": "build", "note": "Core logic", "planned": true},
    {"start": "10:00", "end": "11:00", "label": "practice", "note": "Testing", "planned": false}
  ]
}
-->
Today was productive.
"""
        report = aggregate_events(events, date_str="2026-10-01", analysis_text=analysis_md)
        assert "label_totals" in report
        lt = report["label_totals"]
        assert lt["build"]["duration_seconds"] == 3600.0
        assert lt["build"]["planned_seconds"] == 3600.0
        assert lt["practice"]["duration_seconds"] == 3600.0
        assert lt["practice"]["planned_seconds"] == 0.0

        assert report["labeled_seconds"] == 7200.0
        assert report["unlabeled_seconds"] == 0.0
        assert report["label_coverage_pct"] == 100.0
        assert report["labels"]["energy"] == 4

    def test_labels_partial_coverage_and_coverage_math(self):
        """Partial label coverage correctly computes labeled_seconds, unlabeled_seconds, and label_coverage_pct."""
        events = [
            # 4-hour active screen time: 10:00 to 14:00 (14400s)
            make_browser_event("2026-10-01T10:00:00+05:30", "2026-10-01T14:00:00+05:30", "github.com", "GitHub"),
        ]
        analysis_md = """<!-- labels
{
  "labels": [
    {"start": "10:00", "end": "11:00", "label": "learn", "planned": true}
  ]
}
-->"""
        report = aggregate_events(events, date_str="2026-10-01", analysis_text=analysis_md)
        assert report["label_totals"]["learn"]["duration_seconds"] == 3600.0
        assert report["labeled_seconds"] == 3600.0
        assert report["unlabeled_seconds"] == 10800.0
        assert report["label_coverage_pct"] == 25.0

    def test_overlapping_label_ranges_later_entry_wins(self):
        """Later entry wins rule for overlapping label ranges."""
        events = [
            make_vscode_event("2026-10-01T09:00:00+05:30", "2026-10-01T11:00:00+05:30", "my-project", "main.py", "python"),
        ]
        # Range 1: 09:00 - 11:00 (build)
        # Range 2: 10:00 - 10:30 (practice) - defined later, so it overwrites 10:00-10:30
        analysis_md = """<!-- labels
{
  "labels": [
    {"start": "09:00", "end": "11:00", "label": "build", "planned": true},
    {"start": "10:00", "end": "10:30", "label": "practice", "planned": true}
  ]
}
-->"""
        report = aggregate_events(events, date_str="2026-10-01", analysis_text=analysis_md)
        lt = report["label_totals"]
        # Practice gets 10:00 - 10:30 (30 min = 1800s)
        assert lt["practice"]["duration_seconds"] == 1800.0
        # Build gets 09:00 - 10:00 (3600s) + 10:30 - 11:00 (1800s) = 5400s
        assert lt["build"]["duration_seconds"] == 5400.0
        assert report["labeled_seconds"] == 7200.0

    def test_unknown_label_treated_as_other_and_warned(self):
        """Unknown label treated as 'other' and flagged in data_quality.label_warnings."""
        events = [
            make_browser_event("2026-10-01T10:00:00+05:30", "2026-10-01T11:00:00+05:30", "github.com", "GitHub"),
        ]
        analysis_md = """<!-- labels
{
  "labels": [
    {"start": "10:00", "end": "11:00", "label": "quantum-research", "planned": false}
  ]
}
-->"""
        report = aggregate_events(events, date_str="2026-10-01", analysis_text=analysis_md)
        assert report["label_totals"]["other"]["duration_seconds"] == 3600.0
        warnings = report["data_quality"]["label_warnings"]
        assert any("quantum-research" in w and "other" in w for w in warnings)

    def test_malformed_label_block_does_not_crash(self):
        """Malformed block produces a warning in data_quality, never a crash."""
        events = [
            make_browser_event("2026-10-01T10:00:00+05:30", "2026-10-01T11:00:00+05:30", "github.com", "GitHub"),
        ]
        analysis_md = """<!-- labels
{ this is clearly not valid json }
-->"""
        report = aggregate_events(events, date_str="2026-10-01", analysis_text=analysis_md)
        assert report["summary"]["total_active_seconds"] == 3600.0
        assert report["label_coverage_pct"] == 0.0
        warnings = report["data_quality"]["label_warnings"]
        assert len(warnings) > 0
        assert any("Malformed JSON" in w for w in warnings)

    def test_no_label_block_tolerant(self):
        """Tolerant of missing labels block without warnings or crash."""
        events = [
            make_browser_event("2026-10-01T10:00:00+05:30", "2026-10-01T11:00:00+05:30", "github.com", "GitHub"),
        ]
        analysis_md = "# Standard journal\nJust plain notes without labels."
        report = aggregate_events(events, date_str="2026-10-01", analysis_text=analysis_md)
        assert report["label_coverage_pct"] == 0.0
        assert report["unlabeled_seconds"] == 3600.0
        assert len(report["data_quality"]["label_warnings"]) == 0

    def test_timeline_entry_label_attribution(self):
        """Timeline entries get label if single label covers whole entry, else 'unlabeled', manual -> None."""
        events = [
            # Entry 1: 09:00 - 10:00 wholly covered by "build"
            make_vscode_event("2026-10-01T09:00:00+05:30", "2026-10-01T10:00:00+05:30", "p1", "a.py", "python"),
            # Entry 2: 10:00 - 11:00 partially covered by "practice" (10:00-10:30 only)
            make_browser_event("2026-10-01T10:00:00+05:30", "2026-10-01T11:00:00+05:30", "github.com", "GitHub"),
            # Entry 3: Manual event (keeps own category, label is None)
            {
                "id": "man-1",
                "start": "2026-10-01T11:30:00+05:30",
                "end": "2026-10-01T12:00:00+05:30",
                "duration_seconds": 1800.0,
                "source": "manual",
                "context": {"activity": "Gym", "category": "health"},
            }
        ]
        analysis_md = """<!-- labels
{
  "labels": [
    {"start": "09:00", "end": "10:00", "label": "build"},
    {"start": "10:00", "end": "10:30", "label": "practice"}
  ]
}
-->"""
        report = aggregate_events(events, date_str="2026-10-01", analysis_text=analysis_md)
        tl = report["timeline"]
        assert len(tl) == 3
        # Entry 1: wholly covered by "build" (100% >= 80%)
        assert tl[0]["label"] == "build"
        # Entry 2: only half covered by "practice" (50% < 80%) -> "mixed"
        assert tl[1]["label"] == "mixed"
        # Entry 3: manual event -> None
        assert tl[2]["label"] is None

    def test_session_spanning_two_labels_and_partly_unlabeled(self):
        """One session spanning two labels and partly unlabeled exports segments and strictly reconciles with label_totals."""
        events = [
            # Single 90-minute session from 10:00 to 11:30 (5400 seconds)
            make_vscode_event("2026-10-01T10:00:00+05:30", "2026-10-01T11:30:00+05:30", "proj", "main.py", "python"),
        ]
        analysis_md = """<!-- labels
{
  "labels": [
    {"start": "10:00", "end": "10:30", "label": "build", "planned": true},
    {"start": "10:30", "end": "11:00", "label": "practice", "planned": false}
  ]
}
-->"""
        report = aggregate_events(events, date_str="2026-10-01", analysis_text=analysis_md)

        # 1. Timeline checks
        tl = report["timeline"]
        assert len(tl) == 1
        assert tl[0]["duration_seconds"] == 5400.0
        # Spans across multiple labels (each 33% < 80%) -> label is "mixed"
        assert tl[0]["label"] == "mixed"
        # Timeline entry has NO segments attached (per-entry segments dropped)
        assert "segments" not in tl[0]

        # 2. Top-level segments stored once in report["label_segments"] (labels.segments dropped)
        assert "segments" not in report.get("labels", {})
        segments = report["label_segments"]
        assert len(segments) == 2
        assert segments[0]["label"] == "build"
        assert segments[0]["duration_seconds"] == 1800.0
        assert segments[0]["planned"] is True
        assert segments[1]["label"] == "practice"
        assert segments[1]["duration_seconds"] == 1800.0
        assert segments[1]["planned"] is False

        # 3. Strict reconciliation: sum of segments equals label_totals and labeled_seconds
        build_seg_sum = sum(s["duration_seconds"] for s in segments if s["label"] == "build")
        practice_seg_sum = sum(s["duration_seconds"] for s in segments if s["label"] == "practice")
        total_seg_sum = sum(s["duration_seconds"] for s in segments)

        assert report["label_totals"]["build"]["duration_seconds"] == build_seg_sum == 1800.0
        assert report["label_totals"]["build"]["planned_seconds"] == 1800.0
        assert report["label_totals"]["practice"]["duration_seconds"] == practice_seg_sum == 1800.0
        assert report["label_totals"]["practice"]["planned_seconds"] == 0.0
        assert report["labeled_seconds"] == total_seg_sum == 3600.0
        assert report["unlabeled_seconds"] == 1800.0
        assert report["summary"]["total_active_seconds"] == 5400.0
        assert report["label_coverage_pct"] == round(3600.0 / 5400.0 * 100, 1)  # 66.7%

    def test_strip_labels_block(self):
        """strip_labels_block removes hidden block before rendering markdown."""
        from reporting.generate_report import strip_labels_block

        text = """# Header
<!-- labels
{
  "energy": 3,
  "labels": []
}
-->
Paragraph content."""
        stripped = strip_labels_block(text)
        assert "<!-- labels" not in stripped
        assert "# Header" in stripped
        assert "Paragraph content." in stripped



# =============================================================================
# Offline Labels Tests: rest, eat, walk, social
# =============================================================================
class TestOfflineLabels:
    def test_infer_offline_label_rest(self):
        """Sleep, nap, and rest activities infer 'rest' label."""
        from collector.manual_storage import infer_offline_label

        assert infer_offline_label("Sleep", "rest") == "rest"
        assert infer_offline_label("Afternoon nap", "rest") == "rest"
        assert infer_offline_label("Power nap", "") == "rest"
        assert infer_offline_label("Resting", "other") == "rest"
        assert infer_offline_label("Random Activity", "rest") == "rest"

    def test_infer_offline_label_eat(self):
        """Breakfast, lunch, dinner, snack activities infer 'eat' label."""
        from collector.manual_storage import infer_offline_label

        assert infer_offline_label("Lunch", "meal") == "eat"
        assert infer_offline_label("Dinner", "meal") == "eat"
        assert infer_offline_label("Snacks", "meal") == "eat"
        assert infer_offline_label("Breakfast", "meal") == "eat"
        assert infer_offline_label("Brunch with friends", "") == "eat"
        assert infer_offline_label("Coffee break", "") == "eat"
        assert infer_offline_label("Random Activity", "meal") == "eat"
        assert infer_offline_label("Random Activity", "eat") == "eat"

    def test_infer_offline_label_walk(self):
        """Walk and stroll activities infer 'walk' label."""
        from collector.manual_storage import infer_offline_label

        assert infer_offline_label("Walk", "fitness") == "walk"
        assert infer_offline_label("Morning stroll", "fitness") == "walk"
        assert infer_offline_label("Walking to office", "") == "walk"

    def test_infer_offline_label_social(self):
        """Social activities like talking, calling, meeting infer 'social' label."""
        from collector.manual_storage import infer_offline_label

        assert infer_offline_label("talking with friends", "other") == "social"
        assert infer_offline_label("Team sync", "discussion") == "social"
        assert infer_offline_label("Phone call with mom", "other") == "social"
        assert infer_offline_label("Hangout with friends", "other") == "social"
        assert infer_offline_label("Random Activity", "discussion") == "social"

    def test_infer_offline_label_none_for_unmatched(self):
        """Activities that don't match any offline label return None."""
        from collector.manual_storage import infer_offline_label

        assert infer_offline_label("Gym", "health") is None
        assert infer_offline_label("Shower", "personal") is None
        assert infer_offline_label("Reading a book", "offline_study") is None
        assert infer_offline_label("Commute", "commute") is None

    def test_infer_offline_label_priority_eat_over_walk(self):
        """'Evening Dinner & Walk' with meal category should be 'eat', not 'walk'."""
        from collector.manual_storage import infer_offline_label

        # Category 'meal' wins (eat is checked before walk)
        assert infer_offline_label("Evening Dinner & Walk", "meal") == "eat"
        # Without meal category, 'dinner' keyword matches eat
        assert infer_offline_label("Dinner and Walk", "") == "eat"

    def test_manual_event_label_in_timeline(self):
        """Manual events in report timeline get auto-inferred offline labels."""
        events = [
            make_browser_event("2026-10-01T09:00:00+05:30", "2026-10-01T10:00:00+05:30", "github.com", "GitHub"),
            {
                "id": "man-sleep",
                "start": "2026-10-01T01:00:00+05:30",
                "end": "2026-10-01T09:00:00+05:30",
                "duration_seconds": 28800.0,
                "source": "manual",
                "context": {"activity": "Sleep", "category": "rest"},
            },
            {
                "id": "man-lunch",
                "start": "2026-10-01T12:30:00+05:30",
                "end": "2026-10-01T13:00:00+05:30",
                "duration_seconds": 1800.0,
                "source": "manual",
                "context": {"activity": "Lunch", "category": "meal"},
            },
            {
                "id": "man-walk",
                "start": "2026-10-01T17:00:00+05:30",
                "end": "2026-10-01T17:30:00+05:30",
                "duration_seconds": 1800.0,
                "source": "manual",
                "context": {"activity": "Walk", "category": "fitness"},
            },
            {
                "id": "man-chat",
                "start": "2026-10-01T20:00:00+05:30",
                "end": "2026-10-01T20:30:00+05:30",
                "duration_seconds": 1800.0,
                "source": "manual",
                "context": {"activity": "talking with friends", "category": "other"},
            },
            {
                "id": "man-gym",
                "start": "2026-10-01T16:00:00+05:30",
                "end": "2026-10-01T16:45:00+05:30",
                "duration_seconds": 2700.0,
                "source": "manual",
                "context": {"activity": "Gym", "category": "health"},
            },
        ]
        report = aggregate_events(events, date_str="2026-10-01")
        tl = report["timeline"]

        # Find manual entries by activity name
        manual_entries = {e["context"].get("activity", ""): e for e in tl if e["source"] == "manual"}

        assert manual_entries["Sleep"]["label"] == "rest"
        assert manual_entries["Lunch"]["label"] == "eat"
        assert manual_entries["Walk"]["label"] == "walk"
        assert manual_entries["talking with friends"]["label"] == "social"
        assert manual_entries["Gym"]["label"] is None  # No offline label match

    def test_manual_event_label_override_by_analysis_md(self):
        """Explicit analysis.md label overrides auto-inferred offline label for manual events."""
        events = [
            {
                "id": "man-walk",
                "start": "2026-10-01T17:00:00+05:30",
                "end": "2026-10-01T17:30:00+05:30",
                "duration_seconds": 1800.0,
                "source": "manual",
                "context": {"activity": "Walk", "category": "fitness"},
            },
        ]
        # Explicitly label the walk time as "leisure"
        analysis_md = """<!-- labels
{
  "labels": [
    {"start": "17:00", "end": "17:30", "label": "leisure", "planned": true}
  ]
}
-->"""
        report = aggregate_events(events, date_str="2026-10-01", analysis_text=analysis_md)
        tl = report["timeline"]
        assert len(tl) == 1
        # Should be "leisure" from explicit override, not "walk" from auto-inference
        assert tl[0]["label"] == "leisure"

    def test_offline_labels_in_allowed_labels(self):
        """Offline labels (rest, eat, walk, social) are in the global ALLOWED_LABELS."""
        from collector.config import ALLOWED_LABELS

        for lbl in ["rest", "eat", "walk", "social"]:
            assert lbl in ALLOWED_LABELS, f"{lbl} not in ALLOWED_LABELS"

    def test_offline_labels_in_typical_day_allowed(self):
        """Offline labels (rest, eat, walk, social) are in typical_day ALLOWED_LABELS."""
        from reporting.typical_day import ALLOWED_LABELS as TD_LABELS

        for lbl in ["rest", "eat", "walk", "social"]:
            assert lbl in TD_LABELS, f"{lbl} not in typical_day.ALLOWED_LABELS"

    def test_focus_vs_drift_with_offline_neutral(self):
        """Offline labels (rest, eat, walk, social) are neutral in Focus vs Drift."""
        from reporting.typical_day import aggregate_focus_vs_drift, ALLOWED_LABELS

        total_bins = 96
        bin_width = 900  # 15 min
        # Create a fake cached day with only 'rest' and 'eat' labels
        day = {
            "date": "2026-10-01",
            "screen_seconds": [0.0] * total_bins,
            "pc_seconds": [0.0] * total_bins,
            "mobile_seconds": [0.0] * total_bins,
            "label_seconds": {lbl: [0.0] * total_bins for lbl in ALLOWED_LABELS},
            "planned_label_seconds": {lbl: [0.0] * total_bins for lbl in ALLOWED_LABELS},
            "unplanned_label_seconds": {lbl: [0.0] * total_bins for lbl in ALLOWED_LABELS},
            "coverage_pct": 80.0,
            "sleep_metrics": {},
        }
        # Put 900s of "rest" in bin 0, 900s of "eat" in bin 48 (noon)
        day["label_seconds"]["rest"][0] = 900.0
        day["label_seconds"]["eat"][48] = 900.0
        day["screen_seconds"][0] = 900.0
        day["screen_seconds"][48] = 900.0

        result = aggregate_focus_vs_drift(
            cached_days=[day],
            bin_minutes=15,
            axis_start_hour=0,
            min_coverage_pct=60.0,
            unplanned_only=False,
        )

        assert result["qualified_days_count"] == 1
        # Focus and drift should be 0 (rest and eat are neutral)
        assert result["avg_focus_hours"] == 0.0
        assert result["avg_drift_hours"] == 0.0
        # Neutral bins should have the values
        assert result["avg_neutral_minutes"][0] == 15.0  # 900s / 60
        assert result["avg_neutral_minutes"][48] == 15.0


# =============================================================================
# Report Optimization & Lean Chat Report Tests
# =============================================================================
class TestReportOptimizationAndLeanChatReport:
    def test_one_timezone_consistency(self):
        """Every timestamp in both full report and chat report uses the same local offset, including label_segments."""
        from reporting.generate_report import build_chat_report
        import re

        events = [
            make_vscode_event("2026-10-01T10:00:00+05:30", "2026-10-01T11:00:00+05:30", "proj", "main.py", "python"),
        ]
        analysis_md = '<!-- labels\n{"labels": [{"start": "10:00", "end": "10:30", "label": "build"}]}\n-->'
        report = aggregate_events(events, date_str="2026-10-01", analysis_text=analysis_md)
        chat = build_chat_report(report)

        # Check label_segments in full report uses local offset +05:30, not UTC
        assert len(report["label_segments"]) == 1
        seg = report["label_segments"][0]
        assert seg["start"] == "2026-10-01T10:00:00+05:30"
        assert seg["end"] == "2026-10-01T10:30:00+05:30"

        # Check all timestamps across both reports
        iso_pat = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
        def verify_tz(obj, name):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    verify_tz(v, f"{name}.{k}")
            elif isinstance(obj, list):
                for i, it in enumerate(obj):
                    verify_tz(it, f"{name}[{i}]")
            elif isinstance(obj, str) and iso_pat.match(obj):
                assert obj.endswith("+05:30"), f"Timestamp in {name} does not have local offset +05:30: {obj}"
                assert "+00:00" not in obj and not obj.endswith("Z"), f"UTC offset found in {name}: {obj}"

        verify_tz(report, "full_report")
        verify_tz(chat, "chat_report")

    def test_round_timestamps_to_seconds_no_microseconds(self):
        """All timestamps in both reports are rounded to seconds with no microseconds."""
        from reporting.generate_report import build_chat_report
        import re

        events = [
            make_vscode_event("2026-10-01T10:00:00.456789+05:30", "2026-10-01T11:00:00.890123+05:30", "proj", "main.py", "python"),
        ]
        analysis_md = '<!-- labels\n{"labels": [{"start": "10:00", "end": "10:30", "label": "build"}]}\n-->'
        report = aggregate_events(events, date_str="2026-10-01", analysis_text=analysis_md)
        chat = build_chat_report(report)

        iso_pat = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
        micro_pat = re.compile(r"\.\d+")
        def verify_no_micro(obj, name):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    verify_no_micro(v, f"{name}.{k}")
            elif isinstance(obj, list):
                for i, it in enumerate(obj):
                    verify_no_micro(it, f"{name}[{i}]")
            elif isinstance(obj, str) and iso_pat.match(obj):
                assert not micro_pat.search(obj), f"Microseconds found in {name}: {obj}"

        verify_no_micro(report, "full_report")
        verify_no_micro(chat, "chat_report")

    def test_merge_data_quality_ranges_under_60s(self):
        """Fallback and watcher-offline ranges less than 60s apart are merged in full report."""
        from reporting.generate_report import merge_data_quality_ranges
        tz = timezone(timedelta(hours=5, minutes=30))
        r1 = {"start": "2026-10-01T10:00:00+05:30", "end": "2026-10-01T10:05:00+05:30"}
        r2 = {"start": "2026-10-01T10:05:30+05:30", "end": "2026-10-01T10:10:00+05:30"}  # 30s gap -> merge
        r3 = {"start": "2026-10-01T10:12:00+05:30", "end": "2026-10-01T10:15:00+05:30"}  # 120s gap -> separate
        merged = merge_data_quality_ranges([r1, r2, r3], tz, gap_threshold_seconds=60.0)
        assert len(merged) == 2
        assert merged[0]["start"] == "2026-10-01T10:00:00+05:30"
        assert merged[0]["end"] == "2026-10-01T10:10:00+05:30"
        assert merged[0]["duration_seconds"] == 600.0
        assert merged[1]["start"] == "2026-10-01T10:12:00+05:30"
        assert merged[1]["end"] == "2026-10-01T10:15:00+05:30"
        assert merged[1]["duration_seconds"] == 180.0

    def test_remove_duplication_full_report(self):
        """Top-level label_segments is stored once; per-entry segments, labels.segments and duplicated label fields are dropped."""
        events = [
            make_vscode_event("2026-10-01T10:00:00+05:30", "2026-10-01T11:00:00+05:30", "proj", "main.py", "python"),
        ]
        analysis_md = '<!-- labels\n{"energy": 4, "labels": [{"start": "10:00", "end": "11:00", "label": "build"}]}\n-->'
        report = aggregate_events(events, date_str="2026-10-01", analysis_text=analysis_md)

        # 1. label_segments at top level
        assert "label_segments" in report
        assert len(report["label_segments"]) == 1

        # 2. No per-entry segments in timeline
        assert len(report["timeline"]) == 1
        assert "segments" not in report["timeline"][0]
        assert report["timeline"][0]["label"] == "build"

        # 3. No labels.segments
        assert "segments" not in report["labels"]

        # 4. label_totals, labeled_seconds, unlabeled_seconds, label_coverage_pct kept in one place only (top level)
        assert "label_totals" in report
        assert "labeled_seconds" in report
        assert "unlabeled_seconds" in report
        assert "label_coverage_pct" in report
        assert "label_totals" not in report["labels"]
        assert "labeled_seconds" not in report["labels"]
        assert "unlabeled_seconds" not in report["labels"]
        assert "label_coverage_pct" not in report["labels"]
        assert report["labels"] == {"energy": 4}

    def test_compact_json_and_pretty_flag(self, tmp_data_dir):
        """write_report writes compact single-line JSON by default, and indented JSON when pretty=True."""
        from collector.config import Config
        from reporting.generate_report import write_report
        cfg = Config(data_directory=str(tmp_data_dir))
        events = [
            make_vscode_event("2026-10-01T10:00:00+05:30", "2026-10-01T10:30:00+05:30", "proj", "main.py", "python"),
        ]
        report = aggregate_events(events, date_str="2026-10-01")
        report["date"] = "2026-10-01"

        # Default compact
        path1 = write_report(cfg, report, "2026-10-01.json", pretty=False)
        with open(path1, "r", encoding="utf-8") as f:
            lines1 = f.readlines()
        assert len(lines1) == 1, "Compact JSON report must be a single line"

        chat_path = path1.replace(".json", ".chat.json")
        with open(chat_path, "r", encoding="utf-8") as f:
            chat_lines = f.readlines()
        assert len(chat_lines) == 1, "Compact chat report must be a single line"

        # Pretty flag
        path2 = write_report(cfg, report, "2026-10-01.json", pretty=True)
        with open(path2, "r", encoding="utf-8") as f:
            lines2 = f.readlines()
        assert len(lines2) > 10, "Pretty report must have indentation and multiple lines"

    def test_chat_report_structure_and_omissions(self):
        """Chat report contains required lean sections and omits raw_event_count, segments, longest_sessions, hourly_breakdown, offline ranges."""
        from reporting.generate_report import build_chat_report
        import re

        events = [
            make_browser_event("2026-10-01T10:00:00+05:30", "2026-10-01T10:30:00+05:30", "github.com", "GitHub PR", event_id="b1"),
            {
                "id": "man-1",
                "start": "2026-10-01T12:00:00+05:30",
                "end": "2026-10-01T13:00:00+05:30",
                "duration_seconds": 3600.0,
                "source": "manual",
                "context": {"activity": "Walk", "category": "walk"},
            },
        ]
        report = aggregate_events(events, date_str="2026-10-01")
        report["date"] = "2026-10-01"
        chat = build_chat_report(report)

        # Required fields present
        for req in ["date", "summary", "daily_metrics", "label_totals", "label_coverage_pct", "sources", "titles", "domains", "apps", "desktop_apps", "manual_events", "timeline", "data_quality"]:
            assert req in chat, f"Missing required field {req} in chat report"

        # Omitted sections
        assert "longest_sessions" not in chat
        assert "hourly_breakdown" not in chat
        assert "raw_event_count" not in chat
        assert "watcher_offline_ranges" not in chat["data_quality"]
        assert "fallback_ranges" not in chat["data_quality"]
        assert "collector_offline_ranges" not in chat["data_quality"]

        # Condensed data_quality fields
        dq = chat["data_quality"]
        assert "sources_present" in dq
        assert "last_mobile_sync" in dq
        assert "total_fallback_seconds" in dq
        assert "fallback_count" in dq
        assert "total_watcher_offline_seconds" in dq
        assert "watcher_offline_count" in dq
        assert "label_warnings" in dq

        # Timeline compact rows
        tl = chat["timeline"]
        assert len(tl) >= 2  # header + at least 1 entry
        assert tl[0] == ["start", "end", "duration", "source", "name", "domain", "label"]
        time_pat = re.compile(r"^\d{2}:\d{2}:\d{2}$")
        for row in tl[1:]:
            assert time_pat.match(row[0]), f"Timeline start must be HH:MM:SS, got {row[0]}"
            assert time_pat.match(row[1]), f"Timeline end must be HH:MM:SS, got {row[1]}"

        # Manual events
        assert len(chat["manual_events"]) == 1
        me = chat["manual_events"][0]
        assert me["activity"] == "Walk"
        assert me["duration"] == 3600.0
        assert "start" in me and "end" in me

    def test_heavy_day_chat_report_under_30kb_and_totals_match(self):
        """Chat report for a heavy day with ~165 timeline entries stays under 30 KB (and target < 25 KB) and totals match."""
        from collector.config import get_config
        from reporting.generate_report import generate_single_day_report, build_chat_report
        cfg = get_config()
        # 2026-10-02 has 165 timeline entries
        report = generate_single_day_report(cfg, "2026-10-02")
        assert len(report["timeline"]) >= 150, f"Expected ~165 timeline entries, got {len(report['timeline'])}"

        chat = build_chat_report(report)
        chat_json = json.dumps(chat, separators=(",", ":"), ensure_ascii=False)
        chat_size_bytes = len(chat_json.encode("utf-8"))

        # Under 30 KB and under target 25 KB
        assert chat_size_bytes < 30 * 1024, f"Chat report size {chat_size_bytes} exceeds 30 KB"
        assert chat_size_bytes < 25 * 1024, f"Chat report size {chat_size_bytes} exceeds target 25 KB"

        # Totals match full report
        assert chat["summary"]["screen_seconds"] == report["summary"]["screen_seconds"]
        assert chat["summary"]["browser_seconds"] == report["summary"]["browser_seconds"]
        assert chat["summary"]["vscode_seconds"] == report["summary"]["vscode_seconds"]
        assert chat["summary"]["mobile_seconds"] == report["summary"]["mobile_seconds"]
        assert chat["summary"]["desktop_seconds"] == report["summary"]["desktop_seconds"]
        assert chat["summary"]["manual_seconds"] == report["summary"]["manual_seconds"]
        assert chat["summary"]["brief_seconds"] == report["summary"]["brief_seconds"]
        assert chat["summary"]["brief_session_count"] == report["summary"]["brief_session_count"]
        assert chat["label_totals"] == report["label_totals"]
        assert chat["label_coverage_pct"] == report["label_coverage_pct"]
        assert chat["sources"] == report["sources"]
        assert chat["data_quality"]["total_fallback_seconds"] == round(sum(r["duration_seconds"] for r in report["data_quality"]["fallback_ranges"]), 1)
        assert chat["data_quality"]["total_watcher_offline_seconds"] == round(sum(r["duration_seconds"] for r in report["data_quality"]["watcher_offline_ranges"]), 1)

    def test_labeled_time_on_screen_union_prevents_coverage_over_100(self):
        """Labels resolved non-overlapping and applied to the union of PC and phone screen time
        so each minute gets one label and is counted once. label_coverage_pct <= 100, sum(label_totals) <= screen_seconds."""
        # Overlapping PC and mobile screen time:
        # PC active 10:00 to 11:00 (3600s)
        # Mobile active 10:30 to 11:30 (3600s)
        # Screen union covers 10:00 to 11:30 = 5400s
        events = [
            make_vscode_event("2026-10-01T10:00:00+05:30", "2026-10-01T11:00:00+05:30", "proj", "main.py", "python"),
            {
                "id": "mob-overlap",
                "start": "2026-10-01T10:30:00+05:30",
                "end": "2026-10-01T11:30:00+05:30",
                "duration_seconds": 3600.0,
                "source": "mobile",
                "context": {"app": "Twitter", "package": "com.twitter.android"},
            },
        ]
        # Label covers the entire span 10:00 to 11:30 (5400s)
        analysis_md = """<!-- labels
{
  "labels": [
    {"start": "10:00", "end": "11:30", "label": "build"}
  ]
}
-->"""
        report = aggregate_events(events, date_str="2026-10-01", analysis_text=analysis_md)

        # Screen seconds is the union: 5400s
        assert report["summary"]["screen_seconds"] == 5400.0
        # Labeled seconds must NOT double-count the 10:30-11:00 overlap (which would be 7200s without union)
        assert report["labeled_seconds"] == 5400.0
        assert report["unlabeled_seconds"] == 0.0
        assert report["label_coverage_pct"] == 100.0
        # Sum of label_totals doesn't exceed screen_seconds
        sum_totals = sum(v["duration_seconds"] for v in report["label_totals"].values())
        assert sum_totals == 5400.0
        assert sum_totals <= report["summary"]["screen_seconds"]
        assert report["label_coverage_pct"] <= 100.0

    def test_timeline_label_largest_share_80_percent_rule(self):
        """Timeline label per entry is the label that covers >=80% of the entry, otherwise 'mixed'.
        Exact per-slice labels remain in label_segments in the full report."""
        events = [
            # Entry 1: 10:00 to 11:00 (3600s). "build" covers 10:00 to 10:50 (3000s = 83.3% >= 80%).
            make_vscode_event("2026-10-01T10:00:00+05:30", "2026-10-01T11:00:00+05:30", "proj", "main.py", "python"),
            # Entry 2: 11:00 to 12:00 (3600s). "build" covers 11:00 to 11:45 (2700s = 75% < 80%), "practice" 11:45 to 12:00 (900s = 25%).
            make_vscode_event("2026-10-01T11:00:00+05:30", "2026-10-01T12:00:00+05:30", "proj2", "main.py", "python"),
            # Entry 3: 12:00 to 13:00 (3600s). No labels at all -> "unlabeled".
            make_browser_event("2026-10-01T12:00:00+05:30", "2026-10-01T13:00:00+05:30", "docs.python.org", "Python Docs"),
            # Entry 4: 13:00 to 14:00 (3600s). "learn" covers 13:00 to 13:30 (1800s = 50% < 80%), rest unlabeled -> "mixed".
            make_browser_event("2026-10-01T13:00:00+05:30", "2026-10-01T14:00:00+05:30", "github.com", "GitHub"),
        ]
        analysis_md = """<!-- labels
{
  "labels": [
    {"start": "10:00", "end": "10:50", "label": "build"},
    {"start": "11:00", "end": "11:45", "label": "build"},
    {"start": "11:45", "end": "12:00", "label": "practice"},
    {"start": "13:00", "end": "13:30", "label": "learn"}
  ]
}
-->"""
        report = aggregate_events(events, date_str="2026-10-01", analysis_text=analysis_md)
        tl = report["timeline"]

        # Entry 1: 83.3% build -> "build"
        assert tl[0]["label"] == "build"
        # Entry 2: 75% build, 25% practice -> neither >= 80% -> "mixed"
        assert tl[1]["label"] == "mixed"
        # Entry 3: 0% labels -> "unlabeled"
        assert tl[2]["label"] == "unlabeled"
        # Entry 4: 50% learn, 50% unlabeled -> largest share 50% < 80% -> "mixed"
        assert tl[3]["label"] == "mixed"

        # Exact per-slice labels remain in label_segments in full report
        assert len(report["label_segments"]) == 4
        assert [s["label"] for s in report["label_segments"]] == ["build", "build", "practice", "learn"]
