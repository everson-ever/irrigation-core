#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run with sudo: sudo ./scripts/install-raspberry.sh" >&2
  exit 1
fi

PROJECT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
RUN_USER=${SUDO_USER:-$(stat -c '%U' "${PROJECT_DIR}")}
BINARY_SRC="${PROJECT_DIR}/dist/irrigation"
BINARY_DIR=/opt/irrigation/bin
BINARY_DST="${BINARY_DIR}/irrigation"

if [[ ! -x "${BINARY_SRC}" ]]; then
  echo "Compiled binary not found at ${BINARY_SRC}." >&2
  echo "Run scripts/build-binary.sh first (or copy a binary built elsewhere)." >&2
  exit 1
fi

usermod -aG gpio "${RUN_USER}"

mkdir -p "${BINARY_DIR}"
install -o root -g root -m 755 "${BINARY_SRC}" "${BINARY_DST}"

sed \
  -e "s|__PROJECT_DIR__|${PROJECT_DIR}|g" \
  -e "s|__RUN_USER__|${RUN_USER}|g" \
  -e "s|__BINARY__|${BINARY_DST}|g" \
  "${PROJECT_DIR}/deploy/systemd/irrigation.service.template" \
  > /etc/systemd/system/irrigation.service

if systemctl list-unit-files nodered.service >/dev/null 2>&1; then
  mkdir -p /etc/systemd/system/nodered.service.d
  sed \
    -e "s|__PROJECT_DIR__|${PROJECT_DIR}|g" \
    -e "s|__BINARY_DIR__|${BINARY_DIR}|g" \
    "${PROJECT_DIR}/deploy/systemd/nodered-override.conf.template" \
    > /etc/systemd/system/nodered.service.d/irrigation.conf
fi

chown -R "${RUN_USER}:${RUN_USER}" "${PROJECT_DIR}/data"
systemctl daemon-reload
systemctl enable --now irrigation.service

echo "Installation complete. Operational data is stored in data/irrigation.db."
echo "Legacy JSON data is imported automatically when the database does not exist."
echo "Import node-red/flows.json using the Node-RED editor."
