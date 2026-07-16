```yaml
status: done
priority: medium
type: refactor
```

# Refactor core services for SOLID, single-responsibility, and reduced duplication

## Specification

Refactor the internal structure of `irrigation.application.services`, `irrigation.cli`, and related modules to
improve adherence to SOLID principles, remove duplicated logic, and reduce oversized methods/classes and unclear
naming. This is a pure refactor: **no observable behavior may change** — same public method signatures, same
return values, same JSON output, same exit codes, same exception types and messages, same side-effect ordering
(e.g. when history is recorded relative to status updates).

The existing test suite (`tests/test_services.py`, `tests/test_cli.py`, `tests/test_models.py`,
`tests/test_repository.py`) is the behavioral contract for this task and must pass unmodified in assertions
(only new tests may be added, existing ones must not need their expectations changed).

### Context

The codebase already follows a clean hexagonal layout (`domain` / `application` / `infrastructure`) and is
generally small, but several hotspots have grown past a single responsibility as features were added
incrementally (multi-day schedules, manual override tracking, restart-after-crash handling):

- `IrrigationController.run_once()` (`src/irrigation/application/services.py:466`) is ~55 lines with deeply
  nested conditionals mixing three concerns: computing which schedules/valves are "active", deciding whether to
  start/restart/stop each schedule, and applying the side effects.
- `ManualControlService.turn_on()` (`src/irrigation/application/services.py:335`) mixes state-transition logic,
  schedule-status synchronization, history recording, and a blocking wait loop in one method.
- The `self._schedules is None: return False/None` guard is repeated verbatim in four `ManualControlService`
  private methods (`_has_cancelled_automatic_interval`, `_clear_expired_schedule_statuses`,
  `_set_manual_schedule_status`, `_has_other_running_schedule_on_valve`).
- `ValveService` repeats the `self._repository.update(replace(valve, ...).to_dict())` pattern five times with no
  shared helper.
- `cli.py` defines `_csv` and `_csv_range` (`src/irrigation/cli.py:16-32`), where `_csv_range` is a strict
  generalization of `_csv` (a single expected field count vs. a tuple of allowed counts) — the two duplicate the
  split/strip/validate logic instead of one delegating to the other.
- `cli._dispatch()` (`src/irrigation/cli.py:90`) is a single ~65-line function branching on `args.command` and
  `args.action` via a long `if/elif` chain, which must be edited (and grows in size) every time a command is
  added, working against the open/closed principle.
- Mode labels used for history entries (`"Manual"`, `"Automatic"`, `"Automatic: started after scheduled time"`,
  `"Restarted"`) are scattered as string literals across `IrrigationController` and compared against in
  `HistoryService`, instead of being defined once.
- `services.py` defines its own full-name weekday tuple `WEEKDAYS` (`"Monday"`...`"Sunday"`) while
  `domain/models.py` defines the abbreviated `WEEKDAY_IDS` (`"mon"`...`"sun"`); the near-identical names for two
  different representations are easy to confuse when reading call sites.

Cleaning these up now — while the project is still small — keeps `run_once` and `turn_on` reviewable in one
screen, makes future feature additions (another schedule mode, another CLI command) touch less code, and lowers
the chance that a fix applied to one duplicated call site is forgotten in the others.

### Scope

#### In scope

- Extracting private helper methods to shrink `IrrigationController.run_once()` and
  `ManualControlService.turn_on()` into short orchestrating methods, without changing the public API of either
  class.
- Introducing a shared private save/update helper in `ValveService` (and, if it removes duplication without
  forcing an awkward abstraction, in `ScheduleService`) to remove the repeated `replace(...).to_dict()` +
  `repository.update(...)` pattern.
- Consolidating the repeated `self._schedules is None` guard in `ManualControlService` into one place.
- Merging `_csv` and `_csv_range` in `cli.py` into a single function.
- Restructuring `cli._dispatch()` into smaller per-command handlers (e.g. a dispatch table keyed by
  `args.command`), preserving identical argument parsing, output, and error behavior.
- Naming clean-up which does not change any public signature: e.g. renaming `services.WEEKDAYS` to something
  that reads unambiguously next to `models.WEEKDAY_IDS` (e.g. `WEEKDAY_NAMES`), and replacing the scattered
  history mode string literals with named module-level constants.
- Splitting overly long private helper methods identified above into smaller, well-named ones.

#### Out of scope

- Any change to public method signatures, return shapes, CLI arguments, JSON field names, or exception
  messages.
- `JsonLinesRepository` (`src/irrigation/infrastructure/json_repository.py`): its length comes from
  documented, load-bearing crash-safety/atomicity logic (file locking, torn-line tolerance, stat-based
  caching); refactoring it carries real concurrency risk for a purely cosmetic gain and is not included here.
- Changing `ScheduleService.delete(record_id, valves=None)`'s cross-service collaboration (it is exercised
  directly by tests with a positional `valves` argument — see `tests/test_services.py:708`); revisiting how
  `ScheduleService` coordinates with `ValveService` is a design change, not a like-for-like refactor, and should
  be a separate task if pursued.
- Any new feature, bug fix, or performance optimization.
- Renaming public keyword arguments such as `manual=`, `force_hardware=`, `preserve_manual_stop=` on
  `ValveService`/`ManualControlService` methods — they are internal but changing them is unnecessary churn for
  this task.

## Impact analysis

### Files to inspect

- `src/irrigation/application/services.py` — contains all the classes targeted by this refactor
  (`ScheduleService`, `ValveService`, `HistoryService`, `ManualControlService`, `IrrigationController`).
- `src/irrigation/domain/models.py` — defines `WEEKDAY_IDS`; needed to confirm the naming clash with
  `services.WEEKDAYS` and to keep the two concepts clearly distinguished.
- `src/irrigation/cli.py` — contains `_csv`, `_csv_range`, and `_dispatch`.
- `tests/test_services.py` — establishes the exact behavior of `IrrigationController.run_once`,
  `ManualControlService.turn_on/turn_off`, and `ValveService`/`ScheduleService` that must be preserved.
- `tests/test_cli.py` — establishes exact CLI argument parsing, exit codes, and JSON output that must be
  preserved through the `_dispatch` restructuring.

### Files to change

- `src/irrigation/application/services.py` — extract helper methods in `IrrigationController` and
  `ManualControlService`; add a shared save helper in `ValveService`; replace scattered mode string literals
  with named constants; rename `WEEKDAYS` for clarity.
- `src/irrigation/cli.py` — merge `_csv`/`_csv_range`; split `_dispatch` into per-command handlers.

### Files to create

- None expected. Prefer extracting private methods/constants within existing modules over introducing new
  files or abstractions, per the project's own guidance against speculative abstractions.

### Dependencies and integration points

- No changes to the `Repository`, `GpioController`, or `Clock` ports (`src/irrigation/domain/ports.py`).
- No changes to `bootstrap.Application` wiring.
- No changes to the Node-RED flow or systemd units, since CLI input/output must stay identical.

## Technical approach

### Design principles

- Keep each class and function focused on one responsibility.
- Depend on abstractions at architectural boundaries.
- Keep domain rules independent from infrastructure details.
- Prefer small, explicit interfaces and simple data flows.
- Avoid speculative abstractions, duplicated logic, and unrelated changes.

### Proposed changes

1. Decompose `IrrigationController.run_once()` into a short orchestrating loop plus named private methods that
   each answer one question, e.g. `_is_blocked_by_manual_override(schedule, valve, now)`,
   `_should_start(schedule, now)`, `_should_restart(schedule)`, `_should_stop(schedule, now, active_manual)`,
   keeping `_start`/`_stop` as they are today.
2. Decompose `ManualControlService.turn_on()` into named steps (computing `preserve_manual_stop`, applying the
   valve/schedule state change, recording history, waiting) so the method body reads as a short sequence of
   calls; keep `_wait_for_auto_turn_off` as is.
3. Add a single private helper in `ValveService` (e.g. `_save(valve: Valve)`) that wraps
   `self._repository.update(valve.to_dict())`, and route the five existing call sites through it.
4. Consolidate the repeated `if self._schedules is None: return ...` guard in `ManualControlService` into one
   place (e.g. a single private accessor or early-return decorator/helper), removing the duplicated condition
   from `_has_cancelled_automatic_interval`, `_clear_expired_schedule_statuses`, `_set_manual_schedule_status`,
   and `_has_other_running_schedule_on_valve`.
5. Replace the history mode string literals (`"Manual"`, `"Automatic"`,
   `"Automatic: started after scheduled time"`, `"Restarted"`) with module-level constants shared between
   `IrrigationController` and `HistoryService`.
6. Rename `services.WEEKDAYS` to a name that is unambiguous next to `models.WEEKDAY_IDS` (e.g.
   `WEEKDAY_NAMES`), updating its single use site in `HistoryService.record`.
7. Merge `cli._csv` and `cli._csv_range` into one function that accepts either a single expected count or a
   tuple of allowed counts, and update the four call sites accordingly.
8. Replace `cli._dispatch`'s `if/elif` chain with one short per-command handler function per top-level command
   (`run`, `schedule`, `valve`, `settings`, `history`), and a small dispatch table or `match` statement in
   `_dispatch` that only selects and calls the right handler — the existing `schedule`/`valve` sub-branching
   moves into the relevant handler function.

### Performance considerations

- Expected complexity: `O(n)` per operation, unchanged — this task only reorganizes code, it does not alter
  loops, data structures, or I/O patterns.
- Performance risks: none expected; extracting methods keeps the same operations in the same order.
- Mitigation: preserve the exact order of repository reads/writes and hardware calls when splitting methods,
  since some tests assert on call ordering and side-effect sequencing (e.g. history recorded before/after a
  status flip).

### Error handling and edge cases

- Exception types and messages raised by `ValidationError`/`RecordNotFoundError`/`HardwareError` must stay
  identical, since `cli.execute` matches on `IrrigationError` and prints the message verbatim.
- The order in which `ManualControlService.turn_on`/`IrrigationController.run_once` mutate valve status,
  schedule status, and history must not change, since several tests assert on the resulting state combination
  after a single call.
- CLI argument validation errors (wrong field counts, unknown actions) must keep the same `ValueError` messages
  used by `tests/test_cli.py`.

## Test specification

No new behavior is introduced, so no new test *cases* are required; the existing suite is the safety net. Add
characterization coverage only where a private helper becomes complex enough that the existing public-API tests
would not clearly pinpoint a regression in it.

### Unit tests

- [x] Confirm `tests/test_services.py` still passes unmodified against the refactored `IrrigationController`,
      `ManualControlService`, `ValveService`, and `ScheduleService`.
- [x] Confirm `tests/test_models.py` is unaffected (no changes planned in `domain/models.py` beyond none — this
      task does not touch it, listed here only as a safety check).

### Integration tests

- [x] Confirm `tests/test_cli.py` still passes unmodified against the restructured `_dispatch`, including exit
      codes and JSON output for every command.
- [x] Confirm `tests/test_repository.py` is unaffected (no changes planned in `json_repository.py`).

### Regression tests

- [x] Run the full test suite before and after the refactor and confirm identical pass/fail results with no
      assertion changes.
- [x] Manually diff CLI output for one representative call per command (`schedule list`, `schedule create`,
      `valve ... --no-wait`, `settings`, `history day,,`) before and after, to catch any accidental formatting
      drift not covered by existing assertions.

### Test data and fixtures

- No new fixtures needed; reuse the existing in-memory/mock repositories and `MockGPIO` already used by
  `tests/test_services.py` and `tests/test_cli.py`.

## Acceptance criteria

The task is complete when:

- [x] `IrrigationController.run_once()` and `ManualControlService.turn_on()` are each reduced to a short
      orchestrating body delegating to well-named private helpers.
- [x] The duplicated `replace(valve, ...).to_dict()` + `repository.update(...)` pattern in `ValveService` is
      expressed through a single private helper.
- [x] The repeated `self._schedules is None` guard in `ManualControlService` exists in exactly one place.
- [x] History mode strings are defined once as named constants and reused, not duplicated as literals.
- [x] `cli._csv`/`cli._csv_range` are merged into one function with no duplicated validation logic.
- [x] `cli._dispatch` no longer contains one large `if/elif` chain; each command is handled by its own
      function.
- [x] No public method signature, CLI argument, JSON output shape, exit code, or exception message changed.
- [x] Existing behavior remains unchanged outside the defined scope.
- [x] The full existing test suite passes without modifying any existing assertion.
- [x] Formatting, linting, and type checks (ruff, mypy, as configured in the project) pass.
- [x] No documentation changes are needed, since no user-facing behavior changes.

## Implementation checklist

- [x] Confirm the task number and filename.
- [x] Inspect all files listed in the impact analysis.
- [x] Reassess the affected files before coding and update this task if needed.
- [x] Implement the smallest coherent change per proposed-changes item, running the full test suite after each
      one before moving to the next.
- [x] Add characterization tests only if a specific extracted helper is judged non-obvious enough to warrant
      direct coverage.
- [x] Run focused checks (`pytest tests/test_services.py`, `pytest tests/test_cli.py`).
- [x] Run the full configured validation suite (`pytest` and `ruff check`; this project has no mypy dependency
      or configuration).
- [x] Validate the implementation against every acceptance criterion.
- [x] Move the issue to `status: done` only after implementation and validation pass.

## Notes

- This task is deliberately scoped to the highest-value, lowest-risk cleanups. `ScheduleService.delete`'s
  optional `valves` collaborator parameter is a legitimate SRP smell (a schedule use case reaching into valve
  hardware state) but changing it means changing a signature exercised directly by tests
  (`tests/test_services.py:708`) — that is a design change, not a behavior-preserving refactor, and should be
  proposed as its own task if the team wants to pursue it.
- `JsonLinesRepository` is intentionally excluded: its size is justified by crash-safety comments already in
  the file, and splitting it up is a higher-risk change than the rest of this task for little readability gain.
