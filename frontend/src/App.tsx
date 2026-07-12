import { useEffect, useState } from "react";

type Health = { status: string; mongo: boolean };
type Version = { auctor: string; env: string };

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [version, setVersion] = useState<Version | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      fetch("/health").then((r) => r.json()),
      fetch("/version").then((r) => r.json()),
    ])
      .then(([h, v]) => {
        setHealth(h);
        setVersion(v);
      })
      .catch((e) => setError(String(e)));
  }, []);

  return (
    <main style={{ fontFamily: "system-ui, sans-serif", padding: "3rem", maxWidth: 640 }}>
      <h1>Auctor workspace</h1>
      <p>Control-plane scaffold — the fleet composer/runs panel lands with Slice 1.</p>
      {error && <p style={{ color: "crimson" }}>API unreachable: {error}</p>}
      {version && (
        <p>
          version <code>{version.auctor}</code> · env <code>{version.env}</code>
        </p>
      )}
      {health && (
        <p>
          service: <code>{health.status}</code> · mongo:{" "}
          <code>{health.mongo ? "connected" : "unreachable"}</code>
        </p>
      )}
    </main>
  );
}
