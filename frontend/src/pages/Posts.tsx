import { useCallback } from "react";
import { api, type PostItem, type PlatformStatus } from "../api/client";
import { useFetch } from "../hooks/useFetch";

/**
 * Posts page (item F9).
 *
 * Reads content_posts via GET /api/workflows/posts and renders one card per
 * post. The load-bearing part is the per-platform status row: X and LinkedIn
 * move INDEPENDENTLY, so we iterate (['x','linkedin'] as const) and read
 * post.platform_status[p] for each. We never collapse the two platforms into a
 * single boolean — that would violate the published_post.platform_status
 * contract from the auctor domain pack. A platform with no entry in the map is
 * shown as 'not targeted'; a failed one surfaces its error text; a published
 * one surfaces published_at.
 */

/** The two publish targets, in fixed display order. */
const PLATFORMS = ["x", "linkedin"] as const;
type Platform = (typeof PLATFORMS)[number];

/** Human label for a platform key. */
const PLATFORM_LABEL: Record<Platform, string> = {
  x: "X",
  linkedin: "LinkedIn",
};

/** Format an ISO timestamp for display, tolerating null/undefined/garbage. */
function fmtDate(iso: string | undefined | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

/** Pick a pill background for a per-platform / overall status string. */
function statusColor(status: string): string {
  switch (status) {
    case "published":
      return "#1a7f37";
    case "failed":
    case "blocked":
      return "#b42318";
    case "pending":
    case "publishing":
    case "awaiting_approval":
      return "#9a6700";
    default:
      return "#57606a";
  }
}

/** One labeled per-platform pill: 'X: <status>' / 'LinkedIn: <status>'. */
function PlatformPill({
  platform,
  ps,
}: {
  platform: Platform;
  ps: PlatformStatus | undefined;
}) {
  const label = PLATFORM_LABEL[platform];

  // No entry in platform_status → this platform was never targeted for the post.
  if (!ps) {
    return (
      <span
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: "0.4rem",
          padding: "0.25rem 0.6rem",
          borderRadius: 999,
          fontSize: "0.8rem",
          color: "#57606a",
          background: "#f6f8fa",
          border: "1px solid #e2e2e2",
        }}
      >
        {label}: not targeted
      </span>
    );
  }

  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: "0.4rem",
        padding: "0.25rem 0.6rem",
        borderRadius: 999,
        fontSize: "0.8rem",
        color: "#fff",
        background: statusColor(ps.status),
      }}
    >
      <strong style={{ fontWeight: 600 }}>
        {label}: {ps.status}
      </strong>
      {ps.status === "published" && ps.published_at && (
        <span style={{ opacity: 0.85 }}>· {fmtDate(ps.published_at)}</span>
      )}
      {ps.status === "failed" && ps.error && (
        <span style={{ opacity: 0.9 }}>· {ps.error}</span>
      )}
    </span>
  );
}

/** A single content_posts card. */
function PostCard({ post }: { post: PostItem }) {
  return (
    <li
      style={{
        listStyle: "none",
        border: "1px solid #e2e2e2",
        borderRadius: 10,
        padding: "1rem 1.25rem",
        boxShadow: "0 1px 2px rgba(0,0,0,0.04)",
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "baseline",
          gap: "1rem",
          flexWrap: "wrap",
        }}
      >
        <code style={{ fontSize: "0.85rem", color: "#1f2328" }}>
          {post.post_id}
        </code>
        <span
          style={{
            padding: "0.2rem 0.55rem",
            borderRadius: 999,
            fontSize: "0.78rem",
            color: "#fff",
            background: statusColor(post.status),
          }}
        >
          {post.status}
        </span>
      </div>

      <div
        style={{
          marginTop: "0.5rem",
          fontSize: "0.82rem",
          color: "#57606a",
          display: "flex",
          gap: "1.25rem",
          flexWrap: "wrap",
        }}
      >
        <span>client: {post.client_id}</span>
        <span>pipeline: {post.pipeline}</span>
        <span>created: {fmtDate(post.created_at)}</span>
      </div>

      {/* Per-platform status row — x and linkedin honored independently. */}
      <div
        style={{
          marginTop: "0.75rem",
          display: "flex",
          gap: "0.5rem",
          flexWrap: "wrap",
        }}
      >
        {PLATFORMS.map((p) => (
          <PlatformPill key={p} platform={p} ps={post.platform_status[p]} />
        ))}
      </div>
    </li>
  );
}

export default function Posts() {
  const { data, loading, error, reload } = useFetch<PostItem[]>(
    useCallback(() => api.posts(100), []),
    [],
  );

  return (
    <section style={{ fontFamily: "system-ui, sans-serif", padding: "1.5rem" }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: "1rem",
        }}
      >
        <h2 style={{ margin: 0 }}>Posts</h2>
        <button
          type="button"
          onClick={() => reload()}
          disabled={loading}
          style={{
            padding: "0.4rem 0.9rem",
            fontFamily: "inherit",
            fontSize: "0.9rem",
            fontWeight: 600,
            color: "#1f2328",
            background: "#fff",
            border: "1px solid #d0d7de",
            borderRadius: 8,
            cursor: loading ? "default" : "pointer",
            opacity: loading ? 0.6 : 1,
          }}
        >
          Refresh
        </button>
      </div>

      {loading && <p style={{ color: "#57606a" }}>Loading posts…</p>}
      {error && !loading && (
        <p style={{ color: "#b42318" }}>Failed to load posts: {error}</p>
      )}
      {!loading && !error && data && data.length === 0 && (
        <p style={{ color: "#57606a" }}>No posts yet.</p>
      )}

      {!loading && !error && data && data.length > 0 && (
        <ul
          style={{
            margin: 0,
            padding: 0,
            display: "flex",
            flexDirection: "column",
            gap: "0.75rem",
          }}
        >
          {data.map((post) => (
            <PostCard key={post.post_id} post={post} />
          ))}
        </ul>
      )}
    </section>
  );
}
