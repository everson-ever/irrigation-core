# Support Multiple Weekdays for Schedules

## Metadata

```yaml
status: done
priority: medium
type: feature
```

## Title

Allow schedules to run on selected weekdays

## Specification

### Context

Schedules currently run every day because they only store a time, duration, and valve. Users need to control which days of the week an irrigation schedule is active without creating a separate schedule for every day.

### Scope

#### In scope

- Allow the user to select one or more weekdays when creating a schedule.
- Allow the user to view and edit the selected weekdays.
- Allow a schedule to run on all weekdays through an explicit “Every day” selection.
- Persist the selected weekdays with the schedule.
- Make the automatic controller execute a schedule only on its configured weekdays.
- Preserve existing schedules by treating records without weekday data as schedules that run every day.

#### Out of scope

- Date-specific schedules or date ranges.
- Different times or durations per weekday within one schedule.
- Recurrence rules beyond weekly weekdays.
- Changes to manual valve activation.

## Impact analysis

### Files to inspect

- `src/irrigation/domain/models.py` — schedule data model, serialization, validation, and interval behavior.
- `src/irrigation/application/services.py` — schedule use cases and automatic controller execution rules.
- `src/irrigation/cli.py` — schedule create and update command payloads.
- `src/irrigation/infrastructure/json_repository.py` — persistence behavior and compatibility with existing records.
- `node-red/flows.json` — schedule creation, listing, editing, and command payloads.
- `tests/test_models.py` — existing schedule model and interval specs.
- `tests/test_services.py` — automatic controller and schedule execution specs.
- `data/schedules.json` — existing schedule format and backward-compatibility examples.

### Files to change

- `src/irrigation/domain/models.py` — add a validated weekly-day representation to `Schedule` and serialize it consistently.
- `src/irrigation/application/services.py` — accept weekdays in create/update operations and skip schedules outside their configured weekdays.
- `src/irrigation/cli.py` — accept and validate weekday data in schedule create/update commands while keeping the existing command contract understandable.
- `node-red/flows.json` — add weekday selection to the create/edit forms and display the selected days in the schedule list.
- `tests/test_models.py` — cover weekday normalization, validation, serialization, and legacy records.
- `tests/test_services.py` — cover execution on selected days, non-execution on unselected days, all weekdays, and schedules crossing midnight.

### Files to create

- None expected. Keep the weekday rule in the schedule domain model unless inspection shows that a dedicated value object is necessary.

### Dependencies and integration points

- The Node-RED dashboard sends schedule data to the CLI through shell commands.
- Schedule records are stored as JSON lines in `data/schedules.json` and deployment data defaults.
- `datetime.weekday()` uses Monday as `0` and Sunday as `6`; the persisted format must not depend on locale or translated UI labels.
- Existing records without a weekday field must remain readable and executable every day.

## Technical approach

### Design principles

- Represent weekdays using a small, explicit domain value such as an ordered collection of weekday identifiers.
- Keep weekday validation and normalization inside the domain boundary.
- Keep the controller responsible only for deciding whether a valid schedule is currently active.
- Avoid duplicating weekday mappings between the UI, CLI, model, and controller.
- Preserve the current schedule interval and midnight-crossing behavior.

### Proposed changes

1. Define a canonical persisted representation for weekdays, using stable English identifiers or numeric values and a deterministic Monday-to-Sunday order.
2. Update `Schedule.from_dict`, `Schedule.to_dict`, and schedule creation/update services to validate, normalize, and preserve weekday data.
3. Treat a missing weekday field as all seven weekdays for backward compatibility.
4. Add the weekday condition to automatic execution without changing manual activation or schedule status handling.
5. Update the Node-RED create and edit forms with a multi-select weekday control, including a clear “Every day” behavior, and show the resulting selection in the list.
6. Keep the command payload compact and unambiguous; reject empty or malformed weekday selections with a user-facing validation error.

### Performance considerations

- Expected complexity: `O(n)` per controller cycle, where `n` is the number of schedules; weekday lookup should be `O(1)` per schedule.
- Performance risks: repeated conversion of weekday values in the controller loop or duplicated parsing for every schedule cycle.
- Mitigation: normalize weekdays once when constructing `Schedule` and use an immutable set-like representation or equivalent efficient membership check.

### Error handling and edge cases

- Reject unknown weekday values.
- Reject an empty selection unless the input explicitly means “Every day”.
- Remove duplicate weekday values during normalization or reject them consistently.
- Preserve schedules created before this feature as every-day schedules.
- A schedule that crosses midnight must start only on a configured day; its already-started interval must be allowed to finish on the following calendar day.
- Editing a schedule must not reset its `status` or `enabled` fields.
- The UI must prevent submission until at least one valid day is selected.

## Test specification

### Unit tests

- [ ] A schedule accepts a valid subset of weekdays and preserves canonical ordering.
- [ ] A schedule accepts all seven weekdays.
- [ ] A schedule with no weekday field defaults to all weekdays.
- [ ] Invalid and empty weekday values raise `ValidationError`.
- [ ] Weekday data survives `from_dict` and `to_dict` conversion.

### Integration tests

- [ ] A schedule starts on a configured weekday.
- [ ] A schedule does not start on an unconfigured weekday.
- [ ] An all-weekday schedule continues to run every day.
- [ ] Create and update commands persist the selected weekdays.
- [ ] The Node-RED create/edit/list flow sends and renders weekday data correctly.

### Regression tests

- [ ] Existing schedule records without weekday data continue to run every day.
- [ ] Existing midnight-crossing behavior remains unchanged.
- [ ] Overlapping schedules on the same valve still do not turn the valve off early.
- [ ] Manual valve activation remains unaffected.

### Test data and fixtures

- Use fixed dates with known weekdays, such as Monday and Sunday, instead of relying on the current system date.
- Include a legacy record without a weekday field and records with one, multiple, and all weekdays.

## Acceptance criteria

The task is complete when:

- [ ] The user can select one or more weekdays when creating a schedule.
- [ ] The user can edit and view the selected weekdays.
- [ ] Selecting all weekdays produces an every-day schedule.
- [ ] The automatic controller runs schedules only on configured weekdays.
- [ ] Existing schedules without weekday data continue to run every day.
- [ ] Weekday input is validated at the domain boundary and malformed data cannot be persisted.
- [ ] New and changed behavior is covered by specs.
- [ ] Midnight-crossing, overlapping, enabled/disabled, and manual-control behavior remains correct.
- [ ] The implementation is simple, readable, maintainable, and efficient for the expected number of schedules.
- [ ] Formatting, linting, type checks, and the full test suite pass.
- [ ] User-facing help and README examples are updated if the command syntax changes.

## Implementation checklist

- [ ] Confirm the task number and filename.
- [ ] Inspect all files listed in the impact analysis.
- [ ] Decide and document the canonical weekday representation before implementation.
- [ ] Add or update specs before changing the execution logic.
- [ ] Implement the smallest coherent change.
- [ ] Verify backward compatibility with existing JSON records.
- [ ] Run focused checks.
- [ ] Run the full validation suite.
- [ ] Validate the implementation against every acceptance criterion.
- [ ] Move the issue to `done` only after implementation and validation pass.

## Notes

- The initial request is in Portuguese; the implementation task is intentionally written in English as required by the task-generation convention.
