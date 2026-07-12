// Persistent header + four-tab nav wrapping the authenticated page routes.
//
// Rendered inside RequireAuth, so a valid operator session is already
// guaranteed here. Renders the fixed four-tab nav (Conversations / Crons /
// Posts / Metrics — no more, no fewer) plus a logout action, then the
// matched child route via <Outlet />.

import { NavLink, Outlet } from "react-router-dom";
import { logout } from "../auth/api";

const TABS = [
  { to: "/conversations", label: "Conversations" },
  { to: "/crons", label: "Crons" },
  { to: "/posts", label: "Posts" },
  { to: "/metrics", label: "Metrics" },
] as const;

const navLinkStyle = ({ isActive }: { isActive: boolean }): React.CSSProperties => ({
  padding: "0.5rem 0.9rem",
  borderRadius: 6,
  textDecoration: "none",
  color: isActive ? "#fff" : "inherit",
  background: isActive ? "#2563eb" : "transparent",
  fontWeight: isActive ? 600 : 400,
});

export default function AppShell() {
  return (
    <div style={{ fontFamily: "system-ui, sans-serif", minHeight: "100vh" }}>
      <header
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "0.75rem 1.5rem",
          borderBottom: "1px solid #e5e7eb",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "1.5rem" }}>
          <strong>Auctor</strong>
          <nav style={{ display: "flex", gap: "0.5rem" }}>
            {TABS.map((tab) => (
              <NavLink key={tab.to} to={tab.to} style={navLinkStyle}>
                {tab.label}
              </NavLink>
            ))}
          </nav>
        </div>
        <button onClick={() => void logout()} style={{ cursor: "pointer" }}>
          Log out
        </button>
      </header>
      <main style={{ padding: "1.5rem" }}>
        <Outlet />
      </main>
    </div>
  );
}
