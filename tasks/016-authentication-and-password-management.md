# Authentication and Password Management

## Metadata

```yaml
status: backlog
priority: critical
type: feature
```

## Title

Require authentication to access the dashboard, ship a default admin
credential, and let it be changed from a settings menu

## Specification

The system must not be usable without authenticating first. It must ship
with a default username `admin` and default password `10203040`, and the
interface must provide a way to change that password (a settings/security
menu). It must not be possible to reach any dashboard page or trigger any
irrigation action without first providing valid credentials.

### Context

There is currently **no authentication anywhere** in this project:

- The Node-RED dashboard (`node-red/flows.json`, served at
  `http://<pi-ip>:1880/ui`) has no `ui_tab` gating, no login form, and no
  `httpNodeAuth`/`adminAuth` configuration. Anyone on the network can open
  the dashboard and control valves, schedules, and history.
- `docker-compose.yml:25-29` starts Node-RED with `--userDir /node-red-data
  --flowFile /app/node-red/flows.json` and no `settings.js`, so there is no
  HTTP-level protection in front of `/ui` either in dev or in the
  deployment described in `deploy/package-readme.md`.
- The Python backend (`src/irrigation/`) exposes no web/API layer at all —
  it's a plain argparse CLI (`src/irrigation/cli.py`, subcommands `run`,
  `schedule`, `valve`, `settings`, `history`) invoked by Node-RED's `exec`
  nodes (see the `exec` nodes calling
  `/opt/irrigation/bin/irrigation settings ...` etc. in `flows.json`). There
  is no concept of a user, a password, or a session anywhere in the code or
  database schema (`src/irrigation/infrastructure/sqlite_repository.py:14-58`).
- There is a `settings` table (`sqlite_repository.py:41-45`) but it only
  stores `default_duration_minutes`; there is precedent for a single-row
  settings table and for a hidden dashboard tab used to edit it (the
  `ui_tab` "Tempo padrão para desligar" is currently `disabled: true,
  hidden: true` in `flows.json`), but no credentials table exists.

Since this is a home irrigation controller reachable on the local network
(and potentially port-forwarded/exposed by the installer), letting anyone
open the dashboard and operate valves without a password is a real security
gap. This task adds a minimal authentication layer appropriate for this
CLI + Node-RED-dashboard architecture — no web framework is being
introduced.

### Scope

#### In scope

- A default account (`username: admin`, `password: 10203040`) available the
  first time the system runs, without any manual setup step.
- Storing the credential (hashed, never plaintext) in the existing SQLite
  database, following the codebase's single-row-table pattern already used
  for `settings`.
- A login screen that must be passed before any dashboard tab
  (Agendamentos, Novo Agendamento, Histórico, and the settings tab) is
  reachable or renders live data.
- A "Configurações"/security menu where the logged-in user can change the
  password (current password + new password + confirmation).
- Backend support (CLI subcommand(s) and a service, following the existing
  `SettingsService`/`ScheduleService` pattern) to verify a password and to
  change it, with hashing done via the Python standard library (no new
  dependency — `pyproject.toml:11` currently declares `dependencies = []`
  and the binary is Nuitka-compiled for the Raspberry Pi, per
  `scripts/build-binary.sh`/`deploy/package-readme.md`).
- Deciding and implementing the actual access-control boundary (see
  "Technical approach" — this needs investigation, since Node-RED
  dashboards can be gated at the HTTP/websocket level via
  `httpNodeAuth`/`adminAuth` in `settings.js`, or at the flow level).
  Whatever is chosen must make it impossible to load dashboard data without
  authenticating first — hiding tabs with client-side Angular logic alone
  is **not** sufficient, since the underlying exec-backed endpoints would
  still be reachable.
- Migrating existing installs: an existing `data/irrigation.db` without a
  credentials table must get the default account seeded automatically on
  first run after the upgrade, the same way `settings`/`schedules` are
  auto-migrated today (`deploy/package-readme.md:77-80`,
  `src/irrigation/infrastructure/json_migration.py`).

#### Out of scope

- Multi-user support, roles/permissions, or per-user audit trails — a
  single shared admin account is sufficient for this task.
- Password reset via email/SMS or any external channel (there is no
  connectivity assumption for this system).
- Rate limiting / lockout after repeated failed attempts, 2FA, or other
  hardening beyond "must authenticate" and "password is stored hashed".
  (Worth a follow-up task, not required here.)
- Encrypting the SQLite database at rest.
- Changing how valves/schedules/history behave once authenticated.

## Impact analysis

### Files to inspect

- `src/irrigation/infrastructure/sqlite_repository.py` — `SCHEMA` (lines
  14-58) and `_TABLE_COLUMNS` (lines 60-64) to see how a new table is added
  and wired into the generic `SqliteRepository`; `ScheduleSqliteRepository`
  as the example of a repository with custom logic beyond the generic one.
- `src/irrigation/application/services.py` — `SettingsService` (lines
  336-358) as the direct pattern to follow for a single-row credentials
  table (`list_all()`/`add`/`update` semantics).
- `src/irrigation/bootstrap.py` — `Application` (lines 28-74),
  specifically `runtime_settings()` (lines 44-45), to see where a new
  `auth()`/`credentials()` accessor would be wired.
- `src/irrigation/cli.py` — `_settings_command` (lines 94-101),
  `_COMMAND_HANDLERS` (lines 116-122), and `create_parser` (lines
  125-156) as the pattern for adding new `auth login`/`auth
  change-password` subcommands.
- `src/irrigation/infrastructure/json_migration.py` — how legacy data is
  auto-imported/seeded on first run, as the model for seeding the default
  admin/10203040 credential on first run or on upgrade of an existing
  database.
- `node-red/flows.json` — all `ui_tab`/`ui_group` nodes (search for
  `"type": "ui_tab"`), the hidden "Tempo padrão para desligar" tab/group
  (`disabled: true, hidden: true`) as an example settings tab, the
  `ui_form` node feeding "Atualizar configurações"
  (`92612eb4.8c939`)/"Configurações cadastradas" (`d19f016a.a6ac8`) exec
  nodes as the pattern for a password-change form bound to a new CLI exec
  command, and how `exec` nodes invoke
  `/opt/irrigation/bin/irrigation ...`.
- `docker-compose.yml` — how Node-RED is launched in dev (no `settings.js`
  today) if the chosen approach requires one.
- `deploy/package-readme.md` and `deploy/systemd/*` — deployment/upgrade
  flow, to document the default credential and any new install/upgrade
  step.
- `tests/test_services.py` — existing service test patterns to extend for
  the new credentials service.

### Files to change

- `src/irrigation/infrastructure/sqlite_repository.py` — add a
  `credentials` (or `users`) table to `SCHEMA` and its columns to
  `_TABLE_COLUMNS`.
- `src/irrigation/application/services.py` — add an `AuthService` (or
  similar) with `verify(username, password) -> bool` and
  `change_password(username, current_password, new_password) -> None`,
  hashing with `hashlib`/`secrets` from the standard library.
- `src/irrigation/bootstrap.py` — add an `Application.auth()` accessor.
- `src/irrigation/cli.py` — add an `auth` subcommand with `login` and
  `change-password` actions, wired into `_COMMAND_HANDLERS`.
- `src/irrigation/infrastructure/json_migration.py` (or a new seed step in
  `Application.__post_init__`) — seed the default `admin`/`10203040`
  credential the first time the `credentials` table is empty.
- `node-red/flows.json` — add a login tab/screen gating the existing tabs,
  and a "Trocar senha" form under a settings/security group, wired to the
  new `auth` exec commands.
- `deploy/package-readme.md` — document the default credential and that it
  should be changed after installation.

### Files to create

- Possibly `deploy/node-red/settings.js` (or similar), only if the chosen
  access-control mechanism relies on Node-RED's built-in
  `httpNodeAuth`/`adminAuth`, plus the corresponding install-script wiring
  in `scripts/install-raspberry.sh`.

### Dependencies and integration points

- SQLite schema/migration (`sqlite_repository.py`), since it is the only
  persistence layer in this project.
- Node-RED's `exec` nodes as the only integration point between the
  dashboard and the backend (no REST API exists).
- If HTTP-level gating is chosen: Node-RED's own `settings.js`
  `httpNodeAuth`/`adminAuth`, which is not currently part of this repo's
  deployment and would need to be introduced into
  `scripts/install-raspberry.sh`/`deploy/systemd`.

## Technical approach

### Design principles

- Keep each class and function focused on one responsibility.
- Depend on abstractions at architectural boundaries.
- Keep domain rules independent from infrastructure details.
- Prefer small, explicit interfaces and simple data flows.
- Avoid speculative abstractions, duplicated logic, and unrelated changes.
- No new third-party dependency: hashing must use the Python standard
  library (e.g. `hashlib.pbkdf2_hmac` with a random salt via `secrets`, and
  constant-time comparison via `secrets.compare_digest` or
  `hmac.compare_digest`), consistent with `dependencies = []` in
  `pyproject.toml` and the Nuitka-compiled binary distribution.

### Proposed changes

1. Add a `credentials` table (single row, like `settings`) storing
   `username`, `password_hash`, and `password_salt` (or a combined
   PBKDF2-encoded string). Seed it with `admin`/`10203040` the first time
   the table is empty, mirroring how `SettingsService`/migration seeds
   other first-run data.
2. Add an `AuthService` with `verify(username, password) -> bool` and
   `change_password(username, current_password, new_password) -> None`
   (raising a `ValidationError` if the current password doesn't match or
   the new password is empty/too short), following the
   `SettingsService`/`ScheduleService` constructor-injected-repository
   style.
3. Add `irrigation auth login <username>,<password>` (returns
   `{"authenticated": true/false}`) and
   `irrigation auth change-password <username>,<current>,<new>` CLI
   subcommands, wired the same way as `_settings_command`.
4. Investigate and decide how the dashboard actually enforces "no access
   without login" for this Node-RED architecture — compare:
   - A login `ui_form` gating tab whose submit calls `auth login`, storing
     a short-lived flag (e.g. in Node-RED flow/global context or a signed
     cookie set via a `ui_template`) that a small guard checks before
     other tabs render/act, **combined with** protecting the exec-backed
     endpoints themselves so client-side bypass isn't possible; or
   - Node-RED's built-in `httpNodeAuth`/`adminAuth` in `settings.js`,
     which protects `/ui` and its websocket at the HTTP layer regardless
     of client-side JS, kept in sync with the same `credentials` table
     (e.g. Node-RED's `authenticate` callback shelling out to
     `irrigation auth login`).
   Record the decision and rationale in this task's Notes section before
   implementing, the same way task 015 documented its investigation.
5. Add the "Trocar senha" form to the dashboard (a `ui_form` with
   `type: "password"` fields for current/new/confirm, following the
   "Tempo padrão para desligar" tab's `ui_form` → `exec` pattern), wired to
   `auth change-password`, showing a clear error on wrong current password
   or mismatched confirmation.
6. Update `deploy/package-readme.md` to document the default
   `admin`/`10203040` credential and recommend changing it after first
   login.

### Performance considerations

- Expected complexity: `O(1)` for login/verify/change-password — a
  single-row lookup and a PBKDF2 hash computation.
- Performance risks: an excessively high PBKDF2 iteration count could make
  login noticeably slow on a Raspberry Pi.
- Mitigation: pick an iteration count that is secure but keeps
  verification well under a second on Raspberry Pi–class hardware (e.g.
  `hashlib.pbkdf2_hmac` with ~200k iterations of SHA-256, benchmarked on
  target hardware if possible).

### Error handling and edge cases

- Wrong username/password on login must not reveal which one was wrong.
- Changing the password with an incorrect current password must fail
  without changing anything.
- New password must not be empty and should have a minimum length;
  reject if new password equals the current one only if that's cheap to
  check (not required).
- Upgrading an existing installation whose database has no `credentials`
  row must seed the default account automatically rather than locking the
  user out or crashing.
- Concurrent password-change attempts should not corrupt the single-row
  table (rely on SQLite's existing transaction handling, consistent with
  the rest of the repository layer).
- The login/session mechanism must not leave the dashboard accessible
  after the credential is changed until the change is actually applied
  (no stale cached "authenticated" state bypassing a just-changed
  password on the same device, if sessions are used).

## Test specification

### Unit tests

- [ ] `AuthService.verify` returns `True` for the correct password and
      `False` for an incorrect one.
- [ ] `AuthService.verify` returns `False` for the default credential after
      it has been changed.
- [ ] `AuthService.change_password` updates the stored hash only when the
      current password matches.
- [ ] `AuthService.change_password` rejects an empty/too-short new
      password.
- [ ] The default `admin`/`10203040` credential is seeded when the
      `credentials` table is empty, and is not re-seeded (overwritten) once
      a row already exists.
- [ ] Password hashes are salted such that two accounts (or the same
      password re-hashed) do not produce identical hashes.

### Integration tests

- [ ] `irrigation auth login admin,10203040` succeeds against a freshly
      migrated/seeded database.
- [ ] `irrigation auth change-password admin,10203040,<new>` followed by
      `irrigation auth login admin,<new>` succeeds, and login with the old
      password fails.
- [ ] An existing database created before this feature (no `credentials`
      table) gets the default account seeded on first access after
      upgrading, matching the `json_migration.py` upgrade pattern.

### Regression tests

- [ ] Existing `schedule`, `valve`, `settings`, and `history` CLI commands
      remain unaffected by the new table/migration.
- [ ] The full test suite (`tests/test_services.py`,
      `tests/test_node_red_flow.py`, etc.) continues to pass.

### Test data and fixtures

- Use an in-memory/temporary SQLite database as already done in
  `tests/test_services.py` for other services.

## Acceptance criteria

The task is complete when:

- [ ] The system ships with a working default account (`admin` /
      `10203040`) with no manual setup step required.
- [ ] It is not possible to view dashboard data or trigger any valve/
      schedule action without first authenticating, verified manually
      against the real dashboard (not just by hiding UI elements).
- [ ] The password can be changed from a settings/security menu in the
      dashboard, requiring the current password.
- [ ] Passwords are stored hashed (with a salt), never in plaintext.
- [ ] Existing behavior remains unchanged outside the defined scope.
- [ ] New and changed behavior is covered by specs.
- [ ] Error cases and relevant edge cases are covered.
- [ ] The implementation follows the project's architecture and SOLID
      principles.
- [ ] The implementation is simple, readable, maintainable, and performant
      for the expected workload.
- [ ] Formatting, linting, type checks, and the full test suite pass.
- [ ] Documentation (`deploy/package-readme.md`) is updated with the
      default credential and a recommendation to change it.

## Implementation checklist

- [ ] Confirm the task number and filename.
- [ ] Inspect all files listed in the impact analysis.
- [ ] Reassess the affected files before coding and update this task if
      needed.
- [ ] Implement the smallest coherent change.
- [ ] Add or update specs.
- [ ] Run focused checks.
- [ ] Run the full validation suite.
- [ ] Validate the implementation against every acceptance criterion.
- [ ] Move the issue to `done` only after implementation and validation
      pass.

## Notes

- Original request (Portuguese): "checar a questão de segurança do sistema
  (username/password) — o sistema deve vir com uma senha padrão admin e
  senha 10203040; o sistema deve permitir trocar a senha via interface
  (crie um menu de configurações para tal); não deve ser possível entrar no
  sistema sem informar a senha." Interpreted as: default username `admin`,
  default password `10203040`, with a way to change the password from a
  settings menu, and mandatory authentication to use the system. This task
  is written in English per this project's task-generation convention
  (see `tasks/014-...md` Notes).
- This is primarily a research + implementation task, similar in spirit to
  `tasks/015-reflect-real-system-online-status.md`: the exact mechanism
  used to enforce "no access without login" at the Node-RED/dashboard
  level needs to be decided during implementation and recorded here before
  coding the gating logic, since a purely client-side (Angular) gate would
  not actually prevent access to the underlying exec-backed data.
- Implementation decision: use Node-RED's real HTTP authentication boundary
  via `node-red/settings.js`, not dashboard-only hiding. The settings file
  protects the editor/admin API through `adminAuth` and protects the
  `node-red-dashboard` `/ui` route through `ui.middleware`; both call
  `/opt/irrigation/bin/irrigation auth login ...`, so the dashboard uses the
  same SQLite-backed PBKDF2 credential as the backend and password changes
  take effect without rewriting Node-RED settings. This follows the
  documented Node-RED model for custom editor authentication and dashboard
  middleware, while avoiding static bcrypt values that would drift from the
  SQLite credential.
