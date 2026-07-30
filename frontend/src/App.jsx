import { useCallback, useEffect, useState } from "react";
import ChatWindow from "./components/ChatWindow";
import Products from "./components/Products";
import Settings from "./components/Settings";
import About from "./components/About";
import { listProducts, getMe } from "./api";
import { LANGUAGES } from "./languages";

export default function App() {
  const [view, setView] = useState("chat");
  const [language, setLanguage] = useState("en");
  const [products, setProducts] = useState([]);
  const [me, setMe] = useState(null); // { user, admin } — null while loading

  const isAdmin = !!me?.admin;

  const refreshProducts = useCallback(async () => {
    try {
      const res = await listProducts();
      setProducts(res.products);
    } catch {
      // backend not up yet / not permitted
    }
  }, []);

  // Identify the logged-in user so we can show the right pages.
  useEffect(() => {
    getMe()
      .then(setMe)
      .catch(() => setMe({ user: null, admin: false }));
  }, []);

  // Products list is admin-only; only load it once we know we're admin.
  useEffect(() => {
    if (isAdmin) refreshProducts();
  }, [isAdmin, refreshProducts]);

  // Guard: never leave a non-admin sitting on an admin-only view.
  useEffect(() => {
    if (me && !isAdmin && (view === "products" || view === "settings")) {
      setView("chat");
    }
  }, [me, isAdmin, view]);

  // Admins: Z-Bot · Products · Settings (About lives inside Settings).
  // Everyone else: Z-Bot · About (About sits beside Z-Bot).
  const tabs = isAdmin
    ? [
        { id: "chat", label: "Z-Bot" },
        { id: "products", label: "Products" },
        { id: "settings", label: "Settings" },
      ]
    : [
        { id: "chat", label: "Z-Bot" },
        { id: "about", label: "About" },
      ];

  return (
    <div className="app">
      <header className="topnav">
        <nav className="tabs">
          {tabs.map((t) => (
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
        <a className="logout-link" href="/logout" title="Sign out">
          Log&nbsp;out
        </a>
      </header>

      <div className="view">
        {view === "chat" && <ChatWindow language={language} />}
        {view === "products" && isAdmin && (
          <Products products={products} onChanged={refreshProducts} />
        )}
        {view === "settings" && isAdmin && (
          <Settings onShowAbout={() => setView("about")} />
        )}
        {view === "about" && <About />}
      </div>
    </div>
  );
}
