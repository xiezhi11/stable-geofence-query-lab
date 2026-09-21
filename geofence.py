from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import RLock
from typing import Any, Callable, Optional
from store import StateStore


class ServiceError(Exception):
    def __init__(self, code: str, message: str, field_path: Optional[str] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.field_path = field_path

    def to_dict(self) -> dict[str, Any]:
        error = {"code": self.code, "message": self.message}
        if self.field_path is not None:
            error["field_path"] = self.field_path
        return {"error": error}


def parse_time(value: Any, field_path: str = "timestamp") -> datetime:
    if not isinstance(value, str):
        raise ServiceError("invalid_format", "Timestamp must be an ISO-8601 string with timezone.", field_path)
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        parsed = None
    if parsed is None or parsed.tzinfo is None:
        raise ServiceError("invalid_format", "Timestamp must be an ISO-8601 string with timezone.", field_path)
    return parsed.astimezone(timezone.utc)


def format_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def validate_coordinates(latitude: Any, longitude: Any, field_prefix: str = "") -> tuple[float, float]:
    lat_path = f"{field_prefix}latitude" if field_prefix else "latitude"
    lon_path = f"{field_prefix}longitude" if field_prefix else "longitude"
    if not _finite_number(latitude):
        raise ServiceError("invalid_format", "Latitude must be a finite number.", lat_path)
    if not _finite_number(longitude):
        raise ServiceError("invalid_format", "Longitude must be a finite number.", lon_path)
    latitude = float(latitude)
    longitude = float(longitude)
    if not -90.0 <= latitude <= 90.0:
        raise ServiceError("invalid_coordinates", "Latitude must be between -90 and 90.", lat_path)
    if not -180.0 <= longitude <= 180.0:
        raise ServiceError("invalid_coordinates", "Longitude must be between -180 and 180.", lon_path)
    return latitude, longitude


@dataclass(frozen=True)
class Zone:
    id: str
    name: str
    version: int
    priority: int
    shape: dict[str, Any]
    effective_from: datetime
    effective_to: Optional[datetime]
    revoked: bool = False

    def active_at(self, at: datetime) -> bool:
        if self.revoked or at < self.effective_from:
            return False
        return self.effective_to is None or at < self.effective_to


@dataclass(frozen=True)
class Window:
    id: str
    start: datetime
    end: datetime
    late_until: datetime


@dataclass(frozen=True)
class Snapshot:
    catalog_version: int
    zones: tuple[Zone, ...]


def haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6_371_000.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    )
    return 2 * radius * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _point_on_segment(lat: float, lon: float, a: tuple[float, float], b: tuple[float, float]) -> bool:
    ax, ay = a[1], a[0]
    bx, by = b[1], b[0]
    cross = (lat - ay) * (bx - ax) - (lon - ax) * (by - ay)
    if abs(cross) > 1e-10:
        return False
    return (lon - ax) * (lon - bx) + (lat - ay) * (lat - by) <= 1e-10


def point_in_polygon(latitude: float, longitude: float, points: list[list[float]]) -> bool:
    inside = False
    count = len(points)
    for i, (lat1, lon1) in enumerate(points):
        lat2, lon2 = points[(i + 1) % count]
        if _point_on_segment(latitude, longitude, (lat1, lon1), (lat2, lon2)):
            return True
        if (lat1 > latitude) != (lat2 > latitude):
            boundary_longitude = (lon2 - lon1) * (latitude - lat1) / (lat2 - lat1) + lon1
            if longitude < boundary_longitude:
                inside = not inside
    return inside


def zone_contains(zone: Zone, latitude: float, longitude: float) -> bool:
    shape = zone.shape
    kind = shape.get("type")
    if kind == "circle":
        center = shape.get("center", [])
        radius = shape.get("radius_m")
        return (
            isinstance(center, list) and len(center) == 2
            and _finite_number(radius) and float(radius) >= 0
            and haversine_meters(latitude, longitude, float(center[0]), float(center[1])) <= float(radius)
        )
    if kind == "polygon":
        points = shape.get("points", [])
        return isinstance(points, list) and len(points) >= 3 and point_in_polygon(latitude, longitude, points)
    return False


def _valid_shape(shape: Any) -> bool:
    if not isinstance(shape, dict):
        return False
    kind = shape.get("type")
    if kind == "circle":
        center = shape.get("center")
        radius = shape.get("radius_m")
        return (
            isinstance(center, list) and len(center) == 2
            and all(_finite_number(value) for value in center)
            and -90 <= float(center[0]) <= 90 and -180 <= float(center[1]) <= 180
            and _finite_number(radius) and float(radius) >= 0
        )
    if kind == "polygon":
        points = shape.get("points")
        return (
            isinstance(points, list) and len(points) >= 3
            and all(
                isinstance(point, list) and len(point) == 2 and _finite_number(point[0])
                and _finite_number(point[1]) and -90 <= float(point[0]) <= 90
                and -180 <= float(point[1]) <= 180
                for point in points
            )
        )
    return False


class Clock:
    def __init__(self, fixed_at: Optional[datetime | str] = None):
        self._override: Optional[datetime] = None
        if fixed_at is not None:
            self.set(fixed_at)

    def set(self, value: datetime | str) -> None:
        self._override = value if isinstance(value, datetime) else parse_time(value, "clock")

    def reset(self) -> None:
        self._override = None

    def now(self) -> datetime:
        return (self._override or datetime.now(timezone.utc)).astimezone(timezone.utc)

    @contextmanager
    def fixed(self, value: Optional[datetime]):
        previous = self._override
        if value is not None:
            self._override = value
        try:
            yield
        finally:
            self._override = previous


class ExternalNotifier:
    def __init__(self, sink: Optional[Callable[[dict[str, Any]], None]] = None):
        self.sink = sink

    def confirm(self, payload: dict[str, Any]) -> None:
        if self.sink is not None:
            self.sink(payload)


class GeofenceService:
    def __init__(self, clock: Optional[Clock] = None, notifier: Optional[ExternalNotifier] = None,
                 store: Optional[StateStore] = None):
        self.clock = clock or Clock()
        self.notifier = notifier or ExternalNotifier()
        self.store = store
        self.lock = RLock()
        self.catalog_version = 1
        self.zones: dict[str, list[Zone]] = {}
        self.windows: dict[str, Window] = {}
        self.records: dict[str, dict[str, Any]] = {}
        self.snapshot_history: dict[int, Snapshot] = {}
        if store is not None:
            self.load_state(store.load())

    def _persist(self) -> None:
        if self.store is not None:
            self.store.save(self.export_state())

    def reset(self) -> dict[str, str]:
        with self.lock:
            self.catalog_version = 1
            self.zones.clear()
            self.windows.clear()
            self.records.clear()
            self.snapshot_history.clear()
            self.clock.reset()
            self._persist()
        return {"zones": "cleared", "events": "cleared", "windows": "cleared", "clock": "reset"}

    def export_state(self) -> dict[str, Any]:
        with self.lock:
            return {
                "catalog_version": self.catalog_version,
                "zones": [self._zone_dict(zone) for versions in self.zones.values() for zone in versions],
                "windows": [self._window_dict(window) for window in self.windows.values()],
                "records": list(self.records.values()),
            }

    def load_state(self, state: dict[str, Any]) -> None:
        with self.lock:
            self.catalog_version = int(state.get("catalog_version", 1))
            self.zones = {}
            self.windows = {}
            self.records = {}
            self.snapshot_history = {}
            for item in state.get("zones", []):
                zone = self._zone_from_dict(item)
                self.zones.setdefault(zone.id, []).append(zone)
            for versions in self.zones.values():
                versions.sort(key=lambda zone: (zone.effective_from, zone.version))
            for item in state.get("windows", []):
                window = Window(item["id"], parse_time(item["start"]), parse_time(item["end"]), parse_time(item["late_until"]))
                self.windows[window.id] = window
            for item in state.get("records", []):
                self.records[item["event_id"]] = item
            self.snapshot_history = {
                self.catalog_version: Snapshot(
                    self.catalog_version,
                    tuple(zone for versions in self.zones.values() for zone in versions),
                )
            }

    @staticmethod
    def _zone_dict(zone: Zone) -> dict[str, Any]:
        return {
            "id": zone.id, "name": zone.name, "version": zone.version, "priority": zone.priority,
            "shape": zone.shape, "effective_from": format_time(zone.effective_from),
            "effective_to": format_time(zone.effective_to) if zone.effective_to else None,
            "revoked": zone.revoked,
        }

    @staticmethod
    def _zone_from_dict(item: dict[str, Any]) -> Zone:
        return Zone(
            item["id"], item["name"], int(item["version"]), int(item["priority"]), item["shape"],
            parse_time(item["effective_from"]),
            parse_time(item["effective_to"]) if item.get("effective_to") else None,
            bool(item.get("revoked", False)),
        )

    @staticmethod
    def _window_dict(window: Window) -> dict[str, Any]:
        return {
            "id": window.id, "start": format_time(window.start), "end": format_time(window.end),
            "late_until": format_time(window.late_until),
        }

    def replace_zones(self, payload: list[dict[str, Any]]) -> dict[str, Any]:
        parsed: list[Zone] = []
        overlaps: dict[str, list[tuple[datetime, Optional[datetime]]]] = {}
        seen: set[tuple[str, int]] = set()
        for index, item in enumerate(payload):
            prefix = f"zones[{index}]."
            if not isinstance(item, dict):
                raise ServiceError("invalid_format", "Each zone must be an object.", f"zones[{index}]")
            zone_id = item.get("id")
            if not isinstance(zone_id, str) or not zone_id:
                raise ServiceError("invalid_format", "Zone id is required.", prefix + "id")
            version = item.get("version")
            if not isinstance(version, int) or isinstance(version, bool) or version < 1:
                raise ServiceError("invalid_format", "Zone version must be a positive integer.", prefix + "version")
            if (zone_id, version) in seen:
                raise ServiceError("invalid_format", "Duplicate zone version in batch.", prefix + "version")
            seen.add((zone_id, version))
            if not _valid_shape(item.get("shape")):
                raise ServiceError("invalid_format", "Zone shape is invalid.", prefix + "shape")
            start = parse_time(item.get("effective_from"), prefix + "effective_from")
            end = parse_time(item.get("effective_to"), prefix + "effective_to") if item.get("effective_to") else None
            if end is not None and end <= start:
                raise ServiceError("invalid_format", "effective_to must be after effective_from.", prefix + "effective_to")
            for old_start, old_end in overlaps.setdefault(zone_id, []):
                if end is None or old_end is None or (start < old_end and old_start < end):
                    raise ServiceError("invalid_format", "Versions of one zone cannot overlap in time.", prefix + "version")
            overlaps[zone_id].append((start, end))
            parsed.append(Zone(zone_id, str(item.get("name") or zone_id), version,
                               int(item.get("priority", 0)), item["shape"], start, end,
                               bool(item.get("revoked", False))))
        grouped: dict[str, list[Zone]] = {}
        for zone in parsed:
            grouped.setdefault(zone.id, []).append(zone)
        for versions in grouped.values():
            versions.sort(key=lambda zone: (zone.effective_from, zone.version))
        with self.lock:
            self.snapshot_history[self.catalog_version] = Snapshot(
                self.catalog_version,
                tuple(zone for versions in self.zones.values() for zone in versions),
            )
            self.zones = grouped
            self.catalog_version += 1
            self._persist()
            return {"status": "confirmed", "catalog_version": self.catalog_version, "zone_count": len(parsed)}

    def snapshot(self, expected_version: Optional[int] = None, allow_historical: bool = False) -> Snapshot:
        with self.lock:
            if expected_version is not None and expected_version != self.catalog_version:
                if allow_historical and expected_version in self.snapshot_history:
                    return self.snapshot_history[expected_version]
                raise ServiceError("version_expired",
                                   f"Zone version {expected_version} is not current version {self.catalog_version}.",
                                   "zone_version")
            return Snapshot(self.catalog_version,
                            tuple(zone for versions in self.zones.values() for zone in versions))

    def get_zone(self, zone_id: str, at: Optional[str] = None) -> dict[str, Any]:
        moment = parse_time(at) if at else self.clock.now()
        with self.lock:
            versions = self.zones.get(zone_id)
            if not versions:
                raise ServiceError("zone_not_found", f"Zone '{zone_id}' does not exist.", "zone_id")
            active = [zone for zone in versions if zone.active_at(moment)]
            if not active:
                raise ServiceError("zone_not_found", f"Zone '{zone_id}' is not active at the requested time.", "zone_id")
            return self._zone_dict(active[-1])

    def put_window(self, payload: dict[str, Any]) -> dict[str, Any]:
        window_id = payload.get("id")
        if not isinstance(window_id, str) or not window_id:
            raise ServiceError("invalid_format", "Window id is required.", "id")
        start = parse_time(payload.get("start"), "start")
        end = parse_time(payload.get("end"), "end")
        late_until = parse_time(payload.get("late_until"), "late_until")
        if end <= start:
            raise ServiceError("invalid_format", "Window end must be after start; use full timestamps for cross-day ranges.", "end")
        if late_until < end:
            raise ServiceError("invalid_format", "late_until cannot precede end.", "late_until")
        with self.lock:
            self.windows[window_id] = Window(window_id, start, end, late_until)
            self._persist()
            return {"status": "confirmed", "window": self._window_dict(self.windows[window_id])}

    def submit_event(self, payload: dict[str, Any], snapshot: Optional[Snapshot] = None,
                     error_prefix: str = "") -> dict[str, Any]:
        event_id = payload.get("event_id")
        if not isinstance(event_id, str) or not event_id:
            raise ServiceError("invalid_format", "event_id is required.", error_prefix + "event_id")
        latitude, longitude = validate_coordinates(
            payload.get("latitude"), payload.get("longitude"), error_prefix
        )
        event_time = parse_time(payload.get("timestamp"), error_prefix + "timestamp")
        window_id = payload.get("window_id")
        window = None
        if window_id is not None:
            if not isinstance(window_id, str) or not window_id:
                raise ServiceError("invalid_format", "window_id must be a non-empty string.", error_prefix + "window_id")
            with self.lock:
                window = self.windows.get(window_id)
            if window is None:
                raise ServiceError("window_not_found", f"Window '{window_id}' does not exist.", error_prefix + "window_id")
        requested_version = payload.get("zone_version")
        if requested_version is not None and (not isinstance(requested_version, int)
                                               or isinstance(requested_version, bool) or requested_version < 1):
            raise ServiceError("invalid_format", "zone_version must be a positive integer.", error_prefix + "zone_version")
        with self.lock:
            existing = self.records.get(event_id)
            if existing is not None:
                return {**existing, "duplicate": True,
                        "error": {"code": "duplicate_event",
                                  "message": "Event already confirmed; returning the first stored result.",
                                  "field_path": "event_id"}}
            active_snapshot = snapshot or self.snapshot(requested_version)
            now = self.clock.now()
            status, window_reason = self._window_status(window, event_time, now)
            if status == "closed":
                result = self._record(event_id, payload, latitude, longitude, event_time,
                                      active_snapshot.catalog_version, None, status, window_reason)
                if window_id:
                    result["window_id"] = window_id
                self.records[event_id] = result
                self._persist()
                return {**result, "duplicate": False}
            zone = self._select_zone(active_snapshot.zones, latitude, longitude, event_time)
            result = self._record(event_id, payload, latitude, longitude, event_time,
                                  active_snapshot.catalog_version, zone, "confirmed",
                                  None if zone else "no_active_zone")
            if window_id:
                result["window_id"] = window_id
            self.records[event_id] = result
            self._persist()
            self.notifier.confirm({"event_id": event_id, "status": "confirmed"})
            return {**result, "duplicate": False}

    def submit_batch(self, payload: dict[str, Any]) -> dict[str, Any]:
        events = payload.get("events")
        if not isinstance(events, list):
            raise ServiceError("invalid_format", "events must be an array.", "events")
        requested_version = payload.get("zone_version")
        batch_snapshot = self.snapshot(requested_version, allow_historical=True) if requested_version is not None else self.snapshot()
        results: list[Optional[dict[str, Any]]] = [None] * len(events)
        def handle(index: int, item: Any) -> tuple[int, dict[str, Any]]:
            if not isinstance(item, dict):
                error = ServiceError("invalid_format", "Each event must be an object.", f"events[{index}]")
                return index, {"index": index, "ok": False, **error.to_dict()}
            try:
                return index, {"index": index, "ok": True,
                                "result": self.submit_event(item, batch_snapshot, f"events[{index}].")}
            except ServiceError as error:
                return index, {"index": index, "ok": False, **error.to_dict()}

        max_workers = min(32, max(1, len(events)))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            for index, value in executor.map(lambda pair: handle(pair[0], pair[1]),
                                             enumerate(events)):
                results[index] = value
        return {"status": "complete", "zone_version": batch_snapshot.catalog_version, "results": results}

    def query_records(self, filters: dict[str, Any], limit: int = 50, cursor: Optional[str] = None) -> dict[str, Any]:
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 200:
            raise ServiceError("invalid_format", "limit must be between 1 and 200.", "limit")
        cursor_event_id, cursor_timestamp = self._decode_cursor(cursor)
        zone_id = filters.get("zone_id")
        status = filters.get("status")
        unmatched_only = bool(filters.get("unmatched_only"))
        matching = []
        for record in self.records.values():
            if zone_id is not None and record.get("zone_id") != zone_id:
                continue
            if status is not None and record.get("status") != status:
                continue
            if unmatched_only and record.get("zone_id") is not None:
                continue
            if cursor and (record["timestamp"] < cursor_timestamp
                           or (record["timestamp"] == cursor_timestamp and record["event_id"] <= cursor_event_id)):
                continue
            matching.append(record)
        matching.sort(key=lambda row: (row["timestamp"], row["event_id"]))
        if cursor:
            start_index = 0
            while start_index < len(matching) and (
                matching[start_index]["timestamp"] < cursor_timestamp
                or (matching[start_index]["timestamp"] == cursor_timestamp
                    and matching[start_index]["event_id"] <= cursor_event_id)
            ):
                start_index += 1
        else:
            start_index = 0
        page = matching[start_index:start_index + limit]
        next_index = start_index + limit
        next_cursor = self._encode_cursor(page[-1]["event_id"], page[-1]["timestamp"]) if next_index < len(matching) else None
        return {"total": len(matching), "limit": limit, "records": page, "next_cursor": next_cursor}

    @staticmethod
    def _window_status(window: Optional[Window], event_time: datetime, now: datetime) -> tuple[str, Optional[str]]:
        if window is None:
            return "confirmed", None
        if now > window.late_until:
            return "closed", "window_closed"
        if event_time < window.start or event_time >= window.end:
            return "closed", "event_outside_window"
        return "confirmed", "late_accepted" if now > window.end else None

    @staticmethod
    def _select_zone(zones: tuple[Zone, ...], latitude: float, longitude: float, at: datetime) -> Optional[Zone]:
        candidates = [zone for zone in zones if zone.active_at(at) and zone_contains(zone, latitude, longitude)]
        return max(candidates, key=lambda zone: (zone.priority, zone.version, zone.id)) if candidates else None

    def _record(self, event_id: str, payload: dict[str, Any], latitude: float, longitude: float,
                event_time: datetime, catalog_version: int, zone: Optional[Zone],
                status: str, reason: Optional[str]) -> dict[str, Any]:
        return {
            "event_id": event_id,
            "vehicle_id": payload.get("vehicle_id"),
            "latitude": latitude,
            "longitude": longitude,
            "timestamp": format_time(event_time),
            "zone_version": catalog_version,
            "zone": self._zone_dict(zone) if zone else None,
            "zone_id": zone.id if zone else None,
            "status": status,
            "unmatched_reason": reason,
            "confirmed_at": format_time(self.clock.now()) if status == "confirmed" else None,
        }

    @staticmethod
    def _encode_cursor(event_id: str, timestamp: str) -> str:
        import base64
        import json
        raw = json.dumps([event_id, timestamp], separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).decode()

    @staticmethod
    def _decode_cursor(cursor: Optional[str]) -> tuple[str, str]:
        if not cursor:
            return "", ""
        import base64
        import json
        try:
            event_id, timestamp = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        except Exception:
            raise ServiceError("invalid_cursor", "Pagination cursor is invalid.", "cursor") from None
        if not isinstance(event_id, str) or not isinstance(timestamp, str):
            raise ServiceError("invalid_cursor", "Pagination cursor is invalid.", "cursor")
        return event_id, timestamp
