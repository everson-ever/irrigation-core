# Installation on Raspberry Pi

This package contains the pre-compiled irrigation system binary and every
file needed to install it — **without the Python source code**.

## Contents

```
.
├── data/                          # Schedules, valves, and history
├── deploy/systemd/                # systemd service templates
├── dist/irrigation                # Compiled binary (no Python required)
├── node-red/flows.json            # Node-RED dashboard/flow
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
   - configures the Node-RED service (`PATH` and working directory), if it
     already exists on the system.

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

## Default data

`data/` ships with placeholder values, not a real installation's history:

- `valves.json`: two valves already registered — pin 13 as "Section 1" and
  pin 11 as "Section 2" (matching the pump on pin 15, see the main
  [README](../README.md#default-hardware)). Edit this file to match your
  wiring and section names before going live.
- `schedules.json` and `history*.json`: empty.
- `settings.json`: default manual watering duration of 5 minutes.

## Service operation

```bash
sudo systemctl status irrigation
sudo systemctl restart irrigation
sudo systemctl stop irrigation
journalctl -u irrigation -f
```

## Configuration

To change configuration without recompiling, create
`/etc/default/irrigation-system`:

```bash
IRRIGATION_DATA_DIR=/absolute/path/to/data
IRRIGATION_GPIO_DRIVER=rpi
IRRIGATION_PUMP_PIN=15
IRRIGATION_POLL_INTERVAL=5
```

Restart the service after editing the file.
