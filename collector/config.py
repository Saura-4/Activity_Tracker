import os
import json
from dataclasses import dataclass
from pathlib import Path

from typing import Dict, Any, Optional

ALLOWED_LABELS = (
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
)

@dataclass
class Config:
    data_directory: str = "D:\\ActivityTracker"
    collector_host: str = "127.0.0.1"
    collector_port: int = 8765
    strip_query_strings: bool = True
    session_merge_gap_seconds: float = 30.0
    min_duration_seconds: float = 40.0
    raw_min_duration_seconds: float = 2.0
    android: Dict[str, Any] = None
    auth_token: Optional[str] = None
    cors_origins: Optional[list] = None
    allowed_labels: Optional[list] = None

    def __post_init__(self):
        if self.android is None:
            self.android = {}
        if self.cors_origins is None:
            self.cors_origins = [
                "chrome-extension://*",
                "moz-extension://*",
                "vscode-webview://*",
            ]
        if self.allowed_labels is None:
            self.allowed_labels = list(ALLOWED_LABELS)

    def __getitem__(self, item):
        return getattr(self, item)

    def get(self, item, default=None):
        return getattr(self, item, default)

def get_config() -> Config:
    config = Config()
    
    # Check env var
    env_dir = os.environ.get("ACTIVITY_TRACKER_DIR")
    if env_dir:
        config.data_directory = env_dir

    # Resolve config.json
    # Look in script dir, cwd, project root
    script_dir = Path(__file__).parent
    cwd = Path.cwd()
    project_root = script_dir.parent

    config_paths = [
        script_dir / "config.json",
        cwd / "config.json",
        project_root / "config.json"
    ]

    for p in config_paths:
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if "data_directory" in data:
                        raw_dir = Path(data["data_directory"])
                        if not raw_dir.is_absolute():
                            raw_dir = (project_root / raw_dir).resolve()
                        config.data_directory = str(raw_dir)
                    if "collector_host" in data:
                        config.collector_host = data["collector_host"]
                    if "collector_port" in data:
                        config.collector_port = data["collector_port"]
                    if "strip_query_strings" in data:
                        config.strip_query_strings = data["strip_query_strings"]
                    if "session_merge_gap_seconds" in data:
                        config.session_merge_gap_seconds = float(data["session_merge_gap_seconds"])
                    if "min_duration_seconds" in data:
                        config.min_duration_seconds = float(data["min_duration_seconds"])
                    if "raw_min_duration_seconds" in data:
                        config.raw_min_duration_seconds = float(data["raw_min_duration_seconds"])
                    if "android" in data:
                        config.android = data["android"]
                    if "auth_token" in data:
                        config.auth_token = data["auth_token"]
                    if "cors_origins" in data:
                        config.cors_origins = data["cors_origins"]
                    if "allowed_labels" in data:
                        config.allowed_labels = list(data["allowed_labels"])
                break
            except Exception as e:
                print(f"Error loading config from {p}: {e}")
                
    return config
