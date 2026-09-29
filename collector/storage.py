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
    d = Path(data_dir) / "raw"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{date_str}.jsonl"

def append_event(config, event_data: Dict[str, Any]) -> bool:
    global _current_date, _recent_ids
    
    start_dt = datetime.fromisoformat(event_data["start"].replace('Z', '+00:00')).astimezone()
    date_str = start_dt.strftime("%Y-%m-%d")
    
    with _lock:
        if _current_date != date_str:
            _current_date = date_str
            _recent_ids.clear()
            
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
    file_path = Path(config.data_directory) / "raw" / f"{date_str}.jsonl"
    events = []
    if file_path.exists():
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    events.append(json.loads(line.strip()))
                except Exception:
                    pass
    return events
