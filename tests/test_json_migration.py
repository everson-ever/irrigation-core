import json
from pathlib import Path

import pytest

from irrigation.domain.exceptions import ValidationError
from irrigation.infrastructure.json_migration import migrate_legacy_json
from irrigation.infrastructure.sqlite_repository import (
    ScheduleSqliteRepository,
    SqliteRepository,
    connect_database,
)


def _write_json_lines(path, records):
    path.write_text("".join(json.dumps(record) + "\n" for record in records))


def test_migration_preserves_ids_and_normalizes_weekdays(tmp_path):
    _write_json_lines(
        tmp_path / "schedules.json",
        [
            {
                "id": "4",
                "time": "06:30",
                "duration_minutes": "15",
                "valve_pin": "13",
                "status": 0,
                "enabled": 1,
                "weekdays": ["fri", "mon"],
            }
        ],
    )
    _write_json_lines(
        tmp_path / "valves.json",
        [{"id": "8", "pin": "13", "section": "Horta", "status": 0}],
    )
    _write_json_lines(
        tmp_path / "settings.json",
        [{"id": "1", "default_duration_minutes": 5}],
    )
    _write_json_lines(
        tmp_path / "history.json",
        [
            {
                "id": "12",
                "valve": "Horta",
                "date": "2026-07-16",
                "start": "10:00",
                "end": "10:05",
                "weekday": "Thursday",
                "mode": "Manual",
            }
        ],
    )
    database_path = tmp_path / "irrigation.db"

    assert migrate_legacy_json(tmp_path, database_path) is True
    assert migrate_legacy_json(tmp_path, database_path) is False

    connection = connect_database(database_path)
    assert ScheduleSqliteRepository(connection).list_all()[0]["id"] == "4"
    assert ScheduleSqliteRepository(connection).list_all()[0]["weekdays"] == [
        "mon",
        "fri",
    ]
    assert SqliteRepository(connection, "valves").list_all()[0]["id"] == "8"
    assert SqliteRepository(connection, "settings").list_all()[0]["id"] == "1"
    assert SqliteRepository(connection, "history").list_all()[0]["id"] == "12"


def test_migration_tolerates_a_torn_final_json_line(tmp_path):
    (tmp_path / "history.json").write_text(
        json.dumps(
            {
                "id": "1",
                "valve": "Horta",
                "date": "2026-07-16",
                "start": "10:00",
                "end": "10:05",
                "weekday": "Thursday",
                "mode": "Manual",
            }
        )
        + '\n{"id":"2"'
    )

    assert migrate_legacy_json(tmp_path, tmp_path / "irrigation.db") is True
    connection = connect_database(tmp_path / "irrigation.db")
    assert [
        item["id"] for item in SqliteRepository(connection, "history").list_all()
    ] == ["1"]


def test_failed_migration_leaves_no_database_to_block_retry(tmp_path):
    (tmp_path / "history.json").write_text("not-json\n")
    database_path = tmp_path / "irrigation.db"

    with pytest.raises(ValidationError):
        migrate_legacy_json(tmp_path, database_path)

    assert not database_path.exists()


def test_deployment_database_contains_the_default_settings_row():
    database_path = (
        Path(__file__).resolve().parents[1]
        / "deploy"
        / "data-defaults"
        / "irrigation.db"
    )
    connection = connect_database(database_path)

    assert SqliteRepository(connection, "settings").list_all() == [
        {"id": "1", "default_duration_minutes": 5}
    ]
    assert SqliteRepository(connection, "valves").list_all() == []
    assert (
        connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name = 'runtime_health'"
        ).fetchone()
        is not None
    )
    assert connection.execute("SELECT count(*) FROM runtime_health").fetchone()[0] == 0
    assert {
        row["name"]
        for row in connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name IN ('sensors', 'sensor_state')"
        ).fetchall()
    } == {"sensors", "sensor_state"}
    assert (
        connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name = 'discord_notifications'"
        ).fetchone()
        is not None
    )
    assert (
        connection.execute("SELECT count(*) FROM discord_notifications").fetchone()[0]
        == 0
    )
