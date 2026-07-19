---
status: done
priority: high
type: bug
---

# Preserve Restart History Classification and Restore GPIO State

## Metadata

```yaml
status: done
priority: high
type: bug
```

## Title

Classify restarted automatic runs correctly and restore their GPIO state on startup

## Specification

Keep the existing behavior in which every controller restart during an active
automatic watering window creates a separate `Restarted` history record. Make
the dashboard present those records as automatic restarts instead of manual
runs, and guarantee at the software/hardware boundary that a run restored after
a controller or container restart explicitly drives both its valve GPIO and the
shared pump GPIO high before it is treated as operational.

### Context

When the scheduler starts inside an already-running automatic interval,
`IrrigationController` detects the persisted `Schedule.status = 1` while its
process-local `_started_in_this_process` set is empty. It resumes the run with
`HISTORY_MODE_RESTARTED` and intentionally inserts another history row. This is
the desired audit behavior for this task: repeated restarts remain visible as
separate execution records and continue increasing the record count.

The history dashboard currently decides whether a row is automatic by checking
whether the raw mode text contains `"automatic"`. The persisted value
`"Restarted"` does not contain that word, so a restarted automatic run is shown
as `Manual`, increments the manual count, and loses the information that it was
an automatic execution resumed after a restart. This frontend rule also
disagrees with the application rule in `HistoryService.has_active_automatic`,
which treats every mode other than `Manual` as automatic.

The controller already has two relevant restoration mechanisms:

- `ValveService.configure()` configures every valve and pump output low, then
  calls the GPIO adapter for each valve whose persisted `Valve.status` is true.
- The restarted branch calls `ValveService.turn_on(..., force_hardware=True)`,
  which writes to the GPIO adapter even when the database already says the
  valve is on.

The restart behavior must be made explicit and protected by regression tests.
After a fresh controller starts during a legitimate active run, both the valve
pin and pump pin must be high, the schedule and valve must remain persisted as
running, and a separate `Restarted` history row must be recorded. A successful
software state transition must not rely only on the persisted status flag.

In dashboard terminology, `Ativo` means that an automatic schedule is enabled;
it does **not** mean that watering must be happening at that moment. The hardware
guarantee in this task applies when the UI reports `Regando agora` / a running
status, not merely when a future schedule is enabled.

### Scope

#### In scope

- Preserve one separate `Restarted` history record for every controller restart
  that legitimately resumes an automatic run during its active interval.
- Replace substring-based history-mode detection with an explicit mode
  classification that mirrors the backend semantics: only `Manual` is manual;
  `Automatic`, `Automatic: started after scheduled time`, and `Restarted` are
  automatic-origin modes.
- Display `Restarted` rows with a distinct Portuguese label that communicates
  both origin and event, such as `Automático (reiniciado)`, rather than `Manual`
  or a generic `Automático` label.
- Count `Restarted` rows under `Automáticos`, never under `Manuais`, while still
  counting every restart as its own execution/record.
- Make restarted rows visually distinguishable in the mode badge without
  presenting them as manual watering.
- Keep history search useful for restarted rows by matching the user-facing
  restart label as well as the persisted raw mode.
- Verify that controller startup inside an active automatic interval explicitly
  drives the valve GPIO and the pump GPIO high, including when their persisted
  status is already true.
- Verify that schedule-list/UI running state remains consistent with the
  restored persisted valve state after successful GPIO restoration.
- Preserve manual-stop protection: a run deliberately stopped by the user must
  not be restored merely because the controller restarts.
- Define and test failure behavior at the GPIO adapter boundary so a failed
  hardware activation is not silently treated as a successful restoration.

#### Out of scope

- Deduplicating, merging, or updating history rows across restarts.
- Preventing the history record/execution counters from increasing after a
  restart; the additional record is intentionally retained.
- Changing the persisted raw mode value from `Restarted` or migrating existing
  history rows.
- Recalculating `Tempo irrigado` to merge overlapping original/restart
  intervals; it retains the existing per-record summation semantics.
- Treating every enabled (`Ativo`) schedule as physically watering. GPIO output
  is required only for a schedule that is actually running (`Regando agora`).
- Adding physical electrical feedback, flow sensors, or GPIO readback hardware.
  The guarantee is that successful restoration issues the GPIO-high commands
  and that adapter failures propagate; confirming water flow requires separate
  hardware instrumentation.
- Changing normal manual activation, manual stop, schedule CRUD, timing,
  weekdays, or history-retention behavior.

## Impact analysis

### Files to inspect

- `src/irrigation/application/services.py` — inspect history mode constants,
  `HistoryService.has_active_automatic`, `ValveService.configure`/`turn_on`, and
  the `IrrigationController` restart path to preserve backend classification and
  confirm hardware restoration ordering.
- `src/irrigation/infrastructure/gpio.py` — inspect Raspberry Pi and mock GPIO
  adapters; both valve and pump outputs must be driven high by `turn_on`.
- `src/irrigation/domain/models.py` — inspect persisted `Schedule.status`,
  `Schedule.enabled`, and `Valve.status` semantics so enabled and running states
  remain distinct.
- `src/irrigation/cli.py` — inspect the schedule-list runtime projection used by
  Node-RED after restoration.
- `node-red/templates/historico.html` — inspect `isAutomatic`,
  `automaticCount`, `manualCount`, `modeLabel`, badge classes, and history
  search matching; this is where `Restarted` is currently misclassified.
- `node-red/templates/agendamentos.html` — inspect the distinction between
  `Ativo` and `Regando agora` and how schedule status drives the UI.
- `node-red/flows.json` — inspect the mirrored history and schedule
  `ui_template` formats that must remain synchronized with their source files.
- `scripts/sync_flows_templates.py` — inspect the canonical template-to-flow
  synchronization path before updating `flows.json`.
- `tests/test_services.py` — inspect controller restart, manual-stop,
  `RecordingMockGPIO`, runtime-status, and pump-state coverage.
- `tests/test_node_red_flow.py` — inspect template synchronization and static UI
  contract tests; add behavior-contract assertions for restarted mode mapping.
- `docs/DEVELOPER_GUIDE.md` — inspect documented history modes, restart state
  transitions, runtime-status fields, and GPIO startup sequence.

### Files to change

- `node-red/templates/historico.html` — implement explicit history-mode
  classification, a restarted automatic label/style, correct automatic/manual
  counts, and restart-label search support.
- `node-red/flows.json` — synchronize the updated history template into the
  corresponding Node-RED `ui_template` node using the project sync script.
- `tests/test_node_red_flow.py` — cover explicit `Restarted` classification,
  label, counts, search text, badge behavior, and template synchronization.
- `tests/test_services.py` — strengthen restart recovery tests to assert valve
  GPIO, pump GPIO, persisted schedule/valve state, separate history insertion,
  repeated restart behavior, manual-stop safety, and adapter failure behavior.
- `src/irrigation/application/services.py` — change only if the strengthened
  tests expose a gap in startup reconciliation, GPIO activation ordering, or
  error propagation; keep the existing focused controller/service boundaries.
- `src/irrigation/infrastructure/gpio.py` — change only if adapter-level tests
  expose that the valve and pump are not both driven high or failures are
  swallowed.
- `docs/DEVELOPER_GUIDE.md` — document that `Restarted` is an automatic-origin
  audit event, remains a separate record, and reasserts hardware state.

### Files to create

- None expected beyond this task specification.

### Dependencies and integration points

- `HISTORY_MODE_MANUAL`, `HISTORY_MODE_AUTOMATIC`,
  `HISTORY_MODE_AUTOMATIC_LATE_START`, and `HISTORY_MODE_RESTARTED` are the
  canonical persisted mode values.
- `HistoryService.has_active_automatic` is the backend classification reference:
  `Manual` is excluded and restart/late-start modes are automatic-origin runs.
- `IrrigationController.run()` is the daemon startup entry point and must
  configure/reconcile GPIO before publishing a healthy controller heartbeat.
- `ValveService.configure()` and `ValveService.turn_on(force_hardware=True)`
  are the service boundaries responsible for translating persisted state into
  GPIO operations.
- `GPIORaspberryPi.turn_on()` is the production hardware boundary; it writes
  `HIGH` to both the selected valve and pump pins.
- `ScheduleService.list_with_runtime_status` and `irrigation schedule list`
  provide the state consumed by the schedules dashboard.
- `node-red/templates/*.html` are canonical UI sources and must be mirrored in
  `node-red/flows.json` through `scripts/sync_flows_templates.py`.

## Technical approach

### Design principles

- Keep each class and function focused on one responsibility.
- Depend on abstractions at architectural boundaries.
- Keep domain rules independent from infrastructure details.
- Prefer small, explicit interfaces and simple data flows.
- Avoid speculative abstractions, duplicated logic, and unrelated changes.

### Proposed changes

1. In `historico.html`, introduce one explicit mode-classification function
   that normalizes the raw persisted mode and returns a stable category such as
   `manual`, `automatic`, or `restarted`. Do not infer category using
   `indexOf("automatic")`.
2. Derive all UI behavior from that single classification: `isAutomatic`,
   automatic/manual totals, badge CSS, and `modeLabel`. Map `Restarted` to a
   clear label such as `Automático (reiniciado)` and give it a distinct restart
   badge while retaining automatic semantics.
3. Include the computed user-facing label in `visibleHistory()` search text so
   searches such as `reiniciado` find restarted records, while preserving
   searches by the raw stored value.
4. Synchronize the canonical history template into `node-red/flows.json` with
   `scripts/sync_flows_templates.py`; do not hand-maintain divergent copies.
5. Extend the controller restart test to construct a fresh GPIO adapter whose
   pins begin low while the database contains an active automatic schedule and
   valve. Run the actual startup reconciliation path (or the smallest
   representative `configure` + controller cycle) and assert:
   - the valve pin is high;
   - the shared pump pin is high;
   - the schedule and valve remain persisted as running;
   - a new `Restarted` row is inserted; and
   - the schedule-list projection reports the run consistently.
6. Simulate a second fresh controller/GPIO instance in the same active interval
   and assert another separate `Restarted` row is added and hardware is driven
   high again. This preserves the requested audit behavior while proving each
   restart performs hardware reconciliation rather than trusting memory or the
   database flag alone.
7. Retain the explicit `force_hardware=True` restoration semantics. If tests
   reveal duplicate, contradictory, or incorrectly ordered GPIO operations,
   make the smallest service-layer adjustment that ensures configuration and
   restoration are idempotent and finish with both pins high.
8. Add an adapter-failure test using a GPIO fake that raises `HardwareError` on
   activation. The exception must propagate out of startup/recovery, no healthy
   heartbeat may be published afterward, and no successful `Restarted` history
   row may be committed for an activation that did not complete. If current
   ordering violates this rule, reorder the smallest possible operations so
   hardware activation succeeds before recording successful restoration.
9. Keep the existing manual-stop restart regression intact: when
   `manually_turned_off` protects an active interval, the controller must not
   drive either GPIO high or add a `Restarted` row.

### Performance considerations

- Expected complexity: `O(h)` for rendering/counting/filtering the bounded
  history result and `O(v + s)` for startup reconciliation, where `h`, `v`, and
  `s` are the returned history rows, configured valves, and schedules.
- Performance risks: Angular template helpers can be evaluated repeatedly; do
  not add database/network calls or nested full-history scans inside a
  per-record classifier. GPIO may receive more than one idempotent `HIGH` write
  during startup under the current configure-plus-force sequence.
- Mitigation: keep classification pure and constant-time per row; reuse one
  normalized mapping. Prefer correctness and explicit GPIO reassertion over
  removing harmless idempotent writes unless tests show a real issue.

### Error handling and edge cases

- Existing and new `Restarted` rows must be classified identically without a
  data migration.
- Unknown future mode values must not silently appear as manual. Use a safe
  fallback label/category and cover it with a focused UI contract test.
- Mode comparisons should tolerate surrounding whitespace and case differences
  at the presentation boundary without changing stored values.
- `Automatic: started after scheduled time` remains automatic and retains its
  current behavior; this task must not accidentally collapse it into manual.
- Multiple restarts in the same active interval each create and display a
  separate restarted automatic record.
- A manual run remains `Manual`, increments only the manual count, and retains
  the manual badge.
- An enabled schedule outside its active time remains `Ativo` in the UI while
  valve and pump GPIO stay low.
- A restarted run with persisted running state starts from freshly configured
  low outputs and ends with both the selected valve and pump high.
- A manually stopped automatic interval remains off across restart and does not
  create a successful restart record.
- Hardware activation failure must be observable through the existing error /
  process-health boundary and must not be represented as a successful resumed
  execution.
- Shared-pump behavior with more than one active valve must remain unchanged;
  restoring one run must not turn another active valve off.

## Test specification

### Unit tests

- [x] History UI mode classification maps `Manual` to manual,
  `Automatic`/late-start to automatic, and `Restarted` to restarted automatic.
- [x] A `Restarted` row renders a distinct label such as
  `Automático (reiniciado)` and uses a non-manual badge class.
- [x] Automatic/manual totals include `Restarted` only in the automatic total.
- [x] History search matches both `Restarted` and the Portuguese restart label.
- [x] Unknown history modes do not silently increment the manual count.
- [x] `ValveService.configure()` restores a persisted-on valve by driving both
  its valve pin and the shared pump pin high.
- [x] `ValveService.turn_on(..., force_hardware=True)` calls the GPIO adapter
  even when `Valve.status` is already true.
- [x] A GPIO activation failure propagates as `HardwareError` and is not
  converted into a successful restoration result.

### Integration tests

- [x] Starting a fresh controller during an active automatic run restores both
  valve and pump GPIO from an initially-low adapter state.
- [x] Successful restoration leaves `Schedule.status`, `Valve.status`, and the
  schedule-list runtime projection consistent with `Regando agora`.
- [x] Each fresh controller restart within the same active interval adds one
  separate `Restarted` history row and reasserts both GPIO outputs high.
- [x] If GPIO activation fails during restart, the controller does not publish a
  post-restoration healthy heartbeat or add a successful `Restarted` row.
- [x] Synchronizing the history template produces a `flows.json` format field
  byte-for-byte equal to `node-red/templates/historico.html`.

### Regression tests

- [x] `test_reactivates_hardware_for_interrupted_schedule` is strengthened and
  continues to verify legitimate interrupted-run recovery.
- [x] Manual-stop restart tests continue to prove that deliberate user shutdown
  is not overridden and does not create an extra restart row.
- [x] Normal automatic, late-start automatic, and manual rows retain their
  correct history labels and counts.
- [x] An enabled schedule outside its execution window does not activate GPIO.
- [x] Shared-pump and overlapping-schedule controller tests remain unchanged in
  behavior.
- [x] Existing history filtering, pagination, retention, and duration totals
  remain unchanged outside the defined classification fix.

### Test data and fixtures

- Reuse `FakeClock` and `RecordingMockGPIO` from `tests/test_services.py`.
- Use a persisted schedule with `status = 1`, `enabled = 1`, and a current time
  inside its interval, plus a matching valve with `status = 1`.
- Recreate `ValveService`/`IrrigationController` with a fresh mock GPIO instance
  for each simulated process restart so hardware state starts low while the
  SQLite state survives.
- Include history rows for `Manual`, `Automatic`,
  `Automatic: started after scheduled time`, `Restarted`, and an unknown mode in
  UI classification fixtures.
- Use a failing GPIO fake that raises `HardwareError` from `turn_on` to verify
  failure ordering and health/history behavior.

## Acceptance criteria

The task is complete when:

- [x] Every controller restart during a legitimate active automatic run remains
  a separate `Restarted` history record.
- [x] `Restarted` records are displayed as `Automático (reiniciado)` (or an
  equivalently explicit approved label), never as `Manual`.
- [x] `Restarted` records increment the automatic count and do not increment the
  manual count.
- [x] Restarted records are visually distinguishable and searchable by their
  user-facing restart terminology.
- [x] After a successful controller restart inside an active automatic interval,
  the selected valve GPIO and shared pump GPIO are both high.
- [x] A schedule shown as `Regando agora` after restoration has consistent
  running schedule/valve state and has completed the GPIO activation call.
- [x] Merely showing an enabled schedule as `Ativo` outside its time window does
  not activate the hardware.
- [x] A hardware activation failure is propagated and is not followed by a
  successful restart history record or healthy post-restoration heartbeat.
- [x] A deliberate manual stop is still respected across controller restarts.
- [x] Existing behavior remains unchanged outside the defined scope.
- [x] New and changed behavior is covered by specs.
- [x] Error cases and relevant edge cases are covered.
- [x] The implementation follows the project's architecture and SOLID principles.
- [x] The implementation is simple, readable, maintainable, and performant for the expected workload.
- [x] Formatting, linting, available checks, and the full test suite pass.
- [x] Documentation or user-facing examples are updated when needed.

## Implementation checklist

- [x] Confirm the task number and filename.
- [x] Inspect all files listed in the impact analysis.
- [x] Reassess the affected files before coding and update this task if needed.
- [x] Add or update history classification and restart/GPIO specs before changing
  production behavior.
- [x] Implement the smallest coherent change.
- [x] Synchronize canonical Node-RED templates into `flows.json`.
- [x] Run focused history UI and controller/GPIO checks.
- [x] Run the full validation suite.
- [x] Validate the implementation against every acceptance criterion.
- [x] Move the issue to `done` only after implementation and validation pass.

## Notes

- Decision: preserve `Restarted` as a separate persisted audit record. This task
  corrects its origin/classification and hardware guarantee; it does not dedupe
  executions.
- Decision: use an explicit mode mapping in the dashboard. Substring matching is
  the root cause of the current `Restarted` -> `Manual` misclassification and
  would remain fragile for future modes.
- Decision: the clearest default label is `Automático (reiniciado)`, because it
  communicates both the original automatic source and the restart event.
- The UI cannot prove electrical continuity or water flow without a readback
  sensor. Within current architecture, “hardware activated” means the production
  adapter successfully writes `HIGH` to both GPIO outputs; failures must remain
  observable and must prevent a successful restoration record.
