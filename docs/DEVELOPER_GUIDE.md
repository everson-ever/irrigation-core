# Developer Guide — Irrigation Core

> Technical reference documentation. The goal is that anyone about to implement a
> feature or a task can understand the **whole** system by reading only this
> document, without having to decipher the code from scratch.
>
> Project convention: **classes, methods, functions, variables, and commands use
> English names**; the CLI's JSON output is part of the dashboard contract and
> must not change in a backward-incompatible way.

---

## 1. Overview

Automated irrigation system for Raspberry Pi. It:

- Drives solenoid valves (relays) and a pump via GPIO according to schedules.
- Allows manual on/off control of each section.
- Logs watering history and supports search by day or date range.
- Exposes a web dashboard in **Node-RED** for the end user.

The core is a **Python daemon** (`irrigation run`) that runs in a loop turning
valves on/off, plus a **CLI** that the dashboard calls to read and write data.

```
┌────────────────┐   HTTP    ┌──────────────┐   exec (CLI)   ┌───────────────┐
│  Browser       │ ───────▶  │   Node-RED   │ ─────────────▶ │  irrigation   │
│ (dashboard)    │ ◀───────  │  (dashboard) │ ◀───────────── │  CLI (JSON)   │
└────────────────┘           └──────────────┘                └───────┬───────┘
                                                                      │ SQLite
┌──────────────────────────┐                                         ▼
│ irrigation run (daemon)  │ ───────── turns valves on/off ────▶ data/irrigation.db
│ IrrigationController      │ ◀──────── reads schedules ─────────       │
└──────────────────────────┘                                     GPIO (rpi/mock)
```

Two processes share the **same SQLite database**: the daemon (`scheduler`) and
the CLI invoked by Node-RED. WAL, `busy_timeout`, and `BEGIN IMMEDIATE`
transactions keep concurrent access safe.

---

## 2. Layered architecture (SOLID / Clean Architecture)

The code follows **dependency inversion**: the domain and use cases know nothing
about SQLite, GPIO, or Node-RED. Everything enters through **ports** (Protocols)
and is injected in `bootstrap.py`.

```
src/irrigation/
├── domain/            # Rules and contracts — does NOT import infrastructure
│   ├── models.py      # Entities: Schedule, Valve, HistoryRecord (+ validation)
│   ├── ports.py       # Protocols: Repository, GpioController, Clock
│   └── exceptions.py  # IrrigationError, ValidationError, RecordNotFoundError, HardwareError
├── application/       # Use cases — orchestrates domain + ports
│   └── services.py    # ScheduleService, ValveService, HistoryService,
│                      # ManualControlService, IrrigationController,
│                      # SettingsService, AuthService, RuntimeHealthService
├── infrastructure/    # Concrete implementations of the ports
│   ├── sqlite_repository.py   # Persistence (Repository)
│   ├── gpio.py                # GPIORaspberryPi + MockGPIO (GpioController)
│   ├── clock.py               # SystemClock (Clock)
│   ├── json_repository.py     # JSON Lines (history search snapshot)
│   └── json_migration.py      # One-time import of legacy JSON → SQLite
├── config.py          # Settings.from_env() (environment variables)
├── bootstrap.py       # Application: dependency injection / composition root
└── cli.py             # Interface (argparse) used by systemd and Node-RED
```

**Golden rule for features:**

1. Pure business rule → `domain/models.py` (validation lives in the entities).
2. Orchestration / use case → `application/services.py`.
3. Database/hardware access → behind a port in `domain/ports.py`, implemented in
   `infrastructure/`.
4. User-facing exposure → new subcommand in `cli.py` + node in Node-RED.

Never import `sqlite3`, `RPi.GPIO`, or I/O details inside `domain/` or
`application/`.

---

## 3. Domain model (`domain/models.py`)

All entities are `@dataclass(frozen=True, slots=True)` — **immutable**.
To "change" a record use `dataclasses.replace(...)`.
Validation happens in `__post_init__` / `from_dict`, so an object that exists is
always valid.

### `Schedule`

| Field | Type | Notes |
|-------|------|-------|
| `id` | `str` | Empty until persisted (id comes from SQLite). |
| `times` | `tuple[str, ...]` | 1 to 3 `HH:MM` times, sorted and distinct. |
| `duration_minutes` | `int` | ≥ 1. |
| `valve_pin` | `int` | ≥ 1. Physical pin (BOARD). Unique per schedule. |
| `status` | `bool` | **Currently watering** (set by controller/manual). |
| `enabled` | `bool` | If `False`, the controller ignores the schedule. |
| `weekdays` | `tuple[str, ...]` | Subset of `("mon","tue",...,"sun")`. |

Key points:

- **Multiple times** (up to 3): accepted as a string (`"06:00+18:00"`, separators
  `, ; | +`) or a list. `_reject_overlapping_times` prevents intervals from
  overlapping, including across midnight.
- **`time` (property)**: joins the times with `|` — this is the **canonical
  persisted** format in the `time` column. `times` is the derived list.
- **Weekdays**: `_normalize_weekdays` accepts ids (`mon`), full names (`monday`),
  indices (`0..6`), "all" aliases (`all`, `everyday`, `daily`), and `None` = all
  days.
- **`interval_at(now)`**: returns the `(start, end)` of the relevant slot for
  `now` (the active one, else the most recent past one, else the first). Handles
  watering that **crosses midnight** (`_interval_for_time` looks at the previous
  day).
- **`is_running_at(now)`**: `True` if `enabled` and there is a slot whose weekday
  matches and `start <= now < end`.

### `Valve` (valve/section)

| Field | Notes |
|-------|-------|
| `pin` | Physical pin, **unique** (`UNIQUE` in the schema). |
| `section` | Section name (e.g. "Front garden"). Used as the history key. |
| `status` | On/off. |
| `manually_turned_off` | Flag that prevents the controller from turning it back on after a manual off (see §6). |

### `HistoryRecord`

One completed/started watering row: `valve` (= `section`), `date`, `start`,
`end` (`HH:MM`), `weekday` (English name), and `mode`. Possible modes (constants
in `services.py`):

- `Manual`
- `Automatic`
- `Automatic: started after scheduled time` (late start — system came back online
  within the window)
- `Restarted` (automatic watering resumed after a process restart within the
  valid window). Each process restart creates a separate audit row; the
  dashboard labels and counts these rows as automatic restarts.

---

## 4. Ports (`domain/ports.py`)

Contracts implemented by the infrastructure. They are `typing.Protocol`
(structural typing — no explicit inheritance).

```python
class Repository(Protocol):
    def list_all(self) -> list[dict]: ...
    def find_by_id(self, record_id) -> dict | None: ...
    def add(self, data) -> dict: ...
    def update(self, data) -> dict: ...
    def delete(self, ids) -> bool: ...
    def replace_all(self, records) -> None: ...

class GpioController(Protocol):
    def configure(self, valve_pins) -> None: ...
    def turn_on(self, pin) -> None: ...
    def turn_off(self, pin, keep_pump_on=False) -> None: ...
    def close(self) -> None: ...

class Clock(Protocol):
    def now(self) -> datetime: ...
```

Services work with **dicts** coming from the `Repository` and convert them to
entities via `Model.from_dict(...)`. This keeps persistence agnostic of domain
types.

---

## 5. Use cases (`application/services.py`)

Each service is a cohesive set of use cases. It receives ports in the
constructor.

| Service | Responsibility |
|---------|----------------|
| `ScheduleService` | Schedule CRUD; rejects duplicate valve; `list_with_runtime_status` (enriches with `is_running`, `valve_status`, `remaining_seconds`). |
| `ValveService` | Valve state + GPIO actuation. Lazy `configure()`; manages the `manually_turned_off` flag and `keep_pump_on`. |
| `HistoryService` | Records and searches history; computes the active interval (`active_end`, `has_active_manual`, `has_active_automatic`); writes the search snapshot as JSON. |
| `ManualControlService` | Manual on/off, with wait (`wait`) until auto-off and synchronization of the associated schedule's `status`. |
| `IrrigationController` | **The daemon.** `run()` = loop; `run_once()` = one sweep of all schedules. |
| `SettingsService` | Default manual-mode duration (`settings` table, fixed id = 1). |
| `AuthService` | Login and password change (PBKDF2-SHA256, 200k iterations). Creates `admin/10203040` by default. |
| `RuntimeHealthService` | Daemon heartbeat (`touch`) and online/offline status based on the last heartbeat's age. |

### `list_with_runtime_status` (dashboard contract)

Called by `irrigation schedule list`. For each schedule it returns the
`to_dict()` plus:

- `is_running` — `= schedule.status`.
- `valve_status` — the real valve state (may differ from the schedule if another
  watering/manual run uses the same pin).
- `remaining_seconds` — only while watering; computed from the **real end** of
  the run in the history (`history.active_end`), not the configured duration (a
  manual run can have a different duration).

---

## 6. Automatic controller flow (the heart of the system)

`IrrigationController.run()` (invoked by `irrigation run`):

```
configure() → loop:
    run_once()         # one sweep
    touch(health)      # heartbeat after successful reconciliation
    sleep(poll_interval)   # default 5s
```

`run_once()` → for each `schedule`, `_process_schedule` decides the transition by
comparing **three signals**:

- `is_running = schedule.is_running_at(now)` — should it be watering now?
- `schedule.status` — is it marked as watering in the database?
- `_started_in_this_process` — did this process already start this window? (avoids
  duplicating history records and distinguishes `Restarted`).

State machine summary (inside `_process_schedule`):

| Situation | Action |
|-----------|--------|
| `not enabled` but `status` on | `_stop` (turn off). |
| `is_running` and **not** `status` | `_start_automatic` — mode `Automatic`, or `Automatic: started after scheduled time` if `now` is already past the scheduled time. |
| `is_running`, `status`, but not started in this process | Resume: mode `Restarted` (if never started) or automatic mode. Turns on with `force_hardware=True`. |
| **not** `is_running`, `status`, no active manual | `_stop`. |

Built-in safety rules:

- **`manually_turned_off`**: if the user manually turned a valve off, the
  controller **does not turn it back on** in the same window (`_start_automatic`
  checks `has_active_automatic`). See task `006-block-auto-restart-after-manual-off`.
- **Shared pump** (`keep_pump_on`): when turning off a valve, the pump only turns
  off if **no other** valve/manual run is active (`_should_keep_valve_on`,
  `ValveService.turn_off`).
- **Valve shared by multiple schedules**: `_should_keep_valve_on` keeps the valve
  on if another active schedule uses the same pin.
- **Restart recovery**: startup first configures outputs low and restores every
  persisted-on valve. A resumed schedule then reasserts the valve and shared
  pump outputs with `force_hardware=True` before recording its separate
  `Restarted` row or publishing a healthy heartbeat. GPIO activation errors
  propagate and therefore produce neither a successful restart row nor a new
  heartbeat.

`ManualControlService.turn_on(wait=True)` blocks until the end time, polling; if
the valve is turned off earlier, it clears the schedule's `status`. That is why
the CLI accepts `--no-wait` (used in tests and by the dashboard, which cannot
block).

---

## 7. Persistence (`infrastructure/sqlite_repository.py`)

Database: `data/irrigation.db`. Opened by `connect_database()` with
`journal_mode=WAL`, `foreign_keys=ON`, `busy_timeout=5000`, `isolation_level=None`
(manual transaction control via `_write_transaction` → `BEGIN IMMEDIATE`).

### Schema (SQL in `SCHEMA`)

| Table | Key columns | Notes |
|-------|-------------|-------|
| `schedules` | `time, duration_minutes, valve_pin, status, enabled` | `time` stores canonical times separated by `\|`. |
| `schedule_weekdays` | `schedule_id → schedules(id)`, `weekday` | N:N normalization of days; `ON DELETE CASCADE`. |
| `valves` | `pin (UNIQUE), section, status, manually_turned_off` | Ships **empty** in deploy packages (pins are only known after wiring). |
| `settings` | `id=1, default_duration_minutes` | Single row. |
| `credentials` | `id=1, username (UNIQUE), password_hash` | PBKDF2. |
| `history` | `valve, date, start, end, weekday, mode` | `idx_history_date` index for range search. |
| `runtime_health` | `id=1, last_seen_at` | Daemon heartbeat. |

### Two repository classes

- **`SqliteRepository(connection, table)`** — generic for "flat" tables
  (`valves`, `settings`, `credentials`, `history`). Columns declared in
  `_TABLE_COLUMNS`. Only `history` exposes `find_by_date_range`.
- **`ScheduleSqliteRepository`** — specific, because a schedule has the related
  `schedule_weekdays` table. Inserts/updates the days in a transaction and
  rebuilds `times` from the `time` column in `_record`.
- **`RuntimeHealthSqliteRepository`** — heartbeat upsert (`ON CONFLICT`).

All writes go through `_write_transaction` (atomic commit/rollback). `update`
requires **all** columns of the table (full update, not partial).

### Legacy data migration (`json_migration.py`)

On first startup (`Application.__post_init__`), if legacy JSON Lines files exist
in `data_dir`, they are imported into SQLite **once**, protected by a file lock
(`fcntl`). The original files are preserved for verification. Already done (task
`010`).

---

## 8. GPIO (`infrastructure/gpio.py`)

`create_gpio(driver, pump_pin)` returns:

- **`GPIORaspberryPi`** (`driver="rpi"`, default) — uses `RPi.GPIO` in **`BOARD`**
  mode (physical pin numbering). `turn_on` turns on the pin **and the pump**;
  `turn_off` turns off the pin and, if `keep_pump_on=False`, the pump. Raises
  `HardwareError` if `RPi.GPIO` is unavailable.
- **`MockGPIO`** (`driver="mock"`) — in-memory simulator for dev/tests, no
  hardware. Keeps states in a dict.

On controller startup, `ValveService.configure()` translates persisted-on valve
state back into hardware commands. Since `turn_on` drives both the selected
valve and the shared pump high, a successfully restored running schedule has
both outputs asserted; enabled future schedules remain configured low.

> ⚠️ High level = on. Always use relay/transistor modules; GPIO pins must not
> power the pump/valves directly.

---

## 9. Configuration (`config.py`) and environment

`Settings.from_env()` reads environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `IRRIGATION_DATA_DIR` | `./data` | Where the `.db` and search snapshot live. |
| `IRRIGATION_PUMP_PIN` | `15` | Physical pump pin. |
| `IRRIGATION_POLL_INTERVAL` | `5` | Daemon loop interval (s). |
| `IRRIGATION_GPIO_DRIVER` | `rpi` | `rpi` (production) or `mock` (dev). |
| `TZ` | `America/Fortaleza` | Timezone (docker-compose). |

Derived properties: `database_path` = `data_dir/irrigation.db`,
`history_search_results_path` = `data_dir/history_search_results.json`.

---

## 10. Composition root (`bootstrap.py`)

`Application` is the **only place** that wires everything together. Each method
builds a service already connected to its concrete ports over the same
`sqlite3.Connection`:

```python
app = Application.create()          # reads Settings.from_env(), migrates legacy, opens DB, creates default credentials
app.schedules()          # ScheduleService(ScheduleSqliteRepository(conn))
app.valves()             # ValveService(SqliteRepository(conn, "valves"), create_gpio(...))
app.manual_control()     # ManualControlService(valves, settings, history, SystemClock, poll, schedules)
app.automatic_controller()  # IrrigationController(schedules, valves, history, SystemClock, poll, health)
app.history() / app.runtime_settings() / app.auth() / app.runtime_health()
```

To **add a dependency to a service**, inject it here — do not instantiate
infrastructure inside the services.

---

## 11. CLI (`cli.py`) — the contract with Node-RED

Entry point: `irrigation` (defined in `pyproject.toml → [project.scripts]`).
`execute()` parses args, creates the `Application`, dispatches to a handler, and
prints the result as **single-line JSON** (`stdout`). Known errors
(`IrrigationError`, `ValueError`, `KeyError`) become `Error: ...` on `stderr` and
**exit code 2**.

Commands (each reads/writes JSON dicts — this is the contract the dashboard
consumes):

| Command | Usage | Output |
|---------|-------|--------|
| `run` | Starts the daemon (infinite loop). Handles `SIGTERM` for a clean stop. | — |
| `health [--max-age-seconds N]` | Daemon heartbeat. Default: `poll_interval*3 + 5`. | `{status, component, last_seen_at, age_seconds, max_age_seconds}` |
| `schedule list` | List with runtime status. | array of schedules + `is_running`/`valve_status`/`remaining_seconds` |
| `schedule create` | `data = "HH:MM[+HH:MM...],minutes,pin[,weekdays]"` | created schedule |
| `schedule update` | `data = "id,HH:MM[...],minutes,pin[,weekdays]"` | updated schedule |
| `schedule delete <id>` | Removes; turns off the valve if it becomes orphaned. | `{deleted: bool}` |
| `schedule enabled` | `data = "id,0\|1"` | updated schedule |
| `valve list` | List valves. | array of valves |
| `valve add` | `data = "pin,section"` | created valve |
| `valve update` | `data = "id,pin,section"` | updated valve |
| `valve delete <id>` | Removes an unused valve. | `{deleted: bool}` |
| `valve "pin,on[,minutes][,schedule_id]"` | Manual on (accepts `--no-wait`). | `{changed: bool}` |
| `valve "pin,off[,schedule_id]"` | Manual off. | `{changed: bool}` |
| `settings show` | Default duration. | `{id, default_duration_minutes}` |
| `settings <minutes>` | Updates the default duration. | record |
| `auth login` | stdin JSON only; credentials are rejected in argv | `{authenticated: bool}` |
| `auth change-password` | stdin JSON only; credentials are rejected in argv | `{changed: bool}` |
| `history "day,,"` | Today's watering runs. | array |
| `history "range,YYYY-MM-DD,YYYY-MM-DD"` | Runs in the range. | array |

The non-auth argv forms above remain available for trusted interactive/device-shell
use. Authentication secrets are stdin-only. Node-RED must use the shell-free stdin
contract: invoke only
`irrigation --stdin` and send one JSON object (maximum 4096 UTF-8 bytes) through
stdin. The object contains `command`, `action` when applicable, and named fields;
for example:

```json
{"command":"valve","action":"add","pin":13,"section":"Jardim da frente"}
```

Schedule requests use named fields such as `times`, `duration_minutes`,
`valve_pin`, and `weekdays`; auth requests use `username`, `password`,
`current_password`, and `new_password`. Empty, oversized, malformed, or incomplete
objects return the usual `Error: ...` on stderr with exit code 2. Secrets and
untrusted dashboard values must never be added to argv. Keep the single-line JSON
stdout contract stable when adding commands.

---

## 12. Node-RED dashboard (`node-red/`)

- **`flows.json`** — the dashboard flows. Function nodes build structured request
  objects and call the `invokeIrrigationNode` adapter; `inject` nodes poll
  periodically (e.g. schedule list every ~3 s, health every ~10 s). The frontend
  consumes the CLI's JSON directly — **that is why the JSON output is a
  contract**.
- **`templates/*.html`** — Angular screens (Node-RED classic dashboard):
  `agendamentos.html`, `novo-agendamento.html`, `configuracoes.html`,
  `historico.html`. The UI is in Portuguese; business logic does **not** live
  here (the template only formats and does the client-side countdown).
- **`settings.js`** — Node-RED runtime configuration and the sole process adapter.
  It uses `execFile` with the fixed argv `['--stdin']` and writes JSON to the
  child's stdin. Do not replace this with `exec`, shell pipelines, or payloads in
  argv.

The HTML files in `node-red/templates/` are the source of truth for dashboard
screens. `node-red/flows.json` still contains the embedded `ui_template.format`
strings because Node-RED imports them from that file, but those strings are
generated. After editing a template, run:

```bash
python3 scripts/sync_flows_templates.py
```

Docker Compose runs this sync automatically before starting Node-RED, and
`scripts/build-binary.sh` runs it before packaging `node-red/` for the Raspberry
Pi. CI also checks that committed `flows.json` is already in sync.

Rule: **no business logic in Node-RED.** It is a thin shell that calls the CLI.
If you need new logic, it goes into a service and is exposed by a command.

---

## 13. Deploy and execution

### Development (Docker)

```bash
docker compose up          # brings up scheduler (daemon, GPIO mock) + node-red (:1880)
```

`docker-compose.yml` defines two services with the same image, both with
`IRRIGATION_GPIO_DRIVER=mock` and a `.:/app` volume.

### Local (without Docker)

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
IRRIGATION_GPIO_DRIVER=mock irrigation run          # daemon
IRRIGATION_GPIO_DRIVER=mock irrigation schedule list  # CLI
```

### Raspberry Pi (production)

- `scripts/install-raspberry.sh` — automated installation.
- `scripts/build-binary.sh` — compiles `src/irrigation` into `dist/irrigation` (Nuitka).
- `deploy/systemd/irrigation.service.template` — daemon service.
- `deploy/systemd/nodered-override.conf.template` — Node-RED override.
- Installs with `RPi.GPIO` (`pip install ".[raspberry]"`), `driver=rpi`.
- After wiring, register valves from `Configurações > Seções` or with
  `irrigation valve add "pin,section"`.

---

## 14. Tests and quality

```bash
.venv/bin/python -m pytest              # full suite (~130 tests)
.venv/bin/python -m ruff check .        # lint
.venv/bin/python -m ruff format --check .  # formatting
```

Config in `pyproject.toml`: `pythonpath=["src"]`, `testpaths=["tests"]`, ruff
`line-length=88`, rules `E,F,I,UP,B,SIM`.

Test map (use as a reference when touching each area):

| File | Covers |
|------|--------|
| `test_models.py` | Entity validation and rules (times, weekdays, intervals, midnight). |
| `test_services.py` | All use cases — the largest file; mirrors the controller/manual behavior. |
| `test_cli.py` | CLI contract (parsing, JSON, exit codes). |
| `test_sqlite_repository.py` / `test_repository.py` | Persistence and transactions. |
| `test_json_migration.py` | Legacy-format import. |
| `test_node_red_flow.py` / `test_node_red_settings.py` | Integrity of Node-RED flows and settings. |

Tests use `MockGPIO` and a fixed `Clock` (never real hardware nor an uncontrolled
`datetime.now`).

---

## 15. How to create a new feature (step by step)

1. **Write the task** in `tasks/NNN-description-in-kebab-case.md` from
   `tasks/template.md` (sequential number, `status: backlog`). The template
   guides you: specification, impact analysis, technical approach, tests, and
   acceptance criteria. See `tasks/done/` for real, well-detailed examples.
2. **Business rule** → add/adjust validation in an entity in `domain/models.py`.
   Keep the entity immutable and validated in `__post_init__`.
3. **Use case** → a new method on a service in `application/services.py` (or a new
   service, if it is a cohesive and distinct responsibility). Depend on ports,
   never on infrastructure.
4. **Persistence/hardware** → if you need a new kind of access, extend the port in
   `domain/ports.py` and implement it in `infrastructure/`. New column/table?
   Update `SCHEMA` and `_TABLE_COLUMNS` in `sqlite_repository.py` (the schema is
   idempotent — `CREATE TABLE IF NOT EXISTS`).
5. **Injection** → wire everything in `bootstrap.py`.
6. **Exposure** → a new subcommand in `cli.py` (follow the `_..._command` +
   `_COMMAND_HANDLERS` + `create_parser` pattern) returning stable JSON.
7. **Dashboard** → if it is user-facing, add `exec`/`inject` nodes in
   `node-red/flows.json`, edit the HTML in `node-red/templates/`, and run
   `python3 scripts/sync_flows_templates.py`. No business logic in the frontend.
8. **Tests** → cover the domain (`test_models`), use case (`test_services`), CLI
   (`test_cli`) and, if you touched the dashboard, `test_node_red_flow`. Use
   `MockGPIO` and a fixed `Clock`.
9. **Validate** → run pytest + ruff (check and format). Only then move the task to
   `status: done` and to `tasks/done/`.

### Architecture mental checklist

- [ ] Does the domain still avoid importing `sqlite3`/`RPi.GPIO`/Node-RED?
- [ ] Is validation in the entity, not scattered across services?
- [ ] Do new dependencies enter via a port + injection in the bootstrap?
- [ ] Did the CLI's JSON output stay compatible?
- [ ] Is daemon × CLI concurrency respected (writes in a transaction)?
- [ ] Are `manually_turned_off` and `keep_pump_on` still correct if you touched
      valves/controller?

---

## 16. Pitfalls and invariants that must not break

- **The CLI JSON contract** is consumed directly by the dashboard — an
  incompatible change silently breaks the UI.
- **One schedule per valve/pin** (`ScheduleService._reject_duplicate_valve`).
- **`status` (watering) vs. `enabled` (active)** are different things; don't
  confuse them.
- **Midnight**: any interval calculation must reuse `Schedule.interval_at` /
  `_interval_for_time`, which already handle the day rollover.
- **Pump**: never turn the pump off without checking for other active
  valves/manual runs.
- **Manual off** must suppress automatic restart in the same window.
- **Immutable entities**: use `replace(...)`; do not try to assign attributes.
- **Full update in SQLite**: `update()` requires all of the table's fields.
- **Heartbeat**: `run()` calls `touch` every cycle; `health` derives
  online/offline from the age. If you change `poll_interval`, the default `health`
  threshold (`poll_interval*3+5`) follows along.
