"""Domain models independent from files, GPIO, and user interfaces."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from typing import Any

from .exceptions import ValidationError

WEEKDAY_IDS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_WEEKDAY_INDEX = {weekday: index for index, weekday in enumerate(WEEKDAY_IDS)}
_WEEKDAY_ALIASES = {
    "monday": "mon",
    "tuesday": "tue",
    "wednesday": "wed",
    "thursday": "thu",
    "friday": "fri",
    "saturday": "sat",
    "sunday": "sun",
}
_ALL_WEEKDAY_ALIASES = {"all", "everyday", "every-day", "every_day", "daily"}


class SensorKind(str, Enum):
    RESERVOIR_LEVEL = "reservoir_level"
    FLOW = "flow"
    SOIL_MOISTURE = "soil_moisture"
    LINE_PRESSURE = "line_pressure"
    RAIN = "rain"


class SensorHealth(str, Enum):
    UNKNOWN = "unknown"
    OK = "ok"
    WARNING = "warning"
    FAULT = "fault"
    STALE = "stale"


class NotificationEvent(str, Enum):
    SECTION_ON = "section_on"
    SECTION_OFF = "section_off"
    SCHEDULE_RESTARTED = "schedule_restarted"
    SCHEDULE_CREATED = "schedule_created"
    SCHEDULE_UPDATED = "schedule_updated"
    SCHEDULE_DELETED = "schedule_deleted"
    SECTION_CREATED = "section_created"
    SECTION_UPDATED = "section_updated"
    SECTION_DELETED = "section_deleted"
    PASSWORD_CHANGED = "password_changed"


@dataclass(frozen=True, slots=True)
class NotificationConfig:
    webhook_url: str | None
    enabled_events: frozenset[NotificationEvent]

    @classmethod
    def empty(cls) -> NotificationConfig:
        return cls(webhook_url=None, enabled_events=frozenset())

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> NotificationConfig:
        webhook = data.get("webhook_url")
        webhook_url = None if webhook is None else str(webhook).strip() or None
        enabled = data.get("enabled_events", ())
        try:
            enabled_events = frozenset(NotificationEvent(item) for item in enabled)
        except (TypeError, ValueError) as exc:
            supported = ", ".join(item.value for item in NotificationEvent)
            raise ValidationError(
                f"notification event must be one of: {supported}"
            ) from exc
        return cls(webhook_url=webhook_url, enabled_events=enabled_events)

    def to_dict(self) -> dict[str, Any]:
        return {
            "webhook_url": self.webhook_url,
            "events": {
                event.value: event in self.enabled_events for event in NotificationEvent
            },
        }


def _int_value(value: Any, field: str, minimum: int | None = None) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{field} must be an integer") from exc
    if minimum is not None and number < minimum:
        raise ValidationError(f"{field} must be greater than or equal to {minimum}")
    return number


def _boolean_value(value: Any, field: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str) and value.strip() in ("0", "1"):
        return value.strip() == "1"
    raise ValidationError(f"{field} must be 0 or 1")


def _datetime_value(value: Any, field: str, optional: bool = False) -> datetime | None:
    if value is None or str(value).strip() == "":
        if optional:
            return None
        raise ValidationError(f"{field} is required")
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValidationError(f"{field} must be an ISO 8601 timestamp") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _sensor_scalar(value: Any, field: str) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise ValidationError(f"{field} must be a finite JSON scalar")


def _schedule_time(value: Any) -> str:
    try:
        return datetime.strptime(str(value), "%H:%M").strftime("%H:%M")
    except ValueError as exc:
        raise ValidationError("schedule time must use HH:MM format") from exc


def _normalize_schedule_times(value: Any) -> tuple[str, ...]:
    if value is None:
        raise ValidationError("schedule times must contain at least one time")

    if isinstance(value, str):
        raw_values = [
            item.strip()
            for item in value.replace("|", ",")
            .replace(";", ",")
            .replace("+", ",")
            .split(",")
        ]
    else:
        try:
            raw_values = list(value)
        except TypeError as exc:
            raise ValidationError("schedule times must be a list or string") from exc

    times = tuple(_schedule_time(raw) for raw in raw_values if str(raw).strip())
    if not times:
        raise ValidationError("schedule times must contain at least one time")
    if len(times) > 3:
        raise ValidationError("schedule cannot contain more than three times")
    if len(set(times)) != len(times):
        raise ValidationError("schedule times must be distinct")
    return tuple(sorted(times))


def _normalize_weekdays(value: Any = None) -> tuple[str, ...]:
    if value is None:
        return WEEKDAY_IDS

    if isinstance(value, str):
        text = value.strip().lower()
        if not text:
            raise ValidationError("weekdays must contain at least one weekday")
        if text in _ALL_WEEKDAY_ALIASES:
            return WEEKDAY_IDS
        raw_values = [
            item.strip()
            for item in text.replace("|", ",")
            .replace(";", ",")
            .replace("+", ",")
            .split(",")
        ]
    else:
        try:
            raw_values = list(value)
        except TypeError as exc:
            raise ValidationError("weekdays must be a list or string") from exc

    normalized: set[str] = set()
    for raw in raw_values:
        weekday = str(raw).strip().lower()
        if not weekday:
            continue
        if weekday.isdigit():
            index = int(weekday)
            if 0 <= index <= 6:
                weekday = WEEKDAY_IDS[index]
        weekday = _WEEKDAY_ALIASES.get(weekday, weekday)
        if weekday not in _WEEKDAY_INDEX:
            raise ValidationError(f"unknown weekday: {raw}")
        normalized.add(weekday)

    if not normalized:
        raise ValidationError("weekdays must contain at least one weekday")
    return tuple(weekday for weekday in WEEKDAY_IDS if weekday in normalized)


@dataclass(frozen=True, slots=True)
class Schedule:
    id: str
    times: tuple[str, ...] | str
    duration_minutes: int
    valve_pin: int
    status: bool = False
    enabled: bool = True
    weekdays: tuple[str, ...] = WEEKDAY_IDS

    def __post_init__(self) -> None:
        times = _normalize_schedule_times(self.times)
        duration = _int_value(self.duration_minutes, "duration_minutes", 1)
        object.__setattr__(self, "times", times)
        object.__setattr__(self, "duration_minutes", duration)
        object.__setattr__(self, "weekdays", _normalize_weekdays(self.weekdays))
        self._reject_overlapping_times()

    @property
    def time(self) -> str:
        return "|".join(self.times)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Schedule:
        pin = data.get("valve_pin")
        if pin is None:
            raise ValidationError("valve pin is required")
        return cls(
            id=str(data.get("id", "")),
            times=_normalize_schedule_times(data.get("times", data.get("time"))),
            duration_minutes=_int_value(
                data.get("duration_minutes"), "duration_minutes", 1
            ),
            valve_pin=_int_value(pin, "valve_pin", 1),
            status=bool(_int_value(data.get("status", 0), "status", 0)),
            enabled=bool(_int_value(data.get("enabled", 1), "enabled", 0)),
            weekdays=_normalize_weekdays(data.get("weekdays")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "time": self.time,
            "times": list(self.times),
            "duration_minutes": str(self.duration_minutes),
            "valve_pin": str(self.valve_pin),
            "status": int(self.status),
            "enabled": int(self.enabled),
            "weekdays": list(self.weekdays),
        }

    def interval_at(self, now: datetime) -> tuple[datetime, datetime]:
        intervals = [
            self._interval_for_time(time_value, now) for time_value in self.times
        ]
        for start, end in intervals:
            if start <= now < end:
                return start, end
        past_intervals = [(start, end) for start, end in intervals if start <= now]
        if past_intervals:
            return max(past_intervals, key=lambda interval: interval[0])
        return intervals[0]

    def _interval_for_time(
        self, time_value: str, now: datetime
    ) -> tuple[datetime, datetime]:
        hour, minute = map(int, time_value.split(":"))
        start = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        end = start + timedelta(minutes=self.duration_minutes)
        if now < start:
            previous_start = start - timedelta(days=1)
            previous_end = previous_start + timedelta(minutes=self.duration_minutes)
            if now < previous_end:
                return previous_start, previous_end
        return start, end

    def is_running_at(self, now: datetime) -> bool:
        return self.enabled and any(
            self.runs_on(start) and start <= now < end
            for start, end in (
                self._interval_for_time(time_value, now) for time_value in self.times
            )
        )

    def runs_on(self, day: datetime | date) -> bool:
        return WEEKDAY_IDS[day.weekday()] in self.weekdays

    def _reject_overlapping_times(self) -> None:
        starts = [
            int(time_value[:2]) * 60 + int(time_value[3:]) for time_value in self.times
        ]
        for current, following in zip(starts, starts[1:], strict=False):
            if following < current + self.duration_minutes:
                raise ValidationError("schedule times must not overlap")
        if len(starts) > 1 and starts[0] + 24 * 60 < starts[-1] + self.duration_minutes:
            raise ValidationError("schedule times must not overlap")


@dataclass(frozen=True, slots=True)
class Valve:
    id: str
    pin: int
    section: str
    status: bool = False
    manually_turned_off: bool = False

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Valve:
        return cls(
            id=str(data.get("id", "")),
            pin=_int_value(data.get("pin"), "pin", 1),
            section=str(data.get("section", "")).strip(),
            status=bool(_int_value(data.get("status", 0), "status", 0)),
            manually_turned_off=bool(
                _int_value(
                    data.get("manually_turned_off", 0),
                    "manually_turned_off",
                    0,
                )
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "pin": str(self.pin),
            "status": int(self.status),
            "section": self.section,
            "manually_turned_off": int(self.manually_turned_off),
        }


@dataclass(frozen=True, slots=True)
class Sensor:
    id: str
    name: str
    kind: SensorKind | str
    enabled: bool
    valve_id: str | None
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        name = str(self.name).strip()
        if not name:
            raise ValidationError("sensor name is required")
        if len(name) > 100:
            raise ValidationError("sensor name must contain at most 100 characters")
        try:
            kind = SensorKind(self.kind)
        except ValueError as exc:
            supported = ", ".join(item.value for item in SensorKind)
            raise ValidationError(f"sensor kind must be one of: {supported}") from exc
        valve_id = None if self.valve_id is None else str(self.valve_id).strip()
        if valve_id == "":
            valve_id = None
        if valve_id is not None and (not valve_id.isdigit() or int(valve_id) < 1):
            raise ValidationError("valve_id must be a positive integer")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "enabled", _boolean_value(self.enabled, "enabled"))
        object.__setattr__(self, "valve_id", valve_id)
        object.__setattr__(
            self, "created_at", _datetime_value(self.created_at, "created_at")
        )
        object.__setattr__(
            self, "updated_at", _datetime_value(self.updated_at, "updated_at")
        )
        if self.updated_at < self.created_at:
            raise ValidationError("updated_at must not be before created_at")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Sensor:
        return cls(
            id=str(data.get("id", "")),
            name=data.get("name", ""),
            kind=data.get("kind", ""),
            enabled=data.get("enabled", 1),
            valve_id=data.get("valve_id"),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind.value,
            "enabled": int(self.enabled),
            "valve_id": self.valve_id,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class SensorState:
    sensor_id: str
    health: SensorHealth | str
    value: Any
    unit: str | None
    raw_value: Any
    latest_read_at: datetime | None
    error_message: str | None
    updated_at: datetime

    def __post_init__(self) -> None:
        sensor_id = str(self.sensor_id).strip()
        if not sensor_id.isdigit() or int(sensor_id) < 1:
            raise ValidationError("sensor_id must be a positive integer")
        try:
            health = SensorHealth(self.health)
        except ValueError as exc:
            supported = ", ".join(item.value for item in SensorHealth)
            raise ValidationError(f"sensor health must be one of: {supported}") from exc
        unit = None if self.unit is None else str(self.unit).strip()
        if unit == "":
            unit = None
        if unit is not None and len(unit) > 32:
            raise ValidationError("sensor unit must contain at most 32 characters")
        error = None if self.error_message is None else str(self.error_message).strip()
        if error == "":
            error = None
        if error is not None and len(error) > 300:
            raise ValidationError(
                "sensor error message must contain at most 300 characters"
            )
        if health is SensorHealth.FAULT and error is None:
            raise ValidationError(
                "fault sensor state requires an actionable error message"
            )
        object.__setattr__(self, "sensor_id", sensor_id)
        object.__setattr__(self, "health", health)
        object.__setattr__(self, "value", _sensor_scalar(self.value, "value"))
        object.__setattr__(
            self, "raw_value", _sensor_scalar(self.raw_value, "raw_value")
        )
        object.__setattr__(self, "unit", unit)
        object.__setattr__(self, "error_message", error)
        object.__setattr__(
            self,
            "latest_read_at",
            _datetime_value(self.latest_read_at, "latest_read_at", optional=True),
        )
        object.__setattr__(
            self, "updated_at", _datetime_value(self.updated_at, "updated_at")
        )

    @classmethod
    def unknown(cls, sensor_id: str, at: datetime) -> SensorState:
        return cls(sensor_id, SensorHealth.UNKNOWN, None, None, None, None, None, at)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> SensorState:
        return cls(
            sensor_id=str(data.get("sensor_id", "")),
            health=data.get("health", SensorHealth.UNKNOWN.value),
            value=data.get("value"),
            unit=data.get("unit"),
            raw_value=data.get("raw_value"),
            latest_read_at=data.get("latest_read_at"),
            error_message=data.get("error_message"),
            updated_at=data.get("updated_at"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "sensor_id": self.sensor_id,
            "health": self.health.value,
            "value": self.value,
            "unit": self.unit,
            "raw_value": self.raw_value,
            "latest_read_at": (
                self.latest_read_at.isoformat()
                if self.latest_read_at is not None
                else None
            ),
            "error_message": self.error_message,
            "updated_at": self.updated_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class HistoryRecord:
    id: str
    valve: str
    date: date
    start: str
    end: str
    weekday: str
    mode: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "valve": self.valve,
            "date": self.date.isoformat(),
            "start": self.start,
            "end": self.end,
            "weekday": self.weekday,
            "mode": self.mode,
        }
