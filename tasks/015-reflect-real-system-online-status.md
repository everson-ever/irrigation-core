## Metadata

```yaml
status: backlog
priority: medium
type: bug
```

## Title

Make the "Sistema online" indicator reflect the real system status

## Specification

The "Sistema online" badge shown in the dashboard header (top-right corner,
next to the "IR" avatar) must reflect whether the system is actually
reachable and functioning, instead of always showing as online.

### Context

The badge currently renders as a static element with a hardcoded green dot
and the fixed text "Sistema online":

```html
<div class="ir-online"><span class="ir-online-dot"></span>Sistema online</div>
```

This markup is duplicated identically in `agendamentos.html` (line 753) and
`novo-agendamento.html` (line 532), with no Angular binding, `$watch`, or
data source behind it. It will show "online" even if:

- The Node-RED dashboard websocket connection drops.
- The backend API (irrigation-core Python service) is unreachable.
- The Node-RED flow itself is stopped or crashed.

This is misleading for a home irrigation system: a user glancing at the
badge could believe schedules are running when they are not.

This task is primarily a **research/investigation** task: determine the best
mechanism available in this stack (Node-RED + node-red-dashboard AngularJS
UI + irrigation-core Python backend) to detect and surface real connectivity
status, then implement it.

### Scope

#### In scope

- Investigate available signals for "system online" in this stack:
  - node-red-dashboard's built-in websocket/socket.io connection state
    (exposed to Angular scopes in `ui_control`/dashboard nodes).
  - A lightweight backend health check (e.g. polling an existing or new
    HTTP endpoint on the irrigation-core API) as a way to detect backend
    liveness, not just websocket/browser-to-Node-RED connectivity.
  - Any existing Node-RED status/heartbeat mechanisms already used
    elsewhere in `node-red/flows.json`.
- Decide which signal(s) best represent "the system is actually working"
  (dashboard reachable AND backend responsive), documenting the tradeoffs.
- Implement the chosen approach so the badge dynamically reflects
  online/offline/reconnecting state.
- Apply the same fix consistently across all templates that show the badge.

#### Out of scope

- Redesigning the header/badge visuals beyond what's needed to show
  new states (e.g. "offline", "reconnecting").
- Building a full monitoring/alerting system (e.g. notifications, logs,
  history of downtime).
- Changing how schedules/valves are controlled.

## Impact analysis

### Files to inspect

- `node-red/templates/agendamentos.html` — current badge markup (line 753)
  and Angular controller (`ir-online` CSS starting line 93/115/123).
- `node-red/templates/novo-agendamento.html` — duplicate badge markup
  (line 532) and shared styles (lines 71/93/101).
- `node-red/templates/historico.html` — check whether the badge is present
  here too and needs the same fix.
- `node-red/flows.json` — understand how the dashboard nodes are wired,
  what HTTP/API endpoints already exist that could serve as a health check,
  and how `scope.send`/`msg` are used to talk to the backend.
- `src/irrigation/bootstrap.py` and `src/irrigation/application/services.py`
  — check whether an HTTP layer/router already exists where a lightweight
  `/health` endpoint could be added if needed.
- `deploy/package-readme.md`, `deploy/systemd/*` — understand how the
  backend service and Node-RED are deployed/run, relevant to what
  "online" should mean (process alive vs. API reachable vs. websocket
  connected).

### Files to change

- `node-red/templates/agendamentos.html` — replace static badge with
  dynamic status binding.
- `node-red/templates/novo-agendamento.html` — same fix.
- `node-red/templates/historico.html` — same fix, if applicable.
- `node-red/flows.json` — add/wire any new status-check node or polling
  flow feeding the dashboard scope, if that's the chosen approach.

### Files to create

- Possibly a small backend health-check endpoint (path/module to be
  determined after inspecting `bootstrap.py`/`services.py`), only if the
  investigation concludes that a websocket-only signal is insufficient to
  represent "real" system status.

### Dependencies and integration points

- node-red-dashboard's Angular `$scope` / `ui_control` connection events.
- irrigation-core backend HTTP API, if a health check endpoint is added.
- Node-RED flow scheduling/polling (e.g. `inject` node on an interval) if
  periodic health checks are implemented.

## Technical approach

### Design principles

- Keep each class and function focused on one responsibility.
- Depend on abstractions at architectural boundaries.
- Keep domain rules independent from infrastructure details.
- Prefer small, explicit interfaces and simple data flows.
- Avoid speculative abstractions, duplicated logic, and unrelated changes.

### Proposed changes

1. Research and compare candidate signals for "online" status (dashboard
   websocket connection vs. backend health check vs. both combined),
   and record the decision with rationale in this task's Notes section.
2. Implement the chosen signal end-to-end: emit/poll the status, bind it
   to the Angular scope in each template, and update `ir-online`/
   `ir-online-dot` to show at least "online" and "offline" states (and
   "reconnecting" if relevant).
3. Deduplicate the badge markup/logic across templates if a shared
   include/controller pattern is already used elsewhere in this codebase;
   otherwise keep the same duplication pattern already used for other
   shared UI elements, to stay consistent with the existing structure.

### Performance considerations

- Expected complexity: `O(1)` per status check; negligible system load.
- Performance risks: an overly frequent polling interval could add
  unnecessary load to the backend or Node-RED.
- Mitigation: use a reasonable polling/heartbeat interval (e.g. every
  10–30s) and rely on push-based websocket events where possible instead
  of polling.

### Error handling and edge cases

- Backend unreachable but Node-RED/dashboard still connected.
- Node-RED dashboard websocket disconnects/reconnects while the backend
  stays healthy.
- Browser loses network connectivity entirely.
- Rapid connect/disconnect flapping should not cause the badge to flicker
  excessively.

## Test specification

### Unit tests

- [ ] N/A if the fix is purely front-end/flow wiring with no testable
      Python unit; otherwise cover any new backend health-check logic.

### Integration tests

- [ ] If a backend health endpoint is added, cover it with an integration
      test verifying it returns the expected status/shape.

### Regression tests

- [ ] Verify existing dashboard functionality (schedules list, manual
      actions) is unaffected by the status-check addition.

### Test data and fixtures

- N/A — this is primarily a UI/connectivity concern; manual verification
  with the backend stopped/started is expected to be part of validation.

## Acceptance criteria

The task is complete when:

- [ ] The "Sistema online" badge reflects real connectivity/health, not a
      hardcoded value.
- [ ] The badge visibly changes (e.g. to "offline") when the backend
      and/or Node-RED connection is down, verified manually.
- [ ] Existing behavior remains unchanged outside the defined scope.
- [ ] New and changed behavior is covered by specs where applicable.
- [ ] Error cases and relevant edge cases are covered.
- [ ] The implementation follows the project's architecture and SOLID
      principles.
- [ ] The implementation is simple, readable, maintainable, and performant
      for the expected workload.
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

- The badge markup is currently duplicated in `agendamentos.html` and
  `novo-agendamento.html`; check `historico.html` too when starting
  implementation, since it wasn't confirmed to contain the badge during
  this task's initial investigation.
- Decision on which "online" signal to use (websocket-only, backend health
  check, or combined) should be recorded here once the investigation is
  done, before implementation starts.
