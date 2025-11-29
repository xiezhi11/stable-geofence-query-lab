from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from datetime import datetime
from math import radians, sin, cos, sqrt, atan2

app = FastAPI(title="Geofence Event Service")

# Hardcoded Geofence Zones
ZONES = [
    {
        "id": "zone_circle",
        "name": "Central Park",
        "type": "circle",
        "center": [40.785091, -73.968285],   
        "radius_m": 500
    },
    {
        "id": "zone_poly",
        "name": "Town Square",
        "type": "polygon",
        "points": [
            [40.757, -73.9855],
            [40.757, -73.9830],
            [40.755, -73.9830],
            [40.755, -73.9855]
        ]
    }
]

# In-memory store
vehicle_state: Dict[str, Dict[str, Any]] = {}
event_log: List[Dict[str, Any]] = []

# Utility Functions
def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = (
        sin(dlat / 2) ** 2
        + cos(radians(lat1))
        * cos(radians(lat2))
        * sin(dlon / 2) ** 2
    )
    return 2 * R * atan2(sqrt(a), sqrt(1 - a))

def point_in_polygon(lat, lon, polygon):
    x, y = lon, lat
    inside = False
    n = len(polygon)

    for i in range(n):
        lat1, lon1 = polygon[i]
        lat2, lon2 = polygon[(i + 1) % n]

        if ((lat1 > y) != (lat2 > y)) and \
                (x < (lon2 - lon1) * (y - lat1) / ((lat2 - lat1) + 1e-12) + lon1):
            inside = not inside
    return inside


def detect_zone(lat, lon):
    for z in ZONES:
        if z["type"] == "circle":
            d = haversine(lat, lon, z["center"][0], z["center"][1])
            if d <= z["radius_m"]:
                return z
        else:
            if point_in_polygon(lat, lon, z["points"]):
                return z
    return None

# Models
class Event(BaseModel):
    vehicle_id: str
    latitude: float
    longitude: float
    timestamp: Optional[datetime] = None

# Endpoints
@app.post("/events")
def receive_event(evt: Event):
    ts = evt.timestamp or datetime.utcnow()

    zone = detect_zone(evt.latitude, evt.longitude)
    zone_id = zone["id"] if zone else None

    prev = vehicle_state.get(evt.vehicle_id)
    prev_zone = prev["zone_id"] if prev else None

    action = None
    if prev_zone != zone_id:
        if prev_zone is None and zone_id:
            action = "enter"
        elif prev_zone and zone_id is None:
            action = "exit"
        elif prev_zone and zone_id:
            action = "zone_changed"

    vehicle_state[evt.vehicle_id] = {
        "zone_id": zone_id,
        "zone_name": zone["name"] if zone else None,
        "last_seen": ts.isoformat()
    }

    record = {
        "vehicle_id": evt.vehicle_id,
        "latitude": evt.latitude,
        "longitude": evt.longitude,
        "timestamp": ts.isoformat(),
        "zone_id": zone_id,
        "action": action
    }
    event_log.append(record)

    return {"status": "ok", "event": record}


@app.get("/vehicle/{vehicle_id}")
def get_vehicle(vehicle_id: str):
    if vehicle_id not in vehicle_state:
        raise HTTPException(404, "Vehicle not found")
    return vehicle_state[vehicle_id]


@app.get("/zones")
def get_zones():
    return ZONES


@app.get("/events")
def get_events(limit: int = 100):
    return list(reversed(event_log))[:limit]
