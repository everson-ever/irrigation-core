from __future__ import annotations

import json
import sys
from datetime import datetime
from io import StringIO

import pytest

from irrigation.bootstrap import Application
from irrigation.cli import execute
from irrigation.infrastructure.sqlite_repository import (
    ScheduleSqliteRepository,
    SqliteRepository,
    connect_database,
)


def _repository(tmp_path, table):
    connection = connect_database(tmp_path / "irrigation.db")
    if table == "schedules":
        return ScheduleSqliteRepository(connection)
    return SqliteRepository(connection, table)


def _execute_stdin(payload) -> int:
    return execute(["--stdin"], stdin=StringIO(json.dumps(payload)))


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


def test_health_command_reports_controller_heartbeat(capsys):
    offline_exit_code = execute(["health", "--max-age-seconds", "60"])
    offline_output = json.loads(capsys.readouterr().out)

    app = Application.create()
    app.runtime_health().touch(datetime.now())

    online_exit_code = execute(["health", "--max-age-seconds", "60"])
    online_output = json.loads(capsys.readouterr().out)

    assert offline_exit_code == 0
    assert offline_output["status"] == "offline"
    assert offline_output["last_seen_at"] is None
    assert online_exit_code == 0
    assert online_output["status"] == "online"
    assert online_output["component"] == "irrigation-core"


def test_stdin_schedule_command_preserves_argv_json_contract(capsys):
    exit_code = _execute_stdin(
        {
            "command": "schedule",
            "action": "create",
            "times": ["18:00", "06:00"],
            "duration_minutes": 15,
            "valve_pin": 13,
            "weekdays": ["mon", "wed", "fri"],
        }
    )
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["time"] == "06:00|18:00"
    assert output["duration_minutes"] == "15"
    assert output["valve_pin"] == "13"
    assert output["weekdays"] == ["mon", "wed", "fri"]


@pytest.mark.parametrize(
    "malicious_fields",
    [
        {"times": ["06:30; touch {sentinel}"], "weekdays": ["mon"]},
        {"times": ["06:30"], "weekdays": ["mon; touch {sentinel}"]},
    ],
)
def test_stdin_schedule_metacharacters_are_rejected_without_side_effect(
    capsys, tmp_path, malicious_fields
):
    sentinel = tmp_path / "schedule-pwned"
    request = {
        "command": "schedule",
        "action": "create",
        "duration_minutes": 15,
        "valve_pin": 13,
        **{
            key: [value.format(sentinel=sentinel) for value in values]
            for key, values in malicious_fields.items()
        },
    }

    exit_code = _execute_stdin(request)

    assert exit_code == 2
    assert capsys.readouterr().err.startswith("Error:")
    assert not sentinel.exists()


def test_schedule_create_persists_weekdays(capsys, tmp_path):
    exit_code = execute(["schedule", "create", "06:30,15,13,mon+wed+fri"])
    output = json.loads(capsys.readouterr().out)
    schedule = _repository(tmp_path, "schedules").find_by_id("1")

    assert exit_code == 0
    assert output["weekdays"] == ["mon", "wed", "fri"]
    assert schedule["weekdays"] == ["mon", "wed", "fri"]


def test_schedule_create_persists_multiple_times(capsys, tmp_path):
    exit_code = execute(["schedule", "create", "18:00+06:00+12:00,15,13"])
    output = json.loads(capsys.readouterr().out)
    schedule = _repository(tmp_path, "schedules").find_by_id("1")

    assert exit_code == 0
    assert output["time"] == "06:00|12:00|18:00"
    assert output["times"] == ["06:00", "12:00", "18:00"]
    assert schedule["time"] == "06:00|12:00|18:00"
    assert schedule["times"] == ["06:00", "12:00", "18:00"]


def test_schedule_create_rejects_fourth_time(capsys):
    exit_code = execute(["schedule", "create", "06:00+09:00+12:00+18:00,15,13"])
    err = capsys.readouterr().err

    assert exit_code == 2
    assert "more than three times" in err


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
    schedule = _repository(tmp_path, "schedules").find_by_id("1")

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


def test_schedule_update_persists_multiple_times(capsys, tmp_path):
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
            }
        )
        + "\n"
    )

    exit_code = execute(["schedule", "update", "1,18:00+06:00,10,13"])
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["time"] == "06:00|18:00"
    assert output["times"] == ["06:00", "18:00"]


def test_schedule_enabled_updates_record(capsys, tmp_path):
    execute(["schedule", "create", "06:30,15,13"])
    capsys.readouterr()

    disable_exit_code = execute(["schedule", "enabled", "1,0"])
    disabled_output = json.loads(capsys.readouterr().out)
    disabled_schedule = _repository(tmp_path, "schedules").find_by_id("1")

    enable_exit_code = execute(["schedule", "enabled", "1,1"])
    enabled_output = json.loads(capsys.readouterr().out)
    enabled_schedule = _repository(tmp_path, "schedules").find_by_id("1")

    assert disable_exit_code == 0
    assert disabled_output["enabled"] == 0
    assert disabled_schedule["enabled"] == 0
    assert enable_exit_code == 0
    assert enabled_output["enabled"] == 1
    assert enabled_schedule["enabled"] == 1


def test_schedule_enabled_rejects_invalid_flag_without_changing_record(
    capsys, tmp_path
):
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
                "weekdays": ["mon"],
            }
        )
        + "\n"
    )

    exit_code = execute(["schedule", "enabled", "1,2"])
    captured = capsys.readouterr()
    schedule = _repository(tmp_path, "schedules").find_by_id("1")

    assert exit_code == 2
    assert "enabled must be 0 or 1" in captured.err
    assert schedule["enabled"] == 1


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

    schedules = _repository(tmp_path, "schedules")
    schedule = schedules.find_by_id("1")
    schedules.update({**schedule, "status": 1})

    exit_code = execute(["schedule", "delete", "1"])
    output = json.loads(capsys.readouterr().out)
    valve = _repository(tmp_path, "valves").find_by_id("1")

    assert exit_code == 0
    assert output == {"deleted": True}
    assert valve["status"] == 0


def test_schedule_create_rejects_duplicate_valve(capsys, tmp_path):
    first_exit_code = execute(["schedule", "create", "06:30,15,13"])
    capsys.readouterr()

    second_exit_code = execute(["schedule", "create", "07:00,10,13"])
    captured = capsys.readouterr()
    schedules = _repository(tmp_path, "schedules").list_all()

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
    second_schedule = _repository(tmp_path, "schedules").find_by_id("2")

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
    valve = _repository(tmp_path, "valves").find_by_id("1")
    schedule = _repository(tmp_path, "schedules").find_by_id("1")

    assert turn_off_exit_code == 0
    assert list_exit_code == 0
    assert valve["status"] == 0
    assert valve["manually_turned_off"] == 1
    assert schedule["status"] == 0
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
    schedule = _repository(tmp_path, "schedules").find_by_id("1")
    valve = _repository(tmp_path, "valves").find_by_id("1")

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
    schedule = _repository(tmp_path, "schedules").find_by_id("1")
    valve = _repository(tmp_path, "valves").find_by_id("1")

    assert exit_code == 0
    assert output == {"changed": True}
    assert schedule["status"] == 0
    assert valve["status"] == 1


def test_valve_list_returns_database_records(capsys, tmp_path):
    (tmp_path / "valves.json").write_text(
        json.dumps({"id": "3", "pin": "13", "status": 0, "section": "Horta"}) + "\n"
    )

    exit_code = execute(["valve", "list"])
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output == [
        {
            "id": "3",
            "pin": "13",
            "status": 0,
            "section": "Horta",
            "manually_turned_off": 0,
        }
    ]


def test_valve_add_update_and_delete_manage_database_records(capsys, tmp_path):
    add_exit_code = execute(["valve", "add", "13,Horta"])
    added = json.loads(capsys.readouterr().out)

    update_exit_code = execute(["valve", "update", f"{added['id']},14,Jardim"])
    updated = json.loads(capsys.readouterr().out)

    delete_exit_code = execute(["valve", "delete", added["id"]])
    deleted = json.loads(capsys.readouterr().out)
    records = _repository(tmp_path, "valves").list_all()

    assert add_exit_code == 0
    assert added["pin"] == "13"
    assert added["section"] == "Horta"
    assert update_exit_code == 0
    assert updated["pin"] == "14"
    assert updated["section"] == "Jardim"
    assert delete_exit_code == 0
    assert deleted == {"deleted": True}
    assert records == []


def test_valve_add_and_update_accept_section_names_with_spaces(capsys):
    add_exit_code = execute(["valve", "add", "13,Jardim principal"])
    added = json.loads(capsys.readouterr().out)

    update_exit_code = execute(
        ["valve", "update", added["id"] + ",14,Jardim", "principal"]
    )
    updated = json.loads(capsys.readouterr().out)

    assert add_exit_code == 0
    assert added["section"] == "Jardim principal"
    assert update_exit_code == 0
    assert updated["pin"] == "14"
    assert updated["section"] == "Jardim principal"


def test_stdin_valve_name_treats_shell_metacharacters_as_literal_data(capsys, tmp_path):
    sentinel = tmp_path / "pwned"
    section = (
        f"frente; touch {sentinel} $(touch x) `touch y` | & * > <\nHorta ü, --no-wait"
    )

    exit_code = _execute_stdin(
        {"command": "valve", "action": "add", "pin": 13, "section": section}
    )
    output = json.loads(capsys.readouterr().out)
    stored = _repository(tmp_path, "valves").find_by_id("1")
    flag_exit_code = _execute_stdin(
        {"command": "valve", "action": "add", "pin": 14, "section": "--no-wait"}
    )
    flag_output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["section"] == section
    assert stored["section"] == section
    assert flag_exit_code == 0
    assert flag_output["section"] == "--no-wait"
    assert not sentinel.exists()


def test_valve_add_rejects_duplicate_pin(capsys, tmp_path):
    execute(["valve", "add", "13,Horta"])
    capsys.readouterr()

    exit_code = execute(["valve", "add", "13,Jardim"])
    captured = capsys.readouterr()
    records = _repository(tmp_path, "valves").list_all()

    assert exit_code == 2
    assert "GPIO pin is already registered" in captured.err
    assert len(records) == 1


def test_valve_delete_rejects_schedule_reference(capsys, tmp_path):
    execute(["valve", "add", "13,Horta"])
    capsys.readouterr()
    execute(["schedule", "create", "06:30,15,13"])
    capsys.readouterr()

    exit_code = execute(["valve", "delete", "1"])
    captured = capsys.readouterr()
    valve = _repository(tmp_path, "valves").find_by_id("1")

    assert exit_code == 2
    assert "still used by a schedule" in captured.err
    assert valve is not None


def test_settings_show_returns_current_database_row(capsys):
    assert execute(["settings", "5"]) == 0
    capsys.readouterr()

    exit_code = execute(["settings", "show"])
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output == {"id": "1", "default_duration_minutes": 5}


def test_auth_login_uses_seeded_default_credentials(capsys):
    exit_code = _execute_stdin(
        {
            "command": "auth",
            "action": "login",
            "username": "admin",
            "password": "10203040",
        }
    )
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output == {"authenticated": True}


def test_stdin_auth_keeps_password_out_of_process_arguments(capsys, monkeypatch):
    password = "nova, senha; $(segredo) | ü"
    monkeypatch.setattr("sys.argv", ["irrigation", "--stdin"])

    change_exit_code = _execute_stdin(
        {
            "command": "auth",
            "action": "change-password",
            "username": "admin",
            "current_password": "10203040",
            "new_password": password,
            "confirm_password": password,
        }
    )
    change_output = json.loads(capsys.readouterr().out)
    login_exit_code = _execute_stdin(
        {
            "command": "auth",
            "action": "login",
            "username": "admin",
            "password": password,
        }
    )
    login_output = json.loads(capsys.readouterr().out)

    assert change_exit_code == 0
    assert change_output == {"changed": True}
    assert login_exit_code == 0
    assert login_output == {"authenticated": True}
    assert password not in " ".join(sys.argv)


def test_auth_change_password_updates_login_credential(capsys):
    change_exit_code = _execute_stdin(
        {
            "command": "auth",
            "action": "change-password",
            "username": "admin",
            "current_password": "10203040",
            "new_password": "87654321",
        }
    )
    change_output = json.loads(capsys.readouterr().out)

    old_exit_code = _execute_stdin(
        {
            "command": "auth",
            "action": "login",
            "username": "admin",
            "password": "10203040",
        }
    )
    old_output = json.loads(capsys.readouterr().out)

    new_exit_code = _execute_stdin(
        {
            "command": "auth",
            "action": "login",
            "username": "admin",
            "password": "87654321",
        }
    )
    new_output = json.loads(capsys.readouterr().out)

    assert change_exit_code == 0
    assert change_output == {"changed": True}
    assert old_exit_code == 0
    assert old_output == {"authenticated": False}
    assert new_exit_code == 0
    assert new_output == {"authenticated": True}


def test_auth_change_password_rejects_mismatched_confirmation(capsys):
    exit_code = _execute_stdin(
        {
            "command": "auth",
            "action": "change-password",
            "username": "admin",
            "current_password": "10203040",
            "new_password": "87654321",
            "confirm_password": "different",
        }
    )
    err = capsys.readouterr().err

    assert exit_code == 2
    assert "password confirmation does not match" in err


def test_auth_reset_to_default_restores_default_login(capsys):
    _execute_stdin(
        {
            "command": "auth",
            "action": "change-password",
            "username": "admin",
            "current_password": "10203040",
            "new_password": "87654321",
        }
    )
    capsys.readouterr()

    reset_exit_code = execute(["auth", "reset-to-default"])
    reset_output = json.loads(capsys.readouterr().out)
    default_exit_code = _execute_stdin(
        {
            "command": "auth",
            "action": "login",
            "username": "admin",
            "password": "10203040",
        }
    )
    default_output = json.loads(capsys.readouterr().out)
    stale_exit_code = _execute_stdin(
        {
            "command": "auth",
            "action": "login",
            "username": "admin",
            "password": "87654321",
        }
    )
    stale_output = json.loads(capsys.readouterr().out)

    assert reset_exit_code == 0
    assert reset_output == {"reset": True}
    assert default_exit_code == 0
    assert default_output == {"authenticated": True}
    assert stale_exit_code == 0
    assert stale_output == {"authenticated": False}


@pytest.mark.parametrize("action", ["login", "change-password"])
def test_auth_commands_reject_credentialless_argv_invocation(capsys, action):
    exit_code = execute(["auth", action])

    assert exit_code == 2
    assert "credentials must be provided through --stdin" in capsys.readouterr().err


def test_history_range_reads_database_and_refreshes_json_snapshot(capsys, tmp_path):
    records = [
        {
            "id": str(index),
            "valve": "Horta",
            "date": day,
            "start": "10:00",
            "end": "10:05",
            "weekday": "Thursday",
            "mode": "Manual",
        }
        for index, day in enumerate(("2026-07-15", "2026-07-16"), start=1)
    ]
    (tmp_path / "history.json").write_text(
        "".join(json.dumps(record) + "\n" for record in records)
    )

    exit_code = execute(["history", "range,2026-07-16,2026-07-16"])
    output = json.loads(capsys.readouterr().out)
    snapshot = [
        json.loads(line)
        for line in (tmp_path / "history_search_results.json").read_text().splitlines()
    ]

    assert exit_code == 0
    assert [record["id"] for record in output] == ["2"]
    assert snapshot == output


def test_stdin_history_range_preserves_json_output(capsys, tmp_path):
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
        + "\n"
    )

    exit_code = _execute_stdin(
        {
            "command": "history",
            "action": "range",
            "start_date": "2026-07-16",
            "end_date": "2026-07-16",
        }
    )
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert [record["id"] for record in output] == ["1"]


def test_stdin_history_injection_is_rejected_without_side_effect(capsys, tmp_path):
    sentinel = tmp_path / "history-pwned"

    exit_code = _execute_stdin(
        {
            "command": "history",
            "action": "range",
            "start_date": "2026-07-16",
            "end_date": f"2026-07-16; touch {sentinel}",
        }
    )
    error = capsys.readouterr().err

    assert exit_code == 2
    assert error.startswith("Error:")
    assert not sentinel.exists()


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("", "stdin payload is empty"),
        ("not-json", "stdin payload must be valid JSON"),
        ("[]", "stdin payload must be a JSON object"),
        (json.dumps({"command": "run"}), "command is not available through stdin"),
        (
            json.dumps({"command": "auth", "action": "login"}),
            "stdin payload is missing 'username'",
        ),
    ],
)
def test_stdin_rejects_invalid_payloads(capsys, content, message):
    exit_code = execute(["--stdin"], stdin=StringIO(content))

    assert exit_code == 2
    assert message in capsys.readouterr().err


def test_stdin_rejects_payloads_larger_than_four_kibibytes(capsys):
    content = json.dumps({"command": "auth", "action": "login", "username": "a" * 4096})

    exit_code = execute(["--stdin"], stdin=StringIO(content))

    assert exit_code == 2
    assert "stdin payload exceeds 4096 bytes" in capsys.readouterr().err
