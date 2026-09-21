from __future__ import annotations

import threading

import pytest

from geofence import Clock, GeofenceService, ServiceError
from store import JsonStateStore


def circle(zone_id: str, priority: int = 0, version: int = 1, start="2026-01-01T00:00:00Z", end=None):
    return {
        "id": zone_id, "name": zone_id.upper(), "version": version, "priority": priority,
        "effective_from": start, "effective_to": end,
        "shape": {"type": "circle", "center": [10.0, 20.0], "radius_m": 100},
    }


def square(zone_id: str, priority: int = 0, version: int = 1, start="2026-01-01T00:00:00Z", end=None):
    return {
        "id": zone_id, "name": zone_id.upper(), "version": version, "priority": priority,
        "effective_from": start, "effective_to": end,
        "shape": {"type": "polygon", "points": [[10.0, 20.0], [10.0, 20.01], [10.01, 20.01], [10.01, 20.0]]},
    }


def event(event_id="e1", lat=10.0001, lon=20.0001, ts="2026-01-02T00:00:00Z", **extra):
    data = {"event_id": event_id, "vehicle_id": "v1", "latitude": lat, "longitude": lon, "timestamp": ts}
    data.update(extra)
    return data


def test_boundary_circle_and_polygon_are_included(service):
    service.replace_zones([circle("c"), square("p", priority=1)])
    center = service.submit_event(event("center", 10.0, 20.0))
    corner = service.submit_event(event("corner", 10.0, 20.0))
    # The same boundary point obeys the overlap rule rather than catalogue order.
    assert center["zone_id"] == "p"
    assert corner["zone"]["id"] == "p"


def test_overlap_priority_then_version(service):
    service.replace_zones([circle("low", priority=1), circle("high", priority=2)])
    assert service.submit_event(event("high"))["zone_id"] == "high"
    service.replace_zones([circle("low", priority=2, version=1), circle("high", priority=2, version=2)])
    assert service.submit_event(event("version"))["zone_id"] == "high"


def test_revoked_zone_keeps_history_but_rejects_new_events(service):
    service.replace_zones([circle("z")])
    first = service.submit_event(event("same"))
    assert first["zone_id"] == "z"
    active = circle("z")
    active["revoked"] = True
    service.replace_zones([active])
    second = service.submit_event(event("new", ts="2026-01-03T00:00:00Z"))
    assert second["status"] == "confirmed"
    assert second["zone_id"] is None
    assert second["unmatched_reason"] == "no_active_zone"
    historical = service.query_records({"zone_id": "z"})
    assert historical["records"][0]["event_id"] == "same"


@pytest.mark.parametrize("payload,path", [
    (event(latitude=90.1), "latitude"),
    (event(longitude=-180.1), "longitude"),
    (event(timestamp="2026-01-01 00:00:00"), "timestamp"),
    (event(zone_version=0), "zone_version"),
    (event(event_id=""), "event_id"),
])
def test_validation_error_paths_are_stable(service, payload, path):
    service.replace_zones([circle("z")])
    with pytest.raises(ServiceError) as info:
        service.submit_event(payload)
    assert info.value.field_path == path
    assert info.value.code in {"invalid_format", "invalid_coordinates"}


def test_nonexistent_zone_reference_and_expired_version_have_distinct_codes(service):
    service.replace_zones([circle("z")])
    with pytest.raises(ServiceError) as info:
        service.snapshot(99)
    assert info.value.code == "version_expired"
    with pytest.raises(ServiceError) as info:
        service.get_zone("missing")
    assert info.value.code == "zone_not_found"


def test_duplicate_returns_first_confirmation_even_if_later_submission_closed(service, clock):
    service.put_window({"id": "w", "start": "2026-01-01T00:00:00Z",
                        "end": "2026-01-02T00:00:00Z", "late_until": "2026-01-03T00:00:00Z"})
    service.replace_zones([circle("z")])
    first = service.submit_event(event(ts="2026-01-01T12:00:00Z", window_id="w"))
    clock.set("2026-01-04T00:00:00Z")
    duplicate = service.submit_event(event(ts="2026-01-01T12:00:00Z", window_id="w"))
    assert duplicate["duplicate"] is True
    assert duplicate["error"]["code"] == "duplicate_event"
    assert duplicate["error"]["field_path"] == "event_id"
    assert duplicate["confirmed_at"] == first["confirmed_at"]
    assert duplicate["zone_id"] == "z"


def test_late_cross_day_event_accepted_after_end_but_closed_after_late_until(service, clock):
    service.put_window({"id": "cross", "start": "2026-01-01T20:00:00Z",
                        "end": "2026-01-02T02:00:00Z", "late_until": "2026-01-02T03:00:00Z"})
    clock.set("2026-01-02T02:30:00Z")
    late = service.submit_event(event(ts="2026-01-02T01:00:00Z", window_id="cross"))
    assert late["status"] == "confirmed"
    clock.set("2026-01-02T04:00:00Z")
    closed = service.submit_event(event("e2", ts="2026-01-02T01:00:00Z", window_id="cross"))
    assert closed["status"] == "closed"
    assert closed["unmatched_reason"] == "window_closed"


def test_event_time_selects_different_versions_and_ignores_server_time(service, clock):
    service.replace_zones([
        circle("moving", version=1, start="2026-01-01T00:00:00Z", end="2026-01-02T00:00:00Z"),
        circle("moving", version=2, start="2026-01-02T00:00:00Z", end="2026-01-03T00:00:00Z"),
    ])
    clock.set("2026-12-31T00:00:00Z")
    old = service.submit_event(event("old", ts="2026-01-01T23:59:59Z"))
    new = service.submit_event(event("new", ts="2026-01-02T00:00:00Z"))
    assert old["zone"]["version"] == 1
    assert new["zone"]["version"] == 2


def test_batch_preserves_order_and_keeps_valid_results_after_failure(service):
    service.replace_zones([circle("z")])
    bad = event("bad", latitude=91)
    response = service.submit_batch({"events": [event("one"), bad, event("two")]})
    assert [item["index"] for item in response["results"]] == [0, 1, 2]
    assert response["results"][0]["ok"] is True
    assert response["results"][1]["ok"] is False
    assert response["results"][1]["error"]["field_path"] == "events[1].latitude"
    assert response["results"][2]["ok"] is True


def test_batch_uses_starting_snapshot_when_zones_change_during_processing(service):
    service.replace_zones([circle("z", version=1)])
    captured = service.snapshot(2)
    service.replace_zones([square("z", version=1)])
    response = service.submit_batch({"zone_version": 2, "events": [event()]})
    assert response["zone_version"] == 2
    assert response["results"][0]["ok"] is True
    assert response["results"][0]["result"]["zone"]["shape"]["type"] == "circle"


def test_failed_zone_update_is_atomic(service):
    service.replace_zones([circle("original")])
    good = circle("replacement")
    bad = circle("bad", start="2026-01-03T00:00:00Z", end="2026-01-02T00:00:00Z")
    with pytest.raises(ServiceError):
        service.replace_zones([good, bad])
    assert service.catalog_version == 2
    assert service.get_zone("original", "2026-01-02T00:00:00Z")["id"] == "original"
    with pytest.raises(ServiceError):
        service.get_zone("replacement", "2026-01-02T00:00:00Z")


def test_pagination_is_stable_when_new_events_are_inserted(service):
    service.replace_zones([circle("z")])
    for index in range(5):
        service.submit_event(event(f"e{index}", ts=f"2026-01-0{index + 1}T00:00:00Z"))
    first = service.query_records({}, limit=2)
    second = service.query_records({}, limit=2, cursor=first["next_cursor"])
    service.submit_event(event("inserted", ts="2025-12-31T00:00:00Z"))
    service.submit_event(event("appended", ts="2026-02-01T00:00:00Z"))
    second_after_insert = service.query_records({}, limit=2, cursor=first["next_cursor"])
    assert second["records"] == second_after_insert["records"]
    seen = [item["event_id"] for page in (first["records"], second_after_insert["records"]) for item in page]
    assert len(seen) == len(set(seen))


def test_pagination_filters_total_and_next_page_are_consistent(service):
    service.replace_zones([circle("z")])
    service.submit_event(event("matched-a", ts="2026-01-01T00:00:00Z"))
    service.submit_event(event("unmatched", lat=0, lon=0, ts="2026-01-02T00:00:00Z"))
    service.submit_event(event("matched-b", ts="2026-01-03T00:00:00Z"))
    page = service.query_records({"zone_id": "z"}, limit=1)
    assert page["total"] == 2
    assert [row["event_id"] for row in page["records"]] == ["matched-a"]
    assert page["next_cursor"]


def test_concurrent_page_reads_do_not_duplicate_or_skip(service):
    service.replace_zones([circle("z")])
    pages = []
    errors = []

    def read():
        try:
            first = service.query_records({}, limit=3)
            second = service.query_records({}, limit=3, cursor=first["next_cursor"]) if first["next_cursor"] else {"records": []}
            pages.append([row["event_id"] for row in first["records"] + second["records"]])
        except Exception as exc:
            errors.append(exc)

    readers = [threading.Thread(target=read) for _ in range(4)]
    writers = [threading.Thread(target=lambda i=i: service.submit_event(event(f"c{i}", ts=f"2026-01-{i+1:02d}T00:00:00Z"))) for i in range(4)]
    for worker in readers + writers:
        worker.start()
    for worker in readers + writers:
        worker.join()
    assert not errors
    assert all(len(ids) == len(set(ids)) for ids in pages)


def test_restart_preserves_confirmed_match_without_timezone_dependence(tmp_path, service):
    store = JsonStateStore(tmp_path / "state.json")
    service.store = store
    service.replace_zones([circle("z")])
    service.submit_event(event())
    restarted = GeofenceService(clock=Clock("2030-01-01T00:00:00+09:00"), store=store)
    restored = restarted.query_records({})
    assert restored["records"][0]["zone_id"] == "z"
    assert restored["records"][0]["timestamp"].endswith("Z")
    service.store = None


def test_reset_interface_clears_zones_events_windows_and_clock(service, clock):
    service.replace_zones([circle("z")])
    service.put_window({"id": "w", "start": "2026-01-01T00:00:00Z",
                        "end": "2026-01-02T00:00:00Z", "late_until": "2026-01-03T00:00:00Z"})
    service.submit_event(event())
    result = service.reset()
    assert result == {"zones": "cleared", "events": "cleared", "windows": "cleared", "clock": "reset"}
    assert service.query_records({})["records"] == []
    assert service.snapshot().zones == ()
