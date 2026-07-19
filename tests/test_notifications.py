from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime
from io import StringIO

import pytest

from irrigation.application.services import (
    AuthService,
    HistoryService,
    IrrigationController,
    ManualControlService,
    NotificationService,
    ScheduleService,
    SettingsService,
    ValveService,
)
from irrigation.cli import execute
from irrigation.domain.exceptions import ValidationError
from irrigation.domain.models import NotificationEvent
from irrigation.infrastructure.discord_notifier import DiscordNotifier
from irrigation.infrastructure.gpio import MockGPIO
from irrigation.infrastructure.json_repository import JsonLinesRepository
from irrigation.infrastructure.sqlite_repository import (
    DiscordNotificationSqliteRepository,
    ScheduleSqliteRepository,
    SqliteRepository,
    connect_database,
)

WEBHOOK_URL = "https://discord.com/api/webhooks/123456/test-token"


class RecordingNotifier:
    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[tuple[str, str]] = []
        self.error = error

    def send(self, webhook_url: str, message: str) -> None:
        self.calls.append((webhook_url, message))
        if self.error is not None:
            raise self.error


class RecordingNotificationSink:
    def __init__(self) -> None:
        self.calls = []

    def notify(self, event, **context) -> None:
        self.calls.append((NotificationEvent(event), context))


class FixedClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def now(self) -> datetime:
        return self.value


class FakeHttpResponse:
    def __init__(self, status: int) -> None:
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def getcode(self) -> int:
        return self.status


def service_for(tmp_path, notifier=None):
    repository = DiscordNotificationSqliteRepository(
        connect_database(tmp_path / "irrigation.db")
    )
    return NotificationService(repository, notifier or RecordingNotifier()), repository


def execute_stdin(payload) -> int:
    return execute(["--stdin"], stdin=StringIO(json.dumps(payload)))


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("IRRIGATION_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("IRRIGATION_GPIO_DRIVER", "mock")


def test_config_defaults_to_no_webhook_and_all_events_disabled(tmp_path):
    service, _ = service_for(tmp_path)

    assert service.get_config().to_dict() == {
        "webhook_url": None,
        "events": {event.value: False for event in NotificationEvent},
    }


@pytest.mark.parametrize(
    "webhook_url",
    [
        "",
        "http://discord.com/api/webhooks/123/token",
        "https://example.com/api/webhooks/123/token",
        "https://discord.com/not-webhooks/123/token",
        "https://discord.com/api/webhooks/not-an-id/token",
        "https://[invalid/api/webhooks/123/token",
    ],
)
def test_save_webhook_rejects_invalid_urls(tmp_path, webhook_url):
    service, _ = service_for(tmp_path)

    with pytest.raises(ValidationError, match="webhook URL"):
        service.save_webhook(webhook_url)


def test_event_requires_webhook_and_rejects_unknown_identifier(tmp_path):
    service, _ = service_for(tmp_path)

    with pytest.raises(ValidationError, match="configure a Discord webhook"):
        service.set_event_enabled(NotificationEvent.SECTION_ON.value, 1)
    with pytest.raises(ValidationError, match="notification event"):
        service.set_event_enabled("unknown", 1)
    with pytest.raises(ValidationError, match="enabled must be 0 or 1"):
        service.set_event_enabled(NotificationEvent.SECTION_ON.value, 2)


def test_toggle_persists_and_webhook_deletion_disables_every_event(tmp_path):
    service, repository = service_for(tmp_path)
    service.save_webhook(WEBHOOK_URL)
    for event in NotificationEvent:
        service.set_event_enabled(event.value, 1)

    configured = service.get_config().to_dict()
    deleted = service.delete_webhook()

    assert configured["webhook_url"] == WEBHOOK_URL
    assert all(configured["events"].values())
    assert deleted["webhook_url"] is None
    assert not any(deleted["events"].values())
    assert repository.get()["enabled_events"] == []


def test_notify_only_sends_enabled_events_with_portuguese_context(tmp_path):
    notifier = RecordingNotifier()
    service, _ = service_for(tmp_path, notifier)

    service.notify(NotificationEvent.SECTION_CREATED, section="Horta", pin=13)
    service.save_webhook(WEBHOOK_URL)
    service.notify(NotificationEvent.SECTION_CREATED, section="Horta", pin=13)
    service.set_event_enabled(NotificationEvent.SECTION_CREATED.value, 1)
    service.notify(
        NotificationEvent.SECTION_CREATED,
        section_id="7",
        section="Horta",
        pin=13,
    )

    assert notifier.calls == [
        (
            WEBHOOK_URL,
            "Seção Horta cadastrada: ID 7, pino 13.",
        )
    ]
    assert WEBHOOK_URL not in notifier.calls[0][1]


def test_notify_swallows_notifier_failures(tmp_path):
    notifier = RecordingNotifier(TimeoutError("slow endpoint"))
    service, _ = service_for(tmp_path, notifier)
    service.save_webhook(WEBHOOK_URL)
    service.set_event_enabled(NotificationEvent.PASSWORD_CHANGED.value, 1)

    service.notify(NotificationEvent.PASSWORD_CHANGED, username="admin")

    assert notifier.calls[0][1] == "Senha da conta admin alterada."


def test_notify_formats_section_activation_message(tmp_path):
    notifier = RecordingNotifier()
    service, _ = service_for(tmp_path, notifier)
    service.save_webhook(WEBHOOK_URL)
    service.set_event_enabled(NotificationEvent.SECTION_ON.value, 1)

    service.notify(
        NotificationEvent.SECTION_ON,
        section="Horta",
        pin=13,
        duration_minutes=12,
    )

    assert notifier.calls == [
        (
            WEBHOOK_URL,
            "Seção Horta ligada: pino 13.",
        )
    ]


def test_schedule_crud_notification_uses_section_name_instead_of_id(tmp_path):
    notifier = RecordingNotifier()
    notification_service, _ = service_for(tmp_path, notifier)
    connection = connect_database(tmp_path / "irrigation.db")
    valve_repository = SqliteRepository(connection, "valves")
    valve_repository.add({"pin": 13, "section": "Jardim lateral esquerda", "status": 0})
    schedules = ScheduleService(
        ScheduleSqliteRepository(connection),
        notification_service,
        valve_repository,
    )
    notification_service.save_webhook(WEBHOOK_URL)
    notification_service.set_event_enabled(NotificationEvent.SCHEDULE_UPDATED.value, 1)
    schedule = schedules.create("14:00", 20, 13)

    schedules.update(schedule["id"], "15:00", 25, 13)

    assert notifier.calls == [
        (
            WEBHOOK_URL,
            "Agendamento Jardim lateral esquerda editado: 15:00, "
            "duração de 25 min, pino 13.",
        )
    ]
    assert f"Agendamento {schedule['id']}" not in notifier.calls[0][1]


def test_crud_and_password_services_emit_their_events_after_success(tmp_path):
    connection = connect_database(tmp_path / "events.db")
    notifications = RecordingNotificationSink()
    schedules = ScheduleService(ScheduleSqliteRepository(connection), notifications)
    valves = ValveService(
        SqliteRepository(connection, "valves"), MockGPIO(15), notifications
    )
    auth = AuthService(SqliteRepository(connection, "credentials"), notifications)

    valve = valves.add(13, "Horta")
    valves.update(valve.id, 13, "Horta principal")
    valves.remove(valve.id, schedules)
    schedule = schedules.create("06:30", 10, 13)
    schedules.update(schedule["id"], "07:00", 15, 13)
    schedules.delete(schedule["id"])
    auth.ensure_default_credentials()
    auth.change_password("admin", "10203040", "87654321")

    assert [event for event, _ in notifications.calls] == [
        NotificationEvent.SECTION_CREATED,
        NotificationEvent.SECTION_UPDATED,
        NotificationEvent.SECTION_DELETED,
        NotificationEvent.SCHEDULE_CREATED,
        NotificationEvent.SCHEDULE_UPDATED,
        NotificationEvent.SCHEDULE_DELETED,
        NotificationEvent.PASSWORD_CHANGED,
    ]


def test_controller_emits_on_off_and_restart_events(tmp_path):
    connection = connect_database(tmp_path / "controller.db")
    schedule_repository = ScheduleSqliteRepository(connection)
    valve_repository = SqliteRepository(connection, "valves")
    history_repository = SqliteRepository(connection, "history")
    valve_repository.add({"pin": 13, "section": "Horta", "status": 0})
    schedule_repository.add(
        {
            "time": "10:00",
            "duration_minutes": 10,
            "valve_pin": 13,
            "status": 0,
            "enabled": 1,
        }
    )
    notifications = RecordingNotificationSink()
    clock = FixedClock(datetime(2026, 7, 19, 10, 0))
    controller = IrrigationController(
        ScheduleService(schedule_repository),
        ValveService(valve_repository, MockGPIO(15)),
        HistoryService(
            history_repository,
            JsonLinesRepository(tmp_path / "controller-results.json"),
        ),
        clock,
        poll_interval=0,
        notifications=notifications,
    )

    controller.run_once()
    clock.value = datetime(2026, 7, 19, 10, 11)
    controller.run_once()

    schedule_repository.update({**schedule_repository.find_by_id("1"), "status": 1})
    clock.value = datetime(2026, 7, 20, 10, 5)
    restarted_controller = IrrigationController(
        ScheduleService(schedule_repository),
        ValveService(valve_repository, MockGPIO(15)),
        HistoryService(
            history_repository,
            JsonLinesRepository(tmp_path / "restart-results.json"),
        ),
        clock,
        poll_interval=0,
        notifications=notifications,
    )
    restarted_controller.run_once()

    assert [event for event, _ in notifications.calls] == [
        NotificationEvent.SECTION_ON,
        NotificationEvent.SECTION_OFF,
        NotificationEvent.SCHEDULE_RESTARTED,
    ]
    assert all(context["section"] == "Horta" for _, context in notifications.calls)


def test_manual_control_emits_on_and_off_only_when_state_changes(tmp_path):
    connection = connect_database(tmp_path / "manual.db")
    valve_repository = SqliteRepository(connection, "valves")
    settings_repository = SqliteRepository(connection, "settings")
    history_repository = SqliteRepository(connection, "history")
    valve_repository.add({"pin": 13, "section": "Horta", "status": 0})
    settings_repository.add({"default_duration_minutes": 5})
    notifications = RecordingNotificationSink()
    manual = ManualControlService(
        ValveService(valve_repository, MockGPIO(15)),
        SettingsService(settings_repository),
        HistoryService(
            history_repository,
            JsonLinesRepository(tmp_path / "manual-results.json"),
        ),
        FixedClock(datetime(2026, 7, 19, 12, 0)),
        poll_interval=0,
        notifications=notifications,
    )

    assert manual.turn_on(13, duration_minutes=12, wait=False) is True
    assert manual.turn_on(13, duration_minutes=12, wait=False) is False
    assert manual.turn_off(13) is True
    assert manual.turn_off(13) is False

    assert [event for event, _ in notifications.calls] == [
        NotificationEvent.SECTION_ON,
        NotificationEvent.SECTION_OFF,
    ]
    assert notifications.calls[0][1] == {
        "section": "Horta",
        "pin": 13,
        "duration_minutes": 12,
    }
    assert notifications.calls[1][1] == {"section": "Horta", "pin": 13}


def test_schema_is_additive_for_an_existing_database(tmp_path):
    database_path = tmp_path / "existing.db"
    old_connection = sqlite3.connect(database_path)
    old_connection.execute("CREATE TABLE legacy_data (id INTEGER PRIMARY KEY)")
    old_connection.commit()
    old_connection.close()

    connection = connect_database(database_path)
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }

    assert "legacy_data" in tables
    assert "discord_notifications" in tables


def test_schema_adds_new_event_flags_to_existing_notification_table(tmp_path):
    database_path = tmp_path / "existing-notifications.db"
    old_connection = sqlite3.connect(database_path)
    old_connection.execute(
        "CREATE TABLE discord_notifications ("
        "id INTEGER PRIMARY KEY, webhook_url TEXT, schedule_on INTEGER DEFAULT 0)"
    )
    old_connection.execute(
        "INSERT INTO discord_notifications (id, webhook_url, schedule_on) "
        "VALUES (1, ?, 1)",
        (WEBHOOK_URL,),
    )
    old_connection.commit()
    old_connection.close()

    connection = connect_database(database_path)
    repository = DiscordNotificationSqliteRepository(connection)
    columns = {
        row["name"]
        for row in connection.execute(
            "PRAGMA table_info(discord_notifications)"
        ).fetchall()
    }

    assert {event.value for event in NotificationEvent} <= columns
    assert repository.get()["enabled_events"] == ["section_on"]
    assert (
        connection.execute(
            "SELECT schedule_on FROM discord_notifications WHERE id = 1"
        ).fetchone()[0]
        == 0
    )


def test_notifications_structured_stdin_contract(capsys):
    requests = [
        {"command": "notifications", "action": "get"},
        {
            "command": "notifications",
            "action": "save-webhook",
            "webhook_url": WEBHOOK_URL,
        },
        {
            "command": "notifications",
            "action": "set-event",
            "event": "section_on",
            "enabled": 1,
        },
        {"command": "notifications", "action": "delete-webhook"},
    ]

    outputs = []
    for request in requests:
        assert execute_stdin(request) == 0
        outputs.append(json.loads(capsys.readouterr().out))

    assert outputs[0]["webhook_url"] is None
    assert outputs[1]["webhook_url"] == WEBHOOK_URL
    assert outputs[2]["events"]["section_on"] is True
    assert outputs[3]["webhook_url"] is None
    assert not any(outputs[3]["events"].values())


def test_notifications_cli_reports_actionable_errors(capsys):
    exit_code = execute_stdin(
        {
            "command": "notifications",
            "action": "save-webhook",
            "webhook_url": "https://example.com/hook",
        }
    )

    assert exit_code == 2
    assert "discord.com/api/webhooks" in capsys.readouterr().err


def test_discord_http_client_posts_json_with_fixed_timeout(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return FakeHttpResponse(204)

    monkeypatch.setattr(
        "irrigation.infrastructure.discord_notifier.urlopen", fake_urlopen
    )
    notifier = DiscordNotifier(timeout_seconds=0.25)

    notifier._deliver(WEBHOOK_URL, '{"content":"Irrigação iniciada"}'.encode())

    assert captured["request"].full_url == WEBHOOK_URL
    assert captured["request"].method == "POST"
    assert captured["request"].headers["Content-type"] == "application/json"
    assert captured["timeout"] == 0.25


def test_discord_http_client_rejects_non_success_response(monkeypatch):
    monkeypatch.setattr(
        "irrigation.infrastructure.discord_notifier.urlopen",
        lambda _request, timeout: FakeHttpResponse(500),
    )

    with pytest.raises(OSError, match="HTTP 500"):
        DiscordNotifier()._deliver(WEBHOOK_URL, b"{}")


def test_discord_delivery_worker_does_not_wait_for_a_slow_endpoint(monkeypatch):
    notifier = DiscordNotifier()
    monkeypatch.setattr(
        notifier,
        "_deliver",
        lambda _webhook_url, _payload: time.sleep(0.5),
    )

    started = time.perf_counter()
    notifier.send(WEBHOOK_URL, "Teste")
    elapsed = time.perf_counter() - started

    assert elapsed < 0.2
