import { useEffect, useState } from "react";
import { createUser, deleteUser, listUsers, updateUser } from "../api";

// Admin-only account management: add / rename / change-password / toggle-admin /
// delete the login accounts stored in Supabase.
export default function Users() {
  const [users, setUsers] = useState([]);
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);

  // new-user form
  const [nu, setNu] = useState("");
  const [np, setNp] = useState("");
  const [nAdmin, setNAdmin] = useState(false);

  // per-row password edit: { [username]: "newpass" }
  const [pw, setPw] = useState({});

  const refresh = () =>
    listUsers()
      .then((r) => setUsers(r.users))
      .catch((e) => setStatus(e.message));

  useEffect(() => {
    refresh();
  }, []);

  async function run(fn, ok) {
    setBusy(true);
    setStatus("");
    try {
      await fn();
      setStatus(ok);
      await refresh();
    } catch (e) {
      setStatus(e.message);
    } finally {
      setBusy(false);
    }
  }

  const add = () => {
    if (!nu.trim() || !np) return setStatus("Username and password are required.");
    run(async () => {
      await createUser({ username: nu.trim(), password: np, is_admin: nAdmin });
      setNu("");
      setNp("");
      setNAdmin(false);
    }, "User added ✓");
  };

  const changePw = (username) => {
    const p = pw[username];
    if (!p) return setStatus("Enter a new password first.");
    run(async () => {
      await updateUser(username, { password: p });
      setPw((s) => ({ ...s, [username]: "" }));
    }, `Password updated for ${username} ✓`);
  };

  const toggleAdmin = (u) =>
    run(() => updateUser(u.username, { is_admin: !u.is_admin }), "Role updated ✓");

  const remove = (username) => {
    if (!window.confirm(`Delete user “${username}”?`)) return;
    run(() => deleteUser(username), `Deleted ${username} ✓`);
  };

  return (
    <div className="settings-card">
      <h2>Users</h2>
      <p className="hint">
        Login accounts for this app. Admins can reach Products &amp; Settings; other
        users only see Z-Bot and About.
      </p>

      <ul className="users-list">
        {users.map((u) => (
          <li key={u.username} className="user-row">
            <div className="user-main">
              <span className="user-name">{u.username}</span>
              <button
                className={`role-chip ${u.is_admin ? "role-chip--admin" : ""}`}
                onClick={() => toggleAdmin(u)}
                disabled={busy}
                title="Toggle admin"
              >
                {u.is_admin ? "admin" : "user"}
              </button>
            </div>
            <div className="user-actions">
              <input
                type="password"
                placeholder="New password"
                value={pw[u.username] || ""}
                onChange={(e) => setPw((s) => ({ ...s, [u.username]: e.target.value }))}
                disabled={busy}
              />
              <button className="secondary" onClick={() => changePw(u.username)} disabled={busy}>
                Set
              </button>
              <button className="delete-btn" title="Delete user" onClick={() => remove(u.username)} disabled={busy}>
                ✕
              </button>
            </div>
          </li>
        ))}
      </ul>

      <h3>Add a user</h3>
      <div className="user-add">
        <input
          type="text"
          placeholder="Username"
          value={nu}
          autoCapitalize="none"
          onChange={(e) => setNu(e.target.value)}
          disabled={busy}
        />
        <input
          type="password"
          placeholder="Password"
          value={np}
          onChange={(e) => setNp(e.target.value)}
          disabled={busy}
        />
        <label className="user-admin-check">
          <input type="checkbox" checked={nAdmin} onChange={(e) => setNAdmin(e.target.checked)} />
          Admin
        </label>
        <button onClick={add} disabled={busy}>
          Add
        </button>
      </div>

      {status && <p className="hint">{status}</p>}
    </div>
  );
}
