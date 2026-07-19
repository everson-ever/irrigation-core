import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
INSTALLER_PATH = PROJECT_ROOT / "scripts" / "install-raspberry.sh"
SERVICE_TEMPLATE_PATH = (
    PROJECT_ROOT / "deploy" / "systemd" / "irrigation.service.template"
)


def run_data_initializer(data_dir, default_data_dir):
    return subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; initialize_data_directory "$2" "$3"',
            "installer-test",
            str(INSTALLER_PATH),
            str(data_dir),
            str(default_data_dir),
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def run_node_runtime_installer(command, *arguments):
    return subprocess.run(
        [
            "bash",
            "-c",
            command,
            "installer-test",
            str(INSTALLER_PATH),
            *[str(argument) for argument in arguments],
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def test_installer_preserves_existing_node_runtime(tmp_path):
    apt_log = tmp_path / "apt.log"

    result = run_node_runtime_installer(
        """
        source "$1"
        apt_log=$2
        node() { printf 'v20.0.0'; }
        npm() { printf '10.0.0'; }
        apt-get() { printf 'unexpected apt call' >> "${apt_log}"; return 1; }
        ensure_node_runtime
        """,
        apt_log,
    )

    assert result.returncode == 0
    assert "are already installed" in result.stdout
    assert not apt_log.exists()


def test_installer_uses_apt_when_node_runtime_is_missing(tmp_path):
    apt_log = tmp_path / "apt.log"
    empty_path = tmp_path / "empty-bin"
    empty_path.mkdir()

    result = run_node_runtime_installer(
        """
        source "$1"
        apt_log=$2
        PATH=$3
        apt-get() {
          printf '%s\n' "$*" >> "${apt_log}"
          if [[ $1 == install ]]; then
            node() { printf 'v20.0.0'; }
            npm() { printf '10.0.0'; }
          fi
        }
        ensure_node_runtime
        """,
        apt_log,
        empty_path,
    )

    assert result.returncode == 0
    assert apt_log.read_text().splitlines() == ["update", "install -y nodejs npm"]
    assert "Installing Node.js and npm" in result.stdout


def test_installer_skips_node_red_install_when_service_present(tmp_path):
    apt_log = tmp_path / "apt.log"

    result = run_node_runtime_installer(
        """
        source "$1"
        apt_log=$2
        systemctl() { [[ "$1" == list-unit-files ]]; }
        curl() { printf 'unexpected curl call' >> "${apt_log}"; return 1; }
        bash() { printf 'unexpected bash call' >> "${apt_log}"; return 1; }
        apt-get() { printf 'unexpected apt call' >> "${apt_log}"; return 1; }
        ensure_node_red "pi"
        """,
        apt_log,
    )

    assert result.returncode == 0
    assert "already present" in result.stdout
    assert not apt_log.exists()


def test_installer_installs_node_red_when_service_is_missing(tmp_path):
    marker = tmp_path / "node-red-installed"
    install_log = tmp_path / "install.log"

    result = run_node_runtime_installer(
        """
        source "$1"
        marker=$2
        install_log=$3
        systemctl() { [[ "$1" == list-unit-files && -f "${marker}" ]]; }
        curl() { :; }
        bash() { printf '%s\n' "$*" >> "${install_log}"; touch "${marker}"; }
        ensure_node_red "pi"
        """,
        marker,
        install_log,
    )

    assert result.returncode == 0
    assert "Installing Node-RED" in result.stdout
    assert "Node-RED installed." in result.stdout
    assert "--nodered-user=pi" in install_log.read_text()


def test_installer_deploys_node_red_flow_overwriting_existing_one(tmp_path):
    home_dir = tmp_path / "home" / "pi"
    user_dir = home_dir / ".node-red"
    user_dir.mkdir(parents=True)
    (user_dir / "flows.json").write_text('{"old": true}')

    project_dir = tmp_path / "project"
    (project_dir / "node-red").mkdir(parents=True)
    (project_dir / "node-red" / "flows.json").write_text('{"new": true}')

    chown_log = tmp_path / "chown.log"

    result = run_node_runtime_installer(
        """
        source "$1"
        home_dir=$2
        project_dir=$3
        chown_log=$4
        getent() { printf 'pi:x:1000:1000::%s:/bin/bash' "${home_dir}"; }
        chown() { printf '%s\n' "$*" >> "${chown_log}"; }
        deploy_node_red_flow "pi" "${project_dir}"
        """,
        home_dir,
        project_dir,
        chown_log,
    )

    assert result.returncode == 0
    assert (user_dir / "flows.json").read_text() == '{"new": true}'
    assert "pi:pi" in chown_log.read_text()
    assert "overwriting any previous flow" in result.stdout


def test_installer_reports_when_flow_deploy_user_home_is_unresolved(tmp_path):
    project_dir = tmp_path / "project"
    (project_dir / "node-red").mkdir(parents=True)
    (project_dir / "node-red" / "flows.json").write_text('{"new": true}')

    result = run_node_runtime_installer(
        """
        source "$1"
        project_dir=$2
        getent() { return 2; }
        deploy_node_red_flow "ghost" "${project_dir}"
        """,
        project_dir,
    )

    assert result.returncode != 0
    assert "Could not resolve a home directory" in result.stderr


def test_installer_initializes_missing_data_directory(tmp_path):
    default_data_dir = tmp_path / "deploy" / "data-defaults"
    default_data_dir.mkdir(parents=True)
    (default_data_dir / "irrigation.db").write_text("default database")
    (default_data_dir / "history_search_results.json").write_text("[]")
    data_dir = tmp_path / "data"

    result = run_data_initializer(data_dir, default_data_dir)

    assert result.returncode == 0
    assert (data_dir / "irrigation.db").read_text() == "default database"
    assert (data_dir / "history_search_results.json").read_text() == "[]"
    assert "Initialized" in result.stdout


def test_installer_preserves_existing_data_directory(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "history.json").write_text('{"id": "legacy"}\n')
    default_data_dir = tmp_path / "deploy" / "data-defaults"
    default_data_dir.mkdir(parents=True)
    (default_data_dir / "irrigation.db").write_text("default database")

    result = run_data_initializer(data_dir, default_data_dir)

    assert result.returncode == 0
    assert (data_dir / "history.json").read_text() == '{"id": "legacy"}\n'
    assert not (data_dir / "irrigation.db").exists()


def test_installer_reports_missing_data_and_defaults(tmp_path):
    result = run_data_initializer(
        tmp_path / "data",
        tmp_path / "deploy" / "data-defaults",
    )

    assert result.returncode != 0
    assert "Data directory not found" in result.stderr
    assert "Default data not found" in result.stderr


def test_systemd_working_directory_is_an_unquoted_absolute_path_placeholder():
    template = SERVICE_TEMPLATE_PATH.read_text()

    assert "WorkingDirectory=__PROJECT_DIR__" in template.splitlines()
    assert 'WorkingDirectory="' not in template
