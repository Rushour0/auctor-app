// Single source of truth for the operator console's network layer + backend types.
//
// Every page (Conversations, Crons, Posts, Metrics) talks to the FastAPI
// service through the typed `api` object below. The Vite dev proxy forwards
// /api to the service on :8000, and the session cookie is httponly +
// same-origin, so `credentials: 'include'` is all that's needed to carry it.
//
// ---------------------------------------------------------------------------
// Endpoint contract (with units B-E). If a backend path differs, ONLY this
// file changes — pages import `api`, never raw paths.
//
//   GET  /api/auth/me                -> Me
//   POST /api/auth/logout            -> (session cleared)
//   GET  /api/workflows/events       -> EventItem[]      ?limit&workspace_id
//   GET  /api/workflows/triggers     -> TriggerItem[]    ?limit&workspace_id
//   POST /api/workflows/triggers/ack -> ack a trigger     {workspace_id,trigger_id,status}
//   GET  /api/workflows/posts        -> PostItem[]       ?limit&workspace_id
//   GET  /api/metrics                -> Metrics          ?workspace_id&platform
// ---------------------------------------------------------------------------

import { getWorkspaceId } from '../auth/api';

/** Thrown by the fetch helpers when the backend answers 401 (unauthenticated). */
export class AuthError extends Error {
  constructor(message = 'Unauthorized') {
    super(message);
    this.name = 'AuthError';
  }
}

/**
 * Typed GET. Builds a query string from `params` (skipping undefined values),
 * carries the session cookie, and decodes the JSON body.
 *
 * @throws AuthError on 401, Error(text) on any other non-2xx.
 */
export async function jget<T>(
  path: string,
  params?: Record<string, string | number | undefined>,
): Promise<T> {
  let url = path;
  if (params) {
    const qs = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined) qs.set(key, String(value));
    }
    const s = qs.toString();
    if (s) url = `${path}?${s}`;
  }
  const res = await fetch(url, { credentials: 'include' });
  if (res.status === 401) throw new AuthError();
  if (!res.ok) throw new Error((await res.text()) || res.statusText);
  return res.json() as Promise<T>;
}

/**
 * Typed POST. Sends `body` as JSON when provided (otherwise an empty POST),
 * carries the session cookie, and decodes the JSON body.
 *
 * @throws AuthError on 401, Error(text) on any other non-2xx.
 */
export async function jpost<T>(path: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method: 'POST', credentials: 'include' };
  if (body !== undefined) {
    init.headers = { 'Content-Type': 'application/json' };
    init.body = JSON.stringify(body);
  }
  const res = await fetch(path, init);
  if (res.status === 401) throw new AuthError();
  if (!res.ok) throw new Error((await res.text()) || res.statusText);
  return res.json() as Promise<T>;
}

// ---------------------------------------------------------------------------
// Backend-shape types — mirror the FastAPI response documents EXACTLY
// (snake_case fields, StrEnum-style status strings). Do not rename fields.
// ---------------------------------------------------------------------------

/** The logged-in GitHub operator, as returned by GET /api/auth/me. */
export interface Me {
  login: string;
  gh_id: number;
}

/** A scheduled content-loop trigger row from workflow_triggers. */
export interface TriggerItem {
  workspace_id: string;
  fleet_id: string;
  client_id: string;
  pipeline: 'content_loop';
  trigger_id: string;
  trigger_type: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  scheduled_for: string;
  next_content_check_at: string;
  platform?: 'x' | 'linkedin';
  created_at: string;
  updated_at?: string;
}

/** Per-platform publish outcome inside a PostItem.platform_status map. */
export interface PlatformStatus {
  status: string;
  published_at?: string;
  provider_post_id?: string;
  error?: string;
}

/** A published/attempted content post from content_posts. */
export interface PostItem {
  post_id: string;
  client_id: string;
  pipeline: string;
  status: string;
  /** Per-platform status — x and linkedin move independently, never a boolean. */
  platform_status: Partial<Record<'x' | 'linkedin', PlatformStatus>>;
  provider_responses?: Record<string, unknown>;
  created_at: string;
  updated_at?: string;
}

/**
 * A fleet_events row (the Conversations feed). Includes the agent-run fields
 * (run_id/agent/stage/outcome/cost_usd/duration_ms/model/provider) so a single
 * agent's work is traceable end to end, not just the bare event_type.
 */
export interface EventItem {
  event_id: string;
  workspace_id: string;
  fleet_id: string;
  event_type: string;
  client_id?: string | null;
  pipeline?: string | null;
  run_id?: string | null;
  stage_run_id?: string | null;
  parent_event_id?: string | null;
  agent?: string | null;
  stage?: string | null;
  outcome?: string | null;
  attempt?: number;
  duration_ms?: number | null;
  input_tokens?: number;
  output_tokens?: number;
  cached_tokens?: number;
  cost_usd?: number;
  model?: string | null;
  provider?: string | null;
  payload: Record<string, unknown>;
  recorded_at: string;
  idempotency_key: string;
}

// ---------------------------------------------------------------------------
// Conversations — the real chat-thread contract (docs/08-conversation-and-
// message-contract.md), backed by service/app/conversations.py's
// summarize_event + routers/conversations.py's list/detail/SSE-stream
// endpoints. This is a DIFFERENT, richer surface than EventItem/api.events()
// above (which reads the flat WorkflowEvent log) — one fleet run == one
// conversation thread here, with the 8 contract message types.
// ---------------------------------------------------------------------------

/** The 8 message types the whole conversation contract is built on — do not
 * add a 9th without updating service/app/conversations.py's EVENT_MESSAGE_MAP. */
export type MessageType =
  | 'progress'
  | 'run_completed'
  | 'run_failed'
  | 'approval_request'
  | 'artifact_ready'
  | 'clarification'
  | 'user_message'
  | 'assistant_message';

/** One render-ready message, as produced by summarize_event / streamed via SSE. */
export interface ConversationMessage {
  id: string;
  message_type: MessageType;
  role: 'user' | 'assistant';
  text: string;
  event_type: string;
  client_id: string | null;
  pipeline: string | null;
  payload: Record<string, unknown>;
  recorded_at: string | null;
}

/** One row in the conversation list — a fleet run summary. */
export interface ConversationSummary {
  fleet_id: string;
  workspace_id: string | null;
  status: string | null;
  request: string | null;
  created_at: string | null;
  updated_at: string | null;
  message_count: number;
  last_message: ConversationMessage | null;
}

export interface ConversationDetail {
  fleet: Record<string, unknown>;
  messages: ConversationMessage[];
  message_count: number;
}

/** GET /api/conversations — list fleet-run threads, newest-first. */
export async function listConversations(workspace_id: string): Promise<ConversationSummary[]> {
  const body = await jget<{ conversations: ConversationSummary[] }>('/api/conversations', {
    workspace_id,
  });
  return body.conversations;
}

/** GET /api/conversations/:fleet_id — one thread's full message history. */
export function getConversation(fleet_id: string): Promise<ConversationDetail> {
  return jget<ConversationDetail>(`/api/conversations/${encodeURIComponent(fleet_id)}`);
}

/**
 * Open a live SSE stream of new messages for one conversation, resuming from
 * `after` (an ISO recorded_at cursor — pass the last message's timestamp to
 * avoid replaying history). Returns the EventSource; caller owns .close().
 * Every one of the 8 message types is dispatched as its own named SSE event
 * (see conversations.py's to_sse), so `onMessage` is wired to all 8 rather
 * than relying on the generic 'message' event, which SSE only fires for
 * unnamed frames.
 */
export function streamConversation(
  fleet_id: string,
  after: string | undefined,
  onMessage: (message: ConversationMessage) => void,
): EventSource {
  const qs = after ? `?after=${encodeURIComponent(after)}` : '';
  const source = new EventSource(
    `/api/conversations/${encodeURIComponent(fleet_id)}/events${qs}`,
    { withCredentials: true },
  );
  const messageTypes: MessageType[] = [
    'progress',
    'run_completed',
    'run_failed',
    'approval_request',
    'artifact_ready',
    'clarification',
    'user_message',
    'assistant_message',
  ];
  for (const type of messageTypes) {
    source.addEventListener(type, (event) => {
      onMessage(JSON.parse((event as MessageEvent).data));
    });
  }
  return source;
}

/** POST /api/content-jobs — the "action button turns into a prompt" primitive:
 * research + draft a new post for this client/fleet from a topic, appending
 * new messages to that fleet's conversation (visible live via the SSE stream
 * above). Stops at awaiting_approval — never publishes on its own. */
export async function startContentJob(
  workspace_id: string,
  fleet_id: string,
  client_id: string,
  topic: string,
): Promise<{ run_id: string; draft_id: string; approval_id: string; status: string; draft: string }> {
  const res = await fetch('/api/content-jobs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ workspace_id, fleet_id, client_id, topic }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

/** POST /api/content-jobs/approvals/:id/approve — the one action a human, not
 * a button-triggered prompt, should take: approve + publish an awaiting draft. */
export async function approveContentJob(
  workspace_id: string,
  approval_id: string,
): Promise<{ post_id: string; status: string; post_url: string }> {
  const res = await fetch(
    `/api/content-jobs/approvals/${encodeURIComponent(approval_id)}/approve?workspace_id=${encodeURIComponent(workspace_id)}`,
    { method: 'POST' },
  );
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

/** One day's roll-up in the metrics timeline. */
export interface DailyBucket {
  date: string;
  count: number;
  failed?: number;
}

/** Aggregated console metrics + COGS, as returned by GET /api/metrics. */
export interface Metrics {
  counts: Record<string, number>;
  cost: {
    total_usd: number;
    avg_per_run_usd: number;
    avg_per_post_usd: number;
    by_status_usd: Record<string, number>;
    failed_usd: number;
    usd_to_inr: number;
  };
  by_status: Record<string, number>;
  timeline: DailyBucket[];
  top_pipelines: {
    client_id: string;
    pipeline: string;
    posts: number;
    cost_usd: number;
  }[];
  failure_reasons: { reason: string; count: number }[];
  available_platforms: ('x' | 'linkedin')[];
}

/** One post idea from the public, no-signup demo — always grounded in a real source_url. */
export interface DemoSuggestion {
  post_type: string;
  topic: string;
  draft: string;
  source_url: string;
}

export interface DemoSuggestResult {
  suggestions: DemoSuggestion[];
  sources: string[];
}

/**
 * POST /api/demo/suggest — the one unauthenticated route. Unlike jpost, this reads
 * the FastAPI `{"detail": "..."}` error body and throws that clean message (rate-limit
 * text, "no signal found", etc.) instead of the raw JSON string.
 */
export async function demoSuggest(
  body: { linkedin_url?: string; twitter_handle?: string },
): Promise<DemoSuggestResult> {
  const res = await fetch('/api/demo/suggest', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let message = res.statusText;
    try {
      const errBody = await res.json();
      if (typeof errBody?.detail === 'string') message = errBody.detail;
    } catch {
      // non-JSON error body — fall back to statusText already set above
    }
    throw new Error(message);
  }
  return res.json() as Promise<DemoSuggestResult>;
}

// ---------------------------------------------------------------------------
// Typed client. The one object pages import to reach the backend.
// ---------------------------------------------------------------------------

export const api = {
  /** Current GitHub operator from the session cookie. */
  me: () => jget<Me>('/api/auth/me'),
  /** Clear the server session. */
  logout: () => jpost('/api/auth/logout'),
  /** Conversations feed — recent fleet_events, newest first, scoped to the
   * operator's own workspace (see auth/api.ts's getWorkspaceId). */
  events: (limit = 100) =>
    jget<EventItem[]>('/api/workflows/events', { limit, workspace_id: getWorkspaceId() }),
  /** Crons page — scheduled content-loop triggers, scoped to the operator's workspace. */
  triggers: (limit = 100) =>
    jget<TriggerItem[]>('/api/workflows/triggers', { limit, workspace_id: getWorkspaceId() }),
  /** Ack a trigger, moving it to running/completed/failed. */
  ackTrigger: (
    workspace_id: string,
    trigger_id: string,
    status: 'running' | 'completed' | 'failed',
  ) =>
    jpost('/api/workflows/triggers/ack', { workspace_id, trigger_id, status }),
  /** Posts page — published/attempted content posts, scoped to the operator's workspace. */
  posts: (limit = 100) =>
    jget<PostItem[]>('/api/workflows/posts', { limit, workspace_id: getWorkspaceId() }),
  /** Metrics page — aggregated counts + COGS, required workspace scope + optional platform. */
  metrics: (platform?: 'x' | 'linkedin') =>
    jget<Metrics>(
      '/api/metrics',
      platform ? { workspace_id: getWorkspaceId(), platform } : { workspace_id: getWorkspaceId() },
    ),
};
