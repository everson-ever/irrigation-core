# Installation on Raspberry Pi

This package contains the pre-compiled irrigation system binary and every
file needed to install it — **without the Python source code**.

## Contents

```
.
├── data/                          # SQLite database and search snapshot
├── deploy/systemd/                # systemd service templates
├── dist/irrigation                # Compiled binary (no Python required)
├── node-red/flows.json            # Node-RED dashboard/flow
├── node-red/settings.js           # Node-RED authentication settings
└── scripts/install-raspberry.sh   # Installer
```

## Requirements on the Raspberry Pi

- Raspberry Pi OS (or another Debian-based distro) with the same
  architecture used to compile the binary (armv7l or aarch64).
- Node-RED installed, if you want to use the web dashboard.

## Steps

1. Copy this folder to the Raspberry Pi, for example:

   ```bash
   scp -r irrigation-deploy pi@<pi-ip>:~/irrigation-deploy
   ```

2. On the Raspberry Pi, enter the folder and run the installer as root:

   ```bash
   cd irrigation-deploy
   sudo ./scripts/install-raspberry.sh
   ```

   The script:
   - copies the binary to `/opt/irrigation/bin/irrigation`;
   - adds the user to the `gpio` group;
   - installs and starts the `irrigation.service` systemd service;
   - configures the Node-RED service (`PATH`, working directory, and
     `node-red/settings.js`), if it already exists on the system.

3. If `node-red-dashboard` is not installed yet, run the following with the
   user that runs Node-RED:

   ```bash
   cd ~/.node-red
   npm install node-red-dashboard
   ```

4. In the Node-RED editor (`http://<pi-ip>:1880`):
   - open the **Import** menu;
   - select this folder's `node-red/flows.json`;
   - confirm the deploy;
   - open the dashboard at `http://<pi-ip>:1880/ui`.

   The dashboard and Node-RED editor require authentication. The default
   credentials are:

   - username: `admin`
   - password: `10203040`

   Change this password after the first login from **Configurações → Trocar
   senha**.

## Default data

`data/irrigation.db` ships without installation-specific valve pins or history.
It contains the normalized schema and a default manual watering duration of 5
minutes. The default `admin` account is seeded automatically on first
application start if the credentials table is empty. After wiring the system,
add valves from the dashboard in `Configurações > Seções`, using physical pin
numbering (`GPIO.BOARD`). You can also use the CLI:

```bash
irrigation valve add "13,Front garden"
irrigation valve add "11,Back garden"
```

These pin numbers are only examples. Replace them with the physical pins used
in the installation. `history_search_results.json` remains an empty transient
dashboard snapshot.

Upgrades from the legacy JSON Lines format are automatic: if
`data/irrigation.db` does not exist, the first application start imports
`schedules.json`, `valves.json`, `settings.json`, and `history.json`, preserving
IDs and leaving those files untouched for verification.

## Service operation

```bash
sudo systemctl status irrigation
sudo systemctl restart irrigation
sudo systemctl stop irrigation
journalctl -u irrigation -f
/opt/irrigation/bin/irrigation health
```

The dashboard status badge uses the `irrigation health` command through
Node-RED. The command reports `online` only when the long-running
`irrigation.service` controller has updated its heartbeat recently.

## Configuration

To change configuration without recompiling, create
`/etc/default/irrigation-system`:

```bash
IRRIGATION_DATA_DIR=/absolute/path/to/data
IRRIGATION_GPIO_DRIVER=rpi
IRRIGATION_PUMP_PIN=15
IRRIGATION_POLL_INTERVAL=5
```

Set `IRRIGATION_PUMP_PIN` to the physical pin chosen for the pump relay; it is
configured separately and must not be added to the `valves` table.

Restart the service after editing the file.

Node-RED must load `node-red/settings.js` for dashboard authentication to be
active. The installer sets `NODE_RED_OPTIONS=--settings
<project>/node-red/settings.js` for the packaged `nodered.service`; if your
Node-RED installation uses a custom service, apply the same setting manually.
