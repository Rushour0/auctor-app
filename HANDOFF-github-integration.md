# Handoff — GitHub integration (`metrics_researcher`)

**Status: paused here, coordinate with Kriti before building** — flagged as overlapping with
work Kriti is already doing. Don't duplicate; sync scope first.

## What this piece owns

`metrics_researcher` is one of Auctor's 12 specialists (content-loop pipeline, see
`PRODUCT-SLICES.md` Slice 3). Its job: pull a client's own GitHub activity as sourced content
signal — the "provenance" mechanic that's Auctor's actual differentiator (not voice-matching
alone, which competitors already do).

## Scope, as currently spec'd

Three signal types, all `claim_status`-tagged (never fabricated, every claim traceable):

1. **Commits** — baseline activity signal, lowest priority (noisy, per the PM gap-scan's open
   question: "what counts as a claim-worthy commit" still needs a concrete rule).
2. **Releases** — tagged versions, higher-signal, natural "shipped vX" ship-announcement trigger.
3. **Site/product version changes** — the client's own deploys, tracked separately from GitHub
   releases since not every client's deploy is a tagged GitHub release.

All three are **cron-polled**, not just pulled on-demand at draft time (see `PRODUCT-SLICES.md`'s
pivot note — release/version events should be able to trigger a draft same-day, ahead of the
generic weekly-cadence loop in Slice 4).

## Tool contract shape needed (per the kernel's `07-tools-integrations-and-permissions.md`
pattern — see `~/hermes/landing-page/docs/07-tools-integrations-and-permissions.md`)

```
github_activity_research.json
  allowed_agents: ["metrics_researcher"]
  input: { client_id, github_username_or_org, since_ts }
  output: { commits[], releases[], claim_status per item }
  risk_level: low (read-only)
  approval_policy: none
  auth: GITHUB_TOKEN (already scaffolded in .env.example)

product_usage_research.json
  allowed_agents: ["metrics_researcher"]
  input: { client_id, product_source_config }   # shape TBD — depends on what "site version /
                                                  # product usage" source each client actually has
  output: { events[], claim_status per item }
  risk_level: low (read-only)
  approval_policy: none
```

## Open questions for whoever picks this up (Kriti or otherwise)

1. What counts as a "claim-worthy" commit/PR for drafting purposes — a length threshold on the
   commit message, only commits with a linked PR description, only commits touching certain
   paths? Needs a concrete rule before `metrics_researcher`'s prompt can be written for real.
2. "Site/product version changes" — is this GitHub Releases specifically, a webhook from the
   client's own deploy pipeline, or a generic "check this URL's version endpoint" poll? Different
   clients likely need different answers; the tool contract above assumes a pluggable
   `product_source_config` but the actual adapter shape isn't decided.
3. Cron cadence for polling — how often is "fresh enough" without over-polling GitHub's API rate
   limits across a fleet of N clients (ties into the fleet-scale cost-tracking gap already flagged
   in `PRODUCT-SLICES.md`'s gap-scan section)?

## Where this fits in the build order

Per `PRODUCT-SLICES.md`, this is Slice 3 (Wave 1) — after Slice 1 (site build) and Slice 2 (first
X-published post, manual topic). Everything else in Slice 3 (`trend_researcher`,
`viral_pattern_research`, the `post_type` taxonomy, `content_strategist`) can proceed without
this piece being resolved — `metrics_researcher`'s GitHub signal is one of three signal sources
feeding `content_strategist`, not a hard blocker for the others.
