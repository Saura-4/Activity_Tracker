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
    evt_dict = dataclasses.asdict(event)
    is_new = append_event(config, evt_dict)
    
    if is_new:
        ctx_info = ""
        if event.source == "browser":
            ctx_info = event.context.get("domain", "")
        elif event.source == "vscode":
            ctx_info = event.context.get("workspace", "")
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

async def handle_root(request):
    return web.json_response({
        "status": "ok",
        "service": "Activity Tracker Collector",
        "endpoints": ["GET /health", "GET /config", "POST /event", "POST /events"]
    }, headers=cors_headers())

app = web.Application()
app.router.add_get('/', handle_root)
app.router.add_route('OPTIONS', '/{tail:.*}', handle_options)
app.router.add_get('/health', handle_health)
app.router.add_get('/config', handle_config)
app.router.add_post('/event', handle_event)
app.router.add_post('/events', handle_events)

def main():
    logger.info(f"Starting collector on {config.collector_host}:{config.collector_port}")
    logger.info(f"Data directory: {config.data_directory}")
    
    try:
        web.run_app(app, host=config.collector_host, port=config.collector_port)
    except KeyboardInterrupt:
        logger.info("Shutting down")

if __name__ == '__main__':
    main()
