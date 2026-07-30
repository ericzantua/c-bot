// Vercel Edge Middleware — cookie-session gate for the whole app.
//
// Gates every request (static PWA + /api/*). Unauthenticated navigations go to a
// branded /login page; the form POSTs to /api/login, which the FastAPI backend
// verifies (accounts live in Supabase, editable in Settings) and answers with a
// signed, HttpOnly session cookie. This middleware only VERIFIES that cookie
// (HMAC-SHA256 with AUTH_SECRET) — it never sees passwords. The admin flag is
// carried in the (signature-verified) cookie, so admin-only APIs are gated here
// with no database lookup.
//
// Config (Vercel env var): AUTH_SECRET — must match the backend's AUTH_SECRET.
// Fail-closed: if AUTH_SECRET is unset, every request gets 503.

export const config = {
  matcher: ["/((?!_vercel/).*)"],
};

const COOKIE = "cbot_session";
const enc = new TextEncoder();

// ---- signed-cookie verification (HMAC-SHA256 via Web Crypto) ----
function b64urlToStr(s) {
  return atob(s.replace(/-/g, "+").replace(/_/g, "/"));
}
function b64urlToBytes(s) {
  const bin = b64urlToStr(s);
  const arr = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
  return arr;
}
function b64url(bytes) {
  const arr = new Uint8Array(bytes);
  let bin = "";
  for (let i = 0; i < arr.length; i++) bin += String.fromCharCode(arr[i]);
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
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
async function verifySession(token) {
  if (!token || token.indexOf(".") < 0) return null;
  const [payloadB64, sigB64] = token.split(".");
  let ok = false;
  try {
    const sig = await crypto.subtle.sign("HMAC", await hmacKey(), enc.encode(payloadB64));
    ok = b64url(sig) === sigB64;
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
  return payload; // { u, admin, exp }
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
function clearCookie() {
  return `${COOKIE}=; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=0`;
}

function jsonResponse(obj, status) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "content-type": "application/json", "Cache-Control": "no-store" },
  });
}

// ---- login page ----
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
<form class="card" method="POST" action="/api/login" autocomplete="on">
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

// ---- request handler ----
export default async function middleware(request) {
  const url = new URL(request.url);
  const path = url.pathname;

  if (!process.env.AUTH_SECRET) {
    return new Response("Auth not configured.", { status: 503, headers: { "Cache-Control": "no-store" } });
  }

  // Login page (reachable without a session).
  if (path === "/login") {
    if (await verifySession(getCookie(request, COOKIE))) {
      return new Response(null, { status: 303, headers: { Location: "/", "Cache-Control": "no-store" } });
    }
    const err = url.searchParams.get("error") ? "Invalid username or password." : "";
    return new Response(loginPage(err), { status: 200, headers: HTML_HEADERS });
  }

  // Logout: clear the cookie.
  if (path === "/logout") {
    return new Response(null, {
      status: 303,
      headers: { Location: "/login", "Set-Cookie": clearCookie(), "Cache-Control": "no-store" },
    });
  }

  // Let the login POST reach the backend unauthenticated (it sets the cookie).
  if (path === "/api/login") return;

  // Everything else needs a valid session.
  const payload = await verifySession(getCookie(request, COOKIE));
  if (!payload) {
    if (path.startsWith("/api/")) return jsonResponse({ detail: "Not authenticated" }, 401);
    return new Response(null, { status: 303, headers: { Location: "/login", "Cache-Control": "no-store" } });
  }

  const admin = !!payload.admin;

  // Identity probe for the SPA (cookie is HttpOnly, so JS can't read it).
  if (path === "/api/me") return jsonResponse({ user: payload.u, admin }, 200);

  // Admin-only APIs: user management, product management, ingestion, settings, KB.
  if (!admin && /^\/api\/(users|settings|products|index|knowledge)/.test(path)) {
    return jsonResponse({ detail: "Admin access required." }, 403);
  }

  return; // authenticated → continue
}
