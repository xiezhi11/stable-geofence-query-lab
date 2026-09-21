from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

import pytest

from geofence import Clock, ExternalNotifier, GeofenceService
from geofence import format_time


@dataclass
class CaseReport:
    name: str
    input_version: Any
    clock: str
    cleanup: str = "pending"
    pollution_source: str | None = None


@pytest.fixture
def clock() -> Clock:
    fixed = Clock("2026-01-01T00:00:00Z")
    yield fixed


@pytest.fixture
def notifications() -> list[dict[str, Any]]:
    return []


@pytest.fixture
def service(clock: Clock, notifications: list[dict[str, Any]]) -> GeofenceService:
    target = GeofenceService(clock=clock, notifier=ExternalNotifier(notifications.append))
    target.reset()
    clock.set("2026-01-01T00:00:00Z")
    yield target
    target.reset()


@pytest.fixture(autouse=True)
def case_report(request: pytest.FixtureRequest, service: GeofenceService, clock: Clock):
    report = CaseReport(request.node.name, service.catalog_version, format_time(clock.now()))
    yield
    report.input_version = service.catalog_version
    report.clock = format_time(clock.now())
    service.reset()
    polluted = bool(service.records or service.zones or service.windows)
    report.cleanup = "pollution_detected" if polluted else "verified_clean"
    if polluted:
        report.pollution_source = request.node.name
    tmp_path = Path(request.config._tmp_path_factory.getbasetemp())
    (tmp_path / f"{request.node.name}.json").write_text(
        json.dumps([asdict(report)], ensure_ascii=False, indent=2), encoding="utf-8"
    )


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    root = Path(session.config.rootpath)
    artifacts = root / "test-reports"
    artifacts.mkdir(exist_ok=True)
    rows = []
    tmp_root = Path(str(session.config._tmp_path_factory.getbasetemp()))
    for path in tmp_root.glob("*.json"):
        rows.extend(json.loads(path.read_text(encoding="utf-8")))
    (artifacts / "cases.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# Case Replay Report", "", "| Sample | Input version | Clock | Cleanup | Pollution source |", "| --- | --- | --- | --- | --- |"]
    for row in rows:
        lines.append(
            f"| {row['name']} | {row['input_version']} | {row['clock']} | {row['cleanup']} | {row.get('pollution_source') or '-'} |"
        )
    (artifacts / "cases.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
