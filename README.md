# Auctor — AI personal branding agency (Hermes × Fabri)

Monorepo for Auctor's real product: the Hermes/Fabri control-plane app plus the `.agent/` domain
pack that runs the agent pipelines. Deploys to `app-auctor.rushour0.com` (frontend) and
`api-auctor.rushour0.com` (service) via Coolify on EC2, modeled on `ludexel-app`'s Coolify setup.

Sibling repo: [`auctor-landing`](https://github.com/Rushour0/auctor-landing) is the separate
static marketing site at `auctor.rushour0.com` — this repo is the actual agency product.

## What Auctor does

Researches a client (LinkedIn, site, resume), builds them a positioned personal-brand website
with a voice + video intro, then runs an ongoing content loop: watches the client's own GitHub
activity, product growth, and industry trends for signal, drafts LinkedIn/X posts in the client's
real voice, sends them to WhatsApp for a one-reply approval, and publishes once approved.

## Repository map

```
frontend/               React app — composer, runs panel, fleet roll-up, metrics, login
service/                FastAPI backend — agency API, Mongo persistence, billing
docker/                 frontend.Dockerfile + service.Dockerfile (two separately deployable images)
compose.yml             production compose (mongo + both app images), mirrors ludexel-app's shape
coolify/                setup.sh / bootstrap.sh / aws.md — EC2 + Coolify deploy, adapted for
                         Amazon Linux 2023 / aarch64 (see aws.md for the exact deltas from ludexel-app)
.agent/                 the Hermes+Fabri domain pack
  prompts/domains/auctor/
    manager.md           fleet-lead prompt for the auctor domain
    policy.md             approval rules, anti-fabrication rules, the scheduling-fork write-up
    artifacts.md          field-name catalogue every specialist's output must match verbatim
    specialists/           one file per specialist (researcher, brand_strategist, copywriter,
                            builder, voice_qa, deployer, metrics_researcher, trend_researcher,
                            signal_summarizer, voice_writer, publisher, engagement_analyst;
                            content_strategist + ghostwriter retained for legacy traces)
    evals/cases.json       regression cases
  tools/manifests/        one JSON manifest per tool (Linkup, Cloudflare, ElevenLabs, HeyGen,
                           OpenAI image, GitHub, LinkedIn, Twitter/X, WhatsApp, Dodo Payments)
schemas/                 JSON Schemas for runs/artifacts/events/signals/subscriptions
integrations/hermes/     agency_mcp.py stdio bridge + the WhatsApp channel adapter
```

## Status

Scaffolded — directory shape only. The domain pack, tools, and app code are being built slice by
slice (see the plan this repo was scaffolded from: site-build pipeline first, then WhatsApp
approval + single-platform content loop, then metrics/trend sourcing, then Twitter/X +
image/video formats, then Dodo billing last).

## Local dev

```bash
cp .env.example .env   # fill in real values — never commit .env
```

### Source collectors

The Slice 3 ingestion foundation lives in `service/auctor/collectors/`:

- GitHub: PRs merged into `main` since the previous successful check, including PR copy,
  commit messages, changed files, available patches, and merge timestamps.
- Linkup: deduplicated industry sources with preserved URLs and provenance.
- PostHog: raw product events and per-event count observations since the previous successful
  check.

PostHog uses a read-only personal API key for the initial single-project deployment. The
`verify_posthog_connection` Hermes tool checks `/api/users/@me/` and access to the configured
project before collection, and stores only non-secret connection metadata. A customer-facing
multi-tenant release should replace this credential mode with PostHog OAuth.

Linkup uses bearer-key authentication. `verify_linkup_connection` validates the key through the
credit-balance endpoint without spending a search request. Trend searches apply an incremental
date window from the previous successful cursor, support include/exclude domain filters, remove
tracking parameters, deduplicate canonical URLs, and preserve the original result payload.
The deployed service exposes the same integration at `POST /api/integrations/linkup/verify` and
`POST /api/integrations/linkup/sync`; the sync body accepts `workspace_id`, topics or explicit
queries, search depth, result/lookback limits, and optional domain filters.

All collectors write raw evidence, normalized signals, and sync cursors to MongoDB. Hermes calls
them through the stdio bridge at `integrations/hermes/agency_mcp.py`; its example configuration is
next to that file. The reusable Hermes skill is `.agent/skills/auctor-data-collectors/SKILL.md`.

After each collection run, `signal_summarizer` reads the exact preceding six-hour window through
`get_recent_collected_data`, deduplicates the raw and normalized evidence, and produces a short
list of post-worthy changes, achievements, product signals, and news. `voice_writer` then selects
the strongest sourced topic and creates one text draft in the client's stored voice before the
existing voice-QA and approval gates run.

Run the service locally after installing `service/pyproject.toml`:

```bash
.venv/bin/pip install -e 'service[dev]'
uvicorn auctor.main:app --app-dir service --reload
.venv/bin/python integrations/hermes/agency_mcp.py
```

See `coolify/aws.md` once written for the EC2/Coolify production deploy path.

### Content-loop scheduler

`python -m service.auctor.scheduler` atomically enqueues due content-loop triggers in MongoDB.
Run it every six hours using `docker/auctor-scheduler.cron` or a Coolify Scheduled Task with the
same command. Concurrent invocations are safe: advancing `next_content_check_at` is an atomic
claim, and every cadence window has a deterministic unique trigger id. Hermes reads pending
triggers through `get_pending_workflow_triggers`, marks each `running`, and finally acknowledges
it as `completed` or `failed`. The scheduler itself never drafts or publishes content.
