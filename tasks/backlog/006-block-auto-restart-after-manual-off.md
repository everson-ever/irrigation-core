# Block Automatic Restart After Manually Turning Off an Automatically Started Valve

## Metadata

```yaml
status: backlog
priority: high
type: bug
```

## Title

Do not automatically turn a valve back on after the user turns it off while its triggering schedule is still active

## Specification

### Context

The schedules dashboard already lets the user turn off a valve that is currently on, through the `Desligar agora` button shown on an active schedule row (see `node-red/flows.json`, `scope.turnScheduleOff`). This sends `{ ui_action: "manual", action: "off", valve_pin }`, which is dispatched to `irrigation valve <pin>,off` and ultimately calls `ValveService.turn_off(pin, manual=True)` (`src/irrigation/application/services.py`).

Turning a valve off this way sets `Valve.manually_turned_off = True` and `Valve.status = False`, but it never touches the `Schedule.status` field of the schedule that turned the valve on. The automatic controller (`IrrigationController.run_once`) keeps treating the schedule as active until its time interval ends, and nothing in `run_once` ever reads `Valve.manually_turned_off`.

In the normal case, this is harmless: once a schedule has been started in the current process, its id stays in `self._started_in_this_process`, so the `elif is_running and schedule.status and schedule.id not in self._started_in_this_process` branch never re-fires and the valve stays off for the rest of the interval.

The problem appears whenever the controller process restarts while the schedule's interval is still running (service restart, deploy, crash recovery, `systemd` restart, reboot). `_started_in_this_process` is rebuilt empty, `schedule.status` is still persisted as `True` (never cleared by the manual-off action), and `run_once` treats this exactly like the interrupted-schedule recovery case covered by `test_reactivates_hardware_for_interrupted_schedule`: it calls `_start(..., "Restarted", restarted=True)`, which calls `ValveService.turn_on(pin, force_hardware=True)` and switches the physical valve back on — overriding the user's manual off before the scheduled duration has elapsed.

A related, user-visible symptom is that the schedules table's `Status da seção` column is computed purely from `Schedule.is_running_at(now)` (a time-window check) in `ScheduleService.list_with_runtime_status`, without checking whether the valve is actually on. After a manual off during an active schedule window, the row keeps showing `Ligada` and the `Desligar agora` button, even though the valve is physically off — the UI gives no feedback that the action had any effect.

Manually turning a valve on (not tied to any schedule interval) and turning it off again already works correctly today, because `ManualControlService.turn_on` waits for the requested duration in the same process and stops on its own (`_wait_for_auto_turn_off`); that flow is out of scope and must not be changed.

### Scope

#### In scope

- Prevent the automatic controller from turning a valve back on for the remainder of the interval that was active when the user manually turned it off, including across a controller process restart.
- Keep the existing crash/restart recovery behavior intact: if a schedule's valve is unexpectedly off on restart *without* a manual-off having occurred, the controller must still restore it (`test_reactivates_hardware_for_interrupted_schedule`).
- Make the schedules dashboard reflect the real valve state: a schedule row must stop showing `Ligada` (and the `Desligar agora` action) once the valve has been manually turned off, even while the schedule's time window is still open.
- Ensure the next legitimate occurrence of a schedule (its next natural start, or a different schedule's own interval) is unaffected and still turns the valve on normally.

#### Out of scope

- Changing manual valve activation (`Ligar agora` / `ManualControlService.turn_on`) or its wait-for-duration behavior.
- Changing how overlapping schedules on the same valve decide when to turn the valve off at interval end (`keep_valve_on` logic).
- Adding a way to resume/re-enable an automatically stopped schedule before its interval ends (the user can still use `Ligar agora` manually if they want it back on).
- Changing schedule creation, editing, deletion, or weekday/day-of-week behavior.
- Changing the persisted schedule or valve JSON formats beyond what is already available (`Valve.manually_turned_off` already exists and is unused for this purpose).

## Impact analysis

### Files to inspect

- `src/irrigation/domain/models.py` — `Schedule.is_running_at`/`interval_at` (time-window only, lines 65-78) and `Valve.manually_turned_off` (lines 86-112), which is set but never read today.
- `src/irrigation/application/services.py` — `ValveService.turn_on`/`turn_off` (lines 138-160), `ScheduleService.list_with_runtime_status` (lines 32-38), and `IrrigationController.run_once` (lines 303-341), particularly the `"Restarted"` branch (lines 334-339).
- `src/irrigation/cli.py` — `schedule list` dispatch (line 88) and `valve <pin>,off` dispatch (lines 111-112).
- `node-red/flows.json` — the schedules template (`format` field around line 649): `scope.sectionStatus`, `scope.turnScheduleOff`, and the row action buttons that key off `sectionStatus(schedule)`.
- `tests/test_services.py` — `test_reactivates_hardware_for_interrupted_schedule` (lines 158-178, must keep passing unmodified in intent), `test_schedule_runtime_status_is_specific_to_shared_valve_schedule` and `test_manual_on_valve_does_not_mark_inactive_schedule_as_running` (lines 258-306).
- `tests/test_cli.py` — `test_schedule_list_reports_schedule_specific_running_status` (lines 66-112), the CLI output contract for `is_running`.
- `tests/test_node_red_flow.py` — `test_schedule_list_uses_cli_runtime_status_output` (lines 76-97), asserting the dashboard reads `schedule.is_running`.
- `data/valves.json`, `data/schedules.json` — current persisted shapes, to confirm `manually_turned_off` is already a valid field with a safe default for existing records.

### Files to change

- `src/irrigation/application/services.py`:
  - `IrrigationController.run_once` — guard the `"Restarted"` branch so it does not turn the valve back on when the associated valve has `manually_turned_off = True`.
  - `ScheduleService.list_with_runtime_status` — combine the existing time-window check with the real valve status so a manually stopped valve is reported as not running, while keeping `Schedule.is_running_at` itself unchanged for the controller's own timing decisions.
- `src/irrigation/cli.py` — pass valve data into `list_with_runtime_status` if the method's signature changes to depend on `ValveService`.
- `node-red/flows.json` — only if manual inspection shows the row/button logic needs adjustment beyond consuming the corrected `is_running` field (it already derives `sectionStatus` and button visibility from that field).
- `tests/test_services.py`, `tests/test_cli.py`, `tests/test_node_red_flow.py` — add regression and behavior coverage described below.

### Files to create

- None expected.

### Dependencies and integration points

- `IrrigationController.run_once` is the single place deciding automatic start/stop/restart; it is the only code path that must respect the manual-off guard.
- `ValveService.turn_on` already clears `manually_turned_off` whenever a valve genuinely transitions from off to on — this natural reset is what allows the next legitimate schedule occurrence to run normally without extra bookkeeping.
- The dashboard receives schedule rows exclusively through `irrigation schedule list` (`ScheduleService.list_with_runtime_status`); any status correction must flow through that single source of truth rather than duplicating logic in Node-RED.

## Technical approach

### Design principles

- Keep the controller's own timing decisions (`Schedule.is_running_at`) independent from valve hardware state; combine them only where reporting or start decisions actually need the real-world state.
- Reuse the existing `Valve.manually_turned_off` flag instead of introducing a new persisted field or a schedule-level "cancelled" flag.
- Keep the fix local to the two places that currently disagree with reality: the restart-recovery branch in the controller, and the dashboard status projection.
- Do not weaken the existing crash-recovery guarantee for schedules that were legitimately interrupted without user action.

### Proposed changes

1. In `IrrigationController.run_once`, before executing the `"Restarted"` branch, look up the schedule's valve and skip calling `_start` when `valve.manually_turned_off` is `True`; leave `schedule.status` and `_started_in_this_process` untouched so the schedule still stops normally through the existing `elif not is_running and schedule.status` branch once its interval ends.
2. Update `ScheduleService.list_with_runtime_status` to accept the current valves (or a `ValveService`) and report `is_running` as `schedule.is_running_at(now) and valve.status`, so a manually stopped valve is shown as `Desligada` immediately, matching the fresh row state and re-enabling the `Ligar agora` action if the user wants to turn it back on manually.
3. Update `src/irrigation/cli.py`'s `schedule list` dispatch to supply valve data to the updated service method.
4. Confirm `node-red/flows.json` needs no direct change beyond the corrected backend field; adjust only if the row-actions logic makes assumptions that no longer hold.
5. Rely on the existing behavior of `ValveService.turn_on` (already resets `manually_turned_off` to `False` on a genuine off-to-on transition) so the next natural schedule start — the same schedule's next occurrence, or a different schedule — is unaffected.

### Performance considerations

- Expected complexity: `O(n)` per controller cycle and per list/status request, where `n` is the number of schedules; looking up a valve by pin is already `O(v)` with a small number of valves and can be memoized per cycle if profiling shows it matters.
- Performance risks: repeatedly re-evaluating the guarded `"Restarted"` branch every poll cycle for a stopped-but-still-persisted-active schedule; this is a cheap no-op check and is already the existing pattern for other branches.
- Mitigation: none required beyond the existing per-cycle schedule/valve lookups.

### Error handling and edge cases

- A schedule interrupted by a real process restart (no manual off) must still recover and turn its valve back on, exactly as `test_reactivates_hardware_for_interrupted_schedule` verifies today.
- Two schedules overlapping on the same valve: turning the valve off manually while both are within their own active windows must stop the valve and must not have either schedule's restart branch turn it back on; a genuinely new schedule occurrence for the same valve that starts afterward (its own `is_running and not schedule.status` transition) is a fresh, legitimate start and is allowed to turn the valve on again.
- A schedule that is disabled while its valve was manually turned off must still resolve through the existing disabled-schedule branch without error.
- Existing valve/schedule records without any manual-off history must default `manually_turned_off` to `False` and behave exactly as before.
- The dashboard must not offer `Desligar agora` on a row whose valve is already off, and must offer `Ligar agora` again once the row is corrected to `Desligada`.

## Test specification

### Unit tests

- [ ] `IrrigationController.run_once` does not turn a valve back on during the `"Restarted"` recovery path when `Valve.manually_turned_off` is `True`.
- [ ] `IrrigationController.run_once` still performs the existing restart recovery when `Valve.manually_turned_off` is `False` (regression for `test_reactivates_hardware_for_interrupted_schedule`).
- [ ] `ScheduleService.list_with_runtime_status` reports `is_running = False` for a schedule whose interval is active but whose valve was manually turned off.

### Integration tests

- [ ] Simulate a manual off during an active automatic schedule, followed by a new `IrrigationController` instance (process-restart simulation) running a cycle: the valve stays off for the remainder of the original interval.
- [ ] After the original interval ends, the same schedule's next natural occurrence turns the valve on normally.
- [ ] `irrigation schedule list` reports `is_running: false` for the affected row immediately after the manual-off CLI command runs, without waiting for the interval to end.
- [ ] Two overlapping schedules sharing a valve: manual off during the overlap stops the valve for both, and neither schedule's restart path turns it back on before either interval ends.

### Regression tests

- [ ] `test_reactivates_hardware_for_interrupted_schedule` and the other existing `IrrigationController` specs in `tests/test_services.py` continue to pass unmodified in intent.
- [ ] `test_schedule_runtime_status_is_specific_to_shared_valve_schedule` and `test_manual_on_valve_does_not_mark_inactive_schedule_as_running` continue to pass.
- [ ] Existing manual valve on/off behavior (`ManualControlService`) remains unchanged.
- [ ] `tests/test_cli.py::test_schedule_list_reports_schedule_specific_running_status` and `tests/test_node_red_flow.py::test_schedule_list_uses_cli_runtime_status_output` continue to pass.

### Test data and fixtures

- Fixed clock/time values (as used throughout `tests/test_services.py`) instead of the real system clock.
- A fixture representing a valve with `manually_turned_off: 1` and `status: 0` while its schedule's `status` is still `1` and its interval is still open, to reproduce the restart-recovery bug.
- The existing shared-valve overlap fixtures (`10:46`/`11:06` on valve 13) reused for the overlap edge case.

## Acceptance criteria

The task is complete when:

- [ ] Turning a valve off while it is on due to an automatic schedule keeps it off for the rest of that schedule's configured duration, even if the controller process restarts in the meantime.
- [ ] A schedule interrupted by a restart without any manual action still recovers and turns its valve back on as before.
- [ ] The schedules dashboard shows `Desligada` (and offers `Ligar agora`) immediately after a manual off, instead of continuing to show `Ligada`.
- [ ] The next legitimate occurrence of a schedule, or a different schedule on the same valve, still turns the valve on normally.
- [ ] Existing behavior remains unchanged outside the defined scope, including manual valve activation and overlap safety.
- [ ] New and changed behavior is covered by specs.
- [ ] Error cases and relevant edge cases are covered.
- [ ] The implementation follows the project's architecture and SOLID principles.
- [ ] The implementation is simple, readable, maintainable, and performant for the expected workload.
- [ ] Formatting, linting, type checks, and the full test suite pass.
- [ ] Documentation or user-facing examples are updated when needed.

## Implementation checklist

- [ ] Confirm the task number and filename.
- [ ] Inspect all files listed in the impact analysis.
- [ ] Reassess the affected files before coding and update this task if needed.
- [ ] Add or update specs before changing controller/service behavior.
- [ ] Implement the smallest coherent change.
- [ ] Verify the existing restart-recovery test still passes for the non-manual-off case.
- [ ] Run focused checks.
- [ ] Run the full validation suite.
- [ ] Validate the implementation against every acceptance criterion.
- [ ] Move the issue to `done` only after implementation and validation pass.

## Notes

- The initial request is in Portuguese; this task is intentionally written in English as required by the task-generation convention.
- `Valve.manually_turned_off` already exists in the domain model and is already set correctly by `ValveService.turn_off`/`turn_on`; it is simply never consulted by the controller or the status projection today, which is the root cause of both symptoms described here.
