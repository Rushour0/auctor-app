// Conversations page — a real chat-thread UI over the docs/08 message contract,
// not a raw event log. One fleet run == one conversation (service/app/
// conversations.py's summarize_event + routers/conversations.py's list/detail/
// SSE-stream endpoints already implement the backend half of this; this file is
// purely the chat UI on top).
//
// Live updates: selecting a conversation opens a Server-Sent Events stream
// (streamConversation) that appends new messages as agents actually work —
// no polling, no manual refresh needed while a run is in flight.
//
// The user does NOT get a free-text prompt box. Per the product's own
// approval-gated design (nothing ships without a human), the only inputs are:
// (1) preset action buttons that turn into a real POST /api/content-jobs call
//     with a canned topic drawn from the real post_type taxonomy
//     (ship-announcement/hot-take/build-in-public/milestone, see
//     artifacts.md's post_brief.post_type enum) — never arbitrary user text
//     fed straight to a paid research+draft call;
// (2) an "Approve & publish" button on any approval_request message, the one
//     action a human — not a canned prompt — takes.

import { useEffect, useRef, useState } from "react";
import type React from "react";
import { getWorkspaceId } from "../auth/api";
import {
  approveContentJob,
  getConversation,
  listConversations,
  startContentJob,
  streamConversation,
  type ConversationMessage,
  type ConversationSummary,
} from "../api/client";

// Canned topics mapped to the real post_type taxonomy — clicking a button IS
// the "turns into a prompt" step; there is no free-text field.
const ACTIONS: { label: string; postType: string; topic: string }[] = [
  {
    label: "🚀 Ship announcement",
    postType: "ship-announcement",
    topic: "Announce a recent product update or release",
  },
  {
    label: "🔥 Hot take",
    postType: "hot-take",
    topic: "Share a contrarian or hot-take perspective on a trend in my space",
  },
  {
    label: "🏗️ Build in public",
    postType: "build-in-public",
    topic: "Share progress on what I'm building right now",
  },
  {
    label: "🏆 Milestone",
    postType: "milestone",
    topic: "Highlight a recent milestone or achievement",
  },
];

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString();
}

function lastClientId(messages: ConversationMessage[]): string | null {
  for (let i = messages.length - 1; i >= 0; i--) {
    if (messages[i].client_id) return messages[i].client_id;
  }
  return null;
}

const TYPE_STYLE: Record<string, { bg: string; fg: string; border: string }> = {
  progress: { bg: "#f3f4f6", fg: "#374151", border: "#e5e7eb" },
  user_message: { bg: "#2563eb", fg: "#fff", border: "#2563eb" },
  assistant_message: { bg: "#f3f4f6", fg: "#111827", border: "#e5e7eb" },
  approval_request: { bg: "#fef3c7", fg: "#92400e", border: "#fde68a" },
  artifact_ready: { bg: "#dcfce7", fg: "#166534", border: "#bbf7d0" },
  run_completed: { bg: "#dcfce7", fg: "#166534", border: "#bbf7d0" },
  run_failed: { bg: "#fee2e2", fg: "#991b1b", border: "#fecaca" },
  clarification: { bg: "#e0e7ff", fg: "#3730a3", border: "#c7d2fe" },
};

function MessageBubble({
  message,
  workspaceId,
  onApproved,
}: {
  message: ConversationMessage;
  workspaceId: string;
  onApproved: (text: string) => void;
}): React.JSX.Element {
  const style = TYPE_STYLE[message.message_type] ?? TYPE_STYLE.progress;
  const isUser = message.role === "user";
  const approvalId = (message.payload?.approval_id as string | undefined) ?? undefined;
  const [busy, setBusy] = useState(false);
  const [approved, setApproved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const approve = () => {
    if (!approvalId) return;
    setBusy(true);
    setError(null);
    approveContentJob(workspaceId, approvalId)
      .then((result) => {
        setApproved(true);
        onApproved(`Published: ${result.post_url}`);
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : String(err)))
      .finally(() => setBusy(false));
  };

  return (
    <div style={{ display: "flex", justifyContent: isUser ? "flex-end" : "flex-start", marginBottom: 10 }}>
      <div
        style={{
          maxWidth: "70%",
          padding: "10px 14px",
          borderRadius: 12,
          background: style.bg,
          color: style.fg,
          border: `1px solid ${style.border}`,
        }}
      >
        {message.message_type !== "assistant_message" && message.message_type !== "user_message" && (
          <div style={{ fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.04em", marginBottom: 4, opacity: 0.75 }}>
            {message.message_type.replace(/_/g, " ")}
          </div>
        )}
        <div style={{ whiteSpace: "pre-wrap", fontSize: 14, lineHeight: 1.5 }}>{message.text}</div>

        {message.message_type === "approval_request" && approvalId && !approved && (
          <div style={{ marginTop: 8 }}>
            <button
              type="button"
              onClick={approve}
              disabled={busy}
              style={{
                padding: "6px 12px",
                borderRadius: 6,
                border: "1px solid #92400e",
                background: busy ? "#fde68a" : "#fbbf24",
                color: "#78350f",
                fontWeight: 600,
                fontSize: 12,
                cursor: busy ? "default" : "pointer",
              }}
            >
              {busy ? "Publishing…" : "Approve & publish"}
            </button>
            {error && <div style={{ color: "#991b1b", fontSize: 12, marginTop: 4 }}>{error}</div>}
          </div>
        )}
        {approved && <div style={{ marginTop: 6, fontSize: 12, fontWeight: 600 }}>✓ Published</div>}

        <div style={{ fontSize: 10, opacity: 0.6, marginTop: 4 }}>{fmtDate(message.recorded_at)}</div>
      </div>
    </div>
  );
}

export default function Conversations() {
  const workspaceId = getWorkspaceId();
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [listLoading, setListLoading] = useState(true);
  const [listError, setListError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [messages, setMessages] = useState<ConversationMessage[]>([]);
  const [threadLoading, setThreadLoading] = useState(false);
  const [threadError, setThreadError] = useState<string | null>(null);
  const [actionBusy, setActionBusy] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const sourceRef = useRef<EventSource | null>(null);

  const loadConversations = () => {
    setListLoading(true);
    setListError(null);
    listConversations(workspaceId)
      .then((rows) => {
        setConversations(rows);
        setSelected((current) => current ?? rows[0]?.fleet_id ?? null);
      })
      .catch((err: unknown) => setListError(err instanceof Error ? err.message : String(err)))
      .finally(() => setListLoading(false));
  };

  useEffect(loadConversations, [workspaceId]);

  useEffect(() => {
    sourceRef.current?.close();
    sourceRef.current = null;
    if (!selected) {
      setMessages([]);
      return;
    }
    setThreadLoading(true);
    setThreadError(null);
    let cancelled = false;
    getConversation(selected)
      .then((detail) => {
        if (cancelled) return;
        setMessages(detail.messages);
        const after = detail.messages.at(-1)?.recorded_at ?? undefined;
        const source = streamConversation(selected, after, (message) => {
          setMessages((current) =>
            current.some((m) => m.id === message.id) ? current : [...current, message],
          );
        });
        sourceRef.current = source;
      })
      .catch((err: unknown) => {
        if (!cancelled) setThreadError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (!cancelled) setThreadLoading(false);
      });
    return () => {
      cancelled = true;
      sourceRef.current?.close();
      sourceRef.current = null;
    };
  }, [selected]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const clientId = lastClientId(messages);
  const fleetId = selected;

  const runAction = (action: (typeof ACTIONS)[number]) => {
    if (!fleetId || !clientId) return;
    setActionBusy(action.postType);
    setActionError(null);
    startContentJob(workspaceId, fleetId, clientId, action.topic)
      .then(() => {
        // The new run's events (research/draft/approval) stream in live via SSE —
        // no need to manually append or refetch here.
      })
      .catch((err: unknown) => setActionError(err instanceof Error ? err.message : String(err)))
      .finally(() => setActionBusy(null));
  };

  return (
    <main style={{ fontFamily: "system-ui, sans-serif", display: "flex", height: "calc(100vh - 65px)" }}>
      <aside
        style={{
          width: 300,
          flexShrink: 0,
          borderRight: "1px solid #e5e7eb",
          overflowY: "auto",
          padding: "1rem",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
          <h2 style={{ margin: 0, fontSize: 18 }}>Conversations</h2>
          <button
            type="button"
            onClick={loadConversations}
            disabled={listLoading}
            title="Refresh conversations"
            style={{
              padding: "5px 8px",
              borderRadius: 6,
              border: "1px solid #d1d5db",
              background: "#fff",
              color: "#374151",
              fontSize: 12,
              cursor: listLoading ? "default" : "pointer",
              opacity: listLoading ? 0.6 : 1,
            }}
          >
            ⟳ Refresh
          </button>
        </div>

        <a
          href="/onboarding"
          style={{
            display: "block",
            textAlign: "center",
            padding: "9px 12px",
            marginBottom: 14,
            borderRadius: 8,
            border: "1px solid #2563eb",
            background: "#2563eb",
            color: "#fff",
            fontSize: 13,
            fontWeight: 600,
            textDecoration: "none",
          }}
        >
          + New conversation
        </a>

        {listLoading && <p style={{ color: "#6b7280", fontSize: 13 }}>Loading…</p>}
        {listError && <p style={{ color: "#991b1b", fontSize: 13 }}>{listError}</p>}
        {!listLoading && !listError && conversations.length === 0 && (
          <p
            style={{
              color: "#6b7280",
              fontSize: 13,
              background: "#f9fafb",
              border: "1px solid #e5e7eb",
              borderRadius: 8,
              padding: "10px 12px",
            }}
          >
            No conversations yet. A conversation starts once a client is onboarded — use{" "}
            <span style={{ fontWeight: 600, color: "#2563eb" }}>+ New conversation</span> above to
            begin one.
          </p>
        )}
        {conversations.map((c) => (
          <button
            key={c.fleet_id}
            type="button"
            onClick={() => setSelected(c.fleet_id)}
            style={{
              display: "block",
              width: "100%",
              textAlign: "left",
              padding: "10px 12px",
              marginBottom: 6,
              borderRadius: 8,
              border: "1px solid " + (c.fleet_id === selected ? "#2563eb" : "#e5e7eb"),
              background: c.fleet_id === selected ? "#eff6ff" : "#fff",
              cursor: "pointer",
            }}
          >
            <div style={{ fontSize: 12, fontFamily: "monospace", color: "#6b7280" }}>{c.fleet_id}</div>
            <div style={{ fontSize: 13, fontWeight: 600, margin: "2px 0" }}>{c.status ?? "—"}</div>
            {c.last_message && (
              <div style={{ fontSize: 12, color: "#4b5563", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {c.last_message.text}
              </div>
            )}
            <div style={{ fontSize: 11, color: "#9ca3af", marginTop: 2 }}>{fmtDate(c.updated_at)}</div>
          </button>
        ))}
      </aside>

      <section style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
        {!selected && (
          <div style={{ margin: "auto", color: "#6b7280" }}>Select a conversation to view its thread.</div>
        )}

        {selected && (
          <>
            <div style={{ flex: 1, overflowY: "auto", padding: "1.5rem" }}>
              {threadLoading && <p style={{ color: "#6b7280" }}>Loading thread…</p>}
              {threadError && <p style={{ color: "#991b1b" }}>{threadError}</p>}
              {!threadLoading && !threadError && messages.length === 0 && (
                <p style={{ color: "#6b7280" }}>No messages yet.</p>
              )}
              {messages.map((m) => (
                <MessageBubble
                  key={m.id}
                  message={m}
                  workspaceId={workspaceId}
                  onApproved={(text) =>
                    setMessages((current) => [
                      ...current,
                      {
                        id: `local-${Date.now()}`,
                        message_type: "run_completed",
                        role: "assistant",
                        text,
                        event_type: "local.published",
                        client_id: clientId,
                        pipeline: "content_loop",
                        payload: {},
                        recorded_at: new Date().toISOString(),
                      },
                    ])
                  }
                />
              ))}
              <div ref={bottomRef} />
            </div>

            <div style={{ borderTop: "1px solid #e5e7eb", padding: "0.75rem 1.5rem" }}>
              {actionError && <p style={{ color: "#991b1b", fontSize: 12, margin: "0 0 6px" }}>{actionError}</p>}
              {!clientId && (
                <p style={{ color: "#9ca3af", fontSize: 12, margin: "0 0 6px" }}>
                  No client identified in this thread yet — actions unlock once research starts.
                </p>
              )}
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                {ACTIONS.map((action) => (
                  <button
                    key={action.postType}
                    type="button"
                    onClick={() => runAction(action)}
                    disabled={!clientId || actionBusy !== null}
                    style={{
                      padding: "8px 14px",
                      borderRadius: 999,
                      border: "1px solid #d1d5db",
                      background: actionBusy === action.postType ? "#f3f4f6" : "#fff",
                      cursor: !clientId || actionBusy !== null ? "default" : "pointer",
                      fontSize: 13,
                    }}
                  >
                    {actionBusy === action.postType ? "Working…" : action.label}
                  </button>
                ))}
              </div>
            </div>
          </>
        )}
      </section>
    </main>
  );
}
