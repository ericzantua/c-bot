// Vercel Edge Middleware — HTTP Basic Auth gate for the whole app.
//
// Runs in front of every request (the static PWA *and* /api/*), so nothing is
// reachable without valid credentials. Credentials come from the
// BASIC_AUTH_USERS env var: a comma-separated list of "username:password" pairs,
//   e.g.  alice:s3cret,bob:hunter2
// Set it in the Vercel dashboard (Settings → Environment Variables) so the
// passwords never live in the repo, then redeploy for the change to take effect.
//
// Fail-closed: if BASIC_AUTH_USERS is unset/empty, every request is denied.
// Note: avoid ',' and ':' inside passwords (they're the delimiters).

export const config = {
  // Gate every route except Vercel's internal analytics/insights beacons.
  matcher: ["/((?!_vercel/).*)"],
};

const REALM = "C-Bot";

function parseUsers() {
  const map = new Map();
  const raw = process.env.BASIC_AUTH_USERS || "";
  for (const pair of raw.split(",")) {
    const s = pair.trim();
    if (!s) continue;
    const i = s.indexOf(":");
    if (i <= 0) continue; // need a non-empty username before the colon
    map.set(s.slice(0, i), s.slice(i + 1));
  }
  return map;
}

// Constant-time compare so a wrong password can't be guessed by timing.
function safeEqual(a, b) {
  if (typeof a !== "string" || typeof b !== "string") return false;
  const enc = new TextEncoder();
  const ba = enc.encode(a);
  const bb = enc.encode(b);
  if (ba.length !== bb.length) return false;
  let diff = 0;
  for (let i = 0; i < ba.length; i++) diff |= ba[i] ^ bb[i];
  return diff === 0;
}

function unauthorized(body, extraHeaders) {
  return new Response(body, {
    status: 401,
    headers: {
      "WWW-Authenticate": `Basic realm="${REALM}", charset="UTF-8"`,
      "Cache-Control": "no-store",
      ...extraHeaders,
    },
  });
}

export default function middleware(request) {
  const users = parseUsers();
  if (users.size === 0) {
    // No credentials configured → deny everything (fail closed).
    return new Response("Auth not configured.", {
      status: 503,
      headers: { "Cache-Control": "no-store" },
    });
  }

  const header = request.headers.get("authorization") || "";
  const [scheme, encoded] = header.split(" ");
  if (scheme === "Basic" && encoded) {
    let decoded = "";
    try {
      decoded = atob(encoded);
    } catch {
      decoded = "";
    }
    const i = decoded.indexOf(":");
    if (i >= 0) {
      const user = decoded.slice(0, i);
      const pass = decoded.slice(i + 1);
      const expected = users.get(user);
      if (expected !== undefined && safeEqual(pass, expected)) {
        return; // authenticated → continue to the app
      }
    }
  }
  return unauthorized("Authentication required.");
}
