# Automated irrigation system

Irrigation system for Raspberry Pi with scheduling, manual activation, history,
and a Node-RED web dashboard.

The application uses a layered architecture, testable code, and inverted
dependencies. The version to install and run is at the root of this repository.

Main classes, methods, functions, variables, and commands use English naming.
File names and JSON fields are part of the current dashboard contract.

## Features

- Create, edit, enable, disable, and delete schedules.
- Automatic solenoid valve activation.
- Resume an interrupted irrigation while the schedule is still valid.
- Delayed start when the system comes back online during an irrigation window.
- Manual activation and shutdown.
- Configurable automatic shutdown time for manual mode.
- History logging and search by day or date range.
- Valve state visualization in the Node-RED dashboard.
- Support for schedules that cross midnight.
- Simulated GPIO driver for development without a Raspberry Pi.

## Architecture

```text
.
├── data/                         # Persisted data in JSON Lines
├── deploy/systemd/               # Scheduler service and Node-RED override
├── node-red/flows.json           # Updated dashboard and integration
├── scripts/install-raspberry.sh # Automated Raspberry Pi installation
├── src/irrigation/
│   ├── application/              # Use cases and orchestration
│   ├── domain/                   # Entities, rules, and contracts
│   ├── infrastructure/           # JSON Lines, GPIO, and clock
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

Files use JSON Lines format (one JSON object per line). Writes use locking and
atomic replacement to reduce the risk of corruption when Node-RED and the
scheduler access data concurrently.

## Default hardware

The project uses physical pin numbering (`GPIO.BOARD`). The initial
configuration in [`data/valves.json`](data/valves.json) is:

| Function | Physical pin |
|---|---:|
| Section 1 solenoid valve | 13 |
| Section 2 solenoid valve | 11 |
| Pump | 15 |

Adapt `data/valves.json` and `IRRIGATION_PUMP_PIN` to the real installation.
Use proper relay/transistor modules: GPIO pins must not power the pump or
solenoid valves directly. Also confirm the electrical logic of your relay before
energizing the circuit; this implementation treats high level as on.

## Requirements

- Raspberry Pi with Raspberry Pi OS and Python 3.10 or newer.
- Access to GPIO pins.
- Node-RED to use the web dashboard.
- The `node-red-dashboard` module to import the existing dashboard.

## Installation on Raspberry Pi

Clone the repository and run the installer:

```bash
git clone <THIS-REPOSITORY-URL>
cd Sistema-de-irriga-o
sudo ./scripts/install-raspberry.sh
```

The script:

1. installs Python, `venv`, and `pip` through the system package manager;
2. creates `.venv` and installs the project with the `RPi.GPIO` driver;
3. adds the user to the `gpio` group;
4. installs and starts the `irrigation.service` service;
5. configures the Node-RED service directory and `PATH` when it exists.

After the first installation, restart the session or reboot the Raspberry Pi so
the `gpio` group change takes effect:

```bash
sudo reboot
```

### Configure Node-RED

If the dashboard is not installed yet, run the following command with the user
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

The flow uses the commands installed in `.venv` and reads the files in `data/`.
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
IRRIGATION_POLL_INTERVAL=2
```

Restart the service after changing the file.

## Development without Raspberry Pi

With Docker Compose:

```bash
docker compose up --build
```

Then open the Node-RED dashboard at `http://localhost:1880/ui`.

The Compose environment uses the mock GPIO driver and the repository `data/`
directory, so it can run on a development machine without Raspberry Pi GPIO
access. The scheduler runs in the `scheduler` service and Node-RED runs in the
`node-red` service.

On Linux, the services run as UID/GID `1000:1000` by default to avoid creating
root-owned files in the mounted repository. If your user has a different ID,
create `.env` from `.env.example` and adjust `DOCKER_UID` and `DOCKER_GID`.

Useful Docker commands:

```bash
# Run CLI commands against the same mounted data directory
docker compose run --rm scheduler irrigation schedule create '06:30,15,13'
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

# Create: time,duration in minutes,physical pin
irrigation schedule create '06:30,15,13'

# Update: id,time,duration,pin
irrigation schedule update '1,07:00,10,13'

# Disable or re-enable
irrigation schedule enabled '1,0'
irrigation schedule enabled '1,1'

# Delete
irrigation schedule delete 1

# Manual activation
irrigation valve '13,on'
irrigation valve '13,off'

# Change the default manual time
irrigation settings 5

# Search history
irrigation history 'day,,'
irrigation history 'range,2026-07-01,2026-07-31'
```

In manual mode, the `on` command remains active until the default time ends or
another `off` command turns the valve off. This preserves the behavior expected
by the Node-RED `exec` node.

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

Operational files are stored in `data/`:

- `schedules.json`: schedules and their execution state;
- `valves.json`: pins, sections, and states;
- `settings.json`: default manual activation time;
- `history.json`: activation log;
- `history_search_results.json`: result consumed by the dashboard.

A new installation starts without schedules. Do not reuse files from previous
systems; create schedules and valve configuration for the new installation.

## Screens

| Schedules | New schedule |
|---|---|
| ![Schedules](screenshot%20application/schedules.png) | ![Create schedule](screenshot%20application/create-schedule.png) |

| Valves | Default time | Logs |
|---|---|---|
| ![Valves](screenshot%20application/valves.png) | ![Default time](screenshot%20application/default-time.png) | ![Logs](screenshot%20application/logs.png) |
