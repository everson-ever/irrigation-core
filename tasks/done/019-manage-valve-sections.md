# Manage Valve Sections (Pins) from Settings

## Metadata

```yaml
status: done
priority: medium
type: feature
```

## Title

Add a "Seções" (valve/pin) management section to the settings screen

## Specification

The "Configurações" dashboard tab must gain a second settings section,
alongside the existing "Senha" section, that lets the logged-in user
register, edit, and remove irrigation valves (GPIO pin + section name) from
the UI. Today a `Valve` (`pin`, `section` name) can only be created by
seeding the SQLite `valves` table directly (via `json_migration.py` or
manual DB edits) — there is no service, CLI command, or UI to add, rename,
repoint, or remove a valve/pin at runtime. This task adds that missing
CRUD surface end to end (domain/application/CLI/dashboard).

### Context

- `src/irrigation/domain/models.py:211-242` defines `Valve` (`id`, `pin`,
  `section`, `status`, `manually_turned_off`).
- `src/irrigation/application/services.py:177-237` defines `ValveService`
  with `configure()`, `list_all()`, `get_by_pin()`, `turn_on()`,
  `turn_off()` — no `add`/`update`/`delete` methods exist yet, even though
  the generic `Repository` protocol (`src/irrigation/domain/ports.py:10-17`)
  already supports `add`/`update`/`delete`, and `SqliteRepository` backing
  the `valves` table (`src/irrigation/infrastructure/sqlite_repository.py:31-37,
  60-64`) already enforces `pin INTEGER UNIQUE`.
- `src/irrigation/bootstrap.py:63-65` wires `Application.valves()` to
  `ValveService(SqliteRepository(self._connection, "valves"), gpio)` —
  any new CRUD methods on `ValveService` are reachable from here without
  changes to this wiring.
- `src/irrigation/cli.py:73-99,179-184` defines the `valve` subcommand,
  currently only `list` and `pin,on|off[,minutes][,schedule_id]` — no
  create/update/delete action exists.
- `node-red/templates/configuracoes.html` (see task
  `tasks/done/018-standardize-settings-screen-layout.md`) implements the
  settings screen's sidebar-of-sections pattern: `.ir-config-menu` lists
  sections, `.ir-config-panel` shows the active section's content, and
  `scope.selectConfigSection()`/`isConfigSectionActive()` (lines 450-455)
  toggle which section is visible. The "Senha" section (lines 380-418) is
  the only entry today and is the structural pattern the new "Seções"
  section must follow (`.ir-config-section-head`, `.ir-section-number`,
  `.ir-section-card`, `.ir-form-grid`, `.ir-field`, `.ir-primary-button`,
  `.ir-feedback`).
- `node-red/templates/novo-agendamento.html:638-650,797-798,818-821` reads
  `scope.valves` (pin + section) to render the valve picker used when
  creating a schedule — this is the existing pattern for fetching/rendering
  the valve list on a dashboard tab, and confirms that valve pin/section are
  already surfaced to the frontend today (read-only).
- `src/irrigation/application/services.py:41-42,127-135` (`ScheduleService`)
  rejects a schedule pointing at a valve pin already used by another
  schedule, and `_release_valve_if_unused` (services.py:160-167) turns a
  valve off when its last schedule is deleted — deleting a valve that has
  schedules pointing at it must be handled explicitly (see Scope).

### Scope

#### In scope

- A new `ValveService.add(pin, section) -> Valve` method that validates the
  pin is a positive integer, the section name is non-empty, and the pin is
  not already registered (raising `ValidationError`; the DB `UNIQUE`
  constraint on `pin` is the backstop, not the primary validation path).
- A new `ValveService.update(valve_id, pin, section) -> Valve` method to
  rename a section and/or repoint its pin, with the same validations plus
  duplicate-pin checks against other valves.
- A new `ValveService.remove(valve_id, schedules: ScheduleService) -> bool`
  method that refuses to delete a valve referenced by an existing schedule
  (raising `ValidationError` with a clear message, mirroring
  `ScheduleService.DUPLICATE_VALVE_MESSAGE`'s style), following the
  `ScheduleService.delete(record_id, valves)` pattern of taking the sibling
  service as a collaborator rather than importing it.
- New `irrigation valve add <pin>,<section>`,
  `irrigation valve update <id>,<pin>,<section>`, and
  `irrigation valve delete <id>` CLI actions (or an equivalent subcommand
  structure consistent with the existing `schedule` subcommand's
  `list`/`create`/`update`/`delete` actions), wired into `cli.py` the same
  way as `_schedule_command`/`_valve_command`.
- A new "Seções" entry in the settings screen's `.ir-config-menu`, alongside
  "Senha", following the exact section-toggle pattern already in
  `configuracoes.html`.
- A "Seções" panel that: lists existing valves (pin + section name), lets
  the user add a new valve (pin + section name form), edit an existing
  valve's section name/pin inline or via a form, and delete a valve (with a
  confirmation and a clear error message surfaced in the UI if the valve is
  still referenced by a schedule).
- Backend wiring in `node-red/flows.json` (`exec` nodes calling the new
  `irrigation valve add|update|delete` CLI actions) plus keeping
  `node-red/templates/configuracoes.html` byte-for-byte in sync with the
  corresponding `ui_template` node's `format` field, per the convention
  documented in `docs/DEVELOPER_GUIDE.md` section 12 and enforced by
  `tests/test_node_red_flow.py`.
- Updating `tests/test_services.py` and `tests/test_node_red_flow.py` /
  `tests/test_node_red_settings.py` coverage for the new behavior.

#### Out of scope

- Changing GPIO pin-conflict detection at the hardware level beyond the
  existing `UNIQUE` constraint and the new duplicate-pin validation (no new
  hardware capability/probing is introduced).
- Changing how the pump pin (`settings.pump_pin`) is configured — that
  remains a deployment-level setting, not a per-valve/section record.
  managed here.
- Changing the schedule-creation valve picker's UI beyond automatically
  reflecting newly added/renamed/removed valves (no redesign of
  `novo-agendamento.html`'s picker).
- Reordering or renumbering existing settings sections beyond appending
  "Seções" as a new entry.
- Multi-pump / multi-board GPIO topologies.

## Impact analysis

### Files to inspect

- `src/irrigation/domain/models.py:211-242` — `Valve` dataclass and its
  `from_dict`/`to_dict`, to confirm validation already available (`pin`,
  `section`) before adding service-level checks.
- `src/irrigation/application/services.py:41-238` — `ScheduleService` and
  `ValveService`, as the direct pattern to extend (constructor-injected
  `Repository`, `replace()`-based updates, `ValidationError` on invalid
  input, cross-service collaboration via an explicit parameter).
- `src/irrigation/domain/ports.py:10-17` — confirm `Repository.add`/
  `update`/`delete` signatures match what `ValveService` needs.
- `src/irrigation/infrastructure/sqlite_repository.py:31-37,60-64` —
  `valves` table schema (`pin UNIQUE`, `section`) and `_TABLE_COLUMNS`,
  to confirm no schema migration is needed (columns already exist).
- `src/irrigation/bootstrap.py:63-65` — `Application.valves()` accessor.
- `src/irrigation/cli.py:73-99,141-184` — `_valve_command`/`_schedule_command`
  and `create_parser`, as the pattern for adding new `valve` subcommand
  actions consistent with `schedule`'s `list`/`create`/`update`/`delete`.
- `node-red/templates/configuracoes.html` — full file, especially
  `.ir-config-menu`/`.ir-config-panel` markup (lines 360-419) and the
  `selectConfigSection`/`isConfigSectionActive`/`$watch` scope wiring
  (lines 450-538), as the structural and messaging pattern (`ui_action`,
  `msg.topic` success/error contract) to replicate for the new section.
- `node-red/templates/novo-agendamento.html:638-650,797-821` — existing
  `scope.valves` list rendering, to keep the valve picker consistent with
  any new/renamed/removed valves.
- `node-red/flows.json` — the Configurações `ui_tab`/`ui_template` node and
  the exec nodes backing `change_password`, as the wiring pattern for a new
  exec-backed CRUD flow.
- `docs/DEVELOPER_GUIDE.md` section 12 — the `flows.json`/`templates/*.html`
  mirroring convention.
- `tests/test_services.py` — existing `ValveService`/`ScheduleService` test
  patterns to extend.
- `tests/test_node_red_flow.py`, `tests/test_node_red_settings.py` —
  existing settings-screen assertions to extend.

### Files to change

- `src/irrigation/application/services.py` — add `ValveService.add`,
  `ValveService.update`, `ValveService.remove` (or `delete`), with
  validation and the schedule-reference guard.
- `src/irrigation/cli.py` — extend the `valve` subcommand with
  `add`/`update`/`delete` actions (or restructure `valve` to use
  subparsers like `schedule`, if that better matches existing
  `list`/`pin,on|off[...]` positional-argument style — decide during
  implementation and note the choice here).
- `node-red/flows.json` — add the "Seções" `ui_config_menu` entry, list/add/
  edit/delete UI nodes, and exec nodes calling the new CLI actions; update
  the Configurações `ui_template` node's `format` field.
- `node-red/templates/configuracoes.html` — mirror the updated `ui_template`
  markup exactly.
- `tests/test_services.py` — add `ValveService.add/update/remove` unit
  tests.
- `tests/test_node_red_flow.py` / `tests/test_node_red_settings.py` — add
  assertions for the new "Seções" menu entry/panel and CRUD wiring.

### Files to create

- None expected — extends existing `services.py`, `cli.py`, `flows.json`,
  and `configuracoes.html`.

### Dependencies and integration points

- SQLite `valves` table (already has the needed columns; no schema
  migration expected).
- `ScheduleService` as a collaborator for the delete-guard check (same
  pattern as `ScheduleService.delete(record_id, valves)`).
- Node-RED `exec` nodes as the only integration point between dashboard and
  backend (no REST API in this project).
- GPIO configuration (`ValveService.configure()`/`create_gpio`): adding or
  repointing a valve's pin at runtime means the running process's GPIO
  configuration becomes stale until the next `irrigation run`/restart —
  decide and document how this is handled (see Error handling).

## Technical approach

### Design principles

- Keep each class and function focused on one responsibility.
- Depend on abstractions at architectural boundaries.
- Keep domain rules independent from infrastructure details.
- Prefer small, explicit interfaces and simple data flows.
- Avoid speculative abstractions, duplicated logic, and unrelated changes.

### Proposed changes

1. Add `ValveService.add(pin, section)`, `.update(valve_id, pin, section)`,
   and `.remove(valve_id, schedules)` to `services.py`, following
   `ScheduleService`'s validation style (`ValidationError` on bad input,
   `RecordNotFoundError` via `get`-style lookup for update/remove).
2. Extend the `valve` CLI subcommand (or add `add`/`update`/`delete`
   subparsers) in `cli.py`, wired into `_valve_command`/`_COMMAND_HANDLERS`.
3. Add a "Seções" entry to `.ir-config-menu` in `configuracoes.html`,
   toggled via the existing `selectConfigSection`/`isConfigSectionActive`
   mechanism, with its own `.ir-config-section-head` (numbered "02") and
   `.ir-section-card` containing: a list of current valves (pin + section),
   an add-valve form, and per-row edit/delete controls, reusing
   `.ir-form-grid`/`.ir-field`/`.ir-primary-button`/`.ir-feedback` classes.
4. Wire the new panel's actions to Node-RED `exec` nodes calling
   `irrigation valve add|update|delete ...`, following the
   `ui_action`/`msg.topic` success-error contract used by
   `submitPasswordChange`/`password_changed`/`password_change_error`.
5. Keep `node-red/templates/configuracoes.html` byte-for-byte in sync with
   the `ui_template` node's `format` field.
6. Extend `tests/test_services.py` and the Node-RED flow/settings tests.

### Performance considerations

- Expected complexity: `O(n)` in the number of valves for list/duplicate
  checks (already the pattern used by `ScheduleService._reject_duplicate_valve`
  and `ValveService.get_by_pin`), which is fine given valve counts are
  small (a handful of GPIO pins per installation).
- Performance risks: none beyond existing patterns.
- Mitigation: not applicable.

### Error handling and edge cases

- Adding a valve with a pin already in use (by another valve) must fail
  with a clear `ValidationError`, not a raw SQLite `IntegrityError`.
- Adding/updating a valve with an empty section name must fail validation.
- Deleting a valve referenced by an existing schedule must fail with a
  clear error explaining the valve is in use, rather than silently
  orphaning the schedule's `valve_pin`.
- Deleting or repointing a valve that is currently `status: true` (running)
  should not leave the GPIO pin energized — decide whether to require the
  valve be off first (simplest, consistent with the existing "no access
  without confirmation" pattern) or to force a `turn_off` as part of
  delete; document the decision here before implementing.
- Repointing an existing valve's `pin` to one already used by another valve
  must be rejected the same way as on add.
- Since `ValveService.configure()` only runs once per process
  (`self._configured` guard in `services.py:181-186`), adding/repointing a
  valve while the automatic-control process (`irrigation run`) is already
  running means the new/changed pin won't be GPIO-configured until that
  process restarts — investigate and document whether this is acceptable
  for this task's scope or whether `configure()` needs to be re-run/reset
  after a CRUD change (this mirrors the investigation style of task 015).

## Test specification

### Unit tests

- [ ] `ValveService.add` creates a valve with the given pin/section and
      rejects a duplicate pin with `ValidationError`.
- [ ] `ValveService.add` rejects an empty/whitespace-only section name and
      a non-positive pin.
- [ ] `ValveService.update` renames a section and/or repoints a pin,
      rejecting a pin collision with another valve.
- [ ] `ValveService.remove` deletes a valve with no schedules pointing at
      it, and returns `False`/raises when the valve id does not exist.
- [ ] `ValveService.remove` raises `ValidationError` when a schedule still
      references the valve's pin.

### Integration tests

- [ ] `irrigation valve add <pin>,<section>` followed by `irrigation valve
      list` shows the new valve.
- [ ] `irrigation valve update <id>,<pin>,<section>` updates the stored
      record.
- [ ] `irrigation valve delete <id>` removes the valve, and fails with a
      non-zero exit / error message when the valve has an active schedule.

### Regression tests

- [ ] Existing `valve list` and `valve <pin>,on|off[...]` CLI behavior is
      unaffected.
- [ ] `tests/test_node_red_flow.py` settings-screen assertions (menu order,
      "Senha" section) continue to pass alongside the new "Seções" section.
- [ ] Full test suite (`tests/test_services.py`, `tests/test_cli.py`,
      `tests/test_node_red_flow.py`, `tests/test_node_red_settings.py`)
      continues to pass.

### Test data and fixtures

- Use an in-memory/temporary SQLite database as already done in
  `tests/test_services.py` for `ValveService`/`ScheduleService`.

## Acceptance criteria

The task is complete when:

- [x] The settings screen shows a "Seções" entry alongside "Senha" in the
      config sidebar menu.
- [x] The user can add a new valve (pin + section name) from the UI.
- [x] The user can edit an existing valve's pin and/or section name from
      the UI.
- [x] The user can delete a valve from the UI, with a clear error when it
      is still referenced by a schedule.
- [x] Duplicate pins are rejected with a clear message, both at the
      service layer and surfaced in the UI.
- [x] The schedule-creation valve picker (`novo-agendamento.html`) reflects
      added/renamed/removed valves without further changes.
- [x] Existing behavior remains unchanged outside the defined scope.
- [x] New and changed behavior is covered by specs.
- [x] Error cases and relevant edge cases are covered.
- [x] The implementation follows the project's architecture and SOLID
      principles.
- [x] The implementation is simple, readable, maintainable, and performant
      for the expected workload.
- [x] Formatting, linting, type checks, and the full test suite pass.
- [x] `node-red/templates/configuracoes.html` and the corresponding
      `ui_template` node in `flows.json` remain identical, per repo
      convention.
- [x] Documentation (`docs/DEVELOPER_GUIDE.md` and/or
      `deploy/package-readme.md`) is updated if it references the old
      valve-seeding-only behavior.

## Implementation checklist

- [x] Confirm the task number and filename.
- [x] Inspect all files listed in the impact analysis.
- [x] Reassess the affected files before coding and update this task if
      needed (node ids in `flows.json` may have shifted).
- [x] Implement the smallest coherent change.
- [x] Add or update specs.
- [x] Run focused checks.
- [x] Run the full validation suite.
- [x] Validate the implementation against every acceptance criterion.
- [x] Move the issue to `status: done` only after implementation and
      validation pass.

## Notes

- Original request (Portuguese): "adicionar uma nova section na tela de
  configurações (atualmente só tem a section senha); essa nova section é
  para o usuário conseguir cadastrar/gerenciar o cadastro de sections
  (pins)." Interpreted as: add valve/pin CRUD (create, rename/repoint,
  delete) to the settings screen, since "seção"/"section" in this codebase
  is the existing `Valve.section` field (a named GPIO pin), not a new
  domain concept. This task is written in English per this project's
  task-generation convention (see `tasks/done/014-...md` Notes).
- This is partly a research + implementation task, similar in spirit to
  `tasks/done/015-reflect-real-system-online-status.md`: the exact CLI
  subcommand shape (extending `valve`'s positional-args style vs. adding
  `schedule`-style subparsers) and the GPIO-reconfiguration-on-CRUD
  question should be decided during implementation and recorded here
  before coding.
