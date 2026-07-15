"""Domain models independent from files, GPIO, and user interfaces."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from .exceptions import ValidationError


def _int_value(value: Any, field: str, minimum: int | None = None) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{field} must be an integer") from exc
    if minimum is not None and number < minimum:
        raise ValidationError(f"{field} must be greater than or equal to {minimum}")
    return number


def _schedule_time(value: Any) -> str:
    try:
        return datetime.strptime(str(value), "%H:%M").strftime("%H:%M")
    except ValueError as exc:
        raise ValidationError("schedule time must use HH:MM format") from exc


@dataclass(frozen=True, slots=True)
class Schedule:
    id: str
    time: str
    duration_minutes: int
    valve_pin: int
    status: bool = False
    enabled: bool = True

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Schedule:
        pin = data.get("valve_pin")
        if pin is None:
            raise ValidationError("valve pin is required")
        return cls(
            id=str(data.get("id", "")),
            time=_schedule_time(data.get("time")),
            duration_minutes=_int_value(
                data.get("duration_minutes"), "duration_minutes", 1
            ),
            valve_pin=_int_value(pin, "valve_pin", 1),
            status=bool(_int_value(data.get("status", 0), "status", 0)),
            enabled=bool(_int_value(data.get("enabled", 1), "enabled", 0)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "time": self.time,
            "duration_minutes": str(self.duration_minutes),
            "valve_pin": str(self.valve_pin),
            "status": int(self.status),
            "enabled": int(self.enabled),
        }

    def interval_at(self, now: datetime) -> tuple[datetime, datetime]:
        hour, minute = map(int, self.time.split(":"))
        start = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        end = start + timedelta(minutes=self.duration_minutes)
        if now < start:
            previous_start = start - timedelta(days=1)
            previous_end = previous_start + timedelta(minutes=self.duration_minutes)
            if now < previous_end:
                return previous_start, previous_end
        return start, end


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
