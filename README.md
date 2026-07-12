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
                            content_strategist, ghostwriter, publisher, engagement_analyst)
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

See `coolify/aws.md` once written for the EC2/Coolify production deploy path.
