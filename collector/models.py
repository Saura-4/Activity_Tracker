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
        try:
            from urllib.parse import parse_qsl, urlencode
            parsed = urlparse(ctx["url"])
            host = (parsed.netloc or "").lower()
            is_youtube = "youtube.com" in host or "youtu.be" in host
            if is_youtube:
                # Preserve video identity (?v=, list, search_query) so distinct
                # videos never collapse into https://www.youtube.com/watch.
                q = dict(parse_qsl(parsed.query))
                keep = {k: q[k] for k in ("v", "list", "t", "s", "search_query", "q") if k in q}
                new_q = urlencode(keep)
                stripped = urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", new_q, ""))
                ctx["url"] = stripped
            else:
                stripped = urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))
                ctx["url"] = stripped
        except Exception:
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
