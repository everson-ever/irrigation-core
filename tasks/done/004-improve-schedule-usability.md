# Improve Schedule Dashboard Usability

## Metadata

```yaml
status: done
priority: medium
type: feature
```

## Title

Improve schedule creation, editing, and menu usability

## Specification

### Context

The Node-RED dashboard schedule flow needs clearer user feedback and navigation. Creating or editing a schedule can appear idle while the command is running, editing does not provide a focused pre-filled form experience, and the menu labels/order are not aligned with the intended user workflow.

### Scope

#### In scope

- Show a visible loading state when the user submits the new schedule form.
- Redirect the user to the schedules screen after a schedule is created successfully.
- When editing a schedule, open only the schedule form with the selected schedule data already filled in.
- Hide the schedules table while the edit form is active.
- Show a visible loading state when the user submits an edited schedule.
- Redirect the user to the schedules screen after a schedule is edited successfully.
- Reorder the dashboard menu items as: `Agendamentos`, `Novo Agendamento`, `Histórico`.
- Rename the history menu item so it no longer appears as `Filtrar históricos`.

#### Out of scope

- Changing schedule domain validation rules.
- Changing the persisted schedule data format.
- Redesigning the complete dashboard layout.
- Adding new schedule fields.
- Changing history filtering behavior beyond the menu label.
- Replacing Node-RED dashboard with another frontend framework.

## Impact analysis

### Files to inspect

- `node-red/flows.json` — dashboard pages, menu groups/tabs, schedule list, create form, edit flow, command execution, success routing, and loading feedback.
- `src/irrigation/cli.py` — schedule create/update command contract, output, and exit status used by Node-RED.
- `src/irrigation/application/services.py` — schedule create/update behavior and validation errors surfaced through the CLI.
- `data/schedules.json` — representative persisted schedule records used to pre-fill the edit form.
- `README.md` — dashboard usage documentation or screenshots that may need updates if user-facing navigation changes.
- `screenshot application/schedules.png` — current schedules screen reference.
- `screenshot application/create-schedule.png` — current new schedule screen reference.

### Files to change

- `node-red/flows.json` — add create/update loading states, pre-fill edit form data, hide the schedules table while editing, redirect after successful create/update, and update menu order/labels.
- `README.md` — update user-facing dashboard instructions or screenshots if they describe the old menu label/order or schedule workflow.

### Files to create

- None expected.

### Dependencies and integration points

- The dashboard invokes schedule create and update operations through Node-RED flow nodes and CLI commands.
- The schedule table action for editing must preserve the selected schedule identifier and pass all editable fields into the form state.
- Successful create/update detection depends on the CLI exit status or the existing Node-RED success/error path.
- Menu order and labels are controlled by Node-RED dashboard tab/group configuration in `node-red/flows.json`.

## Technical approach

### Design principles

- Keep each class and function focused on one responsibility.
- Depend on abstractions at architectural boundaries.
- Keep domain rules independent from infrastructure details.
- Prefer small, explicit interfaces and simple data flows.
- Avoid speculative abstractions, duplicated logic, and unrelated changes.

### Proposed changes

1. Trace the create schedule submit path in `node-red/flows.json` and add an explicit loading state before invoking the command.
2. Clear the create loading state on success or failure, show the existing error feedback on failure, and navigate to `Agendamentos` only after a successful create.
3. Trace the edit action from the schedules table, fetch or reuse the selected schedule data, and map it into the form fields before rendering the form.
4. Introduce a dashboard state that distinguishes schedule list mode from edit mode so the table is hidden while the edit form is visible.
5. Add an explicit loading state for the edit submit path and navigate back to `Agendamentos` only after a successful update.
6. Update the Node-RED dashboard menu/tab configuration so the visible order is `Agendamentos`, `Novo Agendamento`, `Histórico`.
7. Rename the history menu entry from `Filtrar históricos` to `Histórico` without changing the underlying history filtering behavior.
8. Update documentation or screenshots only if the existing documentation becomes inaccurate.

### Performance considerations

- Expected complexity: `O(n)` when locating the selected schedule from the current list, where `n` is the number of schedules.
- Performance risks: unnecessary reloads of the schedule list while switching between list and edit mode.
- Mitigation: reuse the selected table row data when reliable, and refresh from persisted data only after successful create/update or when required for consistency.

### Error handling and edge cases

- A failed create command must clear the loading state and keep the user on the new schedule form with actionable feedback.
- A failed edit command must clear the loading state, keep the edit form visible, preserve the user's submitted values, and show actionable feedback.
- The dashboard must not redirect to `Agendamentos` after failed create/update commands.
- If an edit action is triggered for a schedule that no longer exists, show an error and keep or return the user to the schedules list.
- The edit form must preserve the schedule identifier so the update targets the correct record.
- Optional or default fields must be pre-filled consistently with how the schedule was originally created.
- Returning from edit mode to the schedules list must make the table visible again.
- The history menu label must change only the visible navigation text, not the history search behavior.

## Test specification

### Unit tests

- [ ] Schedule create/update CLI success and failure contracts remain deterministic for Node-RED integration.
- [ ] Existing schedule serialization still provides all fields needed to pre-fill the edit form.

### Integration tests

- [ ] Submitting a new schedule shows a loading state while the create command is running.
- [ ] A successful create redirects to `Agendamentos` and refreshes the schedules table.
- [ ] A failed create clears the loading state and keeps the user on the new schedule form.
- [ ] Clicking edit opens a form pre-filled with the selected schedule data.
- [ ] The schedules table is hidden while the edit form is visible.
- [ ] Submitting an edited schedule shows a loading state while the update command is running.
- [ ] A successful update redirects to `Agendamentos` and refreshes the schedules table.
- [ ] A failed update clears the loading state and keeps the edit form visible with the user's values.
- [ ] The dashboard menu appears in the order `Agendamentos`, `Novo Agendamento`, `Histórico`.
- [ ] The history menu item is labeled `Histórico`, not `Filtrar históricos`.

### Regression tests

- [ ] Existing schedule listing remains unchanged outside edit mode.
- [ ] Existing schedule creation and update command payloads remain compatible with the backend.
- [ ] Existing history filtering behavior still works after the menu rename.
- [ ] Existing schedule deletion and enable/disable actions remain unaffected.

### Test data and fixtures

- Use at least one persisted schedule with all editable fields populated.
- Use one schedule with default or optional values to verify pre-fill behavior.
- Use simulated successful and failed CLI command results for create and update paths where the test harness supports flow-level checks.

## Acceptance criteria

The task is complete when:

- [ ] The requested behavior is implemented.
- [ ] Clicking the new schedule submit button shows a loading state while the create action is running.
- [ ] A successful new schedule creation redirects to the `Agendamentos` screen.
- [ ] Clicking edit for a schedule opens a form pre-filled with that schedule's current data.
- [ ] The schedules table is not visible while editing a schedule.
- [ ] Clicking the edit submit button shows a loading state while the update action is running.
- [ ] A successful schedule update redirects to the `Agendamentos` screen.
- [ ] Create and update failures clear loading states and do not incorrectly redirect.
- [ ] The menu order is `Agendamentos`, `Novo Agendamento`, `Histórico`.
- [ ] The history menu item no longer uses the label `Filtrar históricos`.
- [ ] Existing behavior remains unchanged outside the defined scope.
- [ ] New and changed behavior is covered by specs.
- [ ] Error cases and relevant edge cases are covered.
- [ ] The implementation follows the project's architecture and SOLID principles.
- [ ] The implementation is simple, readable, maintainable, and performant for the expected workload.
- [ ] Formatting, linting, type checks, and the full test suite pass.
- [ ] Documentation or user-facing examples are updated when needed.

## Implementation checklist

- [ ] Confirm the task number and filename.
- [ ] Inspect all files listed in the impact analysis.
- [ ] Reassess the affected files before coding and update this task if needed.
- [ ] Identify the Node-RED nodes responsible for schedule list, create, edit, and history navigation.
- [ ] Implement the smallest coherent change.
- [ ] Add or update specs.
- [ ] Run focused checks.
- [ ] Run the full validation suite.
- [ ] Validate the implementation against every acceptance criterion.
- [ ] Move the issue to `done` only after implementation and validation pass.

## Notes

- The initial request is in Portuguese; this task is intentionally written in English as required by the task-generation convention.
- The request says “cadastar noivo agendamento”; this task interprets it as “cadastrar novo agendamento”.
