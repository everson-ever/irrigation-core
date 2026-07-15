# Toggle a Schedule's Enabled State from the Edit Page

## Metadata

```yaml
status: done
priority: medium
type: feature
```

## Title

Add an on/off toggle on the schedule edit page so the user can disable a schedule without deleting it

## Specification

### Context

The user wants to be able to disable a schedule so it will not turn its
valve on automatically, even when its configured time arrives, without
deleting the schedule (so it can be re-enabled later). They asked for this
control to live on the schedule edit page, as a liga/desliga (on/off)
component.

The backend for this already exists and is fully implemented and tested:
`Schedule.enabled` (`src/irrigation/domain/models.py:37`) defaults to
`True` and gates `Schedule.is_running_at` (`models.py:76-78`);
`ScheduleService.set_enabled` (`src/irrigation/application/services.py:101-106`)
validates and persists the flag; `IrrigationController.run_once`
(`services.py`, the `if not schedule.enabled:` branch) already force-stops
the valve and skips all start/restart logic for a disabled schedule, even
across a controller restart; and the CLI already exposes
`irrigation schedule enabled <id>,<0|1>` (`src/irrigation/cli.py:40-41,100-101`).
This is covered today by `tests/test_models.py::test_disabled_schedule_is_not_running_inside_interval`
and `tests/test_services.py::test_disabled_schedule_does_not_turn_on` /
`test_disabling_active_schedule_turns_valve_off_and_resets_status`.

What is missing is exclusively the Node-RED dashboard: there is no
toggle/switch UI anywhere in `node-red/flows.json`, no flow node ever calls
`irrigation schedule enabled`, and `tests/test_node_red_flow.py` has no
coverage for it. `schedule list` already returns `enabled` on every row
(via `Schedule.to_dict()`), so the table/edit template already receives the
current state without any backend change — this task is a pure Node-RED
(dashboard) addition wired to an existing backend command.

### Scope

#### In scope

- Add a liga/desliga toggle for `enabled` on the schedule edit form
  (`ui_template` node `25072c26.808454` in `node-red/flows.json`, the
  `form-editSchedule` block), reflecting the schedule's current `enabled`
  state when the form is opened via "Editar".
- Wire the toggle to a new `ui_action` (e.g. `toggle_enabled`) that calls
  the existing CLI command `irrigation schedule enabled <id>,<0|1>` through
  a new `exec` node, independent of the "Salvar alterações" (time/duration/
  valve) submit, mirroring how `set_enabled` is a separate service method
  from `update`.
- Reflect the change immediately in the schedules table (badge/status) and
  surface any error the CLI/service returns (e.g. invalid id), reusing the
  existing `schedule_error` banner pattern used by delete/edit.
- Add Node-RED flow tests (`tests/test_node_red_flow.py`) asserting the new
  markup, the new `ui_action`, the new exec node's `command`, and its wiring
  into the router function and back into the template.
- Add a CLI regression test for `schedule enabled` in `tests/test_cli.py`
  (currently absent) covering the success and invalid-flag cases.

#### Out of scope

- Any change to `Schedule.enabled`, `ScheduleService.set_enabled`,
  `IrrigationController.run_once`'s disabled-schedule handling, or the CLI
  `schedule enabled` subcommand itself — this logic already exists and is
  already tested; do not modify it beyond what's needed to wire the UI.
- Changing how the "Salvar alterações" (time/duration/valve) edit submit
  works, or folding `enabled` into that same payload/exec call.
- Deleting schedules, weekday/multi-day scheduling
  (`tasks/backlog/001-support-multiple-weekdays.md`), or any other
  unrelated schedule field.
- Adding a generic reusable switch/checkbox component beyond what this one
  toggle needs.

## Impact analysis

### Files to inspect

- `src/irrigation/domain/models.py` — `Schedule.enabled` (line 37) and
  `is_running_at` (lines 76-78), confirming the field and firing gate
  already exist and need no change.
- `src/irrigation/application/services.py` — `ScheduleService.set_enabled`
  (lines 101-106) and `IrrigationController.run_once`'s `if not
  schedule.enabled:` branch, confirming the persistence and controller
  behavior already exist and need no change.
- `src/irrigation/cli.py` — the `schedule enabled` subparser (lines 40-41)
  and dispatch (lines 100-101), confirming the CLI contract (`id,0|1` ->
  JSON result) the new exec node must call.
- `node-red/flows.json` — the `25072c26.808454` "Agendamentos" `ui_template`
  (edit form + table + script) and the `d4f14a77.92f3b1` "Roteia ações da
  tabela de agendamentos" router (3 outputs: delete, edit, manual), plus
  the existing edit chain (`c86fb12c.66d1e` -> `46dd0feb.e4f05` ->
  `b8d2c4e6.f70123` / `e95d01ea.97e4c`) as the wiring pattern to mirror.
- `tests/test_node_red_flow.py` — existing assertions on the edit form
  (`test_schedule_edit_has_prefill_exclusive_mode_loading_and_error_handling`)
  and table (`test_schedule_table_uses_schedule_status_for_badges_and_actions`,
  `test_manual_schedule_action_updates_clicked_schedule_row_immediately`) to
  follow the same string/wires assertion style.
- `tests/test_cli.py` — existing schedule command tests, to add the missing
  `schedule enabled` coverage in the same style.

### Files to change

- `node-red/flows.json`:
  - `25072c26.808454` (`format`): add the enabled toggle markup to
    `form-editSchedule`, prefill it from `schedule.enabled` in
    `scope.sendData`, add a `scope.toggleEnabled(schedule)` (or similar)
    function returning `{ ui_action: "toggle_enabled", id, enabled }`, and
    handle its success/error the same way `schedule_update_error` is
    handled today.
  - `d4f14a77.92f3b1` (router `func`): add a fourth branch for
    `payload.ui_action === "toggle_enabled"` and a fourth `outputs`/`wires`
    entry.
  - New `exec` node running `/opt/irrigation/bin/irrigation schedule
    enabled`, plus success/error function nodes, wired from the router and
    back into `25072c26.808454`, following the `c86fb12c.66d1e` /
    `46dd0feb.e4f05` / `b8d2c4e6.f70123` / `e95d01ea.97e4c` pattern.
- `tests/test_node_red_flow.py` — add assertions for the new toggle markup,
  `ui_action`, exec command, and wires.
- `tests/test_cli.py` — add `schedule enabled` success/error test cases.

### Files to create

- None expected; the new nodes are added inline to the existing
  `node-red/flows.json` array.

### Dependencies and integration points

- The toggle must call the existing `irrigation schedule enabled <id>,<0|1>`
  CLI command; it must not duplicate the enable/disable logic in Node-RED.
- `ScheduleService.set_enabled` already raises `ValidationError` for an
  invalid flag or unknown id; the new exec/error chain must surface that
  message the same way `schedule_update_error` is surfaced today.
- `schedule list`'s existing per-row `enabled` field (from
  `Schedule.to_dict()`) is the source of truth the table/edit form must
  read from; no backend change is needed to expose it.

## Technical approach

### Design principles

- Reuse the existing backend command and error-surfacing conventions
  instead of introducing new persistence, validation, or firing logic.
- Keep toggling `enabled` a separate action from the time/duration/valve
  edit submit, matching the backend's own separation between `update` and
  `set_enabled`.
- Follow the established Node-RED wiring pattern (format function -> exec
  -> success/error function) already used for delete/edit/manual actions,
  rather than inventing a new flow shape.
- Test Node-RED behavior the same way the rest of the suite does: string/
  substring assertions on `flows.json` node `format`/`func` fields and
  `wires` arrays.

### Proposed changes

1. In the `25072c26.808454` template's edit form, add a toggle control for
   `enabled` (reusing the project's `.ir-*` styling; a real
   `<input type="checkbox">`/switch is acceptable since no prior switch
   component exists to match).
2. In `scope.sendData`, prefill the toggle from `schedule.enabled` when the
   form opens for a given schedule.
3. Add `scope.toggleEnabled(schedule)` returning
   `{ ui_action: "toggle_enabled", id: schedule.id, enabled: <0|1> }`, wired
   to the toggle's change/click handler, independent from
   `scope.editSchedule`.
4. In `d4f14a77.92f3b1`, add a branch: if `payload.ui_action ===
   "toggle_enabled"`, format the payload and route it to a new output.
5. Add a new format function node turning `{ id, enabled }` into the CSV
   string the CLI expects (`${id},${enabled}`), a new `exec` node running
   `/opt/irrigation/bin/irrigation schedule enabled`, and success/error
   function nodes mirroring `b8d2c4e6.f70123`/`e95d01ea.97e4c`, wired back
   into `25072c26.808454` (to refresh the row's `enabled` state) and into
   the existing schedule-list refresh path.
6. Update the table/edit form to reflect the schedule's `enabled` state
   (e.g. a status label or the toggle itself) so the user can see at a
   glance whether a schedule is active without opening the edit form.

### Performance considerations

- Expected complexity: `O(1)` per toggle action; no new loops over
  schedules or valves are introduced beyond what `schedule list` already
  does on refresh.
- Performance risks: none beyond the existing per-action CLI subprocess
  invocation already used by every other row action.
- Mitigation: not needed at this scale.

### Error handling and edge cases

- Toggling `enabled` for a schedule that is currently running (mid
  interval) must immediately stop its valve on the next controller cycle,
  which `run_once`'s existing disabled-schedule branch already guarantees;
  the UI must reflect the schedule as disabled right away regardless of
  whether the valve has physically turned off yet.
- Re-enabling a schedule must not retroactively fire it for a window that
  already elapsed; this is already guaranteed by `is_running_at`'s pure
  time-window check and needs no new UI logic.
- An invalid or unknown schedule id (e.g. deleted in another tab) must
  surface the CLI's `ValidationError` message through the existing error
  banner instead of failing silently.
- Toggling must not interfere with or reset the schedule's `time`,
  `duration_minutes`, or `valve_pin` fields, and must not require the
  "Salvar alterações" edit submit to take effect.

## Test specification

### Unit tests

- [ ] `tests/test_cli.py`: `schedule enabled <id>,1` and `<id>,0` return the
      updated record with the expected `enabled` value.
- [ ] `tests/test_cli.py`: `schedule enabled <id>,2` (or another invalid
      flag) returns a validation error and does not change the persisted
      record.

### Integration tests

- [ ] `tests/test_node_red_flow.py`: the edit form template contains the
      new toggle markup and prefills it from `schedule.enabled`.
- [ ] `tests/test_node_red_flow.py`: the router function
      (`d4f14a77.92f3b1`) has a `toggle_enabled` branch and a matching
      `wires` entry pointing at the new format/exec chain.
- [ ] `tests/test_node_red_flow.py`: the new `exec` node's `command` is
      `/opt/irrigation/bin/irrigation schedule enabled`, and its
      success/error outputs wire back into `25072c26.808454`.

### Regression tests

- [ ] Existing edit-form tests
      (`test_schedule_edit_has_prefill_exclusive_mode_loading_and_error_handling`)
      continue to pass unmodified.
- [ ] Existing table/status/manual-action tests
      (`test_schedule_table_uses_schedule_status_for_badges_and_actions`,
      `test_manual_schedule_action_updates_clicked_schedule_row_immediately`)
      continue to pass.
- [ ] `tests/test_models.py::test_disabled_schedule_is_not_running_inside_interval`
      and `tests/test_services.py::test_disabled_schedule_does_not_turn_on` /
      `test_disabling_active_schedule_turns_valve_off_and_resets_status`
      continue to pass unmodified, confirming this task does not touch the
      already-correct firing logic.

### Test data and fixtures

- A schedule fixture with `enabled: 1` and one with `enabled: 0`, to assert
  the toggle's prefilled state in each case.
- The existing `load_nodes()` helper in `tests/test_node_red_flow.py` to
  load and assert against `node-red/flows.json`.

## Acceptance criteria

The task is complete when:

- [ ] The schedule edit page shows a liga/desliga toggle reflecting whether
      the schedule is currently enabled.
- [ ] Turning the toggle off calls `irrigation schedule enabled <id>,0` and
      the schedule stops firing automatically at its configured time,
      including turning off a valve it currently has running.
- [ ] Turning the toggle back on calls `irrigation schedule enabled
      <id>,1` and the schedule resumes firing at its next natural
      occurrence.
- [ ] The action is independent from the "Salvar alterações" submit — the
      user does not need to save the time/duration/valve fields to toggle
      enabled state, and vice versa.
- [ ] Errors from the CLI/service are shown to the user via the existing
      error banner pattern.
- [ ] Existing behavior remains unchanged outside the defined scope,
      including the existing enabled/disabled firing logic and edit
      submit flow.
- [ ] New and changed behavior is covered by specs.
- [ ] Error cases and relevant edge cases are covered.
- [ ] The implementation follows the project's architecture and SOLID
      principles.
- [ ] The implementation is simple, readable, maintainable, and performant
      for the expected workload.
- [ ] Formatting, linting, type checks, and the full test suite pass.
- [ ] Documentation or user-facing examples are updated when needed.

## Implementation checklist

- [ ] Confirm the task number and filename.
- [ ] Inspect all files listed in the impact analysis.
- [ ] Reassess the affected files before coding and update this task if
      needed.
- [ ] Implement the smallest coherent change.
- [ ] Add or update specs.
- [ ] Run focused checks.
- [ ] Run the full validation suite.
- [ ] Validate the implementation against every acceptance criterion.
- [ ] Move the issue to `done` only after implementation and validation
      pass.

## Notes

- The initial request is in Portuguese ("o usuário poder desativar um
  agendamento para não ser ligado automaticamente mesmo se chegar aquele
  horário que deveria ligar, com essa ação na página de edição, em algum
  componente liga/desliga"); this task is written in English per the
  task-generation convention.
- Investigation (see this task's research) confirmed the backend for this
  feature is already complete and tested — `Schedule.enabled`,
  `ScheduleService.set_enabled`, the controller's disabled-schedule branch,
  and the `irrigation schedule enabled` CLI command all already exist. This
  task is scoped to the Node-RED dashboard wiring only.
- There is no existing switch/toggle UI component in the dashboard to
  reuse; the closest precedent is the `Ligar agora` / `Desligar agora`
  mutually-exclusive button pair used for manual valve control. Either
  convention (button pair or a real checkbox/switch) is acceptable; prefer
  whichever reads more clearly as a persistent on/off state rather than a
  one-shot action, since unlike manual on/off this toggle represents a
  standing configuration, not an immediate valve action.
