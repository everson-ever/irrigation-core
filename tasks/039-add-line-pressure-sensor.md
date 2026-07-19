---
status: backlog
priority: high
type: feature
---

## Title

Monitor irrigation-line pressure and stop on unsafe pressure

## Specification

Add one analog pressure transducer after the pump and expose its configuration
under Configurações > Sensores. Convert the transducer signal to pressure,
display the live value, and stop irrigation when pressure remains below or above
configured safe limits after startup transients have passed.

### Context

Pressure complements flow: low pressure can indicate an unprimed/failed pump,
open leak, or supply problem, while high pressure can indicate an obstruction,
closed path, or failed regulator. Many transducers output more voltage or current
than the Raspberry Pi/ADS1115 can accept directly, so the UI must describe the
logical calibration but not imply electrical compatibility.

### Scope

#### In scope

- Support an ADS1115 analog input with address/channel/gain configuration.
- Configure engineering unit (`bar` or `kPa` with canonical internal storage),
  two-point raw-to-pressure calibration, minimum/maximum safe pressure, startup
  grace, confirmation duration, sampling interval, and stale timeout.
- Show raw ADC value, normalized pressure, health, latest-read time, and a live
  test in the Sensors section.
- Evaluate thresholds only when pump/valve state expects pressure, after startup
  grace, using filtering/confirmation to ignore spikes.
- Stop all active irrigation on confirmed low/high pressure and record distinct
  `pressure_low` / `pressure_high` safety reasons.
- Coordinate with flow alarms so one incident produces a primary reason plus
  related diagnostics instead of repeated shutdown/history entries.
- Reject ADC address/channel conflicts with soil-moisture sensors.

#### Out of scope

- Controlling pump speed, a pressure regulator, or variable-frequency drive.
- Multiple pressure zones or one sensor per valve.
- Supporting 4-20 mA electrically without an appropriate external receiver.
- Predictive maintenance or long-term pressure charts.

## Impact analysis

### Files to inspect

- Task 035 implementation — common sensor configuration/status.
- Task 037 implementation — abnormal-flow stop and incident deduplication.
- Task 038 implementation — ADS1115 resource management and calibration.
- Valve/pump services and controller — expected-pressure runtime state.
- CLI, settings template, flows, documentation, and relevant tests.

### Files to change

- Type-specific sensor models/schema/services — pressure settings and policy.
- Shared ADS1115 adapter/resource validator — pressure input support.
- Controller safety monitor — grace, confirmation, stop, and incident data.
- CLI and Sensors section — pressure form, calibration, test, and status.
- Documentation and tests.

### Files to create

- No new ADC module if task 038 provides a reusable adapter; add only a focused
  pressure policy/calibration component where responsibility is clearer.

### Dependencies and integration points

- Depends on task 035 and should reuse task 038's ADS1115 adapter when available.
- Reuse the shared safety-stop mechanism from tasks 036/037.
- Flow and pressure policies observe the same pump/run lifecycle.

## Technical approach

### Proposed changes

1. Persist strict pressure configuration in an additive type-specific table.
2. Convert raw readings with a two-point linear calibration into one canonical
   unit, then format the selected display unit at the boundary.
3. Apply a small median/moving filter and sustained threshold confirmation.
4. Start threshold evaluation only after pump activation plus startup grace;
   stop evaluating when no pressure is expected.
5. On a confirmed incident, invoke the idempotent shared safety-stop service and
   store pressure, threshold, sensor health, valve/run IDs, and reason.
6. Add guided calibration/status controls to the Sensors section.

### Performance considerations

- Expected complexity: `O(1)` per pressure sample.
- Reuse the ADS1115 connection and aggregate current state; do not persist every
  sample or spawn separate monitoring processes.

### Error handling and edge cases

- Reject equal calibration points, negative pressure ranges, unsafe threshold
  ordering, invalid addresses/channels, and conflicting resources.
- An enabled safety sensor that becomes stale/unreadable while irrigation is
  active raises a fault and follows the same documented fail-safe policy as the
  other critical hydraulic monitors.
- Ignore harmless zero pressure while the pump is off.
- Prevent repeated stop commands/history events while the same incident remains
  active; clear only after a healthy recovery window.
- Preserve the first causal reason when flow and pressure fail simultaneously,
  while attaching the other reading as diagnostic context.

## Test specification

### Unit tests

- [ ] Cover linear conversion, units, filtering, grace/confirmation timers,
  thresholds, staleness, recovery, and configuration validation.
- [ ] Verify incident deduplication and causal-reason preservation.

### Integration tests

- [ ] Inject mock ADC values for normal, low, high, noisy, and disconnected
  states.
- [ ] Verify sustained unsafe pressure stops valves/pump once and records data.
- [ ] Verify pressure and moisture channels cannot collide.
- [ ] Verify UI/CLI calibration and live-test behavior.

### Regression tests

- [ ] Pump-off zero readings never create safety events.
- [ ] Existing irrigation is unchanged with no enabled pressure sensor.

## Acceptance criteria

- [ ] Users can configure, calibrate, enable, disable, and test pressure sensing.
- [ ] Live pressure, raw value, unit, health, and freshness are visible.
- [ ] Confirmed low/high pressure stops irrigation after startup grace.
- [ ] Each incident has one auditable safety event with diagnostic values.
- [ ] ADC conflicts and invalid electrical/calibration assumptions are rejected
  or clearly documented.
- [ ] Full tests and quality checks pass.

## Implementation checklist

- [ ] Implement schema, pressure model, conversion, and validation.
- [ ] Reuse/extend the ADC adapter and resource registry.
- [ ] Integrate idempotent safety monitoring and incident recording.
- [ ] Extend the Sensors UI and synchronize flows.
- [ ] Add tests and electrical/wiring documentation.
- [ ] Validate every acceptance criterion before moving to `done`.

## Notes

- The application must never suggest connecting a nominal 5 V, 0-10 V, or
  4-20 mA transducer directly to Raspberry Pi GPIO or an ADC without the
  required conditioning circuit.

