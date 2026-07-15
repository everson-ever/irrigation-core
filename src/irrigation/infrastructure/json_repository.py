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

from irrigation.domain.exceptions import RecordNotFoundError, ValidationError


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
        # Parse cache keyed by (inode, mtime_ns, size). Writers always use
        # atomic os.replace (new inode/mtime), so a stat comparison detects
        # writes from other processes; the polling loops then skip
        # lock + read + JSON parse when nothing changed.
        self._cache_key: tuple[int, int, int] | None = None
        self._cache_records: list[dict[str, Any]] | None = None
        # Tail state from the last read/write, consumed by add() to repair
        # the file before appending: byte offset of a torn final line left
        # by a crash mid-append, and whether the file ends with a newline.
        self._tail_torn_offset: int | None = None
        self._tail_ends_with_newline = True

    @staticmethod
    def _stat_key(stat: os.stat_result) -> tuple[int, int, int]:
        return (stat.st_ino, stat.st_mtime_ns, stat.st_size)

    def _cached_copy(self) -> list[dict[str, Any]]:
        assert self._cache_records is not None
        # Copy each record so callers may mutate results without
        # corrupting the cache (same semantics as a fresh parse).
        return [dict(record) for record in self._cache_records]

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
        # Binary mode so a crash mid-append (torn multi-byte character)
        # cannot make the whole file unreadable.
        with self.file_path.open("rb") as file:
            # fstat the open descriptor so the key matches the exact
            # content parsed, even if the path is replaced concurrently.
            key = self._stat_key(os.fstat(file.fileno()))
            if key == self._cache_key and self._cache_records is not None:
                return self._cached_copy()
            raw = file.read()
        ends_with_newline = raw.endswith(b"\n") or not raw
        torn_offset: int | None = None
        lines = raw.split(b"\n")
        for line_number, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                data = json.loads(line)
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                if line_number == len(lines) and not ends_with_newline:
                    # Torn final line from a crash mid-append: tolerate it
                    # here; add() truncates it before the next append.
                    torn_offset = len(raw) - len(line)
                    continue
                raise ValidationError(
                    f"invalid JSON in {self.file_path}, line {line_number}"
                ) from exc
            if not isinstance(data, dict):
                raise ValidationError(
                    f"invalid record in {self.file_path}, line {line_number}"
                )
            records.append(data)
        self._cache_key = key
        self._cache_records = [dict(record) for record in records]
        self._tail_torn_offset = torn_offset
        self._tail_ends_with_newline = ends_with_newline
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
            self._cache_records = [dict(record) for record in records]
            self._tail_torn_offset = None
            self._tail_ends_with_newline = True
            try:
                self._cache_key = self._stat_key(os.stat(self.file_path))
            except OSError:
                self._cache_key = None
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def list_all(self) -> list[dict[str, Any]]:
        # Lock-free fast path: the cache key was captured from content read
        # (or written) under a lock, and atomic replacement guarantees the
        # path never holds a partially written file.
        if self._cache_records is not None:
            try:
                if self._stat_key(os.stat(self.file_path)) == self._cache_key:
                    return self._cached_copy()
            except OSError:
                pass
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
            self._append_without_lock(new_record)
            return new_record

    def _append_without_lock(self, record: dict[str, Any]) -> None:
        """Append a single line instead of rewriting the whole file.

        Keeps add() O(1) as history.json grows and reduces SD-card wear;
        a crash mid-append leaves at most one torn final line, which
        _read_without_lock tolerates and the next append truncates.
        """
        line = json.dumps(record, ensure_ascii=False).encode("utf-8") + b"\n"
        with self.file_path.open("r+b") as file:
            if self._tail_torn_offset is not None:
                file.truncate(self._tail_torn_offset)
            elif not self._tail_ends_with_newline:
                line = b"\n" + line
            file.seek(0, os.SEEK_END)
            file.write(line)
            file.flush()
            os.fsync(file.fileno())
        if self._cache_records is not None:
            self._cache_records.append(dict(record))
        self._tail_torn_offset = None
        self._tail_ends_with_newline = True
        try:
            self._cache_key = self._stat_key(os.stat(self.file_path))
        except OSError:
            self._cache_key = None

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
