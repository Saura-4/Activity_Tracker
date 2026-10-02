import logging
import sys
import os
import dataclasses
from aiohttp import web

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from collector.config import get_config
from collector.models import validate_and_create_event
from collector.storage import append_event

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

config = get_config()

import fnmatch

def cors_headers(request=None):
    if getattr(config, "cors_origins", None):
        allowed_patterns = list(config.cors_origins)
    else:
        allowed_patterns = [
            "chrome-extension://*",
            "moz-extension://*",
            "vscode-webview://*",
            "null",
        ]

    # Allow localhost origins only when auth_token is set (null origin allowed for local dashboard file)
    if getattr(config, "auth_token", None):
        for origin_pat in ("http://localhost:*", "http://127.0.0.1:*", "null"):
            if origin_pat not in allowed_patterns:
                allowed_patterns.append(origin_pat)
    else:
        allowed_patterns = [
            pat for pat in allowed_patterns
            if pat not in ("http://localhost:*", "http://127.0.0.1:*")
        ]
        if "null" not in allowed_patterns:
            allowed_patterns.append("null")

    origin = request.headers.get("Origin", "") if request else ""
    matched_origin = None
    if origin:
        for pat in allowed_patterns:
            if fnmatch.fnmatch(origin, pat):
                matched_origin = origin
                break

    h = {
        'Access-Control-Allow-Methods': 'POST, GET, OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-Auth-Token'
    }
    if matched_origin:
        h['Access-Control-Allow-Origin'] = matched_origin
    return h

@web.middleware
async def auth_and_cors_middleware(request, handler):
    # Handle preflight OPTIONS
    if request.method == "OPTIONS":
        return web.Response(status=204, headers=cors_headers(request))

    # Health check is public
    if request.path == "/health":
        resp = await handler(request)
        for k, v in cors_headers(request).items():
            if k not in resp.headers:
                resp.headers[k] = v
        return resp

    # Validate auth token if configured
    auth_token = getattr(config, "auth_token", None)
    if auth_token:
        req_token = None
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            req_token = auth_header[7:].strip()
        elif auth_header:
            req_token = auth_header.strip()
        if not req_token:
            req_token = request.headers.get("X-Auth-Token", "")
        if not req_token:
            req_token = request.query.get("token", "")

        if req_token != auth_token:
            return web.json_response(
                {"status": "error", "message": "Unauthorized"},
                status=401,
                headers=cors_headers(request)
            )

    resp = await handler(request)
    for k, v in cors_headers(request).items():
        if k not in resp.headers:
            resp.headers[k] = v
    return resp

async def handle_options(request):
    return web.Response(status=204, headers=cors_headers(request))

async def handle_health(request):
    return web.json_response({"status": "ok"}, headers=cors_headers())

async def handle_config(request):
    cfg_dict = dataclasses.asdict(config)
    if cfg_dict.get("auth_token"):
        cfg_dict["auth_token"] = "***REDACTED***"
    return web.json_response(cfg_dict, headers=cors_headers(request))

async def process_single_event(data):
    event = validate_and_create_event(data, config.strip_query_strings)
    raw_min_dur = getattr(config, "raw_min_duration_seconds", 2.0)
    if event.duration_seconds < raw_min_dur:
        logger.debug(f"Event dropped (duration {event.duration_seconds}s < {raw_min_dur}s): {event.source}")
        return {"status": "ignored", "reason": "duration_below_threshold", "id": event.id}

    evt_dict = dataclasses.asdict(event)
    is_new = append_event(config, evt_dict)
    
    if is_new:
        ctx_info = ""
        if event.source == "browser":
            ctx_info = event.context.get("domain", "")
        elif event.source == "vscode":
            ctx_info = event.context.get("workspace", "")
        elif event.source == "mobile":
            ctx_info = event.context.get("app", "")
        elif event.source == "desktop":
            ctx_info = f"{event.context.get('app', '')} - {event.context.get('title', '')[:35]}"
        logger.info(f"Event: {event.source} | {ctx_info}")
        
    return {"status": "ok", "id": event.id}

async def handle_event(request):
    try:
        data = await request.json()
        result = await process_single_event(data)
        return web.json_response(result, headers=cors_headers())
    except Exception as e:
        logger.error(f"Error processing event: {e}")
        return web.json_response({"status": "error", "message": str(e)}, status=400, headers=cors_headers())

async def handle_events(request):
    try:
        data = await request.json()
        if not isinstance(data, list):
            raise ValueError("Expected list of events")
            
        results = []
        for item in data:
            try:
                res = await process_single_event(item)
                results.append(res)
            except Exception as e:
                results.append({"status": "error", "message": str(e)})
                
        return web.json_response({"status": "ok", "results": results}, headers=cors_headers())
    except Exception as e:
        logger.error(f"Error processing events: {e}")
        return web.json_response({"status": "error", "message": str(e)}, status=400, headers=cors_headers())

async def handle_sync_mobile(request):
    try:
        data = {}
        if request.can_read_body:
            try:
                data = await request.json()
            except Exception:
                pass
        target_date = data.get("date")
        
        import asyncio
        import importlib
        from datetime import datetime
        from collector.android_collector import sync_mobile_activity
        import reporting.generate_report
        import reporting.generate_dashboard
        importlib.reload(reporting.generate_report)
        importlib.reload(reporting.generate_dashboard)
        from reporting.generate_report import generate_single_day_report, write_report
        from reporting.generate_dashboard import generate_dashboard_files

        # Run ADB sync in thread pool to prevent blocking aiohttp event loop
        sync_res = await asyncio.to_thread(sync_mobile_activity, target_date=target_date)

        # Auto-regenerate report for that date and today
        today_date = datetime.now().strftime("%Y-%m-%d")
        actual_date = target_date or today_date
        report = await asyncio.to_thread(generate_single_day_report, config, actual_date)
        await asyncio.to_thread(write_report, config, report, f"{actual_date}.json")
        
        today_report = None
        if actual_date != today_date:
            today_report = await asyncio.to_thread(generate_single_day_report, config, today_date)
            await asyncio.to_thread(write_report, config, today_report, f"{today_date}.json")

        # Regenerate dashboard HTML
        await asyncio.to_thread(generate_dashboard_files, config.data_directory)

        return web.json_response({
            "status": "ok",
            "message": f"Mobile synced: {sync_res.get('total_sessions', 0)} sessions",
            "sync_result": sync_res,
            "report": report,
            "today_report": today_report
        }, headers=cors_headers())
    except Exception as e:
        logger.error(f"Error in handle_sync_mobile: {e}")
        return web.json_response({
            "status": "error",
            "message": str(e)
        }, status=500, headers=cors_headers())

async def handle_generate_report(request):
    try:
        data = {}
        if request.can_read_body:
            try:
                data = await request.json()
            except Exception:
                pass
        import asyncio
        import importlib
        from datetime import datetime
        import reporting.generate_report
        import reporting.generate_dashboard
        importlib.reload(reporting.generate_report)
        importlib.reload(reporting.generate_dashboard)
        from reporting.generate_report import generate_single_day_report, write_report
        from reporting.generate_dashboard import generate_dashboard_files

        today_date = datetime.now().strftime("%Y-%m-%d")
        target_date = data.get("date") or today_date
        if target_date == "today":
            target_date = today_date

        report = await asyncio.to_thread(generate_single_day_report, config, target_date)
        await asyncio.to_thread(write_report, config, report, f"{target_date}.json")

        today_report = None
        # On a new day, if user generated an older day, also ensure today's file is automatically created
        if target_date != today_date:
            today_report = await asyncio.to_thread(generate_single_day_report, config, today_date)
            await asyncio.to_thread(write_report, config, today_report, f"{today_date}.json")

        await asyncio.to_thread(generate_dashboard_files, config.data_directory)

        return web.json_response({
            "status": "ok",
            "message": f"Report generated for {target_date}" + (f" and {today_date}" if today_report else ""),
            "date": target_date,
            "today": today_date,
            "report": report,
            "today_report": today_report
        }, headers=cors_headers())
    except Exception as e:
        logger.error(f"Error in handle_generate_report: {e}")
        return web.json_response({
            "status": "error",
            "message": str(e)
        }, status=500, headers=cors_headers())

async def handle_manual_event(request):
    try:
        data = await request.json()
        from datetime import datetime
        date_str = data.get("date") or datetime.now().strftime("%Y-%m-%d")
        start_time = data.get("start")
        end_time = data.get("end")
        activity = data.get("activity") or data.get("title")
        category = data.get("category")
        notes = data.get("notes", "")

        if not start_time or not end_time or not activity:
            raise ValueError("Required fields: 'start', 'end', 'activity' (or 'title')")

        from collector.manual_storage import create_manual_event, save_manual_event
        evt = create_manual_event(date_str, start_time, end_time, activity, category, notes)
        saved_path = save_manual_event(config.data_directory, date_str, evt)

        # Trigger automatic report and dashboard regeneration
        import asyncio
        import importlib
        import reporting.generate_report
        import reporting.generate_dashboard
        importlib.reload(reporting.generate_report)
        importlib.reload(reporting.generate_dashboard)
        from reporting.generate_report import generate_single_day_report, write_report
        from reporting.generate_dashboard import generate_dashboard_files

        report = await asyncio.to_thread(generate_single_day_report, config, date_str)
        await asyncio.to_thread(write_report, config, report, f"{date_str}.json")
        await asyncio.to_thread(generate_dashboard_files, config.data_directory)

        return web.json_response({
            "status": "ok",
            "message": f"Manual activity '{activity}' logged for {date_str}",
            "event": evt,
            "saved_to": saved_path,
        }, headers=cors_headers())
    except Exception as e:
        logger.error(f"Error logging manual event: {e}")
        return web.json_response({"status": "error", "message": str(e)}, status=400, headers=cors_headers())

async def handle_get_manual(request):
    try:
        from datetime import datetime
        date_str = request.query.get("date") or datetime.now().strftime("%Y-%m-%d")
        from collector.manual_storage import read_manual_events
        events = read_manual_events(config.data_directory, date_str)
        return web.json_response({
            "status": "ok",
            "date": date_str,
            "events": events
        }, headers=cors_headers())
    except Exception as e:
        logger.error(f"Error fetching manual events: {e}")
        return web.json_response({"status": "error", "message": str(e)}, status=400, headers=cors_headers())

async def handle_dashboard(request):
    from pathlib import Path
    dashboard_path = Path(config.data_directory) / "report" / "dashboard.html"
    if dashboard_path.exists():
        return web.FileResponse(dashboard_path)
    return web.Response(text="Dashboard not found at Record/report/dashboard.html", status=404)

async def handle_root(request):
    return web.json_response({
        "status": "ok",
        "service": "Activity Tracker Collector",
        "endpoints": ["GET /health", "GET /config", "GET /dashboard", "POST /event", "POST /events", "POST /api/sync-mobile", "POST /api/generate-report", "POST /api/manual", "GET /api/manual"]
    }, headers=cors_headers())

app = web.Application(middlewares=[auth_and_cors_middleware])
app.router.add_get('/', handle_root)
app.router.add_route('OPTIONS', '/{tail:.*}', handle_options)
app.router.add_get('/health', handle_health)
app.router.add_get('/config', handle_config)
app.router.add_get('/dashboard', handle_dashboard)
app.router.add_get('/report/dashboard.html', handle_dashboard)
app.router.add_post('/event', handle_event)
app.router.add_post('/events', handle_events)
app.router.add_post('/api/sync-mobile', handle_sync_mobile)
app.router.add_post('/api/generate-report', handle_generate_report)
app.router.add_post('/api/manual', handle_manual_event)
app.router.add_get('/api/manual', handle_get_manual)

def start_periodic_mobile_sync(interval_seconds: float = 1800.0):
    import threading
    import time
    def _sync_worker():
        logger.info(f"Periodic mobile sync worker started (every {interval_seconds}s)")
        while True:
            time.sleep(interval_seconds)
            try:
                from collector.android_collector import sync_mobile_activity
                logger.info("Executing scheduled periodic mobile sync...")
                res = sync_mobile_activity()
                logger.info(f"Periodic mobile sync complete: {res.get('total_sessions', 0)} sessions")
            except Exception as e:
                logger.debug(f"Periodic mobile sync skipped/failed: {e}")

    sync_thread = threading.Thread(target=_sync_worker, daemon=True, name="PeriodicMobileSync")
    sync_thread.start()

def main():
    if not getattr(config, "auth_token", None):
        logger.warning(
            "\n" + "=" * 60 + "\n"
            " [SECURITY WARNING] No auth_token configured in collector config!\n"
            " The collector is running in insecure mode.\n"
            " Any local client or browser script can submit events or read config.\n"
            " Set 'auth_token' in config.json to secure your collector.\n"
            + "=" * 60
        )
    logger.info(f"Starting collector on {config.collector_host}:{config.collector_port}")
    logger.info(f"Data directory: {config.data_directory}")
    
    # Start desktop window watcher background thread if on Windows
    if sys.platform == "win32":
        try:
            import threading
            from collector.desktop_watcher import DesktopWatcher
            watcher = DesktopWatcher(
                collector_url=f"http://{config.collector_host}:{config.collector_port}",
                data_directory=config.data_directory,
                min_session_duration=getattr(config, "raw_min_duration_seconds", 2.0)
            )
            watcher_thread = threading.Thread(target=watcher.start, daemon=True)
            watcher_thread.start()
            logger.info("Desktop application watcher thread started")
        except Exception as e:
            logger.warning(f"Could not start desktop watcher: {e}")

    # Start periodic mobile sync background thread if enabled
    android_cfg = getattr(config, "android", {}) or {}
    if android_cfg.get("enabled", True):
        try:
            interval = float(android_cfg.get("sync_interval_seconds", 1800.0))
            start_periodic_mobile_sync(interval_seconds=interval)
        except Exception as e:
            logger.warning(f"Could not start periodic mobile sync: {e}")

    try:
        web.run_app(app, host=config.collector_host, port=config.collector_port)
    except KeyboardInterrupt:
        logger.info("Shutting down")

if __name__ == '__main__':
    main()
