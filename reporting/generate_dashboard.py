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
      --card: #111726;
      --card-hover: #172033;
      --border: #1e293b;
      --foreground: #f8fafc;
      --muted-foreground: #94a3b8;
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
      background: #334155;
      border-radius: 4px;
    }}
  </style>
</head>
<body class="antialiased p-4 sm:p-6 lg:p-8 selection:bg-sky-500/30 selection:text-sky-200">
  <div class="max-w-7xl mx-auto space-y-6">

    <!-- Top Navigation & Controls Bar -->
    <header class="bg-[var(--card)] border border-[var(--border)] rounded-2xl p-5 shadow-lg flex flex-col md:flex-row md:items-center justify-between gap-4">
      <div class="flex items-center gap-3">
        <div class="w-10 h-10 rounded-xl bg-gradient-to-tr from-sky-500 to-indigo-600 flex items-center justify-center shadow-md shadow-sky-500/20 text-white font-bold text-lg">
          ⏱️
        </div>
        <div>
          <h1 class="text-xl sm:text-2xl font-bold tracking-tight text-[var(--foreground)] flex items-center gap-2">
            Activity Intelligence Dashboard
            <span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
              ● 100% Coverage
            </span>
          </h1>
          <p class="text-xs sm:text-sm text-[var(--muted-foreground)]">Unified Digital Footprint: Browser &bull; VS Code &bull; Windows Desktop &bull; Android Mobile</p>
        </div>
      </div>

      <div class="flex flex-wrap items-center gap-3">
        <!-- Date Switcher Buttons -->
        <div id="date-buttons-container" class="inline-flex p-1 bg-slate-900/80 rounded-xl border border-[var(--border)] text-xs font-medium">
          <!-- Populated by JS -->
        </div>

        <!-- Custom JSON loader -->
        <label class="cursor-pointer inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-medium bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 transition">
          <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12"></path></svg>
          Load Report (.json/.md)
          <input type="file" id="file-input" accept=".json,.md" class="hidden">
        </label>
      </div>
    </header>

    <!-- View Mode Selector Tabs -->
    <div class="flex items-center justify-between border-b border-slate-800/80 pb-3">
      <div class="inline-flex p-1 bg-slate-900 rounded-xl border border-slate-800 text-xs font-medium" id="main-view-tabs">
        <button data-tab="split" class="tab-btn px-3 py-1.5 rounded-lg bg-sky-500 text-white font-medium transition flex items-center gap-1.5">
          <span>📊</span> Split Dashboard & Journal
        </button>
        <button data-tab="analytics" class="tab-btn px-3 py-1.5 rounded-lg text-slate-400 hover:text-slate-200 transition flex items-center gap-1.5">
          <span>📈</span> Full Analytics & Charts
        </button>
        <button data-tab="journal" class="tab-btn px-3 py-1.5 rounded-lg text-slate-400 hover:text-slate-200 transition flex items-center gap-1.5">
          <span>📝</span> Executive Journal (.md)
        </button>
      </div>

      <div id="has-analysis-badge" class="hidden sm:inline-flex items-center gap-1.5 text-xs text-emerald-400 bg-emerald-500/10 px-3 py-1 rounded-full border border-emerald-500/20">
        <span>✓</span> Daily Audit Markdown Attached
      </div>
    </div>

    <!-- KPI Metric Cards Grid -->
    <section class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
      <div class="bg-[var(--card)] border border-[var(--border)] rounded-2xl p-5 shadow-sm relative overflow-hidden group hover:border-sky-500/40 transition">
        <div class="absolute -right-3 -top-3 w-16 h-16 bg-sky-500/10 rounded-full blur-xl group-hover:bg-sky-500/20 transition"></div>
        <div class="text-xs font-semibold uppercase tracking-wider text-[var(--muted-foreground)]">Total Active Screen Time</div>
        <div id="metric-total-active" class="text-3xl font-extrabold text-[var(--foreground)] mt-2">--</div>
        <div id="metric-observed-span" class="text-xs text-[var(--muted-foreground)] mt-1.5 flex items-center gap-1">
          <span>Observed span:</span>
          <span class="font-medium text-slate-300">--</span>
        </div>
      </div>

      <div class="bg-[var(--card)] border border-[var(--border)] rounded-2xl p-5 shadow-sm relative overflow-hidden group hover:border-indigo-500/40 transition">
        <div class="absolute -right-3 -top-3 w-16 h-16 bg-indigo-500/10 rounded-full blur-xl group-hover:bg-indigo-500/20 transition"></div>
        <div class="text-xs font-semibold uppercase tracking-wider text-[var(--muted-foreground)]">Deep Focus / Engineering</div>
        <div id="metric-work-time" class="text-3xl font-extrabold text-indigo-400 mt-2">--</div>
        <div id="metric-work-pct" class="text-xs text-[var(--muted-foreground)] mt-1.5">Coding, AI Research, Problem Solving</div>
      </div>

      <div class="bg-[var(--card)] border border-[var(--border)] rounded-2xl p-5 shadow-sm relative overflow-hidden group hover:border-amber-500/40 transition">
        <div class="absolute -right-3 -top-3 w-16 h-16 bg-amber-500/10 rounded-full blur-xl group-hover:bg-amber-500/20 transition"></div>
        <div class="text-xs font-semibold uppercase tracking-wider text-[var(--muted-foreground)]">Context Transitions</div>
        <div id="metric-switches" class="text-3xl font-extrabold text-amber-400 mt-2">--</div>
        <div id="metric-switch-rate" class="text-xs text-[var(--muted-foreground)] mt-1.5">Switches across apps & tabs</div>
      </div>

      <div class="bg-[var(--card)] border border-[var(--border)] rounded-2xl p-5 shadow-sm relative overflow-hidden group hover:border-emerald-500/40 transition">
        <div class="absolute -right-3 -top-3 w-16 h-16 bg-emerald-500/10 rounded-full blur-xl group-hover:bg-emerald-500/20 transition"></div>
        <div class="text-xs font-semibold uppercase tracking-wider text-[var(--muted-foreground)]">Longest Single Focus Block</div>
        <div id="metric-longest-session" class="text-3xl font-extrabold text-emerald-400 mt-2">--</div>
        <div id="metric-longest-name" class="text-xs text-[var(--muted-foreground)] mt-1.5 truncate">--</div>
      </div>
    </section>

    <!-- Executive Journal (.md) Section (Rendered when in 'split' or 'journal' mode) -->
    <section id="journal-section" class="bg-[var(--card)] border border-[var(--border)] rounded-2xl p-6 shadow-sm space-y-4">
      <div class="flex flex-col sm:flex-row sm:items-center justify-between pb-3 border-b border-slate-800/80 gap-2">
        <div class="flex items-center gap-2">
          <div class="w-7 h-7 rounded-lg bg-sky-500/10 border border-sky-500/20 flex items-center justify-center text-sky-400 font-bold text-sm">
            📝
          </div>
          <div>
            <h2 class="text-base font-bold text-[var(--foreground)]" id="journal-heading">Executive Behavioral Audit & Journal</h2>
            <p class="text-xs text-[var(--muted-foreground)]" id="journal-filepath">Loaded from Record/analysis/YYYY/mmm/daily/{initial_date}.md</p>
          </div>
        </div>
        <div class="text-xs text-slate-400 font-mono" id="journal-date-tag">Date: --</div>
      </div>

      <!-- Rendered Markdown Body -->
      <div id="journal-content-container" class="prose prose-invert max-w-none text-slate-200">
        <!-- Rendered markdown goes here -->
      </div>
    </section>

    <!-- Source Split & Device Distribution -->
    <section id="analytics-split-section" class="bg-[var(--card)] border border-[var(--border)] rounded-2xl p-6 shadow-sm space-y-4">
      <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
        <div>
          <h2 class="text-base font-bold text-[var(--foreground)]">Device & Channel Allocation</h2>
          <p class="text-xs text-[var(--muted-foreground)]">Breakdown of attention between PC web, editors, native OS apps, and mobile device</p>
        </div>
        <div id="device-ratio-badge" class="text-xs font-mono px-3 py-1 bg-slate-800/80 rounded-lg text-slate-300 border border-slate-700/60 self-start">
          Ratio: --
        </div>
      </div>

      <!-- Segmented Bar -->
      <div id="source-split-bar" class="w-full h-4 rounded-full overflow-hidden flex bg-slate-900 border border-slate-800 shadow-inner">
        <!-- Dynamic segments -->
      </div>

      <!-- Source Badges Legend -->
      <div class="grid grid-cols-2 sm:grid-cols-4 gap-3 pt-2 text-xs">
        <div class="flex items-center gap-2.5 p-2 rounded-xl bg-slate-900/50 border border-slate-800">
          <span class="w-3.5 h-3.5 rounded-lg bg-sky-500 shrink-0"></span>
          <div class="min-w-0">
            <div class="font-semibold text-sky-400">PC Browser</div>
            <div id="source-stat-browser" class="text-slate-400 font-mono text-[11px]">--</div>
          </div>
        </div>

        <div class="flex items-center gap-2.5 p-2 rounded-xl bg-slate-900/50 border border-slate-800">
          <span class="w-3.5 h-3.5 rounded-lg bg-purple-500 shrink-0"></span>
          <div class="min-w-0">
            <div class="font-semibold text-purple-400">Android Mobile</div>
            <div id="source-stat-mobile" class="text-slate-400 font-mono text-[11px]">--</div>
          </div>
        </div>

        <div class="flex items-center gap-2.5 p-2 rounded-xl bg-slate-900/50 border border-slate-800">
          <span class="w-3.5 h-3.5 rounded-lg bg-emerald-500 shrink-0"></span>
          <div class="min-w-0">
            <div class="font-semibold text-emerald-400">Desktop Apps</div>
            <div id="source-stat-desktop" class="text-slate-400 font-mono text-[11px]">--</div>
          </div>
        </div>

        <div class="flex items-center gap-2.5 p-2 rounded-xl bg-slate-900/50 border border-slate-800">
          <span class="w-3.5 h-3.5 rounded-lg bg-amber-500 shrink-0"></span>
          <div class="min-w-0">
            <div class="font-semibold text-amber-400">VS Code Editor</div>
            <div id="source-stat-vscode" class="text-slate-400 font-mono text-[11px]">--</div>
          </div>
        </div>
      </div>
    </section>

    <!-- 24-Hour Gantt Timeline Strip -->
    <section id="analytics-ribbon-section" class="bg-[var(--card)] border border-[var(--border)] rounded-2xl p-6 shadow-sm space-y-4">
      <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
        <div>
          <h2 class="text-base font-bold text-[var(--foreground)]">24-Hour Chronological Activity Ribbon</h2>
          <p class="text-xs text-[var(--muted-foreground)]">Hover over any block to reveal exact session duration, domain/app, and timestamp</p>
        </div>
        <div class="text-xs text-slate-400 flex items-center gap-3">
          <span class="inline-flex items-center gap-1.5"><span class="w-2 h-2 rounded-full bg-sky-500"></span> Browser</span>
          <span class="inline-flex items-center gap-1.5"><span class="w-2 h-2 rounded-full bg-purple-500"></span> Mobile</span>
          <span class="inline-flex items-center gap-1.5"><span class="w-2 h-2 rounded-full bg-emerald-500"></span> Desktop</span>
          <span class="inline-flex items-center gap-1.5"><span class="w-2 h-2 rounded-full bg-amber-500"></span> VS Code</span>
        </div>
      </div>

      <!-- Timeline Container -->
      <div class="space-y-1.5">
        <div class="relative w-full h-14 bg-slate-950 rounded-xl border border-slate-800 overflow-hidden" id="timeline-strip-container">
          <!-- Session blocks injected here -->
        </div>

        <!-- 24-hour axis labels -->
        <div class="relative w-full h-4 text-[10px] font-mono text-slate-500 flex justify-between px-1">
          <span>00:00</span>
          <span>03:00</span>
          <span>06:00</span>
          <span>09:00</span>
          <span>12:00</span>
          <span>15:00</span>
          <span>18:00</span>
          <span>21:00</span>
          <span>23:59</span>
        </div>
      </div>

      <!-- Hover detail card -->
      <div id="timeline-hover-card" class="p-3 bg-slate-900/90 border border-slate-700/80 rounded-xl text-xs flex flex-wrap items-center justify-between gap-2">
        <div class="flex items-center gap-2">
          <span id="hover-source-pill" class="px-2 py-0.5 rounded text-[11px] font-semibold uppercase tracking-wider bg-slate-800 text-slate-300">Hover Block</span>
          <span id="hover-title" class="font-medium text-slate-200">Move mouse over the ribbon above to inspect sessions</span>
        </div>
        <div id="hover-time" class="font-mono text-slate-400">--:-- &ndash; --:--</div>
      </div>
    </section>

    <!-- Hourly Focus Density Chart & Longest Sessions -->
    <section id="analytics-charts-section" class="grid grid-cols-1 lg:grid-cols-3 gap-6">
      
      <!-- Hourly Stacked Bar Chart -->
      <div class="lg:col-span-2 bg-[var(--card)] border border-[var(--border)] rounded-2xl p-6 shadow-sm space-y-4">
        <div>
          <h2 class="text-base font-bold text-[var(--foreground)]">Hourly Activity Rhythm</h2>
          <p class="text-xs text-[var(--muted-foreground)]">Active minutes per hour throughout the day</p>
        </div>

        <div id="hourly-bars-container" class="h-48 flex items-end gap-1.5 sm:gap-2 pt-6 pb-2 border-b border-slate-800/80 overflow-x-auto custom-scroll">
          <!-- Hourly bars injected by JS -->
        </div>

        <div class="flex justify-between text-[11px] font-mono text-slate-500 px-1">
          <span>12 AM (Night)</span>
          <span>6 AM (Morning)</span>
          <span>12 PM (Noon)</span>
          <span>6 PM (Evening)</span>
          <span>11 PM (Night)</span>
        </div>
      </div>

      <!-- Top Longest Focused Sessions -->
      <div class="bg-[var(--card)] border border-[var(--border)] rounded-2xl p-6 shadow-sm space-y-4">
        <div>
          <h2 class="text-base font-bold text-[var(--foreground)]">Deepest Focus Stretches</h2>
          <p class="text-xs text-[var(--muted-foreground)]">Longest uninterrupted single sessions</p>
        </div>

        <div id="longest-sessions-list" class="space-y-2.5">
          <!-- Populated by JS -->
        </div>
      </div>

    </section>

    <!-- Detailed Leaderboards Grid (Domains, Mobile Apps, Desktop Apps) -->
    <section id="analytics-leaderboards-section" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
      
      <!-- Domains Card -->
      <div class="bg-[var(--card)] border border-[var(--border)] rounded-2xl p-6 shadow-sm space-y-4 flex flex-col">
        <div class="flex items-center justify-between">
          <h2 class="text-base font-bold text-[var(--foreground)] flex items-center gap-2">
            <span class="w-2.5 h-2.5 rounded-full bg-sky-500"></span> Top Websites
          </h2>
          <span id="domains-count-badge" class="text-xs font-mono text-slate-400">0 domains</span>
        </div>
        <div id="domains-list" class="space-y-3 flex-1 overflow-y-auto max-h-96 pr-1 custom-scroll">
          <!-- Populated by JS -->
        </div>
      </div>

      <!-- Mobile Apps Card -->
      <div class="bg-[var(--card)] border border-[var(--border)] rounded-2xl p-6 shadow-sm space-y-4 flex flex-col">
        <div class="flex items-center justify-between">
          <h2 class="text-base font-bold text-[var(--foreground)] flex items-center gap-2">
            <span class="w-2.5 h-2.5 rounded-full bg-purple-500"></span> Mobile Screen Time
          </h2>
          <span id="mobile-count-badge" class="text-xs font-mono text-slate-400">0 apps</span>
        </div>
        <div id="mobile-apps-list" class="space-y-3 flex-1 overflow-y-auto max-h-96 pr-1 custom-scroll">
          <!-- Populated by JS -->
        </div>
      </div>

      <!-- Desktop Applications Card -->
      <div class="bg-[var(--card)] border border-[var(--border)] rounded-2xl p-6 shadow-sm space-y-4 flex flex-col md:col-span-2 lg:col-span-1">
        <div class="flex items-center justify-between">
          <h2 class="text-base font-bold text-[var(--foreground)] flex items-center gap-2">
            <span class="w-2.5 h-2.5 rounded-full bg-emerald-500"></span> Desktop Apps
          </h2>
          <span id="desktop-count-badge" class="text-xs font-mono text-slate-400">0 apps</span>
        </div>
        <div id="desktop-apps-list" class="space-y-3 flex-1 overflow-y-auto max-h-96 pr-1 custom-scroll">
          <!-- Populated by JS -->
        </div>
      </div>

    </section>

    <!-- Comprehensive Filterable Timeline Table -->
    <section id="analytics-ledger-section" class="bg-[var(--card)] border border-[var(--border)] rounded-2xl p-6 shadow-sm space-y-4">
      <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h2 class="text-base font-bold text-[var(--foreground)]">Chronological Activity Ledger</h2>
          <p class="text-xs text-[var(--muted-foreground)]">Complete event-by-event history with duration and context</p>
        </div>

        <!-- Filter tabs & Search -->
        <div class="flex flex-wrap items-center gap-2.5">
          <div id="timeline-filters" class="inline-flex p-1 bg-slate-900 rounded-xl border border-slate-800 text-xs font-medium">
            <button data-filter="all" class="filter-btn px-2.5 py-1 rounded-lg bg-sky-500 text-white transition">All</button>
            <button data-filter="browser" class="filter-btn px-2.5 py-1 rounded-lg text-slate-400 hover:text-slate-200 transition">Browser</button>
            <button data-filter="mobile" class="filter-btn px-2.5 py-1 rounded-lg text-slate-400 hover:text-slate-200 transition">Mobile</button>
            <button data-filter="desktop" class="filter-btn px-2.5 py-1 rounded-lg text-slate-400 hover:text-slate-200 transition">Desktop</button>
            <button data-filter="vscode" class="filter-btn px-2.5 py-1 rounded-lg text-slate-400 hover:text-slate-200 transition">VS Code</button>
          </div>

          <div class="relative">
            <input type="text" id="timeline-search" placeholder="Search sessions..." class="bg-slate-900 border border-slate-800 rounded-xl px-3 py-1.5 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-sky-500 w-44 sm:w-56">
          </div>
        </div>
      </div>

      <!-- Ledger Container -->
      <div class="overflow-hidden border border-slate-800/80 rounded-xl bg-slate-950/60">
        <div class="max-h-[460px] overflow-y-auto custom-scroll divide-y divide-slate-800/60" id="timeline-table-body">
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
          <div class="p-8 text-center bg-slate-900/40 border border-dashed border-slate-800 rounded-xl space-y-3">
            <div class="text-3xl">📝</div>
            <div class="text-sm font-semibold text-slate-300">No Analysis Journal Recorded for ${{currentDate}}</div>
            <p class="text-xs text-slate-500 max-w-md mx-auto">
              You can add your executive daily audit by placing a markdown file at:<br>
              <code class="text-sky-400 bg-slate-950 px-2 py-1 rounded mt-2 inline-block border border-slate-800">
                Record/analysis/${{yr}}/${{mmm}}/daily/${{currentDate}}.md
              </code>
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

        let extraIcon = "";
        if (hasReport && hasMd) extraIcon = " • 📝";
        else if (hasMd) extraIcon = " 📝";

        btn.className = `px-3 py-1 rounded-lg transition ${{isActive ? 'bg-sky-500 text-white shadow-sm font-semibold' : 'text-slate-400 hover:text-slate-200'}}`;
        btn.textContent = `${{d}}${{extraIcon}}`;
        btn.onclick = () => {{
          currentDate = d;
          renderAll();
          initDateButtons();
        }};
        container.appendChild(btn);
      }});
    }}

    function updateViewModeVisibility() {{
      const jSec = document.getElementById("journal-section");
      const splitSec = document.getElementById("analytics-split-section");
      const ribbonSec = document.getElementById("analytics-ribbon-section");
      const chartsSec = document.getElementById("analytics-charts-section");
      const boardsSec = document.getElementById("analytics-leaderboards-section");
      const ledgerSec = document.getElementById("analytics-ledger-section");

      if (activeMainTab === "journal") {{
        jSec.classList.remove("hidden");
        splitSec.classList.add("hidden");
        ribbonSec.classList.add("hidden");
        chartsSec.classList.add("hidden");
        boardsSec.classList.add("hidden");
        ledgerSec.classList.add("hidden");
      }} else if (activeMainTab === "analytics") {{
        jSec.classList.add("hidden");
        splitSec.classList.remove("hidden");
        ribbonSec.classList.remove("hidden");
        chartsSec.classList.remove("hidden");
        boardsSec.classList.remove("hidden");
        ledgerSec.classList.remove("hidden");
      }} else {{ // 'split'
        jSec.classList.remove("hidden");
        splitSec.classList.remove("hidden");
        ribbonSec.classList.remove("hidden");
        chartsSec.classList.remove("hidden");
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

      renderTimelineRibbon(rep.timeline || []);
      renderHourlyChart(rep.hourly_breakdown || []);
      renderLongestSessions(rep.longest_sessions || []);
      renderDomains(rep.domains || []);
      renderMobileApps(rep.apps || []);
      renderDesktopApps(rep.desktop_apps || []);
      renderLedger(rep.timeline || []);
      updateViewModeVisibility();
    }}

    function renderTimelineRibbon(timeline) {{
      const container = document.getElementById("timeline-strip-container");
      container.innerHTML = "";
      if (!timeline || timeline.length === 0) return;

      timeline.forEach(item => {{
        const start = new Date(item.start);
        const end = new Date(item.end);
        
        const startSec = start.getHours() * 3600 + start.getMinutes() * 60 + start.getSeconds();
        const endSec = end.getHours() * 3600 + end.getMinutes() * 60 + end.getSeconds();
        
        const leftPct = (startSec / 86400) * 100;
        let widthPct = ((endSec - startSec) / 86400) * 100;
        if (widthPct < 0.2) widthPct = 0.2;

        const block = document.createElement("div");
        block.className = "absolute top-2 bottom-2 rounded-sm cursor-pointer transition hover:opacity-100 hover:scale-y-125 hover:z-20";
        block.style.left = `${{leftPct}}%`;
        block.style.width = `${{widthPct}}%`;

        let colorClass = "bg-sky-500/80";
        if (item.source === "mobile") colorClass = "bg-purple-500/80";
        else if (item.source === "desktop") colorClass = "bg-emerald-500/80";
        else if (item.source === "vscode") colorClass = "bg-amber-500/80";

        block.className += ` ${{colorClass}}`;

        block.onmouseenter = () => {{
          const title = item.context?.title || item.context?.app || item.context?.domain || item.source;
          const sub = item.context?.domain || item.context?.package || item.context?.workspace || "";
          document.getElementById("hover-title").innerHTML = `<strong class="text-white">${{title}}</strong> ${{sub ? '<span class="text-slate-400">(' + sub + ')</span>' : ''}}`;
          document.getElementById("hover-time").textContent = `${{parseTimeOnly(item.start)}} - ${{parseTimeOnly(item.end)}} (${{formatSecs(item.duration_seconds)}})`;
          
          const pill = document.getElementById("hover-source-pill");
          pill.textContent = item.source;
          pill.className = `px-2 py-0.5 rounded text-[11px] font-semibold uppercase tracking-wider ${{
            item.source === 'mobile' ? 'bg-purple-900/60 text-purple-300 border border-purple-700' :
            item.source === 'desktop' ? 'bg-emerald-900/60 text-emerald-300 border border-emerald-700' :
            item.source === 'vscode' ? 'bg-amber-900/60 text-amber-300 border border-amber-700' :
            'bg-sky-900/60 text-sky-300 border border-sky-700'
          }}`;
        }};

        container.appendChild(block);
      }});
    }}

    function renderHourlyChart(hourly) {{
      const container = document.getElementById("hourly-bars-container");
      container.innerHTML = "";

      const hourMap = {{}};
      for (let h = 0; h < 24; h++) {{
        hourMap[h] = {{ active_seconds: 0, browser: 0, mobile: 0, desktop: 0, vscode: 0 }};
      }}

      hourly.forEach(entry => {{
        if (hourMap[entry.hour] !== undefined) {{
          hourMap[entry.hour] = {{
            active_seconds: entry.active_seconds || 0,
            browser: entry.browser_seconds || 0,
            mobile: entry.mobile_seconds || 0,
            desktop: entry.desktop_seconds || 0,
            vscode: entry.vscode_seconds || 0
          }};
        }}
      }});

      for (let h = 0; h < 24; h++) {{
        const item = hourMap[h];
        const col = document.createElement("div");
        col.className = "flex-1 flex flex-col items-center justify-end h-full group relative cursor-pointer";

        const total = item.active_seconds;
        const totalHeightPct = Math.min(100, (total / 3600) * 100);

        const bH = total > 0 ? (item.browser / total) * 100 : 0;
        const mH = total > 0 ? (item.mobile / total) * 100 : 0;
        const dH = total > 0 ? (item.desktop / total) * 100 : 0;
        const vH = total > 0 ? (item.vscode / total) * 100 : 0;

        col.innerHTML = `
          <div class="opacity-0 group-hover:opacity-100 transition absolute -top-12 z-30 bg-slate-900 border border-slate-700 text-slate-200 text-[10px] px-2 py-1 rounded shadow-lg whitespace-nowrap pointer-events-none">
            ${{h}}:00 &bull; ${{formatSecs(total)}}
          </div>
          <div class="w-full bg-slate-900 rounded-t-sm flex flex-col-reverse overflow-hidden transition-all duration-300 group-hover:brightness-125" style="height: ${{Math.max(4, totalHeightPct)}}%">
            <div class="bg-sky-500 w-full" style="height: ${{bH}}%"></div>
            <div class="bg-purple-500 w-full" style="height: ${{mH}}%"></div>
            <div class="bg-emerald-500 w-full" style="height: ${{dH}}%"></div>
            <div class="bg-amber-500 w-full" style="height: ${{vH}}%"></div>
          </div>
          <span class="text-[9px] font-mono text-slate-500 mt-1">${{h}}</span>
        `;
        container.appendChild(col);
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
        if (searchQuery) {{
          const q = searchQuery.toLowerCase();
          const title = (item.context?.title || item.context?.app || item.context?.domain || "").toLowerCase();
          const sub = (item.context?.domain || item.context?.package || item.context?.file || "").toLowerCase();
          if (!title.includes(q) && !sub.includes(q)) return false;
        }}
        return true;
      }});

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
          }} catch(err) {{
            alert("Could not parse JSON report file: " + err.message);
          }}
        }} else if (file.name.endsWith(".md")) {{
          const d = file.name.replace(".md", "");
          ANALYSES_DATABASE[d] = text;
          currentDate = d;
          initDateButtons();
          renderAll();
        }}
      }};
      reader.readAsText(file);
    }};

    // Initialization
    initDateButtons();
    renderAll();
  </script>
</body>
</html>
"""
    return html

def main():
    parser = argparse.ArgumentParser(description="Generate interactive HTML dashboard from reports and analyses")
    parser.add_argument("--data-dir", type=str, default="Record", help="Root data directory containing report/ and analysis/")
    parser.add_argument("--output", type=str, default="Record/reports/dashboard.html", help="Output HTML file path")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    if not data_dir.is_absolute():
        data_dir = Path(__file__).resolve().parent.parent.parent / args.data_dir

    if not data_dir.exists():
        print(f"Data directory not found: {data_dir}", file=sys.stderr)
        sys.exit(1)

    # 1. Scan JSON reports from both Record/report/**/daily/*.json and Record/reports/*.json
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

    # 2. Scan Markdown analyses from Record/analysis/**/daily/*.md and Record/analysis/*.md
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
                # Use filename stem as date (YYYY-MM-DD)
                date_key = f.stem
                analyses_data[date_key] = content
        except Exception as e:
            print(f"Warning: Failed to load analysis {f.name}: {e}", file=sys.stderr)

    all_dates = sorted(set(list(reports_data.keys()) + list(analyses_data.keys())))
    if not all_dates:
        print("No reports or analysis files found.", file=sys.stderr)
        sys.exit(1)

    latest_date = all_dates[-1]
    dashboard_html = build_dashboard_html(reports_data, analyses_data, latest_date)

    out_path = Path(args.output)
    if not out_path.is_absolute():
        out_path = Path(__file__).resolve().parent.parent.parent / args.output

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
    print(f"Loaded {len(reports_data)} JSON reports: {', '.join(reports_data.keys())}")
    print(f"Loaded {len(analyses_data)} Markdown analyses: {', '.join(analyses_data.keys())}")

if __name__ == "__main__":
    main()
