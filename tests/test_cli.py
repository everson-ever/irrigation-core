from __future__ import annotations

import json
from datetime import datetime

import pytest

from irrigation.cli import execute


@pytest.fixture(autouse=True)
def _isolated_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("IRRIGATION_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("IRRIGATION_GPIO_DRIVER", "mock")


def test_schedule_delete_removes_existing_record(capsys):
    execute(["schedule", "create", "06:30,15,13"])
    capsys.readouterr()

    exit_code = execute(["schedule", "delete", "1"])
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output == {"deleted": True}


def test_schedule_delete_missing_record_is_a_no_op(capsys):
    exit_code = execute(["schedule", "delete", "999"])
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output == {"deleted": False}


def test_schedule_delete_rejects_empty_identifier(capsys):
    exit_code = execute(["schedule", "delete", ""])
    err = capsys.readouterr().err

    assert exit_code == 2
    assert "schedule id is required" in err


def test_schedule_delete_stops_valve_of_active_schedule(capsys, tmp_path):
    valves_file = tmp_path / "valves.json"
    valves_file.write_text(
        json.dumps({"id": "1", "pin": "13", "status": 1, "section": "Horta"}) + "\n"
    )
    execute(["schedule", "create", "10:00,10,13"])
    capsys.readouterr()

    schedules_file = tmp_path / "schedules.json"
    schedule = json.loads(schedules_file.read_text().splitlines()[0])
    schedule["status"] = 1
    schedules_file.write_text(json.dumps(schedule) + "\n")

    exit_code = execute(["schedule", "delete", "1"])
    output = json.loads(capsys.readouterr().out)
    valve = json.loads(valves_file.read_text().splitlines()[0])

    assert exit_code == 0
    assert output == {"deleted": True}
    assert valve["status"] == 0


def test_schedule_list_reports_schedule_specific_running_status(
    capsys, tmp_path, monkeypatch
):
    class FixedDateTime:
        @classmethod
        def now(cls):
            return datetime(2026, 7, 14, 11, 7)

    monkeypatch.setattr("irrigation.cli.datetime", FixedDateTime)
    schedules_file = tmp_path / "schedules.json"
    schedules_file.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "id": "1",
                        "time": "10:46",
                        "duration_minutes": "2",
                        "valve_pin": "13",
                        "status": 0,
                        "enabled": 1,
                    }
                ),
                json.dumps(
                    {
                        "id": "2",
                        "time": "11:06",
                        "duration_minutes": "4",
                        "valve_pin": "13",
                        "status": 1,
                        "enabled": 1,
                    }
                ),
                "",
            ]
        )
    )

    exit_code = execute(["schedule", "list"])
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert [(row["time"], row["valve_pin"], row["is_running"]) for row in output] == [
        ("10:46", "13", False),
        ("11:06", "13", True),
    ]
