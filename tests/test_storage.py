from geofence import Clock, GeofenceService
from store import SqliteStateStore


def test_sqlite_fixture_persists_confirmed_result_and_can_reset(tmp_path):
    path = tmp_path / "fixture.sqlite"
    store = SqliteStateStore(path)
    service = GeofenceService(clock=Clock("2026-01-01T00:00:00Z"), store=store)
    service.replace_zones([{
        "id": "z", "name": "Z", "version": 1, "priority": 0,
        "effective_from": "2026-01-01T00:00:00Z", "effective_to": None,
        "shape": {"type": "circle", "center": [10.0, 20.0], "radius_m": 100},
    }])
    service.submit_event({
        "event_id": "db-1", "vehicle_id": "v1", "latitude": 10.0001,
        "longitude": 20.0001, "timestamp": "2026-01-01T01:00:00Z",
    })
    store.close()

    reopened_store = SqliteStateStore(path)
    reopened = GeofenceService(clock=Clock("2030-01-01T00:00:00Z"), store=reopened_store)
    assert reopened.query_records({})["records"][0]["zone_id"] == "z"
    reopened.reset()
    clean_state = reopened_store.load()
    assert clean_state["records"] == []
    assert clean_state["zones"] == []
    assert clean_state["windows"] == []
    reopened_store.close()
