"""
Manual Activity Storage & Parser for Activity Tracker

Handles reading, writing, and parsing human-entered offline activities
(e.g., afternoon naps, sleep, meals, workouts) from Record/manual/...
"""

import json
import uuid
import re
from pathlib import Path
from datetime import datetime, date, timedelta, timezone
from typing import Dict, Any, List, Optional

DEFAULT_TZ = datetime.now().astimezone().tzinfo or timezone.utc

CATEGORY_KEYWORDS = {
    "rest": ["nap", "sleep", "rest", "lie down", "power nap", "doze", "resting"],
    "meal": ["lunch", "dinner", "breakfast", "brunch", "snack", "snacks", "coffee", "tea", "eating", "food", "cooking"],
    "fitness": ["gym", "workout", "walk", "walking", "run", "running", "yoga", "exercise", "cycling", "stretching"],
    "discussion": ["discussion", "meeting", "sync", "call", "chat", "talk", "1:1", "one-on-one", "discuss", "brainstorm"],
    "offline_study": ["reading", "book", "paper", "study", "notes", "lecture", "whiteboard", "deep reading"],
    "commute": ["commute", "travel", "traveling", "drive", "driving", "transit", "metro", "bus", "flight"],
    "personal": ["shower", "bath", "grooming", "cleaning", "chores", "family", "errand", "errands"],
}

def infer_category(activity_name: str) -> str:
    """Infer a high-level category from the activity name if not explicitly specified."""
    lower = activity_name.lower().strip()
    for cat, keywords in CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if re.search(r'\b' + re.escape(kw) + r'\b', lower):
                return cat
    return "other"


def infer_offline_label(activity_name: str, category: str = "") -> Optional[str]:
    """Infer an offline label (rest, eat, walk, social) from activity name and category.

    Returns one of 'rest', 'eat', 'walk', 'social', or None if no match.
    Used for hybrid ingestion of manual/offline events into the label system.
    """
    act = (activity_name or "").lower().strip()
    cat = (category or "").lower().strip()

    # 1. Rest (sleep, nap, rest, doze, lie down)
    if cat == "rest" or any(
        re.search(r'\b' + re.escape(w) + r'\b', act)
        for w in ['nap', 'sleep', 'rest', 'power nap', 'doze', 'resting', 'lie down']
    ):
        return "rest"

    # 2. Eat (breakfast, lunch, dinner, snack, brunch, eating, meal, food, coffee, tea)
    if cat in ('meal', 'eat', 'food') or any(
        re.search(r'\b' + re.escape(w) + r'\b', act)
        for w in [
            'breakfast', 'lunch', 'dinner', 'snack', 'snacks', 'brunch',
            'eating', 'food', 'meal', 'coffee', 'tea', 'cooking',
        ]
    ):
        return "eat"

    # 3. Walk (walk, walking, stroll, strolling)
    if any(
        re.search(r'\b' + re.escape(w) + r'\b', act)
        for w in ['walk', 'walking', 'stroll', 'strolling']
    ):
        return "walk"

    # 4. Social (talk, friends, hangout, discussion, call, chat, sync, meeting)
    if cat in ('discussion', 'social') or any(
        re.search(r'\b' + re.escape(w) + r'\b', act)
        for w in [
            'talk', 'talking', 'friends', 'friend', 'hangout', 'discussion',
            'discuss', 'call', 'phone', 'chat', 'sync', '1:1', 'one-on-one',
            'meeting', 'brainstorm',
        ]
    ):
        return "social"

    return None


def get_manual_dir(data_dir: str, dt_or_date_str: Any) -> Path:
    """Compute structured path: Record/manual/YYYY/mmm/daily/"""
    if isinstance(dt_or_date_str, str):
        d = date.fromisoformat(dt_or_date_str)
    elif isinstance(dt_or_date_str, datetime):
        d = dt_or_date_str.date()
    else:
        d = dt_or_date_str
        
    year = str(d.year)
    month = d.strftime("%b").lower()
    p = Path(data_dir) / "manual" / year / month / "daily"
    p.mkdir(parents=True, exist_ok=True)
    return p


def parse_time_str(time_str: str) -> tuple[int, int, int]:
    """Parse time string like '13:00', '13:00:32', '1:00pm', '1pm', '9:30am' into (hour, minute, second)."""
    s = time_str.strip().lower()
    is_pm = "pm" in s
    is_am = "am" in s
    s = s.replace("am", "").replace("pm", "").strip()

    parts = s.split(":")
    hour = int(parts[0])
    minute = int(parts[1]) if len(parts) > 1 else 0
    second = int(parts[2]) if len(parts) > 2 else 0

    if is_pm and hour < 12:
        hour += 12
    elif is_am and hour == 12:
        hour = 0

    return hour, minute, second


def create_manual_event(
    date_str: str,
    start_time: str,
    end_time: str,
    activity: str,
    category: Optional[str] = None,
    notes: str = "",
    tz: timezone = DEFAULT_TZ,
) -> Dict[str, Any]:
    """Construct a validated manual activity event with full ISO timestamps."""
    d = date.fromisoformat(date_str)

    # Check if start/end are already full ISO timestamps
    if "T" in start_time:
        s_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        if s_dt.tzinfo is None:
            s_dt = s_dt.replace(tzinfo=tz)
    else:
        sh, sm, ss = parse_time_str(start_time)
        s_dt = datetime(d.year, d.month, d.day, sh, sm, ss, tzinfo=tz)

    if "T" in end_time:
        e_dt = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
        if e_dt.tzinfo is None:
            e_dt = e_dt.replace(tzinfo=tz)
    else:
        eh, em, es = parse_time_str(end_time)
        e_dt = datetime(d.year, d.month, d.day, eh, em, es, tzinfo=tz)
        if e_dt <= s_dt:
            # Crosses midnight into next day (e.g. 23:30 - 01:00 or 13:00 - 13:00)
            e_dt += timedelta(days=1)

    duration = max(0.0, (e_dt - s_dt).total_seconds())
    act_clean = activity.strip()
    cat_clean = category.strip() if category else infer_category(act_clean)

    evt_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{date_str}:{s_dt.isoformat()}:{e_dt.isoformat()}:{act_clean}"))

    return {
        "id": evt_id,
        "start": s_dt.isoformat(),
        "end": e_dt.isoformat(),
        "duration_seconds": round(duration, 1),
        "source": "manual",
        "context": {
            "activity": act_clean,
            "category": cat_clean,
            "notes": notes.strip(),
        },
    }


def parse_text_line(line: str, date_str: str, tz: timezone = DEFAULT_TZ) -> Optional[Dict[str, Any]]:
    """Parse human readable line like:
    '13:00 - 15:00 | Afternoon nap | rest'
    or '13:00-15:00: Afternoon nap'
    or '- 02:00 - 10:00: Sleep'
    """
    clean = line.strip().lstrip("-* ").strip()
    if not clean or clean.startswith("#"):
        return None

    # Try pipe separated: 13:00 - 15:00 | Afternoon nap [ | category [ | notes ] ]
    if "|" in clean:
        parts = [p.strip() for p in clean.split("|")]
        time_part = parts[0]
        activity = parts[1] if len(parts) > 1 else "Offline Activity"
        category = parts[2] if len(parts) > 2 else None
        notes = parts[3] if len(parts) > 3 else ""
    elif ":" in clean:
        # Check for HH:MM[:SS] - HH:MM[:SS]: Activity
        match = re.match(r'^(\d{1,2}(?::\d{2})?(?::\d{2})?(?:am|pm)?\s*[-–—to]+\s*\d{1,2}(?::\d{2})?(?::\d{2})?(?:am|pm)?)\s*[:=]\s*(.+)$', clean, re.IGNORECASE)
        if match:
            time_part = match.group(1)
            activity = match.group(2)
            category = None
            notes = ""
        else:
            return None
    else:
        return None

    # Split time part: e.g. "13:00 - 15:00"
    t_match = re.split(r'\s*[-–—to]+\s*', time_part, flags=re.IGNORECASE)
    if len(t_match) != 2:
        return None

    start_str, end_str = t_match[0], t_match[1]
    return create_manual_event(date_str, start_str, end_str, activity, category, notes, tz=tz)


def read_manual_events(data_dir: str, date_str: str, tz: timezone = DEFAULT_TZ) -> List[Dict[str, Any]]:
    """Read all manual events for date_str from structured Record/manual/ files.
    Supports .jsonl, .json, and .txt / .yaml journal files.
    """
    events = []
    seen_ids = set()

    try:
        d = date.fromisoformat(date_str)
    except Exception:
        return events

    search_dirs = [
        get_manual_dir(data_dir, d),
        Path(data_dir) / "manual",
    ]

    for m_dir in search_dirs:
        if not m_dir.exists():
            continue

        # 1. JSONL file: <date_str>.jsonl
        jsonl_file = m_dir / f"{date_str}.jsonl"
        if jsonl_file.exists():
            with open(jsonl_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        if data.get("source") == "manual" and "start" in data and "end" in data:
                            eid = data.get("id")
                            if eid not in seen_ids:
                                seen_ids.add(eid)
                                events.append(data)
                    except Exception:
                        pass

        # 2. Text / Markdown / YAML journal: <date_str>.txt or <date_str>.yaml or <date_str>.md
        for ext in [".txt", ".yaml", ".md"]:
            text_file = m_dir / f"{date_str}{ext}"
            if text_file.exists():
                with open(text_file, "r", encoding="utf-8") as f:
                    for line in f:
                        evt = parse_text_line(line, date_str, tz=tz)
                        if evt and evt["id"] not in seen_ids:
                            seen_ids.add(evt["id"])
                            events.append(evt)

    events.sort(key=lambda x: x["start"])
    return events


def save_manual_event(data_dir: str, date_str: str, event_data: Dict[str, Any]) -> str:
    """Append a single manual event to Record/manual/YYYY/mmm/daily/YYYY-MM-DD.jsonl
    Idempotent: skips if identical event id is already present.
    """
    m_dir = get_manual_dir(data_dir, date_str)
    target_file = m_dir / f"{date_str}.jsonl"

    existing_ids = set()
    if target_file.exists():
        with open(target_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        e = json.loads(line)
                        if "id" in e:
                            existing_ids.add(e["id"])
                    except Exception:
                        pass

    if event_data.get("id") not in existing_ids:
        with open(target_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(event_data, ensure_ascii=False) + "\n")

    return str(target_file)
