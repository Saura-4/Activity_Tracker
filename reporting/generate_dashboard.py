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

from reporting.generate_report import strip_labels_block

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
    cleaned_analyses_data = {d_k: strip_labels_block(md_t) for d_k, md_t in analyses_data.items()}
    reports_json = json.dumps(reports_data)
    analyses_json = json.dumps(cleaned_analyses_data)
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
        for d_key, md_text in cleaned_analyses_data.items():
            analyses_html_data[d_key] = md_parser.render(md_text)
    except Exception as e:
        print(f"Notice: Markdown pre-rendering skipped: {e}", file=sys.stderr)
        
    analyses_html_json = json.dumps(analyses_html_data)
    
    template_path = Path(__file__).resolve().parent / "dashboard_template.html"
    with open(template_path, "r", encoding="utf-8") as f:
        template = f.read()

    # Simple placeholder substitution (no f-string brace escaping)
    html = (
        template
        .replace("{{REPORTS_JSON}}", reports_json)
        .replace("{{ANALYSES_JSON}}", analyses_json)
        .replace("{{ANALYSES_HTML_JSON}}", analyses_html_json)
        .replace("{{AUTH_TOKEN_JSON}}", auth_token_json)
        .replace("{{INITIAL_DATE}}", initial_date)
    )
    return html

def generate_dashboard_files(data_dir_str: Any = "Record", output_str: str = "Record/report/dashboard.html") -> bool:
    if hasattr(data_dir_str, "data_directory"):
        data_dir_str = data_dir_str.data_directory
    data_dir = Path(data_dir_str)
    if not data_dir.is_absolute():
        data_dir = Path(__file__).resolve().parent.parent.parent / data_dir_str

    if not data_dir.exists():
        print(f"Data directory not found: {data_dir}", file=sys.stderr)
        return False

    reports_data = {}
    report_candidates = list(data_dir.glob("report/**/daily/*.json"))

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

    print(f"Dashboard successfully generated at: {out_path}")
    return True

def main():
    parser = argparse.ArgumentParser(description="Generate interactive HTML dashboard from reports and analyses")
    parser.add_argument("--data-dir", type=str, default="Record", help="Root data directory containing report/ and analysis/")
    parser.add_argument("--output", type=str, default="Record/report/dashboard.html", help="Output HTML file path")
    args = parser.parse_args()

    success = generate_dashboard_files(args.data_dir, args.output)
    if not success:
        sys.exit(1)

if __name__ == "__main__":
    main()
