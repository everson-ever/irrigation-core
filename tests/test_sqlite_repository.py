import sqlite3

import pytest

from irrigation.application.services import HistorySettingsService, SettingsService
from irrigation.domain.exceptions import RecordNotFoundError, ValidationError
from irrigation.infrastructure.sqlite_repository import (
    ScheduleSqliteRepository,
    SqliteRepository,
    connect_database,
)


def test_generic_repository_crud_and_replace_all(tmp_path):
    connection = connect_database(tmp_path / "irrigation.db")
    repository = SqliteRepository(connection, "valves")

    first = repository.add({"pin": "13", "section": "Horta", "status": 0})
    second = repository.add({"pin": "11", "section": "Jardim", "status": 0})
    updated = repository.update({**first, "status": 1})

    assert first["id"] == "1"
    assert second["id"] == "2"
    assert updated["status"] == 1
    assert repository.delete(["2", "999"]) is True
    assert repository.delete(["2", "999"]) is False

    repository.replace_all([{"id": "7", "pin": "15", "section": "Frente", "status": 0}])

    assert repository.list_all() == [
        {
            "id": "7",
            "pin": "15",
            "section": "Frente",
            "status": 0,
            "manually_turned_off": 0,
        }
    ]


def test_update_missing_record_fails(tmp_path):
    repository = SqliteRepository(
        connect_database(tmp_path / "irrigation.db"), "settings"
    )

    with pytest.raises(RecordNotFoundError):
        repository.update({"id": "1", "default_duration_minutes": 5})


def test_settings_service_inserts_once_then_updates_the_single_row(tmp_path):
    repository = SqliteRepository(
        connect_database(tmp_path / "irrigation.db"), "settings"
    )
    service = SettingsService(repository)

    assert repository.list_all() == []
    assert service.update_default_duration(5) == {
        "id": "1",
        "default_duration_minutes": 5,
    }
    assert service.update_default_duration(10) == {
        "id": "1",
        "default_duration_minutes": 10,
    }
    assert repository.list_all() == [{"id": "1", "default_duration_minutes": 10}]


def test_history_settings_service_defaults_then_updates_the_single_row(tmp_path):
    repository = SqliteRepository(
        connect_database(tmp_path / "irrigation.db"), "history_settings"
    )
    service = HistorySettingsService(repository)

    assert repository.list_all() == []
    assert service.retention_days() == 7

    assert service.update_retention_days(15) == {"id": "1", "retention_days": 15}
    assert service.retention_days() == 15

    assert service.update_retention_days(90) == {"id": "1", "retention_days": 90}
    assert repository.list_all() == [{"id": "1", "retention_days": 90}]


@pytest.mark.parametrize("value", [1, 10, 200, "not-a-number", None])
def test_history_settings_service_rejects_disallowed_periods(tmp_path, value):
    repository = SqliteRepository(
        connect_database(tmp_path / "irrigation.db"), "history_settings"
    )
    service = HistorySettingsService(repository)

    with pytest.raises(ValidationError):
        service.update_retention_days(value)


def test_schedule_weekdays_are_normalized_replaced_and_cascaded(tmp_path):
    connection = connect_database(tmp_path / "irrigation.db")
    repository = ScheduleSqliteRepository(connection)
    schedule = repository.add(
        {
            "time": "06:30",
            "duration_minutes": "15",
            "valve_pin": "13",
            "status": 0,
            "enabled": 1,
            "weekdays": ["fri", "mon", "wed"],
        }
    )

    assert schedule["weekdays"] == ["mon", "wed", "fri"]

    updated = repository.update({**schedule, "weekdays": ["tue", "thu"]})

    assert updated["weekdays"] == ["tue", "thu"]
    assert (
        connection.execute(
            "SELECT COUNT(*) FROM schedule_weekdays WHERE schedule_id = 1"
        ).fetchone()[0]
        == 2
    )

    assert repository.delete(["1"]) is True
    assert (
        connection.execute("SELECT COUNT(*) FROM schedule_weekdays").fetchone()[0] == 0
    )


def test_history_range_query_is_inclusive(tmp_path):
    repository = SqliteRepository(
        connect_database(tmp_path / "irrigation.db"), "history"
    )
    for record_id, day in enumerate(
        ("2026-07-01", "2026-07-10", "2026-07-31", "2026-08-01"), start=1
    ):
        repository.add(
            {
                "valve": f"Válvula {record_id}",
                "date": day,
                "start": "10:00",
                "end": "10:05",
                "weekday": "Wednesday",
                "mode": "Manual",
            }
        )

    assert [
        item["date"]
        for item in repository.find_by_date_range("2026-07-10", "2026-07-31")
    ] == ["2026-07-10", "2026-07-31"]


def test_delete_before_prunes_only_older_records(tmp_path):
    repository = SqliteRepository(
        connect_database(tmp_path / "irrigation.db"), "history"
    )
    for record_id, day in enumerate(
        ("2026-07-01", "2026-07-09", "2026-07-10", "2026-07-16"), start=1
    ):
        repository.add(
            {
                "valve": f"Válvula {record_id}",
                "date": day,
                "start": "10:00",
                "end": "10:05",
                "weekday": "Wednesday",
                "mode": "Manual",
            }
        )

    assert repository.delete_before("2026-07-10") == 2
    assert [item["date"] for item in repository.list_all()] == [
        "2026-07-10",
        "2026-07-16",
    ]
    assert repository.delete_before("2026-07-10") == 0


def test_delete_before_rejects_non_history_tables(tmp_path):
    repository = SqliteRepository(
        connect_database(tmp_path / "irrigation.db"), "valves"
    )

    with pytest.raises(ValueError):
        repository.delete_before("2026-07-10")


def test_two_connections_observe_each_others_writes(tmp_path):
    database_path = tmp_path / "irrigation.db"
    first = SqliteRepository(connect_database(database_path), "history")
    second = SqliteRepository(connect_database(database_path), "history")

    first.add(
        {
            "valve": "Horta",
            "date": "2026-07-16",
            "start": "10:00",
            "end": "10:05",
            "weekday": "Thursday",
            "mode": "Manual",
        }
    )

    assert second.find_by_id("1")["valve"] == "Horta"


def test_wal_foreign_keys_and_busy_timeout_are_enabled(tmp_path):
    connection = connect_database(tmp_path / "irrigation.db")

    assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    assert isinstance(connection, sqlite3.Connection)
