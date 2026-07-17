#!/usr/bin/env bash
set -euo pipefail

# Compiles src/irrigation into a single native executable (dist/irrigation)
# using Nuitka. Must run on a Raspberry Pi (or another machine with the same
# CPU architecture and libc as the target), since Nuitka does not cross-compile
# and RPi.GPIO is a native extension.

PROJECT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
VENV="${PROJECT_DIR}/.venv-build"

if command -v apt-get >/dev/null 2>&1; then
  sudo apt-get update
  sudo apt-get install -y python3 python3-venv python3-pip python3-dev build-essential patchelf zip
fi

python3 -m venv "${VENV}"
"${VENV}/bin/pip" install --upgrade pip
"${VENV}/bin/pip" install "${PROJECT_DIR}[raspberry,build]"

rm -rf "${PROJECT_DIR}/dist" "${PROJECT_DIR}/irrigation.build" "${PROJECT_DIR}/irrigation.onefile-build"

"${VENV}/bin/python" -m nuitka \
  --onefile \
  --standalone \
  --output-dir="${PROJECT_DIR}/dist" \
  --output-filename=irrigation \
  --remove-output \
  --assume-yes-for-downloads \
  "${PROJECT_DIR}/src/irrigation/__main__.py"

echo "Binary built at ${PROJECT_DIR}/dist/irrigation"

VERSION=$(sed -n 's/^version = "\(.*\)"/\1/p' "${PROJECT_DIR}/pyproject.toml")
PACKAGE_NAME="irrigation-deploy-${VERSION}"
PACKAGE_DIR="${PROJECT_DIR}/dist/${PACKAGE_NAME}"

rm -rf "${PACKAGE_DIR}" "${PROJECT_DIR}/dist/${PACKAGE_NAME}.zip"
mkdir -p "${PACKAGE_DIR}/dist" "${PACKAGE_DIR}/scripts" "${PACKAGE_DIR}/deploy"
"${VENV}/bin/python" "${PROJECT_DIR}/scripts/sync_flows_templates.py"
cp "${PROJECT_DIR}/dist/irrigation" "${PACKAGE_DIR}/dist/irrigation"
cp -r "${PROJECT_DIR}/deploy/data-defaults" "${PACKAGE_DIR}/data"
cp -r "${PROJECT_DIR}/deploy/systemd" "${PACKAGE_DIR}/deploy/systemd"
cp -r "${PROJECT_DIR}/node-red" "${PACKAGE_DIR}/node-red"
cp "${PROJECT_DIR}/scripts/install-raspberry.sh" "${PACKAGE_DIR}/scripts/install-raspberry.sh"
cp "${PROJECT_DIR}/deploy/package-readme.md" "${PACKAGE_DIR}/README.md"
chmod +x "${PACKAGE_DIR}/dist/irrigation" "${PACKAGE_DIR}/scripts/install-raspberry.sh"

(cd "${PROJECT_DIR}/dist" && zip -rq "${PACKAGE_NAME}.zip" "${PACKAGE_NAME}")
rm -rf "${PACKAGE_DIR}"

echo "Deployment package: ${PROJECT_DIR}/dist/${PACKAGE_NAME}.zip"
echo "Extract it on the Raspberry Pi and follow the README.md inside."
