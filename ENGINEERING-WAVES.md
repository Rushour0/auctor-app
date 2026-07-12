# Auctor — engineering waves (implementation-level, complements PRODUCT-SLICES.md)

`PRODUCT-SLICES.md` is the product decomposition (user outcomes, acceptance criteria, metrics).
This doc is the engineering-implementation view: what actually gets built, in what wave, and the
concrete design for pieces that were still abstract ("a brief-local self-scheduling workaround").
Things noted **"later stage"** below are explicitly deferred — documented now, not built now.

## Wave 0 — domain pack (in progress now)

`.agent/agency.yaml`, `.agent/prompts/{manager.md, common/*.md}`, `.agent/prompts/domains/auctor/
{manager.md, policy.md, artifacts.md, specialists/*.md (12 files), evals/cases.json}`,
`.agent/tools/manifests/*.json`. Prompt/schema layer only — no running service yet. Being built now
via a one-agent-per-file workflow, styled against `~/hermes/microsites`' existing rigor (read-only
reference, nothing written there).

**Final role count: 15 agents**, confirmed — not counting the approval gate (a state, not an
agent) or a separate "repair agent" (repair re-invokes whichever specialist produced the failing
artifact, bounded by retry count, same pattern Microsite Factory uses — not its own role).

- Hermes (2): conversational manager, narrator.
- Fabri (13): the Fabri manager + 12 domain specialists — `researcher`, `brand_strategist`,
  `copywriter`, `builder`, `voice_qa` (shared verifier), `deployer` (site-build, 6); plus
  `metrics_researcher`, `trend_researcher`, `content_strategist`, `ghostwriter`, `publisher`,
  `engagement_analyst` (content-loop, 6).

## Wave 1 — `service/` + `frontend/` scaffolding (later stage)

Turn the Wave 0 prompt layer into a running FastAPI + Mongo backend and a React frontend, matching
`ludexel-app`'s two-image monorepo shape (already decided in the original architecture plan).
Docker images, Coolify wiring, and the CI workflow (`ci.yml` backend+frontend, `publish.yml`
push-to-main continuous deploy, no smoke gate) all land here. This is where `PRODUCT-SLICES.md`'s
Slice 1 (live voice-verified site from a LinkedIn URL) actually becomes real, running code.

## Wave 2 — the scheduler (later stage; concrete design, not yet built)

This is the piece that was still abstract as "a brief-local self-scheduling workaround" — now
concrete:

- **State-backed, not in-memory.** A `next_content_check_at` timestamp lives on every
  `ClientPipeline` document in Mongo. An in-process scheduler (APScheduler inside `service/`)
  wakes on a short interval (~15 min) and polls Mongo for any client with
  `content_loop_mode: active` and `next_content_check_at <= now`. Persisted state matters
  specifically because Coolify redeploys on every push to `main` (our CD setup) — an in-memory-only
  schedule would silently reset on every deploy; a Mongo-persisted timestamp survives it.
- **Two cadences, not one:**
  1. The generic weekly content cadence per client (`content_cadence_per_week` on
     `ClientPipeline`, already in the data model).
  2. A separate, faster poll cursor (`last_release_seen` per client) checking GitHub for a *new*
     release/version — when one appears, it triggers a same-day draft immediately rather than
     waiting for the weekly tick (the event-triggered vs. time-triggered distinction from the
     X-first pivot).
- This is a poll loop against persisted state, not a host crontab install. `policy.md` (Wave 0,
  in progress now) documents this as the intentional, flagged kernel-lifecycle fork it is, so a
  future real `agency_schedule` kernel verb can replace it cleanly without touching specialist
  prompts or artifact shapes.
- Rate-limit awareness: the GitHub poll cursor must back off per-client, not fire a fixed interval
  fleet-wide — at N clients this is exactly the "fan-out changes economics" scaling gotcha flagged
  earlier; size the poll interval off GitHub's actual rate limit divided by active client count,
  not a constant.

## Wave 3 — GitHub integration (later stage; coordinate with Kriti first)

See `HANDOFF-github-integration.md` — paused pending sync with Kriti's overlapping work. Covers
the `github_activity_research` and `product_usage_research` tool implementations
`metrics_researcher`'s prompt (Wave 0) already assumes exist.

## Wave 4 — X/Twitter publish + WhatsApp approval (later stage)

`PRODUCT-SLICES.md` Slice 2. The `publish_twitter_post`, `fetch_twitter_engagement`, and
`send_whatsapp_approval` tool manifests land in Wave 0; their real implementations (API clients,
OAuth/token handling, the WhatsApp Business API webhook receiver) land here.

## Wave 5 — trend/viral-pattern sourcing (later stage)

`PRODUCT-SLICES.md` Slice 3's `trend_researcher` half (the `metrics_researcher`/GitHub half is
Wave 3). Real `trend_research` and `viral_pattern_research` Linkup-backed implementations, plus
the `post_type` taxonomy wiring into `content_strategist`'s actual prompt-execution logic.

## Wave 6+ — everything after (later stage, order unchanged from PRODUCT-SLICES.md)

Cadence loop → batch approval → LinkedIn (secondary) + image/video formats → fleet-of-N → Dodo
billing. See `PRODUCT-SLICES.md` Slices 4-8 for acceptance criteria and metrics — this doc doesn't
duplicate those, just anchors the engineering sequencing to them.

## What's NOT decided yet (flag before building, don't guess)

- Exact GitHub rate-limit budget per client at fleet scale (Wave 2's poll-interval sizing) —
  needs a real number once Wave 3's GitHub integration scope is settled with Kriti.
- WhatsApp Business API provider (direct Meta Cloud API vs. a wrapper like Twilio) — not yet
  chosen; affects Wave 4's `send_whatsapp_approval` implementation shape.
- Whether APScheduler's single-process assumption holds if `service/` ever needs to scale beyond
  one Coolify container instance (fine at current scale; flag if that changes).
