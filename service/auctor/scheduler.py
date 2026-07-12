"""Six-hour cadence scheduler.

This process enqueues due content-loop triggers through WorkflowStore, then immediately consumes
each one via ContentAgencyRunner.consume_trigger — real research + drafting up to the approval
gate, topic derived from the client's own onboarding data. Cron never publishes directly: the
consumer stops at awaiting_approval, identically to the manual POST /api/content-jobs path. A
per-trigger consume failure never blocks the rest of the batch or the other platform (fleet
isolation) — each trigger is resolved to completed/failed independently.

Cadences are split per platform: ``x`` and ``linkedin`` advance independently through their own
``platform_next_check.<platform>`` windows so a stall on one channel never blocks the other. After
enqueuing and consuming, the scheduler makes a best-effort outbound metrics push so downstream
dashboards see COGS without a second poller.
"""

import json

import httpx

from .config import Settings
from .config import get_settings
from .runner import ContentAgencyRunner
from .workflow import WorkflowStore


def _consume(store: WorkflowStore, triggers: list[dict]) -> list[dict]:
    """Consume each enqueued trigger independently — one client's research/drafting
    failure must never stop another client's trigger from being attempted."""
    runner = ContentAgencyRunner(store=store)
    results = []
    for trigger in triggers:
        try:
            results.append(runner.consume_trigger(trigger))
        except Exception as error:  # noqa: BLE001 - never let one bad trigger kill the batch
            results.append(
                {"trigger_id": trigger["trigger_id"], "status": "failed", "reason": str(error)}
            )
    return results


def _push_metrics(store: WorkflowStore, settings: Settings) -> bool:
    """Best-effort outbound metrics push. Never raises: a webhook failure must not break enqueuing."""
    if not settings.metrics_webhook_url:
        return False
    try:
        # Imported lazily to avoid any app<->auctor import cycle at module load time.
        from service.app.metrics_aggregations import build_metrics_payload

        envelope = {
            "schema": "auctor.metrics.v1",
            "source": "scheduler",
            "payload": build_metrics_payload(store.db, settings.auctor_workspace_id),
        }
        response = httpx.post(
            settings.metrics_webhook_url,
            content=json.dumps(envelope, default=str),
            headers={"content-type": "application/json"},
            timeout=settings.metrics_webhook_timeout_seconds,
        )
        return response.is_success
    except Exception:
        return False


def run_once() -> dict:
    settings = get_settings()
    store = WorkflowStore(settings)
    store.ensure_indexes()
    x_triggers = store.enqueue_due_content_loops(
        platform="x",
        interval_hours=(settings.scheduler_interval_hours_x or settings.scheduler_interval_hours),
        batch_size=settings.scheduler_batch_size,
    )
    linkedin_triggers = store.enqueue_due_content_loops(
        platform="linkedin",
        interval_hours=(
            settings.scheduler_interval_hours_linkedin or settings.scheduler_interval_hours
        ),
        batch_size=settings.scheduler_batch_size,
    )
    triggers = x_triggers + linkedin_triggers
    consumed = _consume(store, triggers)
    return {
        "enqueued": len(triggers),
        "consumed": consumed,
        "by_platform": {"x": len(x_triggers), "linkedin": len(linkedin_triggers)},
        "triggers": triggers,
        "pushed": _push_metrics(store, settings),
    }


def main() -> None:
    print(json.dumps(run_once(), default=str))


if __name__ == "__main__":
    main()
