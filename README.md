1. Overview
This project implements a lightweight Geofence Event Processing Service for a taxi company.
Vehicles send real-time GPS updates to the service, and the system detects:
When a vehicle enters a geographic zone
When a vehicle exits a zone
What zone a given vehicle is currently in
The service exposes clean HTTP APIs using FastAPI.

2. Features
Accept GPS events
Via POST /events, containing:
 vehicle_id
 latitude, longitude
 timestamp 

Detect zone entry/exits
 Supports both circular and polygonal geofences
 Computes the correct zone per GPS point
 Compares previous zone vs new zone to determine:
  "enter"
  "exit"
  "zone_changed"
  null if no change

Query current zone of a vehicle
  GET /vehicle/{vehicle_id}

View configured zones
  GET /zones

Retrieve recent events
  GET /events

In-memory state (simple simulation)
  Vehicle status and event logs are stored in dictionaries during runtime.

3. Tech Stack
Python 3
FastAPI
Uvicorn
Pydantic v2

4. Project Structure
geofence_service/
|- main.py
|- requirements.txt
|- README.md
|- venv/

5. Setup Instructions

Step 1 — Install dependencies
From the project folder:
  pip install -r requirements.txt

Step 2 — Run the server
  uvicorn main:app --reload

Step 3 — Open the API UI
Open:
  http://127.0.0.1:8000/docs
  Interactive Swagger UI allows testing all endpoints.

6. API Documentation
  POST /events — Receive a GPS event
Example request:
{
  "vehicle_id": "car1",
  "latitude": 40.756,
  "longitude": -73.984
}
Example response:
{
  "status": "ok",
  "event": {
    "vehicle_id": "car1",
    "latitude": 40.756,
    "longitude": -73.984,
    "timestamp": "2025-11-29T10:04:19.361334",
    "zone_id": "zone_poly",
    "action": "enter"
  }
}

GET /vehicle/{vehicle_id} — Get current vehicle zone
Example:
  GET /vehicle/car1
Response:
{
  "zone_id": "zone_poly",
  "zone_name": "Town Square",
  "last_seen": "2025-11-29T10:04:19.361334"
}

GET /zones — list all configured zones
  Shows both circle and polygon geofences.
GET /events — list of recent processed events
  GET /events?limit=50

7. Design Decisions
i) Why FastAPI?
High performance
Auto-generated API docs
Easy to extend and scale
ii) Why in-memory storage?
Meets assignment requirement
No setup overhead
Keeps code simple and readable

8. Error Handling
Invalid latitude/longitude
Missing fields
Vehicle not found
Invalid JSON body
All handled by FastAPI + Pydantic.

9. Future Improvements
Given more time, the next enhancements would be:
Dynamic zone creation (POST /zones)
Multi-zone tracking per vehicle
WebSocket stream for real-time tracking
Batch GPS event ingestion
Store vehicle history in a real database

# geofence-event-service
