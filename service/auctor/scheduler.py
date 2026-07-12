"""Six-hour cadence scheduler.

This process only enqueues due content-loop triggers through WorkflowStore. Hermes consumes the
pending triggers and runs the normal QA/approval-gated pipeline; cron never publishes directly.
"""

import json

from .config import get_settings
from .workflow import WorkflowStore


def run_once() -> dict:
    settings = get_settings()
    store = WorkflowStore(settings)
    store.ensure_indexes()
    triggers = store.enqueue_due_content_loops(
        interval_hours=settings.scheduler_interval_hours,
        batch_size=settings.scheduler_batch_size,
    )
    return {"enqueued": len(triggers), "triggers": triggers}


def main() -> None:
    print(json.dumps(run_once(), default=str))


if __name__ == "__main__":
    main()
