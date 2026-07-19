---
status: done
priority: high
type: bug
---

## Title

Restrict valve sections to supported physical GPIO pins

## Specification

Replace the free-form GPIO pin field in Configurações > Seções with a required
selector containing only the physical Raspberry Pi header pins approved for
valve outputs:

```text
7, 11, 12, 13, 16, 18, 22, 29, 31, 32, 33, 35, 36, 37, 38, 40
```

Apply the same allowlist in the application service so requests made through
the CLI, Node-RED, or another caller cannot persist an unsupported pin. The
values are physical `GPIO.BOARD` numbers, not BCM GPIO numbers.

### Context

The section form currently accepts any positive integer. Unsupported physical
pins can therefore be stored in the `valves` table. When the long-lived
controller starts, `GPIORaspberryPi.configure()` passes every stored valve pin
to `RPi.GPIO.setup()`. One invalid channel terminates the controller with
`The channel sent is invalid on a Raspberry Pi`; systemd then enters a restart
loop, the dashboard reports the system offline, and automatic irrigation does
not run.

Physical pin 15 is intentionally absent from the allowlist because it is the
installation's configured pump output. Power, ground, ID EEPROM, and pins
reserved for I2C, UART, or SPI are also not offered for valve registration.

### Scope

#### In scope

- Define the exact valve-output allowlist as
  `7, 11, 12, 13, 16, 18, 22, 29, 31, 32, 33, 35, 36, 37, 38, 40`.
- Replace the numeric input used to create or edit a section with a select
  containing only those values.
- Label options as physical `BOARD` pins and avoid presenting them as BCM
  numbers.
- Validate the allowlist in `ValveService.add()` and `ValveService.update()`
  before writing to SQLite.
- Return a clear validation error that includes the rejected value and the
  allowed physical pins.
- Preserve duplicate-pin validation and all existing section CRUD behavior.
- Keep the standalone Configurações template and its `flows.json`
  `ui_template` copy synchronized.
- Add behavior-focused service, CLI, and Node-RED flow tests.

#### Out of scope

- Automatically migrating or deleting invalid valve records already stored in
  existing installations.
- Renumbering GPIO handling from `BOARD` to BCM.
- Allowing users to customize the allowlist from the dashboard.
- Changing the pump pin or exposing pump configuration in the UI.
- Probing Raspberry Pi hardware capabilities dynamically.
- Implementing GPIO conflict management for future sensor tasks.

## Impact analysis

### Files to inspect

- `src/irrigation/application/services.py` — current section add/update and
  duplicate-pin validation paths.
- `src/irrigation/domain/models.py` — existing positive-integer validation for
  `Valve.pin` and `Schedule.valve_pin`.
- `src/irrigation/infrastructure/gpio.py` — confirms physical `GPIO.BOARD`
  numbering and the startup failure path.
- `src/irrigation/cli.py` — valve add/update entry points and validation-error
  serialization.
- `node-red/templates/configuracoes.html` — section form, edit-state handling,
  and request payload construction.
- `node-red/flows.json` — synchronized Configurações `ui_template` content and
  valve CRUD flow.
- `scripts/sync_flows_templates.py` — supported template synchronization
  workflow.
- `tests/test_services.py`, `tests/test_cli.py`, and
  `tests/test_node_red_flow.py` — existing valve CRUD and template tests.

### Files to change

- `src/irrigation/application/services.py` — define/reuse the approved pin set
  and reject unsupported pins in all section mutation paths.
- `node-red/templates/configuracoes.html` — replace the free numeric field with
  the approved-pin selector and preserve add/edit behavior.
- `node-red/flows.json` — synchronize the changed Configurações template.
- `tests/test_services.py` — cover accepted and rejected pins for add/update.
- `tests/test_cli.py` — verify invalid CLI requests fail with the public
  validation message and do not persist data.
- `tests/test_node_red_flow.py` — verify the selector and exact option set are
  present and the free-form numeric input is absent.
- `README.md` and/or `docs/COMPONENTS_GUIDE.md` — document the valve allowlist
  and clarify that values use physical `BOARD` numbering.

### Files to create

- None expected.

### Dependencies and integration points

- `ValveService` remains the authoritative write boundary for section pins.
- Node-RED continues sending the selected numeric value through the existing
  structured `valve` request; no new command or schema is required.
- SQLite's unique constraint remains a backstop for duplicate pins.
- The allowlist assumes the production pump remains on physical pin 15. A
  future change to `IRRIGATION_PUMP_PIN` must explicitly revisit this policy.

## Technical approach

### Design principles

- Enforce the rule at the service boundary, not only in browser markup.
- Keep one clearly named immutable backend constant for the approved `BOARD`
  pins and reuse one validation function from both add and update.
- Keep UI validation immediate and backend validation authoritative.
- Do not broaden the change into hardware discovery or GPIO lifecycle work.

### Proposed changes

1. Add an immutable approved-pin constant and a focused validation helper near
   `ValveService`; call it after integer parsing and before duplicate checks or
   repository writes.
2. Replace `<input type="number">` in the section form with a required
   `<select>` backed by the exact approved-pin list. Ensure editing an existing
   valid section selects its current pin correctly.
3. If an installation already contains an unsupported value, keep the record
   visible and require the user to select an approved value before saving; do
   not silently coerce or delete it.
4. Synchronize `node-red/templates/configuracoes.html` into
   `node-red/flows.json` using the repository script.
5. Update GPIO documentation and add focused service, CLI, UI, and regression
   coverage.

### Performance considerations

- Expected complexity: `O(1)` membership validation using an immutable set;
  the selector has only 16 options.
- Performance risks: none material.
- Mitigation: keep validation local and avoid hardware probing or extra
  subprocesses.

### Error handling and edge cases

- Reject numeric but unsupported values such as physical pins `1`, `14`, `15`,
  `17`, `27`, and `28`.
- Reject BCM numbers when they are not also approved physical pin numbers; the
  error must tell the caller to use physical `BOARD` numbering.
- Reject non-numeric, empty, boolean, fractional, and malformed values through
  the existing integer-validation path.
- An update rejected for its pin must leave the original valve unchanged.
- Duplicate approved pins must continue returning the existing duplicate-pin
  error.
- Existing unsupported records are not migrated automatically, but the form
  must allow users to repair them by selecting an approved value.

## Test specification

### Unit tests

- [x] Parameterize all 16 approved values and verify each can be added.
- [x] Parameterize representative power, ground, reserved-interface, pump, and
  out-of-range values and verify each is rejected without a repository write.
- [x] Verify update uses the same allowlist and preserves the original record
  after rejection.
- [x] Verify duplicate detection still applies to approved pins.

### Integration tests

- [x] Verify CLI add/update accepts an approved physical pin and returns a clear
  validation error for an unsupported pin.
- [x] Verify the Configurações template renders a required selector with the
  exact approved values and submits the selected value as an integer.
- [x] Verify template synchronization leaves `flows.json` in sync.

### Regression tests

- [x] Existing section list, edit, delete, schedule-reference guard, and
  notification behavior remain unchanged.
- [x] Existing schedules referencing valid valve pins continue to operate.
- [x] GPIO numbering remains `GPIO.BOARD`, and physical pin 15 remains reserved
  for the pump.

### Test data and fixtures

- Use physical pin 13 as the normal valid fixture, physical pin 16 as a second
  valid pin, physical pin 15 as the pump-conflict fixture, and physical pin 17
  as a power-pin/BCM-confusion fixture.

## Acceptance criteria

The task is complete when:

- [x] Users can only choose `7, 11, 12, 13, 16, 18, 22, 29, 31, 32, 33, 35,
  36, 37, 38, 40` when creating or editing a section.
- [x] The UI clearly identifies values as physical Raspberry Pi `BOARD` pins.
- [x] `ValveService` rejects every value outside the allowlist for both add and
  update, regardless of whether the request came from Node-RED or the CLI.
- [x] Invalid requests cannot modify the SQLite valve record.
- [x] Existing invalid records remain visible and can be repaired through the
  selector without silent data loss.
- [x] Physical pin 15 cannot be registered as a valve while it is reserved for
  the pump.
- [x] Existing duplicate, section-name, delete, schedule, and notification
  behavior remains unchanged.
- [x] Focused tests and the full validation suite pass.
- [x] User-facing GPIO documentation contains the same allowlist.

## Implementation checklist

- [x] Confirm task number `042` and filename.
- [x] Inspect every file listed in the impact analysis before implementation.
- [x] Add authoritative service-level allowlist validation.
- [x] Replace the section pin input with the fixed selector.
- [x] Handle display and repair of pre-existing unsupported records.
- [x] Synchronize the Node-RED template into `flows.json`.
- [x] Add service, CLI, Node-RED, and regression tests.
- [x] Update user-facing GPIO documentation.
- [x] Run focused tests, formatting/lint checks, and the complete test suite.
- [x] Validate each acceptance criterion before moving the task to `done`.

## Notes

- This task prevents future invalid registrations. Operators must manually
  correct any unsupported pin already stored before restarting a controller
  that is currently failing during GPIO setup.
