#!/usr/bin/env bash
set -euo pipefail

ensure_node_runtime() {
  if command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1; then
    echo "Node.js $(node --version) and npm $(npm --version) are already installed."
    return 0
  fi

  if ! command -v apt-get >/dev/null 2>&1; then
    echo "Node.js and npm are required, but apt-get is not available." >&2
    return 1
  fi

  echo "Installing Node.js and npm..."
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y nodejs npm

  if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
    echo "Node.js or npm is still unavailable after package installation." >&2
    return 1
  fi

  echo "Installed Node.js $(node --version) and npm $(npm --version)."
}

initialize_data_directory() {
  local data_dir=$1
  local default_data_dir=$2

  if [[ -d "${data_dir}" ]]; then
    return 0
  fi

  if [[ -e "${data_dir}" ]]; then
    echo "Data path exists but is not a directory: ${data_dir}." >&2
    return 1
  fi

  if [[ ! -d "${default_data_dir}" ]]; then
    echo "Data directory not found at ${data_dir}." >&2
    echo "Default data not found at ${default_data_dir}." >&2
    return 1
  fi

  cp -a "${default_data_dir}" "${data_dir}"
  echo "Initialized ${data_dir} from deployment defaults."
}

main() {
  if [[ ${EUID} -ne 0 ]]; then
    echo "Run with sudo: sudo ./scripts/install-raspberry.sh" >&2
    exit 1
  fi

  local project_dir
  local run_user
  local binary_src
  local binary_dir=/opt/irrigation/bin
  local binary_dst
  local data_dir
  local default_data_dir

  project_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
  run_user=${SUDO_USER:-$(stat -c '%U' "${project_dir}")}
  binary_src="${project_dir}/dist/irrigation"
  binary_dst="${binary_dir}/irrigation"
  data_dir="${project_dir}/data"
  default_data_dir="${project_dir}/deploy/data-defaults"

  if [[ ! -x "${binary_src}" ]]; then
    echo "Compiled binary not found at ${binary_src}." >&2
    echo "Run scripts/build-binary.sh first (or copy a binary built elsewhere)." >&2
    exit 1
  fi

  initialize_data_directory "${data_dir}" "${default_data_dir}"
  ensure_node_runtime

  usermod -aG gpio "${run_user}"

  mkdir -p "${binary_dir}"
  install -o root -g root -m 755 "${binary_src}" "${binary_dst}"

  sed \
    -e "s|__PROJECT_DIR__|${project_dir}|g" \
    -e "s|__RUN_USER__|${run_user}|g" \
    -e "s|__BINARY__|${binary_dst}|g" \
    "${project_dir}/deploy/systemd/irrigation.service.template" \
    > /etc/systemd/system/irrigation.service

  if systemctl list-unit-files nodered.service >/dev/null 2>&1; then
    mkdir -p /etc/systemd/system/nodered.service.d
    sed \
      -e "s|__PROJECT_DIR__|${project_dir}|g" \
      -e "s|__BINARY_DIR__|${binary_dir}|g" \
      "${project_dir}/deploy/systemd/nodered-override.conf.template" \
      > /etc/systemd/system/nodered.service.d/irrigation.conf
  fi

  chown -R "${run_user}:${run_user}" "${data_dir}"
  systemctl daemon-reload
  systemctl enable --now irrigation.service

  echo "Installation complete. Operational data is stored in data/irrigation.db."
  echo "Legacy JSON data is imported automatically when the database does not exist."
  echo "Import node-red/flows.json using the Node-RED editor."
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
