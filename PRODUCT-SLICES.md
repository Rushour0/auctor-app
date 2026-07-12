# Auctor — product decomposition (agentic-pm handoff)

Produced via a Frame → Investigate (3 parallel persona-lens research passes) → Decompose →
Sequence → Gap-scan pass, 2026-07-12. This is the reference engineering picks up from, slice by
slice, via `multi-agent-delivery`/`hermes-new-agency-brief` — do not re-litigate slices during
engineering; open questions below are already decided with the founder.

## Frame

- **Target user (JTBD):** "When I ship something real (a PR merged, a feature launched, a deal
  closed) but have zero minutes to translate it into a post, I want the work itself to become
  visible content without me writing or scheduling it, so I can compound my reputation while
  staying heads-down on building."
- **Success signal (leading):** % of drafted posts approved with zero edit requests, per client
  — this is both the trust-ladder metric and the earliest signal that voice_qa is actually working
  (per research: one off-voice post triggers immediate abandonment; the tool is only as valuable
  as the founder can trust it unattended).
- **Non-goals (v1):** not a general content calendar tool; not trying to support every social
  platform (LinkedIn + X only); not offering full silent autonomy (approval-frequency reduction,
  never zero-approval, per the ops/skeptic research on reputational risk).

## Key research findings (full detail: session transcript, 3 parallel agent passes)

1. **Voice authenticity is a veto gate, not a nice-to-have.** One off-voice draft ends the
   relationship immediately (cited: Oiti/Moxie Digital sources). Cadence/consistency is the
   retention driver on top of that gate — "3 posts then a month of silence" is the pattern Auctor
   has to prevent.
2. **LinkedIn API is a real go/no-go risk**, not just a lead-time cost: Marketing Developer
   Platform partner review runs 3-4 months with common rejections; the Sales Navigator API tier is
   closed to new partners entirely (as of this research). Decided: attempt the basic self-serve
   `w_member_social` share scope first (see Open Decisions below — this is the higher-risk option,
   chosen deliberately over Wizard-of-Oz or X-first).
3. **Approval fatigue is real even at N=1 client.** Strict never-batched per-post approval (the
   rule Microsite Factory uses for its high-stakes, rare deploys) doesn't transfer to a 3x/week
   content cadence — decided: pull the WhatsApp batch-approval slice forward, right after the
   cadence loop ships, not deferred to the end.
4. **Dual-platform (LinkedIn+X) and GitHub/metrics-sourced content are NOT proven differentiators**
   — dual-platform publish already exists in at least one competitor (Product Hunt's
   "Ghostwriter"); provenance-from-real-work + WhatsApp-approval were not found in any of the 4
   named competitors (Oiti, Ghostli, ContentIn, Windmill Growth), making **provenance** — "drafted
   from what you actually shipped, not a generic prompt" — the actually-defensible claim, not
   voice-matching alone (every competitor already claims voice-matching).
5. **Silent partial-publish is the most likely failure mode** once dual-platform ships (approved
   once, published to only one of two platforms, nobody notices — the kernel's default log policy
   hides tool-call detail). Dual-platform slice must ship explicit per-platform publish-status,
   not a single boolean.
6. **Cost ranking for the novel media integrations:** OpenAI gpt-image (cheapest, ~$0.005/image) <
   ElevenLabs voice (~$0.27/min) < HeyGen video (~$1-4/generated minute, and it's a one-shot
   onboarding cost, not a recurring one — proves nothing about the recurring content-loop
   mechanic). HeyGen is the correct thing to defer furthest on cost/complexity grounds.

## Slices, in build order

### Wave 1 — launch (walking skeleton + the actual differentiator, one client, one platform)

**Slice 1 — Live, voice-verified site from a LinkedIn URL**
- Outcome: a real client pastes their LinkedIn URL and gets back a live, positioned personal site,
  copy gated by all 3 real (not stubbed) `voice_qa` checks.
- Acceptance: researcher → brand_strategist → copywriter → builder → voice_qa → deployer runs
  end-to-end; live Cloudflare URL; human approval gate before deploy.
- Deps: none. Effort: L.
- Metric: time from LinkedIn URL submitted → live site URL.
- Kill criteria: `voice_qa` can't produce a real structural diff from the recruited test client's
  actual writing (fewer than 3 usable reference excerpts) — recruit a different test client rather
  than fake the signal.

**Slice 2 — First WhatsApp-approved post, one platform**
- Outcome: that client gets one post drafted (topic manually supplied, no auto-sourcing yet),
  approved via exactly one WhatsApp reply, and it actually ships.
- Publish path: attempt LinkedIn's self-serve `w_member_social` OAuth share scope (Open Decision
  #1, chosen — riskiest but highest-value if it works; no partner-review dependency if this scope
  is sufficient for personal posting, unlike the Marketing Developer Platform tier).
- Acceptance: ghostwriter drafts → `voice_qa` passes (same 3 checks, on the draft's script) →
  WhatsApp message sent → single-reply approval → publish → `published_post` recorded with real
  platform confirmation (not assumed-success).
- Deps: Slice 1. Effort: M.
- Metric: % of drafts approved with zero edit requests (the north-star trust metric — instrument
  from day one, not retrofitted later).
- Kill criteria: the WhatsApp round-trip requires more than one reply in practice for a real
  client (defeats the core JTBD).

**Slice 3 — Real signal sourcing (the actual differentiator)**
- Outcome: the post topic is no longer manually supplied — sourced from the client's real GitHub
  activity or a live industry trend, every claim traced to source.
- Acceptance: `metrics_researcher` pulls real GitHub data with `claim_status` tags;
  `trend_researcher` pulls real Linkup trend data; `content_strategist` picks from
  `ClientBrandMemory` pillars + these signals; every factual claim in the resulting draft resolves
  to a `claim_status: supported` source (zero-tolerance, per the existing `claim_sourcing` design).
- Deps: Slice 2. Effort: M.
- Metric: % of published posts whose topic came from a real sourced signal, not a manual pick —
  this is the metric that actually proves the "provenance" differentiator research validated as
  the legitimate claim (not voice-matching alone, which competitors already do).
- Kill criteria: GitHub/product-metrics signal is too sparse to produce a usable topic more than
  once a week for the real test client — if so, lean harder on `trend_researcher` for that client.

### Wave 2 — the loop compounds

**Slice 4 — Cadence: the loop runs on its own**
- Outcome: Auctor proposes a new draft on a schedule without a human re-triggering it. This is
  where the brief-local self-scheduling workaround gets built AND where `policy.md` documents the
  kernel deviation explicitly (no `agency_schedule` verb exists — flagged, not silently normalized).
- Deps: Slice 3. Effort: S.
- Metric: posts drafted per client per week without a manual trigger.

**Slice 5 — Batch approval (pulled forward per fatigue research)**
- Outcome: after a run of zero-edit approvals, the client can reply once to approve a whole week's
  queue instead of one WhatsApp round-trip per post — the `agency_approve_batch` design from the
  architecture doc, built now specifically because research showed per-post fatigue is a real
  abandonment risk even at low client counts, not a fleet-scale-only concern.
- Deps: Slice 4. Effort: S.
- Metric: % of eligible weeks where the client uses batch-approve over per-post approval.

**Slice 6 — Dual-platform + richer formats**
- Split into three additive sub-slices, in cost/risk order (cheapest and most differentiating
  first): **6a** Twitter/X publish with explicit per-platform status (no silent partial-publish —
  the #1 ops-flagged failure mode) — M. **6b** OpenAI `gpt-image` photo format — S, cheap. **6c**
  HeyGen video format — S/M, deliberately last: most expensive per-generation, and a one-shot
  onboarding cost that proves nothing about the recurring loop.
- Deps: Slice 2 (single-platform publish proven). Metric: 0 silent partial-publish incidents once
  6a ships (both platforms' status independently visible).

**Slice 7 — Fleet of N**
- Outcome: multiple clients run concurrently with the two-column (site status / loop status)
  roll-up view, isolated per-client retry/blocking.
- Deps: Slices 1-5 stable for one client first — per-client unit economics must already look
  sustainable before fanning out; fleet just multiplies whatever the per-client economics already
  are (the "scaling gotcha" flagged twice now in this project).
- Effort: M. Metric: N concurrent clients, 0 cross-client blocking incidents.
- Kill criteria: if slice 1-5 per-client cost doesn't pencil, do not proceed to fleet — fix unit
  economics first.

**Slice 8 — Dodo billing gate**
- Outcome: new client signups gated on an active subscription.
- Deps: everything above working end-to-end (billing without a working product is pure risk with
  no payoff, per the original architecture decision).
- Effort: S. Metric: successful checkout → gated `agency_start`.

## Descope list (explicit, with reasons)

- **Silent full autonomy (zero approval, ever):** never — the skeptic research shows reputational
  risk is structurally unaddressed by voice-checks alone; only approval-*frequency* reduction
  (Slice 5) is on the roadmap, not approval removal.
- **HeyGen video:** pushed to 6c specifically — most expensive per-generation of the three media
  integrations, and it's a one-shot cost that validates nothing about the recurring loop.
- **Fleet-of-N before single-client economics are proven:** explicit kill criteria on Slice 7 —
  don't fan out a losing unit economics.
- **Billing before the product works:** unchanged from the original architecture decision — Slice
  8 is last on purpose.

## Open decisions register (already resolved with the founder — recorded for engineering)

| # | Decision | Resolution | Blocks |
|---|---|---|---|
| 1 | LinkedIn publish path for Slice 2, given the API access risk | Attempt self-serve `w_member_social` OAuth share scope first (not Wizard-of-Oz, not X-first) | Slice 2 |
| 2 | First real test client for Slice 1/2 (needs real writing history for `voice_qa` to work) | Recruit a friend/colleague, not the founder himself — tests the cold-user path per the kernel's own testing bar | Slice 1 |
| 3 | Approval-batching timing | Pulled forward to right after cadence (Slice 5, not last) given fatigue-abandonment research | Slice 5's position in the sequence |

## Gap-scan notes for engineering

- Run with the kernel's "detailed" observability log toggle ON by default through Wave 1 — the
  default (compact) view hides tool-call detail, and Wave 1 is exactly when a silent LinkedIn-scope
  failure or a partial-publish needs to be visible, not hidden.
- `metrics_researcher`'s definition of a "claim-worthy" GitHub signal (which commits/PRs actually
  count) needs a concrete rule before Slice 3 — flag as a build-time prompt-design decision, not a
  blocking product one.
- Per-client `Usage` rollup (already designed in the architecture doc) is what makes Slice 7's kill
  criteria checkable — build it honestly in Slice 1-3, don't defer it to Slice 7 and discover the
  unit economics don't work only after fanning out.
