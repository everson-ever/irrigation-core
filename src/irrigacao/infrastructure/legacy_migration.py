"""Explicit migration from the data layout used by Part 7."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from irrigacao.domain.exceptions import ValidationError
from irrigacao.domain.models import Schedule, Valve
from irrigacao.infrastructure.json_repository import JsonLinesRepository


def migrate_part_7(source: Path, target: Path) -> dict[str, int]:
    if not source.is_dir():
        raise ValidationError(f"Part 7 directory not found: {source}")
    target.mkdir(parents=True, exist_ok=True)
    totals: dict[str, int] = {}

    schedules = [
        replace(Schedule.from_dict(item), status=False).to_dict()
        for item in _read(source / "agendamentos.json")
    ]
    _save(target, "agendamentos.json", schedules)
    totals["agendamentos"] = len(schedules)

    valves = [
        replace(
            Valve.from_dict(item),
            status=False,
            manually_turned_off=False,
        ).to_dict()
        for item in _read(source / "valvulas.json")
    ]
    _save(target, "valvulas.json", valves)
    totals["valvulas"] = len(valves)

    for file_name, key in (
        ("configuracoes.json", "configuracoes"),
        ("historico.json", "historico"),
    ):
        records = _read(source / file_name) if (source / file_name).exists() else []
        _save(target, file_name, records)
        totals[key] = len(records)

    _save(target, "pesquisaHistoricoResultado.json", [])
    return totals


def _read(file_path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with file_path.open(encoding="utf-8") as content:
        for line_number, line in enumerate(content, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValidationError(
                    f"invalid JSON in {file_path}, line {line_number}"
                ) from exc
            if not isinstance(record, dict):
                raise ValidationError(
                    f"invalid record in {file_path}, line {line_number}"
                )
            records.append(record)
    return records


def _save(target: Path, file_name: str, records: list[dict[str, Any]]) -> None:
    JsonLinesRepository(target / file_name).replace_all(records)
