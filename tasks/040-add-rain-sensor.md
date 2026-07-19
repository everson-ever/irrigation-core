---
status: backlog
priority: high
type: feature
---

## Title

Suspend scheduled irrigation with a configurable rain sensor

## Specification

Add one weather-resistant digital rain sensor and configure it from
Configurações > Sensores. While rain is confirmed, prevent new scheduled
irrigation and optionally stop a currently running automatic schedule. After the
sensor becomes dry, keep schedules suspended for a configurable cooldown so
recent rainfall can reduce unnecessary watering.

### Context

The current controller follows weekly times regardless of rainfall. A digital
wet/dry input is sufficient for the first version, but exposed resistive rain
boards can corrode and bounce, and a wet sensor does not quantify rainfall.
Debounce, active-state configuration, freshness, and transparent suspension
reasons are required.

### Scope

#### In scope

- Configure one digital sensor using physical BOARD pin, wet active state,
  pull-up/pull-down, wet/dry debounce, sampling interval, stale timeout, dry
  cooldown duration, and `stop_running_automatic` policy.
- Add real Raspberry Pi and mock digital readers using the shared input
  lifecycle/resource validation from the level task.
- Show `dry`, `raining`, `cooldown`, health, transition time, and suspension
  expiry in the Sensors section.
- Prevent new automatic schedule starts while raining or in cooldown.
- Re-evaluate delayed and restored automatic runs against the rain policy.
- Optionally stop only automatic irrigation already in progress after wet-state
  confirmation; preserve manual irrigation unless another safety interlock
  blocks it.
- Record schedule skips/stops with rain state and reason without fabricating a
  normal completed run.
- Reject GPIO conflicts with valves, pump, level, flow, and other digital
  sensors.

#### Out of scope

- Rainfall quantity, tipping-bucket accumulation, weather forecasts, or
  evapotranspiration calculations.
- Automatically changing future schedule duration based on rainfall amount.
- BME280 integration.
- Push, email, or SMS weather notifications.

## Impact analysis

### Files to inspect

- Task 035 implementation — common configuration/status and UI.
- Task 036 implementation — reusable digital input/debounce adapter.
- `src/irrigation/application/services.py` — scheduled, delayed, restored, and
  manual irrigation paths.
- History/safety decision storage introduced by prior sensor tasks.
- CLI, Node-RED settings template/flows, and tests.

### Files to change

- Type-specific sensor models/schema/services — rain policy and cooldown.
- Digital-input infrastructure/mock — rain registration and lifecycle.
- Automatic controller — start gate, restored-run check, and optional stop.
- CLI and Sensores UI — conditional configuration, test, and status.
- Documentation and tests.

### Files to create

- No new GPIO adapter if task 036 provides the required generic digital-input
  implementation; add only a focused rain-policy component if needed.

### Dependencies and integration points

- Depends on task 035 and should reuse task 036's digital-input infrastructure.
- Rain is an optimization policy, not a pump-protection interlock; reservoir,
  flow, and pressure safety always take precedence.
- Integrates only with automatic schedule decisions by default.

## Technical approach

### Proposed changes

1. Persist rain connection/policy fields in an additive type-specific table.
2. Map active-high/active-low digital input to wet/dry after sustained debounce.
3. Persist the last confirmed wet/dry transition needed to preserve cooldown
   across controller restarts.
4. Add an automatic-start guard returning a structured suspension reason and
   expiry; check it for normal, delayed, and restored runs.
5. If configured, stop active automatic irrigation idempotently on confirmed
   rain, while leaving manual runs untouched.
6. Display live state/cooldown and provide a clear dry/wet test in the settings
   panel.

### Performance considerations

- Expected complexity: `O(1)` per poll/start decision.
- Reuse the managed digital monitor and persist only confirmed transitions, not
  every dry sample.

### Error handling and edge cases

- Reject invalid pins, pull modes, negative cooldown, and conflicting resources.
- An enabled but stale/unreadable rain sensor raises a visible warning. Because
  it is an optimization rather than a hydraulic safety device, default fallback
  is to preserve the existing schedule; make the fallback explicit and
  auditable rather than silently assuming dry.
- A short wet pulse below debounce must not stop or suspend irrigation.
- Cooldown survives service restart and expires according to the injected
  clock, not process uptime.
- Manual runs remain allowed during rain by default and the UI must state this.
- Repeated schedule polls during rain create at most one decision event per due
  occurrence, not duplicate history noise.

## Test specification

### Unit tests

- [ ] Cover active-high/active-low, debounce, cooldown, stale fallback,
  transition persistence, restart, and resource validation.
- [ ] Cover normal, delayed, restored, and already-running automatic decisions.

### Integration tests

- [ ] Verify confirmed rain skips scheduled starts and exposes the reason.
- [ ] Verify cooldown remains active after dry transition and service restart.
- [ ] Verify optional stop affects automatic but not manual irrigation.
- [ ] Verify CLI/UI configuration and live-test output.

### Regression tests

- [ ] Existing schedules run unchanged without an enabled rain sensor.
- [ ] Other safety interlocks retain priority and manual control remains intact.

## Acceptance criteria

- [ ] Users can configure, enable, disable, and test one rain sensor.
- [ ] Live rain/cooldown state, freshness, transitions, and expiry are visible.
- [ ] Automatic starts are suspended during confirmed rain and cooldown.
- [ ] Delayed/restored runs re-check rain before valve activation.
- [ ] Optional stop affects active automatic runs only.
- [ ] Stale/unavailable behavior is visible, documented, and auditable.
- [ ] GPIO conflicts are rejected consistently.
- [ ] Full tests and quality checks pass.

## Implementation checklist

- [ ] Implement schema, model, policy, and transition persistence.
- [ ] Reuse/extend digital readers and resource validation.
- [ ] Integrate automatic start/stop decisions.
- [ ] Extend the Sensors UI and synchronize flows.
- [ ] Add tests and update weatherproof wiring documentation.
- [ ] Validate every acceptance criterion before moving to `done`.

## Notes

- Recommend a weatherproof optical/contact output or tipping mechanism used only
  as wet/dry in this version. Exposed resistive PCB modules are unsuitable for
  reliable permanent outdoor installation.

