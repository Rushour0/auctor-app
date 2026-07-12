// Conversations page — the operator's view onto the raw workflow-event stream,
// and the place agent runs become visible.
//
// One row per fleet_events document: every lifecycle event WorkflowStore records
// as fleets move their site_build / content_loop pipelines forward. Each event
// optionally carries a run_id/agent/stage/outcome/cost_usd — that's a single
// agent's step within a run, not just a generic log line, so those columns are
// surfaced directly rather than buried in the payload JSON.
//
// Reads through the typed api.events() client (GET /api/workflows/events) —
// this file used to hand-roll its own fetch('/api/events'), which 404'd; now it
// goes through the same client every other page uses.

import type React from "react";

import { useFetch } from "../hooks/useFetch";
import { api, type EventItem } from "../api/client";

/** Format an ISO-8601 timestamp for the recorded_at column; pass raw text through on parse failure. */
function fmtDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString();
}

/** Compact single-line JSON for the payload cell, truncated for width (full text goes in title=). */
function payloadPreview(payload: Record<string, unknown>): string {
  const text = JSON.stringify(payload ?? {});
  return text.length > 120 ? `${text.slice(0, 117)}…` : text;
}

function fmtCost(cost?: number): string {
  if (!cost) return "—";
  return `$${cost.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 4 })}`;
}

const OUTCOME_COLORS: Record<string, { bg: string; fg: string }> = {
  succeeded: { bg: "#dcfce7", fg: "#166534" },
  failed: { bg: "#fee2e2", fg: "#991b1b" },
  blocked: { bg: "#fef3c7", fg: "#92400e" },
};

const cellStyle: React.CSSProperties = {
  padding: "0.35rem 0.6rem",
  borderBottom: "1px solid #e5e5e5",
  verticalAlign: "top",
  textAlign: "left",
};

const headStyle: React.CSSProperties = {
  ...cellStyle,
  borderBottom: "2px solid #ccc",
  fontWeight: 600,
  whiteSpace: "nowrap",
};

export default function Conversations() {
  const { data, loading, error, reload } = useFetch<EventItem[]>(() => api.events(100), []);

  // Newest-first: sort defensively in case the backend hasn't already.
  const events = (data ?? [])
    .slice()
    .sort((a, b) => new Date(b.recorded_at).getTime() - new Date(a.recorded_at).getTime());

  return (
    <main style={{ fontFamily: "system-ui, sans-serif", padding: "3rem", maxWidth: 1300 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: "1rem" }}>
        <h2 style={{ margin: 0 }}>Conversations</h2>
        <button type="button" onClick={reload} disabled={loading}>
          Refresh
        </button>
      </div>

      {loading && <p>Loading…</p>}

      {error && !loading && (
        <p style={{ color: "crimson" }}>
          Failed to load events: {error}{" "}
          <button type="button" onClick={reload}>
            Retry
          </button>
        </p>
      )}

      {!loading && !error && events.length === 0 && (
        <p>No events yet — start a fleet or content job to see agent runs here.</p>
      )}

      {!loading && !error && events.length > 0 && (
        <div style={{ overflowX: "auto" }}>
          <table
            style={{
              width: "100%",
              borderCollapse: "collapse",
              fontSize: "0.8rem",
              marginTop: "1rem",
            }}
          >
            <thead>
              <tr>
                <th style={headStyle}>recorded_at</th>
                <th style={headStyle}>run_id</th>
                <th style={headStyle}>agent</th>
                <th style={headStyle}>stage</th>
                <th style={headStyle}>outcome</th>
                <th style={headStyle}>event_type</th>
                <th style={headStyle}>client_id</th>
                <th style={headStyle}>duration</th>
                <th style={headStyle}>cost</th>
                <th style={headStyle}>payload</th>
              </tr>
            </thead>
            <tbody>
              {events.map((ev) => {
                const outcomeColor = ev.outcome ? OUTCOME_COLORS[ev.outcome] : undefined;
                return (
                  <tr key={ev.event_id}>
                    <td style={{ ...cellStyle, whiteSpace: "nowrap" }}>{fmtDate(ev.recorded_at)}</td>
                    <td
                      style={{ ...cellStyle, fontFamily: "ui-monospace, monospace", fontSize: 11 }}
                    >
                      {ev.run_id ?? "—"}
                    </td>
                    <td style={cellStyle}>{ev.agent ?? "—"}</td>
                    <td style={cellStyle}>{ev.stage ?? "—"}</td>
                    <td style={cellStyle}>
                      {ev.outcome ? (
                        <span
                          style={{
                            display: "inline-block",
                            padding: "2px 8px",
                            borderRadius: 999,
                            fontSize: 11,
                            fontWeight: 600,
                            background: outcomeColor?.bg ?? "#f3f4f6",
                            color: outcomeColor?.fg ?? "#374151",
                          }}
                        >
                          {ev.outcome}
                        </span>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td style={cellStyle}>{ev.event_type}</td>
                    <td style={cellStyle}>{ev.client_id ?? "—"}</td>
                    <td style={cellStyle}>{ev.duration_ms ? `${ev.duration_ms}ms` : "—"}</td>
                    <td style={cellStyle}>{fmtCost(ev.cost_usd)}</td>
                    <td
                      style={{
                        ...cellStyle,
                        fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
                        whiteSpace: "nowrap",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        maxWidth: 320,
                      }}
                      title={JSON.stringify(ev.payload ?? {}, null, 2)}
                    >
                      {payloadPreview(ev.payload)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </main>
  );
}
