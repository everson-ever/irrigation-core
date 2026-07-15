# Validate Automatic Irrigation Scheduling Flow

## Metadata

```yaml
status: backlog
priority: high
type: test
```

## Title

Validate that scheduled irrigation turns valves on and off automatically

## Specification

### Context

The application supports scheduled irrigation, but the complete runtime flow must be verified: when the scheduled time is reached, the configured valve must turn on automatically and, after the configured duration, turn off automatically. Reliable coverage is needed to prevent regressions in the scheduler, valve state, persistence, and execution history.

### Scope

#### In scope

- Validate the end-to-end automatic execution of an enabled irrigation schedule.
- Confirm that the configured valve is switched on at the scheduled start time.
- Confirm that the same valve is switched off when the scheduled interval ends.
- Confirm that schedule and valve statuses are persisted correctly after each transition.
- Confirm that the automatic execution records the expected history entry.
- Cover late scheduler cycles, disabled schedules, and schedules that cross midnight where supported by the current behavior.

#### Out of scope

- Changing the schedule domain model or scheduling rules.
- Adding new scheduling capabilities such as date ranges or weekday selection.
- Testing manual valve activation beyond ensuring it is not changed by the automatic flow.
- Hardware-in-the-loop testing with physical GPIO equipment.

## Impact analysis

### Files to inspect

- `src/irrigation/application/services.py` — automatic controller transitions, valve commands, and history recording.
- `src/irrigation/domain/models.py` — schedule interval and status behavior.
- `src/irrigation/infrastructure/clock.py` — controllable time source used by the scheduler.
- `src/irrigation/infrastructure/gpio.py` — GPIO abstraction and test double behavior.
- `tests/test_services.py` — existing automatic scheduler, valve, overlap, and restart specifications.
- `tests/test_models.py` — schedule interval and midnight-crossing specifications.
- `tests/test_repository.py` — persistence behavior for schedule and valve state.
- `README.md` — documented scheduler behavior and validation commands.

### Files to change

- `tests/test_services.py` — add behavior-focused tests for the complete scheduled start and stop lifecycle and its persisted side effects.
- `tests/test_models.py` — add or adjust interval cases only if the validation exposes an uncovered domain edge case.
- `tests/test_repository.py` — add persistence assertions only if the existing repository coverage does not verify the required state transitions.
- `src/irrigation/application/services.py` — correct scheduler, valve, or history behavior if the validation exposes a production defect.
- `src/irrigation/domain/models.py` — correct interval behavior only if the validation exposes a domain defect.

### Files to create

- None expected. Keep the validation close to the existing scheduler service specifications.

### Dependencies and integration points

- `AutomaticController` coordinates schedule evaluation, `ValveService`, the GPIO abstraction, and history persistence.
- Tests must use the existing fake clock and mock GPIO instead of physical hardware or wall-clock sleeps.
- Schedule and valve records are persisted through the JSON-lines repositories.

## Technical approach

### Design principles

- Test observable behavior and state transitions rather than private implementation details.
- Use deterministic time progression with the existing clock abstraction.
- Keep each test focused on one scheduling rule and its externally visible effects.
- Reuse existing fixtures and test doubles before introducing new helpers.
- Do not alter production behavior unless a failing acceptance criterion identifies a real defect.

### Proposed changes

1. Inspect the controller lifecycle and existing fixtures to define the exact scheduler-cycle contract.
2. Add a deterministic test that creates an enabled schedule, advances time into its interval, runs the controller, and verifies the valve GPIO/state, schedule status, and history start event.
3. Advance time beyond the interval, run the controller again, and verify the valve is switched off, the schedule status is reset, and the history end event is persisted.
4. Add regression cases for a scheduler cycle that starts after the configured time, disabled schedules, overlapping schedules on the same valve, interrupted schedules, and midnight-crossing intervals as applicable.
5. If any test exposes incorrect production behavior, implement the smallest coherent fix, add a regression test for it, and rerun the affected validation.
6. Run focused tests followed by formatting, linting, type checks, and the full test suite.

### Performance considerations

- Expected complexity: `O(n)` per scheduler cycle, where `n` is the number of schedules.
- Performance risks: none expected from tests; avoid real-time waiting and unnecessary repository reloads in test helpers.
- Mitigation: use fixed timestamps, fake time, and in-memory or temporary repositories.

### Error handling and edge cases

- An enabled schedule must not turn on before its interval begins.
- A schedule must turn off once its end time is reached, including exact-boundary timestamps.
- A disabled schedule must not turn on and must stop an active run when appropriate.
- An already-running schedule must not be started twice by repeated controller cycles.
- Overlapping schedules must keep a shared valve on until no active schedule requires it.
- Midnight-crossing schedules must remain active across the calendar-day boundary and stop at the correct end time.
- Test failures must distinguish incorrect GPIO calls from incorrect persisted status or history.

## Test specification

### Unit tests

- [ ] A schedule is recognized as running inside its configured interval and not outside it.
- [ ] Exact start and end boundaries produce the expected running state.
- [ ] A midnight-crossing schedule calculates the correct active interval.

### Integration tests

- [ ] An enabled schedule turns the configured valve on automatically at its scheduled time.
- [ ] The controller turns the valve off automatically after the configured duration.
- [ ] Schedule and valve statuses are persisted after both transitions.
- [ ] Automatic start and stop events are written to irrigation history.
- [ ] A late scheduler cycle starts an active schedule without waiting for the exact minute.

### Regression tests

- [ ] Disabled schedules never turn a valve on.
- [ ] Repeated scheduler cycles do not duplicate starts or history entries.
- [ ] Overlapping schedules do not turn a shared valve off before the final schedule ends.
- [ ] An interrupted active schedule reactivates hardware when the interval is still valid.
- [ ] Manual valve behavior remains unchanged.

### Test data and fixtures

- Use a fixed clock and a temporary schedules, valves, and history repository.
- Include an enabled schedule with a short duration, an enabled schedule crossing midnight, and a disabled schedule.
- Assert both recorded GPIO operations and persisted JSON-compatible records.

## Acceptance criteria

The task is complete when:

- [ ] The complete automatic scheduling flow is covered from start through stop.
- [ ] Tests prove that the valve turns on at the correct time and off at the correct end time.
- [ ] Any defect found during validation is corrected and covered by a regression test.
- [ ] Persisted schedule and valve states are verified after each transition.
- [ ] Automatic history records are verified.
- [ ] Relevant late-start, disabled, overlapping, interrupted, and midnight-crossing cases are covered.
- [ ] No physical hardware or nondeterministic time waits are required.
- [ ] Existing behavior remains unchanged outside the defined validation scope.
- [ ] Formatting, linting, type checks, and the full test suite pass.

## Implementation checklist

- [ ] Confirm the task number and filename.
- [ ] Inspect all files listed in the impact analysis.
- [ ] Reassess the affected files before coding and update this task if needed.
- [ ] Add or update specs before changing production code.
- [ ] Implement the smallest coherent test and, when needed, production fix required by the specs.
- [ ] Add regression coverage for every problem found during validation.
- [ ] Run focused checks.
- [ ] Run the full validation suite.
- [ ] Validate the implementation against every acceptance criterion.
- [ ] Move the issue to `done` only after implementation and validation pass.

## Notes

- The task was requested in Portuguese; it is written in English to follow the repository task convention.
