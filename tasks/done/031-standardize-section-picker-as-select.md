# Standardize the Section/Valve Picker as a Select

## Metadata

```yaml
status: done
priority: medium
type: refactor
```

## Title

Replace the "Seção / válvula" card grid in the new-schedule form with the system's standard select field

## Specification

The "Novo agendamento" (create schedule) form renders the section/valve
picker as a grid of clickable cards (icon, "V.N" pin badge, section name),
implemented by `.ir-valves`/`.ir-valve-card` in
`node-red/templates/novo-agendamento.html:343-388,638-654`. This is the only
place in the dashboard that picks a valve this way. The "Editar agendamento"
modal already picks the same data (valve pin + section) using the app's
standard field pattern: a native `<select>` wrapped in `.ir-field`
(`node-red/templates/agendamentos.html:1003-1006`), styled by the shared
`.ir-field label` / `.ir-field input, .ir-field select` rules
(`agendamentos.html:568-580`) that are duplicated in every template
(`configuracoes.html:494-556` uses the same `.ir-field` pattern).

This task replaces the card grid in `novo-agendamento.html` with that same
`.ir-field` + `<select>` pattern, so the section/valve field looks and
behaves identically whether the user is creating or editing a schedule.

### Context

- The card grid was a custom, one-off control never reused elsewhere; the
  rest of the app (edit-schedule modal, settings screen) already uses plain
  `<select>` elements for choosing a valve/section or any other fixed list,
  wrapped in `.ir-field`.
- `novo-agendamento.html` does not currently define `.ir-field`/`.ir-field
  select` CSS at all (it has its own self-contained `<style>` block, like
  every dashboard template) — the rule must be copied into this file's
  `<style>` block the same way each template keeps its own full copy of
  shared classes (there is no shared CSS file across templates).
- `scope.valves` is already populated the same way in both templates via a
  `$watch` on `msg.payload` (`novo-agendamento.html:713,719-731`); no backend
  or data-fetching change is needed.
- `scope.selectValve(valve)` / `scope.isValveSelected(valve)`
  (`novo-agendamento.html:797-798`) exist only to support the card grid and
  become dead code once replaced by `ng-model="create_form.section"` bound
  directly to a `<select>`.
- `scope.sectionName(create_form.section)` (used at
  `novo-agendamento.html:679` in the summary/review step) must keep working
  unchanged — it resolves a pin back to a section name and does not depend
  on how the field is rendered.
- Per `docs/DEVELOPER_GUIDE.md` section 12,
  `node-red/templates/novo-agendamento.html` must stay byte-for-byte
  identical to the corresponding `ui_template` node's `format` field in
  `node-red/flows.json`, and `tests/test_node_red_flow.py` enforces this.

### Scope

#### In scope

- Replace the `.ir-valves`/`.ir-valve-card` markup
  (`novo-agendamento.html:643-653`) with a `.ir-field` block containing a
  `<label>Seção / válvula</label>` and a native
  `<select ng-model="create_form.section">`, with one
  `<option ng-repeat="valve in valves track by valve.pin" ng-value="+valve.pin">`
  per valve, mirroring `agendamentos.html:1004-1006`'s markup and option
  label format (`{{ valve.section }} · Válvula {{ valve.pin }}`).
- Keep the "Nenhuma seção disponível." empty state
  (`novo-agendamento.html:653`), adapted to the select (e.g. shown instead
  of the select, or as a disabled placeholder option) when `valves.length
  === 0`.
- Add the `.ir-field label` / `.ir-field input, .ir-field select` /
  `.ir-field input:focus, .ir-field select:focus` CSS rules to
  `novo-agendamento.html`'s `<style>` block (copied from
  `agendamentos.html:568-580`), reusing the existing `.ir-field` class name
  for consistency across templates.
- Remove the now-unused `.ir-valves`/`.ir-valve-card`/`.ir-valve-icon`/
  `.ir-valve-check`/`.ir-valve-name`/`.ir-empty-valves` CSS rules
  (`novo-agendamento.html:343-388`) and the `scope.selectValve`/
  `scope.isValveSelected` controller functions
  (`novo-agendamento.html:797-798`), since nothing else uses them.
- Update `node-red/flows.json`'s matching `ui_template` node `format` field
  to stay byte-for-byte identical to the updated `novo-agendamento.html`.
- Update any assertions in `tests/test_node_red_flow.py` /
  `tests/test_node_red_settings.py` that reference the old card-grid markup
  or classes for the create-schedule form.

#### Out of scope

- Changing the edit-schedule modal's existing `<select>`
  (`agendamentos.html:1003-1006`) — it is already the target pattern.
- Changing how `scope.valves` is fetched/populated, or any backend/service
  code.
- Introducing a new shared component/partial system across templates (each
  template keeps its own self-contained markup/CSS, per existing
  convention).
- Any visual redesign beyond adopting the existing `.ir-field`/`<select>`
  pattern (no new custom dropdown component).

## Impact analysis

### Files to inspect

- `node-red/templates/novo-agendamento.html:343-388` — CSS for the card
  grid being removed.
- `node-red/templates/novo-agendamento.html:638-654` — markup being
  replaced.
- `node-red/templates/novo-agendamento.html:679` — `sectionName(...)` usage
  in the summary step, to confirm it keeps working unchanged.
- `node-red/templates/novo-agendamento.html:708-731` — `scope.create_form`
  initialization and the `$watch` populating `scope.valves`, to confirm no
  change is needed there.
- `node-red/templates/novo-agendamento.html:797-798` — `selectValve`/
  `isValveSelected`, to confirm they become unused and can be removed.
- `node-red/templates/agendamentos.html:568-581,1003-1006` — the target
  `.ir-field`/`<select>` pattern to replicate.
- `node-red/flows.json` — locate the `ui_template` node whose `format`
  mirrors `novo-agendamento.html`.
- `tests/test_node_red_flow.py`, `tests/test_node_red_settings.py` — check
  for assertions tied to `.ir-valve-card`/`selectValve`/card-grid markup.

### Files to change

- `node-red/templates/novo-agendamento.html` — swap the card grid for a
  `.ir-field` + `<select>`, add the needed CSS, remove now-dead CSS/JS.
- `node-red/flows.json` — update the matching `ui_template` node's `format`
  field to match, byte-for-byte.
- `tests/test_node_red_flow.py` / `tests/test_node_red_settings.py` — update
  any assertions referencing the removed markup/classes/functions.

### Files to create

- None.

### Dependencies and integration points

- Node-RED `ui_template` node (`novo-agendamento` tab) — the only
  integration point touched; no exec/CLI/service changes.

## Technical approach

### Design principles

- Keep each class and function focused on one responsibility.
- Depend on abstractions at architectural boundaries.
- Keep domain rules independent from infrastructure details.
- Prefer small, explicit interfaces and simple data flows.
- Avoid speculative abstractions, duplicated logic, and unrelated changes.

### Proposed changes

1. Replace `novo-agendamento.html:643-653`'s `.ir-valves`/`.ir-valve-card`
   markup with a `.ir-field` block wrapping a `<select
   ng-model="create_form.section">`, populated via `ng-repeat` over
   `valves`, matching `agendamentos.html:1004-1006`'s option label format.
2. Add the `.ir-field` CSS rules to `novo-agendamento.html`'s `<style>`
   block, copied from `agendamentos.html:568-580`.
3. Remove the dead `.ir-valve-*`/`.ir-empty-valves` CSS
   (`novo-agendamento.html:343-388`) and the dead `scope.selectValve`/
   `scope.isValveSelected` functions (`novo-agendamento.html:797-798`).
4. Keep the "Nenhuma seção disponível." empty-state message, shown when
   `valves.length === 0`.
5. Mirror the final `novo-agendamento.html` content into the corresponding
   `ui_template` node's `format` field in `node-red/flows.json`.
6. Update any Node-RED flow/template tests that assert on the removed
   markup or functions.

### Performance considerations

- Expected complexity: `O(n)` in the number of valves for rendering
  `<option>`s, identical to the current card grid and to the existing
  edit-modal `<select>` — no regression.
- Performance risks: none.
- Mitigation: not applicable.

### Error handling and edge cases

- `valves.length === 0`: show the existing "Nenhuma seção disponível."
  message instead of an empty/unusable select.
- `create_form.section` must still resolve to the correct pin value
  (`ng-value="+valve.pin"` mirrors the numeric coercion already used in
  `agendamentos.html:1006`), so `sectionName(create_form.section)` in the
  summary step and the final `createSchedule()` payload
  (`novo-agendamento.html:867`) keep receiving a numeric pin, unchanged from
  today's behavior.

## Test specification

### Unit tests

- Not applicable (no backend/service logic changes).

### Integration tests

- [x] `tests/test_node_red_flow.py` confirms `novo-agendamento.html` and its
      `ui_template` node's `format` field remain identical.

### Regression tests

- [x] Existing Node-RED flow/template tests continue to pass after removing
      `.ir-valve-card`-related markup and functions.
- [x] `sectionName(create_form.section)` in the review/summary step still
      resolves the selected valve's section name correctly.

### Test data and fixtures

- None beyond the existing Node-RED template fixtures already used by
  `tests/test_node_red_flow.py`.

## Acceptance criteria

The task is complete when:

- [x] The "Seção / válvula" field in the create-schedule form is a native
      `<select>` wrapped in `.ir-field`, matching the pattern already used
      in the edit-schedule modal.
- [x] The card-grid markup, CSS, and now-unused
      `selectValve`/`isValveSelected` functions are removed.
- [x] The empty-state message is preserved when no valves exist.
- [x] Selecting a section still sets `create_form.section` to the correct
      valve pin and the summary/review step still shows the correct section
      name.
- [x] `node-red/templates/novo-agendamento.html` and the corresponding
      `ui_template` node in `flows.json` remain byte-for-byte identical.
- [x] Existing behavior remains unchanged outside the defined scope.
- [x] Formatting, linting, type checks, and the full test suite pass.

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

- Original request (Portuguese): "tornar a listagem de seções um select com
  UI padrão do sistema" — interpreted as replacing the card-grid valve
  picker in the create-schedule form with the plain `<select>` +
  `.ir-field` pattern already used for the same data in the edit-schedule
  modal, since that is the only existing "standard select" pattern in this
  codebase.
