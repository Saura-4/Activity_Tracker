# Activity Tracker

A local-first personal activity tracking system for Windows. Records what application/context is actively being used so an AI agent can later inspect the resulting reports and analyze your behavior.

**Not** a productivity enforcer, website blocker, or cloud analytics tool.

## Architecture

```
Browser Extension(s) ──┐
                       ├──► Local Python Collector ──► D:\ActivityTracker\
VS Code Extension ─────┘         (HTTP)                ├── raw\
                                                       │   └── YYYY-MM-DD.jsonl
                                                       └── report\
                                                           ├── YYYY-MM-DD.json       (Full report for dashboard)
                                                           └── YYYY-MM-DD.chat.json  (Lean report for LLM chat)
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

Rebuild all historical reports and compile dashboard:
```powershell
python reporting/generate_report.py --rebuild-all
```

**Two Outputs Per Day:**
Each run automatically generates two files in `Record/report/<YYYY>/<mmm>/daily/`:
1. **`DATE.json` (Full Report)**: The complete report preserved for the visual dashboard (`dashboard.html`). Written as compact single-line JSON by default (add `--pretty` if you want human-readable indentation). Retains full segment lists, longest sessions, hourly breakdown, and merged offline ranges.
2. **`DATE.chat.json` (Lean Chat Report)**: The lean file specifically designed to be pasted directly into LLM chats. Stays under 25 KB even on heavy days (~165 timeline entries, well below the 30 KB hard ceiling). Contains a trimmed summary, daily metrics, label totals, label coverage percentage, per-source breakdown, top 15 titles, top domains, mobile apps, desktop apps, manual events, compact timeline rows (`[start, end, duration, source, name, domain, label]`), and condensed data quality metrics.

### 8. Inspect the Report

**Which file goes into chat?**
Paste **`DATE.chat.json`** into your LLM chat (Gemini, ChatGPT, Claude). It is optimized to stay under 25 KB while retaining all context the LLM needs to analyze your day.

```powershell
# Copy lean chat report to clipboard on Windows
Get-Content Record\report\2026\oct\daily\2026-10-02.chat.json | Set-Clipboard
```

Or inspect the full report for the dashboard:
```powershell
Get-Content Record\report\2026\oct\daily\2026-10-02.json | ConvertFrom-Json
```

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

## Dashboard Views: Calendar & Typical Day

The dashboard (`Record/report/dashboard.html`) computes all visualizations entirely client-side from embedded reports:

### 1. Calendar Tab (Heatmap & Trends)
- **Range Selector**: Day (15-minute cells), Week (last 7 days, default), Month (last 30 days), and Custom date picker (ranges $>60$ days aggregate rows by week).
- **Layers**:
  - **Activity**: Screen union minutes per cell (scale: 0 to 60m).
  - **PC vs Phone**: Device distribution (sky blue for PC dominant $\ge 70\%$, purple for mobile dominant $\ge 70\%$, teal for balanced).
  - **Label**: Cell color represents dominant label, intensity scaled by active minutes; offline manual events shown distinct from idle.
  - **Sleep Overlay**: Subtle diagonal hatching highlighting cells overlapping bedtime/wake windows.
- **Multi-select Label Filters**: Filter heatmap cells by one or more labels.
- **Interactive Tooltip**: Hovering over any cell displays duration, device breakdown, top application/title, dominant label, and sleep indicators.
- **Summary Metrics**: Average first/last activity, highest work hours (`build`+`practice`+`learn`), highest leisure hours, average sleep duration and bedtime, plus an automatic warning banner if range label coverage falls below 70%.
- **Sleep & Baseline Panel**: Client-side SVG line chart of sleep duration and wake time, rolling 14-day median baseline, sleep regularity metric (standard deviation of bedtime in minutes), and "Today vs baseline" comparison card (with fallback if $<7$ days recorded).

### 2. Typical Day Tab (Routine Synthesis & Dual Range Comparison)
- **Zero Report Bloat**: Precomputes 96-bin daily arrays client-side on demand and caches them in memory.
- **Dual Range Comparison**:
  - **Range A (Target)** and optional **Range B (Comparison)**.
  - Presets: Last 7 days, Last 14 days, Last 30 days, and "This period vs previous period of same length".
  - Custom date pickers for both ranges.
  - Day filters: All / Weekdays / Weekends.
  - Device filters: All / PC / Phone.
- **Day Inclusion & Quality Gates**:
  - Excludes days with 0 sessions or $<30$ minutes of accounted time.
  - Flags days where collector/watcher was offline for most of the day.
  - Displays "N days included, M excluded". If $<5$ included days, suppresses statistical averages to prevent skew.
- **Flexible 24h Axis**:
  - Bins: 15-minute (default), 30-minute, or 60-minute resolution.
  - Selectable axis start: `00:00`, `06:00`, `12:00`, or `18:00` (evening start keeps midnight-crossing sleep unbroken as a single contiguous block).
  - **Horizontal Strip Layers (Range A above Range B, plus Delta Strip)**:
  - **Activity**: % of included days with screen activity in bin (color intensity). Hover shows %, average active minutes, and N days.
  - **Sleep**: % of included nights asleep. Overlays vertical markers for median bedtime and wake time with shaded IQR band. Reports manual vs inferred night counts.
  - **Device**: PC share vs phone share stacked per bin.
  - **Labels**: Dominant label by average minutes, intensity from average minutes, unlabeled in neutral gray, range coverage badge (warning if $<70\%$), multi-select label filters.
  - **Focus vs Drift**:
    - **Focus**: `build` + `practice` + `learn` (emerald track).
    - **Drift**: `leisure` (rose track), with toggle for **unplanned only** (`planned: false`) vs all leisure.
    - **Neutral**: `stay-current`, `career`, `comms`, `other` (+ planned leisure when unplanned-only is enabled).
    - **Unlabeled**: Rendered as a distinct gray share per bin to clearly expose unaccounted/unlabeled time.
    - **Coverage Quality Gate**: Only days meeting the minimum label coverage threshold (default $\ge 60\%$, adjustable) count for synthesis; displays qualified day count (e.g. `6 of 7 days qualified`).
    - **Dedicated Summary Table**: Compares Top 3 Focus Windows ($\ge 1\text{h}$ contiguous), Top 3 Drift Windows ($\ge 1\text{h}$ contiguous), Average Focus Hours/Day, Average Drift Hours/Day, and Label Coverage % across Range A, Range B, and Delta.
  - **Difference Strip (B minus A)**: Diverging color scale (emerald for positive difference, rose for negative difference) comparing Range B directly against Range A.
- **Comparison & Regularity Table**:
  - Compares 12 core metrics across Range A, Range B, and Delta:
    1. Median Bedtime (wrap-aware circular statistics)
    2. Median Wake Time (wrap-aware circular statistics)
    3. Average Sleep Duration
    4. Bedtime Regularity (IQR)
    5. Average First Activity
    6. Average Last Activity
    7. Average Active Hours
    8. Phone Share (%)
    9. Peak Activity Window (1h rolling window)
    10. Peak Work Window (`build` + `practice` + `learn`)
    11. Peak Leisure Window
    12. Average Late-Night Screen Minutes (00:00 to 05:00)
  - Deltas formatted with plain-word shifts (`+1h 30m later`, `-45m earlier`, `+1.2h`, `+5.3%`).

## Data Safeguards & Backup

### 1. Full Idempotent Rebuild (`--rebuild-all`)
Regenerates every daily report from the raw event store and compiles the dashboard:
```powershell
python -m reporting.generate_report --rebuild-all
```
- Discovers all raw dates (both flat `raw/*.jsonl` and hierarchical `raw/YYYY/mmm/daily/*.jsonl`).
- Regenerates each daily JSON report idempotently without duplicating or modifying raw events.
- Automatically triggers `Record/report/dashboard.html` update upon completion.

### 2. One-Line Data Directory Backup
Back up the whole data directory (`raw`, `analysis`, `manual`) into a timestamped archive:

**PowerShell (Windows):**
```powershell
Compress-Archive -Path "Record\raw", "Record\analysis", "Record\manual" -DestinationPath "Record_backup_$(Get-Date -Format 'yyyyMMdd_HHmmss').zip"
```

**Bash / Linux / macOS:**
```bash
tar -czf "Record_backup_$(date +%Y%m%d_%H%M%S).tar.gz" Record/raw Record/analysis Record/manual
```

## Diagnostic & Comparison Tools

### Raw Context Diagnostic Tool (`tools/diagnose.py`)
Inspect raw browser context values and per-app mobile totals for direct comparison against Android Digital Wellbeing:
```powershell
python tools/diagnose.py --date 2026-10-01
```

### Synthetic Comparison Demo (`tools/generate_demo_comparison.py`)
Generates a synthetic 14-day dataset where Range B shifts sleep bedtime and wake time by ~2 hours later, and verifies comparison metrics and difference strips:
```powershell
python tools/generate_demo_comparison.py
```

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
User:  "Analyze what I did yesterday." [pastes Record/report/2026/sep/daily/2026-09-28.chat.json]
Agent: *reads 2026-09-28.chat.json*
Agent: "You spent 3h 20m coding in RAG-Studio (mostly Python), 1h 15m on GitHub
        reviewing PRs, and 45m on ChatGPT. Your longest focus block was 28 minutes on retriever.py."
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
