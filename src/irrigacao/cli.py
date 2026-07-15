"""Command-line interface used by systemd and Node-RED."""

from __future__ import annotations

import argparse
import json
import signal
import sys
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from irrigacao.bootstrap import Application
from irrigacao.domain.exceptions import IrrigationError
from irrigacao.infrastructure.legacy_migration import migrate_part_7


def _csv(value: str, expected_fields: int, description: str) -> list[str]:
    parts = [part.strip() for part in value.split(",")]
    if len(parts) != expected_fields:
        raise ValueError(
            f"{description} must contain {expected_fields} comma-separated fields"
        )
    return parts


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="irrigacao")
    subcommands = parser.add_subparsers(dest="command", required=True)

    subcommands.add_parser("run", aliases=["executar"], help="starts automatic control")

    schedule = subcommands.add_parser("schedule", aliases=["agendamento"])
    schedule_actions = schedule.add_subparsers(dest="action", required=True)
    create = schedule_actions.add_parser("create", aliases=["cadastrar"])
    create.add_argument("data", help="HH:MM,minutes,pin")
    update = schedule_actions.add_parser("update", aliases=["editar"])
    update.add_argument("data", help="id,HH:MM,minutes,pin")
    delete = schedule_actions.add_parser("delete", aliases=["remover"])
    delete.add_argument("id")
    enabled = schedule_actions.add_parser("enabled", aliases=["situacao"])
    enabled.add_argument("data", help="id,0|1")

    compatibility = subcommands.add_parser(
        "schedule-action",
        aliases=["acao-agendamento"],
        help="adapter for the legacy Node-RED schedule payload",
    )
    compatibility.add_argument("data")

    valve = subcommands.add_parser("valve", aliases=["valvula"])
    valve.add_argument("data", help="pin,on|off")
    valve.add_argument(
        "--no-wait",
        "--nao-aguardar",
        action="store_true",
        help="does not wait for automatic shutdown; useful in tests",
    )

    settings = subcommands.add_parser("settings", aliases=["configuracao"])
    settings.add_argument("minutes")

    history = subcommands.add_parser("history", aliases=["historico"])
    history.add_argument("data", help="day,, or range,YYYY-MM-DD,YYYY-MM-DD")

    migrate = subcommands.add_parser("migrate-part-7", aliases=["migrar-parte-7"])
    migrate.add_argument(
        "--source",
        "--origem",
        required=True,
        help="legacy Part 7 directory to import",
    )
    return parser


def execute(argv: Sequence[str] | None = None) -> int:
    args = create_parser().parse_args(argv)
    app = Application.create()

    try:
        if args.command in ("run", "executar"):
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
    if args.command in ("run", "executar"):
        app.automatic_controller().run()
        return None

    if args.command in ("schedule", "agendamento"):
        service = app.schedules()
        if args.action in ("create", "cadastrar"):
            schedule_time, minutes, pin = _csv(args.data, 3, "schedule")
            return service.create(schedule_time, minutes, pin)
        if args.action in ("update", "editar"):
            record_id, schedule_time, minutes, pin = _csv(args.data, 4, "update")
            return service.update(record_id, schedule_time, minutes, pin)
        if args.action in ("delete", "remover"):
            return {"deleted": service.delete(args.id)}
        record_id, enabled = _csv(args.data, 2, "enabled flag")
        return service.set_enabled(record_id, enabled)

    if args.command in ("schedule-action", "acao-agendamento"):
        parts = [part.strip() for part in args.data.split(",")]
        action = parts.pop()
        service = app.schedules()
        if action in ("delete", "deletar") and len(parts) == 1:
            return {"deleted": service.delete(parts[0])}
        if action in ("update", "editar") and len(parts) >= 4:
            return service.update(parts[0], parts[1], parts[2], parts[3])
        if action in ("enabled", "situacao") and len(parts) == 2:
            return service.set_enabled(parts[0], parts[1])
        raise ValueError("invalid schedule action or fields")

    if args.command in ("valve", "valvula"):
        pin, action = _csv(args.data, 2, "valve")
        service = app.manual_control()
        if action in ("on", "ligar"):
            changed = service.turn_on(int(pin), wait=not args.no_wait)
        elif action in ("off", "desligar"):
            changed = service.turn_off(int(pin))
        else:
            raise ValueError("valve action must be on/off or ligar/desligar")
        return {"changed": changed}

    if args.command in ("settings", "configuracao"):
        return app.runtime_settings().update_default_duration(args.minutes)

    if args.command in ("migrate-part-7", "migrar-parte-7"):
        return migrate_part_7(Path(args.source).resolve(), app.settings.data_dir)

    action, start, end = _csv(args.data, 3, "history")
    history_service = app.history()
    if action in ("day", "historicoDia"):
        return history_service.search_day(date.today())
    if action in ("range", "historicoIntervalo"):
        return history_service.search_range(
            date.fromisoformat(start), date.fromisoformat(end)
        )
    raise ValueError("unknown history action")


if __name__ == "__main__":
    raise SystemExit(execute())
