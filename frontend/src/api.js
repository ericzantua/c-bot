// Thin API client. Everything is under /api: in dev, Vite proxies /api → the
// local backend; in production, Vercel routes /api/* to the serverless API.
const BASE = "/api";

async function handle(res) {
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail);
  }
  return res.json();
}

// Who am I? Returns { user, admin } from the auth middleware (the session cookie
// is HttpOnly, so the SPA asks the server instead of reading it).
export async function getMe() {
  return handle(await fetch(`${BASE}/me`));
}

export async function indexCodes(itemCodes) {
  const res = await fetch(`${BASE}/index`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ item_codes: itemCodes }),
  });
  return handle(res);
}

export async function indexOpenTabs() {
  const res = await fetch(`${BASE}/index/open-tabs`, { method: "POST" });
  return handle(res);
}

export async function indexUrls(urls) {
  const res = await fetch(`${BASE}/index/url`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ urls }),
  });
  return handle(res);
}

export async function indexManual(products) {
  const res = await fetch(`${BASE}/index/manual`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ products }),
  });
  return handle(res);
}

export async function loadSamples() {
  const res = await fetch(`${BASE}/index/mock`, { method: "POST" });
  return handle(res);
}

export async function indexPhoto(file) {
  const form = new FormData();
  form.append("image", file);
  const res = await fetch(`${BASE}/index/photo`, { method: "POST", body: form });
  return handle(res);
}

export async function sendChat(question, history, language = "en") {
  const res = await fetch(`${BASE}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, history, language }),
  });
  return handle(res);
}

export async function ttsSynthesize(text) {
  const res = await fetch(`${BASE}/tts`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  if (res.status === 204) throw new Error("__browser__"); // backend says: use browser voice
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail || detail;
    } catch {
      /* non-JSON */
    }
    throw new Error(detail);
  }
  return res.blob(); // audio/mpeg
}

export async function listProducts() {
  const res = await fetch(`${BASE}/products`);
  return handle(res);
}

export async function updateProduct(itemCode, product) {
  const res = await fetch(`${BASE}/products/${encodeURIComponent(itemCode)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(product),
  });
  return handle(res);
}

export async function deleteProduct(itemCode) {
  const res = await fetch(`${BASE}/products/${encodeURIComponent(itemCode)}`, {
    method: "DELETE",
  });
  return handle(res);
}

export async function getSettings() {
  return handle(await fetch(`${BASE}/settings`));
}

export async function saveSettings(settings) {
  const res = await fetch(`${BASE}/settings`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(settings),
  });
  return handle(res);
}

export async function listKnowledge() {
  return handle(await fetch(`${BASE}/knowledge`));
}

export async function addKnowledgeText(title, text) {
  const res = await fetch(`${BASE}/knowledge`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title, text }),
  });
  return handle(res);
}

export async function addKnowledgeFile(file, title = "") {
  const form = new FormData();
  form.append("file", file);
  if (title) form.append("title", title);
  const res = await fetch(`${BASE}/knowledge/file`, { method: "POST", body: form });
  return handle(res);
}

export async function deleteKnowledge(docId) {
  const res = await fetch(`${BASE}/knowledge/${encodeURIComponent(docId)}`, {
    method: "DELETE",
  });
  return handle(res);
}
