// Conversations page — the operator's view onto the raw workflow-event stream.
//
// One row per ``fleet_events`` document: every lifecycle event the WorkflowStore records as fleets
// move their site_build / content_loop pipelines forward. This is the closest thing the control
// plane has to a "conversation" transcript, so it lives under the Conversations tab.
//
// Reads through the same-origin ``GET /api/events`` endpoint (Vite proxies /api -> FastAPI on
// :8000, session cookie carried by ``credentials: 'include'``), mirroring auth/api.ts's fetch
// style. State/guards come from the shared useFetch hook.

import type React from "react";

import { useFetch } from "../hooks/useFetch";

/**
 * One raw ``fleet_events`` document, as persisted by WorkflowStore.record_event.
 * ``client_id`` / ``pipeline`` are optional (fleet-level events carry neither), and ``payload`` is
 * an open dict whose shape depends on ``event_type``.
 */
export type EventItem = {
  event_id: string;
  workspace_id: string;
  fleet_id: string;
  event_type: string;
  client_id?: string | null;
  pipeline?: string | null;
  payload: Record<string, unknown>;
  recorded_at: string;
};

/**
 * Fetch the most recent ``fleet_events`` (newest first, capped at ``limit``).
 * The backend returns ``{ events: EventItem[] }``, matching the /api/workflows/fleets envelope.
 */
async function fetchEvents(limit: number): Promise<EventItem[]> {
  const r = await fetch(`/api/events?limit=${limit}`, { credentials: "include" });
  if (!r.ok) throw new Error(`GET /api/events failed: ${r.status}`);
  const body = (await r.json()) as { events?: EventItem[] };
  return body.events ?? [];
}

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
  const { data, loading, error, reload } = useFetch<EventItem[]>(() => fetchEvents(100), []);

  // Newest-first: sort defensively in case the backend hasn't already.
  const events = (data ?? [])
    .slice()
    .sort((a, b) => new Date(b.recorded_at).getTime() - new Date(a.recorded_at).getTime());

  return (
    <main style={{ fontFamily: "system-ui, sans-serif", padding: "3rem", maxWidth: 1100 }}>
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

      {!loading && !error && events.length === 0 && <p>No events yet.</p>}

      {!loading && !error && events.length > 0 && (
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
              <th style={headStyle}>event_type</th>
              <th style={headStyle}>client_id</th>
              <th style={headStyle}>pipeline</th>
              <th style={headStyle}>payload</th>
            </tr>
          </thead>
          <tbody>
            {events.map((ev) => (
              <tr key={ev.event_id}>
                <td style={{ ...cellStyle, whiteSpace: "nowrap" }}>{fmtDate(ev.recorded_at)}</td>
                <td style={cellStyle}>{ev.event_type}</td>
                <td style={cellStyle}>{ev.client_id ?? "—"}</td>
                <td style={cellStyle}>{ev.pipeline ?? "—"}</td>
                <td
                  style={{
                    ...cellStyle,
                    fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
                    whiteSpace: "nowrap",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    maxWidth: 420,
                  }}
                  title={JSON.stringify(ev.payload ?? {}, null, 2)}
                >
                  {payloadPreview(ev.payload)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}
