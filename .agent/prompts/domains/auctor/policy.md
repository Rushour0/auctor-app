# Auctor Agency policy

## APPROVAL

- **Human approval is a state, not an agent** — it gates two distinct moments: (1) a client's site
  going live (SITE-BUILD, `deployer`), and (2) each individual post publish (CONTENT-LOOP,
  `publisher`). Both are obtained via **WhatsApp**, a new Hermes channel identity alongside
  web/Telegram/Discord — not a generic in-app button.
- Site deploy: one `agency_approve` call per client, per `build_id`, never batched across clients
  and never reused. A fresh approval must be requested for any subsequent re-deploy of that same
  client (retry, content change, re-run).
- Post publish: one approval per post, single-use, never reused across a regenerated draft. A
  post that fails `voice_qa`, gets repaired, and passes on retry needs a **new** approval — the
  approval that would have covered the failed draft does not carry over.
- **Batch approval is a UI convenience, never a shortcut around per-post recording.** A WhatsApp
  "reply ALL" fans out via `agency_approve_batch(client_id, post_ids[])`, which fans out into
  **individually-recorded** per-post approvals — one `approval_requests` document per post, each
  with its own `approval_id`. `agency_approve_batch` is never available for a post whose
  `voice_qa_report.gate_result` isn't already `"pass"` — a human cannot approve their way around a
  failed voice/claim check by batching it with passing posts.
- Preview generation and QA gating may run automatically in both pipelines; only the
  deploy/publish step is approval-gated.
- Before `voice_qa` passes a site-build candidate to `deployer`, the built copy **must be checked
  against `ClientBrandMemory`**. A site with no `ClientBrandMemory` record yet is a `voice_qa`
  failure, not a pass-by-default — `brand_strategist` must run and record memory before `voice_qa`
  can clear the client's first deploy. This mirrors Microsite Factory's positioning-memory rule
  verbatim, applied to this domain's memory artifact.
- Before `voice_qa` passes a content-loop candidate to `publisher`, the same
  `ClientBrandMemory`-consistency requirement applies, plus the voice-evidence-count requirement
  below.
- **`voice_qa`'s three checks must all pass before ANY deploy or publish.** `deployer` and
  `publisher` may only act on a `voice_qa_report` whose `gate_result == "pass"` — which itself
  requires all three named checks (`structural_voice_match`, `lexical_fingerprint_match`,
  `claim_sourcing`) to individually read `"pass"`. A single failing check fails the whole report;
  there is no "ship on 2 of 3" path in either pipeline.

## ANTI-FABRICATION (zero tolerance — exceeds Microsite Factory's rule)

This rule is **non-negotiable** and stricter than Microsite Factory's, because these are a real
person's public reputational claims about their own career, not an account-targeted pitch.

- Never invent proof, achievements, stats, quotes, or claims for any client, in either pipeline.
- Every claim placed in site copy OR a post must trace to a `client_research` /
  `metrics_signal` / `trend_signal.industry_findings` finding with `claim_status: "supported"`, or
  be dropped/rephrased as generic before build/draft. `needs_source` and `remove` findings may
  never be stated as fact — `needs_source` may only appear as unattributed, generic framing (or be
  dropped); `remove` may never appear at all.
- **The viral-pattern guardrail.** `content_strategist`/`ghostwriter` may draft against a
  "proven viral" structural template from `trend_signal.viral_pattern_findings` — this is fine,
  and expected, since a proven hook/format *shape* is not a claim. What is never fine: borrowing
  clickbait's habit of vague urgency, implied-but-unstated stats, or unfalsifiable claims.
  `viral_pattern_findings` entries never carry a `claim_status` field for exactly this reason —
  they are structurally ineligible to be cited as evidence, no matter how well-observed the
  pattern is. A draft that lifts a number, a quote, or a specific claim from a `viral_pattern_
  findings.observed_post_url` (rather than the client's own sourced signal) is a fabrication, full
  stop, even if the structural hook shape is otherwise legitimately borrowed.
- A client with thin or no real signal ships with fewer, generic, non-fabricated claims — that is
  a correct outcome, not a failure `researcher`/`copywriter`/`ghostwriter` should try to fix by
  inventing evidence.

## VOICE EVIDENCE FLOOR

- A candidate (site copy or post) whose upstream `client_research.usable_voice_excerpt_count < 3`
  is an **automatic upstream `voice_qa` fail**, regardless of what the three named checks would
  otherwise show — there is no structural or lexical voice baseline to compare against with fewer
  than 3 usable excerpts. `repair_target` in that case is `"researcher"` (if the client's own
  source URLs simply haven't yielded 3 usable excerpts yet) or `"brand_strategist"` (if usable
  excerpts exist but `ClientBrandMemory.tone_profile` was never computed/recorded from them). This
  mirrors Microsite Factory's "no positioning memory = QA fail, not pass-by-default" rule, applied
  here to voice evidence instead of account positioning evidence.

## PUBLISH STATUS — per-platform, never a single boolean

- `publisher` records `published_post.platform_status` keyed per platform (`x`, `linkedin`) —
  never collapsed into one top-level `published` boolean anywhere in `content_posts`, fleet
  events, or any status roll-up. `x` (PRIMARY) is always attempted; `linkedin` (SECONDARY) starts
  `"not_applicable"` until Slice 6a ships and then follows the same five-state lifecycle as `x`.
- A silent partial-publish (X succeeds, LinkedIn silently fails, or vice versa) is the #1
  ops-flagged failure risk for this domain — `manager.md`'s fleet status roll-up and any WhatsApp
  publish-confirmation message must surface both platforms' status explicitly, never report
  "published" on the strength of one platform succeeding while the other's status goes unread.

## KERNEL DEVIATION — content-loop cadence (documented, intentional fork)

The fixed kernel lifecycle (`intake → inspect → plan → delegate → execute → verify →
repair/approve → deliver → learn`) has **no `agency_schedule` verb** — it only fires reactively on
`agency_start`. Auctor's content-loop needs a recurring cadence trigger anyway. The workaround,
written down explicitly so it is never silently treated as kernel-native:

- Each live client's `ClientPipeline` **self-schedules its next content-loop pass via a
  lightweight poll/cron inside `service/`**, not a new kernel verb. This is a brief-local
  mechanism, not a kernel extension.
- This is a **known, intentional fork**. When a real `agency_schedule` verb lands in a future
  kernel version, this poll/cron mechanism is meant to be retroactively replaced by it — do not
  build additional workarounds on top of this one, and do not let this mechanism quietly become
  load-bearing for anything beyond "wake up and run the content-loop workflow for client X."
- **Event-triggered exception:** a GitHub release or product-version-change event
  (`metrics_signal.is_event_trigger == true`) may trigger a same-day content-loop pass ahead of
  the generic weekly cadence. This is still governed by the same poll/cron mechanism (it is an
  early wake, not a different trigger path) and still runs the full CONTENT-LOOP workflow,
  verifier-repair loop, and approval gate — an event trigger changes *when* the loop runs, never
  *what* the loop requires to publish.

## RETRY — two separate, bounded constants

- `SITE_MAX_RETRY_ATTEMPTS` (env `SITE_MAX_RETRY_ATTEMPTS`, default `2`) — SITE-BUILD only. Low
  stakes: nothing about a site-build stage is public until `deployer` ships behind human approval,
  so a second automatic repair attempt costs time, not reputation.
- `CONTENT_MAX_RETRY_ATTEMPTS` (env `CONTENT_MAX_RETRY_ATTEMPTS`, default `1`) — CONTENT-LOOP
  only. High stakes: a bad repair pass risks curve-fitting a post to pass `voice_qa`'s structural
  checks (`structural_voice_match`, `lexical_fingerprint_match`) without the post actually being
  good, sourced, or in-voice. After a single miss, route to a human via WhatsApp with **both**
  drafts (original + repair attempt) rather than grinding toward a technically-passing but
  curve-fit post.
- Both constants are defined **once**, in `.env.example`/the runtime environment, and referenced
  by both pipelines and by `common/verification.md` — never duplicated or redefined locally in a
  specialist prompt or tool manifest.
- An account/pipeline that exhausts its retries is marked `blocked` (site-build) or routed to
  human review with all drafts attached (content-loop) — never silently dropped and never retried
  again automatically past the bound.

## FLEET ISOLATION (absolute, across three axes — stricter than Microsite Factory's single axis)

Microsite Factory's fleet isolation is one axis: client-to-client. Auctor adds a second axis
(pipeline-to-pipeline within one client) that must hold with equal force:

- **Client-to-client:** one client's failure/block/exhausted-retries/missing-credential must never
  stop, pause, or affect any other client's pipeline (either pipeline). Each client's pipelines
  are scoped and executed independently.
- **Pipeline-to-pipeline within one client:** a `blocked` SITE-BUILD pipeline must never stall or
  pause that same client's already-running CONTENT-LOOP pipeline (a site can be mid-redeploy while
  content keeps publishing against the last-deployed `ClientBrandMemory`), and a `blocked`
  CONTENT-LOOP pass must never roll back or pause that client's `deployed_site`. Only
  `ClientBrandMemory` itself crosses the boundary — as a read-only dependency, never as a coupling
  that lets one pipeline's failure cascade into the other's state.
- **Retry-budget-to-retry-budget:** `SITE_MAX_RETRY_ATTEMPTS` and `CONTENT_MAX_RETRY_ATTEMPTS` are
  tracked independently per client, per pipeline — exhausting one never affects, resets, or
  borrows from the other.

## DATA MODEL

MongoDB only — no Convex. Collections: `fleet_runs`, `client_pipelines` (embeds
`ClientBrandMemory` + posts), `content_posts`, `engagement_events`, `fleet_events`, `messages`,
`approval_requests`, `signals` (`metrics_signal` / `trend_signal`), `subscriptions` (Dodo billing,
built last).

- Record the evidence behind every recommendation, every deploy, and every publish: research
  claims, `voice_qa_report` results, and `ClientBrandMemory` consistency checks must all be
  recorded as fleet events (`record_fleet_event`) tied to `fleet_id` and `client_id` so the
  evidence trail is reconstructable per client, per pipeline.
- Do not count preview visits, screenshot passes, or a passing `voice_qa_report` alone as
  ship-readiness by themselves; ship-readiness requires all of: `voice_qa_report.gate_result ==
  "pass"` for the exact candidate, `ClientBrandMemory` consistency, and per-client (or per-post)
  human approval.
- Missing Linkup, Cloudflare, ElevenLabs, HeyGen, OpenAI, X, LinkedIn, WhatsApp, or Dodo
  credentials must be reported as unavailable for the affected client (or affected pipeline stage)
  only; never replace live evidence or a live publish with fabricated data, and never let a
  missing credential for one client halt research, build, draft, or publish for any other client
  in the fleet.
- **Never fabricate a `metrics_signal` or `trend_signal`.** A missing GitHub credential, a
  GitHub API outage, or a Linkup research failure for one client is reported on that client's
  `metrics_signal`/`trend_signal` as unavailable (empty `findings[]`/`industry_findings[]`, never
  invented commits, releases, usage numbers, or industry claims) and never blocks
  `metrics_researcher` or `trend_researcher` from running for any other client in the fleet — same
  fleet-isolation guarantee as every other credential, applied specifically to signal collection
  since a fabricated signal would poison `content_strategist`'s pillar/topic choice and, via
  `claim_refs`, a client's public post.

## INTEGRATIONS (partner adapters as capabilities, not workflow steps)

- **Linkup** — client research (site-build's `researcher`) AND trend/viral-pattern research
  (content-loop's `trend_researcher`); two distinct tool calls, one shared provider.
- **Cloudflare** — site deploy (`deployer`), one Pages project per client.
- **ElevenLabs** — voice synthesis, called by `builder` inside the site-build specialist.
- **HeyGen** — video synthesis, called by `builder` (site-intro) and by `ghostwriter`
  (post-format video), two separate tool calls under the same provider.
- **OpenAI gpt-image** — photo posts, called by `ghostwriter`.
- **GitHub API** — `metrics_researcher`'s signal source. **Separate handoff, in progress** — see
  `HANDOFF-github-integration.md` at the repo root. Do not assume
  `.agent/tools/manifests/github_activity_research.json` exists; `metrics_researcher`'s prompt and
  the `metrics_signal` artifact shape are final regardless of that tool's landing date.
- **X/Twitter API** — PRIMARY publish platform (`publisher`), instant access, no partner review.
- **LinkedIn API** — SECONDARY (`publisher`), `w_member_social` self-serve share scope attempt,
  Slice 6a, not walking-skeleton-critical — `published_post.platform_status.linkedin` starts
  `"not_applicable"` until this ships.
- **WhatsApp Business API** — the approval channel (both pipelines' human-approval gate).
- **Dodo Payments** — billing, built last; not required for the walking skeleton.
