# Warn when deleting a running schedule

## Metadata

```yaml
status: backlog
priority: medium
type: feature
```

## Title

Warn the user inside the delete confirmation modal when the schedule is running

## Specification

Restate the requested behavior: when the user opens the "Confirmar exclusão?" modal
to delete a schedule that is **currently running** (watering now), the modal itself
must display a warning that the schedule is in execution. The warning appears in the
same modal that already opens — no new modal is introduced. Deletion is still allowed;
the change only adds a clear, in-context warning so the user knows they are removing a
schedule whose valve is on right now.

### Context

The schedule list already knows when a schedule is running: `scope.sectionStatus(schedule)`
returns `1` when `schedule.status` is truthy (`node-red/templates/agendamentos.html:1177-1180`),
which is set by the backend `list_with_runtime_status` (`is_running` / valve status,
`src/irrigation/application/services.py`). The row shows a "regando agora" indicator and a
live countdown for running schedules (`agendamentos.html:875,900`). However, the delete
confirmation modal (`agendamentos.html:958-968`) shows the same generic text
("... será removido. Esta ação não pode ser desfeita.") regardless of whether the schedule
is running. A user can delete a schedule while its valve is actively watering without any
signal that a run is in progress, which is surprising and easy to do by accident.

### Scope

#### In scope

- Detect, when the delete confirmation modal opens, whether the target schedule is currently
  running (using the existing `sectionStatus` / `schedule.status` signal).
- Show a visible warning block inside the existing delete modal when the schedule is running,
  making clear that the schedule is in execution (watering now).
- Keep the warning purely presentational; the existing confirm/cancel flow is unchanged.

#### Out of scope

- Blocking or disabling deletion of a running schedule (the request is to *warn*, not prevent).
- Changing what happens to the physical valve when a running schedule is deleted (whether the
  valve keeps watering or is turned off) — see Notes for the open question and a possible
  follow-up task.
- Any backend, CLI, or data-model change; the running status is already available client-side.
- Adding a warning to any other modal (edit, manual duration).

## Impact analysis

### Files to inspect

- `node-red/templates/agendamentos.html` — delete modal markup (lines 958-968), delete
  handlers `openDeleteConfirmation`/`closeDeleteConfirmation`/`confirmDeleteSchedule`
  (lines 1314-1328), `delete_state` initialization (~line 1037), `scope.sectionStatus`
  (lines 1177-1180), and `scope.scheduleCountdown` (task 014) as the existing pattern for
  reading a running schedule's remaining time.
- `src/irrigation/application/services.py` — `ScheduleService.list_with_runtime_status` to
  confirm the `status`/`is_running` field the frontend already consumes (no change expected).
- `tests/test_node_red_flow.py` — existing template/flow assertions to see how the modal is
  covered and where to add a regression assertion for the warning markup.

### Files to change

- `node-red/templates/agendamentos.html` —
  - In `openDeleteConfirmation(schedule)`, capture whether the schedule is running (e.g.
    `scope.delete_state.running = scope.sectionStatus(schedule) === 1;`).
  - In `closeDeleteConfirmation()` and the `delete_state` initializer, reset the new
    `running` flag so a stale value never carries over to the next deletion.
  - In the delete modal markup, add a warning block shown with `ng-if="delete_state.running"`
    that states the schedule is currently running (watering now).
- `node-red/flows.json` — the schedules screen template is mirrored here as an escaped string;
  the exact same markup and controller changes must be applied to this embedded copy so the
  deployed flow matches the standalone template.

### Files to create

- None.

### Dependencies and integration points

- Relies only on the already-polled `schedule.status` field surfaced by
  `list_with_runtime_status`; no new CLI payload or backend contract is required.
- The `delete_state.schedule` reference is already stored, so the warning can optionally reuse
  `scope.scheduleCountdown(scope.delete_state.schedule)` to show remaining time — kept optional
  to avoid coupling to the countdown timer.

## Technical approach

### Design principles

- Keep the change a presentation concern in the existing modal; do not add a second modal.
- Reuse the existing running-status signal (`sectionStatus`) rather than recomputing it.
- Snapshot the running flag when the modal opens so it is deterministic for the confirmation,
  and reset it on close to avoid stale state.

### Proposed changes

1. Extend the `delete_state` object with a `running` boolean, initialized to `false`.
2. In `openDeleteConfirmation(schedule)`, set `scope.delete_state.running = scope.sectionStatus(schedule) === 1`.
3. In `closeDeleteConfirmation()`, reset `scope.delete_state.running = false` (alongside clearing `schedule`).
4. In the delete modal (`agendamentos.html:958-968`), add a warning element with
   `ng-if="delete_state.running"` above or below the existing `ir-modal-text`, worded to make
   clear the schedule is in execution now (e.g. "Este agendamento está em execução (regando agora)."),
   styled with the existing danger/warning visual treatment used elsewhere in the template.

### Performance considerations

- Expected complexity: `O(1)` — a single status read when the modal opens.
- Performance risks: none; no new polling, network calls, or timers are introduced.
- Mitigation: reuse the already-computed `sectionStatus`; do not add a per-digest watcher.

### Error handling and edge cases

- A schedule with no `status` field: `sectionStatus` returns `null`, so `=== 1` is `false` and
  no warning is shown (safe default).
- The schedule stops running while the modal is open: the snapshot taken at open time still
  shows the warning; this is acceptable and preferred over a value flickering mid-confirmation.
  (If live behavior is desired instead, bind the warning to
  `sectionStatus(delete_state.schedule) === 1`; note this couples it to the poll cycle.)
- Reopening the modal for a non-running schedule after having opened it for a running one must
  not show the warning — guaranteed by resetting `running` on close.

## Test specification

### Unit tests

- [ ] `openDeleteConfirmation` sets `delete_state.running` to `true` for a schedule whose
      `status` is truthy and `false` otherwise (if the JS is unit-testable in the existing harness).

### Integration tests

- [ ] `tests/test_node_red_flow.py`: the `agendamentos.html` template contains a warning block
      gated by `delete_state.running` inside the delete modal.

### Regression tests

- [ ] The delete modal still renders its standard text and confirm/cancel actions for a
      non-running schedule.
- [ ] `confirmDeleteSchedule` still sends the schedule id and closes the modal, unchanged.

### Test data and fixtures

- Reuse the existing template assertions in `tests/test_node_red_flow.py`; assert on the
  presence of the `delete_state.running` binding and the warning copy.

## Acceptance criteria

The task is complete when:

- [ ] Opening the delete confirmation modal for a currently running schedule shows an in-modal
      warning that the schedule is in execution.
- [ ] Opening the modal for a non-running schedule shows no such warning.
- [ ] The warning appears in the same modal that already opens (no new modal).
- [ ] Deletion remains possible and the confirm/cancel flow is unchanged.
- [ ] The `running` flag is reset between openings so no stale warning is shown.
- [ ] Existing behavior remains unchanged outside the defined scope.
- [ ] New and changed behavior is covered by specs.
- [ ] The implementation follows the project's architecture and stays a presentation-only change.
- [ ] Formatting, linting, type checks, and the full test suite pass.

## Implementation checklist

- [ ] Confirm the task number and filename.
- [ ] Inspect all files listed in the impact analysis.
- [ ] Reassess the affected files before coding and update this task if needed.
- [ ] Implement the smallest coherent change.
- [ ] Add or update specs.
- [ ] Run focused checks.
- [ ] Run the full validation suite.
- [ ] Validate the implementation against every acceptance criterion.
- [ ] Move the issue to `done` only after implementation and validation pass.

## Notes

- Original request (Portuguese): "Crie uma task para quando o usuário for excluir um
  agendamento e o mesmo estiver em execução avisar ao usuário. Aviso no próprio modal que já
  abre para o usuário." The task is written in English per the project's convention.
- Open question / possible follow-up: decide what should happen to the physical valve when a
  running schedule is deleted — does the valve keep watering until the run's end, or should
  deletion also stop the run? This behavior is out of scope here (warning only) and may warrant
  a separate task once the desired product behavior is confirmed.
- The warning may optionally show the remaining time via the existing
  `scope.scheduleCountdown` (task 014) to reinforce that a run is active.
- The `agendamentos.html` template is duplicated as an escaped string inside `flows.json`;
  every markup/JS edit must be made in both places to keep the deployed dashboard in sync.
- Backend note (`ScheduleService.delete`, `services.py:147-168`): deleting a running schedule
  already releases the valve via `_release_valve_if_unused` when no other schedule shares the
  `valve_pin`. No backend guard blocks deletion of a running schedule today — consistent with
  this task's "warn, don't block" scope.
