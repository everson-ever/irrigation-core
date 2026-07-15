"""Application dependency composition."""

from __future__ import annotations

from dataclasses import dataclass

from irrigation.application.services import (
    HistoryService,
    IrrigationController,
    ManualControlService,
    ScheduleService,
    SettingsService,
    ValveService,
)
from irrigation.config import Settings
from irrigation.infrastructure.clock import SystemClock
from irrigation.infrastructure.gpio import create_gpio
from irrigation.infrastructure.json_repository import JsonLinesRepository


@dataclass(slots=True)
class Application:
    settings: Settings

    @classmethod
    def create(cls) -> Application:
        return cls(Settings.from_env())

    def repository(self, name: str) -> JsonLinesRepository:
        return JsonLinesRepository(self.settings.file_path(name))

    def schedules(self) -> ScheduleService:
        return ScheduleService(self.repository("schedules.json"))

    def runtime_settings(self) -> SettingsService:
        return SettingsService(self.repository("settings.json"))

    def history(self) -> HistoryService:
        return HistoryService(
            self.repository("history.json"),
            self.repository("history_search_results.json"),
        )

    def valves(self) -> ValveService:
        gpio = create_gpio(self.settings.gpio_driver, self.settings.pump_pin)
        return ValveService(self.repository("valves.json"), gpio)

    def manual_control(self) -> ManualControlService:
        return ManualControlService(
            self.valves(),
            self.runtime_settings(),
            self.history(),
            SystemClock(),
            self.settings.poll_interval,
            self.schedules(),
        )

    def automatic_controller(self) -> IrrigationController:
        return IrrigationController(
            self.schedules(),
            self.valves(),
            self.history(),
            SystemClock(),
            self.settings.poll_interval,
        )
