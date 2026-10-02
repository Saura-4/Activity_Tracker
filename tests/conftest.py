"""
Pytest fixtures for activity tracker tests.
"""
import json
import os
import tempfile
import uuid
from pathlib import Path
from datetime import datetime, timezone, timedelta

import pytest


@pytest.fixture
def tmp_data_dir(tmp_path):
    """Create a temporary data directory mimicking D:\\ActivityTracker."""
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    report_dir = tmp_path / "report"
    report_dir.mkdir()
    return tmp_path


@pytest.fixture
def tz():
    """Return a fixed timezone offset (+05:30 IST) for consistent tests."""
    return timezone(timedelta(hours=5, minutes=30))


def make_browser_event(
    start: str,
    end: str,
    domain: str,
    title: str,
    url: str = "",
    tab_id: int = 1,
    window_id: int = 1,
    event_id: str = None
) -> dict:
    """Create a browser activity event dict.
    
    Args:
        start: ISO-8601 start timestamp
        end: ISO-8601 end timestamp
        domain: Domain (e.g., 'github.com')
        title: Page title
        url: Full URL (defaults to https://{domain}/)
        tab_id: Tab identifier
        window_id: Window identifier
        event_id: Optional UUID; auto-generated if not provided
    """
    if not url:
        url = f"https://{domain}/"
    if not event_id:
        event_id = str(uuid.uuid4())

    start_dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
    end_dt = datetime.fromisoformat(end.replace('Z', '+00:00'))
    duration = (end_dt - start_dt).total_seconds()

    return {
        "id": event_id,
        "start": start,
        "end": end,
        "duration_seconds": duration,
        "source": "browser",
        "context": {
            "browser": "chrome",
            "domain": domain,
            "title": title,
            "url": url,
            "tab_id": tab_id,
            "window_id": window_id
        }
    }


def make_vscode_event(
    start: str,
    end: str,
    workspace: str,
    file: str = "",
    language: str = "",
    event_id: str = None
) -> dict:
    """Create a VS Code activity event dict."""
    if not event_id:
        event_id = str(uuid.uuid4())

    start_dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
    end_dt = datetime.fromisoformat(end.replace('Z', '+00:00'))
    duration = (end_dt - start_dt).total_seconds()

    ctx = {"workspace": workspace}
    if file:
        ctx["file"] = file
    if language:
        ctx["language"] = language

    return {
        "id": event_id,
        "start": start,
        "end": end,
        "duration_seconds": duration,
        "source": "vscode",
        "context": ctx
    }


def make_mobile_event(
    start: str,
    end: str,
    app: str,
    package: str,
    event_id: str = None
) -> dict:
    """Create a mobile app activity event dict."""
    if not event_id:
        event_id = str(uuid.uuid4())

    start_dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
    end_dt = datetime.fromisoformat(end.replace('Z', '+00:00'))
    duration = (end_dt - start_dt).total_seconds()

    return {
        "id": event_id,
        "start": start,
        "end": end,
        "duration_seconds": duration,
        "source": "mobile",
        "context": {
            "app": app,
            "package": package
        }
    }


def make_desktop_event(
    start: str,
    end: str,
    app: str,
    title: str,
    event_id: str = None
) -> dict:
    """Create a desktop app activity event dict."""
    if not event_id:
        event_id = str(uuid.uuid4())

    start_dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
    end_dt = datetime.fromisoformat(end.replace('Z', '+00:00'))
    duration = (end_dt - start_dt).total_seconds()

    return {
        "id": event_id,
        "start": start,
        "end": end,
        "duration_seconds": duration,
        "source": "desktop",
        "context": {
            "app": app,
            "title": title
        }
    }


def write_events_to_jsonl(filepath: str, events: list):
    """Write a list of event dicts to a JSONL file."""
    with open(filepath, "w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")

