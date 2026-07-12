# Verification policy

Every workflow must define a schema check, a domain-quality check, and an action check for external side effects. A failed check returns structured findings with a repair hint. Retry the smallest failed unit and stop after a bounded number of attempts.

In this agency the smallest retryable unit is a single client's pipeline **stage** — within either the site-build pipeline or the content-loop pipeline — not the fleet run and not the whole pipeline. A failure in one client's schema, quality, or action check must never abort or retry sibling clients — repair and retry are scoped to the failing client's failing stage only. This mirrors Microsite Factory's fleet-isolation rule, with the retryable unit narrowed to stage granularity because a single client here runs two independently-triggered pipelines (one-shot site-build, recurring content-loop) rather than one.

## Two separate retry budgets, not one

Unlike a single-pipeline fleet, Auctor bounds retries with **two separate constants**, defined once and referenced (never duplicated) by both pipelines:

- `SITE_MAX_RETRY_ATTEMPTS` (env `AUCTOR_SITE_MAX_RETRY_ATTEMPTS`, default `2`)
- `CONTENT_MAX_RETRY_ATTEMPTS` (env `AUCTOR_CONTENT_MAX_RETRY_ATTEMPTS`, default `1`)

The two pipelines get different budgets because they have different **blast radii** when a repair pass goes wrong:

- **Site-build is low stakes to retry.** Nothing about a site-build stage is public until `deployer` ships behind a human approval gate. A failed `researcher`/`brand_strategist`/`copywriter`/`builder`/`voice_qa` stage can be repaired and re-run twice with no external consequence — the worst case is a slower path to a first draft nobody has seen yet. `SITE_MAX_RETRY_ATTEMPTS` defaults to `2` to give the pipeline a real second chance before giving up.
- **Content-loop is high stakes to retry.** A failed `content_strategist`/`ghostwriter`/`voice_qa` stage sits closer to a live publish, on a recurring cadence, against a real person's reputation. The specific risk is not "retry costs time" but that a repair pass can **curve-fit a post to pass the structural voice_qa checks** (structural_voice_match, lexical_fingerprint_match) without the post actually being good, sourced, or in-voice — i.e. optimizing the artifact to satisfy the verifier rather than to be correct. `CONTENT_MAX_RETRY_ATTEMPTS` defaults to `1` precisely to cut that off early: after a single miss, route to a human via the WhatsApp approval channel with **both** drafts (original + repair attempt) instead of grinding toward a technically-passing but curve-fit post.

When a stage exhausts its pipeline's retry budget it is marked `blocked` and surfaced in that client's pipeline status; for content-loop, exhaustion additionally routes to human review with all drafts attached rather than auto-failing silently. The fleet run, and every sibling client's pipeline (site-build or content-loop), continues unaffected.
