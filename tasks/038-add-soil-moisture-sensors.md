---
status: backlog
priority: high
type: feature
---

## Title

Use configurable soil-moisture sensors to gate irrigation by section

## Specification

Add one analog soil-moisture sensor per irrigation section through ADS1115 ADC
modules. Let the user associate each probe with a registered valve, calibrate
dry and wet values, and define start/stop moisture thresholds. At a scheduled
start, skip irrigation when the section is already wet enough; while watering,
stop early after the configured wet target remains satisfied for a confirmation
period.

### Context

Schedules currently irrigate for a fixed duration regardless of soil condition.
The Raspberry Pi has no general-purpose analog input, while the hardware guide
already proposes two four-channel ADS1115 devices for six to eight sections.
Raw ADC values vary by probe, soil, installation depth, and cabling, so each
sensor requires field calibration and hysteresis.

### Scope

#### In scope

- Support ADS1115 single-ended channels with configurable I2C address, channel,
  gain/full-scale range, sampling interval, and freshness timeout.
- Configure per-probe dry/wet calibration, start threshold, stop threshold,
  confirmation duration, name, enabled state, and exactly one valve/section.
- Support up to four ADS1115 addresses and prevent duplicate address/channel
  assignments; show addresses explicitly in hexadecimal.
- Convert raw ADC values to bounded 0-100% moisture using the calibration
  direction rather than assuming wet is always numerically higher.
- Add monitor-only and schedule-gating policies. Schedule-gating skips a due run
  when moisture is at or above the start threshold and stops early at the stop
  threshold after confirmation.
- Treat configured duration as a hard maximum; moisture control must never run
  longer than the scheduled/manual timeout.
- Record skip/early-stop decisions with moisture value, timestamp, and reason.
- Show raw value, percentage, health, calibration controls, and a live-test
  action in the Sensors section.

#### Out of scope

- Starting irrigation at arbitrary unscheduled times solely because soil is dry.
- Automatic crop-specific thresholds or agronomic recommendations.
- Long-term moisture charts or predictive models.
- Remote/LoRa probes, SDI-12, 4-20 mA, RS-485, or capacitive-frequency sensors.
- Multiple depths per section in the first version.

## Impact analysis

### Files to inspect

- Task 035 implementation — common configuration and state DTOs.
- Tasks 036/037 implementation — monitor lifecycle and safety events.
- `src/irrigation/application/services.py` — schedule-due logic, delayed start,
  restart restoration, manual control, and history.
- `src/irrigation/domain/models.py` — schedule/valve association.
- `src/irrigation/config.py` and bootstrap — I2C/ADC adapter composition.
- Node-RED settings and history templates — calibration and decision feedback.

### Files to change

- Sensor domain/application layer — calibration and moisture policy.
- SQLite — additive soil-moisture settings and decision-event persistence.
- Infrastructure — real ADS1115/I2C adapter and deterministic mock ADC.
- Automatic controller — pre-start gate and early-stop hook.
- CLI and Configurações > Sensores — conditional analog/calibration form.
- History/dashboard documentation and tests.

### Files to create

- A dedicated ADS1115 adapter module is recommended so I2C details and optional
  dependencies do not enter application code.

### Dependencies and integration points

- Depends on task 035 and registered valves/sections.
- Shares I2C safely with future devices; device addresses/channels are logical
  resources and must be validated centrally.
- Moisture decisions integrate with scheduled irrigation, but reservoir, flow,
  and pressure safety interlocks always take precedence.

## Technical approach

### Proposed changes

1. Add strict per-probe settings and a unique `(adc_address, adc_channel)`
   constraint.
2. Define an `AnalogReader`/ADS1115 port and real/mock adapters with explicit
   error translation.
3. Normalize calibrated raw values with clamping and preserve raw values for
   diagnostics.
4. Add hysteretic decision logic: `start_threshold < stop_threshold`; evaluate
   the start threshold only at a due schedule, then stop only at the wet target
   after confirmation.
5. Store explicit skip/early-stop reasons without creating a fake completed
   irrigation when no valve opened.
6. Add a guided two-point calibration flow: capture current value as dry or wet,
   preview percentage, validate separation, then save.

### Performance considerations

- Expected complexity: `O(s)` per sampling cycle for `s` enabled section
  sensors (normally 1-8).
- Sample sequentially at a modest configurable interval and reuse each ADS1115
  connection; avoid a thread/process per probe and avoid saving every sample.

### Error handling and edge cases

- Reject identical/insufficiently separated dry and wet calibration values,
  invalid I2C address/channel, duplicate section association, and invalid
  threshold ordering.
- An unavailable/stale probe in schedule-gating mode must follow an explicit
  configurable fallback defaulting to the existing timed schedule, while
  raising a visible warning; it must not silently report the soil as dry/wet.
- Manual irrigation remains time-controlled and monitor-only in this version;
  safety interlocks still apply.
- Delayed starts and restored schedules must re-evaluate current moisture before
  energizing a valve.
- Noisy readings require confirmation/median filtering before early stop.

## Test specification

### Unit tests

- [ ] Cover calibration in both raw directions, clamping, thresholds,
  hysteresis, filtering, staleness, and validation.
- [ ] Cover due-run skip, early stop, delayed start, and restart decisions.

### Integration tests

- [ ] Simulate two ADS1115 addresses and multiple channels without collision.
- [ ] Verify wet soil skips a schedule and creates a decision event only.
- [ ] Verify a dry run starts and stops at target or at maximum duration.
- [ ] Verify UI calibration capture and CLI JSON contracts.

### Regression tests

- [ ] Timed schedules behave exactly as before when no moisture policy is
  enabled.
- [ ] Manual irrigation duration and other safety interlocks remain intact.

## Acceptance criteria

- [ ] Users can configure and calibrate one moisture probe per section.
- [ ] Raw and 0-100% readings, health, and freshness are visible.
- [ ] Wet sections are skipped at scheduled start under the gating policy.
- [ ] Active scheduled irrigation stops early at the confirmed wet target and
  never exceeds its configured duration.
- [ ] Skip and early-stop reasons are auditable.
- [ ] Invalid/stale readings follow the documented fallback and show warnings.
- [ ] Real I2C hardware is isolated behind a mockable port.
- [ ] Full tests and quality checks pass.

## Implementation checklist

- [ ] Implement schema, models, calibration, and unique resource validation.
- [ ] Implement real/mock ADS1115 adapter.
- [ ] Integrate schedule gate and early stop.
- [ ] Add calibration/status UI and synchronize flows.
- [ ] Add tests and update hardware/developer documentation.
- [ ] Validate every acceptance criterion before moving to `done`.

## Notes

- Long field cables may make raw analog readings unreliable. Document that the
  first version targets short, protected ADC wiring and that remote/industrial
  interfaces require a later task.

