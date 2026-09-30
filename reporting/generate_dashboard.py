"""
Generates an interactive, standalone HTML dashboard from activity tracker JSON reports
and Markdown analysis journals.

Features:
- Multi-source visualization (Browser, VS Code, Desktop, Mobile)
- Synchronized Executive Markdown Journal (.md) + Quantitative Metrics (.json)
- 24-hour interactive session timeline strip
- Hourly activity stacked bar chart
- Category and app leaderboards
- Multi-day switching, date synchronization, and custom report drag-and-drop
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, Any, List

def format_duration(seconds: float) -> str:
    s = int(seconds)
    hours = s // 3600
    minutes = (s % 3600) // 60
    secs = s % 60
    if hours > 0:
        return f"{hours}h {minutes}m"
    if minutes > 0:
        return f"{minutes}m {secs}s"
    return f"{secs}s"

def build_dashboard_html(reports_data: Dict[str, Any], analyses_data: Dict[str, str], initial_date: str) -> str:
    reports_json = json.dumps(reports_data)
    analyses_json = json.dumps(analyses_data)
    
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Activity Tracker - Executive Visual Dashboard</title>
  <script src="https://www.gstatic.com/antigravity/web/dev/tailwindcss.min.js"></script>
  <style>
    :root {{
      --background: #090d16;
      --card: #0d1117;
      --card-hover: #161b22;
      --border: #21262d;
      --border-subtle: #1b2128;
      --foreground: #f0f6fc;
      --muted-foreground: #8b949e;
      --primary: #38bdf8;
      --primary-foreground: #0284c7;
    }}
    body {{
      background-color: var(--background);
      color: var(--foreground);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    }}
    .custom-scroll::-webkit-scrollbar {{
      width: 6px;
      height: 6px;
    }}
    .custom-scroll::-webkit-scrollbar-track {{
      background: rgba(30, 41, 59, 0.4);
      border-radius: 4px;
    }}
    .custom-scroll::-webkit-scrollbar-thumb {{
      background: #21262d;
      border-radius: 4px;
    }}
  </style>
</head>
<body class="antialiased p-4 sm:p-6 lg:p-8 selection:bg-sky-500/20 selection:text-sky-300">
  <div class="max-w-7xl mx-auto space-y-5">

    <!-- Top Navigation & Controls Bar -->
    <header class="bg-[var(--card)] border border-[var(--border)] rounded-xl px-4 py-3 shadow-sm flex flex-col md:flex-row md:items-center justify-between gap-3">
      <div class="flex items-center gap-2.5">
        <div class="w-7 h-7 rounded-md bg-sky-500/10 border border-sky-500/20 flex items-center justify-center text-sky-400">
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
        </div>
        <h1 class="text-base font-semibold tracking-tight text-[var(--foreground)]">Activity Tracker</h1>
      </div>

      <div class="flex flex-wrap items-center gap-2">
        <!-- Date Switcher Buttons -->
        <div id="date-buttons-container" class="inline-flex p-0.5 bg-[#090d16] rounded-lg border border-[var(--border)] text-xs">
          <!-- Populated by JS -->
        </div>

        <!-- Sync Mobile & Generate Report Actions -->
        <button id="btn-sync-mobile" onclick="triggerSyncMobile()" class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium bg-[#161b22] hover:bg-[#21262d] text-slate-300 border border-[var(--border)] transition disabled:opacity-50">
          <svg class="w-3.5 h-3.5 text-purple-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 18h.01M8 21h8a2 2 0 002-2V5a2 2 0 00-2-2H8a2 2 0 00-2 2v14a2 2 0 002 2z"></path></svg>
          <span id="btn-sync-mobile-text">Sync Mobile</span>
        </button>

        <button id="btn-generate-report" onclick="triggerGenerateReport()" class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium bg-[#161b22] hover:bg-[#21262d] text-slate-300 border border-[var(--border)] transition disabled:opacity-50">
          <svg class="w-3.5 h-3.5 text-sky-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"></path></svg>
          <span id="btn-generate-report-text">Generate Report</span>
        </button>

        <!-- Custom JSON loader -->
        <label class="cursor-pointer inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium bg-[#161b22] hover:bg-[#21262d] text-slate-300 border border-[var(--border)] transition">
          <svg class="w-3.5 h-3.5 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12"></path></svg>
          Import
          <input type="file" id="file-input" accept=".json,.md" class="hidden">
        </label>
      </div>
    </header>

    <!-- View Mode Selector Tabs -->
    <div class="flex items-center justify-between border-b border-[var(--border)] pb-2.5">
      <div class="inline-flex p-0.5 bg-[#090d16] rounded-lg border border-[var(--border)] text-xs font-medium" id="main-view-tabs">
        <button data-tab="split" class="tab-btn px-3 py-1 rounded-md bg-[#21262d] text-white transition">Dashboard & Journal</button>
        <button data-tab="analytics" class="tab-btn px-3 py-1 rounded-md text-slate-400 hover:text-slate-200 transition">Analytics</button>
        <button data-tab="journal" class="tab-btn px-3 py-1 rounded-md text-slate-400 hover:text-slate-200 transition">Journal</button>
      </div>

      <div id="has-analysis-badge" class="hidden sm:inline-flex items-center gap-1.5 text-xs text-slate-400">
        <span class="w-1.5 h-1.5 rounded-full bg-emerald-400"></span> Analysis note attached
      </div>
    </div>

    <!-- Annual Activity Contribution Heatmap (GitHub/LeetCode block style) -->
    <section class="bg-[var(--card)] border border-[var(--border)] rounded-xl p-4 shadow-sm space-y-2.5">
      <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-2 pb-2 border-b border-[var(--border)]">
        <div class="flex items-center gap-2">
          <h2 class="text-sm font-semibold text-[var(--foreground)]">Activity Calendar</h2>
          <span id="calendar-summary-badge" class="text-xs font-mono text-slate-400"></span>
        </div>

        <div class="flex items-center gap-3">
          <div id="calendar-hover-info" class="text-xs font-mono text-slate-400">Selected: --</div>

          <!-- Color Scale Legend -->
          <div class="flex items-center gap-1 text-[10px] text-slate-400">
            <span>Less</span>
            <span class="w-2.5 h-2.5 rounded-[2px] bg-[#161b22] border border-[#272d37]" title="No activity"></span>
            <span class="w-2.5 h-2.5 rounded-[2px] bg-[#0e4429] border border-[#14532d]" title="< 2h"></span>
            <span class="w-2.5 h-2.5 rounded-[2px] bg-[#006d32] border border-[#166534]" title="2h - 4h"></span>
            <span class="w-2.5 h-2.5 rounded-[2px] bg-[#26a641] border border-[#22c55e]" title="4h - 6h"></span>
            <span class="w-2.5 h-2.5 rounded-[2px] bg-[#39d353] border border-[#4ade80]" title="> 6h"></span>
            <span>More</span>
          </div>
        </div>
      </div>

      <!-- Heatmap Scroll Container -->
      <div id="calendar-scroll-container" class="overflow-x-auto custom-scroll pb-2 pt-1">
        <div class="inline-flex gap-2 min-w-full">
          <!-- Weekday Labels Column -->
          <div class="flex flex-col text-[10px] text-slate-400 font-mono select-none pt-[18px] shrink-0" style="gap: 3px;">
            <div class="h-[12px] flex items-center pr-1"></div>
            <div class="h-[12px] flex items-center pr-1">Mon</div>
            <div class="h-[12px] flex items-center pr-1"></div>
            <div class="h-[12px] flex items-center pr-1">Wed</div>
            <div class="h-[12px] flex items-center pr-1"></div>
            <div class="h-[12px] flex items-center pr-1">Fri</div>
            <div class="h-[12px] flex items-center pr-1"></div>
          </div>

          <!-- Month labels + 7-row block matrix -->
          <div class="flex flex-col gap-1.5">
            <!-- Months Header Row -->
            <div id="calendar-months-row" class="h-4 relative text-[10px] text-slate-400 font-mono select-none">
              <!-- Rendered via JS -->
            </div>

            <!-- Days Grid (7 rows, 53 columns) -->
            <div id="calendar-days-grid" class="grid grid-rows-7 grid-flow-col" style="gap: 3px;">
              <!-- 371 square blocks rendered via JS -->
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- KPI Metric Cards Grid -->
    <section class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3.5">
      <div class="bg-[var(--card)] border border-[var(--border)] rounded-xl p-4 transition hover:border-[#388bfd]/50">
        <div class="text-[11px] font-medium uppercase tracking-wider text-[var(--muted-foreground)]">Active Screen Time</div>
        <div id="metric-total-active" class="text-2xl font-bold text-[var(--foreground)] mt-1.5 font-mono">--</div>
        <div id="metric-observed-span" class="text-xs text-[var(--muted-foreground)] mt-1">Observed span: --</div>
      </div>

      <div class="bg-[var(--card)] border border-[var(--border)] rounded-xl p-4 transition hover:border-indigo-500/50">
        <div class="text-[11px] font-medium uppercase tracking-wider text-[var(--muted-foreground)]">Deep Focus Time</div>
        <div id="metric-work-time" class="text-2xl font-bold text-indigo-400 mt-1.5 font-mono">--</div>
        <div id="metric-work-pct" class="text-xs text-[var(--muted-foreground)] mt-1">Coding & AI research</div>
      </div>

      <div class="bg-[var(--card)] border border-[var(--border)] rounded-xl p-4 transition hover:border-amber-500/50">
        <div class="text-[11px] font-medium uppercase tracking-wider text-[var(--muted-foreground)]">Context Switches</div>
        <div id="metric-switches" class="text-2xl font-bold text-amber-400 mt-1.5 font-mono">--</div>
        <div id="metric-switch-rate" class="text-xs text-[var(--muted-foreground)] mt-1">Across apps & windows</div>
      </div>

      <div class="bg-[var(--card)] border border-[var(--border)] rounded-xl p-4 transition hover:border-emerald-500/50">
        <div class="text-[11px] font-medium uppercase tracking-wider text-[var(--muted-foreground)]">Longest Focus Block</div>
        <div id="metric-longest-session" class="text-2xl font-bold text-emerald-400 mt-1.5 font-mono">--</div>
        <div id="metric-longest-name" class="text-xs text-[var(--muted-foreground)] mt-1 truncate">--</div>
      </div>
    </section>

    <!-- Daily Journal (.md) Section -->
    <section id="journal-section" class="bg-[var(--card)] border border-[var(--border)] rounded-xl p-4 shadow-sm space-y-3">
      <div class="flex flex-col sm:flex-row sm:items-center justify-between pb-2.5 border-b border-[var(--border)] gap-2">
        <div class="flex items-center gap-2">
          <h2 class="text-sm font-semibold text-[var(--foreground)]" id="journal-heading">Daily Journal</h2>
          <span class="text-xs text-slate-500 font-mono" id="journal-filepath">Record/analysis/...</span>
        </div>
        <div class="text-xs text-slate-400 font-mono" id="journal-date-tag">Date: --</div>
      </div>

      <!-- Rendered Markdown Body -->
      <div id="journal-content-container" class="prose prose-invert max-w-none text-slate-300 text-xs leading-relaxed">
        <!-- Rendered markdown goes here -->
      </div>
    </section>

    <!-- Source Split & Device Distribution -->
    <section id="analytics-split-section" class="bg-[var(--card)] border border-[var(--border)] rounded-xl p-4 shadow-sm space-y-3">
      <div class="flex items-center justify-between">
        <h2 class="text-sm font-semibold text-[var(--foreground)]">Device Breakdown</h2>
        <div id="device-ratio-badge" class="text-xs font-mono px-2 py-0.5 bg-[#090d16] rounded text-slate-400 border border-[var(--border)]">
          Ratio: --
        </div>
      </div>

      <!-- Segmented Bar -->
      <div id="source-split-bar" class="w-full h-3 rounded-full overflow-hidden flex bg-[#090d16] border border-[var(--border)]">
        <!-- Dynamic segments -->
      </div>

      <!-- Source Badges Legend -->
      <div class="grid grid-cols-2 sm:grid-cols-4 gap-2.5 pt-1 text-xs">
        <div class="flex items-center gap-2 p-2 rounded-lg bg-[#090d16]/60 border border-[var(--border)]">
          <span class="w-2.5 h-2.5 rounded-sm bg-sky-400 shrink-0"></span>
          <div class="min-w-0">
            <div class="font-medium text-slate-300 text-xs">Browser</div>
            <div id="source-stat-browser" class="text-slate-500 font-mono text-[11px]">--</div>
          </div>
        </div>

        <div class="flex items-center gap-2 p-2 rounded-lg bg-[#090d16]/60 border border-[var(--border)]">
          <span class="w-2.5 h-2.5 rounded-sm bg-purple-400 shrink-0"></span>
          <div class="min-w-0">
            <div class="font-medium text-slate-300 text-xs">Mobile</div>
            <div id="source-stat-mobile" class="text-slate-500 font-mono text-[11px]">--</div>
          </div>
        </div>

        <div class="flex items-center gap-2 p-2 rounded-lg bg-[#090d16]/60 border border-[var(--border)]">
          <span class="w-2.5 h-2.5 rounded-sm bg-emerald-400 shrink-0"></span>
          <div class="min-w-0">
            <div class="font-medium text-slate-300 text-xs">Desktop</div>
            <div id="source-stat-desktop" class="text-slate-500 font-mono text-[11px]">--</div>
          </div>
        </div>

        <div class="flex items-center gap-2 p-2 rounded-lg bg-[#090d16]/60 border border-[var(--border)]">
          <span class="w-2.5 h-2.5 rounded-sm bg-amber-400 shrink-0"></span>
          <div class="min-w-0">
            <div class="font-medium text-slate-300 text-xs">VS Code</div>
            <div id="source-stat-vscode" class="text-slate-500 font-mono text-[11px]">--</div>
          </div>
        </div>
      </div>
    </section>

    <!-- Hourly Activity Explorer & Inspector -->
    <section id="analytics-hourly-section" class="bg-[var(--card)] border border-[var(--border)] rounded-xl p-4 shadow-sm space-y-4">
      <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-[var(--border)]">
        <div>
          <div class="flex items-center gap-2">
            <h2 class="text-sm font-semibold text-[var(--foreground)]">Hourly Activity Explorer</h2>
            <span id="hourly-summary-badge" class="text-xs font-mono text-slate-400"></span>
          </div>
          <p class="text-xs text-[var(--muted-foreground)] mt-0.5">Inspect what you were doing and for how long during each hour</p>
        </div>

        <!-- Mode Toggle Controls -->
        <div class="flex items-center gap-2">
          <div class="inline-flex p-0.5 bg-[#090d16] rounded-lg border border-[var(--border)] text-xs font-medium" id="hourly-mode-toggle">
            <button id="btn-mode-inspector" onclick="setHourlyViewMode('inspector')" class="px-2.5 py-1 rounded-md bg-[#21262d] text-white transition">Hour Inspector</button>
            <button id="btn-mode-schedule" onclick="setHourlyViewMode('schedule')" class="px-2.5 py-1 rounded-md text-slate-400 hover:text-slate-200 transition">24h Schedule</button>
          </div>
        </div>
      </div>

      <!-- 24-Hour Interactive Rhythm Bar Strip -->
      <div class="space-y-1.5">
        <div class="flex items-center justify-between text-[11px] text-slate-400 px-1">
          <span class="font-mono">Select an hour below to inspect:</span>
          <div class="flex items-center gap-3">
            <span class="inline-flex items-center gap-1.5"><span class="w-2 h-2 rounded-sm bg-sky-400"></span> Browser</span>
            <span class="inline-flex items-center gap-1.5"><span class="w-2 h-2 rounded-sm bg-purple-400"></span> Mobile</span>
            <span class="inline-flex items-center gap-1.5"><span class="w-2 h-2 rounded-sm bg-emerald-400"></span> Desktop</span>
            <span class="inline-flex items-center gap-1.5"><span class="w-2 h-2 rounded-sm bg-amber-400"></span> VS Code</span>
          </div>
        </div>

        <div id="hourly-bars-container" class="h-44 flex items-end gap-1 sm:gap-1.5 pt-6 pb-2 bg-[#090d16] border border-[var(--border)] rounded-xl px-2 sm:px-3 overflow-x-auto custom-scroll">
          <!-- 24 interactive hourly bars injected by JS -->
        </div>

        <div class="flex justify-between text-[10px] font-mono text-slate-500 px-2">
          <span>00:00 (Night)</span>
          <span>06:00 (Morning)</span>
          <span>12:00 (Noon)</span>
          <span>18:00 (Evening)</span>
          <span>23:00 (Night)</span>
        </div>
      </div>

      <!-- Selected Hour Inspector Card -->
      <div id="hourly-inspector-container" class="bg-[#090d16] border border-[var(--border)] rounded-xl p-4 space-y-3">
        <!-- Injected by renderHourlyInspector() -->
      </div>

      <!-- Chronological 24h Schedule Feed (Toggleable) -->
      <div id="hourly-schedule-container" class="hidden bg-[#090d16] border border-[var(--border)] rounded-xl p-4 space-y-2.5">
        <!-- Injected by renderHourlySchedule() -->
      </div>
    </section>

    <!-- Detailed Leaderboards & Focus Blocks Grid (Longest Focus Sessions, Domains, Mobile Apps, Desktop Apps) -->
    <section id="analytics-leaderboards-section" class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
      
      <!-- Top Longest Focused Sessions -->
      <div class="bg-[var(--card)] border border-[var(--border)] rounded-xl p-4 shadow-sm space-y-3 flex flex-col">
        <div class="flex items-center justify-between">
          <h2 class="text-sm font-semibold text-[var(--foreground)]">Longest Sessions</h2>
          <span id="longest-count-badge" class="text-xs font-mono text-slate-500">Top 5</span>
        </div>
        <div id="longest-sessions-list" class="space-y-2 flex-1 overflow-y-auto max-h-80 pr-1 custom-scroll">
          <!-- Populated by JS -->
        </div>
      </div>

      <!-- Domains Card -->
      <div class="bg-[var(--card)] border border-[var(--border)] rounded-xl p-4 shadow-sm space-y-3 flex flex-col">
        <div class="flex items-center justify-between">
          <h2 class="text-sm font-semibold text-[var(--foreground)]">Websites</h2>
          <span id="domains-count-badge" class="text-xs font-mono text-slate-500">0 domains</span>
        </div>
        <div id="domains-list" class="space-y-2.5 flex-1 overflow-y-auto max-h-80 pr-1 custom-scroll">
          <!-- Populated by JS -->
        </div>
      </div>

      <!-- Mobile Apps Card -->
      <div class="bg-[var(--card)] border border-[var(--border)] rounded-xl p-4 shadow-sm space-y-3 flex flex-col">
        <div class="flex items-center justify-between">
          <h2 class="text-sm font-semibold text-[var(--foreground)]">Mobile Apps</h2>
          <span id="mobile-count-badge" class="text-xs font-mono text-slate-500">0 apps</span>
        </div>
        <div id="mobile-apps-list" class="space-y-2.5 flex-1 overflow-y-auto max-h-80 pr-1 custom-scroll">
          <!-- Populated by JS -->
        </div>
      </div>

      <!-- Desktop Applications Card -->
      <div class="bg-[var(--card)] border border-[var(--border)] rounded-xl p-4 shadow-sm space-y-3 flex flex-col">
        <div class="flex items-center justify-between">
          <h2 class="text-sm font-semibold text-[var(--foreground)]">Desktop Apps</h2>
          <span id="desktop-count-badge" class="text-xs font-mono text-slate-500">0 apps</span>
        </div>
        <div id="desktop-apps-list" class="space-y-2.5 flex-1 overflow-y-auto max-h-80 pr-1 custom-scroll">
          <!-- Populated by JS -->
        </div>
      </div>

    </section>

    <!-- Comprehensive Filterable Timeline Table -->
    <section id="analytics-ledger-section" class="bg-[var(--card)] border border-[var(--border)] rounded-xl p-4 shadow-sm space-y-3">
      <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div class="flex items-center gap-2">
          <h2 class="text-sm font-semibold text-[var(--foreground)]">Session Ledger</h2>
          <div id="ledger-hour-filter-pill" class="hidden inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-xs font-mono bg-sky-500/10 text-sky-400 border border-sky-500/20"></div>
        </div>

        <!-- Filter tabs & Search -->
        <div class="flex flex-wrap items-center gap-2">
          <div id="timeline-filters" class="inline-flex p-0.5 bg-[#090d16] rounded-lg border border-[var(--border)] text-xs font-medium">
            <button data-filter="all" class="filter-btn px-2.5 py-1 rounded-md bg-[#21262d] text-white transition text-xs">All</button>
            <button data-filter="browser" class="filter-btn px-2.5 py-1 rounded-md text-slate-400 hover:text-slate-200 transition text-xs">Browser</button>
            <button data-filter="mobile" class="filter-btn px-2.5 py-1 rounded-md text-slate-400 hover:text-slate-200 transition text-xs">Mobile</button>
            <button data-filter="desktop" class="filter-btn px-2.5 py-1 rounded-md text-slate-400 hover:text-slate-200 transition text-xs">Desktop</button>
            <button data-filter="vscode" class="filter-btn px-2.5 py-1 rounded-md text-slate-400 hover:text-slate-200 transition text-xs">VS Code</button>
          </div>

          <div class="relative">
            <input type="text" id="timeline-search" placeholder="Filter..." class="bg-[#090d16] border border-[var(--border)] rounded-lg px-2.5 py-1 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-sky-500/50 w-36 sm:w-48 font-mono">
          </div>
        </div>
      </div>

      <!-- Ledger Container -->
      <div class="overflow-hidden border border-[var(--border)] rounded-lg bg-[#090d16]/70">
        <div class="max-h-[460px] overflow-y-auto custom-scroll divide-y divide-[#21262d]" id="timeline-table-body">
          <!-- Session rows injected by JS -->
        </div>
      </div>
    </section>

  </div>

  <!-- Embedded Data & Client Controller -->
  <script>
    const REPORTS_DATABASE = {reports_json};
    const ANALYSES_DATABASE = {analyses_json};
    let currentDate = "{initial_date}";
    let currentFilter = "all";
    let searchQuery = "";
    let activeMainTab = "split"; // 'split', 'analytics', 'journal'
    let selectedHour = null;
    let hourlyViewMode = "inspector"; // 'inspector' or 'schedule'
    let activeHourFilter = null;

    function formatSecs(secs) {{
      const s = Math.round(secs);
      const h = Math.floor(s / 3600);
      const m = Math.floor((s % 3600) / 60);
      const r = s % 60;
      if (h > 0) return `${{h}}h ${{m}}m`;
      if (m > 0) return `${{m}}m ${{r}}s`;
      return `${{r}}s`;
    }}

    function parseTimeOnly(isoStr) {{
      if (!isoStr) return "--:--";
      const parts = isoStr.split("T");
      if (parts.length > 1) {{
        return parts[1].substring(0, 5);
      }}
      return isoStr;
    }}

    function escapeHtml(text) {{
      const div = document.createElement("div");
      div.textContent = text;
      return div.innerHTML;
    }}

    function inlineFormat(text) {{
      let t = escapeHtml(text);
      // Bold
      t = t.replace(/\\*\\*(.+?)\\*\\*/g, '<strong class="text-white font-semibold">$1</strong>');
      // Italic
      t = t.replace(/\\*(.+?)\\*/g, '<em class="italic text-slate-300">$1</em>');
      // Inline code
      t = t.replace(/`([^`]+)`/g, '<code class="bg-slate-900 text-sky-300 px-1.5 py-0.5 rounded text-[11px] font-mono border border-slate-800">$1</code>');
      // Links
      t = t.replace(/\\[([^\\]]+)\\]\\(([^\\)]+)\\)/g, '<a href="$2" target="_blank" class="text-sky-400 hover:text-sky-300 underline">$1</a>');
      return t;
    }}

    function renderMarkdown(md) {{
      if (!md || !md.trim()) {{
        const parts = currentDate.split("-");
        const yr = parts[0] || "2026";
        const mNames = ["jan","feb","mar","apr","may","jun","jul","aug","sep","oct","nov","dec"];
        const mmm = (parts[1] && parseInt(parts[1]) > 0 && parseInt(parts[1]) <= 12) ? mNames[parseInt(parts[1]) - 1] : "sep";
        return `
          <div class="py-8 text-center bg-[#090d16]/40 border border-dashed border-[#21262d] rounded-lg space-y-1.5">
            <div class="text-xs font-medium text-slate-400">No journal entry for ${{currentDate}}</div>
            <p class="text-[11px] text-slate-600 font-mono">
              Record/analysis/${{yr}}/${{mmm}}/daily/${{currentDate}}.md
            </p>
          </div>
        `;
      }}

      const lines = md.split('\\n');
      let html = [];
      let inList = false;
      let inCode = false;
      let codeBuffer = [];

      for (let i = 0; i < lines.length; i++) {{
        let line = lines[i];

        if (line.trim().startsWith('```')) {{
          if (inCode) {{
            html.push('<pre class="bg-slate-950 border border-slate-800 rounded-xl p-4 my-3 text-xs font-mono text-sky-300 overflow-x-auto custom-scroll"><code>' + escapeHtml(codeBuffer.join('\\n')) + '</code></pre>');
            codeBuffer = [];
            inCode = false;
          }} else {{
            inCode = true;
          }}
          continue;
        }}
        if (inCode) {{
          codeBuffer.push(line);
          continue;
        }}

        if (line.trim() === '---' || line.trim() === '***') {{
          if (inList) {{ html.push('</ul>'); inList = false; }}
          html.push('<hr class="border-slate-800 my-5">');
          continue;
        }}

        if (line.startsWith('# ')) {{
          if (inList) {{ html.push('</ul>'); inList = false; }}
          html.push('<h1 class="text-xl sm:text-2xl font-extrabold text-white tracking-tight mb-3 mt-1 flex items-center gap-2">' + inlineFormat(line.slice(2)) + '</h1>');
          continue;
        }}
        if (line.startsWith('## ')) {{
          if (inList) {{ html.push('</ul>'); inList = false; }}
          html.push('<h2 class="text-base sm:text-lg font-bold text-sky-300 tracking-tight mt-5 mb-2.5 flex items-center gap-2 border-b border-slate-800/80 pb-1.5">' + inlineFormat(line.slice(3)) + '</h2>');
          continue;
        }}
        if (line.startsWith('### ')) {{
          if (inList) {{ html.push('</ul>'); inList = false; }}
          html.push('<h3 class="text-sm font-bold text-indigo-300 tracking-tight mt-4 mb-2">' + inlineFormat(line.slice(4)) + '</h3>');
          continue;
        }}

        if (line.startsWith('> ')) {{
          if (inList) {{ html.push('</ul>'); inList = false; }}
          html.push('<blockquote class="p-3 my-2.5 bg-slate-900/90 border-l-4 border-sky-500 rounded-r-xl text-xs text-slate-300 space-y-1">' + inlineFormat(line.slice(2)) + '</blockquote>');
          continue;
        }}

        if (line.trim().startsWith('- ') || line.trim().startsWith('* ')) {{
          if (!inList) {{
            html.push('<ul class="space-y-1.5 my-2 text-xs text-slate-300 list-disc list-inside">');
            inList = true;
          }}
          html.push('<li class="leading-relaxed">' + inlineFormat(line.trim().slice(2)) + '</li>');
          continue;
        }} else {{
          if (inList) {{
            html.push('</ul>');
            inList = false;
          }}
        }}

        if (!line.trim()) continue;

        html.push('<p class="text-xs text-slate-300 leading-relaxed mb-2.5">' + inlineFormat(line) + '</p>');
      }}

      if (inList) html.push('</ul>');
      return html.join('');
    }}

    function renderCalendarHeatmap() {{
      const allDates = Object.keys(REPORTS_DATABASE).concat(Object.keys(ANALYSES_DATABASE));
      let maxDateStr = "2026-09-30";
      if (allDates.length > 0) {{
        allDates.sort();
        maxDateStr = allDates[allDates.length - 1];
      }}

      // Calculate anchor date (align to Saturday of the latest week)
      const maxDate = new Date(maxDateStr + "T12:00:00Z");
      const dayOfWeek = maxDate.getUTCDay(); // 0=Sun..6=Sat
      const endSaturday = new Date(maxDate.getTime() + (6 - dayOfWeek) * 86400000);
      const startSunday = new Date(endSaturday.getTime() - (52 * 7) * 86400000);

      const monthsContainer = document.getElementById("calendar-months-row");
      const gridContainer = document.getElementById("calendar-days-grid");
      if (!monthsContainer || !gridContainer) return;

      monthsContainer.innerHTML = "";
      gridContainer.innerHTML = "";

      const mNames = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
      let lastMonth = -1;
      let activeDaysCount = 0;
      let totalActiveSecondsAll = 0;

      // Summary across all records
      Object.keys(REPORTS_DATABASE).forEach(d => {{
        const s = REPORTS_DATABASE[d]?.summary?.total_active_seconds || 0;
        if (s > 0) {{
          activeDaysCount++;
          totalActiveSecondsAll += s;
        }}
      }});
      const summaryBadge = document.getElementById("calendar-summary-badge");
      if (summaryBadge) {{
        summaryBadge.textContent = `${{activeDaysCount}} active days • ${{formatSecs(totalActiveSecondsAll)}} recorded`;
      }}

      const dayNames = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

      for (let w = 0; w < 53; w++) {{
        // Month label at Wednesday of week
        const wednesday = new Date(startSunday.getTime() + (w * 7 + 3) * 86400000);
        const m = wednesday.getUTCMonth();
        if (m !== lastMonth) {{
          lastMonth = m;
          const mLabel = document.createElement("span");
          mLabel.className = "absolute font-semibold text-slate-400";
          mLabel.style.left = `${{w * 15}}px`;
          mLabel.textContent = mNames[m];
          monthsContainer.appendChild(mLabel);
        }}

        for (let d = 0; d < 7; d++) {{
          const cur = new Date(startSunday.getTime() + (w * 7 + d) * 86400000);
          const dateStr = cur.toISOString().split("T")[0];
          const isSelected = dateStr === currentDate;
          const isFuture = cur.getTime() > (new Date(maxDateStr + "T23:59:59Z")).getTime();

          const rep = REPORTS_DATABASE[dateStr];
          const secs = rep?.summary?.total_active_seconds || 0;
          const hasMd = !!ANALYSES_DATABASE[dateStr];
          const sessionCount = rep?.summary?.session_count || 0;

          const block = document.createElement("button");
          block.type = "button";
          block.dataset.date = dateStr;

          // Color scale matching GitHub / LeetCode block style
          let lvlClass = "bg-[#161b22] border-[#272d37]";
          if (secs > 0) {{
            if (secs < 7200) {{
              lvlClass = "bg-[#0e4429] border-[#14532d]";
            }} else if (secs < 14400) {{
              lvlClass = "bg-[#006d32] border-[#166534]";
            }} else if (secs < 21600) {{
              lvlClass = "bg-[#26a641] border-[#22c55e]";
            }} else {{
              lvlClass = "bg-[#39d353] border-[#4ade80]";
            }}
          }}

          let baseClass = `w-3 h-3 rounded-[2.5px] border transition-all duration-100 relative ${{lvlClass}}`;
          if (isFuture) {{
            baseClass += " opacity-20 pointer-events-none";
          }} else {{
            baseClass += " hover:scale-125 hover:z-20 cursor-pointer";
          }}

          if (isSelected) {{
            baseClass += " ring-2 ring-sky-400 ring-offset-1 ring-offset-[#090d16] scale-125 z-10 shadow-lg shadow-sky-500/40";
          }}

          block.className = baseClass;

          const friendlyDay = `${{dayNames[cur.getUTCDay()]}}, ${{mNames[cur.getUTCMonth()]}} ${{cur.getUTCDate()}}, ${{cur.getUTCFullYear()}}`;
          const activeText = secs > 0 ? `${{formatSecs(secs)}} active (${{sessionCount}} sessions)` : "No active sessions";
          const mdText = hasMd ? " • note" : "";
          block.title = `${{friendlyDay}}: ${{activeText}}${{mdText}}`;

          block.onmouseenter = () => {{
            const infoBox = document.getElementById("calendar-hover-info");
            if (infoBox) {{
              infoBox.innerHTML = `
                <span class="text-slate-200 font-medium">${{friendlyDay}}</span> &bull; 
                <span class="${{secs > 0 ? 'text-emerald-400 font-semibold' : 'text-slate-500'}}">${{secs > 0 ? formatSecs(secs) : 'No activity'}}</span>
                ${{sessionCount > 0 ? `<span class="text-slate-500"> (${{sessionCount}} sessions)</span>` : ''}}
                ${{hasMd ? `<span class="text-sky-400 font-mono text-[10px]"> • note</span>` : ''}}
              `;
            }}
          }};

          block.onmouseleave = () => {{
            updateCalendarSelectedInfo();
          }};

          block.onclick = () => {{
            currentDate = dateStr;
            activeHourFilter = null;
            selectedHour = null;
            renderAll();
            initDateButtons();
            renderCalendarHeatmap();
          }};

          gridContainer.appendChild(block);
        }}
      }}

      updateCalendarSelectedInfo();
    }}

    function updateCalendarSelectedInfo() {{
      const rep = REPORTS_DATABASE[currentDate];
      const secs = rep?.summary?.total_active_seconds || 0;
      const hasMd = !!ANALYSES_DATABASE[currentDate];
      const sessionCount = rep?.summary?.session_count || 0;
      
      const parts = currentDate.split("-");
      let friendlyDate = currentDate;
      if (parts.length === 3) {{
        const dObj = new Date(parseInt(parts[0]), parseInt(parts[1]) - 1, parseInt(parts[2]));
        const dayNames = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
        const mNames = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
        friendlyDate = `${{dayNames[dObj.getDay()]}}, ${{mNames[dObj.getMonth()]}} ${{dObj.getDate()}}, ${{dObj.getFullYear()}}`;
      }}

      const infoBox = document.getElementById("calendar-hover-info");
      if (infoBox) {{
        infoBox.innerHTML = `
          <span class="text-slate-500">Selected:</span> 
          <strong class="text-slate-200">${{friendlyDate}}</strong> &bull; 
          <span class="${{secs > 0 ? 'text-emerald-400 font-medium' : 'text-slate-500'}}">${{secs > 0 ? formatSecs(secs) : 'No activity recorded'}}</span>
          ${{hasMd ? `<span class="text-sky-400 font-mono text-[10px]"> • note</span>` : ''}}
        `;
      }}
    }}

    function initDateButtons() {{
      const container = document.getElementById("date-buttons-container");
      container.innerHTML = "";
      
      const allDatesSet = new Set([...Object.keys(REPORTS_DATABASE), ...Object.keys(ANALYSES_DATABASE)]);
      const dates = Array.from(allDatesSet).sort().reverse();
      
      dates.forEach(d => {{
        const btn = document.createElement("button");
        const isActive = d === currentDate;
        const hasReport = !!REPORTS_DATABASE[d];
        const hasMd = !!ANALYSES_DATABASE[d];

        let extraDot = hasMd ? ' <span class="inline-block w-1.5 h-1.5 rounded-full bg-sky-400 mb-0.5"></span>' : '';

        btn.className = `px-2.5 py-1 rounded-md transition text-xs font-mono ${{isActive ? 'bg-[#21262d] text-white font-medium border border-[#30363d]' : 'text-slate-400 hover:text-slate-200'}}`;
        btn.innerHTML = `${{d}}${{extraDot}}`;
        btn.onclick = () => {{
          currentDate = d;
          activeHourFilter = null;
          selectedHour = null;
          renderAll();
          initDateButtons();
          renderCalendarHeatmap();
        }};
        container.appendChild(btn);
      }});
    }}

    function updateViewModeVisibility() {{
      const jSec = document.getElementById("journal-section");
      const splitSec = document.getElementById("analytics-split-section");
      const hourlySec = document.getElementById("analytics-hourly-section");
      const boardsSec = document.getElementById("analytics-leaderboards-section");
      const ledgerSec = document.getElementById("analytics-ledger-section");

      if (activeMainTab === "journal") {{
        jSec.classList.remove("hidden");
        splitSec.classList.add("hidden");
        hourlySec.classList.add("hidden");
        boardsSec.classList.add("hidden");
        ledgerSec.classList.add("hidden");
      }} else if (activeMainTab === "analytics") {{
        jSec.classList.add("hidden");
        splitSec.classList.remove("hidden");
        hourlySec.classList.remove("hidden");
        boardsSec.classList.remove("hidden");
        ledgerSec.classList.remove("hidden");
      }} else {{ // 'split'
        jSec.classList.remove("hidden");
        splitSec.classList.remove("hidden");
        hourlySec.classList.remove("hidden");
        boardsSec.classList.remove("hidden");
        ledgerSec.classList.remove("hidden");
      }}
    }}

    function renderAll() {{
      const rep = REPORTS_DATABASE[currentDate] || {{}};
      const mdContent = ANALYSES_DATABASE[currentDate] || "";
      const sum = rep.summary || {{}};
      const sources = rep.sources || {{}};
      
      // Analysis status badge
      const badge = document.getElementById("has-analysis-badge");
      if (mdContent.trim()) {{
        badge.classList.remove("hidden");
      }} else {{
        badge.classList.add("hidden");
      }}

      // Render Markdown Journal
      const journalContainer = document.getElementById("journal-content-container");
      journalContainer.innerHTML = renderMarkdown(mdContent);
      document.getElementById("journal-date-tag").textContent = `Date: ${{currentDate}}`;
      
      const parts = currentDate.split("-");
      const yr = parts[0] || "2026";
      const mNames = ["jan","feb","mar","apr","may","jun","jul","aug","sep","oct","nov","dec"];
      const mmm = (parts[1] && parseInt(parts[1]) > 0 && parseInt(parts[1]) <= 12) ? mNames[parseInt(parts[1]) - 1] : "sep";
      document.getElementById("journal-filepath").textContent = `Record/analysis/${{yr}}/${{mmm}}/daily/${{currentDate}}.md`;

      // Top Metrics
      const totalSec = sum.total_active_seconds || 0;
      document.getElementById("metric-total-active").textContent = totalSec > 0 ? formatSecs(totalSec) : "--";
      
      const spanSec = sum.observed_span_seconds || 0;
      const spanFormatted = formatSecs(spanSec);
      const pctActive = spanSec > 0 ? Math.round((totalSec / spanSec) * 100) : 0;
      document.getElementById("metric-observed-span").innerHTML = spanSec > 0 ? 
        `<span>Observed: <strong class="text-slate-200">${{spanFormatted}}</strong> (${{pctActive}}% active)</span>` : 
        `<span>No active session data</span>`;

      // Deep Work Estimate (ChatGPT, GitHub, LeetCode, Antigravity, VS Code)
      let workSec = (sources.vscode?.duration_seconds || 0);
      if (rep.domains) {{
        rep.domains.forEach(d => {{
          const dm = d.domain.toLowerCase();
          if (dm.includes("chatgpt") || dm.includes("github") || dm.includes("leetcode") || dm.includes("openai") || dm.includes("neopat")) {{
            workSec += d.duration_seconds;
          }}
        }});
      }}
      if (rep.desktop_apps) {{
        rep.desktop_apps.forEach(a => {{
          const ap = a.app.toLowerCase();
          if (ap.includes("antigravity") || ap.includes("terminal") || ap.includes("code")) {{
            workSec += a.duration_seconds;
          }}
        }});
      }}
      document.getElementById("metric-work-time").textContent = workSec > 0 ? formatSecs(workSec) : "--";
      const workPct = totalSec > 0 ? Math.round((workSec / totalSec) * 100) : 0;
      document.getElementById("metric-work-pct").textContent = `${{workPct}}% of total active time`;

      // Switches
      const switches = sum.context_switches || 0;
      document.getElementById("metric-switches").textContent = switches;
      const switchRate = spanSec > 3600 ? (switches / (spanSec / 3600)).toFixed(1) : switches;
      document.getElementById("metric-switch-rate").textContent = `~${{switchRate}} context switches/hr`;

      // Longest session
      const longest = (rep.longest_sessions && rep.longest_sessions.length > 0) ? rep.longest_sessions[0] : null;
      if (longest) {{
        document.getElementById("metric-longest-session").textContent = formatSecs(longest.duration_seconds);
        const name = longest.context?.title || longest.context?.app || longest.context?.domain || longest.source;
        document.getElementById("metric-longest-name").textContent = name;
      }} else {{
        document.getElementById("metric-longest-session").textContent = "--";
        document.getElementById("metric-longest-name").textContent = "None recorded";
      }}

      // Source Split Bar
      const bSec = sources.browser?.duration_seconds || 0;
      const mSec = sources.mobile?.duration_seconds || 0;
      const dSec = sources.desktop?.duration_seconds || 0;
      const vSec = sources.vscode?.duration_seconds || 0;

      const bPct = totalSec > 0 ? (bSec / totalSec) * 100 : 0;
      const mPct = totalSec > 0 ? (mSec / totalSec) * 100 : 0;
      const dPct = totalSec > 0 ? (dSec / totalSec) * 100 : 0;
      const vPct = totalSec > 0 ? (vSec / totalSec) * 100 : 0;

      const barContainer = document.getElementById("source-split-bar");
      barContainer.innerHTML = `
        <div class="bg-sky-500 h-full transition-all duration-500" style="width: ${{bPct}}%" title="Browser: ${{formatSecs(bSec)}} (${{bPct.toFixed(1)}}%)"></div>
        <div class="bg-purple-500 h-full transition-all duration-500" style="width: ${{mPct}}%" title="Mobile: ${{formatSecs(mSec)}} (${{mPct.toFixed(1)}}%)"></div>
        <div class="bg-emerald-500 h-full transition-all duration-500" style="width: ${{dPct}}%" title="Desktop: ${{formatSecs(dSec)}} (${{dPct.toFixed(1)}}%)"></div>
        <div class="bg-amber-500 h-full transition-all duration-500" style="width: ${{vPct}}%" title="VS Code: ${{formatSecs(vSec)}} (${{vPct.toFixed(1)}}%)"></div>
      `;

      document.getElementById("source-stat-browser").textContent = `${{formatSecs(bSec)}} (${{bPct.toFixed(1)}}%) &bull; ${{sources.browser?.session_count || 0}} sess`;
      document.getElementById("source-stat-mobile").textContent = `${{formatSecs(mSec)}} (${{mPct.toFixed(1)}}%) &bull; ${{sources.mobile?.session_count || 0}} sess`;
      document.getElementById("source-stat-desktop").textContent = `${{formatSecs(dSec)}} (${{dPct.toFixed(1)}}%) &bull; ${{sources.desktop?.session_count || 0}} sess`;
      document.getElementById("source-stat-vscode").textContent = `${{formatSecs(vSec)}} (${{vPct.toFixed(1)}}%) &bull; ${{sources.vscode?.session_count || 0}} sess`;

      const pcTotal = bSec + dSec + vSec;
      const pcPct = totalSec > 0 ? Math.round((pcTotal / totalSec) * 100) : 0;
      document.getElementById("device-ratio-badge").textContent = `PC: ${{pcPct}}% | Mobile: ${{100 - pcPct}}%`;

      renderHourlyExplorer();
      renderLongestSessions(rep.longest_sessions || []);
      renderDomains(rep.domains || []);
      renderMobileApps(rep.apps || []);
      renderDesktopApps(rep.desktop_apps || []);
      renderLedger(rep.timeline || []);
      updateViewModeVisibility();
    }}

    function parseLocalTimeParts(isoStr) {{
      if (!isoStr) return null;
      const match = isoStr.match(/T(\\d{2}):(\\d{2}):(\\d{2})/);
      if (match) {{
        const h = parseInt(match[1], 10);
        const m = parseInt(match[2], 10);
        const s = parseInt(match[3], 10);
        return {{ hour: h, minute: m, second: s, totalSeconds: h * 3600 + m * 60 + s }};
      }}
      const d = new Date(isoStr);
      if (isNaN(d.getTime())) return null;
      return {{
        hour: d.getHours(),
        minute: d.getMinutes(),
        second: d.getSeconds(),
        totalSeconds: d.getHours() * 3600 + d.getMinutes() * 60 + d.getSeconds()
      }};
    }}

    function computeHourlyActivityData(rep) {{
      const timeline = rep?.timeline || [];
      const hourly = rep?.hourly_breakdown || [];
      
      const hourBuckets = [];
      for (let h = 0; h < 24; h++) {{
        hourBuckets.push({{
          hour: h,
          totalSeconds: 0,
          reportedActiveSeconds: 0,
          sources: {{ browser: 0, mobile: 0, desktop: 0, vscode: 0 }},
          activities: {{}}
        }});
      }}

      // Populate reported active seconds from hourly_breakdown if present
      hourly.forEach(entry => {{
        const h = entry.hour;
        if (hourBuckets[h]) {{
          hourBuckets[h].sources.browser = entry.browser_seconds || 0;
          hourBuckets[h].sources.mobile = entry.mobile_seconds || 0;
          hourBuckets[h].sources.desktop = entry.desktop_seconds || 0;
          hourBuckets[h].sources.vscode = entry.vscode_seconds || 0;
          hourBuckets[h].reportedActiveSeconds = entry.active_seconds || 0;
        }}
      }});

      // Distribute timeline sessions into hourly buckets
      timeline.forEach(item => {{
        const sPart = parseLocalTimeParts(item.start);
        const ePart = parseLocalTimeParts(item.end);
        if (!sPart || !ePart) return;

        let sSec = sPart.totalSeconds;
        let eSec = ePart.totalSeconds;
        if (eSec < sSec) eSec += 86400; // Passed midnight

        const nominalSpan = eSec - sSec;
        const recordedDur = item.duration_seconds || nominalSpan;
        const scale = nominalSpan > 0 ? Math.min(1.0, recordedDur / nominalSpan) : 1.0;

        const src = item.source || "unknown";
        const ctx = item.context || {{}};

        let title = "";
        let subtitle = "";
        if (src === "browser") {{
          title = ctx.title || ctx.domain || "Browser";
          subtitle = ctx.domain || "";
        }} else if (src === "desktop") {{
          title = ctx.app || "Desktop App";
          subtitle = (ctx.title && ctx.title !== ctx.app) ? ctx.title : "";
        }} else if (src === "mobile") {{
          title = ctx.app || ctx.package || "Mobile App";
          subtitle = ctx.package || "";
        }} else if (src === "vscode") {{
          title = ctx.file || ctx.workspace || "VS Code";
          subtitle = (ctx.workspace ? ctx.workspace + " " : "") + (ctx.language ? "(" + ctx.language + ")" : "");
        }} else {{
          title = src;
        }}

        const actKey = `${{src}}:::${{title}}:::${{subtitle}}`;
        const startH = Math.floor(sSec / 3600);
        const endH = Math.floor(eSec / 3600);

        for (let h = startH; h <= endH; h++) {{
          if (h >= 24) break;
          const hStart = h * 3600;
          const hEnd = (h + 1) * 3600;

          const ovStart = Math.max(sSec, hStart);
          const ovEnd = Math.min(eSec, hEnd);

          if (ovEnd > ovStart) {{
            const rawSec = ovEnd - ovStart;
            const effectiveSec = rawSec * scale;
            const b = hourBuckets[h];

            b.totalSeconds += effectiveSec;
            if (!b.activities[actKey]) {{
              b.activities[actKey] = {{
                source: src,
                title: title,
                subtitle: subtitle,
                durationSeconds: 0,
                sessionCount: 0
              }};
            }}
            b.activities[actKey].durationSeconds += effectiveSec;
            b.activities[actKey].sessionCount += 1;
          }}
        }}
      }});

      // Post-process each bucket
      let peakHour = 0;
      let maxSeconds = 0;
      let activeHoursCount = 0;

      hourBuckets.forEach(b => {{
        if (b.reportedActiveSeconds > 0) {{
          b.displayActiveSeconds = b.reportedActiveSeconds;
        }} else {{
          b.displayActiveSeconds = b.totalSeconds;
        }}

        if (b.displayActiveSeconds > 0) {{
          activeHoursCount++;
          if (b.displayActiveSeconds > maxSeconds) {{
            maxSeconds = b.displayActiveSeconds;
            peakHour = b.hour;
          }}
        }}

        const actList = Object.values(b.activities);
        actList.sort((a, b) => b.durationSeconds - a.durationSeconds);
        b.sortedActivities = actList;
      }});

      return {{
        buckets: hourBuckets,
        peakHour: peakHour,
        maxSeconds: maxSeconds,
        activeHoursCount: activeHoursCount
      }};
    }}

    function renderHourlyExplorer() {{
      const rep = REPORTS_DATABASE[currentDate] || {{}};
      const data = computeHourlyActivityData(rep);
      window.CURRENT_HOURLY_DATA = data;

      if (selectedHour === null || selectedHour < 0 || selectedHour > 23) {{
        selectedHour = data.peakHour;
      }}

      const badge = document.getElementById("hourly-summary-badge");
      if (badge) {{
        if (data.activeHoursCount > 0) {{
          badge.textContent = `${{data.activeHoursCount}} active hours • Peak: ${{String(data.peakHour).padStart(2, "0")}}:00 (${{formatSecs(data.maxSeconds)}})`;
        }} else {{
          badge.textContent = "0 active hours";
        }}
      }}

      renderHourlyRhythmBars(data);
      renderHourlyInspector(data);
      renderHourlySchedule(data);
    }}

    function renderHourlyRhythmBars(data) {{
      const container = document.getElementById("hourly-bars-container");
      if (!container) return;
      container.innerHTML = "";

      for (let h = 0; h < 24; h++) {{
        const item = data.buckets[h];
        const isSelected = h === selectedHour;
        const total = item.displayActiveSeconds || item.totalSeconds || 0;
        const heightPct = Math.min(100, (total / 3600) * 100);

        const bSec = item.sources.browser || 0;
        const mSec = item.sources.mobile || 0;
        const dSec = item.sources.desktop || 0;
        const vSec = item.sources.vscode || 0;
        const sumSrc = bSec + mSec + dSec + vSec || (total || 1);

        const bH = (bSec / sumSrc) * 100;
        const mH = (mSec / sumSrc) * 100;
        const dH = (dSec / sumSrc) * 100;
        const vH = (vSec / sumSrc) * 100;

        const col = document.createElement("div");
        col.className = `flex-1 flex flex-col items-center justify-end h-full group relative cursor-pointer select-none transition-all p-0.5 rounded-lg ${{isSelected ? 'bg-sky-500/10 ring-2 ring-sky-400 ring-offset-1 ring-offset-[#090d16]' : 'hover:bg-[#161b22]'}}`;
        
        const topActs = (item.sortedActivities || []).filter(a => a.durationSeconds >= 60).slice(0, 2);
        let topActsHtml = "";
        if (topActs.length > 0) {{
          topActsHtml = topActs.map(a => `<div class="truncate text-[10px] text-slate-300">• ${{escapeHtml(a.title.substring(0, 28))}}: <strong class="text-white">${{formatSecs(a.durationSeconds)}}</strong></div>`).join("");
        }} else if (total > 0) {{
          topActsHtml = `<div class="text-[10px] text-slate-400">Brief interactions &lt; 1m (${{formatSecs(total)}})</div>`;
        }} else {{
          topActsHtml = `<div class="text-[10px] text-slate-500">No activity (Sleep / Idle)</div>`;
        }}

        col.innerHTML = `
          <div class="opacity-0 group-hover:opacity-100 transition-opacity absolute -top-20 z-30 bg-slate-950 border border-slate-700 text-slate-200 text-xs px-2.5 py-1.5 rounded-lg shadow-2xl pointer-events-none min-w-[160px] space-y-1">
            <div class="flex items-center justify-between border-b border-slate-800 pb-1">
              <span class="font-mono font-bold text-sky-400">${{String(h).padStart(2, "0")}}:00 &ndash; ${{String(h + 1).padStart(2, "0")}}:00</span>
              <span class="font-mono text-slate-300 font-semibold">${{formatSecs(total)}}</span>
            </div>
            ${{topActsHtml}}
          </div>
          <div class="w-full bg-[#161b22] rounded-t-sm flex flex-col-reverse overflow-hidden transition-all duration-300 group-hover:brightness-125" style="height: ${{Math.max(6, heightPct)}}%">
            <div class="bg-sky-500 w-full" style="height: ${{bH}}%"></div>
            <div class="bg-purple-500 w-full" style="height: ${{mH}}%"></div>
            <div class="bg-emerald-500 w-full" style="height: ${{dH}}%"></div>
            <div class="bg-amber-500 w-full" style="height: ${{vH}}%"></div>
          </div>
          <span class="text-[10px] font-mono mt-1 ${{isSelected ? 'text-sky-300 font-bold' : total > 0 ? 'text-slate-300 font-medium' : 'text-slate-600'}}">${{String(h).padStart(2, "0")}}</span>
        `;

        col.onclick = () => {{
          selectHour(h);
        }};

        container.appendChild(col);
      }}
    }}

    function renderHourlyInspector(data) {{
      const container = document.getElementById("hourly-inspector-container");
      if (!container) return;
      container.innerHTML = "";

      const h = selectedHour !== null ? selectedHour : 0;
      const bucket = data.buckets[h] || {{ hour: h, totalSeconds: 0, sortedActivities: [] }};
      const totalSec = bucket.displayActiveSeconds || bucket.totalSeconds || 0;
      const acts = (bucket.sortedActivities || []).filter(a => a.durationSeconds >= 60);
      const minorCount = (bucket.sortedActivities || []).filter(a => a.durationSeconds < 60).length;
      const pctOfHour = Math.min(100, Math.round((totalSec / 3600) * 100));
      const isFiltered = activeHourFilter === h;

      const header = document.createElement("div");
      header.className = "flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-[var(--border)]";
      header.innerHTML = `
        <div class="flex items-center gap-3">
          <div class="w-9 h-9 rounded-lg bg-sky-500/10 border border-sky-500/20 flex items-center justify-center font-mono font-bold text-sm text-sky-400">
            ${{String(h).padStart(2, "0")}}h
          </div>
          <div>
            <div class="flex items-center gap-2">
              <h3 class="text-sm font-semibold text-[var(--foreground)]">Hour ${{String(h).padStart(2, "0")}}:00 &ndash; ${{String(h + 1).padStart(2, "0")}}:00</h3>
              <span class="px-2 py-0.5 rounded text-[11px] font-mono font-medium ${{totalSec > 0 ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : 'bg-slate-800 text-slate-400'}}">
                ${{totalSec > 0 ? formatSecs(totalSec) + ' active (' + pctOfHour + '%)' : 'No Activity'}}
              </span>
            </div>
            <div class="text-xs text-slate-400 mt-0.5 font-mono">
              ${{acts.length > 0 ? `${{acts.length}} activities &ge; 1 min` + (minorCount > 0 ? ` &bull; ${{minorCount}} brief under 1m` : '') : (totalSec > 0 ? 'Only brief interactions &lt; 1 min' : 'Idle span / Sleep')}}
            </div>
          </div>
        </div>

        <div class="flex items-center gap-1.5 self-end sm:self-auto">
          <button onclick="selectHour(${{h > 0 ? h - 1 : 23}})" class="px-2.5 py-1 rounded-md text-xs font-mono bg-[#161b22] hover:bg-[#21262d] text-slate-300 border border-[var(--border)] transition" title="Previous hour">
            &larr; Prev
          </button>
          <button onclick="selectHour(${{h < 23 ? h + 1 : 0}})" class="px-2.5 py-1 rounded-md text-xs font-mono bg-[#161b22] hover:bg-[#21262d] text-slate-300 border border-[var(--border)] transition" title="Next hour">
            Next &rarr;
          </button>
          <button onclick="selectHour(${{data.peakHour}})" class="px-2.5 py-1 rounded-md text-xs font-mono ${{h === data.peakHour ? 'bg-sky-500/20 text-sky-300 border border-sky-500/30' : 'bg-[#161b22] hover:bg-[#21262d] text-slate-300 border border-[var(--border)]'}} transition" title="Jump to peak activity hour">
            Peak (${{String(data.peakHour).padStart(2, "0")}}:00)
          </button>
          <button onclick="toggleHourFilter(${{h}})" class="px-2.5 py-1 rounded-md text-xs font-mono ${{isFiltered ? 'bg-sky-500 text-white font-semibold' : 'bg-[#161b22] hover:bg-[#21262d] text-slate-300 border border-[var(--border)]'}} transition">
            ${{isFiltered ? 'Clear Filter' : 'Filter Ledger'}}
          </button>
        </div>
      `;
      container.appendChild(header);

      if (acts.length === 0) {{
        const empty = document.createElement("div");
        empty.className = "py-8 text-center text-xs text-slate-500 space-y-1 font-mono";
        if (totalSec > 0) {{
          empty.innerHTML = `
            <div>Only brief interactions (&lt; 1 min) logged during ${{String(h).padStart(2, "0")}}:00 &ndash; ${{String(h + 1).padStart(2, "0")}}:00 (${{formatSecs(totalSec)}} total)</div>
            <div class="text-[11px] text-slate-600">Events under 1 minute are hidden from this hourly view.</div>
          `;
        }} else {{
          empty.innerHTML = `
            <div>No active screen sessions logged between ${{String(h).padStart(2, "0")}}:00 and ${{String(h + 1).padStart(2, "0")}}:00</div>
            <div class="text-[11px] text-slate-600">Computer was idle, locked, or sleeping.</div>
          `;
        }}
        container.appendChild(empty);
        return;
      }}

      const listContainer = document.createElement("div");
      listContainer.className = "space-y-2 pt-1";

      acts.forEach((act, idx) => {{
        const itemPct = totalSec > 0 ? (act.durationSeconds / totalSec) * 100 : 0;

        let srcBadge = "bg-sky-500/10 text-sky-400 border-sky-500/20";
        let barColor = "bg-sky-500";
        if (act.source === "mobile") {{
          srcBadge = "bg-purple-500/10 text-purple-400 border-purple-500/20";
          barColor = "bg-purple-500";
        }} else if (act.source === "desktop") {{
          srcBadge = "bg-emerald-500/10 text-emerald-400 border-emerald-500/20";
          barColor = "bg-emerald-500";
        }} else if (act.source === "vscode") {{
          srcBadge = "bg-amber-500/10 text-amber-400 border-amber-500/20";
          barColor = "bg-amber-500";
        }}

        const row = document.createElement("div");
        row.className = "p-2.5 rounded-lg bg-[#0d1117] border border-[var(--border)] hover:border-slate-700 transition space-y-2";
        row.innerHTML = `
          <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-1.5 text-xs">
            <div class="flex items-center gap-2.5 min-w-0">
              <span class="font-mono text-slate-500 font-bold text-xs w-4 shrink-0">${{idx + 1}}.</span>
              <span class="px-1.5 py-0.5 rounded text-[10px] font-mono font-semibold uppercase tracking-wider border shrink-0 ${{srcBadge}}">
                ${{act.source}}
              </span>
              <div class="min-w-0">
                <div class="font-medium text-slate-200 truncate" title="${{escapeHtml(act.title)}}">${{escapeHtml(act.title)}}</div>
                ${{act.subtitle ? `<div class="text-[11px] text-slate-500 font-mono truncate" title="${{escapeHtml(act.subtitle)}}">${{escapeHtml(act.subtitle)}}</div>` : ''}}
              </div>
            </div>

            <div class="flex items-center gap-3 shrink-0 self-end sm:self-auto font-mono text-xs">
              <span class="text-slate-400">${{itemPct.toFixed(1)}}%</span>
              <span class="font-bold text-white bg-[#161b22] px-2 py-0.5 rounded border border-[var(--border)]">${{formatSecs(act.durationSeconds)}}</span>
            </div>
          </div>

          <div class="w-full bg-[#161b22] h-1.5 rounded-full overflow-hidden">
            <div class="${{barColor}} h-full rounded-full transition-all duration-300" style="width: ${{Math.min(100, itemPct)}}%"></div>
          </div>
        `;
        listContainer.appendChild(row);
      }});

      container.appendChild(listContainer);
    }}

    function renderHourlySchedule(data) {{
      const container = document.getElementById("hourly-schedule-container");
      if (!container) return;
      container.innerHTML = "";

      const buckets = data.buckets;
      let idleStart = -1;

      for (let h = 0; h < 24; h++) {{
        const b = buckets[h];
        const total = b.displayActiveSeconds || b.totalSeconds || 0;

        if (total === 0) {{
          if (idleStart === -1) {{
            idleStart = h;
          }}
          if (h === 23 && idleStart !== -1) {{
            flushIdleBlock(container, idleStart, 23);
          }}
          continue;
        }}

        if (idleStart !== -1) {{
          flushIdleBlock(container, idleStart, h - 1);
          idleStart = -1;
        }}

        const row = document.createElement("div");
        row.className = `p-3 rounded-xl bg-[#0d1117] border ${{h === selectedHour ? 'border-sky-500/60 ring-1 ring-sky-500/30' : 'border-[var(--border)]'}} hover:border-slate-700 transition cursor-pointer space-y-2`;
        row.onclick = () => {{
          selectHour(h);
          setHourlyViewMode('inspector');
        }};

        const acts = (b.sortedActivities || []).filter(a => a.durationSeconds >= 60).slice(0, 3);
        let actChips = acts.map(a => {{
          let col = "text-sky-400 bg-sky-500/10 border-sky-500/20";
          if (a.source === "mobile") col = "text-purple-400 bg-purple-500/10 border-purple-500/20";
          else if (a.source === "desktop") col = "text-emerald-400 bg-emerald-500/10 border-emerald-500/20";
          else if (a.source === "vscode") col = "text-amber-400 bg-amber-500/10 border-amber-500/20";
          return `<span class="inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-[11px] font-mono border ${{col}}">
            <span class="font-medium text-slate-200 truncate max-w-[160px]">${{escapeHtml(a.title)}}</span>
            <strong class="text-white">${{formatSecs(a.durationSeconds)}}</strong>
          </span>`;
        }}).join(" ");

        if (!actChips) {{
          actChips = `<span class="text-[11px] text-slate-500 font-mono italic">Brief interactions (&lt; 1 min)</span>`;
        }}

        const pctOfHour = Math.min(100, Math.round((total / 3600) * 100));

        row.innerHTML = `
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-2">
              <span class="font-mono font-bold text-xs text-sky-400 bg-sky-500/10 px-2 py-0.5 rounded border border-sky-500/20">
                ${{String(h).padStart(2, "0")}}:00 &ndash; ${{String(h + 1).padStart(2, "0")}}:00
              </span>
              <span class="text-xs text-slate-300 font-mono font-semibold">${{formatSecs(total)}} active</span>
              <span class="text-[11px] text-slate-500 font-mono">(${{pctOfHour}}%)</span>
            </div>
            <span class="text-[11px] font-mono text-slate-500">${{acts.length}} activities &rarr;</span>
          </div>
          <div class="flex flex-wrap gap-1.5 pt-0.5">
            ${{actChips}}
          </div>
        `;
        container.appendChild(row);
      }}
    }}

    function flushIdleBlock(container, startH, endH) {{
      const hoursCount = endH - startH + 1;
      const block = document.createElement("div");
      block.className = "py-2 px-3 rounded-lg bg-[#090d16]/70 border border-dashed border-[#21262d] flex items-center justify-between text-xs text-slate-500 font-mono";
      block.innerHTML = `
        <div class="flex items-center gap-2">
          <span class="w-1.5 h-1.5 rounded-full bg-slate-600"></span>
          <span>${{String(startH).padStart(2, "0")}}:00 &ndash; ${{String(endH + 1).padStart(2, "0")}}:00</span>
          <span>(${{hoursCount}}h idle)</span>
        </div>
        <span class="text-[11px] text-slate-600">Inactive / Sleep</span>
      `;
      container.appendChild(block);
    }}

    function setHourlyViewMode(mode) {{
      hourlyViewMode = mode;
      const inspectorView = document.getElementById("hourly-inspector-container");
      const scheduleView = document.getElementById("hourly-schedule-container");
      const btnInspector = document.getElementById("btn-mode-inspector");
      const btnSchedule = document.getElementById("btn-mode-schedule");

      if (mode === "inspector") {{
        inspectorView.classList.remove("hidden");
        scheduleView.classList.add("hidden");
        btnInspector.className = "px-2.5 py-1 rounded-md bg-[#21262d] text-white transition";
        btnSchedule.className = "px-2.5 py-1 rounded-md text-slate-400 hover:text-slate-200 transition";
      }} else {{
        inspectorView.classList.add("hidden");
        scheduleView.classList.remove("hidden");
        btnInspector.className = "px-2.5 py-1 rounded-md text-slate-400 hover:text-slate-200 transition";
        btnSchedule.className = "px-2.5 py-1 rounded-md bg-[#21262d] text-white transition";
      }}
    }}

    function selectHour(h) {{
      selectedHour = h;
      if (window.CURRENT_HOURLY_DATA) {{
        renderHourlyRhythmBars(window.CURRENT_HOURLY_DATA);
        renderHourlyInspector(window.CURRENT_HOURLY_DATA);
        renderHourlySchedule(window.CURRENT_HOURLY_DATA);
      }}
    }}

    function toggleHourFilter(h) {{
      if (activeHourFilter === h) {{
        activeHourFilter = null;
      }} else {{
        activeHourFilter = h;
      }}
      renderHourlyExplorer();
      renderLedger(REPORTS_DATABASE[currentDate]?.timeline || []);
      const ledgerSec = document.getElementById("analytics-ledger-section");
      if (ledgerSec && activeHourFilter !== null) {{
        ledgerSec.scrollIntoView({{ behavior: 'smooth' }});
      }}
    }}

    function renderLongestSessions(sessions) {{
      const container = document.getElementById("longest-sessions-list");
      container.innerHTML = "";
      if (!sessions || sessions.length === 0) {{
        container.innerHTML = '<div class="text-xs text-slate-500">No sessions recorded</div>';
        return;
      }}

      sessions.slice(0, 5).forEach((sess, idx) => {{
        const title = sess.context?.title || sess.context?.app || sess.context?.domain || sess.source;
        const card = document.createElement("div");
        card.className = "p-2.5 rounded-xl bg-slate-900/60 border border-slate-800 flex items-center justify-between gap-3 text-xs";
        
        let colorClass = "text-sky-400 bg-sky-500/10 border-sky-500/20";
        if (sess.source === "mobile") colorClass = "text-purple-400 bg-purple-500/10 border-purple-500/20";
        else if (sess.source === "desktop") colorClass = "text-emerald-400 bg-emerald-500/10 border-emerald-500/20";
        else if (sess.source === "vscode") colorClass = "text-amber-400 bg-amber-500/10 border-amber-500/20";

        card.innerHTML = `
          <div class="flex items-center gap-2.5 min-w-0">
            <span class="font-mono text-slate-500 text-xs font-bold w-4">${{idx + 1}}.</span>
            <div class="min-w-0">
              <div class="font-medium text-slate-200 truncate">${{title}}</div>
              <div class="text-[11px] text-slate-400 flex items-center gap-1.5 mt-0.5">
                <span class="px-1.5 py-0.2 rounded border ${{colorClass}} text-[10px] font-semibold">${{sess.source}}</span>
                <span>${{parseTimeOnly(sess.start)}} &ndash; ${{parseTimeOnly(sess.end)}}</span>
              </div>
            </div>
          </div>
          <span class="font-mono font-bold text-slate-200 shrink-0">${{formatSecs(sess.duration_seconds)}}</span>
        `;
        container.appendChild(card);
      }});
    }}

    function renderDomains(domains) {{
      const container = document.getElementById("domains-list");
      container.innerHTML = "";
      document.getElementById("domains-count-badge").textContent = `${{domains.length}} domains`;
      
      if (!domains || domains.length === 0) {{
        container.innerHTML = '<div class="text-xs text-slate-500">No browser domain activity</div>';
        return;
      }}

      domains.slice(0, 10).forEach(d => {{
        const row = document.createElement("div");
        row.className = "space-y-1";
        row.innerHTML = `
          <div class="flex justify-between items-center text-xs">
            <span class="font-medium text-slate-200 truncate max-w-[200px]" title="${{d.domain}}">${{d.domain}}</span>
            <span class="font-mono text-slate-400">${{formatSecs(d.duration_seconds)}} <span class="text-slate-500 font-normal">(${{d.percentage}}%)</span></span>
          </div>
          <div class="w-full bg-slate-900 h-1.5 rounded-full overflow-hidden">
            <div class="bg-sky-500 h-full rounded-full transition-all duration-500" style="width: ${{Math.min(100, d.percentage)}}%"></div>
          </div>
        `;
        container.appendChild(row);
      }});
    }}

    function renderMobileApps(apps) {{
      const container = document.getElementById("mobile-apps-list");
      container.innerHTML = "";
      document.getElementById("mobile-count-badge").textContent = `${{apps.length}} apps`;

      if (!apps || apps.length === 0) {{
        container.innerHTML = '<div class="text-xs text-slate-500">No mobile app activity</div>';
        return;
      }}

      apps.slice(0, 10).forEach(a => {{
        const row = document.createElement("div");
        row.className = "space-y-1";
        row.innerHTML = `
          <div class="flex justify-between items-center text-xs">
            <div class="flex items-center gap-1.5 min-w-0">
              <span class="font-medium text-slate-200 truncate max-w-[170px]">${{a.app}}</span>
            </div>
            <span class="font-mono text-slate-400">${{formatSecs(a.duration_seconds)}} <span class="text-slate-500 font-normal">(${{a.percentage}}%)</span></span>
          </div>
          <div class="w-full bg-slate-900 h-1.5 rounded-full overflow-hidden">
            <div class="bg-purple-500 h-full rounded-full transition-all duration-500" style="width: ${{Math.min(100, a.percentage)}}%"></div>
          </div>
        `;
        container.appendChild(row);
      }});
    }}

    function renderDesktopApps(apps) {{
      const container = document.getElementById("desktop-apps-list");
      container.innerHTML = "";
      document.getElementById("desktop-count-badge").textContent = `${{apps.length}} apps`;

      if (!apps || apps.length === 0) {{
        container.innerHTML = '<div class="text-xs text-slate-500">No desktop app activity</div>';
        return;
      }}

      apps.slice(0, 10).forEach(a => {{
        const row = document.createElement("div");
        row.className = "space-y-1";
        row.innerHTML = `
          <div class="flex justify-between items-center text-xs">
            <span class="font-medium text-slate-200 truncate max-w-[180px]">${{a.app}}</span>
            <span class="font-mono text-slate-400">${{formatSecs(a.duration_seconds)}} <span class="text-slate-500 font-normal">(${{a.percentage}}%)</span></span>
          </div>
          <div class="w-full bg-slate-900 h-1.5 rounded-full overflow-hidden">
            <div class="bg-emerald-500 h-full rounded-full transition-all duration-500" style="width: ${{Math.min(100, a.percentage)}}%"></div>
          </div>
        `;
        container.appendChild(row);
      }});
    }}

    function renderLedger(timeline) {{
      const container = document.getElementById("timeline-table-body");
      container.innerHTML = "";

      let filtered = (timeline || []).filter(item => {{
        if (currentFilter !== "all" && item.source !== currentFilter) return false;
        if (activeHourFilter !== null) {{
          const sPart = parseLocalTimeParts(item.start);
          const ePart = parseLocalTimeParts(item.end);
          if (sPart && ePart) {{
            let sSec = sPart.totalSeconds;
            let eSec = ePart.totalSeconds;
            if (eSec < sSec) eSec += 86400;
            const hStart = activeHourFilter * 3600;
            const hEnd = (activeHourFilter + 1) * 3600;
            if (Math.min(eSec, hEnd) <= Math.max(sSec, hStart)) {{
              return false;
            }}
          }}
        }}
        if (searchQuery) {{
          const q = searchQuery.toLowerCase();
          const title = (item.context?.title || item.context?.app || item.context?.domain || "").toLowerCase();
          const sub = (item.context?.domain || item.context?.package || item.context?.file || "").toLowerCase();
          if (!title.includes(q) && !sub.includes(q)) return false;
        }}
        return true;
      }});

      // Update Ledger filter pill
      const filterPill = document.getElementById("ledger-hour-filter-pill");
      if (filterPill) {{
        if (activeHourFilter !== null) {{
          filterPill.classList.remove("hidden");
          filterPill.innerHTML = `
            <span>Hour ${{String(activeHourFilter).padStart(2, "0")}}:00 &ndash; ${{String(activeHourFilter + 1).padStart(2, "0")}}:00</span>
            <button onclick="toggleHourFilter(${{activeHourFilter}})" class="hover:text-white font-bold text-slate-400">&times;</button>
          `;
        }} else {{
          filterPill.classList.add("hidden");
        }}
      }}

      if (filtered.length === 0) {{
        container.innerHTML = '<div class="p-6 text-center text-xs text-slate-500">No matching activity records found.</div>';
        return;
      }}

      filtered.slice().reverse().forEach(item => {{
        const row = document.createElement("div");
        row.className = "p-3 sm:px-4 hover:bg-slate-900/60 transition flex flex-col sm:flex-row sm:items-center justify-between gap-2 text-xs";

        const title = item.context?.title || item.context?.app || item.context?.domain || item.source;
        const sub = item.context?.domain || item.context?.package || item.context?.file || item.context?.workspace || "";

        let sourceBadge = `<span class="px-2 py-0.5 rounded text-[10px] font-semibold bg-sky-500/10 text-sky-400 border border-sky-500/20">Browser</span>`;
        if (item.source === "mobile") {{
          sourceBadge = `<span class="px-2 py-0.5 rounded text-[10px] font-semibold bg-purple-500/10 text-purple-400 border border-purple-500/20">Mobile</span>`;
        }} else if (item.source === "desktop") {{
          sourceBadge = `<span class="px-2 py-0.5 rounded text-[10px] font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">Desktop</span>`;
        }} else if (item.source === "vscode") {{
          sourceBadge = `<span class="px-2 py-0.5 rounded text-[10px] font-semibold bg-amber-500/10 text-amber-400 border border-amber-500/20">VS Code</span>`;
        }}

        row.innerHTML = `
          <div class="flex items-center gap-3 min-w-0">
            <span class="font-mono text-slate-400 text-[11px] shrink-0 w-24">${{parseTimeOnly(item.start)}} &ndash; ${{parseTimeOnly(item.end)}}</span>
            ${{sourceBadge}}
            <div class="min-w-0">
              <div class="font-medium text-slate-200 truncate max-w-sm sm:max-w-md md:max-w-xl" title="${{title}}">${{title}}</div>
              ${{sub ? `<div class="text-[11px] text-slate-500 truncate max-w-sm">${{sub}}</div>` : ''}}
            </div>
          </div>
          <span class="font-mono font-semibold text-slate-300 self-end sm:self-auto shrink-0 bg-slate-900 px-2 py-0.5 rounded border border-slate-800">${{formatSecs(item.duration_seconds)}}</span>
        `;
        container.appendChild(row);
      }});
    }}

    // Tab buttons handlers
    document.querySelectorAll(".tab-btn").forEach(btn => {{
      btn.onclick = () => {{
        document.querySelectorAll(".tab-btn").forEach(b => {{
          b.className = "tab-btn px-3 py-1.5 rounded-lg text-slate-400 hover:text-slate-200 transition flex items-center gap-1.5";
        }});
        btn.className = "tab-btn px-3 py-1.5 rounded-lg bg-sky-500 text-white font-medium transition flex items-center gap-1.5";
        activeMainTab = btn.getAttribute("data-tab");
        updateViewModeVisibility();
      }};
    }});

    // Filter tabs handlers
    document.querySelectorAll(".filter-btn").forEach(btn => {{
      btn.onclick = () => {{
        document.querySelectorAll(".filter-btn").forEach(b => {{
          b.className = "filter-btn px-2.5 py-1 rounded-lg text-slate-400 hover:text-slate-200 transition";
        }});
        btn.className = "filter-btn px-2.5 py-1 rounded-lg bg-sky-500 text-white font-medium transition";
        currentFilter = btn.getAttribute("data-filter");
        renderLedger(REPORTS_DATABASE[currentDate]?.timeline || []);
      }};
    }});

    // Search handler
    document.getElementById("timeline-search").oninput = (e) => {{
      searchQuery = e.target.value;
      renderLedger(REPORTS_DATABASE[currentDate]?.timeline || []);
    }};

    // Custom file loader (.json or .md)
    document.getElementById("file-input").onchange = (e) => {{
      const file = e.target.files[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = (evt) => {{
        const text = evt.target.result;
        if (file.name.endsWith(".json")) {{
          try {{
            const parsed = JSON.parse(text);
            const d = parsed.date || file.name.replace(".json", "");
            REPORTS_DATABASE[d] = parsed;
            currentDate = d;
            initDateButtons();
            renderAll();
            renderCalendarHeatmap();
          }} catch(err) {{
            alert("Could not parse JSON report file: " + err.message);
          }}
        }} else if (file.name.endsWith(".md")) {{
          const d = file.name.replace(".md", "");
          ANALYSES_DATABASE[d] = text;
          currentDate = d;
          initDateButtons();
          renderAll();
          renderCalendarHeatmap();
        }}
      }};
      reader.readAsText(file);
    }};

    function showToast(message, isError = false) {{
      const toast = document.getElementById("toast-notification");
      if (!toast) return;
      toast.textContent = message;
      if (isError) {{
        toast.className = "fixed bottom-5 right-5 z-50 px-4 py-2.5 rounded-lg text-xs font-mono shadow-2xl border bg-[#1a0f11] text-rose-300 border-rose-500/40 translate-y-0 opacity-100 transition-all duration-200";
      }} else {{
        toast.className = "fixed bottom-5 right-5 z-50 px-4 py-2.5 rounded-lg text-xs font-mono shadow-2xl border bg-[#0d1712] text-emerald-300 border-emerald-500/40 translate-y-0 opacity-100 transition-all duration-200";
      }}
      setTimeout(() => {{
        toast.className = "fixed bottom-5 right-5 z-50 px-4 py-2.5 rounded-lg text-xs font-mono shadow-2xl border translate-y-10 opacity-0 pointer-events-none transition-all duration-200";
      }}, 3500);
    }}

    async function triggerSyncMobile() {{
      const btn = document.getElementById("btn-sync-mobile");
      const text = document.getElementById("btn-sync-mobile-text");
      const orig = text.textContent;
      try {{
        btn.disabled = true;
        text.textContent = "Syncing ADB...";
        const resp = await fetch("http://127.0.0.1:8765/api/sync-mobile", {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify({{ date: currentDate }})
        }});
        const res = await resp.json();
        if (resp.ok && res.status === "ok") {{
          showToast(res.message || "Mobile sync complete!");
          if (res.report && res.report.date) {{
            REPORTS_DATABASE[res.report.date] = res.report;
            renderAll();
            initDateButtons();
            renderCalendarHeatmap();
          }}
        }} else {{
          showToast(res.message || "Mobile sync failed", true);
        }}
      }} catch (err) {{
        showToast("Collector offline. Run run_collector.bat", true);
      }} finally {{
        btn.disabled = false;
        text.textContent = orig;
      }}
    }}

    async function triggerGenerateReport() {{
      const btn = document.getElementById("btn-generate-report");
      const text = document.getElementById("btn-generate-report-text");
      const orig = text.textContent;
      try {{
        btn.disabled = true;
        text.textContent = "Generating...";
        const resp = await fetch("http://127.0.0.1:8765/api/generate-report", {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify({{ date: currentDate }})
        }});
        const res = await resp.json();
        if (resp.ok && res.status === "ok") {{
          showToast(`Report updated for ${{res.date}}!`);
          if (res.report && res.report.date) {{
            REPORTS_DATABASE[res.report.date] = res.report;
            renderAll();
            initDateButtons();
            renderCalendarHeatmap();
          }}
        }} else {{
          showToast(res.message || "Report generation failed", true);
        }}
      }} catch (err) {{
        showToast("Collector offline. Run run_collector.bat", true);
      }} finally {{
        btn.disabled = false;
        text.textContent = orig;
      }}
    }}

    // Initialization
    initDateButtons();
    renderAll();
    renderCalendarHeatmap();

    // Auto-scroll calendar container to rightmost edge (latest month) on initial load
    setTimeout(() => {{
      const scroller = document.getElementById("calendar-scroll-container");
      if (scroller) {{
        scroller.scrollLeft = scroller.scrollWidth;
      }}
    }}, 60);
  </script>

  <!-- Floating Toast Notification -->
  <div id="toast-notification" class="fixed bottom-5 right-5 z-50 px-4 py-2.5 rounded-lg text-xs font-mono shadow-2xl border translate-y-10 opacity-0 pointer-events-none transition-all duration-200"></div>
</body>
</html>
"""
    return html

def generate_dashboard_files(data_dir_str: str = "Record", output_str: str = "Record/reports/dashboard.html") -> bool:
    data_dir = Path(data_dir_str)
    if not data_dir.is_absolute():
        data_dir = Path(__file__).resolve().parent.parent.parent / data_dir_str

    if not data_dir.exists():
        print(f"Data directory not found: {data_dir}", file=sys.stderr)
        return False

    reports_data = {}
    report_candidates = []
    
    hierarchical_reports = list(data_dir.glob("report/**/daily/*.json"))
    report_candidates.extend(hierarchical_reports)
    
    legacy_reports = list(data_dir.glob("reports/*.json"))
    report_candidates.extend(legacy_reports)

    for f in sorted(report_candidates):
        if f.name == "dashboard.html":
            continue
        try:
            with open(f, "r", encoding="utf-8") as fp:
                data = json.load(fp)
                date_key = data.get("date", f.stem)
                reports_data[date_key] = data
        except Exception as e:
            print(f"Warning: Failed to load report {f.name}: {e}", file=sys.stderr)

    analyses_data = {}
    analysis_candidates = []
    
    hierarchical_analyses = list(data_dir.glob("analysis/**/daily/*.md"))
    analysis_candidates.extend(hierarchical_analyses)
    
    flat_analyses = list(data_dir.glob("analysis/*.md"))
    analysis_candidates.extend(flat_analyses)

    for f in sorted(analysis_candidates):
        try:
            with open(f, "r", encoding="utf-8") as fp:
                content = fp.read()
                date_key = f.stem
                analyses_data[date_key] = content
        except Exception as e:
            print(f"Warning: Failed to load analysis {f.name}: {e}", file=sys.stderr)

    all_dates = sorted(set(list(reports_data.keys()) + list(analyses_data.keys())))
    if not all_dates:
        print("No reports or analysis files found.", file=sys.stderr)
        return False

    latest_date = all_dates[-1]
    dashboard_html = build_dashboard_html(reports_data, analyses_data, latest_date)

    out_path = Path(output_str)
    if not out_path.is_absolute():
        out_path = Path(__file__).resolve().parent.parent.parent / output_str

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fp:
        fp.write(dashboard_html)

    # Also mirror into Record/report/dashboard.html
    mirror_path = data_dir / "report" / "dashboard.html"
    mirror_path.parent.mkdir(parents=True, exist_ok=True)
    with open(mirror_path, "w", encoding="utf-8") as fp:
        fp.write(dashboard_html)

    print(f"Dashboard successfully generated at: {out_path}")
    print(f"Mirrored to: {mirror_path}")
    return True

def main():
    parser = argparse.ArgumentParser(description="Generate interactive HTML dashboard from reports and analyses")
    parser.add_argument("--data-dir", type=str, default="Record", help="Root data directory containing report/ and analysis/")
    parser.add_argument("--output", type=str, default="Record/reports/dashboard.html", help="Output HTML file path")
    args = parser.parse_args()

    success = generate_dashboard_files(args.data_dir, args.output)
    if not success:
        sys.exit(1)

if __name__ == "__main__":
    main()
