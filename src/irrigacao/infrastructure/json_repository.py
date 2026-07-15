"""Simple and atomic JSON Lines persistence."""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from irrigacao.domain.exceptions import RecordNotFoundError, ValidationError


class JsonLinesRepository:
    """JSONL repository safe for Python and Node-RED processes.

    Each write uses a file lock and atomic replacement, avoiding partial files
    when the scheduler and UI write at the same time.
    """

    def __init__(self, file_path: str | Path) -> None:
        self.file_path = Path(file_path)
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self.file_path.touch(exist_ok=True)
        self._lock_file = self.file_path.with_suffix(self.file_path.suffix + ".lock")

    @contextmanager
    def _lock(self, exclusive: bool) -> Iterator[None]:
        with self._lock_file.open("a", encoding="utf-8") as lock:
            mode = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
            fcntl.flock(lock.fileno(), mode)
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def _read_without_lock(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        with self.file_path.open(encoding="utf-8") as file:
            for line_number, line in enumerate(file, start=1):
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValidationError(
                        f"invalid JSON in {self.file_path}, line {line_number}"
                    ) from exc
                if not isinstance(data, dict):
                    raise ValidationError(
                        f"invalid record in {self.file_path}, line {line_number}"
                    )
                records.append(data)
        return records

    def _write_without_lock(self, records: Sequence[Mapping[str, Any]]) -> None:
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{self.file_path.name}.", dir=self.file_path.parent, text=True
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as file:
                for record in records:
                    json.dump(dict(record), file, ensure_ascii=False)
                    file.write("\n")
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, self.file_path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def list_all(self) -> list[dict[str, Any]]:
        with self._lock(exclusive=False):
            return self._read_without_lock()

    def find_by_id(self, record_id: str) -> dict[str, Any] | None:
        target = str(record_id)
        return next(
            (item for item in self.list_all() if str(item.get("id")) == target),
            None,
        )

    def add(self, data: Mapping[str, Any]) -> dict[str, Any]:
        with self._lock(exclusive=True):
            records = self._read_without_lock()
            ids = [
                int(item["id"]) for item in records if str(item.get("id", "")).isdigit()
            ]
            new_record = dict(data)
            new_record["id"] = str(max(ids, default=0) + 1)
            records.append(new_record)
            self._write_without_lock(records)
            return new_record

    def update(self, data: Mapping[str, Any]) -> dict[str, Any]:
        record = dict(data)
        record_id = str(record.get("id", ""))
        if not record_id:
            raise ValidationError("id is required for update")
        with self._lock(exclusive=True):
            records = self._read_without_lock()
            for index, current in enumerate(records):
                if str(current.get("id")) == record_id:
                    records[index] = record
                    self._write_without_lock(records)
                    return record
        raise RecordNotFoundError(f"record {record_id} not found")

    def delete(self, ids: Sequence[str]) -> bool:
        targets = {str(item) for item in ids}
        with self._lock(exclusive=True):
            records = self._read_without_lock()
            remaining = [item for item in records if str(item.get("id")) not in targets]
            changed = len(remaining) != len(records)
            if changed:
                self._write_without_lock(remaining)
            return changed

    def replace_all(self, records: Sequence[Mapping[str, Any]]) -> None:
        with self._lock(exclusive=True):
            self._write_without_lock(records)
