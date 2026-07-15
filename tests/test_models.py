from datetime import datetime

import pytest

from irrigation.domain.exceptions import ValidationError
from irrigation.domain.models import Schedule


def test_schedule_requires_valve_field():
    with pytest.raises(ValidationError, match="valve pin is required"):
        Schedule.from_dict(
            {
                "id": "1",
                "time": "06:30",
                "duration_minutes": "15",
                "status": "0",
                "enabled": "1",
            }
        )


def test_schedule_rejects_invalid_time():
    with pytest.raises(ValidationError, match="HH:MM"):
        Schedule.from_dict({"time": "25:00", "duration_minutes": 5, "valve_pin": 13})


def test_interval_crosses_midnight():
    schedule = Schedule("1", "23:55", 10, 13)

    start, end = schedule.interval_at(datetime(2026, 7, 15, 0, 2))

    assert start == datetime(2026, 7, 14, 23, 55)
    assert end == datetime(2026, 7, 15, 0, 5)


def test_interval_boundaries_are_inclusive_at_start_and_exclusive_at_end():
    schedule = Schedule("1", "10:00", 10, 13)

    assert schedule.interval_at(datetime(2026, 7, 14, 10, 0)) == (
        datetime(2026, 7, 14, 10, 0),
        datetime(2026, 7, 14, 10, 10),
    )
    assert schedule.interval_at(datetime(2026, 7, 14, 10, 10)) == (
        datetime(2026, 7, 14, 10, 0),
        datetime(2026, 7, 14, 10, 10),
    )
