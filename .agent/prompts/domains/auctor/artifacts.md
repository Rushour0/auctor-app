# Auctor artifacts

This is the **authoritative field-name catalogue** for both Auctor pipelines (site-build and
content-loop). Every specialist prompt (`specialists/researcher.md`, `specialists/brand_strategist.md`,
`specialists/copywriter.md`, `specialists/builder.md`, `specialists/voice_qa.md`,
`specialists/deployer.md`, `specialists/metrics_researcher.md`, `specialists/trend_researcher.md`,
`specialists/content_strategist.md`, `specialists/ghostwriter.md`, `specialists/publisher.md`,
`specialists/engagement_analyst.md`), every tool manifest under `.agent/tools/manifests/`, and
`service/app/models.py` are all written **against these exact field names** — not the other way
around. **If a specialist file (or a tool manifest, or `models.py`) disagrees with this file on a
field name, this file wins** and the other file is the one that must be corrected.

Every artifact carries `client_id` (the join key across research, positioning, build, QA, deploy,
and every content-loop pass for one client — stable and unique for the lifetime of that client's
`ClientPipeline`, per `manager.md`) and, where the artifact is recorded as a fleet event,
`fleet_id` alongside it. Never join two artifacts across different `client_id` values. Per
**FLEET ISOLATION** (`policy.md`), no artifact or tool call for one `client_id` may read or block
on another `client_id`'s state.

There are thirteen per-client artifact shapes in this catalogue, produced once per client per
pipeline pass (any step may run more than once across bounded retries — see `policy.md`'s
`SITE_MAX_RETRY_ATTEMPTS` / `CONTENT_MAX_RETRY_ATTEMPTS` rule — but only the latest passing
version of each is "current"), plus one cross-run record (`ClientBrandMemory`) that persists
across retries, across fleet runs, and across every content-loop cycle for a given client,
independent of any single pipeline pass.

SITE-BUILD pipeline artifacts (produced once per client, one-shot, fleet-parallel across
clients): `client_research` → `positioning_brief` (+ writes `ClientBrandMemory` v1) →
`site_copy` → `site_draft` → `voice_qa_report` (content_type: `"site"`) → `deployed_site`.

CONTENT-LOOP pipeline artifacts (recurring per client): `metrics_signal` + `trend_signal` (parallel)
→ `post_brief` → `post_draft` → `voice_qa_report` (content_type: `"post"`) → `published_post` →
`engagement_memory`.

## 1. `client_research` — produced by `researcher`

Authored in `specialists/researcher.md`; mirrored here verbatim. This is the sourced evidence base
every downstream artifact must trace claims back to, plus the client's real voice reference
excerpts `voice_qa` checks every candidate against.

```json
{
  "client_id": "client_123",
  "fleet_id": "fleet_...",
  "intake": {
    "name": "string",
    "linkedin_url": "string | null",
    "site_url": "string | null",
    "resume_url": "string | null"
  },
  "career_signals": [
    { "claim": "string", "source_url": "string", "claim_status": "supported | needs_source | remove" }
  ],
  "achievement_signals": [
    { "claim": "string", "source_url": "string", "claim_status": "supported | needs_source | remove" }
  ],
  "voice_reference_excerpts": [
    {
      "text": "string",
      "source_url": "string",
      "excerpt_id": "vre_1"
    }
  ],
  "usable_claim_count": 0,
  "needs_source_count": 0,
  "removed_count": 0,
  "usable_voice_excerpt_count": 0,
  "queried_at": "ISO-8601 timestamp",
  "usage": { "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0 }
}
```

Field notes:
- `career_signals` / `achievement_signals` are arrays of `{claim, source_url, claim_status}` —
  same three-value `claim_status` shape as Microsite Factory's `account_research`, applied by the
  researcher, never re-invented. This is the source pool `brand_strategist` draws
  `career_history[]` and `achievements[]` from for `ClientBrandMemory`.
- `voice_reference_excerpts` is an array of **3-5** real excerpts of the client's own writing
  (LinkedIn posts, blog, resume prose — never AI-generated or paraphrased), each with a stable
  `excerpt_id` other artifacts reference by. **A `client_research` with fewer than 3 usable
  excerpts is an automatic upstream fail at `voice_qa`** (`repair_target: "researcher"`) — mirrors
  Microsite Factory's "no positioning memory = QA fail, not pass-by-default" rule, applied here to
  voice evidence instead of positioning evidence.
- `claim_status` is one of exactly three values: `supported` (has a traceable `source_url`, claim
  stated no stronger than the source supports), `needs_source` (plausible but unverified — visible
  downstream but never shippable as a hard claim), `remove` (contradicted, stale, or unverifiable
  — excluded from usable evidence). This is **ANTI-FABRICATION**'s foundational tagging step,
  applied with zero tolerance per `policy.md` since these are a real person's public reputational
  claims.
- `usable_claim_count` / `needs_source_count` / `removed_count` are the researcher's own rollup
  counts across `career_signals` + `achievement_signals` combined, by `claim_status`.
  `usable_voice_excerpt_count` is the count of `voice_reference_excerpts` (must be >= 3 for
  `voice_qa` to accept downstream candidates).
- `usage` (`tokens_in`, `tokens_out`, `cost_usd`) rolls up into `ClientPipeline.usage`
  (`service/app/models.py`) and then the fleet total — every artifact below that carries its own
  `usage` object follows the same three-field shape and the same rollup rule.
- No extra top-level fields; no renames. `specialists/brand_strategist.md`,
  `specialists/copywriter.md`, and `specialists/voice_qa.md` all read this artifact directly by
  these field names.

## 2. `positioning_brief` — produced by `brand_strategist`

The strategist's one-shot positioning brief for one client's site build. `brand_strategist` also
writes the first version of `ClientBrandMemory` (section 3) from this same pass — the brief and
the memory are two different artifacts produced by the same specialist call.

```json
{
  "client_id": "client_123",
  "fleet_id": "fleet_...",
  "one_liner": "string",
  "brand_pillars": ["string"],
  "icp": "string",
  "content_pillars": ["string"],
  "proof_points": [
    { "claim": "string", "source_ref": "career_signals[0] | achievement_signals[1]", "claim_status": "supported | needs_source | remove" }
  ],
  "cta": { "label": "string", "target": "string" },
  "tone_notes": "string",
  "based_on_client_research_at": "ISO-8601 timestamp",
  "queried_at": "ISO-8601 timestamp",
  "usage": { "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0 }
}
```

Field notes:
- `proof_points[].source_ref` names which `client_research` finding (by array + index, e.g.
  `"achievement_signals[1]"`) the claim traces to; only `claim_status: "supported"` proof points
  may be stated as fact in downstream `site_copy` — `needs_source` may appear only as generic,
  unattributed phrasing (or be dropped), `remove` may never appear at all. This is
  **ANTI-FABRICATION** applied at the positioning layer, same rule Microsite Factory's
  `positioning_angle.value_props` enforces.
- `brand_pillars` / `content_pillars` are two **distinct** lists: `brand_pillars` are the
  identity/positioning themes the site is built around; `content_pillars` are the narrower set of
  recurring topics `content_strategist` is later allowed to pick from (`content_strategist` "MAY
  ONLY select among existing `ClientBrandMemory` pillars, never edit them" — that constraint reads
  `content_pillars` off `ClientBrandMemory`, not off this brief, once memory is written).
- `specialists/copywriter.md` and `specialists/builder.md` read this artifact directly by these
  field names. Once QA passes on the resulting site, this brief's `one_liner` / `brand_pillars` /
  `icp` / `content_pillars` / `proof_points` / `cta` are what get persisted into
  `ClientBrandMemory` (section 3) verbatim — `brand_strategist` does not restate them differently
  between the two artifacts.

## 3. `ClientBrandMemory` — persisted record, written by `brand_strategist`, read by every other specialist

Not a per-pipeline-pass artifact — the persistent cross-run record for a client, mirroring
Microsite Factory's `positioning_memory` role but carrying substantially more state since it is
also the durable source `content_strategist` and `ghostwriter` draw from on every content-loop
cycle, indefinitely, for the life of the client relationship.

```json
{
  "client_id": "client_123",
  "one_liner": "string",
  "brand_pillars": ["string"],
  "icp": "string",
  "tone_profile": {
    "avg_sentence_length": 0.0,
    "avg_paragraph_length": 0.0,
    "contraction_rate": 0.0,
    "emoji_rate": 0.0,
    "exclamation_rate": 0.0,
    "hedge_word_rate": 0.0,
    "vocabulary_notes": "string"
  },
  "voice_profile_ref": "client_research.voice_reference_excerpts",
  "content_pillars": ["string"],
  "proof_points": [
    { "claim": "string", "source_ref": "string", "claim_status": "supported | needs_source | remove" }
  ],
  "cta": { "label": "string", "target": "string" },
  "career_history": [
    { "role": "string", "org": "string", "start": "string", "end": "string | null", "source_ref": "string" }
  ],
  "achievements": [
    { "claim": "string", "source_ref": "string", "claim_status": "supported | needs_source | remove" }
  ],
  "version": 1,
  "drift_incidents": [
    { "detected_at": "ISO-8601 timestamp", "detail": "string", "resolved": true }
  ],
  "recorded_from_fleet_id": "fleet_...",
  "recorded_at": "ISO-8601 timestamp"
}
```

Field notes:
- Keyed solely by `client_id` — there is exactly one current `ClientBrandMemory` record per
  client at any time, independent of `fleet_id` (a client revisited in a later fleet run, or in
  any later content-loop cycle, still checks against its own prior memory).
- `tone_profile` holds the **computed structural stats** `voice_qa`'s `structural_voice_match`
  check (section 5) compares every candidate against — these are numeric/statistical properties
  computed from `voice_reference_excerpts`, never hand-written prose. `voice_profile_ref` points
  back at the source excerpts (`client_research.voice_reference_excerpts`) the stats were computed
  from, so a stat can always be re-derived and audited.
- `content_pillars` is the exact list `content_strategist` "MAY ONLY select among ... never edit
  them" — `content_strategist` reads this field, never `positioning_brief.content_pillars`
  directly, once memory exists (memory is the durable copy; the brief is the one-time origin).
- `career_history[]` and `achievements[]` are separate arrays: `career_history` is factual
  timeline (roles/orgs/dates), `achievements` is claim-bearing accomplishments — kept apart because
  they have different `claim_status` sourcing burdens (`career_history` entries still carry
  `source_ref` but are not claim-tagged the way accomplishment claims are).
- `version` increments by one every time `brand_strategist` persists a new memory version (first
  site-build pass writes `version: 1`; a later drift-repair or explicit rebrand writes `version:
  2`, etc.). **An account with no `ClientBrandMemory` record yet is a legitimate `voice_qa` failure**
  per `policy.md` ("no memory exists" check) — mirrors Microsite Factory's
  "no positioning memory = QA fail, not pass-by-default" rule verbatim, just renamed to this
  domain's artifact.
- `drift_incidents[]` appends one entry every time `voice_qa`'s `structural_voice_match` or
  `claim_sourcing` check flags a candidate as inconsistent with this memory; `resolved` flips to
  `true` once a repair pass clears QA. This is the audit trail `policy.md`'s drift handling refers
  to — never deleted, only appended and marked resolved.
- Every specialist in both pipelines reads `ClientBrandMemory` by these exact field names.
  `content_strategist` additionally reads `engagement_memory` (section 13) alongside it, but never
  writes to `ClientBrandMemory` itself — only `brand_strategist` writes this record.

## 4. `site_copy` — produced by `copywriter`

The exact words that will appear on the client's site, drafted against `positioning_brief` +
`client_research`.

```json
{
  "client_id": "client_123",
  "fleet_id": "fleet_...",
  "headline": "string",
  "bio": "string",
  "about": "string",
  "story": "string",
  "claim_refs": ["career_signals[0]", "achievement_signals[1]"],
  "based_on_positioning_brief_at": "ISO-8601 timestamp",
  "queried_at": "ISO-8601 timestamp",
  "usage": { "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0 }
}
```

Field notes:
- `bio` / `headline` / `about` / `story` are the four named copy blocks the brief above calls out
  explicitly ("bio/headline/about/story"); no additional top-level copy block may be added without
  updating this file first.
- `claim_refs` is the flat list of every `client_research` finding reference actually used across
  all four copy blocks — `voice_qa`'s `claim_sourcing` check (section 5) diffs this against
  `client_research`'s `claim_status: "supported"` findings to catch anything stated as fact that
  isn't sourced.
- `specialists/builder.md` and `specialists/voice_qa.md` both read this artifact directly by these
  field names.

## 5. `site_draft` — produced by `builder`

The rendered page for one client, including the media assets synthesized by the ElevenLabs
`synthesize_voice` and HeyGen `synthesize_video_intro` tool calls the builder makes **inside this
specialist**, not as separate specialist roles.

```json
{
  "client_id": "client_123",
  "fleet_id": "fleet_...",
  "preview_dir": "string",
  "pages": [
    { "path": "index.html", "title": "string", "claim_refs": ["career_signals[0]"] }
  ],
  "media_assets": [
    { "type": "audio | video", "asset_url": "string", "source_tool": "synthesize_voice | synthesize_video_intro" }
  ],
  "build_id": "string",
  "based_on_site_copy_at": "ISO-8601 timestamp",
  "generated_at": "ISO-8601 timestamp",
  "usage": { "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0 }
}
```

Field notes:
- `preview_dir` is this client's exclusive output directory; no other client's `site_draft` may
  reference or overlap it (**FLEET ISOLATION**).
- `media_assets[]` is the array `voice_qa`'s `screenshot_and_gate` check inspects alongside the
  rendered page — every entry names which tool produced it (`source_tool`) so a failed voice or
  video synthesis can be traced back to a specific retry of a specific tool call.
- `pages[].claim_refs` mirrors `site_copy.claim_refs` filtered to what actually rendered on that
  page — `voice_qa` diffs this against `site_copy.claim_refs` to catch claims the builder added or
  dropped versus what the copywriter wrote.
- `build_id` is a stable identifier for this specific generated build (regenerated on every
  repair-loop pass); `based_on_site_copy_at` names which `site_copy` pass produced the copy this
  build renders.
- `specialists/voice_qa.md` reads this artifact directly; `specialists/deployer.md` reads it only
  after `voice_qa_report.gate_result == "pass"`.

## 6. `voice_qa_report` — produced by `voice_qa` (shared verifier, both pipelines)

`voice_qa` is parameterized by `content_type: "site" | "post"` and is the verifier for **both**
pipelines — this is the one artifact shape shared verbatim across site-build and content-loop.
Checked against `ClientBrandMemory` and, for `content_type: "post"`, additionally against
`engagement_memory` context (read-only, never rewritten by `voice_qa`).

```json
{
  "client_id": "client_123",
  "fleet_id": "fleet_...",
  "content_type": "site | post",
  "candidate_ref": "site_draft.build_id | post_draft.draft_id",
  "checks": {
    "structural_voice_match": {
      "result": "pass | fail",
      "tolerance_pct": 30,
      "stat_breaches": [
        { "stat": "avg_sentence_length", "candidate_value": 0.0, "memory_value": 0.0, "pct_delta": 0.0, "within_tolerance": true }
      ]
    },
    "lexical_fingerprint_match": {
      "result": "pass | fail",
      "reused_phrase_count": 0,
      "reused_phrases": ["string"],
      "generic_ai_tell_hits": ["string"]
    },
    "claim_sourcing": {
      "result": "pass | fail",
      "unsourced_claims": [
        { "claim": "string", "location": "string" }
      ]
    }
  },
  "findings": [
    { "severity": "blocker | warning", "area": "string", "detail": "string" }
  ],
  "repair_target": "builder | copywriter | brand_strategist | researcher | ghostwriter | content_strategist | null",
  "retry_count": 0,
  "gate_result": "pass | fail",
  "checked_at": "ISO-8601 timestamp",
  "usage": { "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0 }
}
```

Field notes:
- `checks` always contains exactly these **three named checks** — names are fixed, must not be
  renamed, no check may be silently dropped:
  - `structural_voice_match`: candidate's computed structural stats vs `ClientBrandMemory.tone_profile`,
    **tolerance-banded at ~30%** (`tolerance_pct`). `stat_breaches[]` lists every stat compared,
    each with `candidate_value`, `memory_value`, `pct_delta`, and `within_tolerance` — `result` is
    `"fail"` if any entry has `within_tolerance: false`.
  - `lexical_fingerprint_match`: candidate must reuse **>= 3 real phrases** traceable to
    `client_research.voice_reference_excerpts` (`reused_phrase_count` / `reused_phrases`), and
    must trip **zero** hits against the generic-AI-tell blocklist (`generic_ai_tell_hits`) — any
    hit at all fails this check regardless of `reused_phrase_count`.
  - `claim_sourcing`: **ZERO-TOLERANCE**. Every factual claim in the candidate needs a
    `source_ref` resolving to a `client_research` (or `metrics_signal`/`trend_signal` for posts)
    finding tagged `claim_status: "supported"`. Any single entry in `unsourced_claims[]` fails this
    check — there is no partial-credit tolerance band here, unlike `structural_voice_match`.
- `gate_result` is `"pass"` only if all three checks are `"pass"`; any single `"fail"` makes the
  whole report `"fail"`.
- **A candidate whose upstream `client_research` has fewer than 3 usable
  `voice_reference_excerpts` is an automatic upstream fail** — `voice_qa` does not attempt the
  three checks in that case; it emits `gate_result: "fail"` with `repair_target: "researcher"`
  (or `"brand_strategist"` if the excerpts exist but `ClientBrandMemory` was never written). This
  mirrors "no positioning memory = QA fail, not pass-by-default" verbatim.
- `repair_target` is one of the six specialists listed above depending on `content_type` and which
  check failed (site-build failures route to `builder` / `copywriter` / `brand_strategist` /
  `researcher`; content-loop failures route to `ghostwriter` / `content_strategist` /
  `brand_strategist` / `researcher`); `null` only when `gate_result == "pass"`.
- `retry_count` mirrors the relevant bounded-retry counter at the time this report was produced —
  `SITE_MAX_RETRY_ATTEMPTS` (default `2`) for `content_type: "site"`, `CONTENT_MAX_RETRY_ATTEMPTS`
  (default `1`) for `content_type: "post"`, both env vars defined once and referenced, never
  duplicated, per `policy.md`. Once the relevant counter is exhausted and `gate_result == "fail"`,
  the candidate is routed to human review with all drafts attached, not retried again
  automatically.
- `specialists/deployer.md` and `specialists/publisher.md` may only proceed when handed a
  `voice_qa_report` with `gate_result == "pass"` for the exact `candidate_ref` they are about to
  ship — never a stale or different candidate's passing report.

## 7. `deployed_site` — produced by `deployer`

The record of one client's approved, published site (per `policy.md`: deploy is always
approval-gated, 1:1 with `client_id`, never batched or reused).

```json
{
  "client_id": "client_123",
  "fleet_id": "fleet_...",
  "build_id": "string",
  "cloudflare_pages_project": "string",
  "live_url": "string",
  "approved_by_approval_id": "string",
  "approved_at": "ISO-8601 timestamp",
  "deploy_status": "deploying | deployed | failed",
  "deployed_at": "ISO-8601 timestamp | null",
  "usage": { "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0 }
}
```

Field notes:
- `cloudflare_pages_project` is this client's own, distinct Cloudflare project — one project per
  client, never a shared project with per-client branches.
- `approved_by_approval_id` names the specific `approval_requests` record (WhatsApp channel, per
  **APPROVAL** in `policy.md`) that authorized this deploy; it is single-use — a later re-deploy of
  this same client (retry, content change) must reference a **new** approval, never this same
  `approved_by_approval_id` value again.
- `deploy_status` starts `"deploying"` (set the moment approval releases the client), becomes
  `"deployed"` on success or `"failed"` on a deploy-tool error; `deployed_at` is `null` until
  `deploy_status == "deployed"`.
- `live_url` is what `manager.md`'s fleet status roll-up surfaces per client once
  `deploy_status == "deployed"`.

## 8. `metrics_signal` — produced by `metrics_researcher`

Cron-polled signal of what the client actually shipped/grew this cycle, pulled from the client's
GitHub (commits/releases) and product usage/site-version signals. The concrete GitHub tool
implementation is a forthcoming handoff (see `HANDOFF-github-integration.md`) — this specialist's
prompt and this artifact shape are final regardless of that tool's landing date.

```json
{
  "client_id": "client_123",
  "signal_source": "github_commits | github_releases | product_usage",
  "findings": [
    {
      "claim": "string",
      "source_url": "string",
      "occurred_at": "ISO-8601 timestamp",
      "claim_status": "supported | needs_source | remove"
    }
  ],
  "is_event_trigger": false,
  "polled_at": "ISO-8601 timestamp",
  "usage": { "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0 }
}
```

Field notes:
- `signal_source` names which of the three signal types (per `HANDOFF-github-integration.md`)
  this pass covers; a single cron poll may emit multiple `metrics_signal` artifacts, one per
  source.
- `findings[]` uses the same three-value `claim_status` tagging as every other signal-bearing
  artifact in this catalogue — no exceptions, no separate tagging scheme for metrics.
- `is_event_trigger` is `true` only when this signal is a GitHub release/version-change event
  that should trigger a same-day draft ahead of the generic weekly cadence (per the
  **KERNEL DEVIATION** note in `policy.md`) — `content_strategist` reads this flag to decide
  whether to short-circuit the normal cadence wait.
- `specialists/content_strategist.md` reads this artifact directly by these field names.

## 9. `trend_signal` — produced by `trend_researcher`

Two distinct finding types in one artifact: sourced industry/trend claims, and structural
viral-pattern findings. The two are kept in separate arrays because they have **fundamentally
different sourcing rules** — see the guardrail below.

```json
{
  "client_id": "client_123",
  "industry_findings": [
    { "claim": "string", "source_url": "string", "claim_status": "supported | needs_source | remove" }
  ],
  "viral_pattern_findings": [
    {
      "pattern_id": "vp_1",
      "hook_style": "string",
      "format": "text | text+image | text+video | thread",
      "structural_notes": "string",
      "observed_post_url": "string"
    }
  ],
  "queried_at": "ISO-8601 timestamp",
  "usage": { "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0 }
}
```

Field notes:
- `industry_findings` is `claim_status`-tagged exactly like every other signal array in this
  catalogue and may be cited as fact once `supported`.
- `viral_pattern_findings` is **STRUCTURE ONLY, never content, never claims** — `hook_style` /
  `format` / `structural_notes` describe the *shape* of a real high-engagement X post
  (`observed_post_url` for traceability of the shape, not for quoting its text). Per `policy.md`'s
  anti-fabrication rule: "borrowing a hook/format SHAPE is fine, borrowing clickbait's habit of
  vague urgency or fabricated stats is not" — `viral_pattern_findings` entries **never** carry a
  `claim_status` field, because they are never eligible to be cited as a claim in the first place.
- `specialists/content_strategist.md` reads both arrays; `specialists/ghostwriter.md` reads
  `viral_pattern_findings` only via the `post_brief.based_on_pattern_ref` it's handed, never this
  artifact directly.

## 10. `post_brief` — produced by `content_strategist`

Which pillar/topic/signal/post_type is next for one client's content-loop cycle.
`content_strategist` **MAY ONLY select among existing `ClientBrandMemory.content_pillars`, never
edit them.**

```json
{
  "client_id": "client_123",
  "topic": "string",
  "pillar": "string",
  "post_type": "ship-announcement | hot-take | build-in-public | contrarian | thread-starter | milestone",
  "format": "text | text+image | text+video",
  "based_on_metrics_signal_ref": "string | null",
  "based_on_trend_signal_ref": "string | null",
  "based_on_pattern_ref": "string | null",
  "based_on_memory_version": 1,
  "decided_at": "ISO-8601 timestamp",
  "usage": { "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0 }
}
```

Field notes:
- `post_type` is the exact six-value enum given in the architecture: `ship-announcement`,
  `hot-take`, `build-in-public`, `contrarian`, `thread-starter`, `milestone` — no additional
  values without updating this file first. Each `post_type` maps to a structural template
  `ghostwriter` drafts against.
- `format` is the exact three-value enum: `text`, `text+image`, `text+video` — determines which
  synthesis tool (if any) `ghostwriter` calls.
- `pillar` must be a member of `ClientBrandMemory.content_pillars` at the time of this decision —
  `content_strategist` never writes a pillar that isn't already there.
- `based_on_memory_version` names which `ClientBrandMemory.version` this brief was decided against
  — lets `voice_qa` and `content_strategist` detect a stale brief if memory has since drifted.
- `specialists/ghostwriter.md` reads this artifact directly by these field names.

## 11. `post_draft` — produced by `ghostwriter`

The exact words (+ media) of one post, drafted against the `post_brief`'s structural template,
including OpenAI `synthesize_image` and HeyGen `synthesize_video` tool calls made **inside this
specialist** for `format` values that require media, mirroring `builder`'s in-specialist tool-call
pattern from the site-build pipeline.

```json
{
  "client_id": "client_123",
  "draft_id": "string",
  "text": "string",
  "media_assets": [
    { "type": "image | video", "asset_url": "string", "source_tool": "synthesize_image | synthesize_video" }
  ],
  "claim_refs": ["metrics_signal[0]", "trend_signal.industry_findings[0]"],
  "based_on_post_brief_at": "ISO-8601 timestamp",
  "drafted_against_post_type": "ship-announcement | hot-take | build-in-public | contrarian | thread-starter | milestone",
  "generated_at": "ISO-8601 timestamp",
  "usage": { "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0 }
}
```

Field notes:
- `media_assets` is empty for `format: "text"` briefs; populated per `post_brief.format` for
  image/video formats, same per-entry shape as `site_draft.media_assets` (`type` / `asset_url` /
  `source_tool`) for consistency across both pipelines.
- `claim_refs` is the flat list of every `metrics_signal` / `trend_signal.industry_findings`
  reference actually used in `text` — `voice_qa`'s `claim_sourcing` check diffs this against
  `claim_status: "supported"` findings exactly as it does for `site_copy.claim_refs`.
  `trend_signal.viral_pattern_findings` entries never appear in `claim_refs` (they are never
  claims, per section 9's guardrail).
- `drafted_against_post_type` echoes `post_brief.post_type` so `voice_qa` and
  `content_strategist` can confirm the draft matches the structural template it was briefed
  against.
- `specialists/voice_qa.md` reads this artifact directly (as `content_type: "post"`).

## 12. `published_post` — produced by `publisher`

The record of one post's publish outcome, **per-platform status, never a single boolean** — a
silent partial-publish (e.g. X succeeds, LinkedIn silently fails) is the #1 ops-flagged failure
risk and must always be visible per platform.

```json
{
  "client_id": "client_123",
  "draft_id": "string",
  "approved_by_approval_id": "string",
  "approval_mode": "single | batch",
  "platform_status": {
    "x": { "status": "pending | publishing | published | failed", "post_url": "string | null", "published_at": "ISO-8601 timestamp | null", "error": "string | null" },
    "linkedin": { "status": "not_applicable | pending | publishing | published | failed", "post_url": "string | null", "published_at": "ISO-8601 timestamp | null", "error": "string | null" }
  },
  "usage": { "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0 }
}
```

Field notes:
- `platform_status` has exactly these two named keys, `x` and `linkedin` — `x` is the PRIMARY
  publish platform (instant API access, no partner review) and is always attempted; `linkedin` is
  SECONDARY and starts `"not_applicable"` until Slice 6a ships LinkedIn publish support, at which
  point it follows the same five-state lifecycle as `x`. No additional platform key may be added
  without updating this file first.
- Each platform's status is independently `"published"` or `"failed"` — there is no single
  top-level `published` boolean anywhere on this artifact; any UI or fleet-event summary must read
  both `platform_status.x.status` and `platform_status.linkedin.status` explicitly.
- `approved_by_approval_id` is single-use, same rule as `deployed_site.approved_by_approval_id` —
  never reused across a regenerated draft. `approval_mode` records whether this approval came from
  a single-post WhatsApp reply (`"single"`) or a WhatsApp "reply ALL" batch fan-out
  (`"batch"`) — batch approvals only ever cover already-passing `voice_qa_report`s, per `policy.md`.
- `specialists/engagement_analyst.md` reads this artifact directly to know which `post_url`s to
  poll for engagement metrics, per platform.

## 13. `engagement_memory` — persisted append-only record, written by `engagement_analyst`, read by `content_strategist`

Not a per-cycle artifact in the same sense as the others — an append-only log of what performed,
per client, that accumulates across every content-loop cycle. **DATA ONLY** — `engagement_analyst`
never rewrites `ClientBrandMemory.content_pillars` or any other pillar/positioning field.

```json
{
  "client_id": "client_123",
  "entries": [
    {
      "draft_id": "string",
      "platform": "x | linkedin",
      "post_url": "string",
      "post_type": "ship-announcement | hot-take | build-in-public | contrarian | thread-starter | milestone",
      "metrics": { "impressions": 0, "likes": 0, "reposts": 0, "replies": 0, "collected_at": "ISO-8601 timestamp" }
    }
  ],
  "updated_at": "ISO-8601 timestamp"
}
```

Field notes:
- Keyed solely by `client_id`, one record per client, `entries[]` appended to on every
  `engagement_analyst` pass — never rewritten or pruned by this specialist.
- Each entry's `platform` and `post_type` let `content_strategist` correlate "what performed" back
  to a specific pillar/post_type combination when deciding the next `post_brief`, without
  `engagement_analyst` itself making any pillar-level decision.
- `metrics` is intentionally a flat, provider-agnostic shape (`impressions` / `likes` / `reposts` /
  `replies`) so both X and LinkedIn engagement events can be normalized into the same fields;
  provider-specific extras (if ever needed) go in a separate `raw` sub-object, never by renaming
  these four.

## Cross-artifact rules (apply to every artifact above)

- `client_id` is mandatory on every artifact and every fleet event referencing it; never omit it
  and never let it be inferred rather than passed through explicitly. `fleet_id` accompanies it
  wherever the artifact is recorded as a fleet event.
- Every specialist writes only the fields defined for its own artifact in this catalogue — no
  specialist invents a new top-level field or renames one of the above without a corresponding
  edit to this file first, since this file is the single source of truth other specialist prompts,
  tool manifests, and `service/app/models.py` are written against.
- Every claim that reaches `positioning_brief`, `site_copy`, `post_brief`, or `post_draft` must
  trace back to a `client_research` / `metrics_signal` / `trend_signal.industry_findings` finding
  with `claim_status: "supported"` (or be generic, non-factual filler) — never a `needs_source` or
  `remove` finding stated as fact, and never a `viral_pattern_findings` entry treated as a claim
  (per **ANTI-FABRICATION**, `policy.md`).
- Every artifact that carries a `usage` object uses the same three-field shape (`tokens_in`,
  `tokens_out`, `cost_usd`); these roll up into `ClientPipeline.usage`
  (`service/app/models.py`) per client, then into the fleet-level total the manager reports in its
  status roll-up.
- `voice_qa_report` is the one artifact shape shared verbatim across both pipelines
  (`content_type: "site" | "post"`) — do not fork it into two separate artifact shapes.
- `published_post.platform_status` is always keyed per platform; no specialist, tool manifest, or
  UI surface may collapse it into a single boolean.
- Every phase transition (research/strategize/build/QA/deploy, or
  metrics+trend/strategize/draft/QA/publish/analyze, including retries and blocks) is recorded as
  a fleet event with both `fleet_id` and `client_id`, and an optional `cost_usd`, so the artifact
  trail above is reconstructable per client from the fleet event log alone.
- The content-loop's recurring cadence trigger (cron/poll inside `service/`) is a documented
  **KERNEL DEVIATION** from the fixed kernel lifecycle, per `policy.md` — it is not a new kernel
  verb, and this file does not define one; `metrics_signal.is_event_trigger` is the only field on
  this page that interacts with that deviation, and it does so by flag, not by inventing a new
  artifact type.
