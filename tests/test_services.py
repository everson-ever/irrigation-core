from datetime import datetime

from irrigation.application.services import (
    HistoryService,
    IrrigationController,
    ScheduleService,
    ValveService,
)
from irrigation.infrastructure.gpio import MockGPIO
from irrigation.infrastructure.json_repository import JsonLinesRepository


class FakeClock:
    def __init__(self, now: datetime) -> None:
        self.value = now

    def now(self) -> datetime:
        return self.value


def create_controller(tmp_path, now: datetime):
    schedules_repo = JsonLinesRepository(tmp_path / "schedules.json")
    valves_repo = JsonLinesRepository(tmp_path / "valves.json")
    history_repo = JsonLinesRepository(tmp_path / "history.json")
    result_repo = JsonLinesRepository(tmp_path / "results.json")
    valves_repo.add({"pin": "13", "status": 0, "section": "Horta"})
    gpio = MockGPIO(15)
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
    assert history.list_all()[0]["mode"] == "Automatic: started after scheduled time"

    clock.value = datetime(2026, 7, 14, 10, 11)
    controller.run_once()

    assert schedules.find_by_id("1")["status"] == 0
    assert valves.find_by_id("1")["status"] == 0
    assert gpio.states[13] is False
    assert gpio.states[15] is False


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
