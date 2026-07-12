// Renders a suggested draft as an actual X or LinkedIn post card — not a generic
// box — so the /try demo shows what shipping would actually look like. Borrows the
// real platform interaction-icon shapes (reply/repost/like/share for X;
// like/comment/repost/send for LinkedIn) but skins them in the app's own neutral
// palette rather than X blue / LinkedIn blue, same anti-slop rule
// auctor-landing/src/components/TweetCard.tsx already follows.
//
// Deliberately shows NO engagement counts (no "1.2K likes") — inventing social
// proof for a draft that hasn't shipped yet would be exactly the fabrication this
// product's whole positioning is built against (see policy.md ANTI-FABRICATION).
// The one real, non-fabricated piece of provenance is the "source" link below the
// card, always present, always the real finding the draft was grounded in.

import type React from "react";

type Platform = "x" | "linkedin";

function Icon({ d, size = 16 }: { d: string; size?: number }): React.JSX.Element {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path d={d} stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

const ICONS = {
  reply: "M2 4.5A1.5 1.5 0 0 1 3.5 3h9A1.5 1.5 0 0 1 14 4.5v5A1.5 1.5 0 0 1 12.5 11H7l-3 3v-3H3.5A1.5 1.5 0 0 1 2 9.5z",
  repost: "M4 4.5h6.5a1.5 1.5 0 0 1 1.5 1.5v3M6 2.5 4 4.5l2 2M12 11.5H5.5A1.5 1.5 0 0 1 4 10V7M10 13.5l2-2-2-2",
  heart: "M8 13.2s-5.2-3.1-5.2-6.9a2.9 2.9 0 0 1 5.2-1.8 2.9 2.9 0 0 1 5.2 1.8c0 3.8-5.2 6.9-5.2 6.9Z",
  share: "M8 2v7.5M5 4.5 8 2l3 2.5M3 9v3a1.5 1.5 0 0 0 1.5 1.5h7A1.5 1.5 0 0 0 13 12V9",
  comment: "M2 3.5A1.5 1.5 0 0 1 3.5 2h9A1.5 1.5 0 0 1 14 3.5v6A1.5 1.5 0 0 1 12.5 11H8l-3.5 3v-3H3.5A1.5 1.5 0 0 1 2 9.5z",
  send: "M2 8l11-5.5L9 14l-1.8-4.7L2 8z",
};

const PLATFORM_META: Record<
  Platform,
  { label: string; accent: string; icons: (keyof typeof ICONS)[] }
> = {
  x: { label: "X", accent: "#0f172a", icons: ["reply", "repost", "heart", "share"] },
  linkedin: { label: "LinkedIn", accent: "#1d4ed8", icons: ["heart", "comment", "repost", "send"] },
};

export function PostCard({
  platform,
  handle,
  draft,
  postType,
}: {
  platform: Platform;
  handle: string;
  draft: string;
  postType: string;
}): React.JSX.Element {
  const meta = PLATFORM_META[platform];
  const initial = handle.replace(/^@/, "").trim().charAt(0).toUpperCase() || "?";

  return (
    <div style={{ border: "1px solid #e5e7eb", borderRadius: 12, background: "#fff" }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          padding: "8px 16px",
          borderBottom: "1px solid #f3f4f6",
          fontSize: 11,
          color: "#6b7280",
          textTransform: "uppercase",
          letterSpacing: "0.05em",
        }}
      >
        <span style={{ color: meta.accent, fontWeight: 700 }}>{meta.label}</span>
        <span>· suggested {postType} draft</span>
      </div>

      <div style={{ display: "flex", alignItems: "flex-start", gap: 12, padding: "14px 16px" }}>
        <span
          style={{
            display: "flex",
            height: 40,
            width: 40,
            flexShrink: 0,
            alignItems: "center",
            justifyContent: "center",
            borderRadius: "50%",
            border: `1px solid ${meta.accent}33`,
            background: `${meta.accent}14`,
            color: meta.accent,
            fontSize: 14,
            fontWeight: 700,
          }}
        >
          {initial}
        </span>
        <div style={{ display: "flex", flex: 1, minWidth: 0, flexDirection: "column" }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
            <span style={{ fontSize: 14, fontWeight: 600 }}>{handle || "you"}</span>
            <span style={{ fontSize: 13, color: "#9ca3af" }}>now · draft</span>
          </div>
          <p style={{ margin: "6px 0 0", fontSize: 15, lineHeight: 1.5 }}>{draft}</p>

          <div style={{ display: "flex", maxWidth: 260, justifyContent: "space-between", marginTop: 14, color: "#9ca3af" }}>
            {meta.icons.map((name) => (
              <span key={name} style={{ color: meta.accent }}>
                <Icon d={ICONS[name]} />
              </span>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
