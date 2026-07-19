"""SQLite persistence for irrigation data."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from irrigation.domain.exceptions import RecordNotFoundError, ValidationError
from irrigation.domain.models import WEEKDAY_IDS, NotificationEvent, Schedule

SCHEMA = """
CREATE TABLE IF NOT EXISTS schedules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    time TEXT NOT NULL,
    duration_minutes INTEGER NOT NULL CHECK (duration_minutes > 0),
    valve_pin INTEGER NOT NULL CHECK (valve_pin > 0),
    status INTEGER NOT NULL DEFAULT 0 CHECK (status IN (0, 1)),
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1))
);

CREATE TABLE IF NOT EXISTS schedule_weekdays (
    schedule_id INTEGER NOT NULL REFERENCES schedules(id) ON DELETE CASCADE,
    weekday TEXT NOT NULL CHECK (
        weekday IN ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')
    ),
    PRIMARY KEY (schedule_id, weekday)
);

CREATE TABLE IF NOT EXISTS valves (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pin INTEGER NOT NULL UNIQUE,
    section TEXT NOT NULL,
    status INTEGER NOT NULL DEFAULT 0 CHECK (status IN (0, 1)),
    manually_turned_off INTEGER NOT NULL DEFAULT 0
        CHECK (manually_turned_off IN (0, 1))
);

CREATE TABLE IF NOT EXISTS sensors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL COLLATE NOCASE UNIQUE,
    kind TEXT NOT NULL CHECK (
        kind IN (
            'reservoir_level', 'flow', 'soil_moisture',
            'line_pressure', 'rain'
        )
    ),
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    valve_id INTEGER REFERENCES valves(id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sensor_state (
    sensor_id INTEGER PRIMARY KEY REFERENCES sensors(id) ON DELETE CASCADE,
    health TEXT NOT NULL DEFAULT 'unknown' CHECK (
        health IN ('unknown', 'ok', 'warning', 'fault', 'stale')
    ),
    value_json TEXT,
    unit TEXT,
    raw_value_json TEXT,
    latest_read_at TEXT,
    error_message TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    default_duration_minutes INTEGER NOT NULL
        CHECK (default_duration_minutes > 0)
);

CREATE TABLE IF NOT EXISTS credentials (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    valve TEXT NOT NULL,
    date TEXT NOT NULL,
    start TEXT NOT NULL,
    end TEXT NOT NULL,
    weekday TEXT NOT NULL,
    mode TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runtime_health (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    last_seen_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS history_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    retention_days INTEGER NOT NULL CHECK (retention_days IN (7, 15, 30, 90))
);

CREATE TABLE IF NOT EXISTS discord_notifications (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    webhook_url TEXT,
    section_on INTEGER NOT NULL DEFAULT 0 CHECK (section_on IN (0, 1)),
    section_off INTEGER NOT NULL DEFAULT 0 CHECK (section_off IN (0, 1)),
    schedule_restarted INTEGER NOT NULL DEFAULT 0
        CHECK (schedule_restarted IN (0, 1)),
    schedule_created INTEGER NOT NULL DEFAULT 0
        CHECK (schedule_created IN (0, 1)),
    schedule_updated INTEGER NOT NULL DEFAULT 0
        CHECK (schedule_updated IN (0, 1)),
    schedule_deleted INTEGER NOT NULL DEFAULT 0
        CHECK (schedule_deleted IN (0, 1)),
    section_created INTEGER NOT NULL DEFAULT 0
        CHECK (section_created IN (0, 1)),
    section_updated INTEGER NOT NULL DEFAULT 0
        CHECK (section_updated IN (0, 1)),
    section_deleted INTEGER NOT NULL DEFAULT 0
        CHECK (section_deleted IN (0, 1)),
    password_changed INTEGER NOT NULL DEFAULT 0
        CHECK (password_changed IN (0, 1))
);

CREATE INDEX IF NOT EXISTS idx_history_date ON history(date);
CREATE INDEX IF NOT EXISTS idx_sensors_valve_id ON sensors(valve_id);
"""

_TABLE_COLUMNS = {
    "valves": ("pin", "section", "status", "manually_turned_off"),
    "settings": ("default_duration_minutes",),
    "credentials": ("username", "password_hash"),
    "history": ("valve", "date", "start", "end", "weekday", "mode"),
    "history_settings": ("retention_days",),
}


def _ensure_discord_notification_columns(
    connection: sqlite3.Connection,
) -> None:
    existing = {
        str(row["name"])
        for row in connection.execute(
            "PRAGMA table_info(discord_notifications)"
        ).fetchall()
    }
    for event in NotificationEvent:
        if event.value in existing:
            continue
        try:
            connection.execute(
                f"ALTER TABLE discord_notifications ADD COLUMN {event.value} "
                f"INTEGER NOT NULL DEFAULT 0 CHECK ({event.value} IN (0, 1))"
            )
        except sqlite3.OperationalError:
            refreshed = {
                str(row["name"])
                for row in connection.execute(
                    "PRAGMA table_info(discord_notifications)"
                ).fetchall()
            }
            if event.value not in refreshed:
                raise
    legacy_sources = {
        NotificationEvent.SECTION_ON.value: ("manual_on", "schedule_on"),
        NotificationEvent.SECTION_OFF.value: ("manual_off", "schedule_off"),
    }
    for target, candidates in legacy_sources.items():
        sources = [column for column in candidates if column in existing]
        if not sources:
            continue
        enabled_expression = " OR ".join(
            f"COALESCE({column}, 0) = 1" for column in sources
        )
        connection.execute(
            f"UPDATE discord_notifications SET {target} = 1 "
            f"WHERE {target} = 0 AND ({enabled_expression})"
        )
        connection.execute(
            "UPDATE discord_notifications SET "
            + ", ".join(f"{column} = 0" for column in sources)
        )


def connect_database(database_path: str | Path) -> sqlite3.Connection:
    """Open and initialize an irrigation database connection."""
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=5, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.executescript(SCHEMA)
    _ensure_discord_notification_columns(connection)
    return connection


@contextmanager
def _write_transaction(connection: sqlite3.Connection) -> Iterator[None]:
    connection.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        connection.rollback()
        raise
    else:
        connection.commit()


class SqliteRepository:
    """Repository for a single non-relational irrigation table."""

    def __init__(self, connection: sqlite3.Connection, table: str) -> None:
        if table not in _TABLE_COLUMNS:
            raise ValueError(f"unsupported SQLite repository table: {table}")
        self.connection = connection
        self.table = table
        self.columns = _TABLE_COLUMNS[table]

    def list_all(self) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            f"SELECT id, {', '.join(self.columns)} FROM {self.table} ORDER BY id"
        ).fetchall()
        return [self._record(row) for row in rows]

    def find_by_id(self, record_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            f"SELECT id, {', '.join(self.columns)} FROM {self.table} WHERE id = ?",
            (str(record_id),),
        ).fetchone()
        return None if row is None else self._record(row)

    def add(self, data: Mapping[str, Any]) -> dict[str, Any]:
        values = self._values(data)
        with _write_transaction(self.connection):
            cursor = self.connection.execute(
                f"INSERT INTO {self.table} ({', '.join(values)}) "
                f"VALUES ({', '.join('?' for _ in values)})",
                tuple(values.values()),
            )
            record_id = str(cursor.lastrowid)
        record = self.find_by_id(record_id)
        assert record is not None
        return record

    def update(self, data: Mapping[str, Any]) -> dict[str, Any]:
        record_id = str(data.get("id", ""))
        if not record_id:
            raise ValidationError("id is required for update")
        values = self._values(data)
        if set(values) != set(self.columns):
            raise ValidationError(f"all {self.table} fields are required for update")
        with _write_transaction(self.connection):
            cursor = self.connection.execute(
                f"UPDATE {self.table} SET "
                + ", ".join(f"{column} = ?" for column in self.columns)
                + " WHERE id = ?",
                (*[values[column] for column in self.columns], record_id),
            )
            if cursor.rowcount == 0:
                raise RecordNotFoundError(f"record {record_id} not found")
        record = self.find_by_id(record_id)
        assert record is not None
        return record

    def delete(self, ids: Sequence[str]) -> bool:
        targets = tuple(str(item) for item in ids)
        if not targets:
            return False
        with _write_transaction(self.connection):
            cursor = self.connection.execute(
                f"DELETE FROM {self.table} "
                f"WHERE id IN ({', '.join('?' for _ in targets)})",
                targets,
            )
        return cursor.rowcount > 0

    def replace_all(self, records: Sequence[Mapping[str, Any]]) -> None:
        with _write_transaction(self.connection):
            self._replace_all(records)

    def _replace_all(self, records: Sequence[Mapping[str, Any]]) -> None:
        self.connection.execute(f"DELETE FROM {self.table}")
        for record in records:
            values = self._values(record)
            record_id = str(record.get("id", ""))
            columns = (["id"] if record_id else []) + list(values)
            parameters = ([record_id] if record_id else []) + list(values.values())
            self.connection.execute(
                f"INSERT INTO {self.table} ({', '.join(columns)}) "
                f"VALUES ({', '.join('?' for _ in columns)})",
                parameters,
            )

    def find_by_date_range(
        self, start_date: str, end_date: str
    ) -> list[dict[str, Any]]:
        if self.table != "history":
            raise ValueError("date range queries are only supported for history")
        rows = self.connection.execute(
            "SELECT id, valve, date, start, end, weekday, mode "
            "FROM history WHERE date BETWEEN ? AND ? ORDER BY id",
            (start_date, end_date),
        ).fetchall()
        return [self._record(row) for row in rows]

    def delete_before(self, cutoff_date: str) -> int:
        if self.table != "history":
            raise ValueError("retention deletes are only supported for history")
        with _write_transaction(self.connection):
            cursor = self.connection.execute(
                "DELETE FROM history WHERE date < ?", (cutoff_date,)
            )
        return cursor.rowcount

    def _values(self, data: Mapping[str, Any]) -> dict[str, Any]:
        return {column: data[column] for column in self.columns if column in data}

    def _record(self, row: sqlite3.Row) -> dict[str, Any]:
        record = {column: row[column] for column in self.columns}
        record["id"] = str(row["id"])
        if self.table == "valves":
            record["pin"] = str(record["pin"])
        return {"id": record.pop("id"), **record}


class RuntimeHealthSqliteRepository:
    """Stores the automatic controller heartbeat."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def touch(self, last_seen_at: str) -> None:
        with _write_transaction(self.connection):
            self.connection.execute(
                """
                INSERT INTO runtime_health (id, last_seen_at)
                VALUES (1, ?)
                ON CONFLICT(id) DO UPDATE SET last_seen_at = excluded.last_seen_at
                """,
                (last_seen_at,),
            )

    def last_seen_at(self) -> str | None:
        row = self.connection.execute(
            "SELECT last_seen_at FROM runtime_health WHERE id = 1"
        ).fetchone()
        return None if row is None else str(row["last_seen_at"])


class DiscordNotificationSqliteRepository:
    """Stores the single Discord webhook and its fixed event flags."""

    event_columns = tuple(event.value for event in NotificationEvent)

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def get(self) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT webhook_url, "
            + ", ".join(self.event_columns)
            + " FROM discord_notifications WHERE id = 1"
        ).fetchone()
        if row is None:
            return None
        return {
            "webhook_url": row["webhook_url"],
            "enabled_events": [
                event for event in self.event_columns if bool(row[event])
            ],
        }

    def save_webhook(self, webhook_url: str) -> dict[str, Any]:
        with _write_transaction(self.connection):
            self.connection.execute(
                """
                INSERT INTO discord_notifications (id, webhook_url)
                VALUES (1, ?)
                ON CONFLICT(id) DO UPDATE SET webhook_url = excluded.webhook_url
                """,
                (webhook_url,),
            )
        record = self.get()
        assert record is not None
        return record

    def delete_webhook(self) -> dict[str, Any]:
        assignments = ", ".join(f"{column} = 0" for column in self.event_columns)
        with _write_transaction(self.connection):
            self.connection.execute(
                "INSERT INTO discord_notifications (id, webhook_url) "
                "VALUES (1, NULL) ON CONFLICT(id) DO NOTHING"
            )
            self.connection.execute(
                f"UPDATE discord_notifications SET webhook_url = NULL, {assignments} "
                "WHERE id = 1"
            )
        record = self.get()
        assert record is not None
        return record

    def set_event_enabled(self, event: str, enabled: bool) -> dict[str, Any]:
        if event not in self.event_columns:
            raise ValidationError(f"unknown notification event: {event}")
        with _write_transaction(self.connection):
            self.connection.execute(
                "INSERT INTO discord_notifications (id, webhook_url) "
                "VALUES (1, NULL) ON CONFLICT(id) DO NOTHING"
            )
            self.connection.execute(
                f"UPDATE discord_notifications SET {event} = ? WHERE id = 1",
                (int(enabled),),
            )
        record = self.get()
        assert record is not None
        return record


class SensorSqliteRepository:
    """Persists common sensor configuration and its initial state atomically."""

    columns = ("name", "kind", "enabled", "valve_id", "created_at", "updated_at")

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def list_all(self) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT id, name, kind, enabled, valve_id, created_at, updated_at "
            "FROM sensors ORDER BY name COLLATE NOCASE, id"
        ).fetchall()
        return [self._record(row) for row in rows]

    def find_by_id(self, record_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT id, name, kind, enabled, valve_id, created_at, updated_at "
            "FROM sensors WHERE id = ?",
            (str(record_id),),
        ).fetchone()
        return None if row is None else self._record(row)

    def add(self, data: Mapping[str, Any]) -> dict[str, Any]:
        values = self._values(data)
        if set(values) != set(self.columns):
            raise ValidationError("all sensor fields are required for add")
        try:
            with _write_transaction(self.connection):
                cursor = self.connection.execute(
                    "INSERT INTO sensors "
                    f"({', '.join(self.columns)}) VALUES "
                    f"({', '.join('?' for _ in self.columns)})",
                    tuple(values[column] for column in self.columns),
                )
                record_id = str(cursor.lastrowid)
                self.connection.execute(
                    "INSERT INTO sensor_state "
                    "(sensor_id, health, updated_at) VALUES (?, 'unknown', ?)",
                    (record_id, values["created_at"]),
                )
        except sqlite3.IntegrityError as exc:
            raise ValidationError(self._integrity_message(exc)) from exc
        record = self.find_by_id(record_id)
        assert record is not None
        return record

    def update(self, data: Mapping[str, Any]) -> dict[str, Any]:
        record_id = str(data.get("id", "")).strip()
        if not record_id:
            raise ValidationError("id is required for update")
        values = self._values(data)
        if set(values) != set(self.columns):
            raise ValidationError("all sensor fields are required for update")
        try:
            with _write_transaction(self.connection):
                cursor = self.connection.execute(
                    "UPDATE sensors SET "
                    + ", ".join(f"{column} = ?" for column in self.columns)
                    + " WHERE id = ?",
                    (*[values[column] for column in self.columns], record_id),
                )
                if cursor.rowcount == 0:
                    raise RecordNotFoundError(f"sensor {record_id} not found")
        except sqlite3.IntegrityError as exc:
            raise ValidationError(self._integrity_message(exc)) from exc
        record = self.find_by_id(record_id)
        assert record is not None
        return record

    def delete(self, ids: Sequence[str]) -> bool:
        targets = tuple(str(item) for item in ids)
        if not targets:
            return False
        with _write_transaction(self.connection):
            cursor = self.connection.execute(
                f"DELETE FROM sensors WHERE id IN ({', '.join('?' for _ in targets)})",
                targets,
            )
        return cursor.rowcount > 0

    def replace_all(self, records: Sequence[Mapping[str, Any]]) -> None:
        with _write_transaction(self.connection):
            self.connection.execute("DELETE FROM sensors")
            for record in records:
                values = self._values(record)
                record_id = str(record.get("id", "")).strip()
                columns = (["id"] if record_id else []) + list(self.columns)
                parameters = ([record_id] if record_id else []) + [
                    values[column] for column in self.columns
                ]
                cursor = self.connection.execute(
                    f"INSERT INTO sensors ({', '.join(columns)}) VALUES "
                    f"({', '.join('?' for _ in columns)})",
                    parameters,
                )
                sensor_id = record_id or str(cursor.lastrowid)
                self.connection.execute(
                    "INSERT INTO sensor_state "
                    "(sensor_id, health, updated_at) VALUES (?, 'unknown', ?)",
                    (sensor_id, values["created_at"]),
                )

    def _values(self, data: Mapping[str, Any]) -> dict[str, Any]:
        return {column: data[column] for column in self.columns if column in data}

    @staticmethod
    def _record(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "name": str(row["name"]),
            "kind": str(row["kind"]),
            "enabled": row["enabled"],
            "valve_id": None if row["valve_id"] is None else str(row["valve_id"]),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
        }

    @staticmethod
    def _integrity_message(exc: sqlite3.IntegrityError) -> str:
        message = str(exc).lower()
        if "sensors.name" in message or "unique constraint" in message:
            return "a sensor with this name already exists"
        if "foreign key" in message:
            return "associated valve/section does not exist"
        return "sensor configuration violates a persistence constraint"


class SensorStateSqliteRepository:
    """Stores only the latest generic snapshot for every sensor."""

    columns = (
        "health",
        "value_json",
        "unit",
        "raw_value_json",
        "latest_read_at",
        "error_message",
        "updated_at",
    )

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def list_all(self) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT sensor_id, health, value_json, unit, raw_value_json, "
            "latest_read_at, error_message, updated_at "
            "FROM sensor_state ORDER BY sensor_id"
        ).fetchall()
        return [self._record(row) for row in rows]

    def find_by_sensor_id(self, sensor_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT sensor_id, health, value_json, unit, raw_value_json, "
            "latest_read_at, error_message, updated_at "
            "FROM sensor_state WHERE sensor_id = ?",
            (str(sensor_id),),
        ).fetchone()
        return None if row is None else self._record(row)

    def upsert(self, data: Mapping[str, Any]) -> dict[str, Any]:
        sensor_id = str(data.get("sensor_id", "")).strip()
        if not sensor_id:
            raise ValidationError("sensor_id is required")
        values = {
            "health": data["health"],
            "value_json": self._json_value(data.get("value")),
            "unit": data.get("unit"),
            "raw_value_json": self._json_value(data.get("raw_value")),
            "latest_read_at": data.get("latest_read_at"),
            "error_message": data.get("error_message"),
            "updated_at": data["updated_at"],
        }
        try:
            with _write_transaction(self.connection):
                self.connection.execute(
                    "INSERT INTO sensor_state "
                    "(sensor_id, health, value_json, unit, raw_value_json, "
                    "latest_read_at, error_message, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(sensor_id) DO UPDATE SET "
                    "health = excluded.health, value_json = excluded.value_json, "
                    "unit = excluded.unit, raw_value_json = excluded.raw_value_json, "
                    "latest_read_at = excluded.latest_read_at, "
                    "error_message = excluded.error_message, "
                    "updated_at = excluded.updated_at",
                    (sensor_id, *[values[column] for column in self.columns]),
                )
        except sqlite3.IntegrityError as exc:
            raise RecordNotFoundError(f"sensor {sensor_id} not found") from exc
        record = self.find_by_sensor_id(sensor_id)
        assert record is not None
        return record

    @staticmethod
    def _json_value(value: Any) -> str | None:
        return None if value is None else json.dumps(value, ensure_ascii=False)

    @staticmethod
    def _record(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "sensor_id": str(row["sensor_id"]),
            "health": str(row["health"]),
            "value": (
                None if row["value_json"] is None else json.loads(row["value_json"])
            ),
            "unit": row["unit"],
            "raw_value": (
                None
                if row["raw_value_json"] is None
                else json.loads(row["raw_value_json"])
            ),
            "latest_read_at": row["latest_read_at"],
            "error_message": row["error_message"],
            "updated_at": str(row["updated_at"]),
        }


class ScheduleSqliteRepository:
    """Repository for schedules and their normalized weekday rows."""

    columns = (
        "time",
        "duration_minutes",
        "valve_pin",
        "status",
        "enabled",
    )

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def list_all(self) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT id, time, duration_minutes, valve_pin, status, enabled "
            "FROM schedules ORDER BY id"
        ).fetchall()
        return [self._record(row) for row in rows]

    def find_by_id(self, record_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT id, time, duration_minutes, valve_pin, status, enabled "
            "FROM schedules WHERE id = ?",
            (str(record_id),),
        ).fetchone()
        return None if row is None else self._record(row)

    def add(self, data: Mapping[str, Any]) -> dict[str, Any]:
        values = self._values(data)
        weekdays = self._weekdays(data)
        with _write_transaction(self.connection):
            cursor = self.connection.execute(
                "INSERT INTO schedules "
                f"({', '.join(values)}) VALUES "
                f"({', '.join('?' for _ in values)})",
                tuple(values.values()),
            )
            record_id = str(cursor.lastrowid)
            self._insert_weekdays(record_id, weekdays)
        record = self.find_by_id(record_id)
        assert record is not None
        return record

    def update(self, data: Mapping[str, Any]) -> dict[str, Any]:
        record_id = str(data.get("id", ""))
        if not record_id:
            raise ValidationError("id is required for update")
        values = self._values(data)
        if set(values) != set(self.columns):
            raise ValidationError("all schedule fields are required for update")
        weekdays = self._weekdays(data)
        with _write_transaction(self.connection):
            cursor = self.connection.execute(
                "UPDATE schedules SET "
                + ", ".join(f"{column} = ?" for column in self.columns)
                + " WHERE id = ?",
                (*[values[column] for column in self.columns], record_id),
            )
            if cursor.rowcount == 0:
                raise RecordNotFoundError(f"record {record_id} not found")
            self.connection.execute(
                "DELETE FROM schedule_weekdays WHERE schedule_id = ?", (record_id,)
            )
            self._insert_weekdays(record_id, weekdays)
        record = self.find_by_id(record_id)
        assert record is not None
        return record

    def delete(self, ids: Sequence[str]) -> bool:
        targets = tuple(str(item) for item in ids)
        if not targets:
            return False
        with _write_transaction(self.connection):
            cursor = self.connection.execute(
                "DELETE FROM schedules "
                f"WHERE id IN ({', '.join('?' for _ in targets)})",
                targets,
            )
        return cursor.rowcount > 0

    def replace_all(self, records: Sequence[Mapping[str, Any]]) -> None:
        with _write_transaction(self.connection):
            self._replace_all(records)

    def _replace_all(self, records: Sequence[Mapping[str, Any]]) -> None:
        self.connection.execute("DELETE FROM schedules")
        for record in records:
            values = self._values(record)
            record_id = str(record.get("id", ""))
            columns = (["id"] if record_id else []) + list(values)
            parameters = ([record_id] if record_id else []) + list(values.values())
            cursor = self.connection.execute(
                f"INSERT INTO schedules ({', '.join(columns)}) "
                f"VALUES ({', '.join('?' for _ in columns)})",
                parameters,
            )
            inserted_id = record_id or str(cursor.lastrowid)
            self._insert_weekdays(inserted_id, self._weekdays(record))

    def _record(self, row: sqlite3.Row) -> dict[str, Any]:
        weekday_rows = self.connection.execute(
            "SELECT weekday FROM schedule_weekdays WHERE schedule_id = ? "
            "ORDER BY CASE weekday "
            "WHEN 'mon' THEN 0 WHEN 'tue' THEN 1 WHEN 'wed' THEN 2 "
            "WHEN 'thu' THEN 3 WHEN 'fri' THEN 4 WHEN 'sat' THEN 5 ELSE 6 END",
            (row["id"],),
        ).fetchall()
        time = str(row["time"])
        times = list(
            Schedule.from_dict(
                {
                    "time": time,
                    "duration_minutes": row["duration_minutes"],
                    "valve_pin": row["valve_pin"],
                }
            ).times
        )
        return {
            "id": str(row["id"]),
            "time": time,
            "times": times,
            "duration_minutes": str(row["duration_minutes"]),
            "valve_pin": str(row["valve_pin"]),
            "status": row["status"],
            "enabled": row["enabled"],
            "weekdays": [item["weekday"] for item in weekday_rows],
        }

    def _values(self, data: Mapping[str, Any]) -> dict[str, Any]:
        return {column: data[column] for column in self.columns if column in data}

    @staticmethod
    def _weekdays(data: Mapping[str, Any]) -> tuple[str, ...]:
        raw_weekdays = data.get("weekdays", WEEKDAY_IDS)
        if isinstance(raw_weekdays, str):
            raise ValidationError("weekdays must be a list")
        try:
            selected = {str(weekday) for weekday in raw_weekdays}
        except TypeError as exc:
            raise ValidationError("weekdays must be a list") from exc
        unknown = selected.difference(WEEKDAY_IDS)
        if unknown:
            raise ValidationError(f"unknown weekday: {sorted(unknown)[0]}")
        weekdays = tuple(weekday for weekday in WEEKDAY_IDS if weekday in selected)
        if not weekdays:
            raise ValidationError("weekdays must contain at least one weekday")
        return weekdays

    def _insert_weekdays(self, record_id: str, weekdays: Sequence[str]) -> None:
        self.connection.executemany(
            "INSERT INTO schedule_weekdays (schedule_id, weekday) VALUES (?, ?)",
            ((record_id, weekday) for weekday in weekdays),
        )
