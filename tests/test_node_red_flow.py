import json
from pathlib import Path

FLOW_PATH = Path(__file__).resolve().parents[1] / "node-red" / "flows.json"


def load_nodes():
    return {node["id"]: node for node in json.loads(FLOW_PATH.read_text())}


def test_dashboard_menu_order_and_history_label():
    nodes = load_nodes()

    tabs = [
        nodes["59749dbb.d7d844"],
        nodes["e1bc117a.c215c"],
        nodes["56e52954.09e758"],
    ]

    assert [(tab["name"], tab["order"]) for tab in tabs] == [
        ("Agendamentos", 1),
        ("Novo Agendamento", 2),
        ("Histórico", 3),
    ]


def test_schedule_create_has_loading_error_and_success_navigation():
    nodes = load_nodes()

    create_template = nodes["681694c2.ce0b1c"]["format"]
    create_exec = nodes["1a73e6be.d28d09"]
    create_error = nodes["a74e60b8.3d5b4"]
    navigate = nodes["d98e5f28.7a7c9"]

    assert "create_state.submitting = true" in create_template
    assert "Cadastrando agendamento..." in create_template
    assert "schedule_create_error" in create_template
    assert "create_state.submitting = false" in create_template
    assert "d98e5f28.7a7c9" in create_exec["wires"][0]
    assert create_error["wires"] == [[nodes["681694c2.ce0b1c"]["id"]]]
    assert '{ tab: "Agendamentos" }' in navigate["func"]


def test_schedule_edit_has_prefill_exclusive_mode_loading_and_error_handling():
    nodes = load_nodes()

    schedule_template = nodes["25072c26.808454"]["format"]
    update_exec = nodes["46dd0feb.e4f05"]
    update_error = nodes["e95d01ea.97e4c"]

    assert "scope.schedule_form.id = schedule.id" in schedule_template
    assert "scope.toEditTimeValue = function(value)" in schedule_template
    assert "scope.formatEditTime = function(value)" in schedule_template
    assert "scope.schedule_form.time = scope.toEditTimeValue(schedule.time)" in (
        schedule_template
    )
    assert (
        "scope.schedule_form.duration_minutes = parseInt(schedule.duration_minutes, 10)"
        in schedule_template
    )
    assert (
        "scope.schedule_form.valve_pin = parseInt(schedule.valve_pin, 10)"
        in schedule_template
    )
    assert "time: scope.formatEditTime(schedule.time)" in schedule_template
    assert "!editing_state.editing && schedules.length > 0" in schedule_template
    assert "!editing_state.editing && schedules.length === 0" in schedule_template
    assert 'editing_state.submitting">Salvando alterações...' in schedule_template
    assert "scope.editing_state.submitting = true" in schedule_template
    assert "schedule_update_error" in schedule_template
    assert "scope.editing_state.submitting = false" in schedule_template
    assert "d98e5f28.7a7c9" in update_exec["wires"][0]
    assert update_error["wires"] == [[nodes["25072c26.808454"]["id"]]]


def test_schedule_list_uses_cli_runtime_status_output():
    nodes = load_nodes()

    schedule_loader = nodes["7c602e02.7e8c7"]
    formatter = nodes["afe05d94.376be"]

    assert schedule_loader["type"] == "exec"
    assert schedule_loader["command"] == "/opt/irrigation/bin/irrigation schedule list"
    assert schedule_loader["wires"][0] == ["afe05d94.376be"]
    assert "JSON.parse(text)" in formatter["func"]
    assert 'msg.topic = "schedules"' in formatter["func"]


def test_schedule_table_uses_schedule_running_status_for_badges_and_actions():
    nodes = load_nodes()

    schedule_template = nodes["25072c26.808454"]["format"]
    section_status = schedule_template.split(
        "scope.sectionStatus = function(schedule) {", 1
    )[1].split("  scope.sendId = function(id)", 1)[0]

    assert "schedule.is_running" in section_status
    assert "scope.findValve(schedule)" not in section_status
    assert 'ng-if="sectionStatus(schedule) === 0">Desligada' in schedule_template
    assert 'ng-if="sectionStatus(schedule) === 1">Ligada' in schedule_template
    assert 'ng-if="sectionStatus(schedule) === 1"' in schedule_template
    assert 'ng-if="sectionStatus(schedule) !== 1"' in schedule_template
