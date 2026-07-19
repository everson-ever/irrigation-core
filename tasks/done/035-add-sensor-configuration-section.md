---
status: done
priority: high
type: feature
---

## Title

Add a Sensors section to the settings dashboard

## Specification

Create the shared sensor-configuration foundation and add a **Sensores** section
to the Configurações page. The user must be able to register, edit, enable,
disable, inspect, and remove sensor configurations without editing files or
running shell commands. This task provides the common configuration and status
contract used by the reservoir-level, flow, soil-moisture, line-pressure, and
rain sensor tasks; it does not implement their irrigation rules or real hardware
readers.

### Context

The application currently persists schedules, valves, settings, and history in
SQLite, exposes them through application services and a structured stdin CLI,
and lets Node-RED render settings for passwords, valve sections, and history.
`docs/COMPONENTS_GUIDE.md` describes sensors, but no sensor domain model, port,
repository, CLI command, or dashboard integration exists. GPIO uses physical
`GPIO.BOARD` numbering, while some diagrams use BCM names, so the UI and API
must consistently identify physical pins and reject ambiguous values.

### Scope

#### In scope

- Define the supported sensor kinds: `reservoir_level`, `flow`,
  `soil_moisture`, `line_pressure`, and `rain`.
- Persist common sensor identity and lifecycle fields: name, kind, enabled
  state, optional section/valve association, and timestamps.
- Persist a current-state snapshot per sensor: health (`unknown`, `ok`,
  `warning`, `fault`, `stale`), latest normalized value/unit, raw value,
  latest-read time, and an actionable error message.
- Add application services and a structured `sensor` CLI contract for list,
  get, add, update, enable/disable, delete, and status operations.
- Add **Sensores** as section 04 in
  `node-red/templates/configuracoes.html`, with a responsive sensor list,
  add/edit form, enabled toggle, health/last-read display, and delete
  confirmation.
- Let each sensor-specific task contribute its own connection and calibration
  fields to the common API and conditional form.
- Validate names, supported kinds, existing section references, and deletion
  behavior in the application layer rather than trusting Node-RED.
- Document that dashboard configuration does not replace physical wiring and
  that real-hardware validation becomes available only after the corresponding
  sensor driver is implemented.

#### Out of scope

- Reading physical sensors or changing irrigation decisions.
- Implementing type-specific thresholds, calibration, alarms, or fail-safe
  behavior; those belong to tasks 036-040.
- Long-term storage or charting of every sensor sample.
- Automatic discovery of GPIO, I2C, ADC, or remote sensors.
- BME280, soil-temperature, pump-current, pH, EC, weather forecast, LoRa, or
  remote ESP32 support.

## Impact analysis

### Files to inspect

- `src/irrigation/domain/models.py` — validation and serialization patterns.
- `src/irrigation/domain/ports.py` — dependency-inversion boundary.
- `src/irrigation/application/services.py` — CRUD service patterns.
- `src/irrigation/infrastructure/sqlite_repository.py` — additive schema and
  repository constraints.
- `src/irrigation/cli.py` — structured stdin command dispatch.
- `src/irrigation/bootstrap.py` — dependency composition.
- `node-red/templates/configuracoes.html` — settings-section UI patterns.
- `node-red/flows.json` — settings action routing and polling.
- `scripts/sync_flows_templates.py` — template synchronization.

### Files to change

- `src/irrigation/domain/models.py` — add common sensor configuration/state
  models and enums.
- `src/irrigation/domain/ports.py` — add only the minimal sensor-state contract
  needed by the application layer.
- `src/irrigation/application/services.py` — add common sensor CRUD/status use
  cases.
- `src/irrigation/infrastructure/sqlite_repository.py` — add idempotent
  `sensors` and `sensor_state` tables and repositories where required.
- `src/irrigation/cli.py` — add the `sensor` command and stdin actions.
- `src/irrigation/bootstrap.py` — expose the common sensor service.
- `node-red/templates/configuracoes.html` — add section 04 and its interaction
  state.
- `node-red/flows.json` — route sensor actions/results and receive status
  snapshots.
- `docs/DEVELOPER_GUIDE.md`, `docs/COMPONENTS_GUIDE.md`, and `README.md` —
  document the contract and physical-pin convention.
- Relevant tests under `tests/` — cover models, persistence, services, CLI,
  flow integrity, and template synchronization.

### Files to create

- Prefer no new module unless sensor responsibilities make an existing module
  materially harder to navigate; if created, keep domain, application, and
  infrastructure concerns separate.

### Dependencies and integration points

- Tasks 036-040 depend on this task.
- `Valve` records provide the optional section association.
- `Settings.pump_pin` and registered valve pins are reserved resources that
  later sensor connection validation must inspect.
- Node-RED must continue invoking the CLI with structured stdin and no shell.

## Technical approach

### Design principles

- Keep common sensor lifecycle separate from type-specific configuration.
- Use additive tables rather than altering deployed tables.
- Keep hardware libraries out of the domain and application layers.
- Store only the latest generic snapshot here to avoid unbounded SD-card writes.
- Make the backend authoritative for all validation.

### Proposed changes

1. Add a common `Sensor` model and `SensorState` value object with explicit
   enums and serialization.
2. Add an additive `sensors` table plus a one-row-per-sensor `sensor_state`
   table linked by foreign key with cascade deletion.
3. Implement CRUD and state-query services, including protection against
   deleting a sensor while a future safety policy still references it.
4. Add `sensor` CLI actions with stable JSON responses suitable for Node-RED.
5. Add the Sensores settings panel and reusable conditional-form slots for
   type-specific fields.
6. Sync the template into `flows.json` and add focused flow/template tests.

### Performance considerations

- Expected complexity: `O(n)` to list sensors, where `n` is expected to remain
  below a few dozen; individual updates and state reads are indexed `O(1)`.
- Avoid polling by spawning a CLI process per sensor. Fetch all configuration
  and current states in a single request, and preserve the existing dashboard
  process-spawn constraints documented by task 030.

### Error handling and edge cases

- Reject unsupported kinds, blank/duplicate names, missing section references,
  malformed IDs, and invalid enabled values.
- Return `unknown` before the first reading and `stale` after a type-specific
  freshness window; never present an old value as current.
- Preserve a disabled sensor's last diagnostic value but clearly mark it
  disabled and exclude it from automation.
- Prevent raw hardware exceptions or secrets from reaching the dashboard.
- Deleting a sensor must also remove its current-state snapshot transactionally.

## Test specification

### Unit tests

- [x] Validate supported kinds, names, enabled state, associations, and state
  serialization.
- [x] Verify CRUD rules and disabled/unknown/stale presentation.

### Integration tests

- [x] Verify schema initialization on new and existing databases.
- [x] Verify all structured stdin CLI actions and error responses.
- [x] Verify the settings page can list, add, edit, toggle, and delete sensor
  records using mocked state data.

### Regression tests

- [x] Existing schedule, valve, history, authentication, and settings behavior
  remains unchanged.
- [x] `flows.json` remains synchronized with the HTML template.

### Test data and fixtures

- Include one fixture for each supported kind, plus disabled, unknown, stale,
  and fault states.

## Acceptance criteria

- [x] Configurações contains a responsive **Sensores** section numbered 04.
- [x] Users can manage common sensor configuration entirely through the UI.
- [x] The CLI and SQLite contracts support all five planned sensor kinds.
- [x] Sensor health, last reading, last-read time, and errors are visible.
- [x] The UI distinguishes configured, disabled, unsupported, stale, and faulty
  sensors without claiming unavailable hardware is operational.
- [x] Validation is enforced by the backend and errors are actionable.
- [x] No real sensor controls irrigation in this foundational task.
- [x] Tests, linting, formatting, and template synchronization checks pass.

## Implementation checklist

- [x] Inspect the listed files and confirm the deployed schema constraints.
- [x] Implement the smallest common model and persistence contract.
- [x] Add CLI and dashboard integration.
- [x] Add focused and regression tests.
- [x] Run `python3 scripts/sync_flows_templates.py`.
- [x] Run the full validation suite.
- [x] Validate every acceptance criterion before moving the task to `done`.

## Notes

- All UI pin labels must say **physical pin (BOARD)**. Do not copy ambiguous
  `GPIO23`-style labels from the hardware guide without an explicit mapping.
- Type-specific tables are intentionally deferred so each later task can add
  strict constraints without a wide nullable common table.
