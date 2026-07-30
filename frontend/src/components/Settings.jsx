import { useEffect, useRef, useState } from "react";
import {
  addKnowledgeFile,
  addKnowledgeText,
  deleteKnowledge,
  getSettings,
  listKnowledge,
  saveSettings,
} from "../api";

export default function Settings({ onShowAbout }) {
  const [guidelines, setGuidelines] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState("");

  // Knowledge base
  const [docs, setDocs] = useState([]);
  const [kTitle, setKTitle] = useState("");
  const [kText, setKText] = useState("");
  const [kBusy, setKBusy] = useState(false);
  const [kStatus, setKStatus] = useState("");
  const fileRef = useRef(null);

  useEffect(() => {
    getSettings()
      .then((s) => setGuidelines(s.answer_guidelines || ""))
      .catch((e) => setStatus(e.message))
      .finally(() => setLoading(false));
    refreshDocs();
  }, []);

  function refreshDocs() {
    listKnowledge()
      .then((r) => setDocs(r.documents))
      .catch(() => {});
  }

  async function save() {
    setSaving(true);
    setStatus("");
    try {
      const s = await saveSettings({ answer_guidelines: guidelines });
      setGuidelines(s.answer_guidelines || "");
      setStatus("Saved ✓");
    } catch (e) {
      setStatus(e.message);
    } finally {
      setSaving(false);
    }
  }

  async function addText() {
    if (!kText.trim()) return setKStatus("Paste some text first.");
    setKBusy(true);
    setKStatus("Adding…");
    try {
      const d = await addKnowledgeText(kTitle || "Untitled document", kText);
      setKStatus(`Added “${d.title}” (${d.chunks} chunk${d.chunks === 1 ? "" : "s"})`);
      setKTitle("");
      setKText("");
      refreshDocs();
    } catch (e) {
      setKStatus(e.message);
    } finally {
      setKBusy(false);
    }
  }

  async function addFile(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    setKBusy(true);
    setKStatus(`Reading ${file.name}…`);
    try {
      const d = await addKnowledgeFile(file, kTitle);
      setKStatus(`Added “${d.title}” (${d.chunks} chunk${d.chunks === 1 ? "" : "s"})`);
      setKTitle("");
      refreshDocs();
    } catch (err) {
      setKStatus(err.message);
    } finally {
      setKBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  async function removeDoc(id) {
    try {
      await deleteKnowledge(id);
      refreshDocs();
    } catch (e) {
      setKStatus(e.message);
    }
  }

  return (
    <div className="settings-page">
      <div className="settings-card">
        <h2>About</h2>
        <p className="hint">App information and credits.</p>
        <div className="settings-foot">
          <button className="secondary" onClick={onShowAbout}>
            Open About page
          </button>
        </div>
      </div>

      <div className="settings-card">
        <h2>AI answering guidance</h2>
        <p className="hint">
          How C-Bot should help shoppers choose — added to the chat prompt (e.g. ask
          category-specific clarifying questions before recommending). Answers stay
          grounded in your indexed products.
        </p>
        {loading ? (
          <p className="hint">Loading…</p>
        ) : (
          <textarea
            className="guidelines-input"
            rows={12}
            value={guidelines}
            onChange={(e) => setGuidelines(e.target.value)}
          />
        )}
        <div className="settings-foot">
          <button onClick={save} disabled={saving || loading}>
            {saving ? "Saving…" : "Save guidance"}
          </button>
          {status && <span className="hint">{status}</span>}
        </div>
      </div>

      <div className="settings-card">
        <h2>Knowledge base</h2>
        <p className="hint">
          Reference documents (Costco policies, rules, membership, returns, FAQs…).
          C-Bot uses these to answer policy/general questions — grounded in what you
          add here.
        </p>

        <div className="kb-add">
          <input
            type="text"
            placeholder="Document title (optional)"
            value={kTitle}
            onChange={(e) => setKTitle(e.target.value)}
            disabled={kBusy}
          />
          <textarea
            rows={5}
            placeholder="Paste policy / reference text here…"
            value={kText}
            onChange={(e) => setKText(e.target.value)}
            disabled={kBusy}
          />
          <div className="kb-add-actions">
            <button onClick={addText} disabled={kBusy}>
              Add text
            </button>
            <label className="file-btn secondary">
              Upload file (.txt .md .pdf)
              <input
                ref={fileRef}
                type="file"
                accept=".txt,.md,.markdown,.pdf,text/plain,application/pdf"
                onChange={addFile}
                disabled={kBusy}
                hidden
              />
            </label>
          </div>
          {kStatus && <p className="hint">{kStatus}</p>}
        </div>

        <h3 className="kb-list-title">Documents ({docs.length})</h3>
        {docs.length === 0 ? (
          <p className="hint">No documents yet.</p>
        ) : (
          <ul className="kb-list">
            {docs.map((d) => (
              <li key={d.doc_id}>
                <span className="kb-doc-title">{d.title}</span>
                <span className="kb-doc-meta">
                  {d.chunks} chunk{d.chunks === 1 ? "" : "s"}
                  {d.source ? ` · ${d.source}` : ""}
                </span>
                <button className="delete-btn" title="Remove" onClick={() => removeDoc(d.doc_id)}>
                  ✕
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
