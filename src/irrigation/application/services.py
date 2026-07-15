"""Application use cases; no class depends on RPi.GPIO or concrete files."""

from __future__ import annotations

import time
from collections.abc import Iterable
from dataclasses import replace
from datetime import date, datetime, timedelta
from typing import Any

from irrigation.domain.exceptions import RecordNotFoundError, ValidationError
from irrigation.domain.models import HistoryRecord, Schedule, Valve
from irrigation.domain.ports import Clock, GpioController, Repository

WEEKDAYS = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)


class ScheduleService:
    def __init__(self, repository: Repository) -> None:
        self._repository = repository

    def list_all(self) -> list[Schedule]:
        return [Schedule.from_dict(item) for item in self._repository.list_all()]

    def list_with_runtime_status(
        self,
        now: datetime,
        valves: Iterable[Valve] | None = None,
    ) -> list[dict[str, Any]]:
        valve_status_by_pin = None
        if valves is not None:
            valve_status_by_pin = {valve.pin: valve.status for valve in valves}

        records: list[dict[str, Any]] = []
        for schedule in self.list_all():
            record = schedule.to_dict()
            is_running = schedule.status
            valve_status = None
            if valve_status_by_pin is not None:
                valve_status = valve_status_by_pin.get(schedule.valve_pin, False)
            record["is_running"] = is_running
            record["valve_status"] = valve_status
            records.append(record)
        return records

    def create(
        self, schedule_time: str, duration_minutes: Any, valve_pin: Any
    ) -> dict[str, Any]:
        schedule = Schedule.from_dict(
            {
                "time": schedule_time,
                "duration_minutes": duration_minutes,
                "valve_pin": valve_pin,
                "status": 0,
                "enabled": 1,
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
                "time": schedule_time,
                "duration_minutes": duration_minutes,
                "valve_pin": valve_pin,
                "status": int(current.status),
                "enabled": int(current.enabled),
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

    def delete(self, record_id: str, valves: ValveService | None = None) -> bool:
        record_id = str(record_id).strip()
        if not record_id:
            raise ValidationError("schedule id is required")
        existing = self._repository.find_by_id(record_id)
        if existing is None:
            return False
        schedule = Schedule.from_dict(existing)
        deleted = self._repository.delete([record_id])
        if deleted and schedule.status and valves is not None:
            self._release_valve_if_unused(schedule, valves)
        return deleted

    def _release_valve_if_unused(
        self, schedule: Schedule, valves: ValveService
    ) -> None:
        still_needed = any(
            other.valve_pin == schedule.valve_pin and other.status
            for other in self.list_all()
        )
        if not still_needed:
            valves.turn_off(schedule.valve_pin)

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

    def turn_on(
        self,
        pin: int,
        force_hardware: bool = False,
        preserve_manual_stop: bool = False,
    ) -> bool:
        self._ensure_configured()
        valve = self.get_by_pin(pin)
        if valve.status and not force_hardware:
            if valve.manually_turned_off and not preserve_manual_stop:
                self._repository.update(
                    replace(valve, manually_turned_off=False).to_dict()
                )
            return False
        self._gpio.turn_on(valve.pin)
        if not valve.status or valve.manually_turned_off:
            updated = replace(
                valve,
                status=True,
                manually_turned_off=(
                    valve.manually_turned_off and preserve_manual_stop
                ),
            )
            self._repository.update(updated.to_dict())
        return True

    def turn_off(self, pin: int, manual: bool = False) -> bool:
        self._ensure_configured()
        valve = self.get_by_pin(pin)
        if not valve.status:
            if manual and not valve.manually_turned_off:
                self._repository.update(
                    replace(valve, manually_turned_off=True).to_dict()
                )
            return False
        other_active_valves = any(
            item.status and item.pin != valve.pin for item in self.list_all()
        )
        self._gpio.turn_off(valve.pin, keep_pump_on=other_active_valves)
        updated = replace(valve, status=False, manually_turned_off=manual)
        self._repository.update(updated.to_dict())
        return True

    def clear_manual_stop(self, pin: int) -> None:
        valve = self.get_by_pin(pin)
        if valve.manually_turned_off:
            self._repository.update(replace(valve, manually_turned_off=False).to_dict())

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

    def has_active_manual(self, valve: str, now: datetime) -> bool:
        return self._has_active_record(valve, now, lambda mode: mode == "Manual")

    def has_active_automatic(self, valve: str, now: datetime) -> bool:
        return self._has_active_record(valve, now, lambda mode: mode != "Manual")

    def _has_active_record(self, valve: str, now: datetime, mode_matches) -> bool:
        for item in self._history.list_all():
            if str(item.get("valve")) != valve:
                continue
            if not mode_matches(str(item.get("mode", ""))):
                continue
            start = datetime.combine(
                date.fromisoformat(str(item["date"])),
                datetime.strptime(str(item["start"]), "%H:%M").time(),
            )
            end = datetime.combine(
                start.date(),
                datetime.strptime(str(item["end"]), "%H:%M").time(),
            )
            if end <= start:
                end += timedelta(days=1)
            if start <= now < end:
                return True
        return False

    def search_day(self, day: date) -> list[dict[str, Any]]:
        return self.search_range(day, day)

    def search_range(self, start_date: date, end_date: date) -> list[dict[str, Any]]:
        if start_date > end_date:
            raise ValidationError("start date must be before end date")
        results = [
            item
            for item in self._history.list_all()
            if start_date <= date.fromisoformat(str(item["date"])) <= end_date
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
        return int(records[0]["default_duration_minutes"])

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
                {"id": str(records[0]["id"]), "default_duration_minutes": value}
            )
        return self._repository.add({"default_duration_minutes": value})


class ManualControlService:
    def __init__(
        self,
        valves: ValveService,
        settings: SettingsService,
        history: HistoryService,
        clock: Clock,
        poll_interval: float = 2.0,
        schedules: ScheduleService | None = None,
    ) -> None:
        self._valves = valves
        self._settings = settings
        self._history = history
        self._clock = clock
        self._poll_interval = poll_interval
        self._schedules = schedules

    def turn_on(
        self,
        pin: int,
        duration_minutes: Any = None,
        wait: bool = True,
        schedule_id: str | None = None,
    ) -> bool:
        start = self._clock.now()
        valve = self._valves.get_by_pin(pin)
        preserve_manual_stop = (
            valve.manually_turned_off
            and self._has_cancelled_automatic_interval(pin, start)
        )
        valve_changed = self._valves.turn_on(
            pin, preserve_manual_stop=preserve_manual_stop
        )
        schedule_changed = self._set_manual_schedule_status(schedule_id, True)
        if not valve_changed and not schedule_changed:
            return False
        self._clear_expired_schedule_statuses(
            pin, start, except_schedule_id=schedule_id
        )
        duration = self._manual_duration_minutes(duration_minutes)
        end = start + timedelta(minutes=duration)
        if valve_changed:
            self._history.record(valve.section, start, end, "Manual")
        if wait:
            self._wait_for_auto_turn_off(pin, end, preserve_manual_stop, schedule_id)
        return True

    def turn_off(self, pin: int, schedule_id: str | None = None) -> bool:
        schedule_changed = self._set_manual_schedule_status(schedule_id, False)
        valve_changed = self._valves.turn_off(pin, manual=True)
        return valve_changed or schedule_changed

    def _manual_duration_minutes(self, duration_minutes: Any = None) -> int:
        if duration_minutes in (None, ""):
            return self._settings.default_duration_minutes()
        try:
            duration = int(duration_minutes)
        except (TypeError, ValueError) as exc:
            raise ValidationError("manual duration must be an integer") from exc
        if duration < 1:
            raise ValidationError("manual duration must be greater than zero")
        return duration

    def _wait_for_auto_turn_off(
        self,
        pin: int,
        end: datetime,
        preserve_manual_stop: bool,
        schedule_id: str | None,
    ) -> None:
        while self._clock.now() < end:
            if not self._valves.get_by_pin(pin).status:
                self._set_manual_schedule_status(schedule_id, False)
                return
            time.sleep(self._poll_interval)
        self._set_manual_schedule_status(schedule_id, False)
        if not self._has_other_running_schedule_on_valve(pin, schedule_id):
            self._valves.turn_off(pin, manual=preserve_manual_stop)

    def _has_cancelled_automatic_interval(self, pin: int, now: datetime) -> bool:
        if self._schedules is None:
            return False
        return any(
            schedule.valve_pin == int(pin)
            and schedule.status
            and schedule.is_running_at(now)
            for schedule in self._schedules.list_all()
        )

    def _clear_expired_schedule_statuses(
        self,
        pin: int,
        now: datetime,
        except_schedule_id: str | None = None,
    ) -> None:
        if self._schedules is None:
            return
        for schedule in self._schedules.list_all():
            if (
                schedule.valve_pin == int(pin)
                and schedule.id != str(except_schedule_id or "")
                and schedule.status
                and not schedule.is_running_at(now)
            ):
                self._schedules.set_status(schedule.id, False)

    def _set_manual_schedule_status(
        self, schedule_id: str | None, status: bool
    ) -> bool:
        if self._schedules is None or schedule_id in (None, ""):
            return False
        schedule = self._schedules.get(str(schedule_id))
        if schedule.status == status:
            return False
        self._schedules.set_status(schedule.id, status)
        return True

    def _has_other_running_schedule_on_valve(
        self, pin: int, schedule_id: str | None
    ) -> bool:
        if self._schedules is None:
            return False
        return any(
            schedule.valve_pin == int(pin)
            and schedule.status
            and schedule.id != str(schedule_id or "")
            for schedule in self._schedules.list_all()
        )


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
            if schedule.status and schedule.is_running_at(now)
        }

        for schedule in schedules:
            start, end = schedule.interval_at(now)
            is_running = schedule.is_running_at(now)
            valve = self._valves.get_by_pin(schedule.valve_pin)
            active_manual = self._history.has_active_manual(valve.section, now)
            keep_valve_on = (
                any(
                    other.id != schedule.id
                    and other.id in active_ids
                    and other.valve_pin == schedule.valve_pin
                    for other in schedules
                )
                or active_manual
            )

            if not schedule.enabled:
                if schedule.status:
                    self._stop(schedule, keep_valve_on)
                continue

            if is_running and not schedule.status:
                if valve.manually_turned_off and self._history.has_active_automatic(
                    valve.section, now
                ):
                    continue
                if valve.manually_turned_off:
                    self._valves.clear_manual_stop(schedule.valve_pin)
                mode = (
                    "Automatic"
                    if now.strftime("%H:%M") == schedule.time
                    else "Automatic: started after scheduled time"
                )
                self._start(schedule, now, end, mode, restarted=False)
            elif (
                is_running
                and schedule.status
                and schedule.id not in self._started_in_this_process
            ):
                if valve.manually_turned_off and self._history.has_active_automatic(
                    valve.section, now
                ):
                    continue
                if valve.manually_turned_off:
                    self._valves.clear_manual_stop(schedule.valve_pin)
                self._start(schedule, now, end, "Restarted", restarted=True)
            elif not is_running and schedule.status and not active_manual:
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

    def _stop(self, schedule: Schedule, keep_valve_on: bool = False) -> None:
        valve = self._valves.get_by_pin(schedule.valve_pin)
        if not keep_valve_on and not valve.manually_turned_off:
            self._valves.turn_off(schedule.valve_pin)
        self._schedules.set_status(schedule.id, False)
        self._started_in_this_process.discard(schedule.id)
