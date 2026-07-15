"""Application use cases; no class depends on RPi.GPIO or concrete files."""

from __future__ import annotations

import time
from dataclasses import replace
from datetime import date, datetime, timedelta
from typing import Any

from irrigacao.domain.exceptions import RecordNotFoundError, ValidationError
from irrigacao.domain.models import HistoryRecord, Schedule, Valve
from irrigacao.domain.ports import Clock, GpioController, Repository

WEEKDAYS = (
    "Segunda-feira",
    "Terça-feira",
    "Quarta-feira",
    "Quinta-feira",
    "Sexta-feira",
    "Sábado",
    "Domingo",
)


class ScheduleService:
    def __init__(self, repository: Repository) -> None:
        self._repository = repository

    def list_all(self) -> list[Schedule]:
        return [Schedule.from_dict(item) for item in self._repository.list_all()]

    def create(
        self, schedule_time: str, duration_minutes: Any, valve_pin: Any
    ) -> dict[str, Any]:
        schedule = Schedule.from_dict(
            {
                "horario": schedule_time,
                "tempoLigado": duration_minutes,
                "valvula": valve_pin,
                "status": 0,
                "ativado": 1,
            }
        )
        return self._repository.add(schedule.to_dict())

    def update(
        self,
        record_id: str,
        schedule_time: str,
        duration_minutes: Any,
        valve_pin: Any,
    ) -> dict[str, Any]:
        current = self.get(record_id)
        edited = Schedule.from_dict(
            {
                "id": current.id,
                "horario": schedule_time,
                "tempoLigado": duration_minutes,
                "valvula": valve_pin,
                "status": int(current.status),
                "ativado": int(current.enabled),
            }
        )
        return self._repository.update(edited.to_dict())

    def set_enabled(self, record_id: str, enabled: Any) -> dict[str, Any]:
        current = self.get(record_id)
        value = int(enabled)
        if value not in (0, 1):
            raise ValidationError("enabled must be 0 or 1")
        return self._repository.update(replace(current, enabled=bool(value)).to_dict())

    def set_status(self, record_id: str, status: bool) -> dict[str, Any]:
        current = self.get(record_id)
        return self._repository.update(replace(current, status=status).to_dict())

    def delete(self, record_id: str) -> bool:
        return self._repository.delete([record_id])

    def get(self, record_id: str) -> Schedule:
        data = self._repository.find_by_id(record_id)
        if data is None:
            raise RecordNotFoundError(f"schedule {record_id} not found")
        return Schedule.from_dict(data)


class ValveService:
    def __init__(self, repository: Repository, gpio: GpioController) -> None:
        self._repository = repository
        self._gpio = gpio
        self._configured = False

    def configure(self) -> None:
        valves = self.list_all()
        self._gpio.configure([valve.pin for valve in valves])
        self._configured = True
        for valve in valves:
            if valve.status:
                self._gpio.turn_on(valve.pin)

    def list_all(self) -> list[Valve]:
        return [Valve.from_dict(item) for item in self._repository.list_all()]

    def get_by_pin(self, pin: int) -> Valve:
        for valve in self.list_all():
            if valve.pin == int(pin):
                return valve
        raise RecordNotFoundError(f"valve on pin {pin} not found")

    def turn_on(self, pin: int, force_hardware: bool = False) -> bool:
        self._ensure_configured()
        valve = self.get_by_pin(pin)
        if valve.status and not force_hardware:
            return False
        self._gpio.turn_on(valve.pin)
        if not valve.status:
            updated = replace(valve, status=True, manually_turned_off=False)
            self._repository.update(updated.to_dict())
        return True

    def turn_off(self, pin: int, manual: bool = False) -> bool:
        self._ensure_configured()
        valve = self.get_by_pin(pin)
        if not valve.status:
            return False
        other_active_valves = any(
            item.status and item.pin != valve.pin for item in self.list_all()
        )
        self._gpio.turn_off(valve.pin, keep_pump_on=other_active_valves)
        updated = replace(valve, status=False, manually_turned_off=manual)
        self._repository.update(updated.to_dict())
        return True

    def close(self) -> None:
        self._gpio.close()
        self._configured = False

    def _ensure_configured(self) -> None:
        if not self._configured:
            self.configure()


class HistoryService:
    def __init__(self, history: Repository, search_result: Repository) -> None:
        self._history = history
        self._search_result = search_result

    def record(
        self,
        valve: str,
        start: datetime,
        end: datetime,
        mode: str,
    ) -> dict[str, Any]:
        record = HistoryRecord(
            id="",
            valve=valve,
            date=start.date(),
            start=start.strftime("%H:%M"),
            end=end.strftime("%H:%M"),
            weekday=WEEKDAYS[start.weekday()],
            mode=mode,
        )
        return self._history.add(record.to_dict())

    def search_day(self, day: date) -> list[dict[str, Any]]:
        return self.search_range(day, day)

    def search_range(self, start_date: date, end_date: date) -> list[dict[str, Any]]:
        if start_date > end_date:
            raise ValidationError("start date must be before end date")
        results = [
            item
            for item in self._history.list_all()
            if start_date <= date.fromisoformat(str(item["data"])) <= end_date
        ]
        self._search_result.replace_all(results)
        return results


class SettingsService:
    def __init__(self, repository: Repository) -> None:
        self._repository = repository

    def default_duration_minutes(self) -> int:
        records = self._repository.list_all()
        if not records:
            raise ValidationError("default duration has not been configured yet")
        return int(records[0]["tempoPadrao"])

    def update_default_duration(self, minutes: Any) -> dict[str, Any]:
        try:
            value = int(minutes)
        except (TypeError, ValueError) as exc:
            raise ValidationError("default duration must be an integer") from exc
        if value < 1:
            raise ValidationError("default duration must be greater than zero")
        records = self._repository.list_all()
        if records:
            return self._repository.update(
                {"id": str(records[0]["id"]), "tempoPadrao": value}
            )
        return self._repository.add({"tempoPadrao": value})


class ManualControlService:
    def __init__(
        self,
        valves: ValveService,
        settings: SettingsService,
        history: HistoryService,
        clock: Clock,
        poll_interval: float = 2.0,
    ) -> None:
        self._valves = valves
        self._settings = settings
        self._history = history
        self._clock = clock
        self._poll_interval = poll_interval

    def turn_on(self, pin: int, wait: bool = True) -> bool:
        start = self._clock.now()
        valve = self._valves.get_by_pin(pin)
        if not self._valves.turn_on(pin):
            return False
        end = start + timedelta(minutes=self._settings.default_duration_minutes())
        self._history.record(valve.section, start, end, "Manual")
        if wait:
            self._wait_for_auto_turn_off(pin, end)
        return True

    def turn_off(self, pin: int) -> bool:
        return self._valves.turn_off(pin, manual=True)

    def _wait_for_auto_turn_off(self, pin: int, end: datetime) -> None:
        while self._clock.now() < end:
            if not self._valves.get_by_pin(pin).status:
                return
            time.sleep(self._poll_interval)
        self._valves.turn_off(pin)


class IrrigationController:
    """Runs automatic schedules continuously."""

    def __init__(
        self,
        schedules: ScheduleService,
        valves: ValveService,
        history: HistoryService,
        clock: Clock,
        poll_interval: float = 2.0,
    ) -> None:
        self._schedules = schedules
        self._valves = valves
        self._history = history
        self._clock = clock
        self._poll_interval = poll_interval
        self._started_in_this_process: set[str] = set()

    def run_once(self) -> None:
        now = self._clock.now()
        schedules = self._schedules.list_all()
        active_ids = {
            schedule.id
            for schedule in schedules
            if schedule.enabled and self._is_running(schedule, now)
        }

        for schedule in schedules:
            start, end = schedule.interval_at(now)
            is_running = start <= now < end
            keep_valve_on = any(
                other.id != schedule.id
                and other.id in active_ids
                and other.valve_pin == schedule.valve_pin
                for other in schedules
            )

            if not schedule.enabled:
                if schedule.status:
                    self._stop(schedule, keep_valve_on)
                continue

            if is_running and not schedule.status:
                mode = (
                    "Automático"
                    if now.strftime("%H:%M") == schedule.time
                    else "Automático: após o horário marcado"
                )
                self._start(schedule, now, end, mode, restarted=False)
            elif (
                is_running
                and schedule.status
                and schedule.id not in self._started_in_this_process
            ):
                self._start(schedule, now, end, "Reiniciado", restarted=True)
            elif not is_running and schedule.status:
                self._stop(schedule, keep_valve_on)

    def run(self) -> None:
        self._valves.configure()
        try:
            while True:
                self.run_once()
                time.sleep(self._poll_interval)
        finally:
            self._valves.close()

    def _start(
        self,
        schedule: Schedule,
        now: datetime,
        end: datetime,
        mode: str,
        restarted: bool,
    ) -> None:
        valve = self._valves.get_by_pin(schedule.valve_pin)
        self._valves.turn_on(schedule.valve_pin, force_hardware=restarted)
        if not schedule.status:
            self._schedules.set_status(schedule.id, True)
        self._history.record(valve.section, now, end, mode)
        self._started_in_this_process.add(schedule.id)

    @staticmethod
    def _is_running(schedule: Schedule, now: datetime) -> bool:
        start, end = schedule.interval_at(now)
        return start <= now < end

    def _stop(self, schedule: Schedule, keep_valve_on: bool = False) -> None:
        if not keep_valve_on:
            self._valves.turn_off(schedule.valve_pin)
        self._schedules.set_status(schedule.id, False)
        self._started_in_this_process.discard(schedule.id)
