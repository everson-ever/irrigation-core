"""Application use cases; no class depends on RPi.GPIO or concrete files."""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import time
from collections.abc import Iterable
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

from irrigation.domain.exceptions import RecordNotFoundError, ValidationError
from irrigation.domain.models import (
    HistoryRecord,
    NotificationConfig,
    NotificationEvent,
    Schedule,
    Sensor,
    SensorHealth,
    SensorKind,
    SensorState,
    Valve,
)
from irrigation.domain.ports import (
    Clock,
    GpioController,
    NotificationConfigRepository,
    Notifier,
    Repository,
    SensorStateRepository,
)

WEEKDAY_NAMES = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)

HISTORY_MODE_MANUAL = "Manual"
HISTORY_MODE_AUTOMATIC = "Automatic"
HISTORY_MODE_AUTOMATIC_LATE_START = "Automatic: started after scheduled time"
HISTORY_MODE_RESTARTED = "Restarted"

# Keep only the configured window of execution history; older records are
# pruned when a new one is recorded, bounding storage on the target hardware.
# 7 days is the default until the user configures a different period.
HISTORY_RETENTION_DEFAULT_DAYS = 7
HISTORY_RETENTION_ALLOWED_DAYS = (7, 15, 30, 90)

DEFAULT_AUTH_USERNAME = "admin"
DEFAULT_AUTH_PASSWORD = "10203040"
MIN_PASSWORD_LENGTH = 8
PASSWORD_HASH_ALGORITHM = "pbkdf2_sha256"
PASSWORD_HASH_ITERATIONS = 200_000
PASSWORD_SALT_BYTES = 16

LOGGER = logging.getLogger(__name__)


class NotificationService:
    def __init__(
        self,
        repository: NotificationConfigRepository,
        notifier: Notifier,
    ) -> None:
        self._repository = repository
        self._notifier = notifier

    def get_config(self) -> NotificationConfig:
        record = self._repository.get()
        if record is None:
            return NotificationConfig.empty()
        return NotificationConfig.from_dict(record)

    def save_webhook(self, webhook_url: Any) -> dict[str, Any]:
        normalized = self._validate_webhook_url(webhook_url)
        return NotificationConfig.from_dict(
            self._repository.save_webhook(normalized)
        ).to_dict()

    def delete_webhook(self) -> dict[str, Any]:
        return NotificationConfig.from_dict(self._repository.delete_webhook()).to_dict()

    def set_event_enabled(self, event: Any, enabled: Any) -> dict[str, Any]:
        try:
            notification_event = NotificationEvent(str(event).strip())
        except ValueError as exc:
            supported = ", ".join(item.value for item in NotificationEvent)
            raise ValidationError(
                f"notification event must be one of: {supported}"
            ) from exc
        value = self._enabled_value(enabled)
        if value and self.get_config().webhook_url is None:
            raise ValidationError(
                "configure a Discord webhook before enabling notifications"
            )
        return NotificationConfig.from_dict(
            self._repository.set_event_enabled(notification_event.value, value)
        ).to_dict()

    def notify(self, event: NotificationEvent | str, **context: Any) -> None:
        try:
            notification_event = NotificationEvent(event)
            config = self.get_config()
            if (
                config.webhook_url is None
                or notification_event not in config.enabled_events
            ):
                return
            self._notifier.send(
                config.webhook_url,
                self._message(notification_event, context),
            )
        except Exception:
            LOGGER.warning(
                "Discord notification could not be dispatched for event %s",
                event,
                exc_info=True,
            )

    @staticmethod
    def _validate_webhook_url(value: Any) -> str:
        error_message = (
            "webhook URL must use https://discord.com/api/webhooks/<id>/<token>"
        )
        webhook_url = str(value).strip()
        try:
            parsed = urlparse(webhook_url)
            hostname = parsed.hostname
            port = parsed.port
        except ValueError as exc:
            raise ValidationError(error_message) from exc
        path_parts = [part for part in parsed.path.split("/") if part]
        valid_path = (
            len(path_parts) == 4
            and path_parts[0] == "api"
            and path_parts[1] == "webhooks"
            and path_parts[2].isdigit()
            and bool(path_parts[3])
        )
        if (
            parsed.scheme != "https"
            or hostname != "discord.com"
            or port not in (None, 443)
            or len(webhook_url) > 500
            or parsed.username is not None
            or parsed.password is not None
            or not valid_path
        ):
            raise ValidationError(error_message)
        return webhook_url

    @staticmethod
    def _enabled_value(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, int) and value in (0, 1):
            return bool(value)
        if isinstance(value, str) and value.strip() in ("0", "1"):
            return value.strip() == "1"
        raise ValidationError("enabled must be 0 or 1")

    @staticmethod
    def _message(event: NotificationEvent, context: dict[str, Any]) -> str:
        times = context.get("times", context.get("time", "horário não informado"))
        if isinstance(times, (list, tuple)):
            times = ", ".join(str(item) for item in times)
        duration = context.get("duration_minutes", "?")
        pin = context.get("valve_pin", context.get("pin", "?"))
        section = context.get("section", "")
        schedule_name = section or f"no pino {pin}"
        schedule_valve = f"pino {pin}"
        messages = {
            NotificationEvent.SECTION_ON: (
                f"Seção {section or '?'} ligada: pino {pin}."
            ),
            NotificationEvent.SECTION_OFF: (
                f"Seção {section or '?'} desligada: pino {pin}."
            ),
            NotificationEvent.SCHEDULE_RESTARTED: (
                f"Agendamento {schedule_name} reiniciado após o controlador voltar: "
                f"{times}, {schedule_valve}."
            ),
            NotificationEvent.SCHEDULE_CREATED: (
                f"Agendamento {schedule_name} cadastrado: {times}, duração de "
                f"{duration} min, {schedule_valve}."
            ),
            NotificationEvent.SCHEDULE_UPDATED: (
                f"Agendamento {schedule_name} editado: {times}, duração de "
                f"{duration} min, {schedule_valve}."
            ),
            NotificationEvent.SCHEDULE_DELETED: (
                f"Agendamento {schedule_name} excluído: {times}, {schedule_valve}."
            ),
            NotificationEvent.SECTION_CREATED: (
                f"Seção {section or '?'} cadastrada: "
                f"ID {context.get('section_id', '?')}, "
                f"pino {pin}."
            ),
            NotificationEvent.SECTION_UPDATED: (
                f"Seção {section or '?'} editada: ID {context.get('section_id', '?')}, "
                f"pino {pin}."
            ),
            NotificationEvent.SECTION_DELETED: (
                f"Seção {section or '?'} excluída: "
                f"ID {context.get('section_id', '?')}, "
                f"pino {pin}."
            ),
            NotificationEvent.PASSWORD_CHANGED: (
                f"Senha da conta {context.get('username', 'admin')} alterada."
            ),
        }
        return messages[event]


class ScheduleService:
    DUPLICATE_VALVE_MESSAGE = "This valve/section already has a schedule"

    def __init__(
        self,
        repository: Repository,
        notifications: NotificationService | None = None,
        valve_repository: Repository | None = None,
    ) -> None:
        self._repository = repository
        self._notifications = notifications
        self._valve_repository = valve_repository

    def list_all(self) -> list[Schedule]:
        return [Schedule.from_dict(item) for item in self._repository.list_all()]

    def list_with_runtime_status(
        self,
        now: datetime,
        valves: Iterable[Valve] | None = None,
        history: HistoryService | None = None,
    ) -> list[dict[str, Any]]:
        valve_status_by_pin = None
        valve_section_by_pin = None
        if valves is not None:
            valve_list = list(valves)
            valve_status_by_pin = {valve.pin: valve.status for valve in valve_list}
            valve_section_by_pin = {valve.pin: valve.section for valve in valve_list}

        records: list[dict[str, Any]] = []
        for schedule in self.list_all():
            record = schedule.to_dict()
            is_running = schedule.status
            valve_status = None
            if valve_status_by_pin is not None:
                valve_status = valve_status_by_pin.get(schedule.valve_pin, False)
            record["is_running"] = is_running
            record["valve_status"] = valve_status
            if is_running and history is not None and valve_section_by_pin is not None:
                section = valve_section_by_pin.get(schedule.valve_pin)
                if section is not None:
                    active_end = history.active_end(section, now)
                    if active_end is not None:
                        remaining_seconds = round(
                            max(0, (active_end - now).total_seconds())
                        )
                        record["remaining_seconds"] = remaining_seconds
            records.append(record)
        return records

    def create(
        self,
        schedule_time: str,
        duration_minutes: Any,
        valve_pin: Any,
        weekdays: Any = None,
    ) -> dict[str, Any]:
        schedule = Schedule.from_dict(
            {
                "time": schedule_time,
                "duration_minutes": duration_minutes,
                "valve_pin": valve_pin,
                "status": 0,
                "enabled": 1,
                "weekdays": weekdays,
            }
        )
        self._reject_duplicate_valve(schedule.valve_pin)
        created = self._repository.add(schedule.to_dict())
        self._notify_schedule(NotificationEvent.SCHEDULE_CREATED, created)
        return created

    def update(
        self,
        record_id: str,
        schedule_time: str,
        duration_minutes: Any,
        valve_pin: Any,
        weekdays: Any = None,
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
                "weekdays": current.weekdays if weekdays is None else weekdays,
            }
        )
        self._reject_duplicate_valve(edited.valve_pin, exclude_id=edited.id)
        updated = self._repository.update(edited.to_dict())
        self._notify_schedule(NotificationEvent.SCHEDULE_UPDATED, updated)
        return updated

    def _reject_duplicate_valve(
        self, valve_pin: int, exclude_id: str | None = None
    ) -> None:
        for schedule in self.list_all():
            if exclude_id is not None and schedule.id == exclude_id:
                continue
            if schedule.valve_pin == valve_pin:
                raise ValidationError(self.DUPLICATE_VALVE_MESSAGE)

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
        if deleted:
            self._notify_schedule(
                NotificationEvent.SCHEDULE_DELETED, schedule.to_dict()
            )
        return deleted

    def _notify_schedule(
        self, event: NotificationEvent, schedule: dict[str, Any]
    ) -> None:
        if self._notifications is not None:
            valve_pin = schedule.get("valve_pin")
            self._notifications.notify(
                event,
                schedule_id=schedule.get("id"),
                times=schedule.get("times", schedule.get("time")),
                duration_minutes=schedule.get("duration_minutes"),
                valve_pin=valve_pin,
                section=self._section_name(valve_pin),
            )

    def _section_name(self, valve_pin: Any) -> str | None:
        if self._valve_repository is None:
            return None
        try:
            for valve in self._valve_repository.list_all():
                if int(valve["pin"]) == int(valve_pin):
                    return str(valve["section"])
        except Exception:
            LOGGER.warning(
                "Valve section could not be resolved for schedule notification",
                exc_info=True,
            )
        return None

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
    DUPLICATE_PIN_MESSAGE = "This GPIO pin is already registered for another section"
    VALVE_IN_USE_MESSAGE = "This valve/section is still used by a schedule"
    VALVE_SENSOR_IN_USE_MESSAGE = "This valve/section is still used by a sensor"

    def __init__(
        self,
        repository: Repository,
        gpio: GpioController,
        notifications: NotificationService | None = None,
    ) -> None:
        self._repository = repository
        self._gpio = gpio
        self._configured = False
        self._notifications = notifications

    def configure(self) -> None:
        valves = self.list_all()
        self._gpio.configure([valve.pin for valve in valves])
        self._configured = True
        for valve in valves:
            if valve.status:
                self._gpio.turn_on(valve.pin)

    def list_all(self) -> list[Valve]:
        return [Valve.from_dict(item) for item in self._repository.list_all()]

    def add(self, pin: Any, section: Any) -> Valve:
        valve = self._build_valve("", pin, section)
        self._reject_duplicate_pin(valve.pin)
        created = Valve.from_dict(self._repository.add(valve.to_dict()))
        self._configured = False
        self._notify_section(NotificationEvent.SECTION_CREATED, created)
        return created

    def update(self, valve_id: str, pin: Any, section: Any) -> Valve:
        current = self.get(valve_id)
        edited = self._build_valve(current.id, pin, section, current)
        self._reject_duplicate_pin(edited.pin, exclude_id=edited.id)
        if current.status and current.pin != edited.pin:
            self.turn_off(current.pin)
            edited = replace(edited, status=False, manually_turned_off=False)
        updated = Valve.from_dict(self._repository.update(edited.to_dict()))
        self._configured = False
        self._notify_section(NotificationEvent.SECTION_UPDATED, updated)
        return updated

    def remove(
        self,
        valve_id: str,
        schedules: ScheduleService,
        sensors: SensorService | None = None,
    ) -> bool:
        valve_id = str(valve_id).strip()
        if not valve_id:
            raise ValidationError("valve id is required")
        existing = self._repository.find_by_id(valve_id)
        if existing is None:
            return False
        valve = Valve.from_dict(existing)
        if any(schedule.valve_pin == valve.pin for schedule in schedules.list_all()):
            raise ValidationError(self.VALVE_IN_USE_MESSAGE)
        if sensors is not None and any(
            sensor.valve_id == valve.id for sensor in sensors.list_all()
        ):
            raise ValidationError(self.VALVE_SENSOR_IN_USE_MESSAGE)
        if valve.status:
            self.turn_off(valve.pin)
        deleted = self._repository.delete([valve_id])
        if deleted:
            self._configured = False
            self._notify_section(NotificationEvent.SECTION_DELETED, valve)
        return deleted

    def _notify_section(self, event: NotificationEvent, valve: Valve) -> None:
        if self._notifications is not None:
            self._notifications.notify(
                event,
                section_id=valve.id,
                section=valve.section,
                pin=valve.pin,
            )

    def get(self, record_id: str) -> Valve:
        data = self._repository.find_by_id(str(record_id).strip())
        if data is None:
            raise RecordNotFoundError(f"valve {record_id} not found")
        return Valve.from_dict(data)

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
                self._save(replace(valve, manually_turned_off=False))
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
            self._save(updated)
        return True

    def turn_off(self, pin: int, manual: bool = False) -> bool:
        self._ensure_configured()
        valve = self.get_by_pin(pin)
        if not valve.status:
            if manual and not valve.manually_turned_off:
                self._save(replace(valve, manually_turned_off=True))
            return False
        other_active_valves = any(
            item.status and item.pin != valve.pin for item in self.list_all()
        )
        self._gpio.turn_off(valve.pin, keep_pump_on=other_active_valves)
        updated = replace(valve, status=False, manually_turned_off=manual)
        self._save(updated)
        return True

    def clear_manual_stop(self, pin: int) -> None:
        valve = self.get_by_pin(pin)
        if valve.manually_turned_off:
            self._save(replace(valve, manually_turned_off=False))

    def close(self) -> None:
        self._gpio.close()
        self._configured = False

    def _ensure_configured(self) -> None:
        if not self._configured:
            self.configure()

    def _save(self, valve: Valve) -> dict[str, Any]:
        return self._repository.update(valve.to_dict())

    def _build_valve(
        self,
        valve_id: str,
        pin: Any,
        section: Any,
        current: Valve | None = None,
    ) -> Valve:
        section_name = str(section).strip()
        if not section_name:
            raise ValidationError("section name is required")
        return Valve.from_dict(
            {
                "id": valve_id,
                "pin": pin,
                "section": section_name,
                "status": int(current.status) if current is not None else 0,
                "manually_turned_off": (
                    int(current.manually_turned_off) if current is not None else 0
                ),
            }
        )

    def _reject_duplicate_pin(
        self,
        pin: int,
        exclude_id: str | None = None,
    ) -> None:
        for valve in self.list_all():
            if exclude_id is not None and valve.id == exclude_id:
                continue
            if valve.pin == pin:
                raise ValidationError(self.DUPLICATE_PIN_MESSAGE)


class SensorService:
    """Common sensor lifecycle and latest-status use cases."""

    DUPLICATE_NAME_MESSAGE = "A sensor with this name already exists"
    SENSOR_IN_USE_MESSAGE = "This sensor is still referenced by a safety policy"

    def __init__(
        self,
        repository: Repository,
        state_repository: SensorStateRepository,
        valves: ValveService,
        available_kinds: Iterable[SensorKind | str] = (),
    ) -> None:
        self._repository = repository
        self._state_repository = state_repository
        self._valves = valves
        self._available_kinds = {SensorKind(kind) for kind in available_kinds}

    def list_all(self) -> list[Sensor]:
        return [Sensor.from_dict(item) for item in self._repository.list_all()]

    def list_with_status(self) -> list[dict[str, Any]]:
        states = {
            str(item["sensor_id"]): SensorState.from_dict(item)
            for item in self._state_repository.list_all()
        }
        sections = {valve.id: valve.section for valve in self._valves.list_all()}
        return [
            self._presentation(sensor, states.get(sensor.id), sections)
            for sensor in self.list_all()
        ]

    def get(self, record_id: Any) -> Sensor:
        sensor_id = self._sensor_id(record_id)
        data = self._repository.find_by_id(sensor_id)
        if data is None:
            raise RecordNotFoundError(f"sensor {sensor_id} not found")
        return Sensor.from_dict(data)

    def get_with_status(self, record_id: Any) -> dict[str, Any]:
        sensor = self.get(record_id)
        state_data = self._state_repository.find_by_sensor_id(sensor.id)
        state = None if state_data is None else SensorState.from_dict(state_data)
        sections = {valve.id: valve.section for valve in self._valves.list_all()}
        return self._presentation(sensor, state, sections)

    def add(
        self,
        name: Any,
        kind: Any,
        enabled: Any = 1,
        valve_id: Any = None,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        sensor = Sensor(
            id="",
            name=name,
            kind=kind,
            enabled=enabled,
            valve_id=valve_id,
            created_at=now,
            updated_at=now,
        )
        self._validate_name(sensor.name)
        self._validate_valve(sensor.valve_id)
        created = Sensor.from_dict(self._repository.add(sensor.to_dict()))
        return self.get_with_status(created.id)

    def update(
        self,
        record_id: Any,
        name: Any,
        kind: Any,
        enabled: Any,
        valve_id: Any = None,
    ) -> dict[str, Any]:
        current = self.get(record_id)
        edited = Sensor(
            id=current.id,
            name=name,
            kind=kind,
            enabled=enabled,
            valve_id=valve_id,
            created_at=current.created_at,
            updated_at=datetime.now(timezone.utc),
        )
        self._validate_name(edited.name, exclude_id=edited.id)
        self._validate_valve(edited.valve_id)
        self._repository.update(edited.to_dict())
        return self.get_with_status(edited.id)

    def set_enabled(self, record_id: Any, enabled: Any) -> dict[str, Any]:
        current = self.get(record_id)
        edited = Sensor(
            id=current.id,
            name=current.name,
            kind=current.kind,
            enabled=enabled,
            valve_id=current.valve_id,
            created_at=current.created_at,
            updated_at=datetime.now(timezone.utc),
        )
        self._repository.update(edited.to_dict())
        return self.get_with_status(edited.id)

    def remove(
        self,
        record_id: Any,
        referenced_sensor_ids: Iterable[str] = (),
    ) -> bool:
        sensor_id = self._sensor_id(record_id)
        if self._repository.find_by_id(sensor_id) is None:
            return False
        if sensor_id in {str(item) for item in referenced_sensor_ids}:
            raise ValidationError(self.SENSOR_IN_USE_MESSAGE)
        return self._repository.delete([sensor_id])

    def status(self, record_id: Any = None) -> Any:
        if record_id is None or str(record_id).strip() == "":
            return self.list_with_status()
        return self.get_with_status(record_id)

    def record_state(
        self,
        record_id: Any,
        health: Any,
        value: Any = None,
        unit: Any = None,
        raw_value: Any = None,
        latest_read_at: datetime | str | None = None,
        error_message: Any = None,
    ) -> SensorState:
        sensor = self.get(record_id)
        now = datetime.now(timezone.utc)
        state = SensorState(
            sensor_id=sensor.id,
            health=health,
            value=value,
            unit=unit,
            raw_value=raw_value,
            latest_read_at=latest_read_at,
            error_message=error_message,
            updated_at=now,
        )
        return SensorState.from_dict(self._state_repository.upsert(state.to_dict()))

    def _presentation(
        self,
        sensor: Sensor,
        state: SensorState | None,
        sections: dict[str, str],
    ) -> dict[str, Any]:
        current = state or SensorState.unknown(sensor.id, sensor.updated_at)
        record = sensor.to_dict()
        record["section"] = sections.get(sensor.valve_id or "")
        record["state"] = current.to_dict()
        record["configuration_status"] = "configured"
        record["driver_available"] = sensor.kind in self._available_kinds
        if not sensor.enabled:
            record["availability"] = "disabled"
        elif current.health is SensorHealth.FAULT:
            record["availability"] = "fault"
        elif current.health is SensorHealth.STALE:
            record["availability"] = "stale"
        elif current.health is SensorHealth.WARNING:
            record["availability"] = "warning"
        elif not record["driver_available"] and current.latest_read_at is None:
            record["availability"] = "unsupported"
        elif current.health is SensorHealth.OK:
            record["availability"] = "operational"
        else:
            record["availability"] = "unknown"
        return record

    def _validate_name(self, name: str, exclude_id: str | None = None) -> None:
        normalized = name.casefold()
        if any(
            sensor.name.casefold() == normalized and sensor.id != exclude_id
            for sensor in self.list_all()
        ):
            raise ValidationError(self.DUPLICATE_NAME_MESSAGE)

    def _validate_valve(self, valve_id: str | None) -> None:
        if valve_id is not None:
            try:
                self._valves.get(valve_id)
            except RecordNotFoundError as exc:
                raise ValidationError(
                    f"associated valve/section {valve_id} does not exist"
                ) from exc

    @staticmethod
    def _sensor_id(value: Any) -> str:
        sensor_id = str(value).strip()
        if not sensor_id.isdigit() or int(sensor_id) < 1:
            raise ValidationError("sensor id must be a positive integer")
        return sensor_id


class HistorySettingsService:
    def __init__(self, repository: Repository) -> None:
        self._repository = repository

    def retention_days(self) -> int:
        records = self._repository.list_all()
        if not records:
            return HISTORY_RETENTION_DEFAULT_DAYS
        return int(records[0]["retention_days"])

    def update_retention_days(self, value: Any) -> dict[str, Any]:
        try:
            days = int(value)
        except (TypeError, ValueError) as exc:
            raise ValidationError("retention days must be an integer") from exc
        if days not in HISTORY_RETENTION_ALLOWED_DAYS:
            raise ValidationError(
                "retention days must be one of "
                f"{', '.join(str(item) for item in HISTORY_RETENTION_ALLOWED_DAYS)}"
            )
        records = self._repository.list_all()
        if records:
            return self._repository.update(
                {"id": str(records[0]["id"]), "retention_days": days}
            )
        return self._repository.add({"retention_days": days})


class HistoryService:
    def __init__(
        self,
        history: Repository,
        search_result: Repository,
        retention: HistorySettingsService | None = None,
    ) -> None:
        self._history = history
        self._search_result = search_result
        self._retention = retention

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
            weekday=WEEKDAY_NAMES[start.weekday()],
            mode=mode,
        )
        added = self._history.add(record.to_dict())
        self._prune_expired(start.date())
        return added

    def _prune_expired(self, reference: date) -> None:
        prune = getattr(self._history, "delete_before", None)
        if not callable(prune):
            return
        retention_days = (
            self._retention.retention_days()
            if self._retention is not None
            else HISTORY_RETENTION_DEFAULT_DAYS
        )
        cutoff = reference - timedelta(days=retention_days)
        prune(cutoff.isoformat())

    def has_active_manual(self, valve: str, now: datetime) -> bool:
        return (
            self._active_record_end(
                valve, now, lambda mode: mode == HISTORY_MODE_MANUAL
            )
            is not None
        )

    def has_active_automatic(self, valve: str, now: datetime) -> bool:
        return (
            self._active_record_end(
                valve, now, lambda mode: mode != HISTORY_MODE_MANUAL
            )
            is not None
        )

    def active_end(self, valve: str, now: datetime) -> datetime | None:
        return self._active_record_end(valve, now, lambda _mode: True)

    def _active_record_end(
        self, valve: str, now: datetime, mode_matches
    ) -> datetime | None:
        active_ends: list[datetime] = []
        for item in self._history.list_all():
            if str(item.get("valve")) != valve:
                continue
            if not mode_matches(str(item.get("mode", ""))):
                continue
            start, end = self._record_interval(item)
            if start <= now < end:
                active_ends.append(end)
        if not active_ends:
            return None
        return max(active_ends)

    def _record_interval(self, item: dict[str, Any]) -> tuple[datetime, datetime]:
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
        return start, end

    def search_day(self, day: date) -> list[dict[str, Any]]:
        return self.search_range(day, day)

    def search_range(self, start_date: date, end_date: date) -> list[dict[str, Any]]:
        if start_date > end_date:
            raise ValidationError("start date must be before end date")
        indexed_search = getattr(self._history, "find_by_date_range", None)
        if callable(indexed_search):
            results = indexed_search(start_date.isoformat(), end_date.isoformat())
        else:
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


class AuthService:
    def __init__(
        self,
        repository: Repository,
        notifications: NotificationService | None = None,
    ) -> None:
        self._repository = repository
        self._notifications = notifications

    def ensure_default_credentials(self) -> None:
        if self._repository.list_all():
            return
        self._repository.add(
            {
                "username": DEFAULT_AUTH_USERNAME,
                "password_hash": self._hash_password(DEFAULT_AUTH_PASSWORD),
            }
        )

    def reset_to_default(self) -> dict[str, Any]:
        credentials = self._repository.list_all()
        default_credential = {
            "username": DEFAULT_AUTH_USERNAME,
            "password_hash": self._hash_password(DEFAULT_AUTH_PASSWORD),
        }
        if not credentials:
            return self._repository.add(default_credential)
        return self._repository.update(
            {"id": str(credentials[0]["id"]), **default_credential}
        )

    def verify(self, username: Any, password: Any) -> bool:
        credential = self._credential_for(username)
        if credential is None:
            return False
        return self._verify_password(str(password), str(credential["password_hash"]))

    def change_password(
        self,
        username: Any,
        current_password: Any,
        new_password: Any,
    ) -> dict[str, Any]:
        credential = self._credential_for(username)
        if credential is None or not self._verify_password(
            str(current_password),
            str(credential["password_hash"]),
        ):
            raise ValidationError("invalid username or password")

        password = str(new_password)
        if len(password) < MIN_PASSWORD_LENGTH:
            raise ValidationError(
                f"new password must contain at least {MIN_PASSWORD_LENGTH} characters"
            )

        updated = self._repository.update(
            {
                "id": str(credential["id"]),
                "username": str(credential["username"]),
                "password_hash": self._hash_password(password),
            }
        )
        if self._notifications is not None:
            self._notifications.notify(
                NotificationEvent.PASSWORD_CHANGED,
                username=str(credential["username"]),
            )
        return updated

    def _credential_for(self, username: Any) -> dict[str, Any] | None:
        normalized_username = str(username).strip()
        for credential in self._repository.list_all():
            if str(credential["username"]) == normalized_username:
                return credential
        return None

    @staticmethod
    def _hash_password(password: str) -> str:
        salt = secrets.token_bytes(PASSWORD_SALT_BYTES)
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            PASSWORD_HASH_ITERATIONS,
        )
        return "$".join(
            (
                PASSWORD_HASH_ALGORITHM,
                str(PASSWORD_HASH_ITERATIONS),
                salt.hex(),
                digest.hex(),
            )
        )

    @staticmethod
    def _verify_password(password: str, encoded_hash: str) -> bool:
        try:
            algorithm, iterations, salt, expected = encoded_hash.split("$", 3)
            if algorithm != PASSWORD_HASH_ALGORITHM:
                return False
            digest = hashlib.pbkdf2_hmac(
                "sha256",
                password.encode("utf-8"),
                bytes.fromhex(salt),
                int(iterations),
            ).hex()
        except (TypeError, ValueError):
            return False
        return hmac.compare_digest(digest, expected)


class RuntimeHealthService:
    """Tracks whether the long-running automatic controller is alive."""

    def __init__(self, repository: Any) -> None:
        self._repository = repository

    def touch(self, now: datetime) -> None:
        self._repository.touch(_utc_isoformat(now))

    def status(self, now: datetime, max_age_seconds: float) -> dict[str, Any]:
        last_seen = self._repository.last_seen_at()
        age_seconds = None
        online = False
        if last_seen is not None:
            last_seen_at = datetime.fromisoformat(last_seen)
            age_seconds = max(0.0, (_as_utc(now) - last_seen_at).total_seconds())
            online = age_seconds <= max_age_seconds

        return {
            "status": "online" if online else "offline",
            "component": "irrigation-core",
            "last_seen_at": last_seen,
            "age_seconds": age_seconds,
            "max_age_seconds": max_age_seconds,
        }


def _utc_isoformat(value: datetime) -> str:
    return _as_utc(value).isoformat(timespec="seconds")


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class ManualControlService:
    def __init__(
        self,
        valves: ValveService,
        settings: SettingsService,
        history: HistoryService,
        clock: Clock,
        poll_interval: float = 2.0,
        schedules: ScheduleService | None = None,
        notifications: NotificationService | None = None,
    ) -> None:
        self._valves = valves
        self._settings = settings
        self._history = history
        self._clock = clock
        self._poll_interval = poll_interval
        self._schedules = schedules
        self._notifications = notifications

    def turn_on(
        self,
        pin: int,
        duration_minutes: Any = None,
        wait: bool = True,
        schedule_id: str | None = None,
    ) -> bool:
        start, valve, preserve_manual_stop = self._manual_start_context(pin)
        valve_changed, schedule_changed = self._apply_manual_start(
            pin, preserve_manual_stop, schedule_id
        )
        if not valve_changed and not schedule_changed:
            return False
        self._complete_manual_start(
            pin,
            start,
            valve,
            preserve_manual_stop,
            valve_changed,
            duration_minutes,
            wait,
            schedule_id,
        )
        return True

    def turn_off(self, pin: int, schedule_id: str | None = None) -> bool:
        valve = self._valves.get_by_pin(pin)
        schedule_changed = self._set_manual_schedule_status(schedule_id, False)
        valve_changed = self._valves.turn_off(pin, manual=True)
        changed = valve_changed or schedule_changed
        if changed and self._notifications is not None:
            self._notifications.notify(
                NotificationEvent.SECTION_OFF,
                section=valve.section,
                pin=valve.pin,
            )
        return changed

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

    def _manual_start_context(self, pin: int) -> tuple[datetime, Valve, bool]:
        start = self._clock.now()
        valve = self._valves.get_by_pin(pin)
        preserve_manual_stop = (
            valve.manually_turned_off
            and self._has_cancelled_automatic_interval(pin, start)
        )
        return start, valve, preserve_manual_stop

    def _apply_manual_start(
        self,
        pin: int,
        preserve_manual_stop: bool,
        schedule_id: str | None,
    ) -> tuple[bool, bool]:
        valve_changed = self._valves.turn_on(
            pin, preserve_manual_stop=preserve_manual_stop
        )
        schedule_changed = self._set_manual_schedule_status(schedule_id, True)
        return valve_changed, schedule_changed

    def _complete_manual_start(
        self,
        pin: int,
        start: datetime,
        valve: Valve,
        preserve_manual_stop: bool,
        valve_changed: bool,
        duration_minutes: Any,
        wait: bool,
        schedule_id: str | None,
    ) -> None:
        self._clear_expired_schedule_statuses(
            pin, start, except_schedule_id=schedule_id
        )
        duration = self._manual_duration_minutes(duration_minutes)
        end = start + timedelta(minutes=duration)
        if valve_changed:
            self._history.record(valve.section, start, end, HISTORY_MODE_MANUAL)
        if self._notifications is not None:
            self._notifications.notify(
                NotificationEvent.SECTION_ON,
                section=valve.section,
                pin=valve.pin,
                duration_minutes=duration,
            )
        if wait:
            self._wait_for_auto_turn_off(pin, end, preserve_manual_stop, schedule_id)

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
        schedules = self._schedule_service()
        if schedules is None:
            return False
        return any(
            schedule.valve_pin == int(pin)
            and schedule.status
            and schedule.is_running_at(now)
            for schedule in schedules.list_all()
        )

    def _clear_expired_schedule_statuses(
        self,
        pin: int,
        now: datetime,
        except_schedule_id: str | None = None,
    ) -> None:
        schedules = self._schedule_service()
        if schedules is None:
            return
        for schedule in schedules.list_all():
            if (
                schedule.valve_pin == int(pin)
                and schedule.id != str(except_schedule_id or "")
                and schedule.status
                and not schedule.is_running_at(now)
            ):
                schedules.set_status(schedule.id, False)

    def _set_manual_schedule_status(
        self, schedule_id: str | None, status: bool
    ) -> bool:
        if schedule_id in (None, ""):
            return False
        schedules = self._schedule_service()
        if schedules is None:
            return False
        schedule = schedules.get(str(schedule_id))
        if schedule.status == status:
            return False
        schedules.set_status(schedule.id, status)
        return True

    def _has_other_running_schedule_on_valve(
        self, pin: int, schedule_id: str | None
    ) -> bool:
        schedules = self._schedule_service()
        if schedules is None:
            return False
        return any(
            schedule.valve_pin == int(pin)
            and schedule.status
            and schedule.id != str(schedule_id or "")
            for schedule in schedules.list_all()
        )

    def _schedule_service(self) -> ScheduleService | None:
        if self._schedules is None:
            return None
        return self._schedules


class IrrigationController:
    """Runs automatic schedules continuously."""

    def __init__(
        self,
        schedules: ScheduleService,
        valves: ValveService,
        history: HistoryService,
        clock: Clock,
        poll_interval: float = 2.0,
        runtime_health: RuntimeHealthService | None = None,
        notifications: NotificationService | None = None,
    ) -> None:
        self._schedules = schedules
        self._valves = valves
        self._history = history
        self._clock = clock
        self._poll_interval = poll_interval
        self._runtime_health = runtime_health
        self._notifications = notifications
        self._started_in_this_process: set[str] = set()

    def run_once(self) -> None:
        now = self._clock.now()
        schedules = self._schedules.list_all()
        active_ids = self._active_schedule_ids(schedules, now)

        for schedule in schedules:
            self._process_schedule(schedule, schedules, active_ids, now)

    def _active_schedule_ids(
        self, schedules: list[Schedule], now: datetime
    ) -> set[str]:
        return {
            schedule.id
            for schedule in schedules
            if schedule.status and schedule.is_running_at(now)
        }

    def _process_schedule(
        self,
        schedule: Schedule,
        schedules: list[Schedule],
        active_ids: set[str],
        now: datetime,
    ) -> None:
        start, end = schedule.interval_at(now)
        is_running = schedule.is_running_at(now)
        valve = self._valves.get_by_pin(schedule.valve_pin)
        active_manual = self._history.has_active_manual(valve.section, now)
        keep_valve_on = self._should_keep_valve_on(
            schedule, schedules, active_ids, active_manual
        )
        started_key = self._started_key(schedule, start)

        if not schedule.enabled:
            if schedule.status:
                self._stop(schedule, keep_valve_on)
            return

        if is_running and not schedule.status:
            mode = self._automatic_start_mode(schedule, now)
            self._start_automatic(schedule, valve, now, end, mode, restarted=False)
            return
        if (
            is_running
            and schedule.status
            and started_key not in self._started_in_this_process
        ):
            restarted = not self._has_started_schedule(schedule)
            mode = (
                HISTORY_MODE_RESTARTED
                if restarted
                else self._automatic_start_mode(schedule, now)
            )
            self._start_automatic(
                schedule,
                valve,
                now,
                end,
                mode,
                restarted=restarted,
            )
            return
        if not is_running and schedule.status and not active_manual:
            self._stop(schedule, keep_valve_on)

    def _should_keep_valve_on(
        self,
        schedule: Schedule,
        schedules: list[Schedule],
        active_ids: set[str],
        active_manual: bool,
    ) -> bool:
        return (
            any(
                other.id != schedule.id
                and other.id in active_ids
                and other.valve_pin == schedule.valve_pin
                for other in schedules
            )
            or active_manual
        )

    def _automatic_start_mode(self, schedule: Schedule, now: datetime) -> str:
        start, _ = schedule.interval_at(now)
        if now.strftime("%H:%M") == start.strftime("%H:%M"):
            return HISTORY_MODE_AUTOMATIC
        return HISTORY_MODE_AUTOMATIC_LATE_START

    def _start_automatic(
        self,
        schedule: Schedule,
        valve: Valve,
        now: datetime,
        end: datetime,
        mode: str,
        restarted: bool,
    ) -> None:
        if valve.manually_turned_off and self._history.has_active_automatic(
            valve.section, now
        ):
            return
        if valve.manually_turned_off:
            self._valves.clear_manual_stop(schedule.valve_pin)
        self._start(schedule, now, end, mode, restarted)

    def run(self) -> None:
        self._valves.configure()
        try:
            while True:
                self.run_once()
                self._touch_health()
                time.sleep(self._poll_interval)
        finally:
            self._valves.close()

    def _touch_health(self) -> None:
        if self._runtime_health is not None:
            self._runtime_health.touch(self._clock.now())

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
        start, _ = schedule.interval_at(now)
        self._started_in_this_process.add(self._started_key(schedule, start))
        if self._notifications is not None:
            self._notifications.notify(
                (
                    NotificationEvent.SCHEDULE_RESTARTED
                    if restarted
                    else NotificationEvent.SECTION_ON
                ),
                schedule_id=schedule.id,
                times=schedule.times,
                duration_minutes=schedule.duration_minutes,
                valve_pin=schedule.valve_pin,
                section=valve.section,
            )

    def _stop(self, schedule: Schedule, keep_valve_on: bool = False) -> None:
        valve = self._valves.get_by_pin(schedule.valve_pin)
        if not keep_valve_on and not valve.manually_turned_off:
            self._valves.turn_off(schedule.valve_pin)
        self._schedules.set_status(schedule.id, False)
        if self._notifications is not None:
            self._notifications.notify(
                NotificationEvent.SECTION_OFF,
                schedule_id=schedule.id,
                times=schedule.times,
                duration_minutes=schedule.duration_minutes,
                valve_pin=schedule.valve_pin,
                section=valve.section,
            )
        self._started_in_this_process = {
            key
            for key in self._started_in_this_process
            if not key.startswith(f"{schedule.id}:")
        }

    def _has_started_schedule(self, schedule: Schedule) -> bool:
        return any(
            key.startswith(f"{schedule.id}:") for key in self._started_in_this_process
        )

    @staticmethod
    def _started_key(schedule: Schedule, start: datetime) -> str:
        return f"{schedule.id}:{start.isoformat()}"
