---
status: done
priority: medium
type: feature
---

## Title

Send Discord webhook notifications for irrigation and account events

## Specification

Add a **Discord** section to the Configurações page where the user configures a
single Discord webhook URL and, per event type, whether a notification should
be sent. Supported event types:

- Seção: ligada, desligada (same option for manual and automatic control).
- Agendamento: reiniciado (restarted after a controller restart).
- Agendamento: cadastrado, editado, excluído (schedule created, edited,
  deleted).
- Seção: cadastrada, editada, excluída (valve/section created, edited,
  deleted).
- Senha alterada (account password changed).

The user can save a webhook URL, edit it, and remove it; removal requires
confirmation through the project's existing modal pattern (see the section and
sensor delete modals in `node-red/templates/configuracoes.html`). Each event
type has its own enable/disable toggle, defaulting to disabled until a webhook
URL is configured. When no webhook URL is configured, or an event's toggle is
off, no request is sent for that event. A failed or slow Discord delivery must
never block irrigation control, schedule/section CRUD, or password changes.

### Context

The project already has settings sub-pages for password, seções, histórico,
and sensores, each following the same card/form/modal layout in
`node-red/templates/configuracoes.html` and a matching backend service, CLI
action, and idempotent SQLite table (see `sensors`/`sensor_state` added by
task 035). There is currently no outbound notification mechanism and no
runtime HTTP client dependency (`pyproject.toml` declares
`dependencies = []`). Two independent processes must be able to trigger a
notification:

- The long-running `IrrigationController` (`app.automatic_controller().run()`,
  started by the `irrigation` systemd service) transitions schedules on/off/
  restarted in `IrrigationController._start`/`_stop`
  (`src/irrigation/application/services.py`).
- The short-lived CLI process spawned per Node-RED action performs schedule
  CRUD (`ScheduleService.create/update/delete`), valve/section CRUD
  (`ValveService.add/update/remove`), and password changes
  (`AuthService.change_password`).

Both call paths must be able to reach the same notification configuration and
dispatch logic without adding blocking latency that could delay watering
control or the dashboard's per-request CLI response (task 030 constraints).

### Scope

#### In scope

- Persist one Discord webhook URL and one enabled/disabled flag per supported
  event type in a new additive SQLite table.
- Add a **Discord** settings section (numbered 05) to Configurações with a
  webhook form (add/edit) and an event-toggle list, following the existing
  card/form/badge/feedback visual patterns.
- Let the user remove the configured webhook through a delete-confirmation
  modal matching `ir-modal-backdrop`/`ir-modal` markup already used for
  section and sensor deletion.
- Add application service methods and a structured `notifications` CLI
  contract (get config, save/update webhook, delete webhook, set event
  toggle) so Node-RED never talks to SQLite directly.
- Send a best-effort Discord webhook HTTP request for each enabled event using
  only the Python standard library (no new runtime dependency), with a short
  timeout and no retries, from both the CLI process and the long-running
  controller process.
- Write a Portuguese, human-readable message per event type (e.g. section
  name, schedule time, valve/section identifiers) without leaking the webhook
  URL, password values, or hashes.
- Identify schedules by their registered valve/section name in messages instead
  of the internal numeric schedule id.
- Log and swallow notification failures (invalid URL, timeout, non-2xx
  response) without raising to the caller.

#### Out of scope

- Any notification channel other than Discord (email, SMS, push).
- Delivery retries, queues, or guaranteed delivery.
- Notification history/audit log in the dashboard.
- Notifying on sensor events (covered by tasks 035-040 if ever requested
  separately).
- Rate limiting or de-duplicating rapid repeated events.

## Impact analysis

### Files to inspect

- `src/irrigation/domain/models.py` — existing model/enum/validation patterns.
- `src/irrigation/domain/ports.py` — protocol boundary conventions.
- `src/irrigation/application/services.py` — where `IrrigationController._start`/
  `_stop`, `ScheduleService.create/update/delete`, `ValveService.add/update/remove`,
  and `AuthService.change_password` currently live, to find the exact call
  sites for notification triggers.
- `src/irrigation/infrastructure/sqlite_repository.py` — additive schema
  pattern (`sensors`/`sensor_state` tables) and repository style.
- `src/irrigation/cli.py` — structured stdin command dispatch pattern (see the
  `sensor` command family).
- `src/irrigation/bootstrap.py` — service composition, including
  `automatic_controller()` and `manual_control()` wiring.
- `node-red/templates/configuracoes.html` — section numbering (currently 01-04),
  card/form/modal markup, and the `sensor_delete_state`/`valve_delete_state`
  modal pattern to copy for the webhook-removal modal.
- `node-red/flows.json` — settings action routing.
- `scripts/sync_flows_templates.py` — template/flow synchronization check.
- `pyproject.toml` — confirm the zero-runtime-dependency constraint before
  choosing an HTTP client.

### Files to change

- `src/irrigation/domain/models.py` — add a notification-config model/enum for
  the supported event types.
- `src/irrigation/domain/ports.py` — add a minimal notifier protocol if needed
  to keep the HTTP call out of the application layer.
- `src/irrigation/application/services.py` — add a `NotificationService`
  (webhook CRUD, per-event toggle, dispatch) and call it from the schedule
  on/off/restart transitions, schedule CRUD, valve/section CRUD, and password
  change.
- `src/irrigation/infrastructure/sqlite_repository.py` — add an idempotent
  `discord_notifications` table (single-row webhook config plus per-event
  enabled flags, or one row per event type — decide during implementation)
  and its repository.
- `src/irrigation/infrastructure/` — add the stdlib-based Discord webhook
  client (new file, see below).
- `src/irrigation/cli.py` — add a `notifications` command with actions for
  get/save webhook/delete webhook/set event toggle.
- `src/irrigation/bootstrap.py` — expose `notifications()` and inject the
  service into `automatic_controller()` and the schedule/valve/auth CLI
  handlers.
- `node-red/templates/configuracoes.html` — add section 05 (Discord), its
  webhook form, event toggle list, and delete-confirmation modal.
- `node-red/flows.json` — route the new notifications actions/results.
- `docs/DEVELOPER_GUIDE.md` / `docs/COMPONENTS_GUIDE.md` / `README.md` —
  document the webhook contract and the events that trigger it.
- Relevant tests under `tests/`.

### Files to create

- `src/irrigation/infrastructure/discord_notifier.py` — stdlib `urllib`-based
  webhook sender with a short timeout, isolated so it is the only module that
  performs outbound HTTP.

### Dependencies and integration points

- `IrrigationController` (long-running process) and the CLI schedule/valve/auth
  handlers (short-lived per-request processes) both need access to the same
  notification configuration and dispatch logic.
- Node-RED must continue invoking the CLI with structured stdin and no shell.
- No new runtime dependency should be added unless the stdlib HTTP client is
  demonstrably insufficient (it is not, for a single POST to a webhook URL).

## Technical approach

### Design principles

- Keep the Discord HTTP client isolated in infrastructure; application code
  depends on a small protocol, not on `urllib` directly.
- Treat notification delivery as fire-and-forget: never let it raise into or
  block irrigation control, CRUD flows, or authentication.
- Use an additive table so existing deployments upgrade without migration
  scripts, consistent with `sensors`/`sensor_state`.
- Make the backend authoritative for validating the webhook URL shape and
  event-type identifiers; do not trust Node-RED input.

### Proposed changes

1. Add a `NotificationEvent` enum (section_on, section_off, schedule_restarted,
   schedule_created, schedule_updated, schedule_deleted, section_created,
   section_updated, section_deleted, password_changed) and a config model
   holding the webhook URL plus one enabled flag per event.
2. Add the `discord_notifications` table and repository, following the
   `sensors` table's additive/idempotent style.
3. Add `NotificationService` with `get_config`, `save_webhook`,
   `delete_webhook`, `set_event_enabled`, and a `notify(event, **context)`
   method that no-ops when the webhook is absent or the event is disabled,
   otherwise builds a Portuguese message and calls the injected notifier with
   a short timeout, catching and logging all exceptions.
4. Add `discord_notifier.py` with a single function that POSTs a JSON payload
   to the webhook URL via `urllib.request` with a short timeout (e.g. 5s) and
   no retries.
5. Call `NotificationService.notify(...)` from
   `IrrigationController._start`/`_stop` (on/off/restarted), from
   `ScheduleService.create/update/delete`, from
   `ValveService.add/update/remove`, and from `AuthService.change_password`,
   wiring the service through `bootstrap.py`.
6. Add the `notifications` CLI command and structured stdin actions.
7. Add the Discord settings section (05) with webhook form, event toggles, and
   a delete-confirmation modal reusing the existing
   `ir-modal-backdrop`/`ir-modal is-small` pattern.
8. Sync `flows.json` from the template and add focused/regression tests.

### Performance considerations

- Expected complexity: `O(1)` per event; the notifications table holds a
  single configuration row (or one row per event, bounded by the fixed event
  list).
- Performance risk: a slow or unreachable Discord endpoint could stall the
  long-running controller loop or a per-request CLI process.
- Mitigation: short fixed timeout on the HTTP call, no retries, and a design
  that treats any notifier exception as non-fatal so the caller's real work
  (irrigation control, CRUD, auth) already completed before the notification
  is attempted.

### Error handling and edge cases

- Reject malformed webhook URLs (must be a valid `https://discord.com/api/webhooks/...`-
  style URL) and unknown event-type identifiers at the service layer.
- No webhook configured: all `notify()` calls no-op silently.
- Webhook configured but the specific event toggle is off: no-op for that
  event only.
- Discord request fails (timeout, DNS error, non-2xx): log and continue;
  never raise to the caller or surface as a CRUD/auth failure in the UI.
- Deleting the webhook must clear the URL and leave event toggles in a
  disabled, reusable state so re-adding a webhook doesn't silently resurrect
  stale enabled flags without the user's confirmation.

## Test specification

### Unit tests

- [x] Validate webhook URL format, event-type identifiers, and toggle
  persistence.
- [x] `NotificationService.notify` no-ops when no webhook is configured or the
  event is disabled, and calls the notifier when enabled.
- [x] `NotificationService.notify` swallows notifier exceptions.

### Integration tests

- [x] Verify schema initialization on new and existing databases.
- [x] Verify all structured stdin `notifications` CLI actions and error
  responses.
- [x] Verify schedule on/off/restart transitions, schedule CRUD, valve/section
  CRUD, and password change call the notifier with the expected event and
  message when enabled, and do not call it when disabled.
- [x] Verify the settings page can save, edit, toggle, and delete the webhook
  using a mocked notifier/config.

### Regression tests

- [x] Existing schedule, valve, history, authentication, and settings behavior
  remains unchanged when no webhook is configured.
- [x] A failing/mocked-timeout notifier does not delay or fail schedule
  transitions, CRUD operations, or password changes.
- [x] `flows.json` remains synchronized with the HTML template.

### Test data and fixtures

- Fixtures for: no webhook configured, webhook configured with all events
  enabled, webhook configured with all events disabled, and a notifier stub
  that raises to prove failures are swallowed.

## Acceptance criteria

- [x] Configurações contains a responsive **Discord** section numbered 05.
- [x] The user can add, edit, and remove a Discord webhook URL entirely
  through the UI; removal requires confirmation via the project's modal
  pattern.
- [x] The user can independently enable/disable notifications for: section on
  and off regardless of manual/automatic origin; schedule restarted; schedule
  created, edited, deleted; section created, edited, deleted; password changed.
- [x] Enabled events send a Discord message via webhook; disabled events and a
  missing webhook send nothing.
- [x] Notification failures never block or fail irrigation control, CRUD
  operations, or password changes.
- [x] No new runtime dependency is introduced.
- [x] Validation is enforced by the backend and errors are actionable.
- [x] Tests, linting, formatting, and template synchronization checks pass.

## Implementation checklist

- [x] Inspect the listed files and confirm the current schema/service/CLI
  conventions.
- [x] Implement the smallest common model and persistence contract.
- [x] Add the stdlib Discord notifier and wire it through both the
  long-running controller and the CLI processes.
- [x] Add CLI and dashboard integration, including the delete-confirmation
  modal.
- [x] Add focused and regression tests.
- [x] Run `python3 scripts/sync_flows_templates.py`.
- [x] Run the full validation suite.
- [x] Validate every acceptance criterion before moving the task to `done`.

## Notes

- Discord embeds are a nice-to-have; a plain `content` string per message is
  sufficient to satisfy this task and keeps the notifier trivial.
- Keep the webhook URL out of logs and out of any API response beyond the
  settings page that owns it.
