"""One-time import of legacy JSON Lines data into SQLite."""

from __future__ import annotations

import fcntl
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from irrigation.infrastructure.json_repository import JsonLinesRepository
from irrigation.infrastructure.sqlite_repository import (
    ScheduleSqliteRepository,
    SqliteRepository,
    _write_transaction,
    connect_database,
)

LEGACY_FILES = {
    "schedules": "schedules.json",
    "valves": "valves.json",
    "settings": "settings.json",
    "history": "history.json",
}


def migrate_legacy_json(data_dir: Path, database_path: Path) -> bool:
    """Import legacy files exactly once, preserving their record IDs."""
    if database_path.exists():
        return False

    data_dir.mkdir(parents=True, exist_ok=True)
    paths = {table: data_dir / name for table, name in LEGACY_FILES.items()}
    existing = {table: path for table, path in paths.items() if path.exists()}
    if not existing:
        return False

    with _migration_lock(database_path):
        if database_path.exists():
            return False
        records = {
            table: JsonLinesRepository(path).list_all()
            for table, path in existing.items()
        }
        temporary_path = database_path.with_name(f".{database_path.name}.migrating")
        _remove_database_files(temporary_path)
        connection: sqlite3.Connection | None = None
        try:
            connection = connect_database(temporary_path)
            repositories = {
                "schedules": ScheduleSqliteRepository(connection),
                "valves": SqliteRepository(connection, "valves"),
                "settings": SqliteRepository(connection, "settings"),
                "history": SqliteRepository(connection, "history"),
            }
            with _write_transaction(connection):
                for table, table_records in records.items():
                    repositories[table]._replace_all(table_records)
            connection.close()
            connection = None
            os.replace(temporary_path, database_path)
            return True
        finally:
            if connection is not None:
                connection.close()
            _remove_database_files(temporary_path)


@contextmanager
def _migration_lock(database_path: Path) -> Iterator[None]:
    lock_path = database_path.with_name(f".{database_path.name}.migration.lock")
    with lock_path.open("a", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _remove_database_files(database_path: Path) -> None:
    for suffix in ("", "-wal", "-shm"):
        (database_path.parent / f"{database_path.name}{suffix}").unlink(missing_ok=True)
