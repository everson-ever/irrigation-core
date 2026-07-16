# Show Running Schedule Remaining Time

## Metadata

```yaml
status: done
priority: medium
type: feature
```

## Title

Show remaining time for a schedule that is currently running

## Specification

### Context

The schedule list already shows "Regando agora" when a schedule's valve is currently on (`node-red/templates/agendamentos.html:863,888`), driven by `schedule.status` (`scope.sectionStatus`, `agendamentos.html:1125-1128`). It does not show how long is left before the valve turns off. This applies whether the run was started automatically by the controller (`IrrigationController._process_schedule`, `src/irrigation/application/services.py:543-589`) or manually from the row's "Ligar agora" action (`ManualControlService.turn_on`, `services.py:347-370`), since a manual start against a schedule row also flips `schedule.status` to `true` via `schedule_id` (`ManualControlService._set_manual_schedule_status`, `services.py:475-487`). Users currently have to guess when a section will stop watering.

### Scope

#### In scope

- Show a live countdown (remaining time) on each schedule row that is currently running, regardless of whether the run was started automatically or manually.
- Compute the countdown from the actual end time of the active run, not from the schedule's configured duration, since a manual run's duration can differ from the schedule's configured `duration_minutes`.
- Keep the countdown updating client-side between backend polls so it visibly ticks down.
- Handle schedules with multiple daily times (task 013) by using the currently active time slot's interval.

#### Out of scope

- Changing how manual or automatic runs are started, stopped, or recorded.
- Adding a countdown for the *next* scheduled run (already covered by `nextWateringCountdown`, `agendamentos.html:1160-1170`).
- Persisting or exposing remaining time through the CLI for any command other than `schedule list`.
- Any change to `duration_minutes` semantics or the history data model.

## Impact analysis

### Files to inspect

- `src/irrigation/application/services.py` — `HistoryService.record`/`_has_active_record` (lines 233-284), `ScheduleService.list_with_runtime_status` (lines 40-59), `IrrigationController._process_schedule` (lines 543-589), `ManualControlService._complete_manual_start`/`_wait_for_auto_turn_off` (lines 409-444).
- `src/irrigation/domain/models.py` — `Schedule.interval_at`/`_interval_for_time`/`is_running_at` (lines 164-198), `HistoryRecord` (start/end stored as `HH:MM` strings).
- `src/irrigation/cli.py` — `_schedule_command` "list" branch (lines 39-45) which calls `list_with_runtime_status`.
- `src/irrigation/bootstrap.py` — `Application.schedules()`/`Application.history()` (lines 41-52) wiring.
- `node-red/templates/agendamentos.html` — schedule row rendering (lines 846-916), `scope.sectionStatus` (1125-1128), `scope.nextWateringCountdown` (1160-1170) as the existing countdown pattern to follow, `scope.$watch("msg", ...)` (1033-1062) where the polled payload lands in `scope.schedules`.
- `node-red/flows.json` — the inject node that polls `irrigation schedule list` (`repeat: "3"`, ~3s interval) feeding the dashboard template.
- `tests/test_services.py` — existing `HistoryService`/`ScheduleService`/`IrrigationController` specs to extend.

### Files to change

- `src/irrigation/application/services.py` — refactor `HistoryService._has_active_record` to expose the matching record's end datetime (not just a bool), and add a method to fetch the active run's end for a given valve/section regardless of mode; extend `ScheduleService.list_with_runtime_status` to accept the history service and attach a `remaining_seconds` field to running schedules.
- `src/irrigation/cli.py` — pass `app.history()` into `list_with_runtime_status` in the "list" branch.
- `node-red/templates/agendamentos.html` — cache each running schedule's end time from `remaining_seconds` on payload arrival, add a `scope.scheduleCountdown(schedule)` helper and a client-side ticking mechanism (e.g. `$interval` at 1s) to re-render the countdown, and display it next to the existing "Regando agora" indicators (rows 863 and 888).

### Files to create

- None expected; this extends existing services and templates.

### Dependencies and integration points

- `irrigation schedule list` is the only CLI entry point read by Node-RED for this view; its JSON output is the contract the frontend consumes directly.
- The frontend has no independent data-refresh timer; the dashboard's inject node re-polls every 3 seconds. The remaining-time countdown must tick smoothly between those polls, using the server-provided `remaining_seconds` to resync each time and prevent client-side drift from accumulating.

## Technical approach

### Design principles

- Compute remaining time from the actual active interval (from history), not from static configuration, so manual and automatic runs are handled by the same code path.
- Keep the countdown a presentation concern: the backend reports a plain `remaining_seconds` snapshot; the frontend owns the ticking/display logic, matching the existing `nextWateringCountdown` pattern.
- Avoid duplicating active-interval lookup logic between `has_active_manual`, `has_active_automatic`, and the new end-time lookup.

### Proposed changes

1. In `HistoryService`, refactor `_has_active_record` so it can return the matching active record's end `datetime` (or `None`), and add `active_end(valve: str, now: datetime) -> datetime | None` that checks both manual and automatic modes; keep `has_active_manual`/`has_active_automatic` as thin wrappers over the same lookup.
2. Extend `ScheduleService.list_with_runtime_status` to accept an optional `history: HistoryService` argument; when a schedule `is_running`, resolve its valve's section and call `history.active_end(section, now)` to compute `remaining_seconds = max(0, round((end - now).total_seconds()))`, and include it in the returned dict only when a run is active.
3. Update `_schedule_command` in `cli.py` to pass `app.history()` into `list_with_runtime_status`.
4. In `agendamentos.html`, when a new payload arrives in the `$watch("msg", ...)` handler, for each running schedule compute and cache an absolute end timestamp (`Date.now() + remaining_seconds * 1000`) keyed by schedule id; clear the cached value once a schedule's `status` is no longer running.
5. Add `scope.scheduleCountdown(schedule)` that formats the cached end timestamp minus `Date.now()` as `mm:ss` (or `--` if unavailable), following the days/hours/minutes formatting style already used in `nextWateringCountdown`.
6. Add a lightweight client-side ticking mechanism (`$interval` at 1s, cleared on scope destroy) purely to trigger Angular's digest cycle so the cached countdown re-renders every second between the 3-second data polls.
7. Render the countdown next to the existing "regando agora" markers (time column note at line 863, status badge at line 888), e.g. "regando agora · faltam 4:12".

### Performance considerations

- Expected complexity: `O(n)` per poll cycle for `n` schedules, matching the existing `list_with_runtime_status` loop; the history lookup for the active record is already `O(h)` per running schedule where `h` is history size, unchanged from current `has_active_manual`/`has_active_automatic` cost.
- Performance risks: the 1-second client-side interval is UI-only and does not trigger any network call.
- Mitigation: keep the interval callback limited to reading cached timestamps, no additional backend calls.

### Error handling and edge cases

- A schedule marked `is_running` with no matching active history record (data inconsistency) must not crash the UI; omit the countdown and keep showing "Regando agora" without a time.
- A schedule with multiple time slots (task 013) must use whichever slot is currently active, matching `Schedule.interval_at`'s existing behavior of finding the interval containing `now`.
- When a run stops (poll shows `status` false), the cached countdown for that schedule id must be cleared immediately so a stale number does not flash on the next run.
- Remaining time must never be rendered as negative; clamp to zero.
- Client and server clocks may drift slightly; resync the cached end timestamp from `remaining_seconds` on every poll rather than trusting the client timer indefinitely.

## Test specification

### Unit tests

- [x] `HistoryService.active_end` returns the correct end datetime for an active manual record.
- [x] `HistoryService.active_end` returns the correct end datetime for an active automatic record.
- [x] `HistoryService.active_end` returns `None` when no record is active for the valve.
- [x] `ScheduleService.list_with_runtime_status` includes `remaining_seconds` for a running schedule and omits it for a stopped one.
- [x] `remaining_seconds` reflects a manual run's actual (possibly custom) duration, not the schedule's configured `duration_minutes`.

### Integration tests

- [x] A schedule started automatically shows a decreasing `remaining_seconds` across successive `list_with_runtime_status` calls until it stops.
- [x] A schedule started manually via `schedule_id` shows `remaining_seconds` based on the manual duration.
- [x] A schedule with multiple time slots reports `remaining_seconds` for whichever slot is currently active.

### Regression tests

- [x] Existing `is_running`/`valve_status` fields in `list_with_runtime_status` remain unchanged for stopped schedules.
- [x] `has_active_manual`/`has_active_automatic` continue to return correct booleans after the `_has_active_record` refactor.
- [x] The schedule list still renders correctly when `remaining_seconds` is absent (e.g., during upgrade/rollout with older CLI output cached).

### Test data and fixtures

- Use a fixed `Clock` implementation with known `now` values, consistent with existing tests in `tests/test_services.py`.
- Include fixtures for both a manual history record and an automatic history record active at the same `now`, on different valves.

## Acceptance criteria

The task is complete when:

- [x] A running schedule's row shows a live countdown to when it will stop, whether the run was started automatically or manually.
- [x] The countdown reflects the actual run's end time, including custom manual durations.
- [x] The countdown clears immediately when the run stops and does not show stale values on the next run.
- [x] Existing behavior remains unchanged outside the defined scope.
- [x] New and changed behavior is covered by specs.
- [x] Error cases and relevant edge cases are covered.
- [x] The implementation follows the project's architecture and SOLID principles.
- [x] The implementation is simple, readable, maintainable, and performant for the expected workload.
- [x] Formatting, linting, type checks, and the full test suite pass.

## Implementation checklist

- [x] Confirm the task number and filename.
- [x] Inspect all files listed in the impact analysis.
- [x] Reassess the affected files before coding and update this task if needed.
- [x] Implement the smallest coherent change.
- [x] Add or update specs.
- [x] Run focused checks.
- [x] Run the full validation suite.
- [x] Validate the implementation against every acceptance criterion.
- [x] Move the issue to `done` only after implementation and validation pass.

## Notes

- The initial request is in Portuguese ("quando um agendamento estiver em execução mostre quanto tempo falta para finalizar, independente se foi acionamento manual ou automático"); the implementation task is intentionally written in English as required by the task-generation convention.
- Implemented in `src/irrigation/application/services.py`, `src/irrigation/cli.py`, `node-red/templates/agendamentos.html`, `node-red/flows.json`, `tests/test_services.py`, and `tests/test_node_red_flow.py`.
- Validation run: `.venv/bin/python -m pytest` (`127 passed`), `.venv/bin/python -m ruff check .`, and `.venv/bin/python -m ruff format --check .`.
