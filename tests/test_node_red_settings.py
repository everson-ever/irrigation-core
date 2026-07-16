from pathlib import Path

SETTINGS_PATH = Path(__file__).resolve().parents[1] / "node-red" / "settings.js"


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

    assert '["auth", "login", `${username},${password}`]' in settings
    assert "output.authenticated === true" in settings
    assert "middleware: dashboardAuthMiddleware" in settings
