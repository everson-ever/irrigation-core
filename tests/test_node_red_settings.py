from pathlib import Path

SETTINGS_PATH = Path(__file__).resolve().parents[1] / "node-red" / "settings.js"


def test_flow_file_name_is_fixed_instead_of_hostname_based():
    settings = SETTINGS_PATH.read_text()

    assert 'flowFile: "flows.json"' in settings


def test_dashboard_auth_uses_modern_login_form_instead_of_browser_prompt():
    settings = SETTINGS_PATH.read_text()

    assert "function renderLogin" in settings
    assert 'method="post" action="/ui/login"' in settings
    assert "Entrar no painel" in settings
    assert "WWW-Authenticate" not in settings
    assert "Basic realm" not in settings


def test_dashboard_auth_uses_http_only_session_cookie():
    settings = SETTINGS_PATH.read_text()

    assert "irrigation_session" in settings
    assert "HttpOnly; SameSite=Lax; Path=/ui" in settings
    assert "crypto.randomBytes(32)" in settings
    assert "sessions.add(token)" in settings
    assert "sessions.delete(token)" in settings


def test_dashboard_login_does_not_hang_when_express_already_parsed_the_body():
    settings = SETTINGS_PATH.read_text()

    assert "if (request.body)" in settings
    assert "formFromParsedBody(request.body)" in settings
    assert "if (request.readableEnded || request.complete)" in settings


def test_dashboard_auth_still_verifies_against_cli_credentials():
    settings = SETTINGS_PATH.read_text()

    assert '{ command: "auth", action: "login", username, password }' in settings
    assert "output.authenticated === true" in settings
    assert "middleware: dashboardAuthMiddleware" in settings


def test_cli_invocations_send_json_through_stdin_without_credentials_in_argv():
    settings = SETTINGS_PATH.read_text()

    assert 'execFile(\n    IRRIGATION_BINARY,\n    ["--stdin"]' in settings
    assert "child.stdin.end(input)" in settings
    assert "JSON.stringify(request)" in settings
    assert "function invokeIrrigationNode" in settings
    assert "functionGlobalContext" in settings
    assert "invokeIrrigationNode," in settings
    assert '["auth", "login"' not in settings
    assert "`${username},${password}`" not in settings
