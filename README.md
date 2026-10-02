# Activity Tracker

A local-first personal activity tracking system for Windows. Records what application/context is actively being used so an AI agent can later inspect the resulting reports and analyze your behavior.

**Not** a productivity enforcer, website blocker, or cloud analytics tool.

## Architecture

```
Browser Extension(s) ──┐
                       ├──► Local Python Collector ──► D:\ActivityTracker\
VS Code Extension ─────┘         (HTTP)                ├── raw\
                                                       │   └── YYYY-MM-DD.jsonl
                                                       └── reports\
                                                           └── YYYY-MM-DD.json
```

- **Browser extensions** and the **VS Code extension** send activity events via HTTP to a local Python collector
- The **collector** validates and appends events to daily JSONL files
- The **report generator** reads raw data and produces agent-friendly JSON reports
- Everything stays local. No cloud, no telemetry. Collector endpoints support optional bearer token authentication with restricted CORS origins.

## Project Structure

```
activity-tracker/
├── collector/                  # Python HTTP collector service
│   ├── main.py                 # aiohttp server (127.0.0.1:8765)
│   ├── config.py               # Configuration loader
│   ├── models.py               # Event validation and schema
│   ├── storage.py              # Thread-safe JSONL file writer
│   └── requirements.txt        # Python dependencies
│
├── browser-extension/          # Chromium Manifest V3 extension
│   ├── manifest.json           # Extension manifest
│   ├── background.js           # Service worker (tab/focus tracking)
│   ├── config.html             # Settings page
│   ├── config.js               # Settings logic
│   └── styles.css              # Settings page styling
│
├── vscode-extension/           # VS Code extension (TypeScript)
│   ├── package.json            # Extension manifest
│   ├── tsconfig.json           # TypeScript config
│   └── src/
│       ├── extension.ts        # Main extension (editor/focus tracking)
│       └── collector-client.ts # HTTP client for collector
│
├── reporting/                  # Report generation
│   └── generate_report.py      # CLI report generator
│
├── tests/                      # Test suite
│   ├── conftest.py             # Fixtures and helpers
│   └── test_sessionization.py  # 34 tests for session/aggregation logic
│
├── config.example.json         # Example configuration
├── requirements-dev.txt        # Dev dependencies (pytest)
├── .gitignore
└── README.md
```

## Quick Start

### 1. Configure

Copy the example config:

```powershell
cd activity-tracker
copy config.example.json config.json
```

Edit `config.json` to customize:

```json
{
  "data_directory": "../Record",
  "collector_host": "127.0.0.1",
  "collector_port": 8765,
  "strip_query_strings": true,
  "session_merge_gap_seconds": 30.0,
  "min_duration_seconds": 40.0,
  "raw_min_duration_seconds": 2.0,
  "auth_token": "",
  "cors_origins": ["chrome-extension://*", "moz-extension://*", "vscode-webview://*"]
}
```

Or set the environment variable:
```powershell
$env:ACTIVITY_TRACKER_DIR = "D:\ActivityTracker"
```

### 2. Install Python Dependencies

```powershell
pip install -r collector/requirements.txt
```

### 3. Start the Collector

```powershell
python collector/main.py
```

You should see:
```
Starting collector on 127.0.0.1:8765
Data directory: S:\project\AW
```

The collector must be running for extensions to send events. Consider adding it to Windows startup.

### 4. Load the Browser Extension

For **each** browser profile (Chrome Profile 1, Chrome Profile 2, Brave Profile 1, etc.):

1. Open the browser profile
2. Navigate to `chrome://extensions/`
3. Enable **Developer mode** (top right toggle)
4. Click **Load unpacked**
5. Select the `browser-extension/` directory
6. The extension appears as "Activity Tracker"

Repeat for every profile. Each profile gets its own independent instance.

**Optional:** Click the extension's options (gear icon) to verify the collector URL is `http://127.0.0.1:8765`.

### 5. Install the VS Code Extension

```powershell
cd vscode-extension
npm install
npm run compile
```

Then install it in VS Code:

1. Open VS Code
2. Run `code --install-extension .` from the `vscode-extension/` directory

**Or** for development:
1. Open the `vscode-extension/` folder in VS Code
2. Press `F5` to launch an Extension Development Host

Configure via VS Code Settings:
- `activityTracker.collectorUrl`: Collector endpoint (default: `http://127.0.0.1:8765`)
- `activityTracker.minSessionDuration`: Minimum session seconds to record (default: `2`)
- `activityTracker.authToken`: Optional shared secret token for collector authentication (default: `""`)

### 6. Verify Events Are Recording

With the collector running and extensions loaded:

1. Browse a few websites, switch tabs
2. Switch to VS Code, edit some files
3. Check the raw data:

```powershell
Get-Content D:\ActivityTracker\raw\2026-09-29.jsonl
```

You should see JSONL entries with `"source": "browser"` and `"source": "vscode"`.

### Scheduled Mobile Sync (Android)

Android usagestats history expires over time. To ensure events are captured:
- **Automatic:** The collector runs an automated sync thread every 30 minutes in the background when `android.enabled` is true in `config.json`.
- **Windows Task Scheduler:** Alternatively, schedule `sync_mobile.bat` every 30 minutes:
  ```powershell
  schtasks /create /tn "ActivityTrackerMobileSync" /tr "S:\project\AW\sync_mobile.bat" /sc minute /mo 30
  ```

### 7. Generate a Report

Single day:
```powershell
python reporting/generate_report.py --date 2026-09-29
```

Date range:
```powershell
python reporting/generate_report.py --from 2026-09-28 --to 2026-09-29
```

Reports are written to `D:\ActivityTracker\reports/`.

### 8. Inspect the Report

```powershell
Get-Content D:\ActivityTracker\reports\2026-09-29.json | ConvertFrom-Json
```

Or simply read the JSON file. It's designed for AI agents to consume.

## Event Schema

Both browser and VS Code produce events with the same structure:

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "start": "2026-09-29T18:10:00+05:30",
  "end": "2026-09-29T18:24:31+05:30",
  "duration_seconds": 871,
  "source": "browser",
  "context": {
    "domain": "github.com",
    "title": "Pull Requests",
    "url": "https://github.com/pulls"
  }
}
```

VS Code events:
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440001",
  "start": "2026-09-29T18:24:31+05:30",
  "end": "2026-09-29T18:51:12+05:30",
  "duration_seconds": 1601,
  "source": "vscode",
  "context": {
    "workspace": "RAG-Studio"
  }
}
```

## Report Structure

Reports contain these sections:

| Section | Description |
|---------|-------------|
| `summary` | Total active time (union), PC/browser/VS Code/mobile/desktop/manual splits, brief session stats, session count |
| `daily_metrics` | Compact metrics: screen activity span, phone share, longest & top 3 focus blocks (tolerating gaps $\le 60$s), late night screen seconds (00:00–05:00), and sleep inference |
| `labels` | Human-assigned time-range label overlay totals, planned durations, labeled vs unlabeled seconds, and coverage percentage |
| `data_quality` | Active sources present, last mobile sync timestamp, offline watcher/collector ranges, label warnings, fallback ranges |
| `sources` | Duration and count per source (browser, vscode, desktop, mobile, manual) |
| `domains` | Browser domains ranked by duration with percentages |
| `titles` | Page titles ranked by duration (top 50) |
| `workspaces` | VS Code workspaces ranked by duration |
| `longest_sessions` | Top 10 longest uninterrupted sessions |
| `timeline` | All sessions in chronological order, with matching label annotations |
| `hourly_breakdown` | Activity bucketed by hour of day (union-based active seconds) |

## Daily Metrics & Sleep Inference

The `daily_metrics` block captures rhythm and focus without hardcoded categories:
- **`first_activity` & `last_activity`**: Local timestamps of earliest and latest screen activity (excludes manual offline entries).
- **`active_seconds`**: True screen union duration across PC and mobile.
- **`phone_share`**: Ratio of mobile screen time to total screen time ($0.0$ to $1.0$).
- **`longest_focus_block` & `top_3_focus_blocks`**: Consecutive PC time on the same application, workspace, or website domain, tolerating brief interruptions/switches up to 60 seconds.
- **`late_night_screen_seconds`**: Total screen time between 00:00 and 05:00 local time.
- **`sleep`**: Bedtime, wake time, duration, and phone boundaries (`last_phone_before_bed`, `first_phone_after_wake`) for the night ending on this morning. A manual "Sleep" event takes precedence; otherwise, sleep is inferred as the longest gap ($\ge 3$ hours) without screen activity spanning the night window (20:00 to 12:00) across midnight. If data is insufficient, `insufficient_data: true` is reported explicitly.

## Human-Assigned Labels

Labels provide intentional structure to screen time without rigid automated categorization.

### Fixed Label Set
- `build`: Deep creation, software development, writing, construction.
- `practice`: Deliberate exercise, skill drill, coding katas.
- `learn`: Reading technical documentation, studying papers, courses.
- `stay-current`: Tech blogs, industry news, newsletters.
- `career`: Portfolio, interviews, networking, resume.
- `comms`: Email, chat, messaging, coordination.
- `leisure`: Entertainment, casual browsing, games, social media.
- `other`: Anything else (unknown labels fall back here).

### Storage Format
Labels are embedded inside a hidden HTML comment at the top of the daily analysis journal (`Record/analysis/YYYY/mmm/daily/DATE.md`). It remains invisible in rendered markdown:

```markdown
<!-- labels
{
  "energy": 4,
  "labels": [
    { "start": "09:00", "end": "12:15", "label": "build", "note": "Activity tracker refactoring", "planned": true },
    { "start": "13:30", "end": "14:45", "label": "learn", "note": "Read new documentation" },
    { "start": "15:00", "end": "16:00", "label": "comms", "note": "Team sync" },
    { "start": "21:00", "end": "22:00", "label": "leisure", "note": "Casual videos" }
  ]
}
-->
```

- **Time-range overlay**: Labels apply strictly to screen time by interval intersection. Overlapping label ranges resolve using "later entry wins".
- **Safety**: Malformed blocks produce warnings in `data_quality.label_warnings` without failing report generation.
- **Timeline Integration**: Timeline sessions that fall entirely within a label interval receive `"label": "<label_name>"`; partial or uncovered sessions receive `"unlabeled"`.

## Dashboard & Trends (Phase E)

The dashboard computes all visualizations client-side from embedded reports:
- **Range Selector**: Day (15-minute cells), Week (last 7 days, default), Month (last 30 days), and Custom date picker (ranges $>60$ days aggregate rows by week).
- **Layers**:
  - **Activity**: Screen union minutes per cell (scale: 0 to 60m).
  - **PC vs Phone**: Device distribution (sky blue for PC dominant $\ge 70\%$, purple for mobile dominant $\ge 70\%$, teal for balanced).
  - **Label**: Cell color represents dominant label, intensity scaled by active minutes; offline manual events shown distinct from idle.
  - **Sleep Overlay**: Subtle diagonal hatching highlighting cells overlapping bedtime/wake windows.
- **Multi-select Label Filters**: Filter heatmap cells by one or more labels.
- **Interactive Tooltip**: Hovering over any cell displays duration, device breakdown, top application/title, dominant label, and sleep indicators.
- **Summary Metrics**: Average first/last activity, highest work hours (`build`+`practice`+`learn`), highest leisure hours, average sleep duration and bedtime, plus an automatic warning banner if range label coverage falls below 70%.
- **Sleep & Baseline Panel**: Client-side SVG line chart of sleep duration and wake time, rolling 14-day median baseline, sleep regularity metric (standard deviation of bedtime in minutes), and "Today vs baseline" comparison card (with helpful fallback if $<7$ days recorded).

## Key Invariants

- **Only the focused/active context receives duration.** Background tabs never accumulate time.
- **When the browser loses OS focus** (e.g., switching to VS Code), the browser session ends.
- **When VS Code loses focus**, the VS Code session ends.
- **Sessions are contiguous periods** of activity in one context. Same tab/workspace visited later = new session.
- **No merging** of non-contiguous sessions in raw data (reports aggregate them).
- **No keystroke/content logging.** Only metadata about what's active.

## Privacy

- All data stays on your machine
- URL query strings are stripped by default (`?token=...` → removed)
- No source code contents, keystrokes, clipboard, or screenshots are recorded
- Only metadata: domain, title, workspace name

## Running Tests

```powershell
pip install pytest
python -m pytest tests/ -v
```

## Agent Integration

The intended workflow:

```
User:  "Analyze what I did yesterday."
Agent: *reads D:\ActivityTracker\reports\2026-09-28.json*
Agent: "You spent 3h 20m coding in RAG-Studio (mostly Python), 1h 15m on GitHub
        reviewing PRs, and 45m on ChatGPT. You had 42 context switches with your
        longest uninterrupted session being 28 minutes on retriever.py."
```

The agent can answer:
- What did I spend most time doing?
- How much time coding vs browsing?
- Which projects did I work on?
- Which websites consumed the most time?
- How many context switches?
- What were my longest focused sessions?
- What does my activity timeline look like?

## Limitations

- **VS Code focus detection** uses `vscode.window.state.focused` which may not detect all OS-level focus changes (e.g., Alt-Tab to a non-browser app and back may not always fire)
- **Browser service workers** can be terminated by Chrome/Brave; session state is persisted to storage to handle this, but sub-second precision at boundaries may be lost
- **Multiple browser profiles** each track independently and don't know about each other; the collector simply records all events
- **System sleep/wake** may cause a session to span the sleep period; the duration will be calculated from wall-clock time

## Troubleshooting

| Issue | Fix |
|-------|-----|
| No events appearing | Verify collector is running: `curl http://127.0.0.1:8765/health` |
| Browser extension not sending | Check extension options page → Test Connection |
| VS Code not sending | Run command "Activity Tracker: Show Status" |
| Port conflict | Change `collector_port` in `config.json` and update extension settings |
| Permission error on data dir | Ensure the configured data directory is writable |
