# Automated irrigation system

Irrigation system for Raspberry Pi with scheduling, manual activation, history,
and a Node-RED web dashboard.

The current application was restructured with layered architecture, testable
code, and inverted dependencies. Historical directories from previous versions
were removed from the main tree; the version to install and run is at the root
of this repository.

Main classes, methods, functions, variables, and commands use English naming.
File names and JSON fields were kept unchanged to preserve compatibility with
the dashboard and existing data.

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
├── scripts/instalar-raspberry.sh # Automated Raspberry Pi installation
├── src/irrigacao/
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

Files remain in JSON Lines format (one JSON object per line), compatible with
the read nodes from the original flow. Writes now use locking and atomic
replacement to reduce the risk of corruption when Node-RED and the scheduler
access data concurrently.

## Default hardware

The project uses physical pin numbering (`GPIO.BOARD`). The initial
configuration in [`data/valvulas.json`](data/valvulas.json) is:

| Function | Physical pin |
|---|---:|
| Section 1 solenoid valve | 13 |
| Section 2 solenoid valve | 11 |
| Pump | 15 |

Adapt `data/valvulas.json` and `IRRIGATION_PUMP_PIN` to the real installation.
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
sudo ./scripts/instalar-raspberry.sh
```

The script:

1. installs Python, `venv`, and `pip` through the system package manager;
2. creates `.venv` and installs the project with the `RPi.GPIO` driver;
3. adds the user to the `gpio` group;
4. installs and starts the `irrigacao.service` service;
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
sudo systemctl status irrigacao
sudo systemctl restart irrigacao
sudo systemctl stop irrigacao
journalctl -u irrigacao -f
```

To change configuration without editing code, create
`/etc/default/sistema-irrigacao`:

```bash
IRRIGATION_DATA_DIR=/absolute/path/to/data
IRRIGATION_GPIO_DRIVER=rpi
IRRIGATION_PUMP_PIN=15
IRRIGATION_POLL_INTERVAL=2
```

Restart the service after changing the file.

## Development without Raspberry Pi

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
export IRRIGATION_GPIO_DRIVER=mock
```

Useful commands:

```bash
# Run the scheduler in the foreground
irrigacao run

# Create: time,duration in minutes,physical pin
irrigacao schedule create '06:30,15,13'

# Update: id,time,duration,pin
irrigacao schedule update '1,07:00,10,13'

# Disable or re-enable
irrigacao schedule enabled '1,0'
irrigacao schedule enabled '1,1'

# Delete
irrigacao schedule delete 1

# Manual activation
irrigacao valve '13,on'
irrigacao valve '13,off'

# Change the default manual time
irrigacao settings 5

# Search history
irrigacao history 'day,,'
irrigacao history 'range,2026-07-01,2026-07-31'
```

In manual mode, the `on` command remains active until the default time ends or
another `off` command turns the valve off. This preserves the behavior expected
by the Node-RED `exec` node.

Legacy Portuguese commands are still accepted as compatibility aliases, but the
documentation and new flows use the English CLI.

## Tests and quality

```bash
source .venv/bin/activate
pytest
ruff check src tests
ruff format --check src tests
```

Tests do not access real GPIO. They verify validation, compatibility with the
legacy `led` field, persistence, delayed start, restart, shutdown, disabled
schedules, and intervals that cross midnight.

## Data and Part 7 migration

Operational files are stored in `data/`:

- `agendamentos.json`: schedules and their execution state;
- `valvulas.json`: pins, sections, and states;
- `configuracoes.json`: default manual activation time;
- `historico.json`: activation log;
- `pesquisaHistoricoResultado.json`: result consumed by the dashboard.

A new installation starts without schedules. To migrate entries from the
previous final version, pass an external copy of the legacy `Parte - 7/projeto`
directory to the command:

```bash
sudo systemctl stop irrigacao
cp -a data "data.backup.$(date +%Y%m%d-%H%M%S)"
source .venv/bin/activate
irrigacao migrate-part-7 --source /path/to/Parte\ -\ 7/projeto
sudo systemctl start irrigacao
```

The migrator converts the old `led` field to `valvula`, keeps IDs and data, and
resets execution states to avoid reactivating old irrigation runs. The Python
reader accepts both fields during the transition, but the new dashboard expects
`valvula`.

Before replacing production data, create a backup and keep `status` fields set
to `0`, avoiding interpretation of a long-interrupted execution as active.

## Screens

| Schedules | New schedule |
|---|---|
| ![Schedules](screenshot%20application/agendamentos.png) | ![Create schedule](screenshot%20application/cadastro%20agendamentos.png) |

| Valves | Default time | Logs |
|---|---|---|
| ![Valves](screenshot%20application/valvulas.png) | ![Default time](screenshot%20application/tempo%20padrao.png) | ![Logs](screenshot%20application/logs.png) |
