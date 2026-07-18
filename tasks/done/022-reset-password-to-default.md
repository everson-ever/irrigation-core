# Reset Password to Default

## Metadata

```yaml
status: done
priority: medium
type: feature
```

## Title

Add a local-only CLI command to reset the admin password back to the
factory default

## Specification

Add an `irrigation auth reset-to-default` CLI subcommand that overwrites
the stored credential with `username: admin` /
`password: 10203040` (the same values as `DEFAULT_AUTH_USERNAME` /
`DEFAULT_AUTH_PASSWORD` in `src/irrigation/application/services.py:33-34`),
re-hashed the same way as any other password change. The command must only
be reachable by someone with local access to the Raspberry Pi running the
binary (shell/SSH) — it must **not** be exposed through the Node-RED
dashboard, any `exec` node, or any other network-reachable path, since
that would let an unauthenticated attacker on the network reset the admin
password remotely.

### Context

Today, if a user changes the password from the settings screen and
forgets it, there is no supported recovery path
(`tasks/done/016-authentication-and-password-management.md`, "Out of
scope", explicitly excluded password reset). The only self-healing
behavior is `AuthService.ensure_default_credentials()`
(`services.py:452-460`), which seeds the default credential **only when
the `credentials` table is empty** — it does nothing once a row already
exists. Today, recovering a lost password requires manually deleting the
row from `data/irrigation.db` with a raw SQLite client, which is
undocumented and error-prone (a mistaken `DELETE` on the wrong table, or
leaving the DB in an inconsistent state).

This task formalizes that recovery path as a proper CLI command instead of
requiring direct database surgery, while preserving the security property
that a password reset requires physical/local access to the device (SSH or
console), not just network access to the dashboard. This mirrors the
"physical reset button" pattern common on consumer routers/IoT devices:
you must be standing at the machine (or have shell access to it) to
reset it.

### Scope

#### In scope

- A new `AuthService.reset_to_default()` method that overwrites the
  existing credential row (or creates it if missing) with
  `DEFAULT_AUTH_USERNAME` / `DEFAULT_AUTH_PASSWORD`, hashed via the
  existing `_hash_password` helper.
- A new `irrigation auth reset-to-default` CLI subcommand wired through
  `_auth_command` and `create_parser` in `src/irrigation/cli.py`, callable
  only from a local shell (no Node-RED `exec` node, no dashboard button,
  no HTTP-reachable trigger of any kind).
- Documenting the recovery procedure (running the command over SSH/local
  console) in `README.md`, next to the existing default-credentials
  section, so it is discoverable by whoever operates the device.

#### Out of scope

- Any UI/dashboard button, Node-RED flow, or network-reachable trigger for
  the reset — this must stay a local-shell-only operation.
- Multi-user support, roles, or per-user reset flows (still a single
  shared admin account, per `016`).
- Rate limiting, confirmation prompts beyond argparse's normal behavior,
  or audit logging of resets — out of scope unless the acceptance
  criteria below require it.
- Changing `ensure_default_credentials()`'s existing "seed only if empty"
  behavior for first-run installs.

## Impact analysis

### Files to inspect

- `src/irrigation/application/services.py` — `AuthService`
  (lines 448-534), specifically `ensure_default_credentials()`
  (452-460), `change_password()` (468-493), and `_hash_password()`
  (502-518), as the direct pattern to follow for the new
  `reset_to_default()` method.
- `src/irrigation/cli.py` — `_auth_command` (125-139) and the `auth`
  subparser wiring in `create_parser` (210-217), as the pattern for adding
  the new `reset-to-default` action.
- `src/irrigation/bootstrap.py:51` — `Application.auth()` accessor used to
  obtain the `AuthService` instance in the CLI handler.
- `src/irrigation/infrastructure/sqlite_repository.py:47-51` — the
  `credentials` table schema (`id = 1` single-row constraint), to confirm
  `reset_to_default()` can reuse the existing `add`/`update` semantics
  used by `ensure_default_credentials()`/`change_password()`.
- `README.md:157-160, 198` — existing documentation of the default
  credentials, to extend with the recovery procedure.
- `node-red/flows.json` — confirm no `exec` node currently references
  `auth` subcommands other than `login`/`change-password`, so the new
  command is not accidentally wired into a dashboard-reachable flow.

### Files to change

- `src/irrigation/application/services.py` — add
  `AuthService.reset_to_default()`.
- `src/irrigation/cli.py` — add the `reset-to-default` action to the
  `auth` subparser and handle it in `_auth_command`.
- `README.md` — document the recovery procedure.

### Files to create

- None expected; this fits inside existing files following the
  `change_password`/`_auth_command` pattern.

### Dependencies and integration points

- CLI entry point only (`irrigation auth reset-to-default`), invoked
  directly on the device shell — no Node-RED wiring, no HTTP endpoint.

## Technical approach

### Design principles

- Keep each class and function focused on one responsibility.
- Depend on abstractions at architectural boundaries.
- Keep domain rules independent from infrastructure details.
- Prefer small, explicit interfaces and simple data flows.
- Avoid speculative abstractions, duplicated logic, and unrelated changes.

### Proposed changes

1. Add `AuthService.reset_to_default()`: look up the existing credential
   row via `_credential_for(DEFAULT_AUTH_USERNAME)` (or, if none exists
   under that username, fall back to the single existing row the same way
   `ensure_default_credentials()` does); `update()` (or `add()` if the
   table is empty) with `DEFAULT_AUTH_USERNAME` and
   `self._hash_password(DEFAULT_AUTH_PASSWORD)`.
2. Add an `auth_reset = auth_actions.add_parser("reset-to-default")` in
   `create_parser()`, and handle `args.action == "reset-to-default"` in
   `_auth_command` by calling `app.auth().reset_to_default()` and
   returning `{"reset": True}`.
3. Document the recovery step in `README.md`: running
   `irrigation auth reset-to-default` over SSH/local console restores
   `admin` / `10203040`, and this is intentionally not exposed on the
   dashboard.

### Performance considerations

- Expected complexity: `O(1)` — single-row read/update, same cost as
  `change_password()`.
- Performance risks: none; this is a rare, manual, local operation.
- Mitigation: not applicable.

### Error handling and edge cases

- Credentials table empty (fresh install, never logged in): behave like
  `ensure_default_credentials()` and insert the default row instead of
  updating.
- Username was changed away from `admin` in a prior interaction (not
  currently possible via `change_password`, which keeps the username
  fixed) — reset must still target the single existing row, not fail
  looking for a row named `admin` specifically.
- Running the command twice in a row must be idempotent (no error, same
  resulting credential).

## Test specification

### Unit tests

- [x] `AuthService.reset_to_default()` overwrites an existing changed
      password back to `DEFAULT_AUTH_PASSWORD`, and `verify("admin",
      "10203040")` succeeds afterward.
- [x] `AuthService.reset_to_default()` on an empty repository inserts the
      default credential (same effect as `ensure_default_credentials()`).
- [x] The password hash produced by `reset_to_default()` is generated via
      `_hash_password` (freshly salted), not a stored/static hash.

### Integration tests

- [x] `irrigation auth reset-to-default` CLI invocation resets the
      password, and a subsequent `irrigation auth login admin,10203040`
      returns `{"authenticated": true}`.
- [x] After reset, logging in with the previously-set (now stale) password
      returns `{"authenticated": false}`.

### Regression tests

- [x] Existing `test_auth_change_password_*` CLI tests
      (`tests/test_cli.py:619-650`) and `AuthService` tests
      (`tests/test_services.py:1405-1452`) continue to pass unchanged.

### Test data and fixtures

- Reuse the in-memory/temp-file SQLite repository fixtures already used in
  `tests/test_services.py` and `tests/test_cli.py` for `AuthService`.

## Acceptance criteria

The task is complete when:

- [x] The requested behavior is implemented.
- [x] Existing behavior remains unchanged outside the defined scope.
- [x] New and changed behavior is covered by specs.
- [x] Error cases and relevant edge cases are covered.
- [x] The implementation follows the project's architecture and SOLID
      principles.
- [x] The implementation is simple, readable, maintainable, and
      performant for the expected workload.
- [x] Formatting, linting, type checks, and the full test suite pass.
- [x] Documentation or user-facing examples are updated when needed.
- [x] No Node-RED flow, dashboard tab, or `exec` node exposes
      `reset-to-default` over the network.

## Implementation checklist

- [x] Confirm the task number and filename.
- [x] Inspect all files listed in the impact analysis.
- [x] Reassess the affected files before coding and update this task if
      needed.
- [x] Implement the smallest coherent change.
- [x] Add or update specs.
- [x] Run focused checks.
- [x] Run the full validation suite.
- [x] Validate the implementation against every acceptance criterion.
- [x] Move the issue to `done` only after implementation and validation
      pass.

## Notes

- This intentionally keeps the recovery path local-access-only (SSH/shell
  on the Raspberry Pi) rather than adding a network-reachable
  "forgot password" flow, since `016`'s out-of-scope note explicitly
  excludes remote password reset channels and this is a home device with
  no assumed connectivity for email/SMS-based recovery.
- Completed with 167 tests passing; Ruff lint and format checks also pass.
