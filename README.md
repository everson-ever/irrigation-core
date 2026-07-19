# Automated irrigation system

Irrigation system for Raspberry Pi with scheduling, manual activation, history,
and a Node-RED web dashboard.

The application uses a layered architecture, testable code, and inverted
dependencies. The version to install and run is at the root of this repository.

Main classes, methods, functions, variables, and commands use English naming.
The CLI JSON output is part of the current dashboard contract.

## Features

- Create, edit, enable, disable, and delete schedules.
- Select which weekdays each schedule runs on, including every day.
- Automatic solenoid valve activation.
- Resume an interrupted irrigation while the schedule is still valid.
- Delayed start when the system comes back online during an irrigation window.
- Manual activation and shutdown.
- Configurable automatic shutdown time for manual mode.
- History logging and search by day or date range.
- Valve state visualization in the Node-RED dashboard.
- Common configuration and latest-status dashboard for reservoir-level, flow,
  soil-moisture, line-pressure, and rain sensors.
- Optional Discord webhook notifications for irrigation and account events.
- Support for schedules that cross midnight.
- Simulated GPIO driver for development without a Raspberry Pi.

## Architecture

```text
.
├── data/                         # SQLite database and search snapshot
├── deploy/systemd/               # Scheduler service and Node-RED override
├── node-red/flows.json           # Updated dashboard and integration
├── scripts/build-binary.sh       # Compiles src/irrigation into dist/irrigation
├── scripts/install-raspberry.sh # Automated Raspberry Pi installation
├── src/irrigation/
│   ├── application/              # Use cases and orchestration
│   ├── domain/                   # Entities, rules, and contracts
│   ├── infrastructure/           # SQLite, Discord HTTP, legacy import, GPIO, clock
│   ├── bootstrap.py              # Dependency injection
│   └── cli.py                    # Interface used by systemd and Node-RED
├── tests/                        # Unit tests
└── pyproject.toml                # Package, dependencies, and tooling
```

Responsibilities were separated following SOLID principles:

- Entities validate only domain rules.
- Each service represents a cohesive set of use cases.
- Persistence, clock, and GPIO are contracts injected into the services.
- The real driver can be replaced by the simulated one without changing rules.
- The Node-RED interface calls a thin CLI; it contains no business rules.

Authoritative data is stored in `data/irrigation.db`. SQLite transactions, WAL
mode, foreign keys, and a busy timeout keep concurrent scheduler and Node-RED
CLI access safe. A schedule can contain one to three daily start times, stored
canonically in its time field, while weekdays use a related table; history dates
are indexed for range searches. On first start, installations
that still have the legacy JSON Lines files are imported automatically while
the original files are left in place for verification.

## Hardware configuration

The project uses physical pin numbering (`GPIO.BOARD`). Deployment packages
ship with an empty `valves` table because the valve pins are only known after
the system is wired. After installation, register valves from the dashboard in
`Configurações > Seções`, or through the CLI:

```bash
irrigation valve add "13,Front garden"
irrigation valve add "11,Back garden"
```

The values above are examples, not recommended defaults. Existing valve records
can be listed with `irrigation valve list`, edited with
`irrigation valve update "id,pin,section"`, and removed with
`irrigation valve delete <id>`. Configure the pump pin
separately with `IRRIGATION_PUMP_PIN`, using the physical pin selected during
installation.
Use proper relay/transistor modules: GPIO pins must not power the pump or
solenoid valves directly. Also confirm the electrical logic of your relay before
energizing the circuit; this implementation treats high level as on.

Sensors can be registered, edited, enabled, disabled, inspected, and removed in
`Configurações > Sensores` or through `irrigation sensor`. Every UI and API pin
label uses the physical connector number (**BOARD**), never an ambiguous BCM
label such as `GPIO23`. The current sensor foundation does not read hardware or
change irrigation decisions; wiring validation and live tests become available
only when each type-specific driver is implemented. Dashboard configuration is
not a substitute for safe physical wiring or voltage-level protection.

Discord notifications are configured in `Configurações > Discord`. Add one
`https://discord.com/api/webhooks/...` URL and enable only the desired events,
including section on/off notifications shared by manual and automatic control.
Deleting the webhook also disables every event. Delivery uses the Python
standard library in a detached best-effort worker with a five-second timeout and
no retries, so Discord failures never delay irrigation, CRUD, or password
changes. Webhook URLs and password data are never included in messages.

## Requirements

- Raspberry Pi with Raspberry Pi OS.
- Python 3.10 or newer on whichever machine builds the binary (see
  [Installation](#installation-on-raspberry-pi)); not required on the target
  device if you install a binary built elsewhere.
- Access to GPIO pins.
- Internet access during installation when Node.js or npm is not already
  installed; the installer obtains both from the Raspberry Pi OS package
  repositories.
- Node-RED to use the web dashboard; the installer preserves and configures an
  existing `nodered.service`, but does not install Node-RED itself.
- The `node-red-dashboard` module to import the existing dashboard.

## Installation on Raspberry Pi

Installation happens in two steps: build a native binary from the Python
source, then install that binary. This means the target device never needs
Python, a virtualenv, or the `.py` files themselves — only the compiled
executable, the `data/` directory, and the Node-RED flow.

### 1. Build the binary

Run this on a Raspberry Pi (or another machine with the same CPU
architecture/OS as the target — Nuitka does not cross-compile):

```bash
git clone <THIS-REPOSITORY-URL>
cd Sistema-de-irriga-o
./scripts/build-binary.sh
```

This compiles `src/irrigation` with [Nuitka](https://nuitka.net/) into
`dist/irrigation`, a single self-contained executable. It installs build-only
tooling (`build-essential`, `patchelf`, a throwaway `.venv-build`) that is not
needed at runtime. The build also creates
`dist/irrigation-deploy-<version>.zip`, containing the executable, clean
default data, the Node-RED files, and the systemd templates.

### 2. Install on the target device

If the build was created on the same Raspberry Pi that will run the system,
install directly from the repository root; no file-copy step is needed:

```bash
sudo ./scripts/install-raspberry.sh
```

If the target is a different Raspberry Pi, copy the generated deployment ZIP
instead of selecting folders manually. For example, from the build machine:

```bash
scp dist/irrigation-deploy-*.zip app@RASPBERRY_IP:~/
```

Then, on the target Pi, extract the ZIP, enter the extracted
`irrigation-deploy-<version>` directory, and install:

```bash
unzip irrigation-deploy-*.zip
cd irrigation-deploy-*/
sudo ./scripts/install-raspberry.sh
```

The source checkout intentionally ignores the operational `data/` directory.
When installing directly from a clean checkout, the installer creates it from
`deploy/data-defaults` without overwriting an existing database or legacy JSON
files. The deployment ZIP already includes a clean `data/` directory.

The script:

1. initializes `data/` from the deployment defaults when it is absent;
2. installs Node.js and npm through `apt` when either command is missing;
3. installs the compiled binary at `/opt/irrigation/bin/irrigation`;
4. adds the user to the `gpio` group;
5. installs and starts the `irrigation.service` service;
6. configures the Node-RED service directory and `PATH` when it exists.

The service uses the installation directory as its working directory and keeps
operational state in its `data/` folder. Do not move or remove that directory
after installation.

After the first installation, restart the session or reboot the Raspberry Pi so
the `gpio` group change takes effect:

```bash
sudo reboot
```

### Configure Node-RED

Node.js and npm are installed automatically by the irrigation installer. If the
dashboard module is not installed yet, run the following command with the user
that runs Node-RED:

```bash
cd ~/.node-red
npm install node-red-dashboard
```

In the Node-RED editor:

1. open the **Import** menu;
2. select [`node-red/flows.json`](node-red/flows.json);
3. confirm the deploy;
4. open `http://RASPBERRY_IP:1880/ui`.

The dashboard and Node-RED editor require authentication through
[`node-red/settings.js`](node-red/settings.js). The default credentials are
`admin` / `10203040`; change the password after the first login from
**Configurações → Trocar senha**.

If the changed password is lost, access the Raspberry Pi through SSH or its
local console and run:

```bash
irrigation auth reset-to-default
```

This restores `admin` / `10203040`. The recovery command is intentionally
available only from the device shell and is not exposed through the dashboard
or a Node-RED flow.

The flow uses the binary installed at `/opt/irrigation/bin/irrigation`. Node-RED
always starts it as `irrigation --stdin` without a shell and sends one structured
JSON request through standard input. Dashboard values and credentials are never
appended to a command line; CLI JSON responses on stdout remain unchanged. Only
the transient history-search snapshot is read directly from `data/`.
The scheduler is not started by the flow: it is managed by `systemd` so it can
restart automatically after failures or reboots.

## Service operation

```bash
sudo systemctl status irrigation
sudo systemctl restart irrigation
sudo systemctl stop irrigation
journalctl -u irrigation -f
```

To change configuration without editing code, create
`/etc/default/irrigation-system`:

```bash
IRRIGATION_DATA_DIR=/absolute/path/to/data
IRRIGATION_GPIO_DRIVER=rpi
IRRIGATION_PUMP_PIN=15
IRRIGATION_POLL_INTERVAL=5
```

Restart the service after changing the file.

## Development without Raspberry Pi

With Docker Compose:

```bash
docker compose up --build
```

Then open the Node-RED dashboard at `http://localhost:1880/ui`.
Use the default credentials `admin` / `10203040` on first login.

The Compose environment uses the mock GPIO driver and the repository `data/`
directory, so it can run on a development machine without Raspberry Pi GPIO
access. The scheduler runs in the `scheduler` service and Node-RED runs in the
`node-red` service.

On Linux, the services run as UID/GID `1000:1000` by default to avoid creating
root-owned files in the mounted repository. If your user has a different ID,
create `.env` from `.env.example` and adjust `DOCKER_UID` and `DOCKER_GID`.
The containers default to the `America/Fortaleza` timezone so dashboard times
and automatic schedules use the same local clock. Set `TZ` in `.env` if the
installation uses another timezone.

Useful Docker commands:

```bash
# Run CLI commands against the same mounted data directory
docker compose run --rm scheduler irrigation schedule create '06:30+18:00,15,13,mon+wed+fri'
docker compose run --rm scheduler irrigation valve '13,on' --no-wait
docker compose run --rm scheduler irrigation history 'day,,'

# Run tests and quality checks inside the image
docker compose run --rm scheduler pytest
docker compose run --rm scheduler ruff check src tests
docker compose run --rm scheduler ruff format --check src tests

# Stop the development environment
docker compose down
```

Without Docker:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
export IRRIGATION_GPIO_DRIVER=mock
```

Useful commands:

```bash
# Run the scheduler in the foreground
irrigation run

# Create: one to three start times,duration in minutes,physical pin,weekdays
irrigation schedule create '06:30,15,13,mon+wed+fri'
irrigation schedule create '06:30+12:00+18:00,15,13,mon+wed+fri'
irrigation schedule create '06:30,15,13,everyday'

# Update: id,one to three start times,duration,pin,weekdays
irrigation schedule update '1,07:00+18:00,10,13,tue+thu'

# Disable or re-enable
irrigation schedule enabled '1,0'
irrigation schedule enabled '1,1'

# Delete
irrigation schedule delete 1

# Manual activation
irrigation valve '13,on'
irrigation valve '13,off'
irrigation valve list

# Common sensor configuration (no hardware reading in this foundation)
irrigation sensor add 'Reservoir level,reservoir_level'
irrigation sensor list
irrigation sensor status 1
irrigation sensor enabled '1,0'

# Discord webhook configuration
irrigation notifications save-webhook 'https://discord.com/api/webhooks/123/token'
irrigation notifications set-event 'section_on,1'
irrigation notifications get
irrigation notifications delete-webhook

# Change the default manual time
irrigation settings 5
irrigation settings show

# Search history
irrigation history 'day,,'
irrigation history 'range,2026-07-01,2026-07-31'
```

In manual mode, the `on` command remains active until the default time ends or
another `off` command turns the valve off. This preserves the behavior expected
by the Node-RED `exec` node.

`schedule delete` returns `{"deleted": true}` when the record was removed,
`{"deleted": false}` when the identifier does not match any schedule (a safe
no-op, exit code 0), and exits with status 2 and an `Error: ...` message on
`stderr` for an empty or malformed identifier. Deleting a schedule that is
currently running also turns off its valve, unless another enabled schedule
still needs the same valve. The dashboard shows a dismissible error banner
above the schedule list when a delete command fails.

The optional schedule weekday field accepts stable identifiers joined with
`+`: `mon`, `tue`, `wed`, `thu`, `fri`, `sat`, `sun`. Use `everyday` for all
seven days. Existing schedules without a `weekdays` field are treated as
every-day schedules.

The schedule time field accepts one, two, or three `HH:MM` values joined with
`+`, `;`, or `|`. Times are normalized into chronological order, duplicates and
overlaps within the same schedule are rejected, and the same duration and
weekdays apply to every configured time slot.

## Tests and quality

```bash
source .venv/bin/activate
pytest
ruff check src tests
ruff format --check src tests
```

Tests do not access real GPIO. They verify validation, persistence, delayed
start, restart, shutdown, disabled schedules, and intervals that cross
midnight.

## Data

Operational data is stored in `data/`:

- `irrigation.db`: authoritative schedules, schedule time slots, normalized
  schedule weekdays, valves, settings, and indexed history;
- `history_search_results.json`: transient result snapshot consumed by the
  dashboard after a history search.

The old `schedules.json`, `valves.json`, `settings.json`, and `history.json`
files are only migration inputs. When `irrigation.db` does not exist, startup
imports every legacy file found and preserves its IDs. The legacy files are not
modified or deleted.

A new installation starts without schedules. Do not reuse files from previous
systems; create schedules and valve configuration for the new installation.

## Screens

| Schedules | New schedule |
|---|---|
| ![Schedules](screenshot%20application/schedules.png) | ![Create schedule](screenshot%20application/create-schedule.png) |

| History | Settings |
|---|---|
| ![History](screenshot%20application/history.png) | ![Settings](screenshot%20application/settings.png) |
