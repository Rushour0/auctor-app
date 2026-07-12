// Admin utility: manually run one content job (research -> draft -> QA -> approval
// gate) against an arbitrary workspace/fleet/client, without going through the
// Conversations chat UI. Styled to match the rest of the operator console (system-ui,
// #2563eb primary, #d1d5db/#e5e7eb borders, 6-8px radii) — this page used to be raw,
// unstyled JSX (bare <input>/<button>/<a>, browser defaults throughout).

import { useState } from "react";
import type React from "react";
import { getWorkspaceId } from "../auth/api";

const inputStyle: React.CSSProperties = {
  padding: "0.55rem 0.7rem",
  borderRadius: 6,
  border: "1px solid #d1d5db",
  fontFamily: "inherit",
  fontSize: "0.9rem",
};

const labelStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: "0.3rem",
  fontSize: "0.8rem",
  color: "#6b7280",
};

function Field({
  label,
  ...props
}: React.InputHTMLAttributes<HTMLInputElement> & { label: string }): React.JSX.Element {
  return (
    <label style={labelStyle}>
      <span>{label}</span>
      <input style={inputStyle} {...props} />
    </label>
  );
}

export default function ContentJob() {
  const [workspaceId, setWorkspaceId] = useState(
    localStorage.getItem("auctor-workspace") || getWorkspaceId(),
  );
  const [fleetId, setFleetId] = useState("");
  const [clientId, setClientId] = useState("");
  const [topic, setTopic] = useState("AI agents and founder-led growth");
  const [job, setJob] = useState<Record<string, string> | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function start() {
    setLoading(true);
    setError("");
    try {
      const response = await fetch("/api/content-jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ workspace_id: workspaceId, fleet_id: fleetId, client_id: clientId, topic }),
      });
      if (!response.ok) throw new Error(await response.text());
      setJob(await response.json());
    } catch (reason) {
      setError(String(reason));
    } finally {
      setLoading(false);
    }
  }

  async function approve() {
    if (!job?.approval_id) return;
    setLoading(true);
    setError("");
    try {
      const response = await fetch(
        `/api/content-jobs/approvals/${job.approval_id}/approve?workspace_id=${encodeURIComponent(workspaceId)}`,
        { method: "POST" },
      );
      if (!response.ok) throw new Error(await response.text());
      setJob(await response.json());
    } catch (reason) {
      setError(String(reason));
    } finally {
      setLoading(false);
    }
  }

  return (
    <section style={{ fontFamily: "system-ui, sans-serif", padding: "1.5rem", maxWidth: 900 }}>
      <h1 style={{ fontSize: "1.3rem", margin: "0 0 4px" }}>Run a content job</h1>
      <p style={{ color: "#6b7280", fontSize: "0.9rem", margin: "0 0 1.25rem" }}>
        Live research, a sourced draft and QA — then a hard stop for approval.
      </p>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit,minmax(180px,1fr))",
          gap: 12,
          alignItems: "end",
        }}
      >
        <Field label="Workspace ID" value={workspaceId} onChange={(e) => setWorkspaceId(e.target.value)} placeholder="Workspace ID" />
        <Field label="Fleet ID" value={fleetId} onChange={(e) => setFleetId(e.target.value)} placeholder="Fleet ID" />
        <Field label="Client ID" value={clientId} onChange={(e) => setClientId(e.target.value)} placeholder="Client ID" />
        <Field label="Topic" value={topic} onChange={(e) => setTopic(e.target.value)} placeholder="Topic" />
        <button
          onClick={() => void start()}
          disabled={loading || !fleetId || !clientId || !topic}
          style={{
            padding: "0.6rem 1rem",
            borderRadius: 6,
            border: "none",
            background: loading || !fleetId || !clientId || !topic ? "#93c5fd" : "#2563eb",
            color: "#fff",
            fontFamily: "inherit",
            fontSize: "0.9rem",
            fontWeight: 600,
            cursor: loading || !fleetId || !clientId || !topic ? "default" : "pointer",
          }}
        >
          {loading ? "Working…" : "Research and draft"}
        </button>
      </div>

      {error && (
        <p style={{ color: "#991b1b", background: "#fee2e2", borderRadius: 6, padding: "0.6rem 0.8rem", marginTop: 16, fontSize: "0.85rem" }}>
          {error}
        </p>
      )}

      {job && (
        <div
          style={{
            marginTop: 20,
            padding: 18,
            borderRadius: 10,
            border: "1px solid #e5e7eb",
            background: "#f9fafb",
            whiteSpace: "pre-wrap",
          }}
        >
          <span
            style={{
              display: "inline-block",
              padding: "2px 10px",
              borderRadius: 999,
              fontSize: 12,
              fontWeight: 600,
              background: job.status === "awaiting_approval" ? "#fef3c7" : "#dcfce7",
              color: job.status === "awaiting_approval" ? "#92400e" : "#166534",
            }}
          >
            {job.status}
          </span>
          {job.draft && <p style={{ fontSize: "0.9rem", lineHeight: 1.5, margin: "12px 0" }}>{job.draft}</p>}
          {job.status === "awaiting_approval" && (
            <button
              onClick={() => void approve()}
              disabled={loading}
              style={{
                padding: "0.5rem 0.9rem",
                borderRadius: 6,
                border: "1px solid #92400e",
                background: loading ? "#fde68a" : "#fbbf24",
                color: "#78350f",
                fontFamily: "inherit",
                fontSize: "0.85rem",
                fontWeight: 600,
                cursor: loading ? "default" : "pointer",
              }}
            >
              Approve and publish to web
            </button>
          )}
          {job.post_url && (
            <p style={{ marginTop: 10 }}>
              <a href={job.post_url} style={{ color: "#2563eb", fontSize: "0.85rem", fontWeight: 600 }}>
                Open published output ↗
              </a>
            </p>
          )}
        </div>
      )}
    </section>
  );
}
