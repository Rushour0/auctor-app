"""Six-hour cadence scheduler.

This process only enqueues due content-loop triggers through WorkflowStore. Hermes consumes the
pending triggers and runs the normal QA/approval-gated pipeline; cron never publishes directly.

Cadences are split per platform: ``x`` and ``linkedin`` advance independently through their own
``platform_next_check.<platform>`` windows so a stall on one channel never blocks the other. After
enqueuing, the scheduler makes a best-effort outbound metrics push so downstream dashboards see COGS
without a second poller.
"""

import json

import httpx

from .config import Settings
from .config import get_settings
from .workflow import WorkflowStore


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
    return {
        "enqueued": len(triggers),
        "by_platform": {"x": len(x_triggers), "linkedin": len(linkedin_triggers)},
        "triggers": triggers,
        "pushed": _push_metrics(store, settings),
    }


def main() -> None:
    print(json.dumps(run_once(), default=str))


if __name__ == "__main__":
    main()
