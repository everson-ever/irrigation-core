from datetime import datetime

import pytest

from irrigation.application.services import (
    HistoryService,
    IrrigationController,
    ManualControlService,
    ScheduleService,
    SettingsService,
    ValveService,
)
from irrigation.domain.exceptions import ValidationError
from irrigation.infrastructure.gpio import MockGPIO
from irrigation.infrastructure.json_repository import JsonLinesRepository
from irrigation.infrastructure.sqlite_repository import (
    ScheduleSqliteRepository,
    SqliteRepository,
    connect_database,
)


class FakeClock:
    def __init__(self, now: datetime) -> None:
        self.value = now

    def now(self) -> datetime:
        return self.value


class RecordingMockGPIO(MockGPIO):
    def __init__(self, pump_pin: int) -> None:
        super().__init__(pump_pin)
        self.operations: list[tuple[str, int]] = []

    def turn_on(self, pin: int) -> None:
        self.operations.append(("on", pin))
        super().turn_on(pin)

    def turn_off(self, pin: int, keep_pump_on: bool = False) -> None:
        self.operations.append(("off", pin))
        super().turn_off(pin, keep_pump_on=keep_pump_on)


def create_controller(tmp_path, now: datetime):
    connection = connect_database(tmp_path / "irrigation.db")
    schedules_repo = ScheduleSqliteRepository(connection)
    valves_repo = SqliteRepository(connection, "valves")
    history_repo = SqliteRepository(connection, "history")
    result_repo = JsonLinesRepository(tmp_path / "results.json")
    valves_repo.add({"pin": "13", "status": 0, "section": "Horta"})
    gpio = RecordingMockGPIO(15)
    valve_service = ValveService(valves_repo, gpio)
    clock = FakeClock(now)
    controller = IrrigationController(
        ScheduleService(schedules_repo),
        valve_service,
        HistoryService(history_repo, result_repo),
        clock,
        poll_interval=0,
    )
    return controller, schedules_repo, valves_repo, history_repo, gpio, clock


def test_late_start_and_turn_off_at_end(tmp_path):
    items = create_controller(tmp_path, datetime(2026, 7, 14, 10, 5))
    controller, schedules, valves, history, gpio, clock = items
    schedules.add(
        {
            "time": "10:00",
            "duration_minutes": "10",
            "valve_pin": "13",
            "status": 0,
            "enabled": 1,
        }
    )

    controller.run_once()

    assert schedules.find_by_id("1")["status"] == 1
    assert valves.find_by_id("1")["status"] == 1
    assert gpio.states[13] is True
    assert gpio.operations == [("on", 13)]
    assert history.list_all() == [
        {
            "id": "1",
            "valve": "Horta",
            "date": "2026-07-14",
            "start": "10:05",
            "end": "10:10",
            "weekday": "Tuesday",
            "mode": "Automatic: started after scheduled time",
        }
    ]

    clock.value = datetime(2026, 7, 14, 10, 11)
    controller.run_once()

    assert schedules.find_by_id("1")["status"] == 0
    assert valves.find_by_id("1")["status"] == 0
    assert gpio.states[13] is False
    assert gpio.states[15] is False
    assert gpio.operations == [("on", 13), ("off", 13)]
    assert history.list_all()[0]["end"] == "10:10"


def test_schedule_starts_on_configured_weekday(tmp_path):
    controller, schedules, valves, history, gpio, _ = create_controller(
        tmp_path, datetime(2026, 7, 14, 10, 0)
    )
    schedules.add(
        {
            "time": "10:00",
            "duration_minutes": "10",
            "valve_pin": "13",
            "status": 0,
            "enabled": 1,
            "weekdays": ["tue"],
        }
    )

    controller.run_once()

    assert schedules.find_by_id("1")["status"] == 1
    assert valves.find_by_id("1")["status"] == 1
    assert gpio.operations == [("on", 13)]
    assert history.list_all()[0]["weekday"] == "Tuesday"


def test_schedule_does_not_start_on_unconfigured_weekday(tmp_path):
    controller, schedules, valves, history, gpio, _ = create_controller(
        tmp_path, datetime(2026, 7, 14, 10, 0)
    )
    schedules.add(
        {
            "time": "10:00",
            "duration_minutes": "10",
            "valve_pin": "13",
            "status": 0,
            "enabled": 1,
            "weekdays": ["mon"],
        }
    )

    controller.run_once()

    assert schedules.find_by_id("1")["status"] == 0
    assert valves.find_by_id("1")["status"] == 0
    assert gpio.operations == []
    assert history.list_all() == []


def test_all_weekday_schedule_runs_every_day(tmp_path):
    controller, schedules, _, history, gpio, clock = create_controller(
        tmp_path, datetime(2026, 7, 14, 10, 0)
    )
    schedules.add(
        {
            "time": "10:00",
            "duration_minutes": "10",
            "valve_pin": "13",
            "status": 0,
            "enabled": 1,
            "weekdays": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
        }
    )

    controller.run_once()
    clock.value = datetime(2026, 7, 14, 10, 11)
    controller.run_once()
    clock.value = datetime(2026, 7, 19, 10, 0)
    controller.run_once()

    assert schedules.find_by_id("1")["status"] == 1
    assert gpio.operations == [("on", 13), ("off", 13), ("on", 13)]
    assert [record["weekday"] for record in history.list_all()] == [
        "Tuesday",
        "Sunday",
    ]


def test_multi_time_schedule_runs_each_slot_independently(tmp_path):
    controller, schedules, valves, history, gpio, clock = create_controller(
        tmp_path, datetime(2026, 7, 14, 6, 0)
    )
    schedules.add(
        {
            "time": "06:00|12:00|18:00",
            "duration_minutes": "10",
            "valve_pin": "13",
            "status": 0,
            "enabled": 1,
        }
    )

    controller.run_once()
    clock.value = datetime(2026, 7, 14, 6, 10)
    controller.run_once()
    clock.value = datetime(2026, 7, 14, 12, 0)
    controller.run_once()
    clock.value = datetime(2026, 7, 14, 12, 10)
    controller.run_once()
    clock.value = datetime(2026, 7, 14, 18, 0)
    controller.run_once()

    assert schedules.find_by_id("1")["status"] == 1
    assert valves.find_by_id("1")["status"] == 1
    assert gpio.operations == [
        ("on", 13),
        ("off", 13),
        ("on", 13),
        ("off", 13),
        ("on", 13),
    ]
    assert [(record["start"], record["end"]) for record in history.list_all()] == [
        ("06:00", "06:10"),
        ("12:00", "12:10"),
        ("18:00", "18:10"),
    ]


def test_back_to_back_multi_time_slots_record_separate_intervals(tmp_path):
    controller, schedules, valves, history, gpio, clock = create_controller(
        tmp_path, datetime(2026, 7, 14, 10, 0)
    )
    schedules.add(
        {
            "time": "10:00|10:10",
            "duration_minutes": "10",
            "valve_pin": "13",
            "status": 0,
            "enabled": 1,
        }
    )

    controller.run_once()
    clock.value = datetime(2026, 7, 14, 10, 10)
    controller.run_once()
    clock.value = datetime(2026, 7, 14, 10, 20)
    controller.run_once()

    assert schedules.find_by_id("1")["status"] == 0
    assert valves.find_by_id("1")["status"] == 0
    assert gpio.operations == [("on", 13), ("off", 13)]
    assert [(record["start"], record["end"]) for record in history.list_all()] == [
        ("10:00", "10:10"),
        ("10:10", "10:20"),
    ]


def test_repeated_cycles_do_not_duplicate_automatic_start(tmp_path):
    controller, schedules, _, history, gpio, _ = create_controller(
        tmp_path, datetime(2026, 7, 14, 10, 5)
    )
    schedules.add(
        {
            "time": "10:00",
            "duration_minutes": 10,
            "valve_pin": 13,
            "status": 0,
            "enabled": 1,
        }
    )

    controller.run_once()
    controller.run_once()

    assert gpio.operations == [("on", 13)]
    assert len(history.list_all()) == 1
    assert schedules.find_by_id("1")["status"] == 1


def test_disabling_active_schedule_turns_valve_off_and_resets_status(tmp_path):
    controller, schedules, valves, history, gpio, _ = create_controller(
        tmp_path, datetime(2026, 7, 14, 10, 0)
    )
    schedules.add(
        {
            "time": "10:00",
            "duration_minutes": 10,
            "valve_pin": 13,
            "status": 0,
            "enabled": 1,
        }
    )

    controller.run_once()
    schedules.update(
        {
            "id": "1",
            "time": "10:00",
            "duration_minutes": "10",
            "valve_pin": "13",
            "status": 1,
            "enabled": 0,
        }
    )
    controller.run_once()

    assert schedules.find_by_id("1")["status"] == 0
    assert schedules.find_by_id("1")["enabled"] == 0
    assert valves.find_by_id("1")["status"] == 0
    assert gpio.states[13] is False
    assert gpio.operations == [("on", 13), ("off", 13)]
    assert len(history.list_all()) == 1


def test_reactivates_hardware_for_interrupted_schedule(tmp_path):
    items = create_controller(tmp_path, datetime(2026, 7, 14, 10, 5))
    controller, schedules, valves, history, gpio, _ = items
    schedules.add(
        {
            "time": "10:00",
            "duration_minutes": 10,
            "valve_pin": 13,
            "status": 1,
            "enabled": 1,
        }
    )
    valve_record = valves.find_by_id("1")
    valve_record["status"] = 1
    valves.update(valve_record)

    controller.run_once()

    assert gpio.states[13] is True
    assert history.list_all()[0]["mode"] == "Restarted"


def test_does_not_restart_manually_stopped_schedule_after_controller_restart(tmp_path):
    items = create_controller(tmp_path, datetime(2026, 7, 14, 10, 5))
    controller, schedules, valves, history, gpio, _ = items
    schedules.add(
        {
            "time": "10:00",
            "duration_minutes": 10,
            "valve_pin": 13,
            "status": 0,
            "enabled": 1,
        }
    )
    history.add(
        {
            "valve": "Horta",
            "date": "2026-07-14",
            "start": "10:00",
            "end": "10:10",
            "weekday": "Tuesday",
            "mode": "Automatic",
        }
    )
    valve_record = valves.find_by_id("1")
    valve_record["status"] = 0
    valve_record["manually_turned_off"] = 1
    valves.update(valve_record)

    controller.run_once()

    assert valves.find_by_id("1")["status"] == 0
    assert valves.find_by_id("1")["manually_turned_off"] == 1
    assert schedules.find_by_id("1")["status"] == 0
    assert gpio.operations == []
    assert len(history.list_all()) == 1


def test_manually_stopped_schedule_runs_again_on_next_occurrence(tmp_path):
    items = create_controller(tmp_path, datetime(2026, 7, 14, 10, 5))
    controller, schedules, valves, history, gpio, clock = items
    schedules.add(
        {
            "time": "10:00",
            "duration_minutes": 10,
            "valve_pin": 13,
            "status": 0,
            "enabled": 1,
        }
    )
    history.add(
        {
            "valve": "Horta",
            "date": "2026-07-14",
            "start": "10:00",
            "end": "10:10",
            "weekday": "Tuesday",
            "mode": "Automatic",
        }
    )
    valve_record = valves.find_by_id("1")
    valve_record["status"] = 0
    valve_record["manually_turned_off"] = 1
    valves.update(valve_record)

    controller.run_once()
    clock.value = datetime(2026, 7, 14, 10, 11)
    controller.run_once()
    clock.value = datetime(2026, 7, 15, 10, 0)
    controller.run_once()

    assert schedules.find_by_id("1")["status"] == 1
    assert valves.find_by_id("1")["status"] == 1
    assert valves.find_by_id("1")["manually_turned_off"] == 0
    assert gpio.operations == [("on", 13)]
    assert history.list_all()[-1]["mode"] == "Automatic"


def test_next_occurrence_takes_ownership_from_manual_override(tmp_path):
    items = create_controller(tmp_path, datetime(2026, 7, 14, 10, 11))
    controller, schedules, valves, history, gpio, clock = items
    schedules.add(
        {
            "time": "10:00",
            "duration_minutes": 10,
            "valve_pin": 13,
            "status": 1,
            "enabled": 1,
        }
    )
    valve_record = valves.find_by_id("1")
    valve_record["status"] = 1
    valve_record["manually_turned_off"] = 1
    valves.update(valve_record)

    controller.run_once()
    clock.value = datetime(2026, 7, 15, 10, 0)
    controller.run_once()
    clock.value = datetime(2026, 7, 15, 10, 11)
    controller.run_once()

    assert schedules.find_by_id("1")["status"] == 0
    assert valves.find_by_id("1")["status"] == 0
    assert valves.find_by_id("1")["manually_turned_off"] == 0
    assert gpio.operations == [("on", 13), ("off", 13)]
    assert history.list_all()[0]["mode"] == "Automatic"


def test_disabled_schedule_does_not_turn_on(tmp_path):
    items = create_controller(tmp_path, datetime(2026, 7, 14, 10, 5))
    controller, schedules, _, history, gpio, _ = items
    schedules.add(
        {
            "time": "10:00",
            "duration_minutes": 10,
            "valve_pin": 13,
            "status": 0,
            "enabled": 0,
        }
    )

    controller.run_once()

    assert gpio.states.get(13, False) is False
    assert gpio.states.get(15, False) is False
    assert history.list_all() == []


def test_overlapping_schedules_do_not_turn_off_valve_before_end(tmp_path):
    items = create_controller(tmp_path, datetime(2026, 7, 14, 10, 5))
    controller, schedules, _, _, gpio, clock = items
    for schedule_time in ("10:00", "10:05"):
        schedules.add(
            {
                "time": schedule_time,
                "duration_minutes": 10,
                "valve_pin": 13,
                "status": 0,
                "enabled": 1,
            }
        )
    controller.run_once()

    clock.value = datetime(2026, 7, 14, 10, 11)
    controller.run_once()

    assert schedules.find_by_id("1")["status"] == 0
    assert schedules.find_by_id("2")["status"] == 1
    assert gpio.states[13] is True

    clock.value = datetime(2026, 7, 14, 10, 16)
    controller.run_once()

    assert gpio.states[13] is False


def test_overlapping_manually_stopped_schedules_do_not_restart_valve(tmp_path):
    items = create_controller(tmp_path, datetime(2026, 7, 14, 10, 7))
    controller, schedules, valves, history, gpio, _ = items
    for schedule_time in ("10:00", "10:05"):
        schedules.add(
            {
                "time": schedule_time,
                "duration_minutes": 10,
                "valve_pin": 13,
                "status": 0,
                "enabled": 1,
            }
        )
    history.add(
        {
            "valve": "Horta",
            "date": "2026-07-14",
            "start": "10:00",
            "end": "10:15",
            "weekday": "Tuesday",
            "mode": "Automatic",
        }
    )
    valve_record = valves.find_by_id("1")
    valve_record["status"] = 0
    valve_record["manually_turned_off"] = 1
    valves.update(valve_record)

    controller.run_once()

    assert gpio.operations == []
    assert len(history.list_all()) == 1
    assert schedules.find_by_id("1")["status"] == 0
    assert schedules.find_by_id("2")["status"] == 0


def test_midnight_crossing_schedule_stops_at_exact_end_boundary(tmp_path):
    controller, schedules, valves, history, gpio, clock = create_controller(
        tmp_path, datetime(2026, 7, 15, 0, 2)
    )
    schedules.add(
        {
            "time": "23:55",
            "duration_minutes": 10,
            "valve_pin": 13,
            "status": 0,
            "enabled": 1,
        }
    )

    controller.run_once()

    assert schedules.find_by_id("1")["status"] == 1
    assert valves.find_by_id("1")["status"] == 1
    assert gpio.states[13] is True
    assert history.list_all()[0]["end"] == "00:05"

    clock.value = datetime(2026, 7, 15, 0, 5)
    controller.run_once()

    assert schedules.find_by_id("1")["status"] == 0
    assert valves.find_by_id("1")["status"] == 0
    assert gpio.states[13] is False
    assert gpio.operations == [("on", 13), ("off", 13)]


def test_midnight_crossing_schedule_finishes_on_next_day_for_selected_start_day(
    tmp_path,
):
    controller, schedules, valves, history, gpio, clock = create_controller(
        tmp_path, datetime(2026, 7, 15, 0, 2)
    )
    schedules.add(
        {
            "time": "23:55",
            "duration_minutes": 10,
            "valve_pin": 13,
            "status": 0,
            "enabled": 1,
            "weekdays": ["tue"],
        }
    )

    controller.run_once()

    assert schedules.find_by_id("1")["status"] == 1
    assert valves.find_by_id("1")["status"] == 1
    assert history.list_all()[0]["end"] == "00:05"

    clock.value = datetime(2026, 7, 15, 0, 5)
    controller.run_once()

    assert schedules.find_by_id("1")["status"] == 0
    assert gpio.operations == [("on", 13), ("off", 13)]


def test_midnight_crossing_schedule_does_not_start_after_unselected_start_day(
    tmp_path,
):
    controller, schedules, valves, history, gpio, _ = create_controller(
        tmp_path, datetime(2026, 7, 15, 0, 2)
    )
    schedules.add(
        {
            "time": "23:55",
            "duration_minutes": 10,
            "valve_pin": 13,
            "status": 0,
            "enabled": 1,
            "weekdays": ["wed"],
        }
    )

    controller.run_once()

    assert schedules.find_by_id("1")["status"] == 0
    assert valves.find_by_id("1")["status"] == 0
    assert gpio.operations == []
    assert history.list_all() == []


def test_schedule_runtime_status_is_specific_to_shared_valve_schedule(tmp_path):
    schedules_repo = JsonLinesRepository(tmp_path / "schedules.json")
    valves_repo = JsonLinesRepository(tmp_path / "valves.json")
    service = ScheduleService(schedules_repo)
    valves_repo.add({"pin": "13", "status": 1, "section": "Horta"})
    schedules_repo.add(
        {
            "time": "10:46",
            "duration_minutes": "2",
            "valve_pin": "13",
            "status": 0,
            "enabled": 1,
        }
    )
    schedules_repo.add(
        {
            "time": "11:06",
            "duration_minutes": "4",
            "valve_pin": "13",
            "status": 1,
            "enabled": 1,
        }
    )

    rows = service.list_with_runtime_status(
        datetime(2026, 7, 14, 11, 7),
        [ValveService(valves_repo, MockGPIO(15)).get_by_pin(13)],
    )

    assert [(row["time"], row["valve_pin"], row["is_running"]) for row in rows] == [
        ("10:46", "13", False),
        ("11:06", "13", True),
    ]


def test_manual_on_valve_does_not_mark_inactive_schedule_as_running(tmp_path):
    schedules_repo = JsonLinesRepository(tmp_path / "schedules.json")
    valves_repo = JsonLinesRepository(tmp_path / "valves.json")
    service = ScheduleService(schedules_repo)
    valves_repo.add({"pin": "13", "status": 1, "section": "Horta"})
    schedules_repo.add(
        {
            "time": "10:46",
            "duration_minutes": "2",
            "valve_pin": "13",
            "status": 0,
            "enabled": 1,
        }
    )

    rows = service.list_with_runtime_status(
        datetime(2026, 7, 14, 11, 7),
        [ValveService(valves_repo, MockGPIO(15)).get_by_pin(13)],
    )

    assert rows[0]["is_running"] is False
    assert rows[0]["valve_status"] is True


def test_runtime_status_is_false_when_active_schedule_valve_was_manually_stopped(
    tmp_path,
):
    schedules_repo = JsonLinesRepository(tmp_path / "schedules.json")
    valves_repo = JsonLinesRepository(tmp_path / "valves.json")
    service = ScheduleService(schedules_repo)
    valves_repo.add(
        {
            "pin": "13",
            "status": 0,
            "section": "Horta",
            "manually_turned_off": 1,
        }
    )
    schedules_repo.add(
        {
            "time": "10:00",
            "duration_minutes": "10",
            "valve_pin": "13",
            "status": 0,
            "enabled": 1,
        }
    )

    rows = service.list_with_runtime_status(
        datetime(2026, 7, 14, 10, 5),
        [ValveService(valves_repo, MockGPIO(15)).get_by_pin(13)],
    )

    assert rows[0]["is_running"] is False
    assert rows[0]["valve_status"] is False


def test_history_active_end_returns_manual_record_end(tmp_path):
    history_repo = JsonLinesRepository(tmp_path / "history.json")
    result_repo = JsonLinesRepository(tmp_path / "results.json")
    service = HistoryService(history_repo, result_repo)
    service.record(
        "Horta",
        datetime(2026, 7, 14, 10, 0),
        datetime(2026, 7, 14, 10, 12),
        "Manual",
    )

    active_end = service.active_end("Horta", datetime(2026, 7, 14, 10, 5))

    assert active_end == datetime(2026, 7, 14, 10, 12)
    assert service.has_active_manual("Horta", datetime(2026, 7, 14, 10, 5)) is True
    assert service.has_active_automatic("Horta", datetime(2026, 7, 14, 10, 5)) is False


def test_history_active_end_returns_automatic_record_end(tmp_path):
    history_repo = JsonLinesRepository(tmp_path / "history.json")
    result_repo = JsonLinesRepository(tmp_path / "results.json")
    service = HistoryService(history_repo, result_repo)
    service.record(
        "Horta",
        datetime(2026, 7, 14, 10, 0),
        datetime(2026, 7, 14, 10, 10),
        "Automatic",
    )

    active_end = service.active_end("Horta", datetime(2026, 7, 14, 10, 5))

    assert active_end == datetime(2026, 7, 14, 10, 10)
    assert service.has_active_manual("Horta", datetime(2026, 7, 14, 10, 5)) is False
    assert service.has_active_automatic("Horta", datetime(2026, 7, 14, 10, 5)) is True


def test_history_active_end_returns_none_when_no_record_is_active(tmp_path):
    history_repo = JsonLinesRepository(tmp_path / "history.json")
    result_repo = JsonLinesRepository(tmp_path / "results.json")
    service = HistoryService(history_repo, result_repo)
    service.record(
        "Horta",
        datetime(2026, 7, 14, 10, 0),
        datetime(2026, 7, 14, 10, 10),
        "Automatic",
    )

    assert service.active_end("Horta", datetime(2026, 7, 14, 10, 11)) is None


def test_runtime_status_includes_remaining_seconds_for_running_schedule(tmp_path):
    schedules_repo = JsonLinesRepository(tmp_path / "schedules.json")
    valves_repo = JsonLinesRepository(tmp_path / "valves.json")
    history_repo = JsonLinesRepository(tmp_path / "history.json")
    result_repo = JsonLinesRepository(tmp_path / "results.json")
    schedules_repo.add(
        {
            "time": "10:00",
            "duration_minutes": "10",
            "valve_pin": "13",
            "status": 1,
            "enabled": 1,
        }
    )
    valves_repo.add({"pin": "13", "status": 1, "section": "Horta"})
    history = HistoryService(history_repo, result_repo)
    history.record(
        "Horta",
        datetime(2026, 7, 14, 10, 0),
        datetime(2026, 7, 14, 10, 10),
        "Automatic",
    )

    rows = ScheduleService(schedules_repo).list_with_runtime_status(
        datetime(2026, 7, 14, 10, 4),
        ValveService(valves_repo, MockGPIO(15)).list_all(),
        history,
    )

    assert rows[0]["is_running"] is True
    assert rows[0]["valve_status"] is True
    assert rows[0]["remaining_seconds"] == 360


def test_runtime_status_omits_remaining_seconds_for_stopped_schedule(tmp_path):
    schedules_repo = JsonLinesRepository(tmp_path / "schedules.json")
    valves_repo = JsonLinesRepository(tmp_path / "valves.json")
    history_repo = JsonLinesRepository(tmp_path / "history.json")
    result_repo = JsonLinesRepository(tmp_path / "results.json")
    schedules_repo.add(
        {
            "time": "10:00",
            "duration_minutes": "10",
            "valve_pin": "13",
            "status": 0,
            "enabled": 1,
        }
    )
    valves_repo.add({"pin": "13", "status": 0, "section": "Horta"})
    history = HistoryService(history_repo, result_repo)
    history.record(
        "Horta",
        datetime(2026, 7, 14, 10, 0),
        datetime(2026, 7, 14, 10, 10),
        "Automatic",
    )

    rows = ScheduleService(schedules_repo).list_with_runtime_status(
        datetime(2026, 7, 14, 10, 4),
        ValveService(valves_repo, MockGPIO(15)).list_all(),
        history,
    )

    assert rows[0]["is_running"] is False
    assert rows[0]["valve_status"] is False
    assert "remaining_seconds" not in rows[0]


def test_runtime_status_uses_manual_run_duration_for_remaining_seconds(tmp_path):
    schedules_repo = JsonLinesRepository(tmp_path / "schedules.json")
    valves_repo = JsonLinesRepository(tmp_path / "valves.json")
    settings_repo = JsonLinesRepository(tmp_path / "settings.json")
    history_repo = JsonLinesRepository(tmp_path / "history.json")
    result_repo = JsonLinesRepository(tmp_path / "results.json")
    schedules_repo.add(
        {
            "time": "10:00",
            "duration_minutes": "5",
            "valve_pin": "13",
            "status": 0,
            "enabled": 1,
        }
    )
    valves_repo.add({"pin": "13", "status": 0, "section": "Horta"})
    settings_repo.add({"default_duration_minutes": 5})
    schedule_service = ScheduleService(schedules_repo)
    valve_service = ValveService(valves_repo, MockGPIO(15))
    history = HistoryService(history_repo, result_repo)
    manual = ManualControlService(
        valve_service,
        SettingsService(settings_repo),
        history,
        FakeClock(datetime(2026, 7, 14, 10, 0)),
        poll_interval=0,
        schedules=schedule_service,
    )

    manual.turn_on(13, duration_minutes=12, wait=False, schedule_id="1")
    rows = schedule_service.list_with_runtime_status(
        datetime(2026, 7, 14, 10, 1),
        valve_service.list_all(),
        history,
    )

    assert rows[0]["duration_minutes"] == "5"
    assert rows[0]["is_running"] is True
    assert rows[0]["remaining_seconds"] == 660


def test_automatic_runtime_status_remaining_seconds_decreases(tmp_path):
    items = create_controller(tmp_path, datetime(2026, 7, 14, 10, 0))
    controller, schedules, valves, history_repo, _, clock = items
    schedules.add(
        {
            "time": "10:00",
            "duration_minutes": "10",
            "valve_pin": "13",
            "status": 0,
            "enabled": 1,
        }
    )
    controller.run_once()
    schedule_service = ScheduleService(schedules)
    valve_service = ValveService(valves, MockGPIO(15))
    history = HistoryService(
        history_repo,
        JsonLinesRepository(tmp_path / "history-results.json"),
    )

    clock.value = datetime(2026, 7, 14, 10, 2)
    first = schedule_service.list_with_runtime_status(
        clock.now(), valve_service.list_all(), history
    )
    clock.value = datetime(2026, 7, 14, 10, 5)
    second = schedule_service.list_with_runtime_status(
        clock.now(), valve_service.list_all(), history
    )

    assert first[0]["remaining_seconds"] == 480
    assert second[0]["remaining_seconds"] == 300


def test_multi_time_schedule_reports_remaining_seconds_for_active_slot(tmp_path):
    items = create_controller(tmp_path, datetime(2026, 7, 14, 6, 0))
    controller, schedules, valves, history_repo, _, clock = items
    schedules.add(
        {
            "time": "06:00|12:00",
            "duration_minutes": "10",
            "valve_pin": "13",
            "status": 0,
            "enabled": 1,
        }
    )
    controller.run_once()
    clock.value = datetime(2026, 7, 14, 6, 10)
    controller.run_once()
    clock.value = datetime(2026, 7, 14, 12, 0)
    controller.run_once()
    schedule_service = ScheduleService(schedules)
    valve_service = ValveService(valves, MockGPIO(15))
    history = HistoryService(
        history_repo,
        JsonLinesRepository(tmp_path / "history-results.json"),
    )

    rows = schedule_service.list_with_runtime_status(
        datetime(2026, 7, 14, 12, 4),
        valve_service.list_all(),
        history,
    )

    assert rows[0]["remaining_seconds"] == 360
    assert [(record["start"], record["end"]) for record in history_repo.list_all()] == [
        ("06:00", "06:10"),
        ("12:00", "12:10"),
    ]


def test_schedule_create_rejects_duplicate_valve(tmp_path):
    schedules_repo = JsonLinesRepository(tmp_path / "schedules.json")
    service = ScheduleService(schedules_repo)
    service.create("10:00", "10", "13")

    with pytest.raises(ValidationError, match="valve/section already has a schedule"):
        service.create("11:00", "5", "13")

    assert len(service.list_all()) == 1


def test_schedule_create_persists_selected_weekdays(tmp_path):
    schedules_repo = JsonLinesRepository(tmp_path / "schedules.json")
    service = ScheduleService(schedules_repo)

    created = service.create("10:00", "10", "13", "fri+mon")

    assert created["weekdays"] == ["mon", "fri"]
    assert service.get("1").weekdays == ("mon", "fri")


def test_schedule_update_persists_selected_weekdays_without_resetting_status(tmp_path):
    schedules_repo = JsonLinesRepository(tmp_path / "schedules.json")
    service = ScheduleService(schedules_repo)
    service.create("10:00", "10", "13", "mon")
    service.set_status("1", True)

    updated = service.update("1", "10:30", "15", "13", "tue+thu")

    assert updated["status"] == 1
    assert updated["weekdays"] == ["tue", "thu"]


def test_schedule_update_without_weekdays_preserves_existing_selection(tmp_path):
    schedules_repo = JsonLinesRepository(tmp_path / "schedules.json")
    service = ScheduleService(schedules_repo)
    service.create("10:00", "10", "13", "mon+wed")

    updated = service.update("1", "10:30", "15", "13")

    assert updated["weekdays"] == ["mon", "wed"]


def test_schedule_update_rejects_valve_used_by_different_schedule(tmp_path):
    schedules_repo = JsonLinesRepository(tmp_path / "schedules.json")
    service = ScheduleService(schedules_repo)
    schedules_repo.add(
        {
            "time": "10:00",
            "duration_minutes": "10",
            "valve_pin": "13",
            "status": 0,
            "enabled": 1,
        }
    )
    schedules_repo.add(
        {
            "time": "11:00",
            "duration_minutes": "5",
            "valve_pin": "14",
            "status": 0,
            "enabled": 1,
        }
    )

    with pytest.raises(ValidationError, match="valve/section already has a schedule"):
        service.update("2", "11:30", "6", "13")

    assert schedules_repo.find_by_id("2")["valve_pin"] == "14"


def test_schedule_update_allows_unchanged_valve(tmp_path):
    schedules_repo = JsonLinesRepository(tmp_path / "schedules.json")
    service = ScheduleService(schedules_repo)
    service.create("10:00", "10", "13")

    updated = service.update("1", "10:30", "15", "13")

    assert updated["time"] == "10:30"
    assert updated["duration_minutes"] == "15"
    assert updated["valve_pin"] == "13"


def test_schedule_create_allows_reusing_valve_after_delete(tmp_path):
    schedules, valves, _, _ = create_schedule_service_with_valve(tmp_path)
    schedules.create("10:00", "10", "13")
    schedules.delete("1", valves)

    created = schedules.create("11:00", "5", "13")

    assert created["valve_pin"] == "13"
    assert [schedule.valve_pin for schedule in schedules.list_all()] == [13]


def test_manual_turn_on_uses_provided_duration_instead_of_default(tmp_path):
    valves_repo = JsonLinesRepository(tmp_path / "valves.json")
    settings_repo = JsonLinesRepository(tmp_path / "settings.json")
    history_repo = JsonLinesRepository(tmp_path / "history.json")
    result_repo = JsonLinesRepository(tmp_path / "results.json")
    valves_repo.add({"pin": "13", "status": 0, "section": "Horta"})
    settings_repo.add({"default_duration_minutes": 1})
    clock = FakeClock(datetime(2026, 7, 14, 10, 0))
    service = ManualControlService(
        ValveService(valves_repo, MockGPIO(15)),
        SettingsService(settings_repo),
        HistoryService(history_repo, result_repo),
        clock,
        poll_interval=0,
    )

    changed = service.turn_on(13, duration_minutes=12, wait=False)

    assert changed is True
    assert history_repo.list_all()[0]["end"] == "10:12"


def test_manual_on_clears_expired_schedule_status_before_controller_cycle(tmp_path):
    schedules_repo = JsonLinesRepository(tmp_path / "schedules.json")
    valves_repo = JsonLinesRepository(tmp_path / "valves.json")
    settings_repo = JsonLinesRepository(tmp_path / "settings.json")
    history_repo = JsonLinesRepository(tmp_path / "history.json")
    result_repo = JsonLinesRepository(tmp_path / "results.json")
    schedules_repo.add(
        {
            "time": "10:00",
            "duration_minutes": "10",
            "valve_pin": "13",
            "status": 0,
            "enabled": 1,
        }
    )
    valves_repo.add(
        {
            "pin": "13",
            "status": 0,
            "section": "Horta",
            "manually_turned_off": 1,
        }
    )
    settings_repo.add({"default_duration_minutes": 10})
    clock = FakeClock(datetime(2026, 7, 14, 10, 11))
    gpio = RecordingMockGPIO(15)
    valve_service = ValveService(valves_repo, gpio)
    schedule_service = ScheduleService(schedules_repo)
    history_service = HistoryService(history_repo, result_repo)
    manual = ManualControlService(
        valve_service,
        SettingsService(settings_repo),
        history_service,
        clock,
        poll_interval=0,
        schedules=schedule_service,
    )
    controller = IrrigationController(
        schedule_service,
        valve_service,
        history_service,
        clock,
        poll_interval=0,
    )

    changed = manual.turn_on(13, duration_minutes=10, wait=False)
    controller.run_once()

    assert changed is True
    assert schedules_repo.find_by_id("1")["status"] == 0
    assert valves_repo.find_by_id("1")["status"] == 1
    assert valves_repo.find_by_id("1")["manually_turned_off"] == 0
    assert gpio.operations == [("on", 13)]


def test_manual_on_during_cancelled_schedule_survives_automatic_end(tmp_path):
    schedules_repo = JsonLinesRepository(tmp_path / "schedules.json")
    valves_repo = JsonLinesRepository(tmp_path / "valves.json")
    settings_repo = JsonLinesRepository(tmp_path / "settings.json")
    history_repo = JsonLinesRepository(tmp_path / "history.json")
    result_repo = JsonLinesRepository(tmp_path / "results.json")
    schedules_repo.add(
        {
            "time": "10:00",
            "duration_minutes": "10",
            "valve_pin": "13",
            "status": 0,
            "enabled": 1,
        }
    )
    valves_repo.add(
        {
            "pin": "13",
            "status": 0,
            "section": "Horta",
            "manually_turned_off": 1,
        }
    )
    settings_repo.add({"default_duration_minutes": 20})
    clock = FakeClock(datetime(2026, 7, 14, 10, 5))
    gpio = RecordingMockGPIO(15)
    valve_service = ValveService(valves_repo, gpio)
    schedule_service = ScheduleService(schedules_repo)
    history_service = HistoryService(history_repo, result_repo)
    manual = ManualControlService(
        valve_service,
        SettingsService(settings_repo),
        history_service,
        clock,
        poll_interval=0,
        schedules=schedule_service,
    )
    controller = IrrigationController(
        schedule_service,
        valve_service,
        history_service,
        clock,
        poll_interval=0,
    )

    changed = manual.turn_on(13, duration_minutes=20, wait=False, schedule_id="1")
    clock.value = datetime(2026, 7, 14, 10, 11)
    controller.run_once()

    assert changed is True
    assert schedules_repo.find_by_id("1")["status"] == 1
    assert valves_repo.find_by_id("1")["status"] == 1
    assert valves_repo.find_by_id("1")["manually_turned_off"] == 0
    assert gpio.operations == [("on", 13)]


def test_manual_on_outside_schedule_can_be_toggled_repeatedly(tmp_path):
    schedules_repo = JsonLinesRepository(tmp_path / "schedules.json")
    valves_repo = JsonLinesRepository(tmp_path / "valves.json")
    settings_repo = JsonLinesRepository(tmp_path / "settings.json")
    history_repo = JsonLinesRepository(tmp_path / "history.json")
    result_repo = JsonLinesRepository(tmp_path / "results.json")
    schedules_repo.add(
        {
            "time": "10:00",
            "duration_minutes": "10",
            "valve_pin": "13",
            "status": 0,
            "enabled": 1,
        }
    )
    valves_repo.add(
        {
            "pin": "13",
            "status": 0,
            "section": "Horta",
            "manually_turned_off": 1,
        }
    )
    settings_repo.add({"default_duration_minutes": 10})
    gpio = RecordingMockGPIO(15)
    service = ManualControlService(
        ValveService(valves_repo, gpio),
        SettingsService(settings_repo),
        HistoryService(history_repo, result_repo),
        FakeClock(datetime(2026, 7, 14, 12, 0)),
        poll_interval=0,
        schedules=ScheduleService(schedules_repo),
    )

    assert service.turn_on(13, wait=False, schedule_id="1") is True
    assert schedules_repo.find_by_id("1")["status"] == 1
    assert service.turn_off(13, schedule_id="1") is True
    assert schedules_repo.find_by_id("1")["status"] == 0
    assert service.turn_on(13, wait=False, schedule_id="1") is True

    assert schedules_repo.find_by_id("1")["status"] == 1
    assert valves_repo.find_by_id("1")["status"] == 1
    assert valves_repo.find_by_id("1")["manually_turned_off"] == 0
    assert gpio.operations == [("on", 13), ("off", 13), ("on", 13)]


def create_schedule_service_with_valve(tmp_path):
    schedules_repo = JsonLinesRepository(tmp_path / "schedules.json")
    valves_repo = JsonLinesRepository(tmp_path / "valves.json")
    valves_repo.add({"pin": "13", "status": 0, "section": "Horta"})
    gpio = RecordingMockGPIO(15)
    valve_service = ValveService(valves_repo, gpio)
    schedule_service = ScheduleService(schedules_repo)
    return schedule_service, valve_service, valves_repo, gpio


def test_delete_removes_inactive_schedule_without_touching_valve(tmp_path):
    schedules, valves, valves_repo, gpio = create_schedule_service_with_valve(tmp_path)
    schedules.create("10:00", "10", "13")

    deleted = schedules.delete("1", valves)

    assert deleted is True
    assert schedules.list_all() == []
    assert gpio.operations == []
    assert valves_repo.find_by_id("1")["status"] == 0


def test_delete_stops_valve_of_active_schedule(tmp_path):
    schedules, valves, valves_repo, gpio = create_schedule_service_with_valve(tmp_path)
    schedules.create("10:00", "10", "13")
    schedules.set_status("1", True)
    valves.turn_on(13, force_hardware=True)

    deleted = schedules.delete("1", valves)

    assert deleted is True
    assert schedules.list_all() == []
    assert gpio.states[13] is False
    assert valves_repo.find_by_id("1")["status"] == 0


def test_delete_keeps_shared_valve_on_for_overlapping_schedule(tmp_path):
    schedules_repo = JsonLinesRepository(tmp_path / "schedules.json")
    valves_repo = JsonLinesRepository(tmp_path / "valves.json")
    valves_repo.add({"pin": "13", "status": 0, "section": "Horta"})
    gpio = RecordingMockGPIO(15)
    valves = ValveService(valves_repo, gpio)
    schedules = ScheduleService(schedules_repo)
    schedules_repo.add(
        {
            "time": "10:00",
            "duration_minutes": "10",
            "valve_pin": "13",
            "status": 0,
            "enabled": 1,
        }
    )
    schedules_repo.add(
        {
            "time": "10:05",
            "duration_minutes": "10",
            "valve_pin": "13",
            "status": 0,
            "enabled": 1,
        }
    )
    schedules.set_status("1", True)
    schedules.set_status("2", True)
    valves.turn_on(13, force_hardware=True)

    deleted = schedules.delete("1", valves)

    assert deleted is True
    assert [item.id for item in schedules.list_all()] == ["2"]
    assert gpio.states[13] is True
    assert valves_repo.find_by_id("1")["status"] == 1


def test_delete_missing_record_returns_false(tmp_path):
    schedules, valves, _, gpio = create_schedule_service_with_valve(tmp_path)

    deleted = schedules.delete("999", valves)

    assert deleted is False
    assert gpio.operations == []


def test_delete_rejects_empty_identifier(tmp_path):
    schedules, valves, _, _ = create_schedule_service_with_valve(tmp_path)

    with pytest.raises(ValidationError):
        schedules.delete("   ", valves)


def test_delete_without_valve_service_still_removes_record(tmp_path):
    schedules_repo = JsonLinesRepository(tmp_path / "schedules.json")
    schedules = ScheduleService(schedules_repo)
    schedules.create("10:00", "10", "13")
    schedules.set_status("1", True)

    deleted = schedules.delete("1")

    assert deleted is True
    assert schedules.list_all() == []
