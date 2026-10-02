import uuid
from dataclasses import dataclass, field
from typing import Dict, Any
from datetime import datetime
from urllib.parse import urlparse, urlunparse

@dataclass
class Event:
    id: str
    start: str
    end: str
    duration_seconds: float
    source: str
    context: Dict[str, Any] = field(default_factory=dict)

def validate_and_create_event(data: Dict[str, Any], strip_queries: bool = True) -> Event:
    required = ["start", "end", "duration_seconds", "source", "context"]
    for r in required:
        if r not in data:
            raise ValueError(f"Missing required field: {r}")
            
    if data["source"] not in ["browser", "vscode", "mobile", "desktop", "manual"]:
        raise ValueError(f"Invalid source: {data['source']}")
        
    dur = float(data["duration_seconds"])
    if dur < 0:
        raise ValueError("duration_seconds must be >= 0")
        
    start_dt = datetime.fromisoformat(data["start"].replace('Z', '+00:00'))
    end_dt = datetime.fromisoformat(data["end"].replace('Z', '+00:00'))
    
    if start_dt > end_dt:
        raise ValueError("start time must be before end time")
        
    evt_id = data.get("id", str(uuid.uuid4()))
    
    ctx = data["context"].copy()
    if data["source"] == "browser" and strip_queries and "url" in ctx:
        parsed = urlparse(ctx["url"])
        stripped = urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))
        ctx["url"] = stripped
        
    return Event(
        id=evt_id,
        start=data["start"],
        end=data["end"],
        duration_seconds=dur,
        source=data["source"],
        context=ctx
    )
