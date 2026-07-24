import { useCallback, useEffect, useState } from "react";
import ChatWindow from "./components/ChatWindow";
import Products from "./components/Products";
import Settings from "./components/Settings";
import { listProducts } from "./api";
import { LANGUAGES } from "./languages";

const TABS = [
  { id: "chat", label: "Chat" },
  { id: "products", label: "Products" },
  { id: "settings", label: "Settings" },
];

export default function App() {
  const [view, setView] = useState("chat");
  const [language, setLanguage] = useState("en");
  const [products, setProducts] = useState([]);

  const refreshProducts = useCallback(async () => {
    try {
      const res = await listProducts();
      setProducts(res.products);
    } catch {
      // backend not up yet
    }
  }, []);

  useEffect(() => {
    refreshProducts();
  }, [refreshProducts]);

  return (
    <div className="app">
      <header className="topnav">
        <span className="brand">🛒 C-Bot</span>
        <nav className="tabs">
          {TABS.map((t) => (
            <button
              key={t.id}
              className={`nav-tab ${view === t.id ? "nav-tab--active" : ""}`}
              onClick={() => setView(t.id)}
            >
              {t.label}
              {t.id === "products" && products.length > 0 && (
                <span className="tab-badge">{products.length}</span>
              )}
            </button>
          ))}
        </nav>
        <label className="lang-select">
          <span aria-hidden="true">🌐</span>
          <select value={language} onChange={(e) => setLanguage(e.target.value)}>
            {LANGUAGES.map((l) => (
              <option key={l.code} value={l.code}>
                {l.label}
              </option>
            ))}
          </select>
        </label>
      </header>

      <div className="view">
        {view === "chat" && <ChatWindow language={language} />}
        {view === "products" && (
          <Products products={products} onChanged={refreshProducts} />
        )}
        {view === "settings" && <Settings />}
      </div>
    </div>
  );
}
