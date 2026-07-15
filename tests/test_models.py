from datetime import datetime

import pytest

from irrigacao.domain.exceptions import ValidationError
from irrigacao.domain.models import Schedule


def test_schedule_accepts_legacy_led_field():
    schedule = Schedule.from_dict(
        {
            "id": "1",
            "horario": "06:30",
            "tempoLigado": "15",
            "led": "13",
            "status": "0",
            "ativado": "1",
        }
    )

    assert schedule.valve_pin == 13
    assert schedule.to_dict()["valvula"] == "13"


def test_schedule_rejects_invalid_time():
    with pytest.raises(ValidationError, match="HH:MM"):
        Schedule.from_dict({"horario": "25:00", "tempoLigado": 5, "valvula": 13})


def test_interval_crosses_midnight():
    schedule = Schedule("1", "23:55", 10, 13)

    start, end = schedule.interval_at(datetime(2026, 7, 15, 0, 2))

    assert start == datetime(2026, 7, 14, 23, 55)
    assert end == datetime(2026, 7, 15, 0, 5)
