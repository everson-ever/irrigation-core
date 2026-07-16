# Support Multiple Times per Schedule

## Metadata

```yaml
status: done
priority: medium
type: feature
```

## Title

Allow a schedule to run at up to three times per day

## Specification

### Context

A schedule currently stores a single `time` value, so watering a section more than once a day requires creating a separate schedule for every additional time slot, duplicating the valve, duration, weekday, and enabled settings across records. Users need to pick more than one start time — up to three — within a single schedule.

### Scope

#### In scope

- Allow the user to select one, two, or three start times when creating a schedule.
- Allow the user to view and edit the selected start times.
- Persist all selected times with the schedule.
- Make the automatic controller start and stop the valve for each configured time independently, using the same duration and weekdays for every time slot.
- Continue to prevent overlapping active intervals on the same valve, including overlaps between two time slots of the same schedule.

#### Out of scope

- Different durations, weekdays, or valves per time slot within one schedule.
- More than three time slots per schedule.
- Changes to manual valve activation.
- Changes to the weekday selection feature.

## Impact analysis

### Files to inspect

- `src/irrigation/domain/models.py` — `Schedule` data model, `from_dict`/`to_dict`, `interval_at`, `is_running_at`, and `_schedule_time` validation.
- `src/irrigation/application/services.py` — schedule create/update use cases, automatic controller execution loop, `_automatic_start_mode`, and overlap/active-interval checks (`_has_active_record`, history recording).
- `src/irrigation/cli.py` — `_schedule_command` argument parsing for `create`/`update` and the CSV payload contract (`schedule_time, minutes, pin[, weekdays]`).
- `node-red/flows.json` — schedule create/edit form, list rendering (`records.sort` by `time`, line ~135), and the CSV payload built for the CLI.
- `tests/test_models.py` — existing schedule model and interval specs.
- `tests/test_services.py` — automatic controller execution specs.
- `tests/test_cli.py` — schedule command argument parsing specs.
- `data/schedules.json` / `deploy/data-defaults` — existing schedule format examples.

### Files to change

- `src/irrigation/domain/models.py` — replace the single `time: str` field with an ordered, validated collection of up to three times, update `from_dict`/`to_dict`, and make `interval_at`/`is_running_at` reason about multiple intervals per day.
- `src/irrigation/application/services.py` — accept multiple times in create/update operations, evaluate each configured time slot in the automatic controller loop, and keep overlap detection correct across a schedule's own slots.
- `src/irrigation/cli.py` — accept and validate a compact multi-time payload (e.g. semicolon or pipe-separated times) in `create`/`update` while keeping the existing CSV contract understandable.
- `node-red/flows.json` — let the create/edit form add up to three time inputs, validate the maximum, and show all configured times in the schedule list.
- `tests/test_models.py` — cover single time, multiple times, the three-time maximum, and ordering.
- `tests/test_services.py` — cover independent start/stop for each time slot, non-overlapping and back-to-back slots, and the existing single-time behavior.
- `tests/test_cli.py` — cover parsing of one, two, and three times and rejection of a fourth.

### Files to create

- None expected. Keep the multi-time rule inside the existing `Schedule` model unless inspection shows a dedicated value object is clearer.

### Dependencies and integration points

- The Node-RED dashboard sends schedule data to the CLI through shell commands using a CSV-like payload.
- Schedule records are stored in `data/irrigation.db` (SQLite) after task 010; the persisted times column must be updated to hold a collection of times.
- The automatic controller polls schedules on a fixed interval; each configured time must be checked independently within the same poll loop.
- History/active-interval tracking must distinguish which of a schedule's time slots is currently running.

## Technical approach

### Design principles

- Keep the time-slot rule (ordering, maximum of three, validation) inside the domain boundary, next to the existing weekday normalization pattern.
- Keep the controller responsible only for deciding whether any of a schedule's valid intervals is currently active.
- Avoid duplicating time-parsing or validation logic between the UI, CLI, model, and controller.
- Preserve current midnight-crossing and overlap-prevention behavior for each individual time slot.

### Proposed changes

1. Change `Schedule` to hold an ordered tuple of up to three distinct `HH:MM` times instead of a single `time` string, normalizing and validating them the same way weekdays are normalized (`_normalize_weekdays` pattern).
2. Update `Schedule.from_dict`/`to_dict` to read/write a list of times.
3. Replace `interval_at`/`is_running_at` with logic that computes an interval per configured time and reports whether `now` falls in any of them; keep the existing midnight-crossing lookback per time slot.
4. Update the automatic controller loop (`_automatic_start_mode` and related execution code in `services.py`) to start/stop the valve for whichever time slot is currently due, and to keep per-slot history/active-interval records distinct.
5. Update `_schedule_command` in `cli.py` to accept multiple times in the existing comma-separated payload (e.g. a sub-delimited time field) and validate the three-time maximum before calling the service layer.
6. Update the Node-RED create/edit form to offer up to three time pickers with an "add time" control capped at three, and update the list template to display all configured times for a schedule.

### Performance considerations

- Expected complexity: `O(n * k)` per controller cycle, where `n` is the number of schedules and `k` is the number of time slots per schedule (`k <= 3`).
- Performance risks: recomputing interval parsing for every time slot on every poll cycle.
- Mitigation: normalize and parse times once when constructing `Schedule`, and keep the per-cycle check to a simple bounded loop over at most three precomputed intervals.

### Error handling and edge cases

- Reject more than three times for a single schedule.
- Reject duplicate times within the same schedule.
- Reject invalid or malformed time values, consistent with existing `_schedule_time` validation.
- Reject an empty time selection.
- Two time slots of the same schedule that would overlap (including via duration) must not create overlapping active intervals on the valve; decide and document whether this is validated at creation or simply handled safely by the controller.
- Editing a schedule must not reset its `status`, `enabled`, or `weekdays` fields.
- The UI must prevent submission with zero times or more than three times.

## Test specification

### Unit tests

- [x] A schedule accepts one, two, or three valid times and preserves a deterministic order.
- [x] A schedule rejects a fourth time.
- [x] A schedule rejects duplicate times.
- [x] Invalid or empty time values raise `ValidationError`.
- [x] Time data survives `from_dict`/`to_dict` conversion.

### Integration tests

- [x] A schedule starts and stops correctly for each of its configured times independently.
- [x] A schedule with three times runs three separate intervals in a day.
- [x] Midnight-crossing behavior remains correct for each time slot.
- [x] Create and update commands persist all selected times.
- [x] The Node-RED create/edit/list flow sends and renders multiple times correctly.

### Regression tests

- [x] A schedule with a single configured time continues to run at that time.
- [x] Overlapping schedules on the same valve still do not turn the valve off early.
- [x] Manual valve activation remains unaffected.
- [x] Weekday filtering continues to apply to every time slot of a schedule.

### Test data and fixtures

- Use fixed dates/times with known weekdays instead of relying on the current system date.
- Include records with one, two, and three times.

## Acceptance criteria

The task is complete when:

- [x] The user can select up to three start times when creating a schedule.
- [x] The user can view and edit the selected times, and cannot add a fourth.
- [x] The automatic controller runs the schedule at every configured time.
- [x] Time input is validated at the domain boundary and malformed or excessive data cannot be persisted.
- [x] New and changed behavior is covered by specs.
- [x] Midnight-crossing, overlapping, enabled/disabled, and manual-control behavior remains correct.
- [x] The implementation is simple, readable, maintainable, and efficient for the expected number of schedules.
- [x] Formatting, linting, type checks, and the full test suite pass.
- [x] User-facing help and README examples are updated if the command syntax changes.

## Implementation checklist

- [x] Confirm the task number and filename.
- [x] Inspect all files listed in the impact analysis.
- [x] Reassess the affected files before coding and update this task if needed.
- [x] Decide and document the canonical multi-time representation before implementation.
- [x] Add or update specs before changing the execution logic.
- [x] Implement the smallest coherent change.
- [x] Run focused checks.
- [x] Run the full validation suite.
- [x] Validate the implementation against every acceptance criterion.
- [x] Move the issue to `done` only after implementation and validation pass.

## Notes

- The initial request is in Portuguese ("permitir que o usuário escolha mais de um horário para o agendamento, até 3"); the implementation task is intentionally written in English as required by the task-generation convention.
