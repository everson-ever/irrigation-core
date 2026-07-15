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


def test_schedule_create_persists_weekdays(capsys, tmp_path):
    exit_code = execute(["schedule", "create", "06:30,15,13,mon+wed+fri"])
    output = json.loads(capsys.readouterr().out)
    schedule = json.loads((tmp_path / "schedules.json").read_text().splitlines()[0])

    assert exit_code == 0
    assert output["weekdays"] == ["mon", "wed", "fri"]
    assert schedule["weekdays"] == ["mon", "wed", "fri"]


def test_schedule_create_defaults_to_every_day(capsys):
    exit_code = execute(["schedule", "create", "06:30,15,13"])
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["weekdays"] == ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def test_schedule_update_persists_weekdays_and_preserves_status(capsys, tmp_path):
    schedules_file = tmp_path / "schedules.json"
    schedules_file.write_text(
        json.dumps(
            {
                "id": "1",
                "time": "06:30",
                "duration_minutes": "15",
                "valve_pin": "13",
                "status": 1,
                "enabled": 1,
                "weekdays": ["mon"],
            }
        )
        + "\n"
    )

    exit_code = execute(["schedule", "update", "1,07:00,10,13,tue+thu"])
    output = json.loads(capsys.readouterr().out)
    schedule = json.loads(schedules_file.read_text().splitlines()[0])

    assert exit_code == 0
    assert output["status"] == 1
    assert output["weekdays"] == ["tue", "thu"]
    assert schedule["weekdays"] == ["tue", "thu"]


def test_schedule_update_without_weekdays_preserves_selection(capsys, tmp_path):
    schedules_file = tmp_path / "schedules.json"
    schedules_file.write_text(
        json.dumps(
            {
                "id": "1",
                "time": "06:30",
                "duration_minutes": "15",
                "valve_pin": "13",
                "status": 0,
                "enabled": 1,
                "weekdays": ["mon", "wed"],
            }
        )
        + "\n"
    )

    exit_code = execute(["schedule", "update", "1,07:00,10,13"])
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["weekdays"] == ["mon", "wed"]


def test_schedule_create_rejects_empty_weekdays(capsys):
    exit_code = execute(["schedule", "create", "06:30,15,13,"])
    err = capsys.readouterr().err

    assert exit_code == 2
    assert "weekdays must contain at least one weekday" in err


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


def test_schedule_create_rejects_duplicate_valve(capsys, tmp_path):
    first_exit_code = execute(["schedule", "create", "06:30,15,13"])
    capsys.readouterr()

    second_exit_code = execute(["schedule", "create", "07:00,10,13"])
    captured = capsys.readouterr()
    schedules = [
        json.loads(line)
        for line in (tmp_path / "schedules.json").read_text().splitlines()
    ]

    assert first_exit_code == 0
    assert second_exit_code == 2
    assert "This valve/section already has a schedule" in captured.err
    assert len(schedules) == 1


def test_schedule_update_rejects_duplicate_valve(capsys, tmp_path):
    schedules_file = tmp_path / "schedules.json"
    schedules_file.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "id": "1",
                        "time": "06:30",
                        "duration_minutes": "15",
                        "valve_pin": "13",
                        "status": 0,
                        "enabled": 1,
                    }
                ),
                json.dumps(
                    {
                        "id": "2",
                        "time": "07:00",
                        "duration_minutes": "10",
                        "valve_pin": "14",
                        "status": 0,
                        "enabled": 1,
                    }
                ),
                "",
            ]
        )
    )

    exit_code = execute(["schedule", "update", "2,07:30,10,13"])
    captured = capsys.readouterr()
    second_schedule = json.loads(schedules_file.read_text().splitlines()[1])

    assert exit_code == 2
    assert "This valve/section already has a schedule" in captured.err
    assert second_schedule["valve_pin"] == "14"


def test_schedule_list_reports_schedule_specific_running_status(
    capsys, tmp_path, monkeypatch
):
    class FixedDateTime:
        @classmethod
        def now(cls):
            return datetime(2026, 7, 14, 11, 7)

    monkeypatch.setattr("irrigation.cli.datetime", FixedDateTime)
    schedules_file = tmp_path / "schedules.json"
    valves_file = tmp_path / "valves.json"
    valves_file.write_text(
        json.dumps({"id": "1", "pin": "13", "status": 1, "section": "Horta"}) + "\n"
    )
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
    assert [row["valve_status"] for row in output] == [True, True]


def test_schedule_list_reports_active_schedule_as_stopped_after_manual_off(
    capsys, tmp_path, monkeypatch
):
    class FixedDateTime:
        @classmethod
        def now(cls):
            return datetime(2026, 7, 14, 10, 5)

    monkeypatch.setattr("irrigation.cli.datetime", FixedDateTime)
    schedules_file = tmp_path / "schedules.json"
    schedules_file.write_text(
        json.dumps(
            {
                "id": "1",
                "time": "10:00",
                "duration_minutes": "10",
                "valve_pin": "13",
                "status": 1,
                "enabled": 1,
            }
        )
        + "\n"
    )
    valves_file = tmp_path / "valves.json"
    valves_file.write_text(
        json.dumps({"id": "1", "pin": "13", "status": 1, "section": "Horta"}) + "\n"
    )

    turn_off_exit_code = execute(["valve", "13,off,1"])
    capsys.readouterr()
    list_exit_code = execute(["schedule", "list"])
    output = json.loads(capsys.readouterr().out)
    valve = json.loads(valves_file.read_text().splitlines()[0])

    assert turn_off_exit_code == 0
    assert list_exit_code == 0
    assert valve["status"] == 0
    assert valve["manually_turned_off"] == 1
    assert json.loads(schedules_file.read_text().splitlines()[0])["status"] == 0
    assert output[0]["is_running"] is False
    assert output[0]["valve_status"] is False


def test_manual_on_after_manual_off_turns_valve_on_and_clears_manual_flag(
    capsys, tmp_path
):
    schedules_file = tmp_path / "schedules.json"
    schedules_file.write_text(
        json.dumps(
            {
                "id": "1",
                "time": "10:00",
                "duration_minutes": "10",
                "valve_pin": "13",
                "status": 0,
                "enabled": 1,
            }
        )
        + "\n"
    )
    valves_file = tmp_path / "valves.json"
    valves_file.write_text(
        json.dumps(
            {
                "id": "1",
                "pin": "13",
                "status": 0,
                "section": "Horta",
                "manually_turned_off": 1,
            }
        )
        + "\n"
    )
    settings_file = tmp_path / "settings.json"
    settings_file.write_text(
        json.dumps({"id": "1", "default_duration_minutes": 10}) + "\n"
    )

    exit_code = execute(["valve", "13,on,10,1", "--no-wait"])
    output = json.loads(capsys.readouterr().out)
    schedule = json.loads(schedules_file.read_text().splitlines()[0])
    valve = json.loads(valves_file.read_text().splitlines()[0])

    assert exit_code == 0
    assert output == {"changed": True}
    assert schedule["status"] == 1
    assert valve["status"] == 1
    assert valve["manually_turned_off"] == 0


def test_manual_on_clears_expired_schedule_status_used_by_controller(
    capsys, tmp_path, monkeypatch
):
    class FixedDateTime:
        @classmethod
        def now(cls):
            return datetime(2026, 7, 14, 10, 11)

    monkeypatch.setattr("irrigation.infrastructure.clock.datetime", FixedDateTime)
    schedules_file = tmp_path / "schedules.json"
    schedules_file.write_text(
        json.dumps(
            {
                "id": "1",
                "time": "10:00",
                "duration_minutes": "10",
                "valve_pin": "13",
                "status": 1,
                "enabled": 1,
            }
        )
        + "\n"
    )
    valves_file = tmp_path / "valves.json"
    valves_file.write_text(
        json.dumps(
            {
                "id": "1",
                "pin": "13",
                "status": 0,
                "section": "Horta",
                "manually_turned_off": 1,
            }
        )
        + "\n"
    )
    settings_file = tmp_path / "settings.json"
    settings_file.write_text(
        json.dumps({"id": "1", "default_duration_minutes": 10}) + "\n"
    )

    exit_code = execute(["valve", "13,on,10", "--no-wait"])
    output = json.loads(capsys.readouterr().out)
    schedule = json.loads(schedules_file.read_text().splitlines()[0])
    valve = json.loads(valves_file.read_text().splitlines()[0])

    assert exit_code == 0
    assert output == {"changed": True}
    assert schedule["status"] == 0
    assert valve["status"] == 1
