"""Command-line interface used by systemd and Node-RED."""

from __future__ import annotations

import argparse
import json
import signal
import sys
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Any, TextIO

from irrigation.bootstrap import Application
from irrigation.domain.exceptions import IrrigationError

_MAX_STDIN_BYTES = 4096


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
    stdin = _stdin_request(args)
    if stdin is not None:
        max_age_seconds = stdin.get("max_age_seconds")
        if max_age_seconds is not None:
            max_age_seconds = float(max_age_seconds)
    else:
        max_age_seconds = args.max_age_seconds
    max_age_seconds = (
        max_age_seconds
        if max_age_seconds is not None
        else (app.settings.poll_interval * 3) + 5
    )
    return app.runtime_health().status(datetime.now(), max_age_seconds)


def _schedule_command(app: Application, args: argparse.Namespace):
    service = app.schedules()
    stdin = _stdin_request(args)
    if stdin is not None:
        action = _required(stdin, "action")
        if action == "list":
            return service.list_with_runtime_status(
                datetime.now(),
                app.valves().list_all(),
                app.history(),
            )
        if action == "create":
            return service.create(
                _schedule_times(stdin),
                _required(stdin, "duration_minutes"),
                _required(stdin, "valve_pin"),
                _weekdays(stdin),
            )
        if action == "update":
            return service.update(
                _required(stdin, "id"),
                _schedule_times(stdin),
                _required(stdin, "duration_minutes"),
                _required(stdin, "valve_pin"),
                _weekdays(stdin),
            )
        if action == "delete":
            return {"deleted": service.delete(_required(stdin, "id"), app.valves())}
        if action == "enabled":
            return service.set_enabled(
                _required(stdin, "id"), _required(stdin, "enabled")
            )
        raise ValueError("unknown schedule action")

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
    stdin = _stdin_request(args)
    if stdin is not None:
        action = _required(stdin, "action")
        valves = app.valves()
        if action == "list":
            return [valve.to_dict() for valve in valves.list_all()]
        if action == "add":
            return valves.add(
                _required(stdin, "pin"), _required(stdin, "section")
            ).to_dict()
        if action == "update":
            return valves.update(
                _required(stdin, "id"),
                _required(stdin, "pin"),
                _required(stdin, "section"),
            ).to_dict()
        if action == "delete":
            return {"deleted": valves.remove(_required(stdin, "id"), app.schedules())}
        if action != "manual":
            raise ValueError("unknown valve action")

        valve_action = _required(stdin, "valve_action")
        service = app.manual_control()
        if valve_action == "on":
            changed = service.turn_on(
                int(_required(stdin, "pin")),
                duration_minutes=stdin.get("duration_minutes"),
                wait=not bool(stdin.get("no_wait", False)),
                schedule_id=stdin.get("schedule_id"),
            )
        elif valve_action == "off":
            changed = service.turn_off(
                int(_required(stdin, "pin")),
                schedule_id=stdin.get("schedule_id"),
            )
        else:
            raise ValueError("valve action must be on/off")
        return {"changed": changed}

    action = args.data
    valves = app.valves()
    action_data = " ".join(args.action_data or [])
    if action == "list":
        return [valve.to_dict() for valve in valves.list_all()]
    if action == "add":
        pin, section = _csv(action_data, 2, "valve")
        return valves.add(pin, section).to_dict()
    if action == "update":
        valve_id, pin, section = _csv(action_data, 3, "valve update")
        return valves.update(valve_id, pin, section).to_dict()
    if action == "delete":
        return {"deleted": valves.remove(action_data, app.schedules())}

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
    stdin = _stdin_request(args)
    value = _required(stdin, "value") if stdin is not None else args.value
    if value == "show":
        return {
            "id": "1",
            "default_duration_minutes": service.default_duration_minutes(),
        }
    return service.update_default_duration(value)


def _auth_command(app: Application, args: argparse.Namespace):
    service = app.auth()
    stdin = _stdin_request(args)
    if stdin is not None:
        action = _required(stdin, "action")
        if action == "login":
            return {
                "authenticated": service.verify(
                    _required(stdin, "username"), _required(stdin, "password")
                )
            }
        if action == "change-password":
            new_password = _required(stdin, "new_password")
            confirmation = stdin.get("confirm_password")
            if confirmation is not None and confirmation != new_password:
                raise ValueError("password confirmation does not match")
            service.change_password(
                _required(stdin, "username"),
                _required(stdin, "current_password"),
                new_password,
            )
            return {"changed": True}
        raise ValueError("auth action is not available through stdin")

    if args.action == "reset-to-default":
        service.reset_to_default()
        return {"reset": True}
    raise ValueError("credentials must be provided through --stdin")


def _history_command(app: Application, args: argparse.Namespace):
    stdin = _stdin_request(args)
    if stdin is not None:
        action = _required(stdin, "action")
        start = stdin.get("start_date", "")
        end = stdin.get("end_date", "")
    else:
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
    parser = argparse.ArgumentParser(
        prog="irrigation",
        epilog="Use --stdin by itself to read one structured JSON command from stdin.",
    )
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
    valve.add_argument(
        "data",
        help=("list, add, update, delete, or pin,on|off[,minutes][,schedule_id]"),
    )
    valve.add_argument(
        "action_data",
        nargs="*",
        help="add: pin,section; update: id,pin,section; delete: id",
    )
    valve.add_argument(
        "--no-wait",
        action="store_true",
        help="does not wait for automatic shutdown; useful in tests",
    )

    settings = subcommands.add_parser("settings")
    settings.add_argument("value", help="show or default duration in minutes")

    auth = subcommands.add_parser("auth")
    auth_actions = auth.add_subparsers(dest="action", required=True)
    auth_actions.add_parser(
        "login", help="reads credentials from the --stdin JSON request"
    )
    auth_actions.add_parser(
        "change-password", help="reads credentials from the --stdin JSON request"
    )
    auth_actions.add_parser("reset-to-default")

    history = subcommands.add_parser("history")
    history.add_argument("data", help="day,, or range,YYYY-MM-DD,YYYY-MM-DD")
    return parser


def execute(
    argv: Sequence[str] | None = None,
    stdin: TextIO | None = None,
) -> int:
    try:
        arguments = list(argv) if argv is not None else sys.argv[1:]
        if arguments == ["--stdin"]:
            args = _read_stdin_request(stdin or sys.stdin)
        else:
            args = create_parser().parse_args(arguments)
        app = Application.create()
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


def _read_stdin_request(stream: TextIO) -> argparse.Namespace:
    raw = stream.read(_MAX_STDIN_BYTES + 1)
    if len(raw.encode("utf-8")) > _MAX_STDIN_BYTES:
        raise ValueError(f"stdin payload exceeds {_MAX_STDIN_BYTES} bytes")
    if not raw.strip():
        raise ValueError("stdin payload is empty")
    try:
        request = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("stdin payload must be valid JSON") from exc
    if not isinstance(request, dict):
        raise ValueError("stdin payload must be a JSON object")
    command = _required(request, "command")
    if not isinstance(command, str):
        raise ValueError("stdin payload field 'command' must be a string")
    if command not in _COMMAND_HANDLERS or command == "run":
        raise ValueError("command is not available through stdin")
    return argparse.Namespace(command=command, stdin=request)


def _stdin_request(args: argparse.Namespace) -> Mapping[str, Any] | None:
    return getattr(args, "stdin", None)


def _required(request: Mapping[str, Any], field: str) -> Any:
    if field not in request or request[field] is None:
        raise ValueError(f"stdin payload is missing '{field}'")
    return request[field]


def _schedule_times(request: Mapping[str, Any]) -> Any:
    value = request.get("times", request.get("time"))
    if value is None:
        raise ValueError("stdin payload is missing 'times'")
    if isinstance(value, list):
        return "+".join(str(item) for item in value)
    return value


def _weekdays(request: Mapping[str, Any]) -> Any:
    value = request.get("weekdays")
    if isinstance(value, list):
        return "+".join(str(item) for item in value)
    return value


if __name__ == "__main__":
    raise SystemExit(execute())
