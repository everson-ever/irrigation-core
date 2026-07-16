"""SQLite persistence for irrigation data."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from irrigation.domain.exceptions import RecordNotFoundError, ValidationError
from irrigation.domain.models import WEEKDAY_IDS, Schedule

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

CREATE INDEX IF NOT EXISTS idx_history_date ON history(date);
"""

_TABLE_COLUMNS = {
    "valves": ("pin", "section", "status", "manually_turned_off"),
    "settings": ("default_duration_minutes",),
    "credentials": ("username", "password_hash"),
    "history": ("valve", "date", "start", "end", "weekday", "mode"),
}


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

    def _values(self, data: Mapping[str, Any]) -> dict[str, Any]:
        return {column: data[column] for column in self.columns if column in data}

    def _record(self, row: sqlite3.Row) -> dict[str, Any]:
        record = {column: row[column] for column in self.columns}
        record["id"] = str(row["id"])
        if self.table == "valves":
            record["pin"] = str(record["pin"])
        return {"id": record.pop("id"), **record}


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
