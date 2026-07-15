# Prevent Duplicate Schedules for the Same Valve

## Metadata

```yaml
status: done
priority: medium
type: feature
```

## Title

Reject creating or updating a schedule when the target valve already has one

## Specification

### Context

`ScheduleService.create` and `ScheduleService.update` in
`src/irrigation/application/services.py` currently accept any `valve_pin`
without checking whether another schedule already targets the same valve
(and therefore the same section, since a `Valve.section` is looked up by
`pin`). Users can create several schedules for the same valve/section, for
example `10:46` and `11:06` both for `Válvula 13`. The request is to stop
this: a valve/section may have at most one schedule.

### Scope

#### In scope

- Reject schedule creation when an existing schedule already targets the
  same `valve_pin`.
- Reject schedule updates that would change a schedule's `valve_pin` to one
  already used by a different schedule.
- Surface a clear, user-facing validation error through the CLI and the
  Node-RED create/edit form (e.g. "This valve/section already has a
  schedule").
- Add regression coverage for create, update, and the Node-RED create/edit
  flow.

#### Out of scope

- Changing how a single schedule's time window, duration, or weekdays are
  validated.
- Allowing multiple time windows within one schedule record (a schedule
  remains one time + duration per valve).
- Changing the automatic controller's execution logic for existing
  overlapping schedules created before this change.
- Migrating or deleting pre-existing schedules that already share a valve.

## Impact analysis

### Files to inspect

- `src/irrigation/application/services.py` — `ScheduleService.create` and
  `ScheduleService.update`, and how `list_all` can be used to look up
  existing schedules by `valve_pin`.
- `src/irrigation/domain/models.py` — `Schedule` dataclass and
  `ValidationError` usage conventions.
- `src/irrigation/domain/exceptions.py` — existing exception types to reuse
  for the new validation error.
- `src/irrigation/cli.py` — `schedule create` / `schedule update` command
  handlers and how they currently surface `ValidationError` to the caller.
- `node-red/flows.json` — schedule create/edit form submission and error
  display.
- `tests/test_services.py` — existing `ScheduleService` create/update specs.
- `tests/test_cli.py` — existing CLI contract tests for schedule
  create/update.
- `tests/test_node_red_flow.py` — existing dashboard flow assertions for
  schedule creation/editing.
- `data/schedules.json` and `tasks/done/005-fix-shared-valve-schedule-status.md`
  — prior behavior explicitly allowed multiple schedules per valve; confirm
  this task supersedes that assumption before implementing.

### Files to change

- `src/irrigation/application/services.py` — add a duplicate-valve check in
  `create` and `update`, excluding the schedule's own id on update.
- `src/irrigation/cli.py` — ensure the new `ValidationError` is surfaced the
  same way as existing validation failures.
- `node-red/flows.json` — display the validation error message to the user
  in the create/edit form instead of failing silently.
- `tests/test_services.py` — add tests for duplicate-valve rejection on
  create and update.
- `tests/test_cli.py` — add tests for the CLI error contract.
- `tests/test_node_red_flow.py` — add a test for the form error path.

### Files to create

- None expected.

### Dependencies and integration points

- Schedules are matched by `valve_pin`; a valve's `section` name is derived
  from `Valve.section` via `ValveService.get_by_pin`, so checking
  `valve_pin` is equivalent to checking the section.
- The Node-RED dashboard sends create/update requests to the CLI through
  shell commands and must handle a non-zero/error response without leaving
  the form in an inconsistent state.

## Technical approach

### Design principles

- Keep the duplicate check inside `ScheduleService`, next to existing
  validation, rather than in the CLI or UI layer.
- Reuse the existing `ValidationError` exception and error-surfacing path
  instead of introducing a new error type or channel.
- Keep the check a simple `O(n)` scan over existing schedules; no new
  indexes or persistence changes are needed at the current expected scale.

### Proposed changes

1. In `ScheduleService.create`, before calling `self._repository.add`, check
   whether any existing schedule has the same `valve_pin` and raise
   `ValidationError` if so.
2. In `ScheduleService.update`, apply the same check against all schedules
   except the one being edited (matched by `id`).
3. Confirm the CLI already propagates `ValidationError` messages to
   Node-RED in a way the form can display; adjust only if inspection shows
   otherwise.
4. Update the Node-RED create/edit form to show the returned validation
   message when a duplicate-valve schedule is rejected.
5. Add tests for: creating a second schedule on an already-scheduled valve
   (rejected), updating a schedule to a valve used by another schedule
   (rejected), updating a schedule's own time/duration without changing its
   valve (allowed), and deleting a schedule then reusing its valve
   (allowed).

### Performance considerations

- Expected complexity: `O(n)` per create/update call, where `n` is the
  number of existing schedules.
- Performance risks: none significant at the expected scale (a small
  number of valves/schedules per household system).
- Mitigation: not needed; reuse `list_all()`, already used elsewhere in the
  service.

### Error handling and edge cases

- Creating a schedule for a valve that already has one must be rejected
  with a clear `ValidationError`.
- Updating a schedule's own fields (time, duration) without changing its
  valve must still succeed.
- Updating a schedule to point at a valve used by a different schedule must
  be rejected.
- Deleting a schedule must immediately free its valve for a new schedule.
- Existing persisted data that already violates this rule (multiple
  schedules sharing a valve, as covered by
  `tasks/done/005-fix-shared-valve-schedule-status.md`) must not crash
  `list_all`, `list_with_runtime_status`, or the automatic controller; the
  new rule only applies to new create/update calls.

## Test specification

### Unit tests

- [x] `ScheduleService.create` raises `ValidationError` when the target
      valve already has a schedule.
- [x] `ScheduleService.update` raises `ValidationError` when changing the
      valve to one used by a different schedule.
- [x] `ScheduleService.update` succeeds when the valve is unchanged.
- [x] `ScheduleService.create` succeeds for a valve with no existing
      schedule.

### Integration tests

- [x] CLI `schedule create` returns a validation error for a duplicate
      valve and does not persist a new record.
- [x] CLI `schedule update` returns a validation error when moving a
      schedule to an already-used valve.
- [x] The Node-RED create/edit form surfaces the validation error message
      to the user.

### Regression tests

- [x] Existing schedules that already share a valve continue to be listed,
      executed, and stopped correctly (per
      `tasks/done/005-fix-shared-valve-schedule-status.md`).
- [x] Deleting a schedule frees its valve for a new schedule.
- [x] Existing schedule creation/update behavior for non-duplicate valves
      is unchanged.

### Test data and fixtures

- A valve with an existing schedule and an attempt to create/update a
  second schedule targeting the same `valve_pin`.
- A valve with no schedule, to confirm creation still succeeds.
- Pre-existing fixture data with two schedules sharing a valve, to confirm
  read/list/execution paths still work without triggering the new
  create/update check.

## Acceptance criteria

The task is complete when:

- [x] Creating a schedule for a valve/section that already has one is
      rejected with a clear error.
- [x] Updating a schedule to a valve/section already used by another
      schedule is rejected with a clear error.
- [x] Editing a schedule's own time/duration without changing its valve
      still works.
- [x] Deleting a schedule frees its valve for a new schedule.
- [x] The Node-RED create/edit form shows the validation error to the user.
- [x] Existing multi-schedule-per-valve data is not broken by this change;
      only new create/update calls are restricted.
- [x] New and changed behavior is covered by specs.
- [x] Formatting, linting, type checks, and the full test suite pass.
- [x] Documentation or user-facing examples are updated when needed.

## Implementation checklist

- [x] Confirm the task number and filename.
- [x] Inspect all files listed in the impact analysis.
- [x] Confirm with existing task history
      (`tasks/done/005-fix-shared-valve-schedule-status.md`) that this
      change intentionally supersedes the prior "out of scope" note about
      allowing multiple schedules per valve.
- [x] Implement the smallest coherent change.
- [x] Add or update specs.
- [x] Run focused checks.
- [x] Run the full validation suite.
- [x] Validate the implementation against every acceptance criterion.
- [x] Move the issue to `done` only after implementation and validation
      pass.

## Notes

- The initial request is in Portuguese ("não permitir com que seja criado
  mais de um agendamento para a mesma válvula/seção"); this task is
  intentionally written in English as required by the task-generation
  convention.
- This task changes a rule that a prior task
  (`tasks/done/005-fix-shared-valve-schedule-status.md`) explicitly left
  out of scope and whose regression tests assume multiple schedules can
  share a valve. This task only restricts new create/update calls; it does
  not require migrating or rejecting already-persisted schedules that
  share a valve.
