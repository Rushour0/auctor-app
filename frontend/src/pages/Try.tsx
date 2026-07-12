// Public, no-signup "suggest my posts" page — lives OUTSIDE RequireAuth (see App.tsx),
// the one route in this app that works with no login. Give a LinkedIn URL or an X
// handle, get back real, sourced post suggestions from POST /api/demo/suggest.
//
// Every suggestion shown here carries a source_url the operator can click through to
// verify — no suggestion is ever rendered without one, matching the backend's
// claim_sourcing discipline (service/app/demo.py drops any ungrounded suggestion
// before this page ever sees it).

import { useState } from "react";
import type React from "react";
import { demoSuggest, type DemoSuggestion } from "../api/client";
import { PostCard } from "../components/PostCard";

type State =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "done"; suggestions: DemoSuggestion[] };

// Which platform card to render the results as. X is Auctor's primary platform
// (per PRODUCT-SLICES.md's X-first pivot), so a submission with both handles still
// renders as X — LinkedIn only wins when it's the only handle given.
function cardPlatform(twitterHandle: string): "x" | "linkedin" {
  return twitterHandle.trim() ? "x" : "linkedin";
}

function cardHandle(platform: "x" | "linkedin", linkedinUrl: string, twitterHandle: string): string {
  if (platform === "x") {
    const h = twitterHandle.trim().replace(/^@/, "");
    return h ? `@${h}` : "you";
  }
  const slug = linkedinUrl.trim().split("/").filter(Boolean).pop();
  return slug || "you";
}

export default function Try() {
  const [linkedinUrl, setLinkedinUrl] = useState("");
  const [twitterHandle, setTwitterHandle] = useState("");
  const [state, setState] = useState<State>({ status: "idle" });
  const [resultMeta, setResultMeta] = useState({ platform: "x" as "x" | "linkedin", handle: "you" });

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!linkedinUrl.trim() && !twitterHandle.trim()) {
      setState({ status: "error", message: "Enter a LinkedIn URL or an X/Twitter handle." });
      return;
    }
    const platform = cardPlatform(twitterHandle);
    setResultMeta({ platform, handle: cardHandle(platform, linkedinUrl, twitterHandle) });
    setState({ status: "loading" });
    demoSuggest({
      linkedin_url: linkedinUrl.trim() || undefined,
      twitter_handle: twitterHandle.trim() || undefined,
    })
      .then((result) => setState({ status: "done", suggestions: result.suggestions }))
      .catch((err: unknown) =>
        setState({ status: "error", message: err instanceof Error ? err.message : String(err) }),
      );
  };

  const loading = state.status === "loading";

  return (
    <main
      style={{
        fontFamily: "system-ui, sans-serif",
        padding: "3rem 1.5rem",
        maxWidth: 640,
        margin: "0 auto",
      }}
    >
      <h1>What should you post next?</h1>
      <p style={{ color: "#6b7280" }}>
        No signup. Give us a LinkedIn profile or an X handle — we'll find your real, public
        activity and suggest a few posts, each linked back to the source we found it from.
      </p>

      <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
        <label style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
          <span style={{ fontSize: 13, color: "#6b7280" }}>LinkedIn profile URL</span>
          <input
            type="text"
            value={linkedinUrl}
            onChange={(e) => setLinkedinUrl(e.target.value)}
            placeholder="https://linkedin.com/in/yourname"
            disabled={loading}
            style={{ padding: "0.5rem 0.75rem", borderRadius: 6, border: "1px solid #d1d5db" }}
          />
        </label>
        <label style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
          <span style={{ fontSize: 13, color: "#6b7280" }}>X / Twitter handle</span>
          <input
            type="text"
            value={twitterHandle}
            onChange={(e) => setTwitterHandle(e.target.value)}
            placeholder="@yourname"
            disabled={loading}
            style={{ padding: "0.5rem 0.75rem", borderRadius: 6, border: "1px solid #d1d5db" }}
          />
        </label>
        <button
          type="submit"
          disabled={loading}
          style={{
            padding: "0.6rem 1rem",
            borderRadius: 6,
            border: "none",
            background: loading ? "#93c5fd" : "#2563eb",
            color: "#fff",
            fontWeight: 600,
            cursor: loading ? "default" : "pointer",
          }}
        >
          {loading ? "Looking…" : "Suggest my posts"}
        </button>
      </form>

      {state.status === "error" && (
        <p style={{ color: "#991b1b", marginTop: "1.5rem" }}>{state.message}</p>
      )}

      {state.status === "done" && (
        <div style={{ marginTop: "2rem", display: "flex", flexDirection: "column", gap: "1rem" }}>
          {state.suggestions.length === 0 && (
            <p style={{ color: "#6b7280" }}>No suggestions came back — try a different handle.</p>
          )}
          {state.suggestions.map((s, i) => (
            <div key={i} style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              <PostCard
                platform={resultMeta.platform}
                handle={resultMeta.handle}
                draft={s.draft}
                postType={s.post_type}
              />
              <a
                href={s.source_url}
                target="_blank"
                rel="noreferrer"
                style={{ fontSize: 12, color: "#6b7280", paddingLeft: 4 }}
              >
                source: {s.source_url}
              </a>
            </div>
          ))}
        </div>
      )}
    </main>
  );
}
