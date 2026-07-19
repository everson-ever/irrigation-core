# Make Execution-History Retention Period Configurable

## Metadata

```yaml
status: done
priority: medium
type: feature
```

## Title

Let the user choose how long execution history is kept (7 days, 15 days, 1 month, 3 months) from a new "Histórico" settings section

## Specification

Today the execution-history retention window is a hard-coded 7-day constant
(`HISTORY_RETENTION_DAYS = 7`, `src/irrigation/application/services.py:33-35`),
introduced by task `032-limit-history-retention-to-one-week.md`. Records older
than 7 days are pruned on every new insert
(`HistoryService._prune_expired`, `services.py:362-367`).

Make this retention window **user-configurable**, restricted to exactly these
four periods:

- **7 days**
- **15 days**
- **1 month** (30 days)
- **3 months** (90 days)

No other values are allowed. Expose the choice through a new section on the
Configurações page called **"Histórico"**, where the user selects one period
and saves it. The chosen period is then applied by the prune-on-insert logic in
`HistoryService`. The default (initial / unset) value must remain **7 days**, so
existing behavior is preserved for installations that never touch the new
setting.

### Context

- Retention is currently a fixed constant consumed by
  `HistoryService._prune_expired` (`services.py:362-367`), which computes
  `cutoff = reference - timedelta(days=HISTORY_RETENTION_DAYS)` and calls
  `self._history.delete_before(cutoff.isoformat())`. Task 032 explicitly listed
  "making the retention window configurable via `Settings`" as **out of scope**
  and deferred it to a follow-up — this is that follow-up.
- Application settings live in the single-row SQLite `settings` table
  (`src/irrigation/infrastructure/sqlite_repository.py:41-45`), served by
  `SettingsService` (`services.py:436-458`) and reachable through the
  `settings` CLI command (`_settings_command`, `src/irrigation/cli.py:196-205`).
  The only current setting is `default_duration_minutes`.
- There is **no migration framework**; the schema is applied idempotently on
  each connect via `executescript` (`sqlite_repository.py:88`).
  `CREATE TABLE IF NOT EXISTS` does **not** add columns to an already-existing
  table, and SQLite `ALTER TABLE ... ADD COLUMN` has no `IF NOT EXISTS`. This
  makes adding a column to the existing `settings` table unsafe for databases
  already in the field. The safe, idempotent option is a **dedicated single-row
  table** (the same pattern already used by `credentials` and `runtime_health`,
  `sqlite_repository.py:47-51,63-66`), which is created cleanly on both new and
  existing databases.
- The Configurações dashboard page renders a left menu + right panel driven by
  `scope.active_config_section`, with two existing sections — "Senha"
  (`node-red/templates/configuracoes.html:477-515`) and "Seções"
  (`configuracoes.html:517-573`). A new "Histórico" section follows the same
  markup and reuses the existing CSS classes (`.ir-config-menu-button`,
  `.ir-config-section-head`, `.ir-section-card`, `.ir-form-grid`, `.ir-field`,
  `.ir-primary-button`, `.ir-feedback`).
- `node-red/templates/*.html` is the single source of truth for dashboard HTML;
  `scripts/sync_flows_templates.py` injects it into the matching `ui_template`
  node in `node-red/flows.json` (task 020). The Node-RED **function node** that
  maps `ui_action` payloads to CLI command JSON, its exec node, and the
  `msg.topic` response routing live directly in `flows.json` and must be edited
  there.
- Task `031-standardize-section-picker-as-select.md` established the `<select>`
  dropdown as the standard picker widget; reuse that pattern for the retention
  period selector.

### Scope

#### In scope

- Persist the chosen retention period (7 / 15 / 30 / 90 days) in a dedicated
  single-row SQLite table (e.g. `history_settings(id CHECK (id = 1),
  retention_days)`), created idempotently in `SCHEMA` and registered in
  `_TABLE_COLUMNS` (`sqlite_repository.py:41-76`).
- Add a service (extend `SettingsService` or a small dedicated
  `HistorySettingsService`) exposing:
  - a getter that returns the configured retention days, defaulting to
    `HISTORY_RETENTION_DEFAULT_DAYS = 7` when unset, and
  - a setter that validates the value is one of the four allowed periods and
    upserts the single row (raising `ValidationError` otherwise).
- Define the four allowed periods as a single named constant (e.g.
  `HISTORY_RETENTION_ALLOWED_DAYS = (7, 15, 30, 90)`) in the application layer,
  next to the existing history constants (`services.py:33-35`).
- Make `HistoryService._prune_expired` read the configured retention period
  instead of the hard-coded `HISTORY_RETENTION_DAYS`, via an injected accessor
  (keep the policy in the application layer; `HistoryService` must not touch the
  settings table directly — depend on an abstraction/callable so pruning stays
  testable and repositories without the setting still work).
- Extend the `settings` CLI command (or add a small new action/subcommand) to
  read and update the retention period, following the existing stdin/`--stdin`
  request convention (`cli.py:196-205,238-253`).
- Add a new **"Histórico"** section to `node-red/templates/configuracoes.html`:
  a menu button + a panel with a `<select>` offering the four periods, a save
  button, and an `ir-feedback` area, initialized from the current stored value.
- Wire the new `ui_action` (e.g. `update_history_retention`) through the
  `flows.json` function node to a CLI exec node, and route the response back to
  the template via a `msg.topic` (e.g. `history_retention_saved` /
  `history_retention_error`); run `scripts/sync_flows_templates.py` so
  `flows.json` reflects the updated template.

#### Out of scope

- Changing the pruning mechanism itself (still prune-on-insert at the
  `HistoryService.record()` choke point; no background job).
- Retroactively "restoring" already-pruned records — only future pruning uses
  the new window. Enlarging the window does not bring back deleted rows.
- Making the four allowed periods themselves configurable, or supporting
  arbitrary day counts / custom ranges.
- Any change to the history search read paths (`search_day` / `search_range`)
  or the `history_search_results.json` cache.
- Exposing `default_duration_minutes` on the settings page (it remains
  CLI-only; unrelated to this task).

## Impact analysis

### Files to inspect

- `src/irrigation/application/services.py:33-35` — `HISTORY_RETENTION_DAYS`
  constant to generalize into a default + allowed set.
- `src/irrigation/application/services.py:362-367` — `_prune_expired`, the sole
  consumer of the retention window.
- `src/irrigation/application/services.py:436-458` — `SettingsService`, the
  pattern for a single-row settings getter/setter (upsert) to mirror.
- `src/irrigation/infrastructure/sqlite_repository.py:41-76` — `SCHEMA`,
  single-row table patterns (`settings`, `credentials`, `runtime_health`), and
  `_TABLE_COLUMNS`.
- `src/irrigation/cli.py:196-205` — `_settings_command`, the stdin/args request
  convention to extend.
- `src/irrigation/bootstrap.py:48-58` — composition root wiring
  `SettingsService` and `HistoryService`; where the retention accessor must be
  injected into `HistoryService`.
- `node-red/templates/configuracoes.html:453-575` — section menu + panels,
  including `selectConfigSection` / `isConfigSectionActive`
  (`configuracoes.html:675-680`) and the existing submit/`$watch` handlers
  (`configuracoes.html:726-749,786-862`).
- `node-red/flows.json` — the function node mapping `ui_action` → CLI JSON
  (`func` string), its exec nodes, and `msg.topic` response routing.
- `scripts/sync_flows_templates.py` — the template→flows sync step.
- `tests/test_services.py` — `create_controller` fixture wiring real
  `SqliteRepository` tables; base for retention/setting behavior tests.
- `tests/test_sqlite_repository.py` — single-row table test patterns.
- `tests/test_cli.py` — settings command test patterns.

### Files to change

- `src/irrigation/infrastructure/sqlite_repository.py` — add the
  `history_settings` table to `SCHEMA` and `_TABLE_COLUMNS`.
- `src/irrigation/application/services.py` — add
  `HISTORY_RETENTION_DEFAULT_DAYS` / `HISTORY_RETENTION_ALLOWED_DAYS`, the
  getter/setter service, and make `_prune_expired` read the configured value.
- `src/irrigation/bootstrap.py` — wire the retention accessor into
  `HistoryService`.
- `src/irrigation/cli.py` — extend the settings command to get/set retention.
- `node-red/templates/configuracoes.html` — add the "Histórico" section
  (menu button + panel + `<select>` + submit/feedback handlers).
- `node-red/flows.json` — add the `ui_action` branch, exec node, and response
  routing (and the synced template body).
- `tests/test_services.py`, `tests/test_sqlite_repository.py`,
  `tests/test_cli.py` — cover the new setting, validation, and prune behavior.

### Files to create

- None required (prefer a dedicated table over a new module; add a small
  service class in `services.py` only if it reads cleaner than extending
  `SettingsService`).

### Dependencies and integration points

- `Repository` port (`src/irrigation/domain/ports.py`) — the new single-row
  table uses the existing `SqliteRepository`; no port change needed (retention
  read in `HistoryService` goes through an injected callable, not the port).
- SQLite schema — additive only (a new `CREATE TABLE IF NOT EXISTS`), safe on
  existing databases without a migration framework.
- Node-RED dashboard `ui_template` + function/exec nodes and the CLI stdin
  contract.

## Technical approach

### Design principles

- Keep each class and function focused on one responsibility.
- Depend on abstractions at architectural boundaries.
- Keep domain rules independent from infrastructure details.
- Prefer small, explicit interfaces and simple data flows.
- Avoid speculative abstractions, duplicated logic, and unrelated changes.

### Proposed changes

1. Schema: add `CREATE TABLE IF NOT EXISTS history_settings (id INTEGER PRIMARY
   KEY CHECK (id = 1), retention_days INTEGER NOT NULL CHECK (retention_days IN
   (7, 15, 30, 90)))` and register `"history_settings": ("retention_days",)` in
   `_TABLE_COLUMNS`.
2. Constants: replace/augment `HISTORY_RETENTION_DAYS` with
   `HISTORY_RETENTION_DEFAULT_DAYS = 7` and
   `HISTORY_RETENTION_ALLOWED_DAYS = (7, 15, 30, 90)`.
3. Settings service: add `retention_days()` (returns stored value or the default
   when the row is absent) and `update_retention_days(value)` (validate ∈ allowed
   set, else `ValidationError`; upsert single row) — mirroring
   `SettingsService.update_default_duration` (`services.py:446-458`).
4. `HistoryService`: inject a `retention_days` accessor (callable/port) in the
   constructor; `_prune_expired` computes
   `cutoff = reference - timedelta(days=self._retention_days())`. Keep the
   defensive `getattr(self._history, "delete_before", None)` guard.
5. Bootstrap: construct the retention accessor and pass it into `HistoryService`
   (`bootstrap.py:54-58`).
6. CLI: added a new `history-retention` subcommand (mirroring `settings`'s
   `show`/update shape exactly) rather than overloading `_settings_command`,
   keeping the two settings domains independent — `settings show` still only
   returns `default_duration_minutes`.
7. Frontend: add the "Histórico" menu button and panel (section number "03")
   with a `<select>` bound to `history_retention_form.days`, a submit handler
   sending `{ ui_action: "update_history_retention", retention_days }`, and a
   `$watch` branch handling the `history_retention_saved` /
   `history_retention_error` topics; initialize the select from the current
   value. Reuse existing section CSS classes.
8. flows.json: added the function-node branch mapping the new `ui_action` to
   `{ command: "history-retention", value: retention_days }`, an exec node
   pair (success/error), and a periodic poll (`034retention.poll` →
   `034retention.fetch` → `034retention.format`, every 5s like the existing
   valve poll) broadcasting a `history_retention` topic to both the
   Configurações and Histórico templates so the current period and the
   dynamic "last N days" copy stay in sync; ran
   `scripts/sync_flows_templates.py` afterwards.

### Performance considerations

- Expected complexity: `O(1)` — the retention read is a single-row lookup; the
  prune remains the same bounded, `idx_history_date`-backed `DELETE` as task
  032.
- Performance risks: an extra single-row read per `record()` if retention is
  fetched on every insert. Mitigation: read the setting once per prune call (it
  is a tiny indexed single-row query) — no caching layer needed at this
  insertion rate.

### Error handling and edge cases

- Unset setting (fresh DB / never configured): getter returns the 7-day default,
  preserving current behavior.
- Invalid value (not in {7, 15, 30, 90}): setter raises `ValidationError`; the
  CHECK constraint is a second line of defense.
- Enlarging the window does not resurrect already-pruned rows (documented as a
  known, accepted limitation).
- Shrinking the window: the next `record()` prunes anything now outside the
  smaller window in one indexed delete.
- Non-integer / missing payload from the dashboard: coerced/validated the same
  way `update_default_duration` handles bad input (`services.py:446-452`).

## Test specification

### Unit tests

- [x] Retention getter returns the stored value when set and the 7-day default
      when the row is absent.
- [x] Retention setter accepts each of 7 / 15 / 30 / 90 and rejects any other
      value with `ValidationError`.
- [x] `history_settings` upsert stores exactly one row (id = 1) across repeated
      updates.

### Integration tests

- [x] `HistoryService.record()` prunes using the **configured** window: seed
      history and settings, set retention to 15 days, and assert records older
      than 15 (but within 30) days are pruned while 7-day behavior no longer
      applies.
- [x] With no configured setting, pruning still uses the 7-day default
      (regression against task 032 behavior).
- [x] The settings CLI command round-trips the retention value (set then show).

### Regression tests

- [x] Existing task-032 retention tests still pass under the default value.
- [x] `default_duration_minutes` settings behavior is unchanged.
- [x] Search paths (`search_day` / `search_range`) are unaffected.

### Test data and fixtures

- Added a dedicated `_history_service_with_retention` helper in
  `tests/test_services.py` (alongside the existing `_history_service` helper)
  that wires a `HistorySettingsService` backed by the `history_settings`
  table into `HistoryService`, rather than extending the unrelated
  `create_controller` fixture used by the automatic-controller tests.

## Acceptance criteria

The task is complete when:

- [x] The user can select one of exactly four retention periods (7 days,
      15 days, 1 month, 3 months) in a "Histórico" section on the Configurações
      page and save it.
- [x] The saved period is persisted and drives `HistoryService` prune-on-insert;
      the four periods are defined as a single named constant.
- [x] When no period is configured, retention defaults to 7 days (task-032
      behavior is preserved).
- [x] Invalid periods are rejected in the service (and guarded by a DB CHECK).
- [x] Existing behavior remains unchanged outside the defined scope.
- [x] New and changed behavior is covered by specs (repository, service, CLI,
      and default/regression cases).
- [x] The implementation follows the project's hexagonal architecture and SOLID
      principles (retention policy in the application layer, persistence in
      infrastructure, `HistoryService` depending on an injected accessor).
- [x] The dashboard change lives in `configuracoes.html`, `flows.json` is synced
      via `scripts/sync_flows_templates.py`, and the two copies do not drift.
- [x] Formatting, linting, and the full test suite pass (`ruff check`,
      `ruff format --check`, `pytest`). Note: this project does not use mypy —
      no `mypy` config exists in `pyproject.toml` and `docs/DEVELOPER_GUIDE.md`
      only documents `pytest`/`ruff`; the acceptance criterion is satisfied
      against the tooling the project actually runs.
- [x] Documentation or user-facing copy is updated where the current 7-day limit
      is mentioned (e.g. `node-red/templates/historico.html`), and now reads
      the configured period dynamically via the new `history_retention` topic.

## Implementation checklist

- [x] Confirm the task number and filename (`034-...`).
- [x] Inspect all files listed in the impact analysis.
- [x] Reassess the affected files before coding and update this task if needed.
- [x] Add the `history_settings` table + retention service getter/setter.
- [x] Inject the retention accessor into `HistoryService._prune_expired`.
- [x] Extend the CLI and add the "Histórico" dashboard section + flows wiring.
- [x] Add or update specs.
- [x] Run focused checks (retention service + repository + CLI tests).
- [x] Run the full validation suite.
- [x] Validate the implementation against every acceptance criterion.
- [x] Move the issue to `status: done` only after implementation and validation
      pass.

## Notes

- Follow-up to `tasks/032-limit-history-retention-to-one-week.md`, which
  deferred configurability. Reuse the `<select>` picker convention from
  `tasks/031-standardize-section-picker-as-select.md`.
- Original request (Portuguese): "configurar por quanto tempo quer manter o
  histórico de execuções — 7 dias, 15 dias, 1 mês, 3 meses (apenas esses
  períodos). Nova seção na página de configurações chamada Histórico."
- "1 mês" is interpreted as 30 days and "3 meses" as 90 days, consistent with
  the day-based `timedelta` cutoff already used by `_prune_expired`.
- A dedicated `history_settings` table is preferred over adding a column to the
  existing `settings` table because there is no migration framework and
  `CREATE TABLE IF NOT EXISTS` cannot add columns to databases already
  deployed; a new single-row table is created cleanly on both new and existing
  databases. Confirm this choice during implementation.
