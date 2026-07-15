# Fix Shared Valve Schedule Status

## Metadata

```yaml
status: done
priority: high
type: bug
```

## Title

Show running status only for the active schedule instance

## Specification

### Context

The schedules dashboard currently shows the section status as `Ligada` for every schedule that uses a valve that is currently on. This is misleading when two or more schedules share the same valve.

Example observed behavior:

- The schedule `11:06`, `4 min`, `Jardim lateral esquerda (Válvula 13)` starts at the correct time and turns valve 13 on.
- Another schedule for the same valve, such as `10:46`, `2 min`, `Jardim lateral esquerda (Válvula 13)`, is outside its active time window.
- Because both schedules use valve 13, the older schedule is also displayed as `Ligada`, even though that schedule is not the one currently running.

The UI must distinguish between the physical valve state and the execution state of each schedule row. A valve can be on while only one matching schedule row is currently active.

### Scope

#### In scope

- Correct the schedules list so the `Status da seção` column represents whether that specific schedule is currently running.
- Keep the valve physically on when any valid active schedule for that valve is running.
- Preserve manual valve control behavior.
- Preserve overlap safety so one schedule ending does not turn off a valve still required by another active schedule.
- Ensure action buttons match the corrected row state:
  - The active schedule row may show `Desligar agora`.
  - Inactive schedule rows that share the same active valve must not appear as running only because the valve is on.
- Add regression coverage for multiple schedules sharing the same valve.

#### Out of scope

- Redesigning the schedules table layout.
- Changing the persisted schedule format unless inspection proves the current format cannot represent the required state safely.
- Preventing users from creating multiple schedules for the same valve.
- Changing schedule conflict validation rules.
- Changing manual activation screens beyond preserving their existing behavior.

## Impact analysis

### Files to inspect

- `src/irrigation/domain/models.py` — schedule interval logic, status fields, serialization, and how running state is represented.
- `src/irrigation/application/services.py` — automatic controller logic that starts, stops, and reports schedules and valves.
- `src/irrigation/cli.py` — list/status command output consumed by Node-RED.
- `src/irrigation/infrastructure/json_repository.py` — persistence behavior for schedules and valves.
- `node-red/flows.json` — schedules table mapping, status badge rendering, and action button selection.
- `tests/test_models.py` — existing schedule interval and status behavior specs.
- `tests/test_services.py` — controller specs for active schedules, valves, and overlapping execution.
- `tests/test_cli.py` — CLI output contract for schedule listing/status data.
- `tests/test_node_red_flow.py` — dashboard flow assertions for schedule rows and button rendering.
- `data/schedules.json` — representative persisted schedule records, including schedules sharing the same valve.
- `data/valves.json` — current valve state format used by dashboard status rendering.

### Files to change

- `src/irrigation/application/services.py` — report schedule-row running state independently from raw valve state and keep valve stop logic safe for overlaps.
- `src/irrigation/cli.py` — expose enough schedule-specific status information for the dashboard to render each row correctly.
- `node-red/flows.json` — render `Status da seção` and row actions from schedule-specific running state instead of only the valve state.
- `tests/test_services.py` — add regression tests for shared-valve schedules where only the current schedule is active.
- `tests/test_cli.py` — add or update output-contract tests for schedule-specific status.
- `tests/test_node_red_flow.py` — verify dashboard flow uses schedule-specific status data for badges and action buttons.

### Files to create

- None expected.

### Dependencies and integration points

- The automatic controller evaluates schedule time windows and sends GPIO commands through the valve abstraction.
- The schedules dashboard receives schedule data through Node-RED flow nodes and CLI command output.
- The same valve may be used by multiple schedules with different start times and durations.
- Manual valve activation may also turn a valve on independently of schedule execution; the schedule table must not incorrectly mark unrelated schedule rows as running because of manual activation.

## Technical approach

### Design principles

- Keep each class and function focused on one responsibility.
- Depend on abstractions at architectural boundaries.
- Keep domain rules independent from infrastructure details.
- Prefer small, explicit interfaces and simple data flows.
- Avoid speculative abstractions, duplicated logic, and unrelated changes.

### Proposed changes

1. Trace how the schedules table currently determines `Ligada` versus `Desligada`, identifying whether it derives row status from valve state, persisted schedule status, interval checks, or mixed data.
2. Define a schedule-specific runtime state for list output, such as `is_running`, based on whether the schedule itself is currently inside its active interval and enabled.
3. Keep physical valve state as separate data, used only to represent the actual valve output and to protect overlap/manual-control behavior.
4. Update automatic execution and status reporting so a valve being on does not cause every schedule using that valve to be reported as running.
5. Update the Node-RED schedule row rendering to use the schedule-specific runtime state for the status badge and primary action button.
6. Preserve the existing safety rule that a valve must remain on while at least one active schedule or valid manual activation still requires it.
7. Add regression tests covering two schedules for valve 13 where only the `11:06` schedule is active and the earlier `10:46` schedule remains inactive in the list.

### Performance considerations

- Expected complexity: `O(n)` per schedule-list/status refresh, where `n` is the number of schedules.
- Performance risks: recomputing valve usage repeatedly for every row if overlap detection is implemented with nested scans.
- Mitigation: calculate active schedules once per refresh/controller cycle and derive active valve references from that set.

### Error handling and edge cases

- If two schedules for the same valve overlap, both schedule rows may be shown as running only while each row is within its own active interval.
- If one overlapping schedule ends while another remains active, the valve must stay on.
- If a valve is manually turned on, schedules using that valve must not be shown as running unless their own schedule interval is active.
- If a schedule is disabled, it must not be shown as running even when its valve is on.
- If schedule status persisted from a previous run is stale, list/status output must not trust it blindly over the current schedule interval and controller state.
- Midnight-crossing schedules must still report running correctly across the date boundary.
- The `Desligar agora` action must not create a state where stopping one schedule turns off a valve still needed by another active schedule.

## Test specification

### Unit tests

- [x] A schedule reports active only during its own configured time interval.
- [x] Two schedules with the same valve can have different active states at the same current time.
- [x] A disabled schedule is not active even if its valve is on.
- [x] A midnight-crossing schedule still reports active across midnight when appropriate.

### Integration tests

- [x] Given two schedules for valve 13 at `10:46` for `2 min` and `11:06` for `4 min`, when the current time is inside the `11:06` interval only, only the `11:06` schedule is reported as running.
- [x] When valve 13 is on manually and no schedule for valve 13 is inside its active interval, no schedule row for valve 13 is reported as running.
- [x] When two schedules for the same valve overlap, ending one schedule does not turn the valve off while the other schedule remains active.
- [x] The CLI schedule list/status output contains schedule-specific running data that Node-RED can consume without inferring row state only from valve state.
- [x] The Node-RED schedules table renders `Ligada` only for rows whose schedule-specific running state is true.
- [x] The Node-RED schedules table renders `Desligada` for inactive rows even when another active schedule uses the same valve.

### Regression tests

- [x] Existing single-schedule valve status behavior remains correct.
- [x] Existing manual `Ligar agora` and `Desligar agora` actions still work.
- [x] Existing schedule creation, editing, and deletion behavior remains unchanged.
- [x] Existing overlap protection remains correct for schedules sharing the same valve.
- [x] Existing history logging remains unchanged unless it currently records incorrect schedule identity.

### Test data and fixtures

- Use fixed times instead of the real system clock:
  - `10:46`, duration `2 min`, valve 13.
  - `11:06`, duration `4 min`, valve 13.
  - A current time inside only the `11:06` interval.
- Include at least one manual-on valve fixture to prove manual valve state does not mark unrelated schedules as running.
- Include one overlapping shared-valve fixture to verify valve shutdown safety.

## Acceptance criteria

The task is complete when:

- [x] The schedules table shows `Ligada` only for the schedule row that is currently running.
- [x] A schedule row is not shown as `Ligada` merely because another schedule using the same valve is running.
- [x] A schedule row is not shown as `Ligada` merely because the valve was manually turned on.
- [x] The action buttons are consistent with the corrected row state.
- [x] Physical valve state remains correct: a valve stays on while any active schedule or valid manual activation requires it.
- [x] The shared-valve example with `10:46`, `2 min`, valve 13 and `11:06`, `4 min`, valve 13 is covered by regression tests.
- [x] Existing behavior remains unchanged outside the defined scope.
- [x] New and changed behavior is covered by specs.
- [x] Error cases and relevant edge cases are covered.
- [x] The implementation follows the project's architecture and SOLID principles.
- [x] The implementation is simple, readable, maintainable, and performant for the expected workload.
- [x] Formatting, linting, type checks, and the full test suite pass.
- [x] Documentation or user-facing examples are updated when needed.

## Implementation checklist

- [x] Confirm the task number and filename.
- [x] Inspect all files listed in the impact analysis.
- [x] Reassess the affected files before coding and update this task if needed.
- [x] Identify whether the wrong UI status comes from Node-RED row mapping, CLI output, service state, or stale persisted schedule status.
- [x] Add regression tests for shared-valve schedules before changing behavior.
- [x] Implement the smallest coherent change.
- [x] Add or update specs.
- [x] Run focused checks.
- [x] Run the full validation suite.
- [x] Validate the implementation against every acceptance criterion.
- [x] Move the issue to `done` only after implementation and validation pass.

## Notes

- The initial request is in Portuguese; this task is intentionally written in English as required by the task-generation convention.
- The reported UI issue is treated as a state-modeling bug: valve state and schedule execution state are related but not equivalent.
