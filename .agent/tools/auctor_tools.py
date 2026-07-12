#!/usr/bin/env python3
"""Generic Auctor tool dispatcher CLI.

    python3 .agent/tools/auctor_tools.py <tool_name>

Reads one JSON object on stdin (matching that tool's manifest ``input_schema``) and writes one
JSON object on stdout (matching its ``output_schema``), per every manifest's ``command`` field
(``.agent/tools/manifests/<tool_name>.json``).

This is the FIRST tool implementation in the repo. Its calling convention is meant to be reused by
every future tool (``linkup_client_research``, ``github_activity_research``, etc.) — new tools are
added by writing a handler function and registering it in ``HANDLERS`` below, not by inventing a
new CLI shape.

Each handler is an ``async def handler(payload: dict) -> dict`` coroutine. The dispatcher takes
care of: reading stdin, resolving the DB handle, running the coroutine, and writing stdout.
Handlers must never raise for expected/business failures (missing approval, invalid id, ...) —
they catch those and return an output-schema-shaped ``status: "failed"`` dict instead. Only
programmer errors should propagate as uncaught exceptions.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

# Make the repo's `service` package importable when this script is invoked directly (it lives
# under .agent/tools/, outside the `service` package tree).
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from service.app.db import get_db  # noqa: E402
from service.auctor.collectors.linkup import LinkupCollector  # noqa: E402
from service.auctor.workflow import WorkflowEvent, WorkflowStore  # noqa: E402

Handler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]

HANDLERS: dict[str, Handler] = {}


def tool(name: str) -> Callable[[Handler], Handler]:
    """Decorator: register ``handler`` under ``name`` in the dispatcher's tool registry."""

    def register(handler: Handler) -> Handler:
        HANDLERS[name] = handler
        return handler

    return register


@tool("publish_x")
async def _publish_x(payload: dict[str, Any]) -> dict[str, Any]:
    from service.app.tools import publish_x

    return await publish_x.run(get_db(), payload)


@tool("x_engagement_metrics")
async def _x_engagement_metrics(payload: dict[str, Any]) -> dict[str, Any]:
    from service.app.tools import x_engagement_metrics

    return await x_engagement_metrics.run(get_db(), payload)


@tool("record_fleet_event")
async def _record_fleet_event(payload: dict[str, Any]) -> dict[str, Any]:
    event = WorkflowEvent.model_validate({
        "workspace_id": payload.get("workspace_id") or os.getenv("AUCTOR_WORKSPACE_ID", "personal"),
        "fleet_id": payload["fleet_id"], "client_id": payload.get("client_id"),
        "pipeline": payload.get("pipeline"), "run_id": payload.get("run_id"),
        "stage_run_id": payload.get("stage_run_id"), "agent": payload.get("agent"),
        "stage": payload.get("stage"), "outcome": payload.get("outcome"),
        "event_type": payload["event_type"], "payload": payload.get("payload", {}),
        "idempotency_key": payload.get("idempotency_key")
        or f"{payload['fleet_id']}:{payload['event_type']}:{payload.get('client_id', 'fleet')}",
    })
    return WorkflowStore().record_event(event)


@tool("linkup_client_research")
async def _linkup_client_research(payload: dict[str, Any]) -> dict[str, Any]:
    workspace_id = payload.get("workspace_id") or os.getenv("AUCTOR_WORKSPACE_ID", "personal")
    topics = [payload["name"], *payload.get("topics", [])]
    return LinkupCollector().collect(workspace_id=workspace_id, topics=topics).model_dump(mode="json")


@tool("linkup_trend_research")
async def _linkup_trend_research(payload: dict[str, Any]) -> dict[str, Any]:
    workspace_id = payload.get("workspace_id") or os.getenv("AUCTOR_WORKSPACE_ID", "personal")
    icp = payload.get("icp")
    topics = icp if isinstance(icp, list) else [str(icp)]
    return LinkupCollector().collect(workspace_id=workspace_id, topics=topics).model_dump(mode="json")


async def _dispatch(tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    handler = HANDLERS.get(tool_name)
    if handler is None:
        return {
            "status": "failed",
            "error_message": f"Unknown tool_name={tool_name!r}. Known tools: {sorted(HANDLERS)}",
        }
    return await handler(payload)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(
            json.dumps({"status": "failed", "error_message": "usage: auctor_tools.py <tool_name>"})
        )
        return 2

    tool_name = argv[1]
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        print(json.dumps({"status": "failed", "error_message": f"invalid JSON on stdin: {exc}"}))
        return 2

    result = asyncio.run(_dispatch(tool_name, payload))
    print(json.dumps(result, default=str))
    return 0 if result.get("status") != "failed" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
