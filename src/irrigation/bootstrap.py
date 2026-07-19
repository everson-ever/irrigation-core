"""Application dependency composition."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from irrigation.application.services import (
    AuthService,
    HistoryService,
    HistorySettingsService,
    IrrigationController,
    ManualControlService,
    RuntimeHealthService,
    ScheduleService,
    SettingsService,
    ValveService,
)
from irrigation.config import Settings
from irrigation.infrastructure.clock import SystemClock
from irrigation.infrastructure.gpio import create_gpio
from irrigation.infrastructure.json_migration import migrate_legacy_json
from irrigation.infrastructure.json_repository import JsonLinesRepository
from irrigation.infrastructure.sqlite_repository import (
    RuntimeHealthSqliteRepository,
    ScheduleSqliteRepository,
    SqliteRepository,
    connect_database,
)


@dataclass(slots=True)
class Application:
    settings: Settings
    _connection: sqlite3.Connection = field(init=False, repr=False)

    def __post_init__(self) -> None:
        migrate_legacy_json(self.settings.data_dir, self.settings.database_path)
        self._connection = connect_database(self.settings.database_path)
        self.auth().ensure_default_credentials()

    @classmethod
    def create(cls) -> Application:
        return cls(Settings.from_env())

    def schedules(self) -> ScheduleService:
        return ScheduleService(ScheduleSqliteRepository(self._connection))

    def runtime_settings(self) -> SettingsService:
        return SettingsService(SqliteRepository(self._connection, "settings"))

    def history_settings(self) -> HistorySettingsService:
        return HistorySettingsService(
            SqliteRepository(self._connection, "history_settings")
        )

    def auth(self) -> AuthService:
        return AuthService(SqliteRepository(self._connection, "credentials"))

    def history(self) -> HistoryService:
        return HistoryService(
            SqliteRepository(self._connection, "history"),
            JsonLinesRepository(self.settings.history_search_results_path),
            self.history_settings(),
        )

    def runtime_health(self) -> RuntimeHealthService:
        return RuntimeHealthService(RuntimeHealthSqliteRepository(self._connection))

    def valves(self) -> ValveService:
        gpio = create_gpio(self.settings.gpio_driver, self.settings.pump_pin)
        return ValveService(SqliteRepository(self._connection, "valves"), gpio)

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
            self.runtime_health(),
        )
