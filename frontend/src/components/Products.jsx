import { useRef, useState } from "react";
import {
  deleteProduct,
  indexCodes,
  indexManual,
  indexOpenTabs,
  indexPhoto,
  indexUrls,
  loadSamples,
  updateProduct,
} from "../api";

const FIELDS = [
  { key: "title", label: "Title" },
  { key: "brand", label: "Brand" },
  { key: "model", label: "Model" },
  { key: "price", label: "Current price" },
  { key: "price_date", label: "Current price date" },
  { key: "promo_price", label: "Sale price" },
  { key: "price_valid_until", label: "Sale price expires" },
  { key: "regular_price", label: "Regular price" },
  { key: "rating", label: "Rating" },
  { key: "url", label: "URL" },
];

// Manual-add form fields (works from any device — no scraping). item_code first.
const MANUAL_FIELDS = [
  { key: "item_code", label: "Item code / number *", placeholder: "e.g. 1858512" },
  { key: "title", label: "Product name" },
  { key: "brand", label: "Brand" },
  { key: "model", label: "Model" },
  { key: "price", label: "Current price", placeholder: "$59.99" },
  { key: "price_date", label: "Current price date", placeholder: "2026-08-06" },
  { key: "promo_price", label: "Sale price" },
  { key: "price_valid_until", label: "Sale price expires", placeholder: "2026-08-20" },
  { key: "rating", label: "Rating", placeholder: "4.5" },
];

const EMPTY_PRODUCT = {
  item_code: "", title: "", brand: "", model: "", price: "", price_date: "",
  promo_price: "", price_valid_until: "", rating: "", description: "", features: "",
};

function ProductCard({ product, onChanged }) {
  const [draft, setDraft] = useState({
    ...product,
    features: (product.features || []).join("\n"),
  });
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");

  function set(key, value) {
    setDraft((d) => ({ ...d, [key]: value }));
    setSaved(false);
  }

  async function save() {
    setSaving(true);
    setError("");
    try {
      await updateProduct(product.item_code, {
        ...draft,
        features: draft.features
          .split("\n")
          .map((s) => s.trim())
          .filter(Boolean),
      });
      setSaved(true);
      onChanged();
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  }

  async function remove() {
    setError("");
    try {
      await deleteProduct(product.item_code);
      onChanged();
    } catch (e) {
      setError(e.message);
    }
  }

  return (
    <div className="product-card">
      <div className="product-card-head">
        <span className="product-code">#{product.item_code}</span>
        <button className="delete-btn" title="Remove" onClick={remove}>
          ✕
        </button>
      </div>
      <div className="fields">
        {FIELDS.map((f) => (
          <label className="field" key={f.key}>
            <span>{f.label}</span>
            <input value={draft[f.key] || ""} onChange={(e) => set(f.key, e.target.value)} />
          </label>
        ))}
      </div>
      <label className="field">
        <span>Description</span>
        <textarea rows={2} value={draft.description || ""} onChange={(e) => set("description", e.target.value)} />
      </label>
      <label className="field">
        <span>Features (one per line)</span>
        <textarea rows={3} value={draft.features} onChange={(e) => set("features", e.target.value)} />
      </label>
      <div className="product-card-foot">
        <button onClick={save} disabled={saving}>
          {saving ? "Saving…" : saved ? "Saved ✓" : "Save"}
        </button>
        {error && <span className="err-text">{error}</span>}
      </div>
    </div>
  );
}

export default function Products({ products, onChanged }) {
  const [codesText, setCodesText] = useState("");
  const [urlsText, setUrlsText] = useState("");
  const [draft, setDraft] = useState(EMPTY_PRODUCT);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState(null);
  const fileRef = useRef(null);

  const setField = (k, v) => setDraft((d) => ({ ...d, [k]: v }));

  function applyResults(results, prefix = []) {
    const lines = [...prefix];
    let anyError = false;
    for (const r of results) {
      if (r.status === "indexed") lines.push(`✓ ${r.item_code} — ${r.title || "indexed"}`);
      else {
        anyError = true;
        lines.push(`✗ ${r.item_code} — ${r.error}`);
      }
    }
    setStatus({ kind: anyError ? "warn" : "success", lines });
  }

  async function run(fn, infoLine) {
    setBusy(true);
    setStatus({ kind: "info", lines: [infoLine] });
    try {
      return await fn();
    } catch (e) {
      setStatus({ kind: "error", lines: [e.message] });
    } finally {
      setBusy(false);
      onChanged();
    }
  }

  const parse = (t) => t.split(/[\s,]+/).map((s) => s.trim()).filter(Boolean);

  async function addCodes() {
    const codes = parse(codesText);
    if (!codes.length) return setStatus({ kind: "error", lines: ["Enter at least one item code."] });
    const res = await run(() => indexCodes(codes), `Scraping ${codes.length} item(s)…`);
    if (res) {
      applyResults(res.results);
      setCodesText("");
    }
  }

  async function addUrls() {
    const urls = urlsText.split(/\s*\n\s*/).map((s) => s.trim()).filter(Boolean);
    if (!urls.length) return setStatus({ kind: "error", lines: ["Paste at least one URL."] });
    const res = await run(() => indexUrls(urls), `Scraping ${urls.length} URL(s)…`);
    if (res) {
      applyResults(res.results);
      setUrlsText("");
    }
  }

  async function addPhoto(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    const res = await run(() => indexPhoto(file), "Reading photo with Claude vision…");
    if (res) {
      const prefix = res.extracted_codes.length
        ? [`Found: ${res.extracted_codes.join(", ")}`]
        : [res.vision_note || "No item numbers found."];
      applyResults(res.results, prefix);
    }
    if (fileRef.current) fileRef.current.value = "";
  }

  async function addManual() {
    if (!draft.item_code.trim()) {
      return setStatus({ kind: "error", lines: ["Item code / number is required."] });
    }
    const product = {
      ...draft,
      item_code: draft.item_code.trim(),
      features: draft.features.split("\n").map((s) => s.trim()).filter(Boolean),
    };
    const res = await run(() => indexManual([product]), `Adding ${product.item_code}…`);
    if (res) {
      applyResults(res.results);
      if (res.results.every((r) => r.status === "indexed")) setDraft(EMPTY_PRODUCT);
    }
  }

  async function openTabs() {
    const res = await run(() => indexOpenTabs(), "Reading open Costco tab(s)…");
    if (res) applyResults(res.results);
  }

  async function samples() {
    const res = await run(() => loadSamples(), "Loading sample products…");
    if (res) applyResults(res.results);
  }

  return (
    <div className="products-page">
      <aside className="ingest-panel">
        <h2>Add a product</h2>
        {MANUAL_FIELDS.map((f) => (
          <label className="field" key={f.key}>
            <span>{f.label}</span>
            <input
              value={draft[f.key]}
              placeholder={f.placeholder || ""}
              onChange={(e) => setField(f.key, e.target.value)}
              disabled={busy}
            />
          </label>
        ))}
        <label className="field">
          <span>Description</span>
          <textarea
            rows={2}
            value={draft.description}
            onChange={(e) => setField("description", e.target.value)}
            disabled={busy}
          />
        </label>
        <label className="field">
          <span>Features (one per line)</span>
          <textarea
            rows={3}
            value={draft.features}
            onChange={(e) => setField("features", e.target.value)}
            disabled={busy}
          />
        </label>
        <button onClick={addManual} disabled={busy}>Add product</button>

        <h2>Add by item code</h2>
        <textarea
          rows={2}
          placeholder="e.g. 1858512, 3118678"
          value={codesText}
          onChange={(e) => setCodesText(e.target.value)}
          disabled={busy}
        />
        <button onClick={addCodes} disabled={busy}>Scrape &amp; index</button>

        <h2>Add by product URL</h2>
        <textarea
          rows={2}
          placeholder="Paste costco.ca product URL(s), one per line"
          value={urlsText}
          onChange={(e) => setUrlsText(e.target.value)}
          disabled={busy}
        />
        <button onClick={addUrls} disabled={busy}>Scrape URL &amp; index</button>

        <h2>Other ways to add</h2>
        <button className="secondary" onClick={openTabs} disabled={busy}>Read open Costco tab(s)</button>
        <label className="file-btn secondary">
          Upload photo
          <input ref={fileRef} type="file" accept="image/*" onChange={addPhoto} disabled={busy} hidden />
        </label>
        <button className="secondary" onClick={samples} disabled={busy}>Load sample products</button>

        {status && (
          <div className={`status status--${status.kind}`}>
            {status.lines.map((l, i) => (
              <div key={i}>{l}</div>
            ))}
          </div>
        )}
      </aside>

      <section className="product-list">
        <h2 className="product-list-title">Indexed products ({products.length})</h2>
        {products.length === 0 ? (
          <p className="hint">Nothing indexed yet — add products on the left.</p>
        ) : (
          <div className="product-grid">
            {products.map((p) => (
              <ProductCard key={p.item_code} product={p} onChanged={onChanged} />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
