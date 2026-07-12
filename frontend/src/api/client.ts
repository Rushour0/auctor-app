// Single source of truth for the operator console's network layer + backend types.
//
// Every page (Conversations, Crons, Posts, Metrics) talks to the FastAPI
// service through the typed `api` object below. The Vite dev proxy forwards
// /api to the service on :8000, and the session cookie is httponly +
// same-origin, so `credentials: 'include'` is all that's needed to carry it.
// No external deps.
//
// ---------------------------------------------------------------------------
// Endpoint contract (with units B-E). If a backend path differs, ONLY this
// file changes — pages import `api`, never raw paths.
//
//   GET  /api/auth/me                -> Me
//   POST /api/auth/logout            -> (session cleared)
//   GET  /api/workflows/events       -> EventItem[]      ?limit
//   GET  /api/workflows/triggers     -> TriggerItem[]    ?limit
//   POST /api/workflows/triggers/ack -> ack a trigger     {workspace_id,trigger_id,status}
//   GET  /api/workflows/posts        -> PostItem[]       ?limit
//   GET  /api/metrics                -> Metrics          ?platform
// ---------------------------------------------------------------------------

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

/** A fleet_events row (the Conversations feed). */
export interface EventItem {
  event_type: string;
  client_id: string;
  pipeline: string;
  payload: Record<string, unknown>;
  recorded_at: string;
  idempotency_key: string;
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

// ---------------------------------------------------------------------------
// Typed client. The one object pages import to reach the backend.
// ---------------------------------------------------------------------------

export const api = {
  /** Current GitHub operator from the session cookie. */
  me: () => jget<Me>('/api/auth/me'),
  /** Clear the server session. */
  logout: () => jpost('/api/auth/logout'),
  /** Conversations feed — recent fleet_events, newest first. */
  events: (limit = 100) =>
    jget<EventItem[]>('/api/workflows/events', { limit }),
  /** Crons page — scheduled content-loop triggers. */
  triggers: (limit = 100) =>
    jget<TriggerItem[]>('/api/workflows/triggers', { limit }),
  /** Ack a trigger, moving it to running/completed/failed. */
  ackTrigger: (
    workspace_id: string,
    trigger_id: string,
    status: 'running' | 'completed' | 'failed',
  ) =>
    jpost('/api/workflows/triggers/ack', { workspace_id, trigger_id, status }),
  /** Posts page — published/attempted content posts. */
  posts: (limit = 100) => jget<PostItem[]>('/api/workflows/posts', { limit }),
  /** Metrics page — aggregated counts + COGS, optionally scoped to a platform. */
  metrics: (platform?: 'x' | 'linkedin') =>
    jget<Metrics>('/api/metrics', platform ? { platform } : undefined),
};
