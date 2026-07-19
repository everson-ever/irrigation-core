---
status: backlog
priority: high
type: feature
---

## Title

Measure water flow and stop irrigation when flow is abnormal

## Specification

Add support for a pulse-output flow sensor installed on the main irrigation
line. Let the user configure and calibrate it from Configurações > Sensores,
show current flow and accumulated volume, associate measured volume with each
irrigation execution, and safely stop the system when an active run has no flow
after a configurable startup grace period.

### Context

The dashboard currently states that consumption estimates are unavailable and
the controller assumes an energized valve means water is moving. A pulse flow
meter can confirm delivery, identify dry running or obstruction, quantify water
use, and reveal unexpected flow when no valve should be open.

### Scope

#### In scope

- Configure physical BOARD pulse pin, electrical active edge, pull mode,
  pulses-per-liter calibration, minimum valid flow, maximum valid flow, startup
  grace period, no-flow confirmation duration, and stale timeout.
- Count pulses in the long-lived controller with a real GPIO adapter and a mock
  pulse source; protect shared state from concurrent callbacks.
- Calculate instantaneous L/min over a stable sampling window and accumulated
  liters with explicit rounding rules.
- Record delivered liters for manual and scheduled irrigation runs without
  writing one SQLite row per pulse.
- Stop active irrigation after confirmed no-flow or excessive-flow conditions,
  and store an actionable safety reason.
- Detect unexpected flow while all valves/pump are off and surface a leak alert;
  do not claim the software can isolate mains water unless a master valve exists.
- Show live L/min, current-run liters, total liters, health, calibration, and a
  resettable maintenance counter in the Sensors section.

#### Out of scope

- One flow sensor per valve/section.
- Billing-grade metering or legal metrology.
- Automatic calibration without a known reference volume.
- Closing a nonexistent master supply valve.
- High-frequency persistence of raw pulses.

## Impact analysis

### Files to inspect

- Task 035 implementation — common sensor configuration/status.
- Task 036 implementation — safety-stop and digital-input lifecycle patterns.
- `src/irrigation/application/services.py` — run start/end and history capture.
- `src/irrigation/infrastructure/gpio.py` — Raspberry Pi GPIO ownership.
- `src/irrigation/domain/models.py` and SQLite history schema — execution data.
- Node-RED schedule/history templates — consumption presentation points.

### Files to change

- Sensor configuration models/schema/services — flow calibration and policy.
- Hardware adapters — edge counting and mock pulse injection.
- Controller/manual/history services — run-scoped volume and safety response.
- SQLite — additive run-measurement and current-counter persistence.
- CLI, Sensors UI, schedule summary, and history display — readings and liters.
- Documentation and tests.

### Files to create

- A focused pulse-counter adapter may be created to isolate callback lifecycle,
  synchronization, and cleanup.

### Dependencies and integration points

- Depends on task 035; reuse task 036's safety-stop abstraction if it exists,
  without creating a second competing shutdown path.
- Integrates with valve/pump runtime state and history execution boundaries.

## Technical approach

### Proposed changes

1. Persist strict flow-sensor configuration and calibration in an additive
   type-specific table.
2. Implement an interrupt/edge-based pulse counter for Raspberry Pi and a
   deterministic mock; convert pulses using `pulses_per_liter`.
3. Maintain a bounded in-memory sampling window and checkpoint aggregate totals
   at controlled intervals and run completion.
4. Attach start/end meter values to each irrigation run so delivered liters are
   reproducible after restart.
5. Evaluate no-flow only after startup grace and for a sustained confirmation
   period; evaluate excessive flow similarly to reject transient spikes.
6. Use the shared safety-stop path and expose alerts/live values through CLI and
   Node-RED.

### Performance considerations

- Pulse callbacks must perform constant-time in-memory increments only.
- Batch/checkpoint writes to limit SD-card wear; never write per pulse.
- Dashboard reads an aggregate snapshot in one request.

### Error handling and edge cases

- Reject zero/negative calibration and thresholds where maximum is not above
  minimum.
- Handle 32-bit counter rollover by using an application-level monotonic
  integer/delta strategy.
- Distinguish sensor disconnection from genuine zero flow as far as the hardware
  permits; both become a visible fault during an expected-flow window.
- Preserve accumulated volume across controller restart without double-counting
  the last checkpoint.
- If the process restarts mid-run, reconcile the persisted baseline and mark
  measurement quality rather than fabricating missing volume.
- A disabled flow sensor does not block irrigation.

## Test specification

### Unit tests

- [ ] Cover pulse conversion, time windows, calibration, rounding, rollover,
  grace/confirmation timers, and threshold validation.
- [ ] Cover run-volume accounting and restart reconciliation.

### Integration tests

- [ ] Inject mock pulses and verify L/min, liters, and history output.
- [ ] Verify confirmed no-flow/excessive-flow stops valves and pump once.
- [ ] Verify unexpected-flow alerts do not issue unsupported actuator commands.
- [ ] Verify UI/CLI calibration and live status.

### Regression tests

- [ ] Existing history remains readable when volume is unavailable.
- [ ] With no enabled flow sensor, run timing and shutdown remain unchanged.

## Acceptance criteria

- [ ] The user can configure, calibrate, enable, disable, and test the meter.
- [ ] Current L/min and accumulated liters are visible and timestamped.
- [ ] Each completed irrigation exposes delivered liters when measurement is
  valid.
- [ ] Confirmed no-flow and excessive-flow conditions stop irrigation safely
  after the configured grace/confirmation windows.
- [ ] Unexpected idle flow raises a clear alert.
- [ ] Pulse handling does not cause per-pulse database writes.
- [ ] Full tests and quality checks pass.

## Implementation checklist

- [ ] Implement schema, model, and calibration validation.
- [ ] Implement real/mock pulse counting and lifecycle cleanup.
- [ ] Integrate volume accounting and safety-stop rules.
- [ ] Extend settings/history UI and synchronize flows.
- [ ] Add tests and update documentation.
- [ ] Validate every acceptance criterion before moving to `done`.

## Notes

- Common meters such as the YF-S201 may use supply/signal levels that are not
  safe for Raspberry Pi GPIO. Require documented level shifting or isolation;
  software configuration cannot make a 5 V signal safe.

