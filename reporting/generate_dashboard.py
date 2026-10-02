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
import os
import sys
from pathlib import Path
from typing import Dict, Any, List
from datetime import datetime

# Add parent directory to path so we can import collector modules
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from collector.config import get_config

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
    try:
        cfg = get_config()
        auth_token_str = getattr(cfg, "auth_token", "") or ""
    except Exception:
        auth_token_str = ""
    auth_token_json = json.dumps(auth_token_str)
    
    # Pre-render markdown to HTML with tables enabled using markdown-it-py
    analyses_html_data = {}
    try:
        venv_site_packages = r's:\project\RAG\.venv\Lib\site-packages'
        if venv_site_packages not in sys.path and os.path.exists(venv_site_packages):
            sys.path.append(venv_site_packages)
        from markdown_it import MarkdownIt
        md_parser = MarkdownIt().enable('table').enable('strikethrough')
        for d_key, md_text in analyses_data.items():
            analyses_html_data[d_key] = md_parser.render(md_text)
    except Exception as e:
        print(f"Notice: Markdown pre-rendering skipped: {e}", file=sys.stderr)
        
    analyses_html_json = json.dumps(analyses_html_data)
    
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Activity Tracker - Executive Visual Dashboard</title>
  <script src="https://www.gstatic.com/antigravity/web/dev/tailwindcss.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
  <style>
    :root {{
      --background: #090a0f;
      --card: #11141e;
      --card-hover: #161b29;
      --border: rgba(255, 255, 255, 0.08);
      --border-subtle: rgba(255, 255, 255, 0.04);
      --foreground: #f8fafc;
      --muted-foreground: #94a3b8;
      --primary: #6366f1;
      --primary-foreground: #ffffff;
    }}
    body {{
      background-color: var(--background);
      background-image: radial-gradient(ellipse 80% 50% at 50% -20%, rgba(99, 102, 241, 0.08), transparent 70%);
      background-attachment: fixed;
      color: var(--foreground);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Inter", Helvetica, Arial, sans-serif;
    }}
    .custom-scroll::-webkit-scrollbar {{
      width: 5px;
      height: 5px;
    }}
    .custom-scroll::-webkit-scrollbar-track {{
      background: #090a0f;
    }}
    .custom-scroll::-webkit-scrollbar-thumb {{
      background: #1e2436;
      border-radius: 3px;
    }}
    .custom-scroll::-webkit-scrollbar-thumb:hover {{
      background: #2b334c;
    }}

    /* Executive Markdown Journal Presentation */
    .markdown-body {{
      color: #cbd5e1;
      font-size: 0.875rem;
      line-height: 1.7;
    }}
    .markdown-body h1 {{
      font-size: 1.45rem;
      font-weight: 700;
      color: #ffffff;
      margin-top: 1.25rem;
      margin-bottom: 0.875rem;
      letter-spacing: -0.025em;
      border-bottom: 1px solid rgba(255, 255, 255, 0.08);
      padding-bottom: 0.5rem;
    }}
    .markdown-body h2 {{
      font-size: 1.15rem;
      font-weight: 600;
      color: #f1f5f9;
      margin-top: 1.75rem;
      margin-bottom: 0.75rem;
      letter-spacing: -0.015em;
      border-bottom: 1px solid rgba(255, 255, 255, 0.06);
      padding-bottom: 0.375rem;
    }}
    .markdown-body h3 {{
      font-size: 0.975rem;
      font-weight: 600;
      color: #e2e8f0;
      margin-top: 1.25rem;
      margin-bottom: 0.5rem;
    }}
    .markdown-body p {{
      margin-bottom: 0.875rem;
      color: #cbd5e1;
    }}
    .markdown-body strong {{
      color: #ffffff;
      font-weight: 600;
    }}
    .markdown-body em {{
      color: #cbd5e1;
      font-style: italic;
    }}
    .markdown-body hr {{
      border: 0;
      border-top: 1px solid rgba(255, 255, 255, 0.08);
      margin: 1.75rem 0;
    }}
    .markdown-body ul {{
      list-style-type: disc;
      padding-left: 1.35rem;
      margin-bottom: 1rem;
    }}
    .markdown-body ol {{
      list-style-type: decimal;
      padding-left: 1.35rem;
      margin-bottom: 1rem;
    }}
    .markdown-body li {{
      margin-bottom: 0.375rem;
      padding-left: 0.25rem;
      line-height: 1.65;
    }}
    .markdown-body li::marker {{
      color: #818cf8;
    }}
    .markdown-body blockquote {{
      border-left: 3px solid #6366f1;
      background: rgba(99, 102, 241, 0.04);
      border-radius: 0 0.5rem 0.5rem 0;
      padding: 0.75rem 1rem;
      margin: 1rem 0;
      color: #94a3b8;
    }}
    .markdown-body blockquote p:last-child {{
      margin-bottom: 0;
    }}
    .markdown-body table {{
      width: 100%;
      border-collapse: separate;
      border-spacing: 0;
      margin: 1.25rem 0;
      font-size: 0.8125rem;
      border: 1px solid rgba(255, 255, 255, 0.08);
      border-radius: 0.625rem;
      overflow: hidden;
    }}
    .markdown-body th {{
      background-color: #161b29;
      color: #f8fafc;
      font-weight: 600;
      text-align: left;
      padding: 0.65rem 0.875rem;
      border-bottom: 1px solid rgba(255, 255, 255, 0.08);
      border-right: 1px solid rgba(255, 255, 255, 0.04);
      font-size: 0.75rem;
      text-transform: uppercase;
      letter-spacing: 0.03em;
    }}
    .markdown-body th:last-child {{
      border-right: none;
    }}
    .markdown-body td {{
      padding: 0.6rem 0.875rem;
      border-bottom: 1px solid rgba(255, 255, 255, 0.04);
      border-right: 1px solid rgba(255, 255, 255, 0.04);
      color: #cbd5e1;
      vertical-align: top;
    }}
    .markdown-body td:last-child {{
      border-right: none;
    }}
    .markdown-body tr:last-child td {{
      border-bottom: none;
    }}
    .markdown-body tr:nth-child(even) {{
      background-color: rgba(255, 255, 255, 0.015);
    }}
    .markdown-body tr:hover td {{
      background-color: rgba(255, 255, 255, 0.03);
    }}
    .markdown-body code:not(pre code) {{
      background-color: rgba(255, 255, 255, 0.06);
      border: 1px solid rgba(255, 255, 255, 0.08);
      padding: 0.15rem 0.35rem;
      border-radius: 0.25rem;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      font-size: 0.775rem;
      color: #e0e7ff;
    }}
    .markdown-body pre {{
      background: #06080e;
      border: 1px solid rgba(255, 255, 255, 0.08);
      border-radius: 0.625rem;
      padding: 1rem;
      margin: 1rem 0;
      overflow-x: auto;
    }}
    .markdown-body pre code {{
      background: transparent;
      border: none;
      padding: 0;
      font-size: 0.8rem;
      color: #e2e8f0;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
    }}
    .markdown-body a {{
      color: #818cf8;
      text-decoration: underline;
      text-underline-offset: 3px;
      transition: color 0.15s ease;
    }}
    .markdown-body a:hover {{
      color: #a5b4fc;
    }}
    #overview-journal-preview.markdown-body h1,
    #overview-journal-preview.markdown-body h2 {{
      font-size: 0.95rem;
      font-weight: 600;
      color: #f1f5f9;
      margin-top: 0.75rem;
      margin-bottom: 0.35rem;
      padding-bottom: 0.2rem;
    }}
    #overview-journal-preview.markdown-body h1:first-child,
    #overview-journal-preview.markdown-body h2:first-child,
    #overview-journal-preview.markdown-body h3:first-child,
    #overview-journal-preview.markdown-body p:first-child {{
      margin-top: 0;
    }}
    #overview-journal-preview.markdown-body h3 {{
      font-size: 0.85rem;
      font-weight: 600;
      color: #e2e8f0;
      margin-top: 0.5rem;
      margin-bottom: 0.25rem;
    }}
    #overview-journal-preview.markdown-body p {{
      margin-bottom: 0.5rem;
      font-size: 0.8rem;
      line-height: 1.5;
    }}
    #overview-journal-preview.markdown-body ul,
    #overview-journal-preview.markdown-body ol {{
      margin-bottom: 0.5rem;
      padding-left: 1.15rem;
      font-size: 0.8rem;
    }}
    #overview-journal-preview.markdown-body li {{
      margin-bottom: 0.25rem;
      line-height: 1.5;
    }}
    #overview-journal-preview.markdown-body table {{
      margin: 0.5rem 0;
      font-size: 0.75rem;
    }}
    #overview-journal-preview.markdown-body th,
    #overview-journal-preview.markdown-body td {{
      padding: 0.35rem 0.5rem;
    }}
  </style>
</head>
<body class="antialiased p-4 sm:p-6 lg:p-8 text-[#f8fafc] selection:bg-indigo-500/30 selection:text-white min-h-screen">
  <div class="max-w-7xl mx-auto space-y-4">

    <!-- Top Navigation & Controls Bar -->
    <header class="bg-[var(--card)] border border-[var(--border)] rounded-xl px-4 py-3 shadow-[inset_0_1px_0_rgba(255,255,255,0.05)] flex flex-col md:flex-row md:items-center justify-between gap-3">
      <div class="flex items-center gap-3">
        <div class="w-8 h-8 rounded-lg bg-white/[0.04] border border-white/[0.08] flex items-center justify-center text-slate-300">
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
        </div>
        <div>
          <div class="flex items-center gap-2">
            <h1 class="text-sm font-semibold tracking-tight text-white">Activity Tracker</h1>
            <span id="header-today-badge" class="hidden text-[9px] uppercase px-1.5 py-0.2 rounded bg-indigo-500/10 text-indigo-300 border border-indigo-500/20 font-sans font-bold">Today</span>
          </div>
          <div class="text-xs font-mono text-slate-400" id="header-active-date">--</div>
        </div>
      </div>

      <div class="flex flex-wrap items-center gap-2">
        <!-- Date Stepper: Prev & Next & Quick Dates -->
        <div class="inline-flex items-center p-0.5 bg-[#0c0e16] rounded-lg border border-white/[0.08] text-xs">
          <button onclick="selectPreviousDate()" class="px-2 py-1 rounded text-slate-400 hover:text-white hover:bg-white/[0.04] transition font-mono" title="Previous recorded day">&larr; Prev</button>
          <div id="date-buttons-container" class="inline-flex">
            <!-- Populated by JS -->
          </div>
          <button onclick="selectNextDate()" class="px-2 py-1 rounded text-slate-400 hover:text-white hover:bg-white/[0.04] transition font-mono" title="Next recorded day">Next &rarr;</button>
        </div>

        <!-- Sync Mobile & Generate Report Actions -->
        <button id="btn-sync-mobile" onclick="triggerSyncMobile()" class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium bg-[#161a27] hover:bg-[#1e2335] text-slate-200 border border-white/[0.08] transition disabled:opacity-50">
          <svg class="w-3.5 h-3.5 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 18h.01M8 21h8a2 2 0 002-2V5a2 2 0 00-2-2H8a2 2 0 00-2 2v14a2 2 0 002 2z"></path></svg>
          <span id="btn-sync-mobile-text">Sync Mobile</span>
        </button>

        <button id="btn-generate-report" onclick="triggerGenerateReport()" class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium bg-[#161a27] hover:bg-[#1e2335] text-slate-200 border border-white/[0.08] transition disabled:opacity-50">
          <svg class="w-3.5 h-3.5 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"></path></svg>
          <span id="btn-generate-report-text">Generate Report</span>
        </button>

        <button id="btn-label-gap" onclick="openLabelGapModal()" class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium bg-[#f97316]/15 hover:bg-[#f97316]/25 text-[#fb923c] border border-[#f97316]/30 transition">
          <svg class="w-3.5 h-3.5 text-[#fb923c]" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"></path></svg>
          <span id="btn-label-gap-text">Log Offline</span>
        </button>

        <!-- Custom JSON loader -->
        <label class="cursor-pointer inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium bg-[#161a27] hover:bg-[#1e2335] text-slate-200 border border-white/[0.08] transition">
          <svg class="w-3.5 h-3.5 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12"></path></svg>
          Import
          <input type="file" id="file-input" accept=".json,.md" class="hidden">
        </label>
      </div>
    </header>

    <!-- Main Navigation Tabs (4 Focused Views) -->
    <nav class="flex items-center justify-between border-b border-[var(--border)] pb-2.5">
      <div class="inline-flex p-1 bg-[#0c0e16] rounded-xl border border-white/[0.08] text-xs font-medium gap-1" id="main-nav-tabs">
        <button id="tab-btn-overview" onclick="setActiveTab('overview')" class="tab-btn px-3.5 py-1.5 rounded-lg bg-white/[0.08] text-white font-medium border border-white/[0.14] shadow-sm transition flex items-center gap-2 text-xs">
          <svg class="w-3.5 h-3.5 text-slate-300" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2V6zM14 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2V6zM4 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2v-2zM14 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2v-2z"></path></svg>
          Overview
        </button>
        <button id="tab-btn-analytics" onclick="setActiveTab('analytics')" class="tab-btn px-3.5 py-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-white/[0.04] border border-transparent transition flex items-center gap-2 text-xs">
          <svg class="w-3.5 h-3.5 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"></path></svg>
          Analytics
        </button>
        <button id="tab-btn-sessions" onclick="setActiveTab('sessions')" class="tab-btn px-3.5 py-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-white/[0.04] border border-transparent transition flex items-center gap-2 text-xs">
          <svg class="w-3.5 h-3.5 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
          Sessions
          <span id="nav-session-count-badge" class="px-1.5 py-0.2 rounded-full text-[10px] font-mono bg-white/[0.06] text-slate-300">0</span>
        </button>
        <button id="tab-btn-journal" onclick="setActiveTab('journal')" class="tab-btn px-3.5 py-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-white/[0.04] border border-transparent transition flex items-center gap-2 text-xs">
          <svg class="w-3.5 h-3.5 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253"></path></svg>
          Journal
          <span id="nav-journal-dot" class="w-1.5 h-1.5 rounded-full bg-[#34d399] hidden"></span>
        </button>
      </div>

      <div class="flex items-center gap-3 text-xs">
        <div id="has-analysis-badge" class="hidden sm:inline-flex items-center gap-1.5 text-xs text-slate-400">
          <span class="w-1.5 h-1.5 rounded-full bg-[#34d399]"></span> Analysis note attached
        </div>
      </div>
    </nav>

    <!-- ==================== VIEW 1: OVERVIEW ("What happened today?") ==================== -->
    <div id="view-tab-overview" class="space-y-4">

      <!-- Annual Activity Contribution Heatmap (GitHub/LeetCode block style) -->
      <section class="bg-[var(--card)] border border-[var(--border)] rounded-xl p-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.05)] space-y-2.5">
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
              <span class="w-2.5 h-2.5 rounded-[2px] bg-[#131620] border border-white/[0.05]" title="No activity"></span>
              <span class="w-2.5 h-2.5 rounded-[2px] bg-[#0f2e24] border border-[#18493a]" title="< 2h"></span>
              <span class="w-2.5 h-2.5 rounded-[2px] bg-[#144738] border border-[#1f6b54]" title="2h - 4h"></span>
              <span class="w-2.5 h-2.5 rounded-[2px] bg-[#1a664f] border border-[#299171]" title="4h - 6h"></span>
              <span class="w-2.5 h-2.5 rounded-[2px] bg-[#228e6c] border border-[#34d399]" title="> 6h"></span>
              <span>More</span>
            </div>
          </div>
        </div>

        <!-- Heatmap Scroll Container -->
        <div id="calendar-scroll-container" class="overflow-x-auto custom-scroll pb-2 pt-1">
          <div class="inline-flex gap-2 min-w-full">
            <!-- Weekday Labels Column -->
            <div class="flex flex-col text-[10px] text-neutral-500 font-mono select-none pt-[18px] shrink-0" style="gap: 3px;">
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
              <div id="calendar-months-row" class="h-4 relative text-[10px] text-neutral-500 font-mono select-none"></div>
              <div id="calendar-days-grid" class="grid grid-rows-7 grid-flow-col" style="gap: 3px;"></div>
            </div>
          </div>
        </div>
      </section>

      <!-- KPI Metric Cards Grid -->
      <section class="grid grid-cols-1 sm:grid-cols-2 gap-3.5">
        <div class="bg-[var(--card)] border border-[var(--border)] rounded-xl p-4 transition-all duration-200 hover:border-white/[0.18] shadow-[inset_0_1px_0_rgba(255,255,255,0.05)] relative group">
          <div class="flex items-center justify-between">
            <span class="text-[11px] font-medium uppercase tracking-wider text-slate-400">Active Screen Time</span>
            <div class="w-6 h-6 rounded bg-white/[0.04] border border-white/[0.08] flex items-center justify-center text-slate-400 group-hover:text-slate-200 transition">
              <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
            </div>
          </div>
          <div id="metric-total-active" class="text-2xl font-bold text-white mt-1.5 font-mono tracking-tight">--</div>
          <div id="metric-observed-span" class="text-xs text-slate-400 mt-1">Observed span: --</div>
        </div>

        <div class="bg-[var(--card)] border border-[var(--border)] rounded-xl p-4 transition-all duration-200 hover:border-white/[0.18] shadow-[inset_0_1px_0_rgba(255,255,255,0.05)] relative group">
          <div class="flex items-center justify-between">
            <span class="text-[11px] font-medium uppercase tracking-wider text-slate-400">Longest Focus Block</span>
            <div class="w-6 h-6 rounded bg-white/[0.04] border border-white/[0.08] flex items-center justify-center text-slate-400 group-hover:text-slate-200 transition">
              <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"></path></svg>
            </div>
          </div>
          <div id="metric-longest-session" class="text-2xl font-bold text-white mt-1.5 font-mono tracking-tight">--</div>
          <div id="metric-longest-name" class="text-xs text-slate-400 mt-1 truncate">--</div>
        </div>
      </section>

      <!-- Overview Split: Daily Executive Summary (AI Journal Preview) & Day at a Glance -->
      <section class="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <!-- Left: Daily Executive Summary (AI Journal Preview) -->
        <div class="bg-[var(--card)] border border-[var(--border)] rounded-xl p-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.05)] flex flex-col justify-between space-y-3">
          <div class="space-y-3">
            <div class="flex items-center justify-between pb-2.5 border-b border-[var(--border)]">
              <div class="flex items-center gap-2">
                <div class="w-6 h-6 rounded-md bg-white/[0.04] border border-white/[0.08] flex items-center justify-center text-slate-300">
                  <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"></path></svg>
                </div>
                <h3 class="text-sm font-semibold text-white">Executive AI Summary</h3>
              </div>
              <button onclick="setActiveTab('journal')" class="text-xs font-mono text-slate-400 hover:text-white transition flex items-center gap-1">
                Full Journal &rarr;
              </button>
            </div>
            
            <div id="overview-journal-preview" class="markdown-body text-xs text-slate-300 leading-relaxed max-h-[260px] overflow-y-auto custom-scroll space-y-2 pr-1">
              <!-- Rendered preview -->
            </div>
          </div>

          <div class="pt-2 border-t border-white/[0.05] flex items-center justify-between text-[11px] text-slate-500 font-mono">
            <span id="overview-journal-meta">Record/analysis/...</span>
            <button onclick="setActiveTab('journal')" class="text-slate-400 hover:text-white transition">Read full analysis &rarr;</button>
          </div>
        </div>

        <!-- Right: Day at a Glance (Key Information Snapshot) -->
        <div class="bg-[var(--card)] border border-[var(--border)] rounded-xl p-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.05)] flex flex-col justify-between space-y-3">
          <div class="space-y-3.5">
            <div class="flex items-center justify-between pb-2.5 border-b border-[var(--border)]">
              <div class="flex items-center gap-2">
                <div class="w-6 h-6 rounded-md bg-white/[0.04] border border-white/[0.08] flex items-center justify-center text-slate-300">
                  <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"></path></svg>
                </div>
                <h3 class="text-sm font-semibold text-white">Day at a Glance</h3>
              </div>
              <button onclick="setActiveTab('analytics')" class="text-xs font-mono text-slate-400 hover:text-white transition flex items-center gap-1">
                Full Analytics &rarr;
              </button>
            </div>

            <!-- Device Distribution Mini-Bar -->
            <div class="space-y-1.5">
              <div class="flex justify-between items-center text-xs">
                <span class="text-slate-400 font-medium">Device Distribution</span>
                <span id="overview-device-ratio" class="font-mono text-slate-300 text-[11px]">PC: -- | Mobile: --</span>
              </div>
              <div id="overview-source-split-bar" class="w-full h-2.5 rounded-full overflow-hidden flex bg-[#0c0e16] border border-white/[0.08]">
                <!-- Injected via JS -->
              </div>
              <div class="flex flex-wrap items-center justify-between text-[10px] text-slate-400 font-mono pt-0.5 gap-2">
                <span class="inline-flex items-center gap-1"><span class="w-2 h-2 rounded-sm bg-[#38bdf8]"></span> Browser <span id="overview-stat-browser" class="text-slate-200">--</span></span>
                <span class="inline-flex items-center gap-1"><span class="w-2 h-2 rounded-sm bg-[#a78bfa]"></span> Mobile <span id="overview-stat-mobile" class="text-slate-200">--</span></span>
                <span class="inline-flex items-center gap-1"><span class="w-2 h-2 rounded-sm bg-[#34d399]"></span> Desktop <span id="overview-stat-desktop" class="text-slate-200">--</span></span>
                <span class="inline-flex items-center gap-1"><span class="w-2 h-2 rounded-sm bg-[#fbbf24]"></span> VS Code <span id="overview-stat-vscode" class="text-slate-200">--</span></span>
              </div>
            </div>

            <!-- Top 3 Focus Sessions Snapshot -->
            <div class="space-y-1.5">
              <div class="flex justify-between items-center text-xs">
                <span class="text-slate-400 font-medium">Top Focus Sessions Today</span>
                <span class="text-[11px] text-slate-500 font-mono">Longest blocks</span>
              </div>
              <div id="overview-top-sessions" class="space-y-1.5">
                <!-- Injected via JS -->
              </div>
            </div>
          </div>

          <div class="pt-2 border-t border-white/[0.05] flex items-center justify-between text-[11px] text-slate-500 font-mono">
            <span id="overview-rhythm-highlight">Span: -- to --</span>
            <button onclick="setActiveTab('sessions')" class="text-slate-400 hover:text-white transition">View all sessions &rarr;</button>
          </div>
        </div>
      </section>
    </div>

    <!-- ==================== VIEW 2: ANALYTICS ("Where did my time go?") ==================== -->
    <div id="view-tab-analytics" class="hidden space-y-4">
      <!-- Source Split & Device Distribution -->
      <section id="analytics-split-section" class="bg-[var(--card)] border border-[var(--border)] rounded-xl p-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.05)] space-y-3">
        <div class="flex items-center justify-between">
          <div>
            <h2 class="text-sm font-semibold text-[var(--foreground)]">Device Breakdown</h2>
            <p class="text-xs text-[var(--muted-foreground)] mt-0.5">Distribution of time across personal computing and mobile devices</p>
          </div>
          <div id="device-ratio-badge" class="text-xs font-mono px-2.5 py-1 bg-[#0c0e16] rounded text-slate-200 border border-white/[0.08] font-semibold">
            Ratio: --
          </div>
        </div>

        <!-- Segmented Bar -->
        <div id="source-split-bar" class="w-full h-3 rounded-full overflow-hidden flex bg-[#0c0e16] border border-white/[0.08]"></div>

        <!-- Source Badges Legend -->
        <div class="grid grid-cols-2 sm:grid-cols-4 gap-2.5 pt-1 text-xs">
          <div class="flex items-center gap-2 p-2 rounded-lg bg-[#0c0e16] border border-white/[0.08]">
            <span class="w-2.5 h-2.5 rounded-sm bg-[#38bdf8] shrink-0"></span>
            <div class="min-w-0">
              <div class="font-medium text-white text-xs">Browser</div>
              <div id="source-stat-browser" class="text-slate-400 font-mono text-[11px]">--</div>
            </div>
          </div>

          <div class="flex items-center gap-2 p-2 rounded-lg bg-[#0c0e16] border border-white/[0.08]">
            <span class="w-2.5 h-2.5 rounded-sm bg-[#a78bfa] shrink-0"></span>
            <div class="min-w-0">
              <div class="font-medium text-white text-xs">Mobile</div>
              <div id="source-stat-mobile" class="text-slate-400 font-mono text-[11px]">--</div>
            </div>
          </div>

          <div class="flex items-center gap-2 p-2 rounded-lg bg-[#0c0e16] border border-white/[0.08]">
            <span class="w-2.5 h-2.5 rounded-sm bg-[#34d399] shrink-0"></span>
            <div class="min-w-0">
              <div class="font-medium text-white text-xs">Desktop</div>
              <div id="source-stat-desktop" class="text-slate-400 font-mono text-[11px]">--</div>
            </div>
          </div>

          <div class="flex items-center gap-2 p-2 rounded-lg bg-[#0c0e16] border border-white/[0.08]">
            <span class="w-2.5 h-2.5 rounded-sm bg-[#fbbf24] shrink-0"></span>
            <div class="min-w-0">
              <div class="font-medium text-white text-xs">VS Code</div>
              <div id="source-stat-vscode" class="text-slate-400 font-mono text-[11px]">--</div>
            </div>
          </div>
        </div>
      </section>

      <!-- Hourly Activity Explorer & Inspector -->
      <section id="analytics-hourly-section" class="bg-[var(--card)] border border-[var(--border)] rounded-xl p-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.05)] space-y-4">
        <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-[var(--border)]">
          <div>
            <div class="flex items-center gap-2">
              <h2 class="text-sm font-semibold text-[var(--foreground)]">Hourly Activity Explorer</h2>
              <span id="hourly-summary-badge" class="text-xs font-mono text-slate-400"></span>
            </div>
            <p class="text-xs text-[var(--muted-foreground)] mt-0.5">Inspect active and idle rhythms, parallel PC/mobile timelines, and hourly session details</p>
          </div>

          <!-- Mode Toggle Controls -->
          <div class="flex items-center gap-2">
            <div class="inline-flex p-0.5 bg-[#0c0e16] rounded-lg border border-white/[0.08] text-xs font-medium" id="hourly-mode-toggle">
              <button id="btn-mode-inspector" onclick="setHourlyViewMode('inspector')" class="px-2.5 py-1 rounded-md bg-white/[0.08] text-white border border-white/[0.14] transition">Hour Inspector</button>
              <button id="btn-mode-duallane" onclick="setHourlyViewMode('duallane')" class="px-2.5 py-1 rounded-md text-slate-400 hover:text-white transition">Dual-Lane (PC vs Mobile)</button>
              <button id="btn-mode-schedule" onclick="setHourlyViewMode('schedule')" class="px-2.5 py-1 rounded-md text-slate-400 hover:text-white transition">24h Schedule</button>
            </div>
          </div>
        </div>

        <!-- 24-Hour Interactive Rhythm Bar Strip -->
        <div class="space-y-1.5">
          <div class="flex items-center justify-between text-[11px] text-slate-400 px-1">
            <span class="font-mono">Select an hour below to inspect:</span>
            <div class="flex items-center gap-3">
              <span class="inline-flex items-center gap-1.5"><span class="w-2 h-2 rounded-sm bg-[#38bdf8]"></span> Browser</span>
              <span class="inline-flex items-center gap-1.5"><span class="w-2 h-2 rounded-sm bg-[#a78bfa]"></span> Mobile</span>
              <span class="inline-flex items-center gap-1.5"><span class="w-2 h-2 rounded-sm bg-[#34d399]"></span> Desktop</span>
              <span class="inline-flex items-center gap-1.5"><span class="w-2 h-2 rounded-sm bg-[#fbbf24]"></span> VS Code</span>
            </div>
          </div>

          <div id="hourly-bars-container" class="h-44 flex items-end gap-1 sm:gap-1.5 pt-6 pb-2 bg-[#0c0e16] border border-white/[0.08] rounded-xl px-2 sm:px-3 overflow-x-auto custom-scroll">
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
        <div id="hourly-inspector-container" class="bg-[#0c0e16] border border-white/[0.08] rounded-xl p-4 space-y-3">
          <!-- Injected by renderHourlyInspector() -->
        </div>

        <!-- Dual-Lane Swimlane (PC vs Mobile) -->
        <div id="hourly-duallane-container" class="hidden bg-[#0c0e16] border border-white/[0.08] rounded-xl p-4 space-y-4">
          <!-- Injected by renderDualLaneSwimlane() -->
        </div>

        <!-- Chronological 24h Schedule Feed (Toggleable) -->
        <div id="hourly-schedule-container" class="hidden bg-[#0c0e16] border border-white/[0.08] rounded-xl p-4 space-y-2.5">
          <!-- Injected by renderHourlySchedule() -->
        </div>
      </section>

      <!-- Detailed Leaderboards & Focus Blocks Grid -->
      <section id="analytics-leaderboards-section" class="space-y-4">
        
        <!-- Row 1: Focus & Task Analytics (Cumulative by Title vs Discrete Longest Sessions) -->
        <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <!-- Card 1: Top Activities by Title (Combined Overall) -->
          <div class="bg-[var(--card)] border border-[var(--border)] rounded-xl p-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.05)] space-y-3 flex flex-col">
            <div class="flex items-center justify-between pb-1 border-b border-white/[0.05]">
              <div>
                <h2 class="text-sm font-semibold text-[var(--foreground)]">Top Activities by Title</h2>
                <p class="text-[11px] text-[var(--muted-foreground)]">Combined overall time across all sessions with the same title</p>
              </div>
              <span id="titles-count-badge" class="text-xs font-mono text-slate-500">Top 10</span>
            </div>
            <div id="combined-titles-list" class="space-y-2 flex-1 overflow-y-auto max-h-80 pr-1 custom-scroll">
              <!-- Populated by JS -->
            </div>
          </div>

          <!-- Card 2: Top Longest Focused Sessions -->
          <div class="bg-[var(--card)] border border-[var(--border)] rounded-xl p-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.05)] space-y-3 flex flex-col">
            <div class="flex items-center justify-between pb-1 border-b border-white/[0.05]">
              <div>
                <h2 class="text-sm font-semibold text-[var(--foreground)]">Longest Focus Sessions</h2>
                <p class="text-[11px] text-[var(--muted-foreground)]">Longest single uninterrupted focus sessions (screen activity only)</p>
              </div>
              <span id="longest-count-badge" class="text-xs font-mono text-slate-500">Top 5</span>
            </div>
            <div id="longest-sessions-list" class="space-y-2 flex-1 overflow-y-auto max-h-80 pr-1 custom-scroll">
              <!-- Populated by JS -->
            </div>
          </div>
        </div>

        <!-- Row 2: Platforms & Applications Breakdown -->
        <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          <!-- Domains Card -->
          <div class="bg-[var(--card)] border border-[var(--border)] rounded-xl p-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.05)] space-y-3 flex flex-col">
            <div class="flex items-center justify-between">
              <h2 class="text-sm font-semibold text-[var(--foreground)]">Websites</h2>
              <span id="domains-count-badge" class="text-xs font-mono text-slate-500">0 domains</span>
            </div>
            <div id="domains-list" class="space-y-2.5 flex-1 overflow-y-auto max-h-72 pr-1 custom-scroll">
              <!-- Populated by JS -->
            </div>
          </div>

          <!-- Desktop Applications Card -->
          <div class="bg-[var(--card)] border border-[var(--border)] rounded-xl p-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.05)] space-y-3 flex flex-col">
            <div class="flex items-center justify-between">
              <h2 class="text-sm font-semibold text-[var(--foreground)]">Desktop Apps</h2>
              <span id="desktop-count-badge" class="text-xs font-mono text-slate-500">0 apps</span>
            </div>
            <div id="desktop-apps-list" class="space-y-2.5 flex-1 overflow-y-auto max-h-72 pr-1 custom-scroll">
              <!-- Populated by JS -->
            </div>
          </div>

          <!-- Mobile Apps Card -->
          <div class="bg-[var(--card)] border border-[var(--border)] rounded-xl p-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.05)] space-y-3 flex flex-col">
            <div class="flex items-center justify-between">
              <h2 class="text-sm font-semibold text-[var(--foreground)]">Mobile Apps</h2>
              <span id="mobile-count-badge" class="text-xs font-mono text-slate-500">0 apps</span>
            </div>
            <div id="mobile-apps-list" class="space-y-2.5 flex-1 overflow-y-auto max-h-72 pr-1 custom-scroll">
              <!-- Populated by JS -->
            </div>
          </div>
        </div>

      </section>
    </div>

    <!-- ==================== VIEW 3: SESSIONS / TIMELINE ("What exactly did I do?") ==================== -->
    <div id="view-tab-sessions" class="hidden space-y-4">
      <!-- Unobserved Timeline Gaps & Quick Labeling -->
      <section id="unobserved-gaps-section" class="bg-[var(--card)] border border-[var(--border)] rounded-xl p-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.05)] space-y-3">
        <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-2 pb-2 border-b border-[var(--border)]">
          <div class="flex items-center gap-2">
            <h2 class="text-sm font-semibold text-[var(--foreground)] flex items-center gap-2">
              <span>Unobserved Timeline Gaps</span>
              <span id="unobserved-gaps-count-badge" class="px-2 py-0.5 rounded text-[11px] font-mono bg-orange-500/10 text-[#fb923c] border border-orange-500/20 font-medium">0 Gaps</span>
            </h2>
          </div>
          <div class="flex items-center gap-2">
            <p class="text-xs text-[var(--muted-foreground)]">Unobserved periods (&ge; 10m) without screen activity.</p>
            <button onclick="openLabelGapModal()" class="px-2.5 py-1 rounded-md text-xs font-semibold bg-[#f97316]/15 hover:bg-[#f97316]/25 text-[#fb923c] border border-[#f97316]/30 transition flex items-center gap-1">
              <span>+ Manual Label</span>
            </button>
          </div>
        </div>
        <div id="unobserved-gaps-list" class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2.5">
          <!-- Injected dynamically by JS -->
        </div>
      </section>

      <section id="analytics-ledger-section" class="bg-[var(--card)] border border-[var(--border)] rounded-xl p-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.05)] space-y-3">
        <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-2 border-b border-[var(--border)]">
          <div>
            <div class="flex items-center gap-2">
              <h2 class="text-sm font-semibold text-[var(--foreground)]">Session Ledger & Timeline</h2>
              <div id="ledger-hour-filter-pill" class="hidden inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded text-xs font-mono bg-indigo-500/10 text-indigo-300 border border-indigo-500/20 font-medium"></div>
            </div>
            <p class="text-xs text-[var(--muted-foreground)] mt-0.5">Chronological log of discrete focus sessions (&ge; 40s duration)</p>
          </div>

          <!-- Filter tabs & Search -->
          <div class="flex flex-wrap items-center gap-2">
            <div id="timeline-filters" class="inline-flex p-0.5 bg-[#0c0e16] rounded-lg border border-white/[0.08] text-xs font-medium">
              <button data-filter="all" class="filter-btn px-2.5 py-1 rounded-md bg-white/[0.08] text-white border border-white/[0.14] transition text-xs font-medium">All</button>
              <button data-filter="browser" class="filter-btn px-2.5 py-1 rounded-md text-slate-400 hover:text-white transition text-xs">Browser</button>
              <button data-filter="mobile" class="filter-btn px-2.5 py-1 rounded-md text-slate-400 hover:text-white transition text-xs">Mobile</button>
              <button data-filter="desktop" class="filter-btn px-2.5 py-1 rounded-md text-slate-400 hover:text-white transition text-xs">Desktop</button>
              <button data-filter="vscode" class="filter-btn px-2.5 py-1 rounded-md text-slate-400 hover:text-white transition text-xs">VS Code</button>
              <button data-filter="manual" class="filter-btn px-2.5 py-1 rounded-md text-slate-400 hover:text-white transition text-xs">Offline</button>
            </div>

            <div class="relative">
              <input type="text" id="timeline-search" placeholder="Search sessions..." class="bg-[#0c0e16] border border-white/[0.1] rounded-lg px-2.5 py-1 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-indigo-400/60 w-36 sm:w-56 font-mono transition">
            </div>

            <span id="ledger-session-counter" class="text-xs font-mono text-slate-400 hidden sm:inline-block"></span>
          </div>
        </div>

        <!-- Ledger Container -->
        <div class="overflow-hidden border border-white/[0.08] rounded-lg bg-[#0c0e16]">
          <div class="max-h-[520px] overflow-y-auto custom-scroll divide-y divide-white/[0.04]" id="timeline-table-body">
            <!-- Session rows injected by JS -->
          </div>
        </div>
      </section>
    </div>

    <!-- ==================== VIEW 4: JOURNAL / ANALYSIS ("What does today's activity mean?") ==================== -->
    <div id="view-tab-journal" class="hidden space-y-4">
      <section id="journal-section" class="bg-[var(--card)] border border-[var(--border)] rounded-xl p-4 shadow-sm space-y-3">
        <div class="flex flex-col sm:flex-row sm:items-center justify-between pb-2.5 border-b border-[var(--border)] gap-2">
          <div class="flex items-center gap-2.5">
            <div class="w-7 h-7 rounded-md bg-[#141414] border border-[#222222] flex items-center justify-center text-neutral-400">
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253"></path></svg>
            </div>
            <div>
              <h2 class="text-sm font-semibold text-[var(--foreground)]" id="journal-heading">Daily Behavioral Analysis & Executive Journal</h2>
              <span class="text-xs text-neutral-500 font-mono" id="journal-filepath">Record/analysis/...</span>
            </div>
          </div>

          <div class="flex items-center gap-2">
            <span class="text-xs text-neutral-400 font-mono px-2.5 py-1 rounded bg-[#121212] border border-[#222222]" id="journal-date-tag">Date: --</span>
            <button onclick="copyJournalMarkdown()" class="px-2.5 py-1 rounded-md text-xs font-mono bg-[#141414] hover:bg-[#1f1f1f] text-neutral-300 border border-[var(--border)] transition flex items-center gap-1.5" title="Copy raw Markdown journal">
              <svg class="w-3.5 h-3.5 text-neutral-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 5H6a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2v-1M8 5a2 2 0 002 2h2a2 2 0 002-2M8 5a2 2 0 012-2h2a2 2 0 012 2m0 0h2a2 2 0 012 2v3m2 4H10m0 0l3-3m-3 3l3 3"></path></svg>
              Copy
            </button>
          </div>
        </div>

        <!-- Rendered Markdown Body -->
        <div id="journal-content-container" class="markdown-body max-w-none pt-1">
          <!-- Rendered markdown goes here -->
        </div>
      </section>
    </div>

  </div>

  <!-- Label Offline Period Modal -->
  <div id="label-offline-modal" class="fixed inset-0 bg-black/75 backdrop-blur-sm z-50 hidden items-center justify-center p-4">
    <div class="bg-[#11141e] border border-white/[0.12] rounded-2xl max-w-md w-full p-5 shadow-2xl space-y-4">
      <div class="flex items-center justify-between pb-3 border-b border-white/[0.08]">
        <div class="flex items-center gap-2">
          <span class="text-base font-semibold text-white">Label Offline Period</span>
          <span id="modal-gap-duration-pill" class="px-2 py-0.5 rounded text-xs font-mono bg-[#f97316]/15 text-[#fb923c] border border-[#f97316]/30 font-medium"></span>
        </div>
        <button onclick="closeLabelGapModal()" class="text-slate-400 hover:text-white p-1 rounded-lg hover:bg-white/[0.06] transition text-sm">✕</button>
      </div>

      <!-- Hidden inputs for date and times (read-only fixed period) -->
      <input type="hidden" id="modal-gap-date">
      <input type="hidden" id="modal-gap-start">
      <input type="hidden" id="modal-gap-end">

      <!-- Read-only timeline period banner -->
      <div class="p-2.5 rounded-lg bg-[#090a0f] border border-white/[0.08] flex items-center justify-between font-mono text-xs">
        <div>
          <span class="text-slate-400 text-[11px]">Period:</span>
          <span id="modal-gap-time-display" class="font-bold text-[#fb923c] ml-1.5">--</span>
        </div>
        <div class="text-slate-400 text-[11px]">
          <span id="modal-gap-date-display" class="text-slate-300">--</span>
        </div>
      </div>

      <div class="space-y-3.5 text-xs">
        <!-- Preset Activity Options (Multi-select) -->
        <div>
          <div class="flex items-center justify-between mb-1.5">
            <label class="text-slate-400 font-mono text-[10px] uppercase tracking-wider">Activity Options (Select One or More)</label>
            <button type="button" onclick="clearSelectedPresets()" class="text-[10px] text-slate-500 hover:text-slate-300 font-mono">Clear</button>
          </div>
          <div id="modal-preset-container" class="flex flex-wrap gap-1.5">
            <!-- Buttons injected & managed by JS: Afternoon nap, Sleep, Dinner, Snacks, Lunch, Walk, Discussion -->
          </div>
        </div>

        <!-- Activity Label / Manual Label -->
        <div>
          <label class="block text-slate-400 font-mono text-[11px] mb-1">Activity Label / Manual Label</label>
          <input type="text" id="modal-gap-activity" placeholder="Select options above or type custom label..." class="w-full bg-[#090a0f] border border-white/[0.1] rounded-lg px-3 py-2 text-white font-medium focus:outline-none focus:border-[#f97316]">
        </div>

        <!-- Notes (Optional) -->
        <div>
          <label class="block text-slate-400 font-mono text-[11px] mb-1">Notes (Optional)</label>
          <input type="text" id="modal-gap-notes" placeholder="e.g. Offline details, context..." class="w-full bg-[#090a0f] border border-white/[0.1] rounded-lg px-3 py-2 text-white text-xs focus:outline-none focus:border-[#f97316]">
        </div>

        <div id="modal-gap-status" class="hidden text-xs py-1"></div>
      </div>

      <div class="flex items-center justify-end gap-2.5 pt-3 border-t border-white/[0.08]">
        <button type="button" onclick="closeLabelGapModal()" class="px-3.5 py-1.5 rounded-lg text-xs font-medium text-slate-400 hover:text-white hover:bg-white/[0.06] transition">Cancel</button>
        <button type="button" id="btn-submit-gap-label" onclick="submitLabelGapModal()" class="px-4 py-1.5 rounded-lg text-xs font-semibold bg-[#f97316] hover:bg-[#ea580c] text-white shadow-lg shadow-[#f97316]/20 transition flex items-center gap-1.5">
          <span id="btn-submit-gap-text">Save & Update</span>
        </button>
      </div>
    </div>
  </div>

  <!-- Embedded Data & Client Controller -->
  <script>
    const REPORTS_DATABASE = {reports_json};
    const ANALYSES_DATABASE = {analyses_json};
    const ANALYSES_HTML_DATABASE = {analyses_html_json};
    const COLLECTOR_AUTH_TOKEN = {auth_token_json};

    function getCollectorHeaders() {{
      const headers = {{ "Content-Type": "application/json" }};
      const token = localStorage.getItem("activity_tracker_token") || COLLECTOR_AUTH_TOKEN || "";
      if (token) {{
        headers["Authorization"] = "Bearer " + token;
      }}
      return headers;
    }}

    let currentDate = "{initial_date}";
    let currentFilter = "all";
    let searchQuery = "";
    let activeMainTab = "overview"; // 'overview', 'analytics', 'sessions', 'journal'
    let selectedHour = null;
    let hourlyViewMode = "inspector"; // 'inspector' or 'schedule'
    let activeHourFilter = null;
    let expandedScheduleHour = null;

    function persistDashboardState() {{
      try {{
        sessionStorage.setItem("dashboard_active_date", currentDate);
        sessionStorage.setItem("dashboard_active_tab", activeMainTab);
      }} catch (e) {{}}
      if (window.history && window.history.replaceState) {{
        window.history.replaceState(null, "", `#date=${{encodeURIComponent(currentDate)}}&tab=${{encodeURIComponent(activeMainTab)}}`);
      }}
    }}

    function formatFriendlyDate(dateStr) {{
      if (!dateStr) return "--";
      const parts = dateStr.split("-");
      if (parts.length === 3) {{
        const dObj = new Date(parseInt(parts[0], 10), parseInt(parts[1], 10) - 1, parseInt(parts[2], 10));
        const dayNames = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
        const mNames = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
        return `${{dayNames[dObj.getDay()]}}, ${{mNames[dObj.getMonth()]}} ${{dObj.getDate()}}, ${{dObj.getFullYear()}}`;
      }}
      return dateStr;
    }}

    function getAllDatesList() {{
      const localToday = new Date().toLocaleDateString('en-CA');
      const allDatesSet = new Set([...Object.keys(REPORTS_DATABASE), ...Object.keys(ANALYSES_DATABASE), localToday]);
      return Array.from(allDatesSet).sort();
    }}

    function onDateChange(newDate) {{
      currentDate = newDate;
      activeHourFilter = null;
      selectedHour = null;
      expandedScheduleHour = null;
      renderAll();
      initDateButtons();
      renderCalendarHeatmap();
      persistDashboardState();
    }}

    function selectPreviousDate() {{
      const dates = getAllDatesList();
      const idx = dates.indexOf(currentDate);
      if (idx > 0) {{
        onDateChange(dates[idx - 1]);
      }} else {{
        showToast("Already at earliest recorded day");
      }}
    }}

    function selectNextDate() {{
      const dates = getAllDatesList();
      const idx = dates.indexOf(currentDate);
      if (idx >= 0 && idx < dates.length - 1) {{
        onDateChange(dates[idx + 1]);
      }} else {{
        showToast("Already at latest recorded day");
      }}
    }}

    function formatSecs(secs) {{
      const s = Math.round(secs);
      const h = Math.floor(s / 3600);
      const m = Math.floor((s % 3600) / 60);
      const r = s % 60;
      if (h > 0) return `${{h}}h ${{m}}m`;
      if (m > 0) return `${{m}}m ${{r}}s`;
      return `${{r}}s`;
    }}

    function formatTimeOfDay(totalSec) {{
      const h = Math.floor(totalSec / 3600) % 24;
      const m = Math.floor((totalSec % 3600) / 60);
      const s = Math.floor(totalSec % 60);
      return `${{String(h).padStart(2, "0")}}:${{String(m).padStart(2, "0")}}:${{String(s).padStart(2, "0")}}`;
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
      t = t.replace(/\\*(.+?)\\*/g, '<em class="italic text-neutral-300">$1</em>');
      // Inline code
      t = t.replace(/`([^`]+)`/g, '<code class="bg-[#121212] text-neutral-200 px-1.5 py-0.5 rounded text-[11px] font-mono border border-[#222222]">$1</code>');
      // Links
      t = t.replace(/\\[([^\\]]+)\\]\\(([^\\)]+)\\)/g, '<a href="$2" target="_blank" class="text-neutral-300 hover:text-white underline decoration-neutral-600 underline-offset-2">$1</a>');
      return t;
    }}

    function renderMarkdown(md) {{
      if (!md || !md.trim()) {{
        const parts = currentDate.split("-");
        const yr = parts[0] || "2026";
        const mNames = ["jan","feb","mar","apr","may","jun","jul","aug","sep","oct","nov","dec"];
        const mmm = (parts[1] && parseInt(parts[1]) > 0 && parseInt(parts[1]) <= 12) ? mNames[parseInt(parts[1]) - 1] : "sep";
        return `
          <div class="py-12 text-center bg-[#07090e] border border-dashed border-white/[0.08] rounded-xl space-y-2">
            <div class="text-sm font-medium text-slate-300">No journal entry for ${{currentDate}}</div>
            <p class="text-xs text-slate-500 font-mono">
              Record/analysis/${{yr}}/${{mmm}}/daily/${{currentDate}}.md
            </p>
          </div>
        `;
      }}

      // 1. If marked.js is available from CDN/bundle, use it (full GitHub Flavored Markdown)
      if (typeof marked !== "undefined" && typeof marked.parse === "function") {{
        try {{
          return marked.parse(md, {{ gfm: true, breaks: false }});
        }} catch (err) {{
          console.warn("marked.parse error, falling back to pre-rendered HTML:", err);
        }}
      }}

      // 2. If pre-rendered HTML is available in database
      if (typeof ANALYSES_HTML_DATABASE !== "undefined" && ANALYSES_HTML_DATABASE[currentDate]) {{
        return ANALYSES_HTML_DATABASE[currentDate];
      }}

      // 3. Robust client-side fallback parser supporting tables, lists, blockquotes, code
      const lines = md.split('\\n');
      let html = [];
      let inList = false;
      let listType = null;
      let inCode = false;
      let codeBuffer = [];
      let inTable = false;
      let tableRows = [];

      function flushList() {{
        if (inList) {{
          html.push(listType === 'ol' ? '</ol>' : '</ul>');
          inList = false;
          listType = null;
        }}
      }}

      function flushTable() {{
        if (inTable) {{
          if (tableRows.length > 0) {{
            let tHtml = ['<table>'];
            let hasHeader = tableRows.length > 1 && tableRows[1].every(c => c.trim().match(/^:?-+:?$/));
            let startRow = 0;
            if (hasHeader) {{
              tHtml.push('<thead><tr>');
              tableRows[0].forEach(cell => {{
                tHtml.push('<th>' + inlineFormat(cell.trim()) + '</th>');
              }});
              tHtml.push('</tr></thead>');
              startRow = 2;
            }}
            tHtml.push('<tbody>');
            for (let r = startRow; r < tableRows.length; r++) {{
              tHtml.push('<tr>');
              tableRows[r].forEach(cell => {{
                tHtml.push('<td>' + inlineFormat(cell.trim()) + '</td>');
              }});
              tHtml.push('</tr>');
            }}
            tHtml.push('</tbody></table>');
            html.push(tHtml.join(''));
          }}
          inTable = false;
          tableRows = [];
        }}
      }}

      for (let i = 0; i < lines.length; i++) {{
        let line = lines[i];

        if (line.trim().startsWith('```')) {{
          flushList();
          flushTable();
          if (inCode) {{
            html.push('<pre><code>' + escapeHtml(codeBuffer.join('\\n')) + '</code></pre>');
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

        // Table row handling
        if (line.trim().startsWith('|') && line.trim().endsWith('|')) {{
          flushList();
          inTable = true;
          let cells = line.trim().slice(1, -1).split('|');
          tableRows.push(cells);
          continue;
        }} else if (inTable) {{
          flushTable();
        }}

        if (line.trim() === '---' || line.trim() === '***') {{
          flushList();
          html.push('<hr>');
          continue;
        }}

        if (line.startsWith('# ')) {{
          flushList();
          html.push('<h1>' + inlineFormat(line.slice(2)) + '</h1>');
          continue;
        }}
        if (line.startsWith('## ')) {{
          flushList();
          html.push('<h2>' + inlineFormat(line.slice(3)) + '</h2>');
          continue;
        }}
        if (line.startsWith('### ')) {{
          flushList();
          html.push('<h3>' + inlineFormat(line.slice(4)) + '</h3>');
          continue;
        }}

        if (line.startsWith('> ')) {{
          flushList();
          html.push('<blockquote>' + inlineFormat(line.slice(2)) + '</blockquote>');
          continue;
        }}

        const olMatch = line.trim().match(/^(\\d+)\\.\\s+(.*)/);
        if (olMatch) {{
          if (!inList || listType !== 'ol') {{
            flushList();
            html.push('<ol>');
            inList = true;
            listType = 'ol';
          }}
          html.push('<li>' + inlineFormat(olMatch[2]) + '</li>');
          continue;
        }}

        if (line.trim().startsWith('- ') || line.trim().startsWith('* ')) {{
          if (!inList || listType !== 'ul') {{
            flushList();
            html.push('<ul>');
            inList = true;
            listType = 'ul';
          }}
          html.push('<li>' + inlineFormat(line.trim().slice(2)) + '</li>');
          continue;
        }}

        flushList();

        if (!line.trim()) continue;

        html.push('<p>' + inlineFormat(line) + '</p>');
      }}

      flushList();
      flushTable();
      return html.join('');
    }}

    function renderCalendarHeatmap() {{
      const localToday = new Date().toLocaleDateString('en-CA');
      const allDates = Object.keys(REPORTS_DATABASE).concat(Object.keys(ANALYSES_DATABASE)).concat([localToday]);
      let maxDateStr = localToday;
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
          mLabel.className = "absolute font-semibold text-neutral-400";
          mLabel.style.left = `${{w * 15}}px`;
          mLabel.textContent = mNames[m];
          monthsContainer.appendChild(mLabel);
        }}

        for (let d = 0; d < 7; d++) {{
          const cur = new Date(startSunday.getTime() + (w * 7 + d) * 86400000);
          const dateStr = cur.toISOString().split("T")[0];
          const isFuture = cur.getTime() > (new Date(maxDateStr + "T23:59:59Z")).getTime();

          const rep = REPORTS_DATABASE[dateStr];
          const secs = rep?.summary?.total_active_seconds || 0;
          const hasMd = !!ANALYSES_DATABASE[dateStr];
          const sessionCount = rep?.summary?.session_count || 0;

          const block = document.createElement("button");
          block.type = "button";
          block.dataset.date = dateStr;

          // Luminous Linear emerald ramp
          let lvlClass = "bg-[#131620] border-white/[0.05]";
          if (secs > 0) {{
            if (secs < 7200) {{
              lvlClass = "bg-[#0f2e24] border-[#18493a]";
            }} else if (secs < 14400) {{
              lvlClass = "bg-[#144738] border-[#1f6b54]";
            }} else if (secs < 21600) {{
              lvlClass = "bg-[#1a664f] border-[#299171]";
            }} else {{
              lvlClass = "bg-[#228e6c] border-[#34d399]";
            }}
          }}

          let baseClass = `w-3 h-3 rounded-[2.5px] border transition-all duration-100 relative ${{lvlClass}}`;
          if (isFuture) {{
            baseClass += " opacity-20 pointer-events-none";
          }} else {{
            baseClass += " hover:scale-125 hover:z-20 cursor-pointer";
          }}

          if (dateStr === currentDate) {{
            baseClass += " ring-1 ring-white/80 ring-offset-1 ring-offset-[#090a0f] scale-110 z-20 shadow-[0_0_8px_rgba(255,255,255,0.25)]";
          }}

          block.className = baseClass;

          if (hasMd) {{
            block.innerHTML = '<span class="absolute -top-0.5 -right-0.5 w-1 h-1 rounded-full bg-[#34d399] pointer-events-none shadow-[0_0_4px_rgba(52,211,153,0.6)]"></span>';
          }}

          const friendlyDay = `${{dayNames[cur.getUTCDay()]}}, ${{mNames[cur.getUTCMonth()]}} ${{cur.getUTCDate()}}, ${{cur.getUTCFullYear()}}`;
          const activeText = secs > 0 ? `${{formatSecs(secs)}} active (${{sessionCount}} sessions)` : "No active sessions";
          const mdText = hasMd ? " • note" : "";
          block.title = `${{friendlyDay}}: ${{activeText}}${{mdText}}`;

          block.onmouseenter = () => {{
            const infoBox = document.getElementById("calendar-hover-info");
            if (infoBox) {{
              infoBox.innerHTML = `
                <span class="text-neutral-200 font-medium">${{friendlyDay}}</span> &bull; 
                <span class="${{secs > 0 ? 'text-neutral-200 font-medium' : 'text-neutral-500'}}">${{secs > 0 ? formatSecs(secs) : 'No activity'}}</span>
                ${{sessionCount > 0 ? `<span class="text-neutral-500"> (${{sessionCount}} sessions)</span>` : ''}}
                ${{hasMd ? `<span class="text-neutral-400 font-mono text-[10px]"> • note</span>` : ''}}
              `;
            }}
          }};

          block.onmouseleave = () => {{
            updateCalendarSelectedInfo();
          }};

          block.onclick = () => {{
            onDateChange(dateStr);
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
      const friendlyDate = formatFriendlyDate(currentDate);

      const infoBox = document.getElementById("calendar-hover-info");
      if (infoBox) {{
        infoBox.innerHTML = `
          <span class="text-neutral-500">Selected:</span> 
          <strong class="text-neutral-200">${{friendlyDate}}</strong> &bull; 
          <span class="${{secs > 0 ? 'text-neutral-200 font-medium' : 'text-neutral-500'}}">${{secs > 0 ? formatSecs(secs) : 'No activity recorded'}}</span>
          ${{hasMd ? `<span class="text-neutral-400 font-mono text-[10px]"> • note</span>` : ''}}
        `;
      }}
    }}

    function initDateButtons() {{
      const container = document.getElementById("date-buttons-container");
      if (!container) return;
      container.innerHTML = "";
      
      const localToday = new Date().toLocaleDateString('en-CA');
      const allDatesSet = new Set([...Object.keys(REPORTS_DATABASE), ...Object.keys(ANALYSES_DATABASE), localToday]);
      const dates = Array.from(allDatesSet).sort().reverse();
      
      dates.forEach(d => {{
        const btn = document.createElement("button");
        const isActive = d === currentDate;
        const hasReport = !!REPORTS_DATABASE[d];
        const hasMd = !!ANALYSES_DATABASE[d];
        const isToday = d === localToday;

        let extraDot = hasMd ? ' <span class="inline-block w-1.5 h-1.5 rounded-full bg-[#34d399] mb-0.5"></span>' : '';
        let todayBadge = isToday ? ' <span class="text-[9px] uppercase px-1 py-0.2 rounded bg-indigo-500/10 text-indigo-300 font-sans font-bold border border-indigo-500/20">Today</span>' : '';

        btn.className = `px-2.5 py-1 rounded-md transition text-xs font-mono ${{isActive ? 'bg-white/[0.08] text-white font-medium border border-white/[0.14]' : 'text-slate-400 hover:text-white hover:bg-white/[0.04]'}}`;
        btn.innerHTML = `${{d}}${{todayBadge}}${{extraDot}}`;
        btn.onclick = () => {{
          onDateChange(d);
        }};
        container.appendChild(btn);
      }});
    }}

    function setActiveTab(tab) {{
      const tabs = ["overview", "analytics", "sessions", "journal"];
      if (!tabs.includes(tab)) tab = "overview";
      activeMainTab = tab;

      tabs.forEach(t => {{
        const btn = document.getElementById(`tab-btn-${{t}}`);
        const view = document.getElementById(`view-tab-${{t}}`);
        if (btn) {{
          if (t === activeMainTab) {{
            btn.className = "tab-btn px-3.5 py-1.5 rounded-lg bg-white/[0.08] text-white font-medium border border-white/[0.14] shadow-sm transition flex items-center gap-2 text-xs";
          }} else {{
            btn.className = "tab-btn px-3.5 py-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-white/[0.04] border border-transparent transition flex items-center gap-2 text-xs";
          }}
        }}
        if (view) {{
          if (t === activeMainTab) {{
            view.classList.remove("hidden");
          }} else {{
            view.classList.add("hidden");
          }}
        }}
      }});
      persistDashboardState();
    }}

    function updateViewModeVisibility() {{
      setActiveTab(activeMainTab);
    }}

    function copyJournalMarkdown() {{
      const md = ANALYSES_DATABASE[currentDate] || "";
      if (!md || !md.trim()) {{
        showToast("No journal text to copy for this date", true);
        return;
      }}
      if (navigator.clipboard && navigator.clipboard.writeText) {{
        navigator.clipboard.writeText(md).then(() => {{
          showToast("Journal markdown copied to clipboard!");
        }}).catch(() => {{
          showToast("Failed to copy to clipboard", true);
        }});
      }} else {{
        showToast("Clipboard access not supported in this browser", true);
      }}
    }}

    function renderOverviewSummary(rep, mdContent) {{
      const sum = rep?.summary || {{}};
      const sources = rep?.sources || {{}};
      const totalSec = sum.total_active_seconds || 0;

      // 1. Executive AI Summary Preview
      const previewContainer = document.getElementById("overview-journal-preview");
      const metaSpan = document.getElementById("overview-journal-meta");
      const parts = currentDate.split("-");
      const yr = parts[0] || "2026";
      const mNames = ["jan","feb","mar","apr","may","jun","jul","aug","sep","oct","nov","dec"];
      const mmm = (parts[1] && parseInt(parts[1]) > 0 && parseInt(parts[1]) <= 12) ? mNames[parseInt(parts[1]) - 1] : "sep";
      if (metaSpan) {{
        metaSpan.textContent = `Record/analysis/${{yr}}/${{mmm}}/daily/${{currentDate}}.md`;
      }}

      if (previewContainer) {{
        if (mdContent && mdContent.trim()) {{
          previewContainer.innerHTML = renderMarkdown(mdContent);
        }} else {{
          previewContainer.innerHTML = `
            <div class="py-10 text-center bg-[#050505] border border-dashed border-[#1f1f1f] rounded-xl space-y-2">
              <div class="text-xs font-medium text-neutral-300">No AI journal note generated for ${{currentDate}}</div>
              <p class="text-[11px] text-neutral-500 font-mono max-w-sm mx-auto">
                Generate an agent analysis or review recorded sessions in Analytics and Sessions views.
              </p>
            </div>
          `;
        }}
      }}

      // 2. Day at a Glance: Device Distribution Mini-Bar
      const bSec = sources.browser?.duration_seconds || 0;
      const mSec = sources.mobile?.duration_seconds || 0;
      const dSec = sources.desktop?.duration_seconds || 0;
      const vSec = sources.vscode?.duration_seconds || 0;

      const bPct = totalSec > 0 ? (bSec / totalSec) * 100 : 0;
      const mPct = totalSec > 0 ? (mSec / totalSec) * 100 : 0;
      const dPct = totalSec > 0 ? (dSec / totalSec) * 100 : 0;
      const vPct = totalSec > 0 ? (vSec / totalSec) * 100 : 0;

      const pcTotal = bSec + dSec + vSec;
      const pcPct = totalSec > 0 ? Math.round((pcTotal / totalSec) * 100) : 0;
      const devRatio = document.getElementById("overview-device-ratio");
      if (devRatio) {{
        devRatio.textContent = `PC: ${{pcPct}}% | Mobile: ${{100 - pcPct}}%`;
      }}

      const barContainer = document.getElementById("overview-source-split-bar");
      if (barContainer) {{
        barContainer.innerHTML = `
          <div class="bg-[#38bdf8] h-full transition-all duration-500" style="width: ${{bPct}}%" title="Browser: ${{formatSecs(bSec)}} (${{bPct.toFixed(1)}}%)"></div>
          <div class="bg-[#a78bfa] h-full transition-all duration-500" style="width: ${{mPct}}%" title="Mobile: ${{formatSecs(mSec)}} (${{mPct.toFixed(1)}}%)"></div>
          <div class="bg-[#34d399] h-full transition-all duration-500" style="width: ${{dPct}}%" title="Desktop: ${{formatSecs(dSec)}} (${{dPct.toFixed(1)}}%)"></div>
          <div class="bg-[#fbbf24] h-full transition-all duration-500" style="width: ${{vPct}}%" title="VS Code: ${{formatSecs(vSec)}} (${{vPct.toFixed(1)}}%)"></div>
        `;
      }}

      const statB = document.getElementById("overview-stat-browser");
      if (statB) statB.textContent = `${{formatSecs(bSec)}}`;
      const statM = document.getElementById("overview-stat-mobile");
      if (statM) statM.textContent = `${{formatSecs(mSec)}}`;
      const statD = document.getElementById("overview-stat-desktop");
      if (statD) statD.textContent = `${{formatSecs(dSec)}}`;
      const statV = document.getElementById("overview-stat-vscode");
      if (statV) statV.textContent = `${{formatSecs(vSec)}}`;

      // 3. Top 3 Focus Sessions
      const topSessionsContainer = document.getElementById("overview-top-sessions");
      if (topSessionsContainer) {{
        topSessionsContainer.innerHTML = "";
        const longest = (rep.longest_sessions || []).filter(s => s.source !== "manual").slice(0, 3);
        if (longest.length === 0) {{
          topSessionsContainer.innerHTML = '<div class="text-xs text-slate-500 py-2">No active sessions recorded today.</div>';
        }} else {{
          longest.forEach((sess, idx) => {{
            const title = sess.context?.activity || sess.context?.title || sess.context?.app || sess.context?.domain || sess.source;
            const sub = sess.context?.category || sess.context?.domain || sess.context?.package || sess.context?.file || "";
            let badge = "bg-[#38bdf8]/10 text-[#7dd3fc] border border-[#38bdf8]/20";
            if (sess.source === "mobile") badge = "bg-[#a78bfa]/10 text-[#c4b5fd] border border-[#a78bfa]/20";
            else if (sess.source === "desktop") badge = "bg-[#34d399]/10 text-[#6ee7b7] border border-[#34d399]/20";
            else if (sess.source === "vscode") badge = "bg-[#fbbf24]/10 text-[#fde047] border border-[#fbbf24]/20";

            const row = document.createElement("div");
            row.className = "flex items-center justify-between gap-2 p-2 rounded-lg bg-[#0e111a] border border-white/[0.06] hover:bg-[#141824] transition text-xs";
            row.innerHTML = `
              <div class="flex items-center gap-2 min-w-0">
                <span class="font-mono text-slate-500 font-bold w-3 shrink-0">${{idx + 1}}.</span>
                <span class="px-1.5 py-0.2 rounded text-[10px] font-mono uppercase font-semibold border shrink-0 ${{badge}}">${{sess.source}}</span>
                <div class="min-w-0">
                  <div class="font-medium text-white truncate max-w-[160px] sm:max-w-xs" title="${{escapeHtml(title)}}">${{escapeHtml(title)}}</div>
                  ${{sub ? `<div class="text-[10px] text-slate-500 font-mono truncate max-w-[160px] sm:max-w-xs">${{escapeHtml(sub)}}</div>` : ''}}
                </div>
              </div>
              <span class="font-mono font-semibold text-white bg-white/[0.05] px-2 py-0.5 rounded border border-white/[0.08] shrink-0">${{formatSecs(sess.duration_seconds)}}</span>
            `;
            topSessionsContainer.appendChild(row);
          }});
        }}
      }}

      // 4. Rhythm Highlight
      const rhythmEl = document.getElementById("overview-rhythm-highlight");
      if (rhythmEl) {{
        const spanSec = sum.observed_span_seconds || 0;
        const sTime = parseTimeOnly(sum.start_time);
        const eTime = parseTimeOnly(sum.end_time);
        if (spanSec > 0 && sTime !== "--:--") {{
          rhythmEl.innerHTML = `Span: <strong class="text-neutral-300 font-mono">${{sTime}} &ndash; ${{eTime}}</strong> (${{formatSecs(spanSec)}})`;
        }} else {{
          rhythmEl.textContent = `Span: No recorded active span`;
        }}
      }}
    }}

    function renderAll() {{
      const rep = REPORTS_DATABASE[currentDate] || {{}};
      const mdContent = ANALYSES_DATABASE[currentDate] || "";
      const sum = rep.summary || {{}};
      const sources = rep.sources || {{}};
      
      // Header active date display
      const headerDate = document.getElementById("header-active-date");
      if (headerDate) {{
        headerDate.innerHTML = `<span class="text-neutral-200 font-medium">${{formatFriendlyDate(currentDate)}}</span> <span class="text-neutral-500 font-normal">(${{currentDate}})</span>`;
      }}

      // Analysis status badge in nav
      const badge = document.getElementById("has-analysis-badge");
      if (badge) {{
        if (mdContent.trim()) {{
          badge.classList.remove("hidden");
        }} else {{
          badge.classList.add("hidden");
        }}
      }}

      // Nav session count badge & journal dot
      const timelineLen = (rep.timeline || []).length;
      const navSessionBadge = document.getElementById("nav-session-count-badge");
      if (navSessionBadge) navSessionBadge.textContent = timelineLen;

      const navJournalDot = document.getElementById("nav-journal-dot");
      if (navJournalDot) {{
        if (mdContent && mdContent.trim()) {{
          navJournalDot.classList.remove("hidden");
        }} else {{
          navJournalDot.classList.add("hidden");
        }}
      }}

      const ledgerCounter = document.getElementById("ledger-session-counter");
      if (ledgerCounter) ledgerCounter.textContent = `${{timelineLen}} sessions logged`;

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
        `<span>Observed: <strong class="text-neutral-200">${{spanFormatted}}</strong> (${{pctActive}}% active)</span>` : 
        `<span>No active session data</span>`;


      // Longest session
      // Longest session (screen activity only)
      const longest = (rep.longest_sessions || []).find(s => s.source !== "manual") || null;
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
        <div class="bg-[#38bdf8] h-full transition-all duration-500" style="width: ${{bPct}}%" title="Browser: ${{formatSecs(bSec)}} (${{bPct.toFixed(1)}}%)"></div>
        <div class="bg-[#a78bfa] h-full transition-all duration-500" style="width: ${{mPct}}%" title="Mobile: ${{formatSecs(mSec)}} (${{mPct.toFixed(1)}}%)"></div>
        <div class="bg-[#34d399] h-full transition-all duration-500" style="width: ${{dPct}}%" title="Desktop: ${{formatSecs(dSec)}} (${{dPct.toFixed(1)}}%)"></div>
        <div class="bg-[#fbbf24] h-full transition-all duration-500" style="width: ${{vPct}}%" title="VS Code: ${{formatSecs(vSec)}} (${{vPct.toFixed(1)}}%)"></div>
      `;

      document.getElementById("source-stat-browser").textContent = `${{formatSecs(bSec)}} (${{bPct.toFixed(1)}}%) &bull; ${{sources.browser?.session_count || 0}} sess`;
      document.getElementById("source-stat-mobile").textContent = `${{formatSecs(mSec)}} (${{mPct.toFixed(1)}}%) &bull; ${{sources.mobile?.session_count || 0}} sess`;
      document.getElementById("source-stat-desktop").textContent = `${{formatSecs(dSec)}} (${{dPct.toFixed(1)}}%) &bull; ${{sources.desktop?.session_count || 0}} sess`;
      document.getElementById("source-stat-vscode").textContent = `${{formatSecs(vSec)}} (${{vPct.toFixed(1)}}%) &bull; ${{sources.vscode?.session_count || 0}} sess`;

      const pcTotal = bSec + dSec + vSec;
      const pcPct = totalSec > 0 ? Math.round((pcTotal / totalSec) * 100) : 0;
      document.getElementById("device-ratio-badge").textContent = `PC: ${{pcPct}}% | Mobile: ${{100 - pcPct}}%`;

      renderOverviewSummary(rep, mdContent);
      renderHourlyExplorer();
      renderCombinedTitles(rep.timeline || []);
      renderLongestSessions(rep.longest_sessions || []);
      renderDomains(rep.domains || []);
      renderMobileApps(rep.apps || []);
      renderDesktopApps(rep.desktop_apps || []);
      renderLedger(rep.timeline || []);
      renderUnobservedGapsCard(rep);
      setActiveTab(activeMainTab);
    }}

    function computeUnobservedGaps(timeline, targetDateStr) {{
      if (!timeline || timeline.length === 0) return [];
      
      const parsedIntervals = [];
      timeline.forEach(item => {{
        const sPart = parseLocalTimeParts(item.start);
        const ePart = parseLocalTimeParts(item.end);
        if (!sPart || !ePart) return;
        let sSec = sPart.totalSeconds;
        let eSec = ePart.totalSeconds;
        if (eSec < sSec) eSec += 86400;
        parsedIntervals.push({{
          startSec: sSec,
          endSec: eSec,
          source: item.source,
          title: item.context?.activity || item.context?.title || item.context?.app || item.context?.domain || item.source
        }});
      }});

      parsedIntervals.sort((a, b) => a.startSec - b.startSec);
      
      const merged = [];
      parsedIntervals.forEach(iv => {{
        if (!merged.length) {{
          merged.push(Object.assign({{}}, iv));
          return;
        }}
        const prev = merged[merged.length - 1];
        if (iv.startSec <= prev.endSec) {{
          if (iv.endSec > prev.endSec) {{
            prev.endSec = iv.endSec;
            prev.followed = iv.title;
          }}
        }} else {{
          merged.push(Object.assign({{}}, iv));
        }}
      }});

      const gaps = [];

      // 1. Day start boundary (00:00:00 to first observed activity)
      if (merged.length > 0 && merged[0].startSec >= 10 * 60) {{
        gaps.push({{
          startSec: 0,
          endSec: merged[0].startSec,
          duration: merged[0].startSec,
          startStr: "00:00:00",
          endStr: formatTimeOfDay(merged[0].startSec),
          prior: "Midnight (00:00:00)",
          next: merged[0].title
        }});
      }}

      // 2. Inter-activity timeline gaps
      for (let i = 0; i < merged.length - 1; i++) {{
        const gStart = merged[i].endSec;
        const gEnd = merged[i + 1].startSec;
        const dur = gEnd - gStart;
        if (dur >= 10 * 60) {{
          gaps.push({{
            startSec: gStart,
            endSec: gEnd,
            duration: dur,
            startStr: formatTimeOfDay(gStart),
            endStr: formatTimeOfDay(gEnd),
            prior: merged[i].followed || merged[i].title,
            next: merged[i + 1].title
          }});
        }}
      }}

      // 3. Day end boundary (last activity to day end or current time)
      if (merged.length > 0) {{
        const lastEnd = merged[merged.length - 1].endSec;
        let endBoundary = 86400;
        const now = new Date();
        const todayStr = `${{now.getFullYear()}}-${{String(now.getMonth() + 1).padStart(2, "0")}}-${{String(now.getDate()).padStart(2, "0")}}`;
        if (targetDateStr === todayStr) {{
          endBoundary = Math.min(86400, now.getHours() * 3600 + now.getMinutes() * 60 + now.getSeconds());
        }}
        const dur = endBoundary - lastEnd;
        if (dur >= 10 * 60) {{
          gaps.push({{
            startSec: lastEnd,
            endSec: endBoundary,
            duration: dur,
            startStr: formatTimeOfDay(lastEnd),
            endStr: formatTimeOfDay(endBoundary),
            prior: merged[merged.length - 1].followed || merged[merged.length - 1].title,
            next: targetDateStr === todayStr ? "Current Time" : "Day End (23:59)"
          }});
        }}
      }}

      return gaps;
    }}

    const PRESET_OPTIONS = [
      "Afternoon nap",
      "Sleep",
      "Dinner",
      "Snacks",
      "Lunch",
      "Walk",
      "Discussion"
    ];
    let selectedPresets = new Set();

    function renderPresetButtons() {{
      const container = document.getElementById("modal-preset-container");
      if (!container) return;
      container.innerHTML = "";
      PRESET_OPTIONS.forEach(opt => {{
        const isSel = selectedPresets.has(opt);
        const btn = document.createElement("button");
        btn.type = "button";
        btn.textContent = opt;
        btn.className = isSel
          ? "px-2.5 py-1 rounded-md text-[11px] font-medium bg-[#f97316] text-white border border-[#f97316] shadow-sm transition"
          : "px-2.5 py-1 rounded-md text-[11px] font-medium bg-white/[0.04] text-slate-300 hover:bg-white/[0.08] hover:text-white border border-white/[0.08] transition";
        btn.onclick = () => togglePreset(opt);
        container.appendChild(btn);
      }});
    }}

    function togglePreset(opt) {{
      if (selectedPresets.has(opt)) {{
        selectedPresets.delete(opt);
      }} else {{
        selectedPresets.add(opt);
      }}
      renderPresetButtons();
      syncActivityInputFromPresets();
    }}

    function syncActivityInputFromPresets() {{
      const actInput = document.getElementById("modal-gap-activity");
      if (!actInput) return;
      if (selectedPresets.size > 0) {{
        actInput.value = Array.from(selectedPresets).join(" + ");
      }} else {{
        actInput.value = "";
      }}
    }}

    function clearSelectedPresets() {{
      selectedPresets.clear();
      renderPresetButtons();
      syncActivityInputFromPresets();
    }}

    function renderUnobservedGapsCard(rep) {{
      const container = document.getElementById("unobserved-gaps-list");
      const badge = document.getElementById("unobserved-gaps-count-badge");
      if (!container) return;

      const gaps = computeUnobservedGaps(rep?.timeline || [], currentDate);
      if (badge) badge.textContent = `${{gaps.length}} Gaps`;

      container.innerHTML = "";
      if (gaps.length === 0) {{
        container.innerHTML = `<div class="col-span-full py-4 text-center text-xs text-neutral-500 font-mono">No unobserved gaps (&ge; 10 min) remaining today. All active and offline time accounted for!</div>`;
        return;
      }}

      gaps.forEach(g => {{
        const card = document.createElement("div");
        card.className = "p-3 rounded-xl bg-[#090a0f] border border-[#f97316]/20 hover:border-[#f97316]/40 transition flex items-center justify-between gap-3 text-xs";
        
        let suggestion = "";
        const startH = Math.floor(g.startSec / 3600);
        if ((startH >= 23 || startH < 7) && g.duration >= 3 * 3600) suggestion = "Sleep";
        else if (startH >= 12 && startH <= 16 && g.duration >= 30 * 60) suggestion = "Afternoon nap";
        else if (startH >= 12 && startH <= 14 && g.duration < 90 * 60) suggestion = "Lunch";
        else if (startH >= 19 && startH <= 22 && g.duration < 90 * 60) suggestion = "Dinner";

        card.innerHTML = `
          <div class="min-w-0">
            <div class="flex items-center gap-2">
              <span class="font-mono font-bold text-[#fb923c] text-xs">${{g.startStr}} &ndash; ${{g.endStr}}</span>
              <span class="px-1.5 py-0.2 rounded text-[10px] font-mono bg-[#f97316]/10 text-[#fdba74] border border-[#f97316]/30">${{formatSecs(g.duration)}}</span>
            </div>
            <div class="text-[10px] text-neutral-400 truncate mt-1">
              Between: <span class="text-neutral-300">${{escapeHtml(g.prior)}}</span> &rarr; <span class="text-neutral-300">${{escapeHtml(g.next)}}</span>
            </div>
          </div>
          <button onclick="openLabelGapModal('${{g.startStr}}', '${{g.endStr}}', '${{suggestion}}')" class="px-2.5 py-1.5 rounded-lg text-xs font-semibold bg-[#f97316]/15 hover:bg-[#f97316]/25 text-[#fb923c] border border-[#f97316]/30 shrink-0 transition flex items-center gap-1">
            <span>+ Label</span>
          </button>
        `;
        container.appendChild(card);
      }});
    }}

    function openLabelGapModal(startStr = "", endStr = "", suggested = "") {{
      const modal = document.getElementById("label-offline-modal");
      if (!modal) return;

      if (!startStr || !endStr) {{
        const rep = REPORTS_DATABASE[currentDate] || {{}};
        const gaps = computeUnobservedGaps(rep?.timeline || [], currentDate);
        if (gaps && gaps.length > 0) {{
          startStr = gaps[0].startStr;
          endStr = gaps[0].endStr;
          if (!suggested) {{
            const startH = Math.floor(gaps[0].startSec / 3600);
            if ((startH >= 23 || startH < 7) && gaps[0].duration >= 3 * 3600) suggested = "Sleep";
            else if (startH >= 12 && startH <= 16 && gaps[0].duration >= 30 * 60) suggested = "Afternoon nap";
            else if (startH >= 12 && startH <= 14) suggested = "Lunch";
            else if (startH >= 19 && startH <= 22) suggested = "Dinner";
          }}
        }} else {{
          startStr = "13:00";
          endStr = "14:00";
        }}
      }}

      document.getElementById("modal-gap-date").value = currentDate;
      document.getElementById("modal-gap-start").value = startStr;
      document.getElementById("modal-gap-end").value = endStr;
      
      document.getElementById("modal-gap-date-display").textContent = currentDate;
      document.getElementById("modal-gap-time-display").textContent = `${{startStr}} – ${{endStr}}`;

      const pill = document.getElementById("modal-gap-duration-pill");
      let gapDur = 0;
      if (startStr && endStr) {{
        const sParts = startStr.split(":").map(Number);
        const eParts = endStr.split(":").map(Number);
        const sSec = (sParts[0] || 0) * 3600 + (sParts[1] || 0) * 60 + (sParts[2] || 0);
        let eSec = (eParts[0] || 0) * 3600 + (eParts[1] || 0) * 60 + (eParts[2] || 0);
        if (eSec < sSec) eSec += 86400;
        gapDur = eSec - sSec;
      }}
      if (gapDur > 0) {{
        pill.textContent = `${{formatSecs(gapDur)}} (${{startStr}} &ndash; ${{endStr}})`;
      }} else {{
        pill.textContent = `${{startStr}} &ndash; ${{endStr}}`;
      }}
      pill.classList.remove("hidden");

      selectedPresets.clear();
      if (suggested && PRESET_OPTIONS.includes(suggested)) {{
        selectedPresets.add(suggested);
      }}
      renderPresetButtons();
      syncActivityInputFromPresets();

      if (suggested && !PRESET_OPTIONS.includes(suggested)) {{
        document.getElementById("modal-gap-activity").value = suggested;
      }}

      document.getElementById("modal-gap-notes").value = "";
      const statusEl = document.getElementById("modal-gap-status");
      statusEl.className = "hidden text-xs py-1";
      statusEl.textContent = "";

      modal.classList.remove("hidden");
      modal.classList.add("flex");
    }}

    function closeLabelGapModal() {{
      const modal = document.getElementById("label-offline-modal");
      if (!modal) return;
      modal.classList.add("hidden");
      modal.classList.remove("flex");
    }}

    async function submitLabelGapModal() {{
      const dateVal = document.getElementById("modal-gap-date").value || currentDate;
      const startVal = document.getElementById("modal-gap-start").value.trim();
      const endVal = document.getElementById("modal-gap-end").value.trim();
      const actVal = document.getElementById("modal-gap-activity").value.trim();
      const notesVal = document.getElementById("modal-gap-notes").value.trim();

      const statusEl = document.getElementById("modal-gap-status");
      const submitBtn = document.getElementById("btn-submit-gap-label");
      const submitText = document.getElementById("btn-submit-gap-text");

      if (!startVal || !endVal || !actVal) {{
        statusEl.className = "block text-xs py-1 text-rose-400 font-mono";
        statusEl.textContent = "Please select or enter an activity label.";
        return;
      }}

      statusEl.className = "block text-xs py-1 text-slate-300 font-mono";
      statusEl.textContent = "Saving to collector and updating report...";
      submitBtn.disabled = true;
      submitText.textContent = "Saving...";

      try {{
        const resp = await fetch("http://127.0.0.1:8765/api/manual", {{
          method: "POST",
          headers: getCollectorHeaders(),
          body: JSON.stringify({{
            date: dateVal,
            start: startVal,
            end: endVal,
            activity: actVal,
            notes: notesVal
          }})
        }});

        if (!resp.ok) {{
          const err = await resp.json().catch(() => ({{}}));
          throw new Error(err.message || `HTTP ${{resp.status}}`);
        }}

        statusEl.className = "block text-xs py-1 text-[#fb923c] font-mono";
        statusEl.textContent = `Saved '${{actVal}}'! Refreshing...`;

        setTimeout(() => {{
          closeLabelGapModal();
          try {{
            sessionStorage.setItem("dashboard_active_date", dateVal);
            sessionStorage.setItem("dashboard_active_tab", activeMainTab);
          }} catch (e) {{}}
          window.location.hash = `#date=${{encodeURIComponent(dateVal)}}&tab=${{encodeURIComponent(activeMainTab)}}`;
          window.location.reload();
        }}, 600);

      }} catch (err) {{
        console.error("Collector error:", err);
        statusEl.className = "block text-xs py-1 text-amber-400 font-mono space-y-1";
        statusEl.innerHTML = `
          <div>Collector server is not currently running at 127.0.0.1:8765.</div>
          <div class="text-[11px] text-slate-400">Please start <code class="text-white font-semibold">run_collector.bat</code> or run <code class="text-white font-semibold">annotate_gaps.bat</code>.</div>
        `;
        submitBtn.disabled = false;
        submitText.textContent = "Retry";
      }}
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
          hasReported: false,
          sources: {{ browser: 0, mobile: 0, desktop: 0, vscode: 0 }},
          manualSeconds: 0,
          activities: {{}},
          manualActivities: {{}}
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
          hourBuckets[h].hasReported = true;
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

        if (src === "manual") {{
          const actName = ctx.activity || ctx.title || "Offline Activity";
          const notes = ctx.notes || "";
          const actKey = `manual:::${{actName}}:::${{notes}}`;
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

              b.manualSeconds += effectiveSec;
              if (!b.manualActivities[actKey]) {{
                b.manualActivities[actKey] = {{
                  source: "manual",
                  title: actName,
                  subtitle: notes || (ctx.category ? ctx.category.toUpperCase() : "Offline"),
                  durationSeconds: 0,
                  sessionCount: 0
                }};
              }}
              b.manualActivities[actKey].durationSeconds += effectiveSec;
              b.manualActivities[actKey].sessionCount += 1;
            }}
          }}
        }} else {{
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
          }} else if (src === "vscode") {{
            title = ctx.workspace || "VS Code";
            subtitle = "";
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
        }}
      }});

      // Post-process each bucket
      let peakHour = 0;
      let maxSeconds = 0;
      let activeHoursCount = 0;

      hourBuckets.forEach(b => {{
        if (b.hasReported) {{
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

        const manList = Object.values(b.manualActivities);
        manList.sort((a, b) => b.durationSeconds - a.durationSeconds);
        b.sortedManualActivities = manList;
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
      renderDualLaneSwimlane();
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
        col.className = `flex-1 flex flex-col items-center justify-end h-full group relative cursor-pointer select-none transition-all p-0.5 rounded-lg ${{isSelected ? 'bg-white/[0.12]' : 'hover:bg-white/[0.04]'}}`;
        
        const topActs = (item.sortedActivities || []).filter(a => a.durationSeconds >= 60).slice(0, 2);
        let topActsHtml = "";
        if (topActs.length > 0) {{
          topActsHtml = topActs.map(a => `<div class="truncate text-[10px] text-neutral-300">• ${{escapeHtml(a.title.substring(0, 28))}}: <strong class="text-white">${{formatSecs(a.durationSeconds)}}</strong></div>`).join("");
        }} else if (total > 0) {{
          topActsHtml = `<div class="text-[10px] text-neutral-400">Brief interactions &lt; 1m (${{formatSecs(total)}})</div>`;
        }} else {{
          topActsHtml = `<div class="text-[10px] text-neutral-500">No activity (Sleep / Idle)</div>`;
        }}

        col.innerHTML = `
          <div class="opacity-0 group-hover:opacity-100 transition-opacity absolute -top-20 z-30 bg-[#11141e] border border-white/[0.12] text-neutral-200 text-xs px-2.5 py-1.5 rounded-lg shadow-2xl pointer-events-none min-w-[160px] space-y-1">
            <div class="flex items-center justify-between border-b border-white/[0.08] pb-1">
              <span class="font-mono font-medium text-white">${{String(h).padStart(2, "0")}}:00 &ndash; ${{String(h + 1).padStart(2, "0")}}:00</span>
              <span class="font-mono text-white font-semibold">${{formatSecs(total)}}</span>
            </div>
            ${{topActsHtml}}
          </div>
          <div class="w-full bg-[#0c0e16] rounded-t-sm flex flex-col-reverse overflow-hidden transition-all duration-300 group-hover:brightness-125" style="height: ${{Math.max(6, heightPct)}}%">
            <div class="bg-[#38bdf8] w-full" style="height: ${{bH}}%"></div>
            <div class="bg-[#a78bfa] w-full" style="height: ${{mH}}%"></div>
            <div class="bg-[#34d399] w-full" style="height: ${{dH}}%"></div>
            <div class="bg-[#fbbf24] w-full" style="height: ${{vH}}%"></div>
          </div>
          <span class="text-[10px] font-mono mt-1 ${{isSelected ? 'text-white font-bold' : total > 0 ? 'text-neutral-300 font-medium' : 'text-neutral-600'}}">${{String(h).padStart(2, "0")}}</span>
        `;

        col.onclick = () => {{
          selectHour(h);
        }};

        container.appendChild(col);
      }}
    }}

    function appendHourDetailView(container, h, data) {{
      const bucket = data.buckets[h] || {{ hour: h, totalSeconds: 0, manualSeconds: 0, sortedActivities: [], sortedManualActivities: [] }};
      const totalSec = bucket.displayActiveSeconds || bucket.totalSeconds || 0;
      const manSec = bucket.manualSeconds || 0;
      const acts = (bucket.sortedActivities || []).filter(a => a.durationSeconds >= 60);
      const manActs = (bucket.sortedManualActivities || []).filter(a => a.durationSeconds >= 60);
      const minorCount = (bucket.sortedActivities || []).filter(a => a.durationSeconds < 60).length;
      const pctOfHour = Math.min(100, Math.round((totalSec / 3600) * 100));

      if (totalSec > 0 || manSec > 0) {{
        // Mini Multi-Track timeline strip for this 60-minute window
        const rep = REPORTS_DATABASE[currentDate] || {{}};
        const hStart = h * 3600;
        const hEnd = (h + 1) * 3600;
        const pcSegs = [];
        const mobSegs = [];
        const manSegs = [];

        (rep.timeline || []).forEach(item => {{
          const sPart = parseLocalTimeParts(item.start);
          const ePart = parseLocalTimeParts(item.end);
          if (!sPart || !ePart) return;
          let sSec = sPart.totalSeconds;
          let eSec = ePart.totalSeconds;
          if (eSec < sSec) eSec += 86400;

          const ovS = Math.max(sSec, hStart);
          const ovE = Math.min(eSec, hEnd);
          if (ovE > ovS) {{
            const dur = ovE - ovS;
            const leftPct = ((ovS - hStart) / 3600) * 100;
            const widthPct = Math.max(0.5, (dur / 3600) * 100);
            const ctx = item.context || {{}};
            const title = ctx.activity || ctx.title || ctx.app || ctx.domain || item.source;
            const seg = {{
              startSec: ovS,
              endSec: ovE,
              duration: dur,
              leftPct: leftPct,
              widthPct: widthPct,
              source: item.source,
              title: title
            }};
            if (item.source === "mobile") {{
              mobSegs.push(seg);
            }} else if (item.source === "manual") {{
              manSegs.push(seg);
            }} else {{
              pcSegs.push(seg);
            }}
          }}
        }});

        // Overlap computation for this hour (PC + Phone only)
        const hourOverlaps = [];
        pcSegs.forEach(p => {{
          mobSegs.forEach(m => {{
            const os = Math.max(p.startSec, m.startSec);
            const oe = Math.min(p.endSec, m.endSec);
            if (oe > os) {{
              hourOverlaps.push({{
                leftPct: ((os - hStart) / 3600) * 100,
                widthPct: Math.max(0.5, ((oe - os) / 3600) * 100),
                duration: oe - os,
                pcTitle: p.title,
                mobTitle: m.title
              }});
            }}
          }});
        }});

        // Deduplicate overlap seconds
        const mergedHOverlaps = [];
        hourOverlaps.slice().sort((a, b) => a.leftPct - b.leftPct).forEach(ov => {{
          const s = ov.leftPct;
          const e = ov.leftPct + ov.widthPct;
          if (!mergedHOverlaps.length || s > mergedHOverlaps[mergedHOverlaps.length - 1][1]) {{
            mergedHOverlaps.push([s, e]);
          }} else {{
            mergedHOverlaps[mergedHOverlaps.length - 1][1] = Math.max(mergedHOverlaps[mergedHOverlaps.length - 1][1], e);
          }}
        }});
        const hourOverlapSec = Math.round(mergedHOverlaps.reduce((sum, [s, e]) => sum + ((e - s) / 100 * 3600), 0));

        const miniDualLane = document.createElement("div");
        miniDualLane.className = "p-3 rounded-xl bg-[#0c0e16] border border-white/[0.08] space-y-2.5 my-1";

        let pcBlocksHtml = pcSegs.map(s => {{
          let col = "bg-[#38bdf8]";
          if (s.source === "vscode") col = "bg-[#fbbf24]";
          else if (s.source === "desktop") col = "bg-[#34d399]";
          return `<div class="absolute top-0 bottom-0 ${{col}} rounded-[2px] transition hover:brightness-125 cursor-pointer" style="left: ${{s.leftPct}}%; width: ${{s.widthPct}}%;" title="${{escapeHtml(s.title)}} (${{formatSecs(s.duration)}})"></div>`;
        }}).join("");

        let mobBlocksHtml = mobSegs.map(s => {{
          return `<div class="absolute top-0 bottom-0 bg-[#a78bfa] rounded-[2px] transition hover:brightness-125 cursor-pointer" style="left: ${{s.leftPct}}%; width: ${{s.widthPct}}%;" title="${{escapeHtml(s.title)}} (${{formatSecs(s.duration)}})"></div>`;
        }}).join("");

        let manBlocksHtml = manSegs.map(s => {{
          return `<div class="absolute top-0 bottom-0 bg-[#ea580c] rounded-[2px] transition hover:brightness-125 cursor-pointer" style="left: ${{s.leftPct}}%; width: ${{s.widthPct}}%;" title="[OFFLINE] ${{escapeHtml(s.title)}} (${{formatSecs(s.duration)}})"></div>`;
        }}).join("");

        let overlapBlocksHtml = hourOverlaps.map(ov => {{
          return `<div class="absolute top-0 bottom-0 bg-[#fb7185] rounded-[2px] z-10 transition hover:brightness-125 cursor-pointer" style="left: ${{ov.leftPct}}%; width: ${{ov.widthPct}}%;" title="Co-Use: ${{escapeHtml(ov.pcTitle)}} + ${{escapeHtml(ov.mobTitle)}} (${{formatSecs(ov.duration)}})"></div>`;
        }}).join("");

        miniDualLane.innerHTML = `
          <div class="flex items-center justify-between text-[11px] font-mono">
            <span class="text-neutral-400 font-medium flex items-center gap-1.5">
              <span>Multi-Track (Hour ${{String(h).padStart(2, "0")}}:00 Window)</span>
              ${{hourOverlapSec > 0 ? `<span class="px-1.5 py-0.2 rounded text-[10px] bg-[#fb7185]/10 text-[#fda4af] border border-[#fb7185]/20 font-medium">${{formatSecs(hourOverlapSec)}} Co-Use</span>` : ''}}
            </span>
            <div class="flex items-center gap-3 text-[10px] text-neutral-400">
              <span class="inline-flex items-center gap-1"><span class="w-1.5 h-1.5 rounded-sm bg-[#38bdf8]"></span> PC</span>
              <span class="inline-flex items-center gap-1"><span class="w-1.5 h-1.5 rounded-sm bg-[#a78bfa]"></span> Phone</span>
              ${{manSegs.length > 0 ? `<span class="inline-flex items-center gap-1 text-[#fb923c] font-medium"><span class="w-1.5 h-1.5 rounded-sm bg-[#ea580c]"></span> Offline</span>` : ''}}
              ${{hourOverlaps.length > 0 ? `<span class="inline-flex items-center gap-1 text-[#fda4af] font-medium"><span class="w-1.5 h-1.5 rounded-sm bg-[#fb7185]"></span> Co-Use</span>` : ''}}
            </div>
          </div>

          <div class="space-y-1.5 relative pt-1">
            <div class="flex items-center gap-2">
              <span class="text-[10px] font-mono text-neutral-400 w-10 shrink-0">PC</span>
              <div class="flex-1 h-3.5 bg-[#090a0f] rounded relative overflow-hidden border border-white/[0.04]">
                ${{pcBlocksHtml || '<span class="text-[9px] text-neutral-600 font-mono absolute inset-0 flex items-center px-2">idle</span>'}}
              </div>
            </div>

            <div class="flex items-center gap-2">
              <span class="text-[10px] font-mono text-neutral-400 w-10 shrink-0">Phone</span>
              <div class="flex-1 h-3.5 bg-[#090a0f] rounded relative overflow-hidden border border-white/[0.04]">
                ${{mobBlocksHtml || '<span class="text-[9px] text-neutral-600 font-mono absolute inset-0 flex items-center px-2">idle</span>'}}
              </div>
            </div>

            ${{manSegs.length > 0 ? `
            <div class="flex items-center gap-2">
              <span class="text-[10px] font-mono text-[#fb923c] w-10 shrink-0 font-medium">Offline</span>
              <div class="flex-1 h-3.5 bg-[#090a0f] rounded relative overflow-hidden border border-[#f97316]/20">
                ${{manBlocksHtml}}
              </div>
            </div>
            ` : ''}}

            ${{hourOverlaps.length > 0 ? `
            <div class="flex items-center gap-2">
              <span class="text-[10px] font-mono text-[#fda4af] w-10 shrink-0 font-medium">Co-Use</span>
              <div class="flex-1 h-2 bg-[#090a0f] rounded relative overflow-hidden border border-white/[0.04]">
                ${{overlapBlocksHtml}}
              </div>
            </div>
            ` : ''}}

            <div class="flex justify-between text-[9px] font-mono text-neutral-500 pl-12 pr-0.5 pt-0.5">
              <span>00m</span>
              <span>15m</span>
              <span>30m</span>
              <span>45m</span>
              <span>60m</span>
            </div>
          </div>
        `;
        container.appendChild(miniDualLane);
      }}

      if (acts.length === 0 && manActs.length === 0) {{
        const empty = document.createElement("div");
        empty.className = "py-8 text-center text-xs text-neutral-500 space-y-1 font-mono";
        if (totalSec > 0) {{
          empty.innerHTML = `
            <div>Only brief interactions (&lt; 1 min) logged during ${{String(h).padStart(2, "0")}}:00 &ndash; ${{String(h + 1).padStart(2, "0")}}:00 (${{formatSecs(totalSec)}} total)</div>
            <div class="text-[11px] text-neutral-600">Events under 1 minute are hidden from this hourly view.</div>
          `;
        }} else {{
          empty.innerHTML = `
            <div>No activity logged between ${{String(h).padStart(2, "0")}}:00 and ${{String(h + 1).padStart(2, "0")}}:00</div>
            <div class="text-[11px] text-neutral-600">Computer and phone were idle.</div>
          `;
        }}
        container.appendChild(empty);
        return;
      }}

      const listContainer = document.createElement("div");
      listContainer.className = "space-y-2 pt-1";

      let actIndex = 1;
      acts.forEach((act) => {{
        const itemPct = totalSec > 0 ? (act.durationSeconds / totalSec) * 100 : 0;

        let srcBadge = "bg-[#38bdf8]/10 text-[#7dd3fc] border-[#38bdf8]/20";
        let barColor = "bg-[#38bdf8]";
        if (act.source === "mobile") {{
          srcBadge = "bg-[#a78bfa]/10 text-[#c4b5fd] border-[#a78bfa]/20";
          barColor = "bg-[#a78bfa]";
        }} else if (act.source === "desktop") {{
          srcBadge = "bg-[#34d399]/10 text-[#6ee7b7] border-[#34d399]/20";
          barColor = "bg-[#34d399]";
        }} else if (act.source === "vscode") {{
          srcBadge = "bg-[#fbbf24]/10 text-[#fde047] border-[#fbbf24]/20";
          barColor = "bg-[#fbbf24]";
        }}

        const row = document.createElement("div");
        row.className = "p-2.5 rounded-lg bg-[#0e111a] border border-white/[0.06] hover:bg-[#141824] hover:border-white/[0.12] transition space-y-2";
        row.innerHTML = `
          <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-1.5 text-xs">
            <div class="flex items-center gap-2.5 min-w-0">
              <span class="font-mono text-neutral-500 font-bold text-xs w-4 shrink-0">${{actIndex++}}.</span>
              <span class="px-1.5 py-0.5 rounded text-[10px] font-mono font-semibold uppercase tracking-wider border shrink-0 ${{srcBadge}}">
                ${{act.source}}
              </span>
              <div class="min-w-0">
                <div class="font-medium text-white truncate" title="${{escapeHtml(act.title)}}">${{escapeHtml(act.title)}}</div>
                ${{act.subtitle ? `<div class="text-[11px] text-neutral-400 font-mono truncate" title="${{escapeHtml(act.subtitle)}}">${{escapeHtml(act.subtitle)}}</div>` : ''}}
              </div>
            </div>

            <div class="flex items-center gap-3 shrink-0 self-end sm:self-auto font-mono text-xs">
              <span class="text-neutral-400">${{itemPct.toFixed(1)}}%</span>
              <span class="font-medium text-white bg-white/[0.06] px-2 py-0.5 rounded border border-white/[0.08]">${{formatSecs(act.durationSeconds)}}</span>
            </div>
          </div>

          <div class="w-full bg-[#090a0f] h-1.5 rounded-full overflow-hidden border border-white/[0.04]">
            <div class="${{barColor}} h-full rounded-full transition-all duration-300" style="width: ${{Math.min(100, itemPct)}}%"></div>
          </div>
        `;
        listContainer.appendChild(row);
      }});

      manActs.forEach((act) => {{
        const itemPct = Math.min(100, (act.durationSeconds / 3600) * 100);
        const row = document.createElement("div");
        row.className = "p-2.5 rounded-lg bg-[#140f0a] border border-[#f97316]/20 hover:border-[#f97316]/40 transition space-y-2";
        row.innerHTML = `
          <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-1.5 text-xs">
            <div class="flex items-center gap-2.5 min-w-0">
              <span class="font-mono text-[#fb923c] font-bold text-xs w-4 shrink-0">${{actIndex++}}.</span>
              <span class="px-1.5 py-0.5 rounded text-[10px] font-mono font-semibold uppercase tracking-wider border shrink-0 bg-[#f97316]/10 text-[#fb923c] border-[#f97316]/30">
                OFFLINE
              </span>
              <div class="min-w-0">
                <div class="font-medium text-white truncate" title="${{escapeHtml(act.title)}}">${{escapeHtml(act.title)}}</div>
                ${{act.subtitle ? `<div class="text-[11px] text-neutral-400 font-mono truncate" title="${{escapeHtml(act.subtitle)}}">${{escapeHtml(act.subtitle)}}</div>` : ''}}
              </div>
            </div>

            <div class="flex items-center gap-3 shrink-0 self-end sm:self-auto font-mono text-xs">
              <span class="text-[#fdba74] font-mono">${{itemPct.toFixed(1)}}% of hr</span>
              <span class="font-medium text-white bg-[#f97316]/20 px-2 py-0.5 rounded border border-[#f97316]/30">${{formatSecs(act.durationSeconds)}}</span>
            </div>
          </div>

          <div class="w-full bg-[#090a0f] h-1.5 rounded-full overflow-hidden border border-[#f97316]/15">
            <div class="bg-[#ea580c] h-full rounded-full transition-all duration-300" style="width: ${{itemPct}}%"></div>
          </div>
        `;
        listContainer.appendChild(row);
      }});

      container.appendChild(listContainer);
    }}

    function renderHourlyInspector(data) {{
      const container = document.getElementById("hourly-inspector-container");
      if (!container) return;
      container.innerHTML = "";

      const h = selectedHour !== null ? selectedHour : 0;
      const bucket = data.buckets[h] || {{ hour: h, totalSeconds: 0, manualSeconds: 0, sortedActivities: [], sortedManualActivities: [] }};
      const totalSec = bucket.displayActiveSeconds || bucket.totalSeconds || 0;
      const manSec = bucket.manualSeconds || 0;
      const acts = (bucket.sortedActivities || []).filter(a => a.durationSeconds >= 60);
      const manActs = (bucket.sortedManualActivities || []).filter(a => a.durationSeconds >= 60);
      const minorCount = (bucket.sortedActivities || []).filter(a => a.durationSeconds < 60).length;
      const pctOfHour = Math.min(100, Math.round((totalSec / 3600) * 100));
      const isFiltered = activeHourFilter === h;

      let badgeHtml = "";
      if (totalSec > 0) {{
        badgeHtml = `<span class="px-2 py-0.5 rounded text-[11px] font-mono font-medium bg-[#34d399]/10 text-[#6ee7b7] border border-[#34d399]/20">${{formatSecs(totalSec)}} active (${{pctOfHour}}%)</span>`;
      }} else if (manSec > 0) {{
        badgeHtml = `<span class="px-2 py-0.5 rounded text-[11px] font-mono font-medium bg-[#f97316]/10 text-[#fb923c] border border-[#f97316]/20">${{formatSecs(manSec)}} offline</span>`;
      }} else {{
        badgeHtml = `<span class="px-2 py-0.5 rounded text-[11px] font-mono font-medium bg-white/[0.04] text-neutral-400 border border-white/[0.08]">No Activity</span>`;
      }}

      let subText = "";
      if (acts.length > 0 && manActs.length > 0) {{
        subText = `${{acts.length}} screen activities • ${{manActs.length}} offline activities`;
      }} else if (acts.length > 0) {{
        subText = `${{acts.length}} activities &ge; 1 min` + (minorCount > 0 ? ` &bull; ${{minorCount}} brief under 1m` : '');
      }} else if (manActs.length > 0) {{
        subText = `${{manActs.map(a => escapeHtml(a.title)).join(", ")}} (${{formatSecs(manSec)}})`;
      }} else {{
        subText = totalSec > 0 ? 'Only brief interactions &lt; 1 min' : 'Idle span / Sleep';
      }}

      const header = document.createElement("div");
      header.className = "flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-white/[0.08]";
      header.innerHTML = `
        <div class="flex items-center gap-3">
          <div class="w-9 h-9 rounded-lg bg-white/[0.04] border border-white/[0.08] flex items-center justify-center font-mono font-semibold text-sm text-white shadow-[inset_0_1px_0_rgba(255,255,255,0.05)]">
            ${{String(h).padStart(2, "0")}}h
          </div>
          <div>
            <div class="flex items-center gap-2">
              <h3 class="text-sm font-semibold text-white">Hour ${{String(h).padStart(2, "0")}}:00 &ndash; ${{String(h + 1).padStart(2, "0")}}:00</h3>
              ${{badgeHtml}}
            </div>
            <div class="text-xs text-neutral-400 mt-0.5 font-mono">
              ${{subText}}
            </div>
          </div>
        </div>

        <div class="flex items-center gap-1.5 self-end sm:self-auto">
          <button onclick="selectHour(${{h > 0 ? h - 1 : 23}})" class="px-2.5 py-1 rounded-md text-xs font-mono bg-[#0c0e16] hover:bg-white/[0.06] text-neutral-300 border border-white/[0.08] transition" title="Previous hour">
            &larr; Prev
          </button>
          <button onclick="selectHour(${{h < 23 ? h + 1 : 0}})" class="px-2.5 py-1 rounded-md text-xs font-mono bg-[#0c0e16] hover:bg-white/[0.06] text-neutral-300 border border-white/[0.08] transition" title="Next hour">
            Next &rarr;
          </button>
          <button onclick="selectHour(${{data.peakHour}})" class="px-2.5 py-1 rounded-md text-xs font-mono ${{h === data.peakHour ? 'bg-white/[0.12] text-white border border-white/[0.2] font-semibold' : 'bg-[#0c0e16] hover:bg-white/[0.06] text-neutral-300 border border-white/[0.08]'}} transition" title="Jump to peak activity hour">
            Peak (${{String(data.peakHour).padStart(2, "0")}}:00)
          </button>
          <button onclick="toggleHourFilter(${{h}})" class="px-2.5 py-1 rounded-md text-xs font-mono ${{isFiltered ? 'bg-white/[0.12] text-white border border-white/[0.2] font-semibold' : 'bg-[#0c0e16] hover:bg-white/[0.06] text-neutral-300 border border-white/[0.08]'}} transition">
            ${{isFiltered ? 'Clear Filter' : 'Filter Ledger'}}
          </button>
        </div>
      `;
      container.appendChild(header);

      appendHourDetailView(container, h, data);
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
            flushIdleBlock(container, idleStart, 23, data);
          }}
          continue;
        }}

        if (idleStart !== -1) {{
          flushIdleBlock(container, idleStart, h - 1, data);
          idleStart = -1;
        }}

        const isExpanded = (expandedScheduleHour === h);
        const row = document.createElement("div");
        row.className = `rounded-xl border transition ${{isExpanded ? 'bg-[#121622] border-white/[0.18] shadow-lg ring-1 ring-white/[0.05]' : 'bg-[#0e111a] border-white/[0.06] hover:bg-[#141824] hover:border-white/[0.12]'}}`;

        const acts = (b.sortedActivities || []).filter(a => a.durationSeconds >= 60);
        const manActs = (b.sortedManualActivities || []).filter(a => a.durationSeconds >= 60);
        const top3Acts = acts.slice(0, 3);
        const actChipsList = top3Acts.map(a => {{
          let col = "text-[#7dd3fc] bg-[#38bdf8]/10 border-[#38bdf8]/20";
          if (a.source === "mobile") col = "text-[#c4b5fd] bg-[#a78bfa]/10 border-[#a78bfa]/20";
          else if (a.source === "desktop") col = "text-[#6ee7b7] bg-[#34d399]/10 border-[#34d399]/20";
          else if (a.source === "vscode") col = "text-[#fde047] bg-[#fbbf24]/10 border-[#fbbf24]/20";
          return `<span class="inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-[11px] font-mono border ${{col}}">
            <span class="font-medium text-white truncate max-w-[160px]">${{escapeHtml(a.title)}}</span>
            <strong class="text-neutral-300 font-semibold">${{formatSecs(a.durationSeconds)}}</strong>
          </span>`;
        }});

        manActs.slice(0, 2).forEach(ma => {{
          actChipsList.push(`<span class="inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-[11px] font-mono border text-[#fb923c] bg-[#f97316]/10 border-[#f97316]/20">
            <span class="font-medium text-white truncate max-w-[160px]">${{escapeHtml(ma.title)}}</span>
            <strong class="text-[#fdba74] font-semibold">${{formatSecs(ma.durationSeconds)}}</strong>
          </span>`);
        }});

        let actChips = actChipsList.join(" ");
        if (!actChips) {{
          actChips = `<span class="text-[11px] text-neutral-500 font-mono italic">Brief interactions (&lt; 1 min)</span>`;
        }}

        const pctOfHour = Math.min(100, Math.round((total / 3600) * 100));

        // Clickable header row toggles dropdown in place
        const headerEl = document.createElement("div");
        headerEl.className = "p-3 cursor-pointer space-y-2 select-none";
        headerEl.onclick = () => {{
          expandedScheduleHour = (expandedScheduleHour === h ? null : h);
          selectedHour = h;
          renderHourlySchedule(data);
          renderHourlyRhythmBars(data);
        }};

        const chevron = isExpanded
          ? `<svg class="w-3.5 h-3.5 text-[#fb923c] transform rotate-180 transition-transform duration-200" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"></path></svg>`
          : `<svg class="w-3.5 h-3.5 text-neutral-400 transition-transform duration-200" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"></path></svg>`;

        headerEl.innerHTML = `
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-2">
              <span class="font-mono font-medium text-xs text-white bg-white/[0.06] px-2 py-0.5 rounded border border-white/[0.08]">
                ${{String(h).padStart(2, "0")}}:00 &ndash; ${{String(h + 1).padStart(2, "0")}}:00
              </span>
              <span class="text-xs text-white font-mono font-semibold">${{formatSecs(total)}} active</span>
              <span class="text-[11px] text-neutral-400 font-mono">(${{pctOfHour}}%)</span>
            </div>
            <div class="flex items-center gap-1.5 text-[11px] font-mono ${{isExpanded ? 'text-[#fb923c] font-semibold' : 'text-neutral-400 hover:text-white'}}">
              <span>${{acts.length + manActs.length}} activities</span>
              ${{chevron}}
            </div>
          </div>
          <div class="flex flex-wrap gap-1.5 pt-0.5">
            ${{actChips}}
          </div>
        `;
        row.appendChild(headerEl);

        // If expanded, render inline dropdown inspector right here
        if (isExpanded) {{
          const dropdownEl = document.createElement("div");
          dropdownEl.className = "border-t border-white/[0.08] p-3 pt-3.5 space-y-3 bg-[#0a0d16]/90 rounded-b-xl";
          dropdownEl.onclick = (e) => e.stopPropagation();

          const isFiltered = activeHourFilter === h;
          const subBar = document.createElement("div");
          subBar.className = "flex items-center justify-between pb-2 border-b border-white/[0.06]";
          subBar.innerHTML = `
            <div class="flex items-center gap-2">
              <span class="text-xs font-semibold text-white">Hour ${{String(h).padStart(2, "0")}}:00 Detailed Breakdown</span>
              <span class="text-[11px] font-mono text-neutral-400 font-normal">(${{formatSecs(total)}})</span>
            </div>
            <div class="flex items-center gap-2">
              <button onclick="toggleHourFilter(${{h}})" class="px-2.5 py-1 rounded text-xs font-mono ${{isFiltered ? 'bg-white/[0.12] text-white border border-white/[0.2] font-semibold' : 'bg-[#0c0e16] hover:bg-white/[0.06] text-neutral-300 border border-white/[0.08]'}} transition">
                ${{isFiltered ? 'Clear Filter' : 'Filter Ledger'}}
              </button>
            </div>
          `;
          dropdownEl.appendChild(subBar);

          appendHourDetailView(dropdownEl, h, data);

          row.appendChild(dropdownEl);
        }}

        container.appendChild(row);
      }}
    }}

    function flushIdleBlock(container, startH, endH, data) {{
      const hoursCount = endH - startH + 1;
      const manualActsMap = {{}};
      if (data && data.buckets) {{
        for (let ih = startH; ih <= endH; ih++) {{
          (data.buckets[ih]?.sortedManualActivities || []).forEach(ma => {{
            if (!manualActsMap[ma.title]) {{
              manualActsMap[ma.title] = 0;
            }}
            manualActsMap[ma.title] += ma.durationSeconds;
          }});
        }}
      }}
      const manualActsList = Object.entries(manualActsMap);

      const block = document.createElement("div");
      if (manualActsList.length > 0) {{
        block.className = "py-2.5 px-3 rounded-xl bg-[#0c0e16]/80 border border-dashed border-[#f97316]/30 flex flex-wrap items-center justify-between gap-2 text-xs font-mono transition";
        const manualChipsHtml = manualActsList.map(([title, dur]) => {{
          return `<span class="inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-[11px] font-mono bg-[#f97316]/15 text-[#fb923c] border border-[#f97316]/30">
            <span class="font-medium text-white">${{escapeHtml(title)}}</span>
            <strong class="text-[#fdba74] font-semibold">${{formatSecs(dur)}}</strong>
          </span>`;
        }}).join(" ");

        block.innerHTML = `
          <div class="flex items-center gap-2.5 flex-wrap">
            <span class="w-1.5 h-1.5 rounded-full bg-[#f97316]"></span>
            <span class="font-medium text-white bg-white/[0.06] px-2 py-0.5 rounded border border-white/[0.08]">
              ${{String(startH).padStart(2, "0")}}:00 &ndash; ${{String(endH + 1).padStart(2, "0")}}:00
            </span>
            <span class="text-neutral-400">(${{hoursCount}}h inactive)</span>
            ${{manualChipsHtml}}
          </div>
          <div class="flex items-center gap-2">
            <span class="text-[11px] text-[#fb923c] font-medium">Offline / Rest</span>
          </div>
        `;
      }} else {{
        block.className = "py-2.5 px-3 rounded-xl bg-[#0c0e16]/60 border border-dashed border-white/[0.08] flex flex-wrap items-center justify-between gap-2 text-xs text-neutral-400 font-mono transition";
        const sTimeStr = `${{String(startH).padStart(2, "0")}}:00:00`;
        const eTimeStr = `${{String(endH + 1).padStart(2, "0")}}:00:00`;
        const suggested = (startH >= 22 || startH < 7) ? "Sleep" : (startH >= 12 && startH <= 16) ? "Afternoon nap" : "";

        block.innerHTML = `
          <div class="flex items-center gap-2">
            <span class="w-1.5 h-1.5 rounded-full bg-neutral-600"></span>
            <span class="font-medium text-neutral-300 bg-white/[0.04] px-2 py-0.5 rounded border border-white/[0.06]">
              ${{String(startH).padStart(2, "0")}}:00 &ndash; ${{String(endH + 1).padStart(2, "0")}}:00
            </span>
            <span>(${{hoursCount}}h inactive)</span>
          </div>
          <div class="flex items-center gap-2">
            <span class="text-[11px] text-neutral-500">No screen activity</span>
            <button onclick="openLabelGapModal('${{sTimeStr}}', '${{eTimeStr}}', '${{suggested}}')" class="px-2 py-0.5 rounded text-[11px] font-semibold bg-[#f97316]/15 hover:bg-[#f97316]/25 text-[#fb923c] border border-[#f97316]/30 transition">
              + Label Offline
            </button>
          </div>
        `;
      }}
      container.appendChild(block);
    }}

    function renderDualLaneSwimlane() {{
      const container = document.getElementById("hourly-duallane-container");
      if (!container) return;
      container.innerHTML = "";

      const rep = REPORTS_DATABASE[currentDate] || {{}};
      const timeline = rep.timeline || [];
      const sources = rep.sources || {{}};

      const pcSessions = [];
      const mobSessions = [];
      const manualSessions = [];

      timeline.forEach(item => {{
        const sPart = parseLocalTimeParts(item.start);
        const ePart = parseLocalTimeParts(item.end);
        if (!sPart || !ePart) return;

        let sSec = sPart.totalSeconds;
        let eSec = ePart.totalSeconds;
        if (eSec < sSec) eSec += 86400;

        const dur = Math.max(1, eSec - sSec);
        const ctx = item.context || {{}};
        let title = "";
        let subtitle = "";

        if (item.source === "browser") {{
          title = ctx.title || ctx.domain || "Browser";
          subtitle = ctx.domain || "";
        }} else if (item.source === "desktop") {{
          title = ctx.app || "Desktop App";
          subtitle = (ctx.title && ctx.title !== ctx.app) ? ctx.title : "";
        }} else if (item.source === "mobile") {{
          title = ctx.app || ctx.package || "Mobile App";
          subtitle = ctx.package || "";
        }} else if (item.source === "vscode") {{
          title = ctx.workspace || "VS Code";
          subtitle = "";
        }} else if (item.source === "manual") {{
          title = ctx.activity || ctx.title || "Offline Activity";
          subtitle = ctx.category ? ctx.category.toUpperCase() : "Offline";
        }} else {{
          title = item.source || "Session";
        }}

        const sess = {{
          source: item.source,
          startSec: sSec,
          endSec: eSec,
          duration: dur,
          startStr: formatTimeOfDay(sSec),
          endStr: formatTimeOfDay(eSec),
          title: title,
          subtitle: subtitle,
          rawItem: item
        }};

        if (item.source === "mobile") {{
          mobSessions.push(sess);
        }} else if (item.source === "manual") {{
          manualSessions.push(sess);
        }} else {{
          pcSessions.push(sess);
        }}
      }});

      // Compute pairwise overlaps between PC and Mobile
      const rawOverlaps = [];
      pcSessions.forEach(p => {{
        mobSessions.forEach(m => {{
          const os = Math.max(p.startSec, m.startSec);
          const oe = Math.min(p.endSec, m.endSec);
          if (oe > os) {{
            rawOverlaps.push({{
              startSec: os,
              endSec: oe,
              duration: oe - os,
              pc: p,
              mob: m,
              hour: Math.floor(os / 3600)
            }});
          }}
        }});
      }});

      // Chronological sort
      rawOverlaps.sort((a, b) => a.startSec - b.startSec);

      // Deduplicate overlapping intervals for total co-use duration
      const mergedIntervals = [];
      rawOverlaps.forEach(o => {{
        if (!mergedIntervals.length || o.startSec > mergedIntervals[mergedIntervals.length - 1][1]) {{
          mergedIntervals.push([o.startSec, o.endSec]);
        }} else {{
          mergedIntervals[mergedIntervals.length - 1][1] = Math.max(mergedIntervals[mergedIntervals.length - 1][1], o.endSec);
        }}
      }});
      const totalCoUseSec = mergedIntervals.reduce((sum, [s, e]) => sum + (e - s), 0);

      // PC total seconds
      const bSec = sources.browser?.duration_seconds || 0;
      const dSec = sources.desktop?.duration_seconds || 0;
      const vSec = sources.vscode?.duration_seconds || 0;
      const pcTotalSec = bSec + dSec + vSec || pcSessions.reduce((sum, s) => sum + s.duration, 0);

      // Mobile total seconds
      const mobTotalSec = sources.mobile?.duration_seconds || mobSessions.reduce((sum, s) => sum + s.duration, 0);

      // Continuous non-overlapping coverage
      const allActiveIntervals = [];
      [...pcSessions, ...mobSessions].forEach(s => {{
        allActiveIntervals.push([s.startSec, s.endSec]);
      }});
      allActiveIntervals.sort((a, b) => a[0] - b[0]);
      const mergedAll = [];
      allActiveIntervals.forEach(([s, e]) => {{
        if (!mergedAll.length || s > mergedAll[mergedAll.length - 1][1]) {{
          mergedAll.push([s, e]);
        }} else {{
          mergedAll[mergedAll.length - 1][1] = Math.max(mergedAll[mergedAll.length - 1][1], e);
        }}
      }});
      const totalUnionSec = mergedAll.reduce((sum, [s, e]) => sum + (e - s), 0);

      const manTotalSec = sources.manual?.duration_seconds || manualSessions.reduce((sum, s) => sum + s.duration, 0);
      const totalAccounted = rep.summary?.total_accounted_seconds || totalUnionSec;
      const unobservedSec = rep.summary?.unobserved_seconds || Math.max(0, 86400 - totalAccounted);

      // 1. Header & Summary Cards
      const headerSection = document.createElement("div");
      headerSection.className = "space-y-3";
      headerSection.innerHTML = `
        <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-2 pb-1">
          <div>
            <h3 class="text-sm font-semibold text-white flex items-center gap-2">
              <span>24-Hour Multi-Track Swimlane (PC vs Mobile vs Offline)</span>
              <span class="px-2 py-0.5 rounded text-[11px] font-mono bg-white/[0.06] text-neutral-200 border border-white/[0.08] font-medium">Parallel Tracks</span>
            </h3>
            <p class="text-xs text-neutral-400 mt-0.5">
              Renders independent timelines for PC, smartphone, and manual offline activities to preserve true duration and highlight 24-hour routine.
            </p>
          </div>
          <div class="flex items-center gap-2 text-xs font-mono">
            <span class="text-neutral-400">Selected Hour:</span>
            <span class="px-2 py-0.5 rounded bg-white/[0.08] text-white border border-white/[0.14] font-semibold">
              ${{selectedHour !== null ? String(selectedHour).padStart(2, "0") + ":00" : "None"}}
            </span>
          </div>
        </div>

        <div class="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
          <div class="p-3 rounded-xl bg-[#0e111a] border border-white/[0.06] shadow-[inset_0_1px_0_rgba(255,255,255,0.03)]">
            <div class="text-[11px] text-neutral-400 font-medium flex items-center gap-1.5">
              <span>PC Workstation</span>
            </div>
            <div class="text-lg font-bold text-white font-mono mt-1">${{formatSecs(pcTotalSec)}}</div>
            <div class="text-[10px] text-neutral-500 font-mono mt-0.5">${{pcSessions.length}} sessions logged</div>
          </div>

          <div class="p-3 rounded-xl bg-[#0e111a] border border-white/[0.06] shadow-[inset_0_1px_0_rgba(255,255,255,0.03)]">
            <div class="text-[11px] text-neutral-400 font-medium flex items-center gap-1.5">
              <span>Mobile Smartphone</span>
            </div>
            <div class="text-lg font-bold text-white font-mono mt-1">${{formatSecs(mobTotalSec)}}</div>
            <div class="text-[10px] text-neutral-500 font-mono mt-0.5">${{mobSessions.length}} sessions logged</div>
          </div>

          <div class="p-3 rounded-xl bg-[#0e111a] border border-white/[0.06] shadow-[inset_0_1px_0_rgba(255,255,255,0.03)]">
            <div class="text-[11px] text-neutral-400 font-medium flex items-center gap-1.5">
              <span>Offline & Rest</span>
            </div>
            <div class="text-lg font-bold text-[#fb923c] font-mono mt-1">${{formatSecs(manTotalSec)}}</div>
            <div class="text-[10px] text-neutral-500 font-mono mt-0.5">${{manualSessions.length}} offline sessions</div>
          </div>

          <div class="p-3 rounded-xl bg-[#0e111a] border border-white/[0.06] shadow-[inset_0_1px_0_rgba(255,255,255,0.03)]">
            <div class="text-[11px] text-neutral-400 font-medium flex items-center gap-1.5">
              <span>Total Accounted</span>
            </div>
            <div class="text-lg font-bold text-white font-mono mt-1">${{formatSecs(totalAccounted)}}</div>
            <div class="text-[10px] text-neutral-500 font-mono mt-0.5">Unobserved: ${{formatSecs(unobservedSec)}}</div>
          </div>
        </div>
      `;
      container.appendChild(headerSection);

      // 2. Swimlane Graphic Canvas
      const swimlaneCard = document.createElement("div");
      swimlaneCard.className = "p-3 sm:p-4 rounded-xl bg-[#0c0e16] border border-white/[0.08] space-y-3";

      const selHourLeft = selectedHour !== null ? (selectedHour / 24) * 100 : 0;
      const selHourWidth = (1 / 24) * 100;

      let gridLinesHtml = "";
      for (let h = 0; h <= 24; h += 2) {{
        const leftPct = (h / 24) * 100;
        gridLinesHtml += `
          <div class="absolute top-0 bottom-0 border-l border-white/[0.05] pointer-events-none" style="left: ${{leftPct}}%;">
            <span class="absolute -top-5 -translate-x-1/2 text-[9px] font-mono text-neutral-500">${{String(h).padStart(2, "0")}}:00</span>
          </div>
        `;
      }}

      let pcBlocksHtml = pcSessions.map(s => {{
        const leftPct = Math.min(100, Math.max(0, (s.startSec / 86400) * 100));
        const widthPct = Math.min(100 - leftPct, Math.max(0.3, (s.duration / 86400) * 100));
        let col = "bg-[#38bdf8]";
        if (s.source === "vscode") col = "bg-[#fbbf24]";
        else if (s.source === "desktop") col = "bg-[#34d399]";
        const tooltip = `[${{s.source.toUpperCase()}}] ${{escapeHtml(s.title)}}\\n${{s.startStr}} - ${{s.endStr}} (${{formatSecs(s.duration)}})\\nClick to inspect hour`;
        return `<div onclick="selectHour(${{Math.floor(s.startSec / 3600)}}); event.stopPropagation();" class="absolute top-0.5 bottom-0.5 ${{col}} rounded-[2px] transition hover:brightness-125 cursor-pointer" style="left: ${{leftPct}}%; width: ${{widthPct}}%;" title="${{tooltip}}"></div>`;
      }}).join("");

      let mobBlocksHtml = mobSessions.map(s => {{
        const leftPct = Math.min(100, Math.max(0, (s.startSec / 86400) * 100));
        const widthPct = Math.min(100 - leftPct, Math.max(0.3, (s.duration / 86400) * 100));
        const tooltip = `[MOBILE] ${{escapeHtml(s.title)}}\\n${{s.startStr}} - ${{s.endStr}} (${{formatSecs(s.duration)}})\\nClick to inspect hour`;
        return `<div onclick="selectHour(${{Math.floor(s.startSec / 3600)}}); event.stopPropagation();" class="absolute top-0.5 bottom-0.5 bg-[#a78bfa] rounded-[2px] transition hover:brightness-125 cursor-pointer" style="left: ${{leftPct}}%; width: ${{widthPct}}%;" title="${{tooltip}}"></div>`;
      }}).join("");

      let manBlocksHtml = manualSessions.map(s => {{
        const leftPct = Math.min(100, Math.max(0, (s.startSec / 86400) * 100));
        const widthPct = Math.min(100 - leftPct, Math.max(0.3, (s.duration / 86400) * 100));
        const tooltip = `[OFFLINE] ${{escapeHtml(s.title)}}\\n${{s.startStr}} - ${{s.endStr}} (${{formatSecs(s.duration)}})\\nClick to inspect hour`;
        return `<div onclick="selectHour(${{Math.floor(s.startSec / 3600)}}); event.stopPropagation();" class="absolute top-0.5 bottom-0.5 bg-[#ea580c] rounded-[2px] transition hover:brightness-125 cursor-pointer" style="left: ${{leftPct}}%; width: ${{widthPct}}%;" title="${{tooltip}}"></div>`;
      }}).join("");

      let overlapBlocksHtml = rawOverlaps.map(ov => {{
        const leftPct = Math.min(100, Math.max(0, (ov.startSec / 86400) * 100));
        const widthPct = Math.min(100 - leftPct, Math.max(0.3, (ov.duration / 86400) * 100));
        const sTime = formatTimeOfDay(ov.startSec);
        const eTime = formatTimeOfDay(ov.endSec);
        const tooltip = `Co-Use: ${{escapeHtml(ov.pc.title)}} + ${{escapeHtml(ov.mob.title)}}\\n${{sTime}} - ${{eTime}} (${{formatSecs(ov.duration)}})\\nClick to inspect hour ${{ov.hour}}:00`;
        return `<div onclick="selectHour(${{ov.hour}}); event.stopPropagation();" class="absolute top-0.5 bottom-0.5 bg-[#fb7185] rounded-[2px] transition hover:brightness-125 cursor-pointer z-10" style="left: ${{leftPct}}%; width: ${{widthPct}}%;" title="${{tooltip}}"></div>`;
      }}).join("");

      swimlaneCard.innerHTML = `
        <div class="flex items-center justify-between text-xs pb-1">
          <span class="font-mono text-neutral-400">24-Hour Timeline Strip (Click any point to select hour)</span>
          <div class="flex items-center gap-3 text-[11px] font-mono text-neutral-400">
            <span class="inline-flex items-center gap-1"><span class="w-2 h-2 rounded-sm bg-[#38bdf8]"></span> Browser</span>
            <span class="inline-flex items-center gap-1"><span class="w-2 h-2 rounded-sm bg-[#fbbf24]"></span> VS Code</span>
            <span class="inline-flex items-center gap-1"><span class="w-2 h-2 rounded-sm bg-[#34d399]"></span> Desktop</span>
            <span class="inline-flex items-center gap-1"><span class="w-2 h-2 rounded-sm bg-[#a78bfa]"></span> Mobile</span>
            <span class="inline-flex items-center gap-1"><span class="w-2 h-2 rounded-sm bg-[#ea580c]"></span> Offline</span>
            <span class="inline-flex items-center gap-1 text-[#fda4af] font-medium"><span class="w-2 h-2 rounded-sm bg-[#fb7185]"></span> Co-Use</span>
          </div>
        </div>

        <div class="relative pt-6 pb-2 select-none" id="swimlane-tracks-wrapper">
          <div class="relative h-32 bg-[#090a0f] rounded-lg border border-white/[0.08] overflow-hidden cursor-crosshair" id="swimlane-canvas-box">
            ${{gridLinesHtml}}

            ${{selectedHour !== null ? `
              <div class="absolute top-0 bottom-0 bg-white/[0.06] border-x border-white/[0.14] pointer-events-none transition-all duration-200 z-0" style="left: ${{selHourLeft}}%; width: ${{selHourWidth}}%;">
                <span class="absolute bottom-1 left-1/2 -translate-x-1/2 text-[9px] font-mono text-white font-semibold bg-[#11141e]/90 px-1 rounded border border-white/[0.1]">${{String(selectedHour).padStart(2, "0")}}h</span>
              </div>
            ` : ''}}

            <!-- PC Track (Row 1) -->
            <div class="absolute left-0 right-0 top-1 h-6 border-b border-white/[0.05]">
              <span class="absolute left-2 top-0.5 text-[8px] font-mono text-neutral-400 uppercase tracking-wider font-bold z-20 pointer-events-none">PC Track</span>
              <div class="w-full h-full relative">
                ${{pcBlocksHtml}}
              </div>
            </div>

            <!-- Overlap / Co-Use Track (Row 2) -->
            <div class="absolute left-0 right-0 top-7 h-4 border-b border-white/[0.05] bg-[#0c0e16]/60">
              <span class="absolute left-2 top-0.5 text-[8px] font-mono text-[#fda4af] uppercase tracking-wider font-semibold z-20 pointer-events-none">Co-Use</span>
              <div class="w-full h-full relative">
                ${{overlapBlocksHtml}}
              </div>
            </div>

            <!-- Mobile Track (Row 3) -->
            <div class="absolute left-0 right-0 top-11 h-6 border-b border-white/[0.05]">
              <span class="absolute left-2 top-0.5 text-[8px] font-mono text-[#c4b5fd] uppercase tracking-wider font-semibold z-20 pointer-events-none">Mobile Track</span>
              <div class="w-full h-full relative">
                ${{mobBlocksHtml}}
              </div>
            </div>

            <!-- Offline / Rest Track (Row 4) -->
            <div class="absolute left-0 right-0 top-[69px] h-6">
              <span class="absolute left-2 top-0.5 text-[8px] font-mono text-[#fb923c] uppercase tracking-wider font-semibold z-20 pointer-events-none">Offline / Rest</span>
              <div class="w-full h-full relative">
                ${{manBlocksHtml}}
              </div>
            </div>
          </div>
        </div>
      `;

      setTimeout(() => {{
        const box = document.getElementById("swimlane-canvas-box");
        if (box) {{
          box.onclick = (e) => {{
            const rect = box.getBoundingClientRect();
            const clickX = e.clientX - rect.left;
            const pct = Math.max(0, Math.min(1, clickX / rect.width));
            const pickedHour = Math.min(23, Math.floor(pct * 24));
            selectHour(pickedHour);
          }};
        }}
      }}, 50);

      container.appendChild(swimlaneCard);

      // 3. Concurrent Multitasking (Co-Use Sessions) Log
      const overlapsCard = document.createElement("div");
      overlapsCard.className = "p-3 sm:p-4 rounded-xl bg-[#0c0e16] border border-white/[0.08] space-y-3";
      
      if (rawOverlaps.length === 0) {{
        overlapsCard.innerHTML = `
          <div class="flex items-center gap-2 pb-1 border-b border-white/[0.08]">
            <span class="text-sm font-semibold text-white">Concurrent Multitasking (Co-Use Sessions)</span>
            <span class="px-2 py-0.5 rounded text-[11px] font-mono bg-white/[0.04] text-neutral-400 border border-white/[0.08]">0 Overlaps</span>
          </div>
          <div class="py-6 text-center text-xs text-neutral-500 font-mono space-y-1">
            <div>No concurrent PC and Mobile sessions detected today.</div>
            <div class="text-[11px] text-neutral-600">Workstation and phone were used at distinct, non-overlapping intervals.</div>
          </div>
        `;
      }} else {{
        let listRowsHtml = rawOverlaps.map((ov, idx) => {{
          const pcSrc = ov.pc.source;
          let pcBadge = "bg-[#38bdf8]/10 text-[#7dd3fc] border-[#38bdf8]/20";
          if (pcSrc === "vscode") pcBadge = "bg-[#fbbf24]/10 text-[#fde047] border-[#fbbf24]/20";
          else if (pcSrc === "desktop") pcBadge = "bg-[#34d399]/10 text-[#6ee7b7] border-[#34d399]/20";

          const sTime = formatTimeOfDay(ov.startSec);
          const eTime = formatTimeOfDay(ov.endSec);

          return `
            <div class="p-2.5 rounded-lg bg-[#0e111a] border border-white/[0.06] hover:bg-[#141824] hover:border-white/[0.12] transition flex flex-col sm:flex-row sm:items-center justify-between gap-3 text-xs">
              <div class="flex items-start sm:items-center gap-2.5 min-w-0 flex-1">
                <span class="font-mono text-neutral-500 font-bold text-xs w-5 shrink-0 pt-0.5 sm:pt-0">${{idx + 1}}.</span>
                <span class="px-2 py-0.5 rounded text-[11px] font-mono font-medium bg-[#fb7185]/10 text-[#fda4af] border border-[#fb7185]/20 shrink-0">
                  ${{formatSecs(ov.duration)}}
                </span>
                <div class="min-w-0 flex-1 space-y-1">
                  <!-- PC Activity -->
                  <div class="flex items-center gap-1.5 truncate">
                    <span class="text-[10px] font-mono px-1 py-0.2 rounded border uppercase font-medium ${{pcBadge}} shrink-0">${{pcSrc}}</span>
                    <span class="font-medium text-white truncate" title="${{escapeHtml(ov.pc.title)}}">${{escapeHtml(ov.pc.title)}}</span>
                  </div>
                  <!-- Mobile Activity -->
                  <div class="flex items-center gap-1.5 truncate">
                    <span class="text-[10px] font-mono px-1 py-0.2 rounded border uppercase font-medium bg-[#a78bfa]/10 text-[#c4b5fd] border-[#a78bfa]/20 shrink-0">mobile</span>
                    <span class="font-medium text-neutral-300 truncate" title="${{escapeHtml(ov.mob.title)}}">${{escapeHtml(ov.mob.title)}}</span>
                  </div>
                </div>
              </div>

              <div class="flex items-center gap-2 shrink-0 self-end sm:self-auto font-mono text-xs">
                <span class="text-neutral-400">${{sTime}} &ndash; ${{eTime}}</span>
                <button onclick="selectHour(${{ov.hour}}); setHourlyViewMode('inspector');" class="px-2 py-1 rounded bg-white/[0.06] hover:bg-white/[0.1] text-neutral-300 border border-white/[0.08] transition text-[11px]" title="Inspect hour ${{String(ov.hour).padStart(2, '0')}}:00">
                  Hour ${{String(ov.hour).padStart(2, "0")}}:00 &rarr;
                </button>
              </div>
            </div>
          `;
        }}).join("");

        overlapsCard.innerHTML = `
          <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-2 pb-2 border-b border-white/[0.08]">
            <div class="flex items-center gap-2">
              <span class="text-sm font-semibold text-white">Concurrent Multitasking (Co-Use Sessions)</span>
              <span class="px-2 py-0.5 rounded text-[11px] font-mono bg-[#fb7185]/10 text-[#fda4af] border border-[#fb7185]/20 font-medium">
                ${{rawOverlaps.length}} co-use intervals (${{formatSecs(totalCoUseSec)}})
              </span>
            </div>
            <div class="text-xs text-neutral-400 font-mono">
              Instances where PC Workstation and Smartphone were used simultaneously
            </div>
          </div>

          <div class="max-h-[360px] overflow-y-auto custom-scroll space-y-2 pt-1">
            ${{listRowsHtml}}
          </div>
        `;
      }}

      container.appendChild(overlapsCard);
    }}

    function setHourlyViewMode(mode) {{
      hourlyViewMode = mode;
      const inspectorView = document.getElementById("hourly-inspector-container");
      const duallaneView = document.getElementById("hourly-duallane-container");
      const scheduleView = document.getElementById("hourly-schedule-container");
      const btnInspector = document.getElementById("btn-mode-inspector");
      const btnDuallane = document.getElementById("btn-mode-duallane");
      const btnSchedule = document.getElementById("btn-mode-schedule");

      if (inspectorView) inspectorView.classList.add("hidden");
      if (duallaneView) duallaneView.classList.add("hidden");
      if (scheduleView) scheduleView.classList.add("hidden");

      [btnInspector, btnDuallane, btnSchedule].forEach(btn => {{
        if (btn) btn.className = "px-2.5 py-1 rounded-md text-neutral-400 hover:text-white transition";
      }});

      if (mode === "inspector") {{
        if (inspectorView) inspectorView.classList.remove("hidden");
        if (btnInspector) btnInspector.className = "px-2.5 py-1 rounded-md bg-white/[0.08] text-white border border-white/[0.14] transition";
      }} else if (mode === "duallane") {{
        if (duallaneView) duallaneView.classList.remove("hidden");
        if (btnDuallane) btnDuallane.className = "px-2.5 py-1 rounded-md bg-white/[0.08] text-white border border-white/[0.14] transition";
      }} else {{ // 'schedule'
        if (scheduleView) scheduleView.classList.remove("hidden");
        if (btnSchedule) btnSchedule.className = "px-2.5 py-1 rounded-md bg-white/[0.08] text-white border border-white/[0.14] transition";
      }}
    }}

    function selectHour(h) {{
      selectedHour = h;
      if (hourlyViewMode === 'schedule') {{
        expandedScheduleHour = h;
      }}
      if (window.CURRENT_HOURLY_DATA) {{
        renderHourlyRhythmBars(window.CURRENT_HOURLY_DATA);
        renderHourlyInspector(window.CURRENT_HOURLY_DATA);
        renderDualLaneSwimlane();
        renderHourlySchedule(window.CURRENT_HOURLY_DATA);
      }}
    }}

    function toggleHourFilter(h) {{
      if (activeHourFilter === h) {{
        activeHourFilter = null;
      }} else {{
        activeHourFilter = h;
        setActiveTab("sessions");
      }}
      renderHourlyExplorer();
      renderLedger(REPORTS_DATABASE[currentDate]?.timeline || []);
      const ledgerSec = document.getElementById("analytics-ledger-section");
      if (ledgerSec && activeHourFilter !== null) {{
        ledgerSec.scrollIntoView({{ behavior: 'smooth' }});
      }}
    }}

    function renderCombinedTitles(timeline) {{
      const container = document.getElementById("combined-titles-list");
      const badge = document.getElementById("titles-count-badge");
      if (!container) return;
      container.innerHTML = "";

      const titleMap = new Map();
      let totalActiveSec = 0;

      (timeline || []).forEach(item => {{
        if (item.source === "manual") return;
        const dur = item.duration_seconds || 0;
        totalActiveSec += dur;

        let title = item.context?.title || item.context?.activity || item.context?.app || item.context?.domain || item.source;
        if (!title || !title.trim()) return;
        title = title.trim();

        const sub = item.context?.domain || item.context?.package || item.context?.workspace || item.context?.category || "";
        const src = item.source || "screen";

        if (!titleMap.has(title)) {{
          titleMap.set(title, {{
            title: title,
            duration: 0,
            count: 0,
            source: src,
            subtitle: sub
          }});
        }}

        const entry = titleMap.get(title);
        entry.duration += dur;
        entry.count += 1;
        if (!entry.subtitle && sub) entry.subtitle = sub;
      }});

      const list = Array.from(titleMap.values()).sort((a, b) => b.duration - a.duration);
      if (badge) badge.textContent = `${{list.length}} titles`;

      if (list.length === 0) {{
        container.innerHTML = '<div class="text-xs text-neutral-500 py-2">No screen activity recorded</div>';
        return;
      }}

      const maxDur = list[0].duration;

      list.slice(0, 10).forEach((t, idx) => {{
        let colorClass = "bg-[#38bdf8]/10 text-[#7dd3fc] border-[#38bdf8]/20";
        let barColor = "bg-[#38bdf8]";
        if (t.source === "mobile") {{
          colorClass = "bg-[#a78bfa]/10 text-[#c4b5fd] border-[#a78bfa]/20";
          barColor = "bg-[#a78bfa]";
        }} else if (t.source === "desktop") {{
          colorClass = "bg-[#34d399]/10 text-[#6ee7b7] border-[#34d399]/20";
          barColor = "bg-[#34d399]";
        }} else if (t.source === "vscode") {{
          colorClass = "bg-[#fbbf24]/10 text-[#fde047] border-[#fbbf24]/20";
          barColor = "bg-[#fbbf24]";
        }}

        const pct = totalActiveSec > 0 ? ((t.duration / totalActiveSec) * 100).toFixed(1) : 0;
        const barWidth = maxDur > 0 ? Math.min(100, Math.max(2, (t.duration / maxDur) * 100)) : 0;

        const card = document.createElement("div");
        card.className = "p-2.5 rounded-xl bg-[#0e111a] border border-white/[0.06] hover:bg-[#141824] hover:border-white/[0.12] transition space-y-1.5 text-xs";
        card.innerHTML = `
          <div class="flex items-center justify-between gap-2">
            <div class="flex items-center gap-2 min-w-0">
              <span class="font-mono text-neutral-500 text-xs font-bold w-4 shrink-0">${{idx + 1}}.</span>
              <div class="min-w-0">
                <div class="font-medium text-white truncate max-w-[200px] sm:max-w-[280px]" title="${{escapeHtml(t.title)}}">${{escapeHtml(t.title)}}</div>
                <div class="text-[10px] text-neutral-400 flex items-center gap-1.5 mt-0.5">
                  <span class="px-1.5 py-0.2 rounded border ${{colorClass}} text-[9px] font-semibold">${{t.source}}</span>
                  ${{t.subtitle ? `<span class="truncate max-w-[140px] font-mono text-slate-500">${{escapeHtml(t.subtitle)}}</span>` : ''}}
                  <span class="text-neutral-500">&bull;</span>
                  <span class="font-mono text-slate-400">${{t.count}} sess</span>
                </div>
              </div>
            </div>
            <div class="text-right shrink-0">
              <div class="font-mono font-bold text-white text-xs">${{formatSecs(t.duration)}}</div>
              <div class="text-[10px] font-mono text-neutral-500">${{pct}}%</div>
            </div>
          </div>
          <div class="w-full bg-[#090a0f] h-1 rounded-full overflow-hidden border border-white/[0.04]">
            <div class="${{barColor}} h-full rounded-full transition-all duration-500" style="width: ${{barWidth}}%"></div>
          </div>
        `;
        container.appendChild(card);
      }});
    }}

    function renderLongestSessions(sessions) {{
      const container = document.getElementById("longest-sessions-list");
      if (!container) return;
      container.innerHTML = "";
      
      const activeSessions = (sessions || []).filter(s => s.source !== "manual");
      if (activeSessions.length === 0) {{
        container.innerHTML = '<div class="text-xs text-neutral-500 py-2">No screen sessions recorded</div>';
        return;
      }}

      activeSessions.slice(0, 5).forEach((sess, idx) => {{
        const title = sess.context?.activity || sess.context?.title || sess.context?.app || sess.context?.domain || sess.source;
        const card = document.createElement("div");
        card.className = "p-2.5 rounded-xl bg-[#0e111a] border border-white/[0.06] hover:bg-[#141824] hover:border-white/[0.12] transition flex items-center justify-between gap-3 text-xs";
        
        let colorClass = "bg-[#38bdf8]/10 text-[#7dd3fc] border-[#38bdf8]/20";
        if (sess.source === "mobile") colorClass = "bg-[#a78bfa]/10 text-[#c4b5fd] border-[#a78bfa]/20";
        else if (sess.source === "desktop") colorClass = "bg-[#34d399]/10 text-[#6ee7b7] border-[#34d399]/20";
        else if (sess.source === "vscode") colorClass = "bg-[#fbbf24]/10 text-[#fde047] border-[#fbbf24]/20";

        card.innerHTML = `
          <div class="flex items-center gap-2.5 min-w-0">
            <span class="font-mono text-neutral-500 text-xs font-bold w-4">${{idx + 1}}.</span>
            <div class="min-w-0">
              <div class="font-medium text-white truncate max-w-[200px] sm:max-w-[260px]" title="${{escapeHtml(title)}}">${{escapeHtml(title)}}</div>
              <div class="text-[11px] text-neutral-400 flex items-center gap-1.5 mt-0.5">
                <span class="px-1.5 py-0.2 rounded border ${{colorClass}} text-[10px] font-semibold">${{sess.source}}</span>
                <span>${{parseTimeOnly(sess.start)}} &ndash; ${{parseTimeOnly(sess.end)}}</span>
              </div>
            </div>
          </div>
          <span class="font-mono font-bold text-white shrink-0 bg-white/[0.04] px-2 py-0.5 rounded border border-white/[0.08]">${{formatSecs(sess.duration_seconds)}}</span>
        `;
        container.appendChild(card);
      }});
    }}

    function renderDomains(domains) {{
      const container = document.getElementById("domains-list");
      container.innerHTML = "";
      document.getElementById("domains-count-badge").textContent = `${{domains.length}} domains`;
      
      if (!domains || domains.length === 0) {{
        container.innerHTML = '<div class="text-xs text-neutral-500">No browser domain activity</div>';
        return;
      }}

      domains.slice(0, 10).forEach(d => {{
        const row = document.createElement("div");
        row.className = "space-y-1.5 p-2 rounded-lg bg-[#0e111a] border border-white/[0.04]";
        row.innerHTML = `
          <div class="flex justify-between items-center text-xs">
            <span class="font-medium text-neutral-200 truncate max-w-[200px]" title="${{d.domain}}">${{d.domain}}</span>
            <span class="font-mono text-neutral-300">${{formatSecs(d.duration_seconds)}} <span class="text-neutral-500 font-normal">(${{d.percentage}}%)</span></span>
          </div>
          <div class="w-full bg-[#090a0f] h-1.5 rounded-full overflow-hidden border border-white/[0.04]">
            <div class="bg-[#38bdf8] h-full rounded-full transition-all duration-500" style="width: ${{Math.min(100, d.percentage)}}%"></div>
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
        container.innerHTML = '<div class="text-xs text-neutral-500">No mobile app activity</div>';
        return;
      }}

      apps.slice(0, 10).forEach(a => {{
        const row = document.createElement("div");
        row.className = "space-y-1.5 p-2 rounded-lg bg-[#0e111a] border border-white/[0.04]";
        row.innerHTML = `
          <div class="flex justify-between items-center text-xs">
            <div class="flex items-center gap-1.5 min-w-0">
              <span class="font-medium text-neutral-200 truncate max-w-[170px]">${{a.app}}</span>
            </div>
            <span class="font-mono text-neutral-300">${{formatSecs(a.duration_seconds)}} <span class="text-neutral-500 font-normal">(${{a.percentage}}%)</span></span>
          </div>
          <div class="w-full bg-[#090a0f] h-1.5 rounded-full overflow-hidden border border-white/[0.04]">
            <div class="bg-[#a78bfa] h-full rounded-full transition-all duration-500" style="width: ${{Math.min(100, a.percentage)}}%"></div>
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
        container.innerHTML = '<div class="text-xs text-neutral-500">No desktop app activity</div>';
        return;
      }}

      apps.slice(0, 10).forEach(a => {{
        const row = document.createElement("div");
        row.className = "space-y-1.5 p-2 rounded-lg bg-[#0e111a] border border-white/[0.04]";
        row.innerHTML = `
          <div class="flex justify-between items-center text-xs">
            <span class="font-medium text-neutral-200 truncate max-w-[180px]">${{a.app}}</span>
            <span class="font-mono text-neutral-300">${{formatSecs(a.duration_seconds)}} <span class="text-neutral-500 font-normal">(${{a.percentage}}%)</span></span>
          </div>
          <div class="w-full bg-[#090a0f] h-1.5 rounded-full overflow-hidden border border-white/[0.04]">
            <div class="bg-[#34d399] h-full rounded-full transition-all duration-500" style="width: ${{Math.min(100, a.percentage)}}%"></div>
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
            <button onclick="toggleHourFilter(${{activeHourFilter}})" class="hover:text-white font-bold text-neutral-400">&times;</button>
          `;
        }} else {{
          filterPill.classList.add("hidden");
        }}
      }}

      if (filtered.length === 0) {{
        container.innerHTML = '<div class="p-6 text-center text-xs text-neutral-500">No matching activity records found.</div>';
        return;
      }}

      filtered.slice().reverse().forEach(item => {{
        const row = document.createElement("div");
        row.className = "p-3 sm:px-4 hover:bg-white/[0.02] transition flex flex-col sm:flex-row sm:items-center justify-between gap-2 text-xs border-b border-white/[0.04] last:border-0";

        const title = item.context?.activity || item.context?.title || item.context?.app || item.context?.domain || item.source;
        const sub = item.context?.category || item.context?.domain || item.context?.package || item.context?.workspace || "";

        let sourceBadge = `<span class="px-2 py-0.5 rounded text-[10px] font-mono font-semibold bg-[#38bdf8]/10 text-[#7dd3fc] border border-[#38bdf8]/20">Browser</span>`;
        if (item.source === "mobile") {{
          sourceBadge = `<span class="px-2 py-0.5 rounded text-[10px] font-mono font-semibold bg-[#a78bfa]/10 text-[#c4b5fd] border border-[#a78bfa]/20">Mobile</span>`;
        }} else if (item.source === "desktop") {{
          sourceBadge = `<span class="px-2 py-0.5 rounded text-[10px] font-mono font-semibold bg-[#34d399]/10 text-[#6ee7b7] border border-[#34d399]/20">Desktop</span>`;
        }} else if (item.source === "vscode") {{
          sourceBadge = `<span class="px-2 py-0.5 rounded text-[10px] font-mono font-semibold bg-[#fbbf24]/10 text-[#fde047] border border-[#fbbf24]/20">VS Code</span>`;
        }} else if (item.source === "manual") {{
          sourceBadge = `<span class="px-2 py-0.5 rounded text-[10px] font-mono font-semibold bg-[#f97316]/10 text-[#fb923c] border border-[#f97316]/20">Offline</span>`;
        }}

        row.innerHTML = `
          <div class="flex items-center gap-3 min-w-0">
            <span class="font-mono text-neutral-400 text-[11px] shrink-0 w-24">${{parseTimeOnly(item.start)}} &ndash; ${{parseTimeOnly(item.end)}}</span>
            ${{sourceBadge}}
            <div class="min-w-0">
              <div class="font-medium text-white truncate max-w-sm sm:max-w-md md:max-w-xl" title="${{title}}">${{title}}</div>
              ${{sub ? `<div class="text-[11px] text-neutral-400 truncate max-w-sm">${{sub}}</div>` : ''}}
            </div>
          </div>
          <span class="font-mono font-semibold text-neutral-200 self-end sm:self-auto shrink-0 bg-white/[0.04] px-2 py-0.5 rounded border border-white/[0.08]">${{formatSecs(item.duration_seconds)}}</span>
        `;
        container.appendChild(row);
      }});
    }}

    // Filter tabs handlers
    document.querySelectorAll(".filter-btn").forEach(btn => {{
      btn.onclick = () => {{
        document.querySelectorAll(".filter-btn").forEach(b => {{
          b.className = "filter-btn px-2.5 py-1 rounded-md text-neutral-400 hover:text-white transition text-xs";
        }});
        btn.className = "filter-btn px-2.5 py-1 rounded-md bg-white/[0.08] text-white border border-white/[0.14] transition text-xs";
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
            onDateChange(d);
          }} catch(err) {{
            alert("Could not parse JSON report file: " + err.message);
          }}
        }} else if (file.name.endsWith(".md")) {{
          const d = file.name.replace(".md", "");
          ANALYSES_DATABASE[d] = text;
          onDateChange(d);
        }}
      }};
      reader.readAsText(file);
    }};

    function showToast(message, isError = false) {{
      const toast = document.getElementById("toast-notification");
      if (!toast) return;
      toast.textContent = message;
      if (isError) {{
        toast.className = "fixed bottom-5 right-5 z-50 px-4 py-2.5 rounded-lg text-xs font-mono shadow-2xl border bg-[#fb7185]/10 text-[#fda4af] border-[#fb7185]/30 translate-y-0 opacity-100 transition-all duration-200";
      }} else {{
        toast.className = "fixed bottom-5 right-5 z-50 px-4 py-2.5 rounded-lg text-xs font-mono shadow-2xl border bg-[#34d399]/10 text-[#6ee7b7] border-[#34d399]/30 translate-y-0 opacity-100 transition-all duration-200";
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
          headers: getCollectorHeaders(),
          body: JSON.stringify({{ date: currentDate }})
        }});
        const res = await resp.json();
        if (resp.ok && res.status === "ok") {{
          showToast(res.message || "Mobile sync complete!");
          if (res.report && res.report.date) {{
            REPORTS_DATABASE[res.report.date] = res.report;
            onDateChange(res.report.date);
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
      const localToday = new Date().toLocaleDateString('en-CA');
      const targetDate = currentDate || localToday;

      try {{
        btn.disabled = true;
        text.textContent = "Generating...";
        const resp = await fetch("http://127.0.0.1:8765/api/generate-report", {{
          method: "POST",
          headers: getCollectorHeaders(),
          body: JSON.stringify({{ date: targetDate, today: localToday }})
        }});
        const res = await resp.json();
        if (resp.ok && res.status === "ok") {{
          showToast(res.message || `Report updated for ${{res.date}}!`);
          if (res.report && res.report.date) {{
            REPORTS_DATABASE[res.report.date] = res.report;
          }}
          if (res.today_report && res.today_report.date) {{
            REPORTS_DATABASE[res.today_report.date] = res.today_report;
          }}
          if (targetDate === localToday || !REPORTS_DATABASE[currentDate]) {{
            currentDate = res.report?.date || localToday;
          }}
          onDateChange(currentDate);
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

    // Initialization: restore state from URL hash or sessionStorage
    let restoredDate = null;
    let restoredTab = null;

    const hashStr = (window.location.hash || "").replace(/^#/, "");
    if (hashStr) {{
      const params = new URLSearchParams(hashStr);
      if (params.get("date")) restoredDate = params.get("date");
      if (params.get("tab")) restoredTab = params.get("tab");
    }}

    if (!restoredDate) {{
      try {{
        restoredDate = sessionStorage.getItem("dashboard_active_date");
      }} catch (e) {{}}
    }}
    if (!restoredTab) {{
      try {{
        restoredTab = sessionStorage.getItem("dashboard_active_tab");
      }} catch (e) {{}}
    }}

    const localToday = new Date().toLocaleDateString('en-CA');
    const validDates = getAllDatesList();

    if (restoredDate && (validDates.includes(restoredDate) || REPORTS_DATABASE[restoredDate] || ANALYSES_DATABASE[restoredDate])) {{
      currentDate = restoredDate;
    }} else if (REPORTS_DATABASE[localToday]) {{
      currentDate = localToday;
    }}

    const validTabs = ["overview", "analytics", "sessions", "journal"];
    if (restoredTab && validTabs.includes(restoredTab)) {{
      activeMainTab = restoredTab;
    }}

    initDateButtons();
    renderAll();
    renderCalendarHeatmap();
    setActiveTab(activeMainTab);

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

    today_str = datetime.now().strftime("%Y-%m-%d")
    if today_str not in reports_data:
        try:
            from collector.config import get_config
            from reporting.generate_report import generate_single_day_report, write_report
            cfg = get_config()
            today_report = generate_single_day_report(cfg, today_str)
            write_report(cfg, today_report, f"{today_str}.json")
            reports_data[today_str] = today_report
            print(f"Auto-created new day report file for: {today_str}")
        except Exception as e:
            print(f"Notice: Could not auto-generate new day report for {today_str}: {e}", file=sys.stderr)

    all_dates = sorted(set(list(reports_data.keys()) + list(analyses_data.keys())))
    if not all_dates:
        print("No reports or analysis files found.", file=sys.stderr)
        return False

    latest_date = today_str if today_str in reports_data else all_dates[-1]
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
