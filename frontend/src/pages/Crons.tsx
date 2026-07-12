// Crons page — the scheduled content-loop triggers view.
//
// Reads workflow_triggers via GET /api/workflows/triggers (newest first) and
// renders one row per TriggerItem. Because cadence is now split PER PLATFORM
// (x and linkedin schedule independently), the platform column renders as a
// small colored pill to reinforce that a row belongs to one platform's loop —
// '—' when the trigger predates the split and has no platform.
//
// A pending trigger can be acked to `running` inline: POST
// /api/workflows/triggers/ack {workspace_id,trigger_id,status:'running'}, then
// the table reloads. Each row carries its own busy flag so the button disables
// only for the row being acked, never the whole table.
//
// Inline-styled to match the operator console's dependency-free page shell.

import type React from "react";
import { useState } from "react";
import { useFetch } from "../hooks/useFetch";
import { api, type TriggerItem } from "../api/client";

/** Format an ISO timestamp for display; empty/invalid values render as '—'. */
function fmtDate(iso?: string): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString();
}

/** Amber/blue/green/red pill palette for the trigger lifecycle statuses. */
const STATUS_COLORS: Record<TriggerItem["status"], { bg: string; fg: string }> = {
  pending: { bg: "#fef3c7", fg: "#92400e" },
  running: { bg: "#dbeafe", fg: "#1e40af" },
  completed: { bg: "#dcfce7", fg: "#166534" },
  failed: { bg: "#fee2e2", fg: "#991b1b" },
};

/** Per-platform pill palette — x and linkedin are visually distinct. */
const PLATFORM_COLORS: Record<"x" | "linkedin", { bg: string; fg: string }> = {
  x: { bg: "#e0e7ff", fg: "#3730a3" },
  linkedin: { bg: "#cffafe", fg: "#155e75" },
};

const pillStyle = (c: { bg: string; fg: string }): React.CSSProperties => ({
  display: "inline-block",
  padding: "2px 8px",
  borderRadius: 999,
  background: c.bg,
  color: c.fg,
  fontSize: 12,
  fontWeight: 600,
  textTransform: "lowercase",
});

const thStyle: React.CSSProperties = {
  textAlign: "left",
  padding: "8px 12px",
  borderBottom: "2px solid #e5e7eb",
  fontSize: 12,
  color: "#6b7280",
  textTransform: "uppercase",
  letterSpacing: "0.05em",
  whiteSpace: "nowrap",
};

const tdStyle: React.CSSProperties = {
  padding: "8px 12px",
  borderBottom: "1px solid #f3f4f6",
  fontSize: 14,
  whiteSpace: "nowrap",
};

export default function Crons() {
  const { data, loading, error, reload } = useFetch(() => api.triggers(100), []);
  // Per-row busy flags keyed by trigger_id so acking one row never disables others.
  const [busy, setBusy] = useState<Record<string, boolean>>({});

  const ack = (row: TriggerItem) => {
    setBusy((b) => ({ ...b, [row.trigger_id]: true }));
    api
      .ackTrigger(row.workspace_id, row.trigger_id, "running")
      .then(() => reload())
      .catch((e) => {
        // Surface the failure without losing the console; clear the busy flag.
        alert(`Ack failed: ${String(e)}`);
      })
      .finally(() => setBusy((b) => ({ ...b, [row.trigger_id]: false })));
  };

  return (
    <div style={{ padding: 24 }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: 16,
        }}
      >
        <h2 style={{ margin: 0 }}>Crons</h2>
        <button
          type="button"
          onClick={reload}
          disabled={loading}
          style={{
            padding: "6px 14px",
            borderRadius: 6,
            border: "1px solid #d1d5db",
            background: "#fff",
            cursor: loading ? "default" : "pointer",
            fontSize: 14,
          }}
        >
          Refresh
        </button>
      </div>

      {loading && <p style={{ color: "#6b7280" }}>Loading…</p>}
      {error && <p style={{ color: "#991b1b" }}>Error: {error}</p>}
      {!loading && !error && data && data.length === 0 && (
        <p style={{ color: "#6b7280" }}>No scheduled triggers.</p>
      )}

      {!loading && !error && data && data.length > 0 && (
        <div style={{ overflowX: "auto" }}>
          <table style={{ borderCollapse: "collapse", width: "100%" }}>
            <thead>
              <tr>
                <th style={thStyle}>Scheduled for</th>
                <th style={thStyle}>Trigger ID</th>
                <th style={thStyle}>Platform</th>
                <th style={thStyle}>Pipeline</th>
                <th style={thStyle}>Status</th>
                <th style={thStyle}>Next content check</th>
                <th style={thStyle} />
              </tr>
            </thead>
            <tbody>
              {data.map((row) => (
                <tr key={row.trigger_id}>
                  <td style={tdStyle}>{fmtDate(row.scheduled_for)}</td>
                  <td style={{ ...tdStyle, fontFamily: "monospace", fontSize: 12 }}>
                    {row.trigger_id}
                  </td>
                  <td style={tdStyle}>
                    {row.platform ? (
                      <span style={pillStyle(PLATFORM_COLORS[row.platform])}>
                        {row.platform}
                      </span>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td style={tdStyle}>{row.pipeline}</td>
                  <td style={tdStyle}>
                    <span style={pillStyle(STATUS_COLORS[row.status])}>{row.status}</span>
                  </td>
                  <td style={tdStyle}>{fmtDate(row.next_content_check_at)}</td>
                  <td style={tdStyle}>
                    {row.status === "pending" && (
                      <button
                        type="button"
                        onClick={() => ack(row)}
                        disabled={!!busy[row.trigger_id]}
                        style={{
                          padding: "4px 10px",
                          borderRadius: 6,
                          border: "1px solid #1e40af",
                          background: busy[row.trigger_id] ? "#eff6ff" : "#dbeafe",
                          color: "#1e40af",
                          cursor: busy[row.trigger_id] ? "default" : "pointer",
                          fontSize: 12,
                          fontWeight: 600,
                        }}
                      >
                        {busy[row.trigger_id] ? "Acking…" : "Ack running"}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
