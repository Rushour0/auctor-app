import { goToLogin } from "./api";

/**
 * Standalone login screen rendered at /login, OUTSIDE the four-tab AppShell.
 *
 * This is the GitHub-OAuth gate in front of the four top-level pages
 * (Conversations, Crons, Posts, Metrics) — it is deliberately NOT a fifth
 * page. The single primary action full-page-navigates to the backend
 * authorize route via goToLogin(); there is no data fetching here.
 */
export default function Login() {
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
      </div>
    </main>
  );
}
