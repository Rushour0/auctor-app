---
name: auctor-data-collectors
description: Collect GitHub main-branch merges, Linkup industry trends, and PostHog product metrics into Auctor's MongoDB evidence store. Use for scheduled syncs, backfills, freshness checks, and source-signal troubleshooting.
---

# Auctor Data Collectors

Use the `auctor-memory` MCP tools. MongoDB is the durable evidence store; conversational memory is not a substitute.

## Workflow

1. Identify the `workspace_id` and call `get_collection_status`.
2. Run only the requested collectors:
   - `sync_github`: PR title, description, commit messages, code changes, and merge timestamp for PRs merged into `main` since the previous successful check.
   - `sync_industry_trends`: cited Linkup sources for explicit industry topics.
   - `verify_linkup_connection`: validate the Linkup key and inspect remaining credits without running a search.
   - `sync_posthog`: raw PostHog product events plus per-event counts since the previous successful check.
   - `verify_posthog_connection`: validate PostHog authentication and project access before the first sync or after credential changes.
3. Call `get_collection_status` again.
4. Report counts, checked time ranges, truncation warnings, and failures.

## Guardrails

- Never mix workspace IDs.
- Keep GitHub repository scope explicit for production runs.
- Do not expose credentials or private code patches in chat.
- Do not infer business outcomes from commit messages alone.
- Treat Linkup results as evidence, preserving their URLs.
- If PostHog reaches its row limit, increase the limit and rerun before advancing its cursor.
- Collection never authorizes drafting, approval, or publishing.
