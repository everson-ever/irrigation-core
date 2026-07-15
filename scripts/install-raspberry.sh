#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run with sudo: sudo ./scripts/install-raspberry.sh" >&2
  exit 1
fi

PROJECT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
RUN_USER=${SUDO_USER:-$(stat -c '%U' "${PROJECT_DIR}")}

apt-get update
apt-get install -y python3 python3-venv python3-pip
usermod -aG gpio "${RUN_USER}"

sudo -u "${RUN_USER}" python3 -m venv "${PROJECT_DIR}/.venv"
sudo -u "${RUN_USER}" "${PROJECT_DIR}/.venv/bin/pip" install --upgrade pip
sudo -u "${RUN_USER}" "${PROJECT_DIR}/.venv/bin/pip" install "${PROJECT_DIR}[raspberry]"

sed \
  -e "s|__PROJECT_DIR__|${PROJECT_DIR}|g" \
  -e "s|__RUN_USER__|${RUN_USER}|g" \
  "${PROJECT_DIR}/deploy/systemd/irrigation.service.template" \
  > /etc/systemd/system/irrigation.service

if systemctl list-unit-files nodered.service >/dev/null 2>&1; then
  mkdir -p /etc/systemd/system/nodered.service.d
  sed "s|__PROJECT_DIR__|${PROJECT_DIR}|g" \
    "${PROJECT_DIR}/deploy/systemd/nodered-override.conf.template" \
    > /etc/systemd/system/nodered.service.d/irrigation.conf
fi

chown -R "${RUN_USER}:${RUN_USER}" "${PROJECT_DIR}/data"
systemctl daemon-reload
systemctl enable --now irrigation.service

echo "Installation complete. Import node-red/flows.json using the Node-RED editor."
