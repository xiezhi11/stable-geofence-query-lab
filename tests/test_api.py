from __future__ import annotations

from fastapi.testclient import TestClient

from main import create_app


ZONE = {
    "id": "z", "name": "Z", "version": 1, "priority": 0,
    "effective_from": "2026-01-01T00:00:00Z", "effective_to": None,
    "shape": {"type": "circle", "center": [10.0, 20.0], "radius_m": 100},
}
EVENT = {
    "event_id": "api-1", "vehicle_id": "v1", "latitude": 10.0001,
    "longitude": 20.0001, "timestamp": "2026-01-02T00:00:00Z",
}


def test_http_error_contract_has_stable_code_and_no_stack_path(tmp_path):
    client = TestClient(create_app(str(tmp_path / "state.json")))
    response = client.post("/events", json={"event_id": "bad", "latitude": 91, "longitude": 0,
                                             "timestamp": "2026-01-02T00:00:00Z"})
    assert response.status_code == 400
    assert response.json() == {
        "error": {"code": "invalid_coordinates",
                 "message": "Latitude must be between -90 and 90.",
                 "field_path": "latitude"}
    }


def test_fixed_clock_batch_pagination_and_restart(tmp_path):
    state_path = tmp_path / "state.json"
    client = TestClient(create_app(str(state_path)))
    client.post("/admin/reset")
    assert client.put("/zones", json={"zones": [ZONE]}).status_code == 200
    headers = {"X-Fixed-Clock": "2026-01-02T12:00:00+09:00"}
    batch = client.post("/events/batch", json={"events": [
        EVENT,
        {**EVENT, "event_id": "bad", "latitude": "north"},
        {**EVENT, "event_id": "api-2"},
    ]}, headers=headers)
    assert batch.status_code == 200
    payload = batch.json()
    assert [item["index"] for item in payload["results"]] == [0, 1, 2]
    assert payload["results"][0]["result"]["confirmed_at"] == "2026-01-02T03:00:00Z"
    assert payload["results"][1]["error"]["field_path"] == "events[1].latitude"
    duplicate = client.post("/events", json=EVENT, headers=headers).json()
    assert duplicate["duplicate"] is True
    assert duplicate["zone_id"] == "z"
    page = client.get("/matches?zone_id=z&limit=1").json()
    assert page["total"] == 2 and page["next_cursor"]
    restarted = TestClient(create_app(str(state_path)))
    assert restarted.post("/snapshots/restart").json()["records"] == 2
    assert restarted.get("/matches?zone_id=z").json()["records"][0]["zone_id"] == "z"
