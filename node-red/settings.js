const { execFile } = require("child_process");
const crypto = require("crypto");

const IRRIGATION_BINARY =
  process.env.IRRIGATION_BINARY || "/opt/irrigation/bin/irrigation";
const SESSION_COOKIE = "irrigation_session";
const SESSION_MAX_AGE_SECONDS = 8 * 60 * 60;
const sessions = new Set();

function verifyCredentials(username, password) {
  return new Promise((resolve) => {
    execFile(
      IRRIGATION_BINARY,
      ["auth", "login", `${username},${password}`],
      { timeout: 10000 },
      (error, stdout) => {
        if (error) {
          resolve(false);
          return;
        }
        try {
          const output = JSON.parse(String(stdout || "{}"));
          resolve(output.authenticated === true);
        } catch (_parseError) {
          resolve(false);
        }
      },
    );
  });
}

function dashboardAuthMiddleware(request, response, next) {
  if (isLoginRequest(request)) {
    handleLogin(request, response);
    return;
  }
  if (isLogoutRequest(request)) {
    logout(request, response);
    return;
  }
  if (hasValidSession(request)) {
    next();
    return;
  }
  renderLogin(response);
}

function handleLogin(request, response) {
  readFormBody(request)
    .then((form) => {
      const username = String(form.get("username") || "");
      const password = String(form.get("password") || "");
      return verifyCredentials(username, password);
    })
    .then((valid) => {
      if (!valid) {
        renderLogin(response, "Usuário ou senha inválidos.", 401);
        return;
      }
      const token = crypto.randomBytes(32).toString("hex");
      sessions.add(token);
      response.setHeader(
        "Set-Cookie",
        `${SESSION_COOKIE}=${token}; HttpOnly; SameSite=Lax; Path=/ui; Max-Age=${SESSION_MAX_AGE_SECONDS}`,
      );
      response.redirect("/ui");
    })
    .catch(() => renderLogin(response, "Não foi possível validar o login.", 500));
}

function logout(request, response) {
  const token = sessionToken(request);
  if (token) {
    sessions.delete(token);
  }
  response.setHeader(
    "Set-Cookie",
    `${SESSION_COOKIE}=; HttpOnly; SameSite=Lax; Path=/ui; Max-Age=0`,
  );
  response.redirect("/ui");
}

function hasValidSession(request) {
  const token = sessionToken(request);
  return Boolean(token && sessions.has(token));
}

function sessionToken(request) {
  const cookies = String(request.headers.cookie || "").split(";");
  for (const cookie of cookies) {
    const [name, ...valueParts] = cookie.trim().split("=");
    if (name === SESSION_COOKIE) {
      return valueParts.join("=");
    }
  }
  return "";
}

function isLoginRequest(request) {
  return request.method === "POST" && requestPath(request).endsWith("/ui/login");
}

function isLogoutRequest(request) {
  return requestPath(request).endsWith("/ui/logout");
}

function requestPath(request) {
  return new URL(request.originalUrl || request.url || "/", "http://localhost")
    .pathname;
}

function readFormBody(request) {
  if (request.body) {
    return Promise.resolve(formFromParsedBody(request.body));
  }
  if (request.readableEnded || request.complete) {
    return Promise.resolve(new URLSearchParams(""));
  }
  return new Promise((resolve, reject) => {
    let body = "";
    let settled = false;
    function finish(value) {
      if (settled) {
        return;
      }
      settled = true;
      resolve(value);
    }
    function fail(error) {
      if (settled) {
        return;
      }
      settled = true;
      reject(error);
    }
    request.on("data", (chunk) => {
      body += chunk;
      if (body.length > 4096) {
        fail(new Error("login form too large"));
      }
    });
    request.on("end", () => finish(new URLSearchParams(body)));
    request.on("error", fail);
  });
}

function formFromParsedBody(body) {
  const form = new URLSearchParams("");
  if (typeof body === "string") {
    return new URLSearchParams(body);
  }
  if (typeof body !== "object") {
    return form;
  }
  for (const [key, value] of Object.entries(body)) {
    form.set(key, String(value));
  }
  return form;
}

function renderLogin(response, errorMessage = "", statusCode = 200) {
  response.setHeader("Cache-Control", "no-store");
  response.status(statusCode).send(`<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Irriga • Login</title>
  <style>
    :root {
      --green: #11877d;
      --green-dark: #0d756c;
      --ink: #071a18;
      --muted: #6c7476;
      --line: #dfe8e6;
      --danger: #c92f2f;
      --danger-bg: #fff0f0;
    }
    * { box-sizing: border-box; }
    body {
      min-height: 100vh;
      margin: 0;
      display: grid;
      place-items: center;
      padding: 28px;
      background:
        radial-gradient(circle at 12% 12%, rgba(17, 135, 125, .16), transparent 28rem),
        linear-gradient(135deg, #edf6f3, #f7faf9 48%, #e8f1ef);
      color: var(--ink);
      font-family: Inter, Roboto, Arial, sans-serif;
    }
    .login-card {
      width: min(100%, 430px);
      border: 1px solid rgba(17, 135, 125, .16);
      border-radius: 24px;
      padding: 34px;
      background: rgba(255, 255, 255, .9);
      box-shadow: 0 24px 70px rgba(7, 26, 24, .12);
      backdrop-filter: blur(14px);
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 12px;
      margin-bottom: 28px;
      font-size: 18px;
      font-weight: 900;
    }
    .brand-mark {
      display: grid;
      width: 42px;
      height: 42px;
      place-items: center;
      border-radius: 14px;
      background: var(--green);
      color: #fff;
      box-shadow: 0 12px 28px rgba(17, 135, 125, .26);
    }
    .brand-mark svg { width: 23px; height: 23px; }
    .eyebrow {
      margin: 0 0 8px;
      color: var(--green);
      font-size: 12px;
      font-weight: 900;
      letter-spacing: .1em;
      text-transform: uppercase;
    }
    h1 {
      margin: 0;
      font-size: 30px;
      line-height: 1.05;
    }
    .help {
      margin: 10px 0 26px;
      color: var(--muted);
      font-size: 14px;
      line-height: 1.5;
    }
    form {
      display: grid;
      gap: 14px;
    }
    label {
      display: grid;
      gap: 7px;
      color: #263432;
      font-size: 12px;
      font-weight: 850;
    }
    input {
      width: 100%;
      height: 46px;
      border: 1px solid var(--line);
      border-radius: 13px;
      padding: 0 14px;
      outline: 0;
      background: #fff;
      color: var(--ink);
      font-size: 15px;
    }
    input:focus {
      border-color: var(--green);
      box-shadow: 0 0 0 4px rgba(17, 135, 125, .11);
    }
    button {
      height: 46px;
      border: 0;
      border-radius: 13px;
      margin-top: 6px;
      background: var(--green);
      color: #fff;
      cursor: pointer;
      font: inherit;
      font-weight: 900;
      box-shadow: 0 12px 26px rgba(17, 135, 125, .22);
    }
    button:hover { background: var(--green-dark); }
    .error {
      margin: 0 0 16px;
      border: 1px solid #ffd1d1;
      border-radius: 13px;
      padding: 12px 14px;
      background: var(--danger-bg);
      color: var(--danger);
      font-size: 13px;
      font-weight: 800;
    }
  </style>
</head>
<body>
  <main class="login-card">
    <div class="brand">
      <span class="brand-mark">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" aria-hidden="true"><path d="M12 3s5 6.1 5 11a5 5 0 0 1-10 0c0-4.9 5-11 5-11Z"/></svg>
      </span>
      <span>Irriga</span>
    </div>
    <p class="eyebrow">Acesso seguro</p>
    <h1>Entrar no painel</h1>
    <p class="help">Informe as credenciais para visualizar dados ou acionar a irrigação.</p>
    ${errorMessage ? `<p class="error">${escapeHtml(errorMessage)}</p>` : ""}
    <form method="post" action="/ui/login">
      <label>
        Usuário
        <input name="username" autocomplete="username" value="admin" required autofocus>
      </label>
      <label>
        Senha
        <input name="password" type="password" autocomplete="current-password" required>
      </label>
      <button type="submit">Entrar</button>
    </form>
  </main>
</body>
</html>`);
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

module.exports = {
  adminAuth: {
    type: "credentials",
    users(username) {
      if (username === "admin") {
        return Promise.resolve({ username: "admin", permissions: "*" });
      }
      return Promise.resolve(null);
    },
    authenticate(username, password) {
      return verifyCredentials(username, password).then((valid) => {
        if (valid) {
          return { username: "admin", permissions: "*" };
        }
        return null;
      });
    },
    default() {
      return Promise.resolve(null);
    },
  },
  ui: {
    path: "ui",
    middleware: dashboardAuthMiddleware,
  },
};
