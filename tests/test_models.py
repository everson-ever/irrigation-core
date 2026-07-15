from datetime import datetime

import pytest

from irrigation.domain.exceptions import ValidationError
from irrigation.domain.models import WEEKDAY_IDS, Schedule


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


def test_schedule_running_state_uses_own_interval():
    schedule = Schedule("1", "10:00", 10, 13)

    assert schedule.is_running_at(datetime(2026, 7, 14, 10, 0)) is True
    assert schedule.is_running_at(datetime(2026, 7, 14, 10, 9)) is True
    assert schedule.is_running_at(datetime(2026, 7, 14, 10, 10)) is False
    assert schedule.is_running_at(datetime(2026, 7, 14, 9, 59)) is False


def test_shared_valve_schedules_can_have_different_running_states():
    earlier = Schedule("1", "10:46", 2, 13)
    current = Schedule("2", "11:06", 4, 13)
    now = datetime(2026, 7, 14, 11, 7)

    assert earlier.is_running_at(now) is False
    assert current.is_running_at(now) is True


def test_disabled_schedule_is_not_running_inside_interval():
    schedule = Schedule("1", "10:00", 10, 13, enabled=False)

    assert schedule.is_running_at(datetime(2026, 7, 14, 10, 5)) is False


def test_midnight_crossing_schedule_reports_running_after_midnight():
    schedule = Schedule("1", "23:55", 10, 13)

    assert schedule.is_running_at(datetime(2026, 7, 15, 0, 2)) is True
    assert schedule.is_running_at(datetime(2026, 7, 15, 0, 5)) is False


def test_schedule_accepts_weekday_subset_and_preserves_canonical_order():
    schedule = Schedule.from_dict(
        {
            "time": "06:30",
            "duration_minutes": 15,
            "valve_pin": 13,
            "weekdays": ["fri", "mon", "mon", "wed"],
        }
    )

    assert schedule.weekdays == ("mon", "wed", "fri")
    assert schedule.to_dict()["weekdays"] == ["mon", "wed", "fri"]


def test_schedule_accepts_all_weekdays_alias():
    schedule = Schedule.from_dict(
        {
            "time": "06:30",
            "duration_minutes": 15,
            "valve_pin": 13,
            "weekdays": "everyday",
        }
    )

    assert schedule.weekdays == WEEKDAY_IDS


def test_legacy_schedule_without_weekdays_defaults_to_every_day():
    schedule = Schedule.from_dict(
        {"time": "06:30", "duration_minutes": 15, "valve_pin": 13}
    )

    assert schedule.weekdays == WEEKDAY_IDS
    assert schedule.is_running_at(datetime(2026, 7, 19, 6, 30)) is True


def test_schedule_rejects_invalid_weekdays():
    with pytest.raises(ValidationError, match="unknown weekday"):
        Schedule.from_dict(
            {
                "time": "06:30",
                "duration_minutes": 15,
                "valve_pin": 13,
                "weekdays": ["monday", "funday"],
            }
        )


def test_schedule_rejects_empty_weekdays():
    with pytest.raises(ValidationError, match="at least one weekday"):
        Schedule.from_dict(
            {
                "time": "06:30",
                "duration_minutes": 15,
                "valve_pin": 13,
                "weekdays": [],
            }
        )


def test_weekday_data_survives_from_dict_and_to_dict_conversion():
    schedule = Schedule.from_dict(
        {
            "id": "1",
            "time": "06:30",
            "duration_minutes": "15",
            "valve_pin": "13",
            "weekdays": "sun+mon",
        }
    )

    assert schedule.to_dict() == {
        "id": "1",
        "time": "06:30",
        "duration_minutes": "15",
        "valve_pin": "13",
        "status": 0,
        "enabled": 1,
        "weekdays": ["mon", "sun"],
    }


def test_midnight_crossing_schedule_uses_start_day_for_weekday_rule():
    schedule = Schedule("1", "23:55", 10, 13, weekdays=("tue",))

    assert schedule.is_running_at(datetime(2026, 7, 15, 0, 2)) is True
    assert schedule.is_running_at(datetime(2026, 7, 16, 0, 2)) is False
