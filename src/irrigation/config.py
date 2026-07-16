"""Centralized settings loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Settings:
    data_dir: Path
    pump_pin: int = 15
    # Schedules have minute granularity; 5s keeps turn-on/off within ±5s
    # while roughly halving the daemon's idle wakeups on the Pi.
    poll_interval: float = 5.0
    gpio_driver: str = "rpi"

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            data_dir=Path(
                os.getenv("IRRIGATION_DATA_DIR", Path.cwd() / "data")
            ).resolve(),
            pump_pin=int(os.getenv("IRRIGATION_PUMP_PIN", "15")),
            poll_interval=float(os.getenv("IRRIGATION_POLL_INTERVAL", "5")),
            gpio_driver=os.getenv("IRRIGATION_GPIO_DRIVER", "rpi").lower(),
        )

    @property
    def database_path(self) -> Path:
        return self.data_dir / "irrigation.db"

    @property
    def history_search_results_path(self) -> Path:
        return self.data_dir / "history_search_results.json"
