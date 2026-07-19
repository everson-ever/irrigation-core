from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from io import StringIO

import pytest

from irrigation.application.services import ScheduleService, SensorService, ValveService
from irrigation.cli import execute
from irrigation.domain.exceptions import ValidationError
from irrigation.domain.models import Sensor, SensorHealth, SensorKind, SensorState
from irrigation.infrastructure.gpio import MockGPIO
from irrigation.infrastructure.sqlite_repository import (
    ScheduleSqliteRepository,
    SensorSqliteRepository,
    SensorStateSqliteRepository,
    SqliteRepository,
    connect_database,
)


def _service(tmp_path):
    connection = connect_database(tmp_path / "irrigation.db")
    valves = ValveService(SqliteRepository(connection, "valves"), MockGPIO(15))
    return (
        SensorService(
            SensorSqliteRepository(connection),
            SensorStateSqliteRepository(connection),
            valves,
        ),
        valves,
        connection,
    )


def test_sensor_model_accepts_only_supported_kinds_and_serializes_timestamps():
    now = datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc)

    for kind in SensorKind:
        sensor = Sensor("1", "  Sensor principal  ", kind.value, 1, None, now, now)
        assert sensor.name == "Sensor principal"
        assert sensor.to_dict()["kind"] == kind.value
        assert sensor.to_dict()["created_at"] == now.isoformat()

    with pytest.raises(ValidationError, match="sensor kind must be one of"):
        Sensor("1", "Inválido", "temperature", True, None, now, now)
    with pytest.raises(ValidationError, match="sensor name is required"):
        Sensor("1", "  ", SensorKind.RAIN, True, None, now, now)
    with pytest.raises(ValidationError, match="enabled must be 0 or 1"):
        Sensor("1", "Chuva", SensorKind.RAIN, 2, None, now, now)


def test_sensor_state_supports_unknown_stale_and_actionable_fault_snapshots():
    now = datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc)
    unknown = SensorState.unknown("1", now)
    stale = SensorState("1", "stale", 41.5, "%", 13200, now, "Recalibre", now)
    fault = SensorState(
        "1", SensorHealth.FAULT, None, None, None, None, "Sem sinal", now
    )

    assert unknown.to_dict()["health"] == "unknown"
    assert stale.to_dict()["value"] == 41.5
    assert stale.to_dict()["raw_value"] == 13200
    assert fault.to_dict()["error_message"] == "Sem sinal"
    with pytest.raises(ValidationError, match="actionable error"):
        SensorState("1", "fault", None, None, None, None, None, now)


def test_sensor_service_validates_names_associations_and_status_presentation(tmp_path):
    service, valves, _ = _service(tmp_path)
    valve = valves.add(13, "Horta")
    sensor = service.add("Umidade Horta", "soil_moisture", 1, valve.id)

    assert sensor["section"] == "Horta"
    assert sensor["state"]["health"] == "unknown"
    assert sensor["availability"] == "unsupported"

    with pytest.raises(ValidationError, match="already exists"):
        service.add("umidade horta", "rain")
    with pytest.raises(ValidationError, match="does not exist"):
        service.add("Chuva", "rain", 1, "999")
    with pytest.raises(ValidationError, match="positive integer"):
        service.get("ambiguous-id")

    service.record_state(
        sensor["id"],
        "stale",
        value=48,
        unit="%",
        raw_value=12000,
        latest_read_at=datetime.now(timezone.utc),
        error_message="Leitura fora da janela de atualização",
    )
    assert service.status(sensor["id"])["availability"] == "stale"
    disabled = service.set_enabled(sensor["id"], 0)
    assert disabled["availability"] == "disabled"
    assert disabled["state"]["value"] == 48


def test_sensor_delete_cascades_latest_state_and_valve_delete_is_protected(tmp_path):
    service, valves, connection = _service(tmp_path)
    valve = valves.add(13, "Horta")
    sensor = service.add("Sensor associado", "rain", 1, valve.id)

    with pytest.raises(ValidationError, match="still used by a sensor"):
        valves.remove(
            valve.id,
            ScheduleService(ScheduleSqliteRepository(connection)),
            service,
        )

    assert service.remove(sensor["id"]) is True
    assert (
        SensorStateSqliteRepository(connection).find_by_sensor_id(sensor["id"]) is None
    )
    assert service.remove(sensor["id"]) is False


def test_sensor_schema_is_added_to_an_existing_database(tmp_path):
    path = tmp_path / "existing.db"
    legacy = sqlite3.connect(path)
    legacy.execute("CREATE TABLE legacy_data (id INTEGER PRIMARY KEY, value TEXT)")
    legacy.execute("INSERT INTO legacy_data (value) VALUES ('preserved')")
    legacy.commit()
    legacy.close()

    connection = connect_database(path)
    tables = {
        row["name"]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }

    assert {"sensors", "sensor_state"}.issubset(tables)
    assert (
        connection.execute("SELECT value FROM legacy_data").fetchone()["value"]
        == "preserved"
    )


def test_structured_sensor_cli_covers_crud_toggle_and_status(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("IRRIGATION_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("IRRIGATION_GPIO_DRIVER", "mock")

    def call(payload):
        code = execute(["--stdin"], stdin=StringIO(json.dumps(payload)))
        captured = capsys.readouterr()
        return code, json.loads(captured.out) if captured.out else captured.err

    code, added = call(
        {
            "command": "sensor",
            "action": "add",
            "name": "Nível principal",
            "kind": "reservoir_level",
            "enabled": 1,
        }
    )
    assert code == 0
    assert added["state"]["health"] == "unknown"

    assert call({"command": "sensor", "action": "list"})[1][0]["id"] == added["id"]
    assert (
        call({"command": "sensor", "action": "get", "id": added["id"]})[1]["name"]
        == "Nível principal"
    )
    updated = call(
        {
            "command": "sensor",
            "action": "update",
            "id": added["id"],
            "name": "Nível da cisterna",
            "kind": "reservoir_level",
            "enabled": 1,
            "valve_id": None,
        }
    )[1]
    assert updated["name"] == "Nível da cisterna"
    assert (
        call(
            {"command": "sensor", "action": "enabled", "id": added["id"], "enabled": 0}
        )[1]["availability"]
        == "disabled"
    )
    assert (
        call({"command": "sensor", "action": "status", "id": added["id"]})[1]["state"][
            "health"
        ]
        == "unknown"
    )
    assert call({"command": "sensor", "action": "delete", "id": added["id"]})[1] == {
        "deleted": True
    }


def test_structured_sensor_cli_returns_actionable_validation_error(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("IRRIGATION_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("IRRIGATION_GPIO_DRIVER", "mock")

    code = execute(
        ["--stdin"],
        stdin=StringIO(
            json.dumps(
                {
                    "command": "sensor",
                    "action": "add",
                    "name": "Chuva",
                    "kind": "gpio23",
                }
            )
        ),
    )

    assert code == 2
    assert "sensor kind must be one of" in capsys.readouterr().err
