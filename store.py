from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from pathlib import Path
from typing import Any, Protocol


class StateStore(Protocol):
    def load(self) -> dict[str, Any]: ...
    def save(self, state: dict[str, Any]) -> None: ...
    def clear(self) -> None: ...


class JsonStateStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        with self.path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def save(self, state: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(prefix=self.path.name + ".", dir=str(self.path.parent))
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(state, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                handle.write("\n")
            os.replace(temporary_name, self.path)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()


class SqliteStateStore:
    def __init__(self, path: str | Path):
        self.path = ":memory:" if str(path) == ":memory:" else str(Path(path))
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.execute("CREATE TABLE IF NOT EXISTS service_state (id INTEGER PRIMARY KEY CHECK (id = 1), payload TEXT NOT NULL)")
        self._connection.commit()

    def load(self) -> dict[str, Any]:
        row = self._connection.execute("SELECT payload FROM service_state WHERE id = 1").fetchone()
        return json.loads(row[0]) if row else {}

    def save(self, state: dict[str, Any]) -> None:
        payload = json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        with self._connection:
            self._connection.execute(
                "INSERT INTO service_state(id, payload) VALUES (1, ?) "
                "ON CONFLICT(id) DO UPDATE SET payload = excluded.payload",
                (payload,),
            )

    def clear(self) -> None:
        with self._connection:
            self._connection.execute("DELETE FROM service_state")

    def close(self) -> None:
        self._connection.close()


def create_store(path: str | Path) -> StateStore:
    if str(path).endswith(".db") or str(path).endswith(".sqlite"):
        return SqliteStateStore(path)
    return JsonStateStore(path)
