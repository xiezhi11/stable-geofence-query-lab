from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any, Optional

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from geofence import Clock, ExternalNotifier, GeofenceService, ServiceError, parse_time
from store import create_store


def create_app(state_path: Optional[str] = None) -> FastAPI:
    path = state_path or os.environ.get("GEOFENCE_STATE_PATH")
    store = create_store(path) if path else None
    clock = Clock()
    notifications: list[dict[str, Any]] = []
    service = GeofenceService(clock=clock, notifier=ExternalNotifier(notifications.append), store=store)

    app = FastAPI(title="Deterministic Geofence Event Service")
    app.state.service = service
    app.state.clock = clock
    app.state.notifications = notifications

    @app.exception_handler(ServiceError)
    async def service_error_handler(request: Request, exc: ServiceError):
        status_codes = {
            "invalid_format": 400,
            "invalid_coordinates": 400,
            "invalid_cursor": 400,
            "zone_not_found": 404,
            "window_not_found": 404,
            "version_expired": 409,
            "duplicate_event": 409,
        }
        return JSONResponse(exc.to_dict(), status_code=status_codes.get(exc.code, 400))

    @app.exception_handler(Exception)
    async def generic_error_handler(request: Request, exc: Exception):
        return JSONResponse({"error": {"code": "internal_error", "message": "Request failed."}}, status_code=500)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        first = exc.errors()[0] if exc.errors() else {"loc": ["body"], "msg": "Invalid request."}
        location = [str(part) for part in first.get("loc", ["body"]) if part != "body"]
        field_path = ".".join(location) if location else "body"
        return JSONResponse({"error": {"code": "invalid_format", "message": "Request format is invalid.",
                                       "field_path": field_path}}, status_code=400)

    @asynccontextmanager
    async def fixed_clock(request: Request):
        value = request.headers.get("X-Fixed-Clock")
        moment = parse_time(value, "X-Fixed-Clock") if value else None
        with app.state.clock.fixed(moment):
            yield

    @app.post("/admin/reset")
    async def reset(request: Request):
        async with fixed_clock(request):
            app.state.notifications.clear()
            return app.state.service.reset()

    @app.post("/admin/clock")
    async def set_clock(payload: dict[str, Any]):
        value = payload.get("now")
        if value is None:
            app.state.clock.reset()
            return {"clock": "system"}
        moment = parse_time(value, "now")
        app.state.clock.set(moment)
        return {"clock": moment.isoformat().replace("+00:00", "Z")}

    @app.put("/zones")
    async def replace_zones(payload: dict[str, Any]):
        zones = payload.get("zones")
        if not isinstance(zones, list):
            raise ServiceError("invalid_format", "zones must be an array.", "zones")
        return app.state.service.replace_zones(zones)

    @app.get("/zones/{zone_id}")
    async def get_zone(zone_id: str, at: Optional[str] = None):
        return app.state.service.get_zone(zone_id, at)

    @app.post("/windows")
    async def put_window(payload: dict[str, Any]):
        return app.state.service.put_window(payload)

    @app.post("/events")
    async def submit_event(request: Request, payload: dict[str, Any]):
        async with fixed_clock(request):
            return app.state.service.submit_event(payload)

    @app.post("/events/batch")
    async def submit_batch(request: Request, payload: dict[str, Any]):
        async with fixed_clock(request):
            return app.state.service.submit_batch(payload)

    @app.get("/matches")
    async def query_matches(
        zone_id: Optional[str] = None,
        status: Optional[str] = None,
        unmatched_only: bool = False,
        limit: int = Query(50, ge=1, le=200),
        cursor: Optional[str] = None,
    ):
        return app.state.service.query_records(
            {"zone_id": zone_id, "status": status, "unmatched_only": unmatched_only},
            limit=limit,
            cursor=cursor,
        )

    @app.post("/snapshots/restart")
    async def restart_from_store():
        if app.state.service.store is None:
            return {"status": "restarted", "persistence": "disabled"}
        state = app.state.service.store.load()
        app.state.service.load_state(state)
        return {"status": "restarted", "persistence": "enabled", "records": len(state.get("records", []))}

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


app = create_app()
