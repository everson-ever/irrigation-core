# Fix Schedule Deletion from the Dashboard

## Metadata

```yaml
status: done
priority: high
type: bug
```

## Title

Make dashboard schedule deletion remove the selected record

## Specification

### Context

When a user confirms the deletion of a schedule in the Node-RED dashboard, the schedule may remain visible and persisted instead of being removed. The delete action crosses the dashboard template, the Node-RED routing and `exec` nodes, the CLI, the application service, and the JSON-lines repository. The action currently provides no reliable user-visible distinction between a successful deletion, a missing schedule, and a command failure.

### Scope

#### In scope

- Ensure that confirming deletion sends the selected schedule identifier without ambiguity.
- Ensure that the Node-RED flow invokes the CLI delete command with the correct identifier.
- Ensure that a successful deletion is persisted and the dashboard refreshes from the current schedule file.
- Surface or handle command and validation failures so a failed deletion is not presented as a successful action.
- Define safe behavior when the selected schedule no longer exists before the delete request is processed.
- Prevent deletion of an active schedule from leaving its valve running or its runtime state inconsistent.

#### Out of scope

- Redesigning schedule creation, editing, enabling, or manual valve controls.
- Changing schedule recurrence, duration, or validation rules unrelated to deletion.
- Replacing the JSON-lines repository or the Node-RED dashboard framework.
- Adding bulk deletion or undo functionality.

## Impact analysis

### Files to inspect

- `node-red/flows.json` — delete confirmation, identifier propagation, `exec` wiring, refresh flow, and dashboard feedback.
- `src/irrigation/cli.py` — delete argument parsing, command invocation, exit status, and serialized result.
- `src/irrigation/application/services.py` — schedule deletion behavior and cleanup of active schedule state.
- `src/irrigation/infrastructure/json_repository.py` — delete semantics, missing-record behavior, and atomic persistence.
- `tests/test_repository.py` — existing repository deletion behavior and missing identifier cases.
- `tests/test_services.py` — schedule lifecycle, valve state, and controller behavior needed for active deletion regression coverage.
- `README.md` — documented schedule deletion command and any user-facing behavior that needs clarification.

### Files to change

- `node-red/flows.json` — correct the delete request/response path, refresh the list only after a valid result, and expose a useful failure state in the dashboard.
- `src/irrigation/cli.py` — preserve a deterministic success/failure contract for schedule deletion and validate the identifier at the command boundary when required.
- `src/irrigation/application/services.py` — implement the smallest safe deletion behavior, including cleanup for an active schedule if the service boundary requires it.
- `tests/test_repository.py` — cover persistence and result behavior for successful and missing-record deletion.
- `tests/test_services.py` — cover deletion of inactive and active schedules, including valve and schedule state cleanup.
- `tests/test_cli.py` — add command-level coverage for the delete argument and result contract if a CLI test module is introduced during implementation.
- `README.md` — update deletion behavior or troubleshooting information if the command contract changes.

### Files to create

- `tests/test_cli.py` — purpose-focused coverage for schedule deletion argument handling and command results, only if existing test organization does not provide a suitable location.

### Dependencies and integration points

- The dashboard template sends a deletion action containing the schedule `id` to the `Roteia ações da tabela de agendamentos` function node.
- The Node-RED `exec` node invokes `/opt/irrigation/bin/irrigation schedule delete` and must pass the identifier as one CLI argument.
- `ScheduleService.delete` delegates persistence to `JsonLinesRepository.delete`.
- The scheduler and Node-RED processes can access the same `data/schedules.json`; refresh behavior must observe atomic writes from the repository.
- If an active schedule can be deleted, the valve service/GPIO state and automatic controller runtime state must be coordinated so deletion cannot leave irrigation running unexpectedly.

## Technical approach

### Design principles

- Keep the dashboard responsible for interaction and presentation, not persistence rules.
- Keep identifier validation and deletion semantics explicit at the application boundary.
- Reuse the repository's atomic write and cross-process cache invalidation behavior.
- Treat command exit status and stderr as part of the integration contract.
- Prefer observable behavior tests over assertions on Node-RED or service internals.
- Avoid changing unrelated schedule actions or introducing a new deletion abstraction.

### Proposed changes

1. Trace the confirmed delete payload through the dashboard template, router, and `exec` node, then normalize it to a non-empty schedule identifier passed as exactly one CLI argument.
2. Define and implement the delete result contract: successful deletion must be distinguishable from a missing identifier, a missing record, and an execution/validation error.
3. Make the dashboard reload schedules only from the refreshed persisted data after the delete command completes, and show an actionable error when deletion fails.
4. If an active schedule is deletable, stop the associated valve when no other active schedule requires it, clear the schedule's runtime state, and preserve overlapping-schedule behavior.
5. Add focused repository, service, CLI, and flow-level regression coverage for successful deletion, stale selections, malformed identifiers, refresh behavior, and active/overlapping schedules.
6. Run focused tests and the complete formatting, linting, and test validation suite.

### Performance considerations

- Expected complexity: `O(n)` for the repository rewrite and `O(n)` for checking other schedules that may keep a shared valve active, where `n` is the number of schedules.
- Performance risks: unnecessary repeated file reads or refresh loops after a delete command.
- Mitigation: rely on the repository's atomic replacement and cache detection, perform one refresh after command completion, and keep cleanup checks limited to the existing schedule collection.

### Error handling and edge cases

- Reject an empty, missing, non-scalar, or malformed schedule identifier before invoking persistence.
- Deleting an existing inactive schedule removes exactly that record and returns success.
- Deleting an already-removed schedule must not silently report that a record was deleted.
- A failed CLI command must not cause the dashboard to discard or hide the current schedule list.
- The final remaining schedule must render the dashboard's empty state after successful deletion.
- Deleting an active schedule must not leave its valve on; a valve shared with another active schedule must remain on until the other schedule ends.
- Repeated delete requests must be idempotent from the hardware's perspective and must not create duplicate refreshes or errors.
- Concurrent scheduler/UI writes must preserve valid JSON-lines data.

## Test specification

### Unit tests

- [x] Schedule deletion accepts a valid identifier and removes the matching record.
- [x] Empty and malformed identifiers are rejected with a clear validation error.
- [x] A missing schedule produces an explicit not-found or no-op result according to the chosen contract.
- [x] Deleting an active schedule clears its runtime state and stops its valve when no other schedule needs it.

### Integration tests

- [x] A dashboard delete action is transformed into `schedule delete <id>` with the selected schedule's identifier.
- [x] A successful CLI deletion persists the removal and returns a success result.
- [x] The Node-RED refresh displays the updated list, including the empty state when the last schedule is removed.
- [x] CLI and flow failures leave the existing list intact and expose an actionable error.
- [x] Deleting one of overlapping active schedules does not turn off a valve required by another schedule.

### Regression tests

- [x] Existing schedule creation, editing, enabling/disabling, and manual valve actions remain unchanged.
- [x] Repository writes remain valid JSON lines and remain visible across separate repository instances.
- [x] Automatic scheduling can continue to start and stop remaining schedules after a deletion.
- [x] Repeated deletion of the same identifier does not alter unrelated records or hardware state.

### Test data and fixtures

- Use temporary JSON-lines repositories containing one inactive schedule, one active schedule, and two overlapping schedules on the same valve.
- Use the existing mock GPIO and deterministic clock fixtures for active-schedule cleanup.
- Use representative dashboard payloads with string and numeric-looking identifiers, plus empty and missing identifiers.
- Assert persisted records, CLI output/exit status, refresh payloads, GPIO operations, and user-visible error routing where the test harness supports them.

## Acceptance criteria

The task is complete when:

- [x] Confirming deletion removes the selected schedule from persistent storage.
- [x] The identifier sent by the dashboard is the identifier used by the CLI and repository, without accidental coercion or loss.
- [x] The dashboard refreshes from the current persisted schedule list after successful deletion.
- [x] The dashboard does not report or display a successful deletion when the command fails or the record is missing.
- [x] Deleting the last schedule displays the empty-state view.
- [x] Deleting an active schedule cannot leave its valve running, while overlapping schedules continue to protect a valve they still require.
- [x] New and changed behavior is covered by focused and regression specs.
- [x] Existing behavior remains unchanged outside the defined deletion scope.
- [x] The implementation follows the project's architecture and keeps responsibilities separated across UI, CLI, application, and persistence layers.
- [x] Formatting, linting, type checks, and the full test suite pass.
- [x] Documentation or user-facing troubleshooting is updated when the command or feedback contract changes.

## Implementation checklist

- [x] Confirm the task number and filename.
- [x] Inspect all files listed in the impact analysis.
- [x] Reproduce the failed dashboard deletion and identify the failing boundary.
- [x] Reassess the affected files before coding and update this task if needed.
- [x] Define the success, missing-record, and failure result contract.
- [x] Add or update specs before changing production or flow logic.
- [x] Implement the smallest coherent change.
- [x] Verify persistence and cross-process refresh behavior.
- [x] Run focused checks.
- [x] Run the full validation suite.
- [x] Validate the implementation against every acceptance criterion.
- [x] Move the issue to `done` only after implementation and validation pass.

## Notes

- The request was made in Portuguese; this task is intentionally written in English to follow the repository task convention.
- The reported symptom is user-facing. The exact failing boundary must be confirmed during implementation rather than assumed from the current flow definition.
