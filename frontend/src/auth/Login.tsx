import { useState } from "react";
import type React from "react";
import { useNavigate } from "react-router-dom";
import { goToLogin, loginWithCredentials } from "./api";

/**
 * Standalone login screen rendered at /login, OUTSIDE the four-tab AppShell.
 *
 * This is the gate in front of the four top-level pages (Conversations, Crons,
 * Posts, Metrics) — it is deliberately NOT a fifth page. Two ways in, both
 * setting the same session cookie: the GitHub OAuth redirect (goToLogin), or a
 * username/password fallback (POST /api/auth/login) for deployments where
 * GitHub OAuth isn't configured or working yet. The credential form fails
 * gracefully (503) if the backend has no OPERATOR_LOGIN_USERNAME/PASSWORD set —
 * that's surfaced as a normal error message, not a broken page.
 */
export default function Login() {
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    loginWithCredentials(username, password)
      .then(() => navigate("/", { replace: true }))
      .catch((err: unknown) => setError(err instanceof Error ? err.message : String(err)))
      .finally(() => setLoading(false));
  };

  return (
    <main
      style={{
        fontFamily: "system-ui, sans-serif",
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: "3rem",
      }}
    >
      <div
        style={{
          maxWidth: 380,
          width: "100%",
          border: "1px solid #e2e2e2",
          borderRadius: 12,
          padding: "2.5rem",
          textAlign: "center",
          boxShadow: "0 1px 3px rgba(0,0,0,0.06)",
        }}
      >
        <h1 style={{ fontSize: "1.5rem", marginBottom: "0.5rem" }}>
          Auctor operator console
        </h1>
        <p style={{ color: "#666", marginBottom: "2rem", lineHeight: 1.5 }}>
          Sign in to reach the fleet workspace.
        </p>
        <button
          type="button"
          onClick={() => goToLogin()}
          style={{
            width: "100%",
            padding: "0.75rem 1rem",
            fontFamily: "inherit",
            fontSize: "1rem",
            fontWeight: 600,
            color: "#fff",
            background: "#1f2328",
            border: "none",
            borderRadius: 8,
            cursor: "pointer",
          }}
        >
          Sign in with GitHub
        </button>

        <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", margin: "1.5rem 0" }}>
          <span style={{ flex: 1, height: 1, background: "#e2e2e2" }} />
          <span style={{ fontSize: 12, color: "#999" }}>or</span>
          <span style={{ flex: 1, height: 1, background: "#e2e2e2" }} />
        </div>

        <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: "0.6rem", textAlign: "left" }}>
          <input
            type="text"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            placeholder="Username"
            autoComplete="username"
            disabled={loading}
            style={{ padding: "0.6rem 0.75rem", borderRadius: 6, border: "1px solid #d1d5db" }}
          />
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Password"
            autoComplete="current-password"
            disabled={loading}
            style={{ padding: "0.6rem 0.75rem", borderRadius: 6, border: "1px solid #d1d5db" }}
          />
          <button
            type="submit"
            disabled={loading}
            style={{
              padding: "0.65rem 1rem",
              fontFamily: "inherit",
              fontSize: "0.95rem",
              fontWeight: 600,
              color: "#1f2328",
              background: "#fff",
              border: "1px solid #1f2328",
              borderRadius: 8,
              cursor: loading ? "default" : "pointer",
            }}
          >
            {loading ? "Signing in…" : "Sign in with password"}
          </button>
          {error && <p style={{ color: "#991b1b", fontSize: 13, margin: 0 }}>{error}</p>}
        </form>
      </div>
    </main>
  );
}
