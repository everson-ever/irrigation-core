# Task Template

> Use this template to turn a task specification into a small, maintainable, and testable implementation plan. Write the task in English.

## File naming convention

Save each task using the following format:

```text
NNN-short-kebab-case-description.md
```

Examples:

```text
001-support-multiple-days.md
002-fix-valve-schedule-validation.md
```

The number must be sequential and the description must be concise, lowercase, and written in English.

## Metadata

```yaml
status: backlog
priority: medium
type: feature
```

- `status`: `backlog`, `in_progress`, `blocked`, `done`, or `cancelled`
- `priority`: `low`, `medium`, `high`, or `critical`
- `type`: `feature`, `bug`, `refactor`, `maintenance`, `performance`, `documentation`, or `test`

New issues must always be created with `status: backlog`. After implementation,
the issue must be validated against all acceptance criteria. Move it to
`status: done` only after the implementation and validation are complete.

## Title

<!-- Use an imperative, concise title. -->

## Specification

<!-- Restate the requested behavior clearly and completely. -->

### Context

<!-- Explain why this task is needed and which problem it solves. -->

### Scope

#### In scope

-

#### Out of scope

-

## Impact analysis

### Files to inspect

<!-- List existing files that must be understood before implementation. -->

- `path/to/file.py` — reason for inspection

### Files to change

<!-- List the expected files and the responsibility of each change. -->

- `path/to/file.py` — planned change

### Files to create

<!-- List new files only when they represent a clear responsibility. -->

- `path/to/file.py` — purpose

### Dependencies and integration points

<!-- Describe APIs, domain ports, repositories, CLI entry points, configuration, or external systems affected. -->

-

## Technical approach

<!-- Describe the simplest implementation that satisfies the specification. -->

### Design principles

- Keep each class and function focused on one responsibility.
- Depend on abstractions at architectural boundaries.
- Keep domain rules independent from infrastructure details.
- Prefer small, explicit interfaces and simple data flows.
- Avoid speculative abstractions, duplicated logic, and unrelated changes.

### Proposed changes

1. 
2. 
3. 

### Performance considerations

<!-- State expected input size, relevant complexity, I/O behavior, and how unnecessary work will be avoided. -->

- Expected complexity: `O(?)`
- Performance risks:
- Mitigation:

### Error handling and edge cases

-

## Test specification

<!-- Add or update specs before considering the task complete. Prefer behavior-focused tests. -->

### Unit tests

- [ ]

### Integration tests

- [ ]

### Regression tests

- [ ]

### Test data and fixtures

-

## Acceptance criteria

The task is complete when:

- [ ] The requested behavior is implemented.
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
- [ ] Implement the smallest coherent change.
- [ ] Add or update specs.
- [ ] Run focused checks.
- [ ] Run the full validation suite.
- [ ] Validate the implementation against every acceptance criterion.
- [ ] Move the issue to `done` only after implementation and validation pass.

## Notes

<!-- Record decisions, assumptions, blockers, or follow-up tasks. -->

-
