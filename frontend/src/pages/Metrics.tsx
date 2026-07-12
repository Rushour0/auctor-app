import { useState } from "react";
import { api, type Metrics as MetricsPayload } from "../api/client";
import { useFetch } from "../hooks/useFetch";

/**
 * Metrics page (item F10) — GET /api/metrics with an optional platform
 * drill-down.
 *
 * Mirrors the ludexel COGS dashboard pattern: one polling round-trip returns a
 * pre-aggregated payload and the page renders it as inline-styled blocks with
 * no chart library. The headline surfaces `cost.failed_usd` prominently — the
 * dollars burned on runs that never shipped a post — because that is the number
 * the deck quotes as wasted COGS.
 *
 * The chip group drives `platform` state; passing `undefined` keeps the
 * cross-platform (common) view, and only the platforms actually present in
 * `available_platforms` get a chip so unavailable engines are hidden. Per FLEET
 * ISOLATION the backend already scopes which platforms the operator can see.
 */

type Platform = "all" | "x" | "linkedin";

// ---------------------------------------------------------------------------
// Pure, null-safe formatters. Everything unknown renders as an em dash so a
// fresh workspace (no runs, no cost) never shows NaN or "$undefined".
// ---------------------------------------------------------------------------

const DASH = "—";

/** USD money. Small COGS values keep more decimals so sub-cent costs read. */
function fmtUsd(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return DASH;
  const digits = Math.abs(n) < 1 ? 4 : 2;
  return `$${n.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: digits,
  })}`;
}

/** Convert a USD figure to ₹ via the payload's usd_to_inr rate. */
function fmtInr(usd: number | null | undefined, rate: number | null | undefined): string {
  if (usd === null || usd === undefined || Number.isNaN(usd)) return DASH;
  if (rate === null || rate === undefined || Number.isNaN(rate)) return DASH;
  return `₹${(usd * rate).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

/** Integer count with thousands separators. */
function fmtNum(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return DASH;
  return n.toLocaleString();
}

/** ISO date -> short local date (used for timeline tooltips). */
function fmtDate(s: string | null | undefined): string {
  if (!s) return DASH;
  const d = new Date(s);
  if (Number.isNaN(d.getTime())) return s;
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

// ---------------------------------------------------------------------------
// Status color map — shared by the stacked proportion bar and its legend.
// Unknown statuses fall back to a neutral gray so the bar never breaks.
// ---------------------------------------------------------------------------

const STATUS_COLORS: Record<string, string> = {
  draft: "#9aa0a6",
  approved: "#f5a623",
  published: "#2e7d32",
  failed: "#c0392b",
};

function statusColor(status: string): string {
  return STATUS_COLORS[status] ?? "#c9ccd1";
}

// ---------------------------------------------------------------------------
// Shared inline style fragments (this scaffold has no CSS system yet, so the
// four pages are inline-styled; these mirror Login.tsx's palette).
// ---------------------------------------------------------------------------

const CARD: React.CSSProperties = {
  border: "1px solid #e2e2e2",
  borderRadius: 12,
  padding: "1.25rem 1.5rem",
  background: "#fff",
  boxShadow: "0 1px 3px rgba(0,0,0,0.06)",
};

const SECTION_TITLE: React.CSSProperties = {
  fontSize: "0.8rem",
  fontWeight: 700,
  textTransform: "uppercase",
  letterSpacing: "0.04em",
  color: "#666",
  margin: "0 0 0.85rem",
};

const MUTED: React.CSSProperties = { color: "#666" };

function StatTile({
  label,
  value,
  accent,
  sub,
}: {
  label: string;
  value: string;
  accent?: string;
  sub?: string;
}) {
  return (
    <div
      style={{
        flex: "1 1 160px",
        minWidth: 150,
        border: "1px solid #e2e2e2",
        borderRadius: 10,
        padding: "0.9rem 1rem",
        background: "#fafafa",
      }}
    >
      <div style={{ fontSize: "0.72rem", fontWeight: 600, ...MUTED, textTransform: "uppercase", letterSpacing: "0.03em" }}>
        {label}
      </div>
      <div
        style={{
          fontSize: "1.5rem",
          fontWeight: 700,
          marginTop: "0.3rem",
          color: accent ?? "#1f2328",
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {value}
      </div>
      {sub && <div style={{ fontSize: "0.72rem", marginTop: "0.2rem", ...MUTED }}>{sub}</div>}
    </div>
  );
}

// ---------------------------------------------------------------------------

const PLATFORM_LABELS: Record<Exclude<Platform, "all">, string> = {
  x: "X",
  linkedin: "LinkedIn",
};

export default function Metrics() {
  const [platform, setPlatform] = useState<Platform>("all");
  const { data, loading, error } = useFetch<MetricsPayload>(
    () => api.metrics(platform === "all" ? undefined : platform),
    [platform],
  );

  // Chip group — always offer "All"; only surface X / LinkedIn when the
  // backend advertises them so unavailable platforms stay hidden.
  const available = data?.available_platforms ?? [];
  const chips: Platform[] = ["all", ...available.filter((p) => p === "x" || p === "linkedin")];

  return (
    <main style={{ fontFamily: "system-ui, sans-serif", padding: "1.5rem 2rem", maxWidth: 1080, margin: "0 auto" }}>
      <div style={{ display: "flex", alignItems: "center", gap: "1rem", flexWrap: "wrap" }}>
        <h2 style={{ fontSize: "1.5rem", margin: 0 }}>Metrics</h2>
        <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap" }}>
          {chips.map((p) => {
            const active = platform === p;
            const label = p === "all" ? "All" : PLATFORM_LABELS[p];
            return (
              <button
                key={p}
                type="button"
                onClick={() => setPlatform(p)}
                style={{
                  padding: "0.35rem 0.85rem",
                  fontFamily: "inherit",
                  fontSize: "0.85rem",
                  fontWeight: 600,
                  borderRadius: 999,
                  cursor: "pointer",
                  border: active ? "1px solid #1f2328" : "1px solid #e2e2e2",
                  background: active ? "#1f2328" : "#fff",
                  color: active ? "#fff" : "#1f2328",
                }}
              >
                {label}
              </button>
            );
          })}
        </div>
      </div>

      {loading && !data && <p style={{ ...MUTED, marginTop: "2rem" }}>Loading metrics…</p>}
      {error && (
        <p style={{ color: "#c0392b", marginTop: "2rem" }}>Failed to load metrics: {error}</p>
      )}

      {data && <MetricsBody data={data} />}
    </main>
  );
}

// ---------------------------------------------------------------------------

function MetricsBody({ data }: { data: MetricsPayload }) {
  const { cost, counts, by_status, timeline, top_pipelines, failure_reasons } = data;

  const countEntries = Object.entries(counts ?? {});
  const statusEntries = Object.entries(by_status ?? {}).filter(([, v]) => v > 0);
  const statusTotal = statusEntries.reduce((s, [, v]) => s + v, 0);
  const timelineMax = Math.max(1, ...(timeline ?? []).map((b) => b.count));

  const nothing =
    countEntries.length === 0 &&
    statusEntries.length === 0 &&
    (timeline ?? []).length === 0 &&
    (cost?.total_usd ?? 0) === 0;

  if (nothing) {
    return (
      <p style={{ ...MUTED, marginTop: "2rem" }}>
        No activity yet for this view. Metrics appear once fleets start running content loops.
      </p>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "1.5rem", marginTop: "1.5rem" }}>
      {/* (1) COGS headline — failed_usd surfaced prominently. */}
      <section style={CARD}>
        <h3 style={SECTION_TITLE}>Cost of goods (COGS)</h3>
        <div style={{ display: "flex", flexWrap: "wrap", gap: "0.75rem" }}>
          <StatTile label="Total spend" value={fmtUsd(cost?.total_usd)} sub={fmtInr(cost?.total_usd, cost?.usd_to_inr)} />
          <StatTile label="Avg / run" value={fmtUsd(cost?.avg_per_run_usd)} />
          <StatTile label="Avg / post" value={fmtUsd(cost?.avg_per_post_usd)} />
          <StatTile
            label="Burned on failures"
            value={fmtUsd(cost?.failed_usd)}
            accent="#c0392b"
            sub={fmtInr(cost?.failed_usd, cost?.usd_to_inr)}
          />
        </div>
      </section>

      {/* (2) Counts. */}
      {countEntries.length > 0 && (
        <section style={CARD}>
          <h3 style={SECTION_TITLE}>Counts</h3>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "0.75rem" }}>
            {countEntries.map(([label, value]) => (
              <StatTile key={label} label={label.replace(/_/g, " ")} value={fmtNum(value)} />
            ))}
          </div>
        </section>
      )}

      {/* (3) Status breakdown — horizontal stacked proportion bar. */}
      {statusEntries.length > 0 && (
        <section style={CARD}>
          <h3 style={SECTION_TITLE}>Posts by status</h3>
          <div
            style={{
              display: "flex",
              width: "100%",
              height: 28,
              borderRadius: 6,
              overflow: "hidden",
              border: "1px solid #e2e2e2",
            }}
          >
            {statusEntries.map(([status, value]) => {
              const pct = (value / statusTotal) * 100;
              return (
                <div
                  key={status}
                  title={`${status}: ${fmtNum(value)} (${pct.toFixed(1)}%)`}
                  style={{ width: `${pct}%`, background: statusColor(status) }}
                />
              );
            })}
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "0.85rem", marginTop: "0.75rem" }}>
            {statusEntries.map(([status, value]) => (
              <div key={status} style={{ display: "flex", alignItems: "center", gap: "0.4rem", fontSize: "0.82rem" }}>
                <span
                  style={{ width: 10, height: 10, borderRadius: 2, background: statusColor(status), display: "inline-block" }}
                />
                <span style={{ textTransform: "capitalize" }}>{status}</span>
                <span style={MUTED}>{fmtNum(value)}</span>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* (4) Timeline — hand-rolled flexbox bars, red segment ∝ failed. */}
      {(timeline ?? []).length > 0 && (
        <section style={CARD}>
          <h3 style={SECTION_TITLE}>Activity ({timeline.length}-day)</h3>
          <div style={{ display: "flex", alignItems: "flex-end", gap: 3, height: 120 }}>
            {timeline.map((b) => {
              const failed = b.failed ?? 0;
              const barH = (b.count / timelineMax) * 100; // % of the 120px track
              const failedFrac = b.count > 0 ? failed / b.count : 0;
              return (
                <div
                  key={b.date}
                  title={`${fmtDate(b.date)}: ${fmtNum(b.count)} posts, ${fmtNum(failed)} failed`}
                  style={{
                    flex: "1 1 0",
                    minWidth: 4,
                    height: `${barH}%`,
                    minHeight: b.count > 0 ? 2 : 0,
                    display: "flex",
                    flexDirection: "column",
                    justifyContent: "flex-end",
                    background: "#2e7d32",
                    borderRadius: "2px 2px 0 0",
                    overflow: "hidden",
                  }}
                >
                  {failed > 0 && <div style={{ height: `${failedFrac * 100}%`, background: "#c0392b" }} />}
                </div>
              );
            })}
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", marginTop: "0.5rem", fontSize: "0.72rem", ...MUTED }}>
            <span>{fmtDate(timeline[0]?.date)}</span>
            <span>{fmtDate(timeline[timeline.length - 1]?.date)}</span>
          </div>
        </section>
      )}

      {/* (5) Top pipelines table + failure reasons list. */}
      <div style={{ display: "flex", gap: "1.5rem", flexWrap: "wrap", alignItems: "flex-start" }}>
        {(top_pipelines ?? []).length > 0 && (
          <section style={{ ...CARD, flex: "1 1 380px", minWidth: 300 }}>
            <h3 style={SECTION_TITLE}>Top pipelines by spend</h3>
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.85rem" }}>
                <thead>
                  <tr style={{ textAlign: "left", color: "#666" }}>
                    <th style={{ padding: "0.4rem 0.5rem", fontWeight: 600 }}>Client</th>
                    <th style={{ padding: "0.4rem 0.5rem", fontWeight: 600 }}>Pipeline</th>
                    <th style={{ padding: "0.4rem 0.5rem", fontWeight: 600, textAlign: "right" }}>Posts</th>
                    <th style={{ padding: "0.4rem 0.5rem", fontWeight: 600, textAlign: "right" }}>Cost</th>
                  </tr>
                </thead>
                <tbody>
                  {top_pipelines.map((row, i) => (
                    <tr key={`${row.client_id}-${row.pipeline}-${i}`} style={{ borderTop: "1px solid #f0f0f0" }}>
                      <td style={{ padding: "0.4rem 0.5rem", fontFamily: "ui-monospace, monospace" }}>{row.client_id}</td>
                      <td style={{ padding: "0.4rem 0.5rem" }}>{row.pipeline}</td>
                      <td style={{ padding: "0.4rem 0.5rem", textAlign: "right", fontVariantNumeric: "tabular-nums" }}>
                        {fmtNum(row.posts)}
                      </td>
                      <td style={{ padding: "0.4rem 0.5rem", textAlign: "right", fontVariantNumeric: "tabular-nums" }}>
                        {fmtUsd(row.cost_usd)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}

        {(failure_reasons ?? []).length > 0 && (
          <section style={{ ...CARD, flex: "1 1 260px", minWidth: 240 }}>
            <h3 style={SECTION_TITLE}>Failure reasons</h3>
            <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: "0.5rem" }}>
              {failure_reasons.map((f, i) => (
                <li
                  key={`${f.reason}-${i}`}
                  style={{ display: "flex", justifyContent: "space-between", gap: "1rem", fontSize: "0.85rem" }}
                >
                  <span style={{ color: "#1f2328" }}>{f.reason}</span>
                  <span
                    style={{
                      fontVariantNumeric: "tabular-nums",
                      fontWeight: 600,
                      color: "#c0392b",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {fmtNum(f.count)}
                  </span>
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>
    </div>
  );
}
