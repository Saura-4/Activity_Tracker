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

def cors_headers():
    return {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'POST, GET, OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type'
    }

async def handle_options(request):
    return web.Response(headers=cors_headers())

async def handle_health(request):
    return web.json_response({"status": "ok"}, headers=cors_headers())

async def handle_config(request):
    return web.json_response(dataclasses.asdict(config), headers=cors_headers())

async def process_single_event(data):
    event = validate_and_create_event(data, config.strip_query_strings)
    min_dur = getattr(config, "min_duration_seconds", 40.0)
    if event.duration_seconds < min_dur:
        logger.debug(f"Event dropped (duration {event.duration_seconds}s < {min_dur}s): {event.source}")
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

async def handle_root(request):
    return web.json_response({
        "status": "ok",
        "service": "Activity Tracker Collector",
        "endpoints": ["GET /health", "GET /config", "POST /event", "POST /events", "POST /api/sync-mobile", "POST /api/generate-report", "POST /api/manual", "GET /api/manual"]
    }, headers=cors_headers())

app = web.Application()
app.router.add_get('/', handle_root)
app.router.add_route('OPTIONS', '/{tail:.*}', handle_options)
app.router.add_get('/health', handle_health)
app.router.add_get('/config', handle_config)
app.router.add_post('/event', handle_event)
app.router.add_post('/events', handle_events)
app.router.add_post('/api/sync-mobile', handle_sync_mobile)
app.router.add_post('/api/generate-report', handle_generate_report)
app.router.add_post('/api/manual', handle_manual_event)
app.router.add_get('/api/manual', handle_get_manual)

def main():
    logger.info(f"Starting collector on {config.collector_host}:{config.collector_port}")
    logger.info(f"Data directory: {config.data_directory}")
    
    # Start desktop window watcher background thread if on Windows
    if sys.platform == "win32":
        try:
            import threading
            from collector.desktop_watcher import DesktopWatcher
            watcher = DesktopWatcher(
                collector_url=f"http://{config.collector_host}:{config.collector_port}",
                data_directory=config.data_directory
            )
            watcher_thread = threading.Thread(target=watcher.start, daemon=True)
            watcher_thread.start()
            logger.info("Desktop application watcher thread started")
        except Exception as e:
            logger.warning(f"Could not start desktop watcher: {e}")

    try:
        web.run_app(app, host=config.collector_host, port=config.collector_port)
    except KeyboardInterrupt:
        logger.info("Shutting down")

if __name__ == '__main__':
    main()
