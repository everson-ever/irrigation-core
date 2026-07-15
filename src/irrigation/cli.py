"""Command-line interface used by systemd and Node-RED."""

from __future__ import annotations

import argparse
import json
import signal
import sys
from collections.abc import Sequence
from datetime import date

from irrigation.bootstrap import Application
from irrigation.domain.exceptions import IrrigationError


def _csv(value: str, expected_fields: int, description: str) -> list[str]:
    parts = [part.strip() for part in value.split(",")]
    if len(parts) != expected_fields:
        raise ValueError(
            f"{description} must contain {expected_fields} comma-separated fields"
        )
    return parts


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="irrigation")
    subcommands = parser.add_subparsers(dest="command", required=True)

    subcommands.add_parser("run", help="starts automatic control")

    schedule = subcommands.add_parser("schedule")
    schedule_actions = schedule.add_subparsers(dest="action", required=True)
    create = schedule_actions.add_parser("create")
    create.add_argument("data", help="HH:MM,minutes,pin")
    update = schedule_actions.add_parser("update")
    update.add_argument("data", help="id,HH:MM,minutes,pin")
    delete = schedule_actions.add_parser("delete")
    delete.add_argument("id")
    enabled = schedule_actions.add_parser("enabled")
    enabled.add_argument("data", help="id,0|1")

    valve = subcommands.add_parser("valve")
    valve.add_argument("data", help="pin,on|off[,minutes]")
    valve.add_argument(
        "--no-wait",
        action="store_true",
        help="does not wait for automatic shutdown; useful in tests",
    )

    settings = subcommands.add_parser("settings")
    settings.add_argument("minutes")

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
    if args.command == "run":
        app.automatic_controller().run()
        return None

    if args.command == "schedule":
        service = app.schedules()
        if args.action == "create":
            schedule_time, minutes, pin = _csv(args.data, 3, "schedule")
            return service.create(schedule_time, minutes, pin)
        if args.action == "update":
            record_id, schedule_time, minutes, pin = _csv(args.data, 4, "update")
            return service.update(record_id, schedule_time, minutes, pin)
        if args.action == "delete":
            return {"deleted": service.delete(args.id)}
        record_id, enabled = _csv(args.data, 2, "enabled flag")
        return service.set_enabled(record_id, enabled)

    if args.command == "valve":
        valve_data = [part.strip() for part in args.data.split(",")]
        if len(valve_data) not in (2, 3):
            raise ValueError("valve must contain 2 or 3 comma-separated fields")
        pin, action = valve_data[:2]
        duration_minutes = valve_data[2] if len(valve_data) == 3 else None
        service = app.manual_control()
        if action == "on":
            changed = service.turn_on(
                int(pin), duration_minutes=duration_minutes, wait=not args.no_wait
            )
        elif action == "off":
            changed = service.turn_off(int(pin))
        else:
            raise ValueError("valve action must be on/off")
        return {"changed": changed}

    if args.command == "settings":
        return app.runtime_settings().update_default_duration(args.minutes)

    action, start, end = _csv(args.data, 3, "history")
    history_service = app.history()
    if action == "day":
        return history_service.search_day(date.today())
    if action == "range":
        return history_service.search_range(
            date.fromisoformat(start), date.fromisoformat(end)
        )
    raise ValueError("unknown history action")


if __name__ == "__main__":
    raise SystemExit(execute())
