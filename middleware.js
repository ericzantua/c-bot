// Vercel Edge Middleware — cookie-based login gate for the whole app.
//
// Gates every request (static PWA + /api/*). Unauthenticated visitors are sent
// to a branded /login page; a correct username+password sets a signed, HttpOnly
// session cookie that the middleware verifies on every subsequent request. This
// avoids the browser's native Basic-Auth prompt (which double-prompts and is
// flaky inside installed PWAs).
//
// Config (Vercel env vars, never in the repo):
//   AUTH_USERS   comma-separated "username:password" pairs, e.g. eric:secret,jane:pw2
//                (avoid ',' and ':' inside passwords — they're the delimiters)
//   AUTH_SECRET  random string used to HMAC-sign the session cookie
// Fail-closed: if either is unset, every request gets 503.

export const config = {
  // Gate every route except Vercel's internal analytics/insights beacons.
  matcher: ["/((?!_vercel/).*)"],
};

const COOKIE = "cbot_session";
const SESSION_DAYS = 30;
const enc = new TextEncoder();

// ---- credential store -------------------------------------------------------
function parseUsers() {
  const map = new Map();
  const raw = process.env.AUTH_USERS || process.env.BASIC_AUTH_USERS || "";
  for (const pair of raw.split(",")) {
    const s = pair.trim();
    if (!s) continue;
    const i = s.indexOf(":");
    if (i <= 0) continue;
    map.set(s.slice(0, i), s.slice(i + 1));
  }
  return map;
}

// Admins get the Products/Settings pages + the management APIs. Configure via the
// AUTH_ADMINS env var (comma-separated usernames); everyone else is a plain user.
function parseAdmins() {
  const set = new Set();
  for (const name of (process.env.AUTH_ADMINS || "").split(",")) {
    const s = name.trim();
    if (s) set.add(s);
  }
  return set;
}

function jsonResponse(obj, status) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "content-type": "application/json", "Cache-Control": "no-store" },
  });
}

// Constant-time string compare so a wrong password can't be timing-guessed.
function safeEqual(a, b) {
  if (typeof a !== "string" || typeof b !== "string") return false;
  const ba = enc.encode(a);
  const bb = enc.encode(b);
  if (ba.length !== bb.length) return false;
  let diff = 0;
  for (let i = 0; i < ba.length; i++) diff |= ba[i] ^ bb[i];
  return diff === 0;
}

// ---- signed session cookie (HMAC-SHA256 via Web Crypto) ---------------------
function b64url(bytes) {
  const arr = new Uint8Array(bytes);
  let bin = "";
  for (let i = 0; i < arr.length; i++) bin += String.fromCharCode(arr[i]);
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}
function b64urlToStr(s) {
  return atob(s.replace(/-/g, "+").replace(/_/g, "/"));
}
function b64urlToBytes(s) {
  const bin = b64urlToStr(s);
  const arr = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
  return arr;
}
function hmacKey() {
  return crypto.subtle.importKey(
    "raw",
    enc.encode(process.env.AUTH_SECRET || ""),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign", "verify"]
  );
}
async function signSession(username) {
  const exp = Date.now() + SESSION_DAYS * 24 * 60 * 60 * 1000;
  const payloadB64 = b64url(enc.encode(JSON.stringify({ u: username, exp })));
  const sig = await crypto.subtle.sign("HMAC", await hmacKey(), enc.encode(payloadB64));
  return `${payloadB64}.${b64url(sig)}`;
}
async function verifySession(token) {
  if (!token || token.indexOf(".") < 0) return null;
  const [payloadB64, sigB64] = token.split(".");
  let ok = false;
  try {
    ok = await crypto.subtle.verify("HMAC", await hmacKey(), b64urlToBytes(sigB64), enc.encode(payloadB64));
  } catch {
    return null;
  }
  if (!ok) return null;
  let payload;
  try {
    payload = JSON.parse(b64urlToStr(payloadB64));
  } catch {
    return null;
  }
  if (!payload || typeof payload.exp !== "number" || Date.now() > payload.exp) return null;
  return payload.u || null;
}

function getCookie(request, name) {
  const header = request.headers.get("cookie") || "";
  for (const part of header.split(";")) {
    const s = part.trim();
    const i = s.indexOf("=");
    if (i > 0 && s.slice(0, i) === name) return s.slice(i + 1);
  }
  return null;
}
function sessionCookie(token) {
  const maxAge = SESSION_DAYS * 24 * 60 * 60;
  return `${COOKIE}=${token}; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=${maxAge}`;
}
function clearCookie() {
  return `${COOKIE}=; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=0`;
}

// ---- login page -------------------------------------------------------------
const HTML_HEADERS = { "content-type": "text/html; charset=utf-8", "Cache-Control": "no-store" };

function loginPage(error) {
  const err = error ? `<p class="err">${error}</p>` : "";
  return `<!doctype html><html lang="en"><head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover"/>
<title>C-Bot — Sign in</title>
<style>
  :root{--red:#e32b2b;--dark:#b81f1f;--ink:#1f2733;--muted:#6b7688;--border:#e2e6ee;}
  *{box-sizing:border-box}
  body{margin:0;min-height:100dvh;display:flex;align-items:center;justify-content:center;
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
    background:#f4f6fb;color:var(--ink);padding:24px}
  .card{width:100%;max-width:360px;background:#fff;border:1px solid var(--border);
    border-radius:16px;padding:28px 24px;box-shadow:0 10px 30px rgba(20,30,50,.08)}
  .brand{font-size:30px;font-weight:800;color:var(--red);text-align:center;margin:0 0 4px}
  .tag{color:var(--muted);text-align:center;margin:0 0 20px;font-size:13px}
  label{display:block;font-size:12px;color:var(--muted);margin:12px 0 4px;font-weight:600}
  input{width:100%;border:1px solid var(--border);border-radius:10px;padding:12px;font-size:16px;font-family:inherit}
  input:focus{outline:none;border-color:var(--red)}
  button{width:100%;margin-top:18px;border:none;border-radius:10px;padding:13px;font-size:15px;
    font-weight:700;color:#fff;background:var(--red);cursor:pointer}
  button:active{background:var(--dark)}
  .err{background:#fdecea;color:#b42318;border-radius:10px;padding:10px 12px;font-size:13px;margin:14px 0 0}
</style></head><body>
<form class="card" method="POST" action="/login" autocomplete="on">
  <h1 class="brand">🛒 C-Bot</h1>
  <p class="tag">Sign in to continue</p>
  ${err}
  <label for="u">Username</label>
  <input id="u" name="username" autocapitalize="none" autocorrect="off" autofocus required/>
  <label for="p">Password</label>
  <input id="p" name="password" type="password" required/>
  <button type="submit">Sign in</button>
</form>
</body></html>`;
}

// ---- request handler --------------------------------------------------------
export default async function middleware(request) {
  const url = new URL(request.url);
  const path = url.pathname;
  const users = parseUsers();

  if (users.size === 0 || !process.env.AUTH_SECRET) {
    return new Response("Auth not configured.", { status: 503, headers: { "Cache-Control": "no-store" } });
  }

  // --- login route (reachable without a session) ---
  if (path === "/login") {
    if (request.method === "POST") {
      const form = await request.formData();
      const username = (form.get("username") || "").toString();
      const password = (form.get("password") || "").toString();
      const expected = users.get(username);
      if (expected !== undefined && safeEqual(password, expected)) {
        const token = await signSession(username);
        return new Response(null, {
          status: 303,
          headers: { Location: "/", "Set-Cookie": sessionCookie(token), "Cache-Control": "no-store" },
        });
      }
      return new Response(loginPage("Invalid username or password."), { status: 401, headers: HTML_HEADERS });
    }
    // GET: already signed in? skip the form.
    if (await verifySession(getCookie(request, COOKIE))) {
      return new Response(null, { status: 303, headers: { Location: "/", "Cache-Control": "no-store" } });
    }
    return new Response(loginPage(""), { status: 200, headers: HTML_HEADERS });
  }

  // --- logout ---
  if (path === "/logout") {
    return new Response(null, {
      status: 303,
      headers: { Location: "/login", "Set-Cookie": clearCookie(), "Cache-Control": "no-store" },
    });
  }

  // --- everything else requires a valid session ---
  const user = await verifySession(getCookie(request, COOKIE));
  if (!user) {
    if (path.startsWith("/api/")) return jsonResponse({ detail: "Not authenticated" }, 401);
    return new Response(null, { status: 303, headers: { Location: "/login", "Cache-Control": "no-store" } });
  }

  const admin = parseAdmins().has(user);

  // Identity probe for the SPA (the session cookie is HttpOnly, so JS can't read it).
  if (path === "/api/me") return jsonResponse({ user, admin }, 200);

  // Admin-only APIs: product management, ingestion, settings, knowledge base.
  // (Plain users keep /api/chat, /api/tts, /api/health, /api/me.)
  if (!admin && /^\/api\/(settings|products|index|knowledge)/.test(path)) {
    return jsonResponse({ detail: "Admin access required." }, 403);
  }

  return; // authenticated → continue
}
