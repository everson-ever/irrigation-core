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
    schedules_repo = JsonLinesRepository(tmp_path / "schedules.json")
    valves_repo = JsonLinesRepository(tmp_path / "valves.json")
    history_repo = JsonLinesRepository(tmp_path / "history.json")
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
    schedules, valves, valves_repo, gpio = create_schedule_service_with_valve(tmp_path)
    schedules.create("10:00", "10", "13")
    schedules.create("10:05", "10", "13")
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
