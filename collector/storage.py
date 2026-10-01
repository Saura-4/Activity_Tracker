import json
import threading
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List

_lock = threading.Lock()
_recent_ids = set()
_current_date = None

def get_file_path(data_dir: str, dt: datetime) -> Path:
    date_str = dt.strftime("%Y-%m-%d")
    year = str(dt.year)
    month = dt.strftime("%b").lower()
    d = Path(data_dir) / "raw" / year / month / "daily"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{date_str}.jsonl"

def append_event(config, event_data: Dict[str, Any]) -> bool:
    global _current_date, _recent_ids
    
    min_dur = getattr(config, "min_duration_seconds", 40.0) if config else 40.0
    dur = float(event_data.get("duration_seconds", 0.0))
    if dur < min_dur:
        return False

    start_dt = datetime.fromisoformat(event_data["start"].replace('Z', '+00:00')).astimezone()
    date_str = start_dt.strftime("%Y-%m-%d")
    
    with _lock:
        evt_id = event_data["id"]
        if evt_id in _recent_ids:
            return False # Duplicate
            
        file_path = get_file_path(config.data_directory, start_dt)
        
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event_data) + "\n")
            
        _recent_ids.add(evt_id)
        if len(_recent_ids) > 10000:
            _recent_ids = set(list(_recent_ids)[-5000:])
            
    return True

def read_events(config, date_str: str) -> List[Dict[str, Any]]:
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        file_path = get_file_path(config.data_directory, dt)
    except Exception:
        file_path = Path(config.data_directory) / "raw" / f"{date_str}.jsonl"

    if not file_path.exists():
        legacy_path = Path(config.data_directory) / "raw" / f"{date_str}.jsonl"
        if legacy_path.exists():
            file_path = legacy_path

    events = []
    if file_path.exists():
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    events.append(json.loads(line.strip()))
                except Exception:
                    pass
    return events
