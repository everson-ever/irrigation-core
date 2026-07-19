---
status: backlog
priority: critical
type: feature
---

## Title

Protect irrigation with a configurable reservoir-level sensor

## Specification

Add reservoir-level monitoring as the first hardware safety interlock. Support
one low-level float switch initially, with an optional second high-level float,
configured from Configurações > Sensores. When the configured low-level state is
active, automatic and manual starts must be blocked and an irrigation already
running must be stopped safely so the shared pump cannot run dry.

### Context

The pump is switched whenever a valve turns on. There is currently no water
availability check, so an empty reservoir can leave the pump running dry. Float
switches are digital inputs but may be wired normally open or normally closed;
the active electrical state must therefore be configurable and all inputs must
be 3.3 V-safe.

### Scope

#### In scope

- Add type-specific level configuration: low-level physical BOARD pin,
  low-water active state, pull-up/pull-down mode, debounce duration, freshness
  timeout, and optional high-level pin/state.
- Add a real Raspberry Pi digital-input reader and a deterministic mock reader.
- Display `low`, `available`, and, when a second float exists, `full`, plus
  health and latest-read time.
- Continuously monitor the enabled level sensor from the long-lived scheduler
  process, not from Node-RED polling.
- Block new automatic and manual runs while water is low.
- Stop all active valves and the shared pump when low water is confirmed after
  debouncing; record a safety event with reason `reservoir_low`.
- Expose a read-only live test from the settings panel and explain the result.
- Reject pin conflicts with pump, valves, or other configured digital sensors.

#### Out of scope

- Continuous tank percentage, ultrasonic/distance, pressure-depth, or analog
  probes.
- Automatic reservoir filling or control of an inlet valve.
- Notifications outside the dashboard.
- Bypassing the interlock from the web UI.

## Impact analysis

### Files to inspect

- Task 035 implementation — common sensor contracts and settings UI.
- `src/irrigation/infrastructure/gpio.py` — current output lifecycle and cleanup.
- `src/irrigation/application/services.py` — manual and automatic start/stop
  choke points and shared-pump behavior.
- `src/irrigation/domain/ports.py` — hardware abstraction boundary.
- `src/irrigation/bootstrap.py` and `src/irrigation/config.py` — scheduler
  composition and poll interval.

### Files to change

- Domain/application sensor models and services — level settings and interlock.
- SQLite schema/repositories — additive level settings and safety-event data.
- Raspberry Pi/mock sensor infrastructure — debounced digital readings without
  interfering with valve output cleanup.
- CLI and Configurações sensor form — configuration, status, and test action.
- Controller/manual services — enforce the low-water interlock.
- Documentation and tests — wiring, fail-safe rules, and behavior.

### Files to create

- A dedicated digital-input adapter module is allowed if it avoids mixing input
  monitoring with valve/pump output responsibilities.

### Dependencies and integration points

- Depends on task 035.
- Integrates with `IrrigationController`, `ManualControlService`,
  `ValveService`, and the scheduler lifecycle.
- Must share GPIO numbering/resource validation without invoking global cleanup
  that disrupts active outputs.

## Technical approach

### Proposed changes

1. Persist one enabled reservoir-level policy and its digital connection data.
2. Implement a `ReservoirLevelReader` port with Raspberry Pi and mock adapters.
3. Debounce transitions using the injected clock; do not sleep in request paths.
4. Add a reusable start guard checked immediately before any valve/pump start.
5. Add an emergency-stop path that closes all active valves, then the pump, and
   records the reason without misclassifying it as a normal completion.
6. Surface current state and a live test in the Sensors section.

### Performance considerations

- Expected complexity: `O(1)` per poll and `O(v)` only during emergency stop,
  where `v` is the small number of valves.
- Reuse the scheduler loop or one managed monitor; do not spawn processes or
  threads per dashboard refresh.

### Error handling and edge cases

- Default to a fail-safe policy: an enabled safety sensor that is stale,
  unreadable, or invalid blocks new starts. A running irrigation is stopped only
  after the configured freshness/debounce policy prevents transient false trips.
- A disabled level sensor has no control effect and is clearly shown as
  disabled.
- Normally closed wiring must be supported and recommended because a broken
  wire then becomes detectable as unsafe.
- Simultaneous valve runs must all stop before pump state is considered safe.
- Configuration changes while irrigation is running must be transactional; an
  invalid edit cannot disable an active protection silently.

## Test specification

### Unit tests

- [ ] Cover active-high/active-low, pull mode, debounce, stale readings, and
  low/available/full state mapping.
- [ ] Verify start guards and emergency-stop decisions with a fixed clock.

### Integration tests

- [ ] Verify mock GPIO monitoring blocks manual and automatic starts.
- [ ] Verify low water during a run closes valves/pump and records the event.
- [ ] Verify CLI/UI configuration and live-test results.

### Regression tests

- [ ] With no configured/enabled level sensor, existing irrigation behavior is
  unchanged.
- [ ] GPIO sensor cleanup never changes valve or pump output state.

## Acceptance criteria

- [ ] The user can configure and test low/high float inputs from Sensores.
- [ ] Pin conflicts and unsafe configuration are rejected.
- [ ] Confirmed low water blocks all new irrigation starts.
- [ ] Confirmed low water stops active irrigation and the shared pump.
- [ ] Missing/stale enabled safety readings produce a visible fault and enforce
  the documented fail-safe behavior.
- [ ] Safety events preserve the reason `reservoir_low`.
- [ ] Real hardware is isolated behind a tested port with a mock adapter.
- [ ] Full tests and quality checks pass.

## Implementation checklist

- [ ] Implement additive schema and type-specific validation.
- [ ] Implement reader adapters and scheduler monitoring.
- [ ] Integrate the start guard and emergency stop.
- [ ] Extend the sensor form/status UI and sync flows.
- [ ] Add focused, integration, and regression tests.
- [ ] Update wiring and operating documentation.
- [ ] Validate every acceptance criterion before moving to `done`.

## Notes

- Inputs must never receive 5 V. Electrical level conversion/protection remains
  a physical installation requirement and must be documented in the UI help.

