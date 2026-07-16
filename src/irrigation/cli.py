"""Command-line interface used by systemd and Node-RED."""

from __future__ import annotations

import argparse
import json
import signal
import sys
from collections.abc import Sequence
from datetime import date, datetime

from irrigation.bootstrap import Application
from irrigation.domain.exceptions import IrrigationError


def _csv(
    value: str,
    expected_fields: int | tuple[int, ...],
    description: str,
) -> list[str]:
    parts = [part.strip() for part in value.split(",")]
    if isinstance(expected_fields, int):
        if len(parts) == expected_fields:
            return parts
        raise ValueError(
            f"{description} must contain {expected_fields} comma-separated fields"
        )
    if len(parts) in expected_fields:
        return parts
    options = " or ".join(str(item) for item in expected_fields)
    raise ValueError(f"{description} must contain {options} comma-separated fields")


def _run_command(app: Application, _args: argparse.Namespace):
    app.automatic_controller().run()
    return None


def _health_command(app: Application, args: argparse.Namespace):
    max_age_seconds = (
        args.max_age_seconds
        if args.max_age_seconds is not None
        else (app.settings.poll_interval * 3) + 5
    )
    return app.runtime_health().status(datetime.now(), max_age_seconds)


def _schedule_command(app: Application, args: argparse.Namespace):
    service = app.schedules()
    if args.action == "list":
        return service.list_with_runtime_status(
            datetime.now(),
            app.valves().list_all(),
            app.history(),
        )
    if args.action == "create":
        parts = _csv(args.data, (3, 4), "schedule")
        schedule_time, minutes, pin = parts[:3]
        weekdays = parts[3] if len(parts) == 4 else None
        return service.create(schedule_time, minutes, pin, weekdays)
    if args.action == "update":
        parts = _csv(args.data, (4, 5), "update")
        record_id, schedule_time, minutes, pin = parts[:4]
        weekdays = parts[4] if len(parts) == 5 else None
        return service.update(record_id, schedule_time, minutes, pin, weekdays)
    if args.action == "delete":
        return {"deleted": service.delete(args.id, app.valves())}
    record_id, enabled = _csv(args.data, 2, "enabled flag")
    return service.set_enabled(record_id, enabled)


def _valve_command(app: Application, args: argparse.Namespace):
    if args.data == "list":
        return [valve.to_dict() for valve in app.valves().list_all()]
    valve_data = [part.strip() for part in args.data.split(",")]
    if len(valve_data) not in (2, 3, 4):
        raise ValueError("valve must contain 2 to 4 comma-separated fields")
    pin, action = valve_data[:2]
    duration_minutes = None
    schedule_id = None
    if action == "on":
        duration_minutes = valve_data[2] if len(valve_data) >= 3 else None
        schedule_id = valve_data[3] if len(valve_data) == 4 else None
    elif action == "off":
        schedule_id = valve_data[2] if len(valve_data) == 3 else None
        if len(valve_data) == 4:
            raise ValueError("off action must not contain duration")
    service = app.manual_control()
    if action == "on":
        changed = service.turn_on(
            int(pin),
            duration_minutes=duration_minutes,
            wait=not args.no_wait,
            schedule_id=schedule_id,
        )
    elif action == "off":
        changed = service.turn_off(int(pin), schedule_id=schedule_id)
    else:
        raise ValueError("valve action must be on/off")
    return {"changed": changed}


def _settings_command(app: Application, args: argparse.Namespace):
    service = app.runtime_settings()
    if args.value == "show":
        return {
            "id": "1",
            "default_duration_minutes": service.default_duration_minutes(),
        }
    return service.update_default_duration(args.value)


def _auth_command(app: Application, args: argparse.Namespace):
    service = app.auth()
    if args.action == "login":
        username, password = _csv(args.data, 2, "credentials")
        return {"authenticated": service.verify(username, password)}

    username, current_password, new_password, *confirmation = _csv(
        args.data,
        (3, 4),
        "password change",
    )
    if confirmation and confirmation[0] != new_password:
        raise ValueError("password confirmation does not match")
    service.change_password(username, current_password, new_password)
    return {"changed": True}


def _history_command(app: Application, args: argparse.Namespace):
    action, start, end = _csv(args.data, 3, "history")
    history_service = app.history()
    if action == "day":
        return history_service.search_day(date.today())
    if action == "range":
        return history_service.search_range(
            date.fromisoformat(start), date.fromisoformat(end)
        )
    raise ValueError("unknown history action")


_COMMAND_HANDLERS = {
    "run": _run_command,
    "health": _health_command,
    "schedule": _schedule_command,
    "valve": _valve_command,
    "settings": _settings_command,
    "auth": _auth_command,
    "history": _history_command,
}


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="irrigation")
    subcommands = parser.add_subparsers(dest="command", required=True)

    subcommands.add_parser("run", help="starts automatic control")

    health = subcommands.add_parser("health", help="checks the controller heartbeat")
    health.add_argument(
        "--max-age-seconds",
        type=float,
        default=None,
        help="maximum heartbeat age accepted as online",
    )

    schedule = subcommands.add_parser("schedule")
    schedule_actions = schedule.add_subparsers(dest="action", required=True)
    schedule_actions.add_parser("list")
    create = schedule_actions.add_parser("create")
    create.add_argument("data", help="HH:MM[+HH:MM...],minutes,pin[,weekdays]")
    update = schedule_actions.add_parser("update")
    update.add_argument("data", help="id,HH:MM[+HH:MM...],minutes,pin[,weekdays]")
    delete = schedule_actions.add_parser("delete")
    delete.add_argument("id")
    enabled = schedule_actions.add_parser("enabled")
    enabled.add_argument("data", help="id,0|1")

    valve = subcommands.add_parser("valve")
    valve.add_argument("data", help="list or pin,on|off[,minutes][,schedule_id]")
    valve.add_argument(
        "--no-wait",
        action="store_true",
        help="does not wait for automatic shutdown; useful in tests",
    )

    settings = subcommands.add_parser("settings")
    settings.add_argument("value", help="show or default duration in minutes")

    auth = subcommands.add_parser("auth")
    auth_actions = auth.add_subparsers(dest="action", required=True)
    auth_login = auth_actions.add_parser("login")
    auth_login.add_argument("data", help="username,password")
    auth_change = auth_actions.add_parser("change-password")
    auth_change.add_argument(
        "data", help="username,current_password,new_password[,confirm_password]"
    )

    history = subcommands.add_parser("history")
    history.add_argument("data", help="day,, or range,YYYY-MM-DD,YYYY-MM-DD")
    return parser


def execute(argv: Sequence[str] | None = None) -> int:
    args = create_parser().parse_args(argv)
    app = Application.create()

    try:
        if args.command == "run":
            signal.signal(signal.SIGTERM, _stop_gracefully)
        result = _dispatch(app, args)
    except (IrrigationError, ValueError, KeyError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    if result is not None:
        print(json.dumps(result, ensure_ascii=False))
    return 0


def _stop_gracefully(_signal, _frame) -> None:
    raise SystemExit(0)


def _dispatch(app: Application, args: argparse.Namespace):
    return _COMMAND_HANDLERS[args.command](app, args)


if __name__ == "__main__":
    raise SystemExit(execute())
