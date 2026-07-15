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
    create_success = nodes["a9c1b3d4.e5f607"]
    create_error = nodes["a74e60b8.3d5b4"]
    navigate = nodes["d98e5f28.7a7c9"]

    assert "create_state.submitting = true" in create_template
    assert "Cadastrando agendamento..." in create_template
    assert "schedule_create_error" in create_template
    assert "create_state.submitting = false" in create_template
    assert "create_form.weekdays" in create_template
    assert "Todos os dias" in create_template
    assert "hasSelectedWeekday(create_form.weekdays)" in create_template
    assert "weekdays: scope.normalizeWeekdays(scope.create_form.weekdays)" in (
        create_template
    )
    assert "selectedWeekdays" in nodes["38e56a9f.2ca156"]["func"]
    assert (
        "`${time},${duration_minutes},${section},${selectedWeekdays}`"
        in nodes["38e56a9f.2ca156"]["func"]
    )
    assert 'replace(/^Error:\\s*/, "")' in create_error["func"]
    assert "msg.payload = String(msg.payload)" in create_error["func"]
    assert create_exec["wires"][0] == ["a9c1b3d4.e5f607"]
    assert "if (!output)" in create_success["func"]
    assert create_success["wires"] == [["7c602e02.7e8c7", "d98e5f28.7a7c9"]]
    assert create_error["wires"] == [[nodes["681694c2.ce0b1c"]["id"]]]
    assert '{ tab: "Agendamentos" }' in navigate["func"]


def test_schedule_edit_has_prefill_exclusive_mode_loading_and_error_handling():
    nodes = load_nodes()

    schedule_template = nodes["25072c26.808454"]["format"]
    update_exec = nodes["46dd0feb.e4f05"]
    update_formatter = nodes["c86fb12c.66d1e"]
    update_success = nodes["b8d2c4e6.f70123"]
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
    assert (
        "scope.schedule_form.weekdays = scope.normalizeWeekdays(schedule.weekdays)"
        in (schedule_template)
    )
    assert "scope.schedule_form.enabled = scope.isScheduleEnabled(schedule)" in (
        schedule_template
    )
    assert 'name="enabled"' in schedule_template
    assert 'ng-model="schedule_form.enabled"' in schedule_template
    assert 'ng-change="send({payload:toggleEnabled(schedule_form)})"' in (
        schedule_template
    )
    assert "scope.toggleEnabled = function(schedule)" in schedule_template
    assert 'ui_action: "toggle_enabled"' in schedule_template
    assert "enabled: schedule.enabled ? 1 : 0" in schedule_template
    assert "hasSelectedWeekday(schedule_form.weekdays)" in schedule_template
    assert "weekdays: scope.normalizeWeekdays(schedule.weekdays)" in schedule_template
    assert "selectedWeekdays" in update_formatter["func"]
    assert (
        "`${id},${time},${duration_minutes},${valve_pin},${selectedWeekdays}`"
        in update_formatter["func"]
    )
    assert "time: scope.formatEditTime(schedule.time)" in schedule_template
    assert "!editing_state.editing && schedules.length > 0" in schedule_template
    assert "!editing_state.editing && schedules.length === 0" in schedule_template
    assert 'editing_state.submitting">Salvando alterações...' in schedule_template
    assert "scope.editing_state.submitting = true" in schedule_template
    assert "schedule_update_error" in schedule_template
    assert "scope.editing_state.submitting = false" in schedule_template
    assert 'replace(/^Error:\\s*/, "")' in update_error["func"]
    assert "msg.payload = String(msg.payload)" in update_error["func"]
    assert update_exec["wires"][0] == ["b8d2c4e6.f70123"]
    assert "if (!output)" in update_success["func"]
    assert update_success["wires"] == [["7c602e02.7e8c7", "d98e5f28.7a7c9"]]
    assert update_error["wires"] == [[nodes["25072c26.808454"]["id"]]]


def test_schedule_enabled_toggle_has_flow_wiring_and_error_feedback():
    nodes = load_nodes()

    schedule_template = nodes["25072c26.808454"]["format"]
    action_router = nodes["d4f14a77.92f3b1"]
    enabled_formatter = nodes["e7a2d5c1.4b8f9a"]
    enabled_exec = nodes["f3c91a2b.6d4e8f"]
    enabled_success = nodes["a4d7e9c2.18b6f3"]
    enabled_error = nodes["d2b6f7a8.9e1c4d"]

    assert "<th>Agendamento</th>" in schedule_template
    assert 'data-label="Agendamento"' in schedule_template
    assert "scope.isScheduleEnabled = function(schedule)" in schedule_template
    assert 'ng-if="isScheduleEnabled(schedule)">Ativo' in schedule_template
    assert 'ng-if="!isScheduleEnabled(schedule)">Inativo' in schedule_template
    assert 'msg.topic === "schedule_enabled"' in schedule_template
    assert "scope.applyEnabledFeedback(msg.payload)" in schedule_template
    assert "scope.schedules[i].enabled = enabled ? 1 : 0" in schedule_template
    assert "scope.editing_state.enabled_submitting = true" in schedule_template
    assert "Atualizando liga/desliga..." in schedule_template
    assert 'msg.topic === "schedule_enabled_error"' in schedule_template

    assert action_router["outputs"] == 4
    assert 'payload.ui_action === "toggle_enabled"' in action_router["func"]
    assert "msg.payload = { id: payload.id, enabled: payload.enabled }" in (
        action_router["func"]
    )
    assert action_router["wires"][3] == ["e7a2d5c1.4b8f9a"]

    assert "const { id, enabled } = msg.payload || {}" in enabled_formatter["func"]
    assert "`${id},${value}`" in enabled_formatter["func"]
    assert enabled_formatter["wires"] == [["f3c91a2b.6d4e8f"]]
    assert enabled_exec["command"] == "/opt/irrigation/bin/irrigation schedule enabled"
    assert enabled_exec["addpay"] is True
    assert enabled_exec["wires"][0] == ["a4d7e9c2.18b6f3"]
    assert enabled_exec["wires"][1] == ["d2b6f7a8.9e1c4d"]
    assert 'msg.topic = "schedule_enabled"' in enabled_success["func"]
    assert "JSON.parse(output)" in enabled_success["func"]
    assert enabled_success["wires"] == [["25072c26.808454", "7c602e02.7e8c7"]]
    assert 'msg.topic = "schedule_enabled_error"' in enabled_error["func"]
    assert 'replace(/^Error:\\s*/, "")' in enabled_error["func"]
    assert enabled_error["wires"] == [["25072c26.808454"]]


def test_schedule_forms_display_cli_validation_errors():
    nodes = load_nodes()

    create_template = nodes["681694c2.ce0b1c"]["format"]
    edit_template = nodes["25072c26.808454"]["format"]
    create_error = nodes["a74e60b8.3d5b4"]
    update_error = nodes["e95d01ea.97e4c"]

    assert 'ng-if="create_error"' in create_template
    assert "{{ create_error }}" in create_template
    assert 'msg.topic = "schedule_create_error"' in create_error["func"]
    assert 'replace(/^Error:\\s*/, "")' in create_error["func"]
    assert 'ng-if="schedule_error"' in edit_template
    assert "{{ schedule_error }}" in edit_template
    assert 'msg.topic = "schedule_update_error"' in update_error["func"]
    assert 'replace(/^Error:\\s*/, "")' in update_error["func"]


def test_schedule_list_uses_cli_runtime_status_output():
    nodes = load_nodes()

    schedule_loader = nodes["7c602e02.7e8c7"]
    formatter = nodes["afe05d94.376be"]

    assert schedule_loader["type"] == "exec"
    assert schedule_loader["command"] == "/opt/irrigation/bin/irrigation schedule list"
    assert schedule_loader["wires"][0] == ["afe05d94.376be"]
    assert "JSON.parse(text)" in formatter["func"]
    assert 'msg.topic = "schedules"' in formatter["func"]


def test_schedule_list_displays_weekdays():
    nodes = load_nodes()

    schedule_template = nodes["25072c26.808454"]["format"]

    assert "<th>Dias</th>" in schedule_template
    assert 'data-label="Dias">{{ formatWeekdays(schedule.weekdays) }}' in (
        schedule_template
    )
    assert 'return "Todos os dias"' in schedule_template
    assert '{ id: "mon", label: "Seg" }' in schedule_template


def test_schedule_table_uses_schedule_status_for_badges_and_actions():
    nodes = load_nodes()

    schedule_template = nodes["25072c26.808454"]["format"]
    section_status = schedule_template.split(
        "scope.sectionStatus = function(schedule) {", 1
    )[1].split("  scope.sendId = function(id)", 1)[0]

    assert "schedule.status" in section_status
    assert "schedule.valve_status" not in section_status
    assert 'ng-if="sectionStatus(schedule) === 0">Desligada' in schedule_template
    assert 'ng-if="sectionStatus(schedule) === 1">Ligada' in schedule_template
    assert 'ng-if="sectionStatus(schedule) === 1"' in schedule_template
    assert 'ng-if="sectionStatus(schedule) !== 1"' in schedule_template


def test_manual_schedule_action_updates_clicked_schedule_row_immediately():
    nodes = load_nodes()

    schedule_template = nodes["25072c26.808454"]["format"]
    action_router = nodes["d4f14a77.92f3b1"]

    assert "manual_feedback" in schedule_template
    assert "scope.applyManualFeedback(msg.payload)" in schedule_template
    assert "scope.manual_pending = scope.manual_pending || {}" in schedule_template
    assert "scope.manual_pending_timers = scope.manual_pending_timers || {}" in (
        schedule_template
    )
    assert "scope.manual_pending_timeout_ms = 15000" in schedule_template
    assert 'ng-disabled="manual_pending[schedule.id]"' in schedule_template
    assert '"Ligando..." : "Ligar agora"' in schedule_template
    assert '"Desligando..." : "Desligar agora"' in schedule_template
    assert 'scope.startManualPending(schedule, "on")' in schedule_template
    assert 'scope.startManualPending(schedule, "off")' in schedule_template
    assert "setTimeout(function()" in schedule_template
    assert "scope.clearManualPending(payload.id)" in schedule_template
    assert "String(scope.schedules[i].id) === String(payload.id)" in (schedule_template)
    assert 'scope.schedules[i].status = payload.action === "on" ? 1 : 0' in (
        schedule_template
    )
    assert 'action: "on", id: schedule.id' in schedule_template
    assert 'action: "off", id: schedule.id' in schedule_template
    assert 'msg.topic = "manual_feedback"' in action_router["func"]
    assert "id: payload.id" in action_router["func"]
    assert "id } = msg.payload" in nodes["5b92c8ad.78d3e8"]["func"]
    assert action_router["wires"][2] == [
        "5b92c8ad.78d3e8",
        "25072c26.808454",
    ]
