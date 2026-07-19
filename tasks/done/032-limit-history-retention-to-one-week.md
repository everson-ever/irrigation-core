# Limit Execution-History Retention to the Last Week

## Metadata

```yaml
status: done
priority: medium
type: performance
```

## Title

Prune execution-history records older than 7 days when new records are inserted

## Specification

The system persists every irrigation execution into the `history` table and
**never deletes anything**, so the table grows without bound. On the target
hardware (a Raspberry Pi with limited storage) this is a real capacity risk.

Enforce a fixed retention window of **the last 7 days**: whenever a new
execution record is written, records whose `date` is older than the retention
window must be deleted in the same operation. The pruning must be performant —
a bounded, index-backed `DELETE`, never a full-table scan or a per-row Python
loop.

### Context

- Execution history is stored in the SQLite `history` table
  (`src/irrigation/infrastructure/sqlite_repository.py:53-61`), which has an
  index on the `date` column
  (`idx_history_date`, `sqlite_repository.py:68`). The `date` column is TEXT in
  ISO `YYYY-MM-DD` form (`HistoryRecord.to_dict`,
  `src/irrigation/domain/models.py:256-264`), so lexical `<` comparison equals
  chronological comparison — the same assumption `find_by_date_range`'s
  `BETWEEN` already relies on (`sqlite_repository.py:189-199`).
- Every history record is created through a single choke point,
  `HistoryService.record()`
  (`src/irrigation/application/services.py:338-354`), which calls
  `self._history.add(record.to_dict())`. Both call sites — manual irrigation
  (`services.py:682`) and automatic/scheduled irrigation (`services.py:915`) —
  go through it. This is the natural place to enforce retention "when new
  records are entering".
- `record()` already receives `start: datetime` (the execution start = "now"),
  so the retention cutoff can be derived without adding a new dependency
  (`Clock`) to `HistoryService`.
- There is no migration framework; the schema is applied idempotently on each
  connect via `executescript` (`sqlite_repository.py:88`). No DDL change is
  required — the existing `idx_history_date` already backs the delete.
- Related backlog task `tasks/029-optimize-history-retention-and-active-lookups.md`
  bundles "retention policy" together with new indexes and rewriting the
  `has_active_manual`/`has_active_automatic` `list_all()` scans. **This task
  (032) delivers only the retention-enforcement portion.** The index/active-
  lookup optimizations in 029 remain a separate concern; 029 should be updated
  to reference 032 for the retention part. A useful side effect: capping the
  table at ~7 days also bounds the `self._history.list_all()` scans in
  `_active_record_end` (`services.py:375-389`).

### Scope

#### In scope

- Add a bounded, history-only delete capability to `SqliteRepository`
  (e.g. `delete_before(cutoff_date: str) -> int`) that runs
  `DELETE FROM history WHERE date < ?` inside the existing
  `_write_transaction`, guarded to `self.table == "history"` exactly like
  `find_by_date_range` (`sqlite_repository.py:189-199`).
- Define the retention window as a single named constant (e.g.
  `HISTORY_RETENTION_DAYS = 7`) in the application layer, alongside the other
  history constants (`services.py:28-31`).
- In `HistoryService.record()`, after the insert, prune records older than the
  window using `start.date()` as the reference date:
  cutoff = `start.date() - timedelta(days=HISTORY_RETENTION_DAYS)`; delete
  records with `date < cutoff.isoformat()`.
- Invoke the prune defensively (e.g. via `getattr(self._history,
  "delete_before", None)`), mirroring how `search_range` optionally uses
  `find_by_date_range` (`services.py:410-412`), so a repository backend without
  the method does not break.

#### Out of scope

- Making the retention window configurable via environment/`Settings`
  (`src/irrigation/config.py`). Keep it a single constant for now; env-driven
  configuration can be a follow-up.
- Adding new indexes or rewriting the `has_active_manual` /
  `has_active_automatic` / `_active_record_end` scans — that belongs to task
  029.
- Any change to the `history_search_results.json` cache
  (`JsonLinesRepository`) or the search read paths (`search_day`/
  `search_range`).
- A background/scheduled cleanup job — pruning is done inline on insert.
- Backfilling / one-time bulk cleanup of an already-large table beyond what the
  first post-change insert prunes (the first `record()` after deploy will prune
  all rows older than the window in one indexed delete, which is sufficient).

## Impact analysis

### Files to inspect

- `src/irrigation/application/services.py:28-31` — existing history constants;
  where `HISTORY_RETENTION_DAYS` should live.
- `src/irrigation/application/services.py:338-354` — `HistoryService.record()`,
  the single insertion choke point to extend with pruning.
- `src/irrigation/application/services.py:375-402` — `_active_record_end` /
  `_record_interval`, to confirm pruning by `date` never removes a still-active
  record (active records are always today's, well inside the window).
- `src/irrigation/application/services.py:404-420` — `search_range`'s optional
  `getattr(..., "find_by_date_range")` pattern to mirror for `delete_before`.
- `src/irrigation/infrastructure/sqlite_repository.py:53-68` — `history` DDL
  and `idx_history_date`, confirming the index backs `WHERE date < ?`.
- `src/irrigation/infrastructure/sqlite_repository.py:92-101,189-199` —
  `_write_transaction` and the `find_by_date_range` guard pattern to follow.
- `src/irrigation/domain/models.py:246-264` — `HistoryRecord`, confirming
  `date` is serialized as ISO `YYYY-MM-DD`.
- `tests/test_services.py:40-65` — the `create_controller` fixture wiring a real
  `SqliteRepository(connection, "history")`, to base retention tests on.
- `tests/test_sqlite_repository.py:100-127` — existing history repository tests
  (`find_by_date_range`), the pattern for a `delete_before` unit test.

### Files to change

- `src/irrigation/infrastructure/sqlite_repository.py` — add the history-only
  `delete_before(cutoff_date)` method (bounded, indexed `DELETE`, in a write
  transaction).
- `src/irrigation/application/services.py` — add `HISTORY_RETENTION_DAYS` and
  prune older records inside `HistoryService.record()`.
- `tests/test_sqlite_repository.py` — unit test for `delete_before`.
- `tests/test_services.py` — behavior test that `record()` prunes rows older
  than the window and keeps rows within it.

### Files to create

- None.

### Dependencies and integration points

- `Repository` port (`src/irrigation/domain/ports.py:10-16`): `delete_before` is
  a history-specific extension accessed via `getattr`, so the core `Repository`
  Protocol does not need to change (consistent with `find_by_date_range`, which
  is also not on the Protocol).
- SQLite `history` table and its `idx_history_date` index — no schema/DDL
  change; the existing index backs the delete.
- Composition root `src/irrigation/bootstrap.py:54-58` — no change; history is
  always wired to `SqliteRepository`.

## Technical approach

### Design principles

- Keep each class and function focused on one responsibility.
- Depend on abstractions at architectural boundaries.
- Keep domain rules independent from infrastructure details.
- Prefer small, explicit interfaces and simple data flows.
- Avoid speculative abstractions, duplicated logic, and unrelated changes.

### Proposed changes

1. In `sqlite_repository.py`, add
   `delete_before(self, cutoff_date: str) -> int`: guard
   `self.table == "history"` (raise `ValueError` otherwise, like
   `find_by_date_range`), then inside `_write_transaction` run
   `DELETE FROM history WHERE date < ?` with `(cutoff_date,)` and return
   `cursor.rowcount`.
2. In `services.py`, add module constant `HISTORY_RETENTION_DAYS = 7` next to
   the existing history constants, with a short comment explaining the "last
   week" policy.
3. In `HistoryService.record()`, after `self._history.add(...)`, compute
   `cutoff = start.date() - timedelta(days=HISTORY_RETENTION_DAYS)` and, if the
   repository exposes `delete_before`, call
   `delete_before(cutoff.isoformat())`. Return the inserted record unchanged.
   (`timedelta`/`date` are already imported at `services.py:11`.)
4. Keep the retention *policy* (the 7-day window, the reference date) in the
   application layer; the repository only executes a bounded delete it is told
   to run — infrastructure stays free of domain rules.

Decision to confirm during implementation: whether "last week" means delete
`date < today - 7` (a strict 7-day trailing window, chosen here) vs
`date < today - 6` (keep 7 calendar days including today). Both keep at least a
full week of usable history; the constant makes the boundary explicit and easy
to adjust.

### Performance considerations

- Expected input size: a handful of executions per day; the table is capped at
  ~7 days of rows after the first prune.
- Expected complexity: insert stays `O(1)` amortized; the prune is
  `O(log n + k)` where `k` is the number of deleted rows, using
  `idx_history_date` for the `WHERE date < ?` range — no full-table scan and no
  per-row Python iteration.
- I/O behavior: one extra small, indexed `DELETE` per execution insert. Given
  the low insertion frequency this is negligible; on steady state the delete
  usually touches 0 rows (cheap index seek).
- Performance risks: running two separate write transactions per `record()`
  (the `add` then the prune). Acceptable at this insertion rate; if it ever
  matters, the insert+prune can be folded into a single transaction via a
  dedicated repository method — noted, not implemented now.
- Mitigation: rely on the existing `idx_history_date`; do not add a Python-side
  filter/loop.

### Error handling and edge cases

- Records crossing midnight: stored under `start.date()` with an `end` that may
  roll to the next day (`_record_interval`, `services.py:391-402`). Pruning by
  `date` only removes records whose *start* date is older than the window, so a
  currently-active record (always today's) is never deleted.
- Steady state / nothing to delete: `DELETE ... WHERE date < ?` matches 0 rows
  and returns quickly; `record()` behaves exactly as before.
- ISO date comparison: `date` is TEXT `YYYY-MM-DD`, so string `<` equals
  chronological order — same assumption already used by `find_by_date_range`.
- Backend without `delete_before` (e.g. a JSON/alt repository in a test): the
  `getattr` guard skips pruning rather than raising, preserving current
  behavior (mirrors `search_range`).
- First insert after deploy on an already-large table: prunes everything older
  than the window in one indexed delete; subsequent inserts stay cheap.

## Test specification

### Unit tests

- [x] `SqliteRepository.delete_before` on the `history` table deletes only rows
      with `date <` the cutoff, leaves rows on/after it, and returns the deleted
      count.
- [x] `delete_before` on a non-history table raises `ValueError` (matching the
      `find_by_date_range` guard).

### Integration tests

- [x] `HistoryService.record()` prunes rows older than
      `HISTORY_RETENTION_DAYS` while keeping rows within the window, using a
      seeded history table and a controlled `start` datetime (extend the
      `create_controller` fixture in `tests/test_services.py`).

### Regression tests

- [x] Existing history tests in `tests/test_services.py` (record shape,
      `list_all` contents, active-run detection) still pass — records within the
      window are untouched.
- [x] `search_day`/`search_range` behavior is unchanged for data inside the
      retention window.

### Test data and fixtures

- Seed the real `SqliteRepository(connection, "history")` (already provided by
  the `create_controller` fixture) with records dated inside and outside the
  7-day window relative to a fixed `start`/clock value.

## Acceptance criteria

The task is complete when:

- [x] Writing a new execution record deletes all history records older than the
      7-day retention window in the same operation.
- [x] Records within the last 7 days are preserved and remain fully usable by
      search and active-run detection.
- [x] Pruning uses a bounded, `idx_history_date`-backed `DELETE` — no
      full-table scan and no per-row Python loop.
- [x] The retention window is a single named constant.
- [x] Existing behavior remains unchanged outside the defined scope.
- [x] New and changed behavior is covered by specs (repository unit test +
      service behavior test), including the midnight-crossing and
      nothing-to-delete edge cases.
- [x] The implementation follows the project's hexagonal architecture and SOLID
      principles (policy in the application layer, bounded delete in
      infrastructure).
- [x] Formatting, linting, type checks, and the full test suite pass
      (`ruff`, `mypy`, `pytest`).

## Implementation checklist

- [x] Confirm the task number and filename (`032-...`).
- [x] Inspect all files listed in the impact analysis.
- [x] Reassess the affected files before coding and update this task if needed.
- [x] Implement the smallest coherent change (repository `delete_before` +
      `HistoryService.record` prune + constant).
- [x] Add or update specs.
- [x] Run focused checks (history repository + service tests).
- [x] Run the full validation suite.
- [x] Validate the implementation against every acceptance criterion.
- [x] Move the issue to `status: done` only after implementation and validation
      pass.

## Notes

- Original request (Portuguese): "Hoje o sistema salva o histórico das
  execuções sem limite algum … a ideia é salvar somente a última semana;
  registros antigos devem ser deletados quando novos estiverem entrando; faça de
  modo performático." Interpreted as a fixed 7-day retention window enforced by
  an index-backed prune-on-insert at the `HistoryService.record()` choke point.
- Overlaps with `tasks/029-optimize-history-retention-and-active-lookups.md`.
  This task owns the retention-enforcement piece; 029 should be updated to defer
  retention to 032 and keep only the indexing/active-lookup optimizations.
