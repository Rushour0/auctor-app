"""Live MongoDB smoke test for the Hermes workflow MCP.

Run explicitly; this is intentionally not collected by pytest because it writes labeled test data
to the configured MongoDB database.
"""

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main() -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    workspace_id = f"smoke-hermes-{stamp}"
    fleet_id = f"fleet-smoke-{stamp}"
    client_id = "client-smoke-kriti"
    script = Path(__file__).resolve().parents[2] / "integrations" / "hermes" / "agency_mcp.py"
    params = StdioServerParameters(command=sys.executable, args=[str(script)])

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            calls = [
                (
                    "start_fleet",
                    {
                        "intake": {
                            "workspace_id": workspace_id,
                            "fleet_id": fleet_id,
                            "request": "Live Hermes persistence smoke test",
                            "clients": [
                                {
                                    "client_id": client_id,
                                    "name": "Kriti Agarwal (smoke test)",
                                    "linkedin_url": "https://linkedin.com/in/test-only",
                                    "audience": ["investors", "prospective customers"],
                                    "self_reported_context": {
                                        "role": "test-only",
                                        "startup": "test-only",
                                    },
                                }
                            ],
                        }
                    },
                ),
                (
                    "save_workflow_artifact",
                    {
                        "artifact": {
                            "workspace_id": workspace_id,
                            "fleet_id": fleet_id,
                            "client_id": client_id,
                            "pipeline": "site_build",
                            "artifact_type": "client_research",
                            "artifact_id": f"research-{stamp}",
                            "producer": "researcher",
                            "payload": {"usable_claim_count": 0, "usable_voice_excerpt_count": 0},
                        }
                    },
                ),
                (
                    "record_workflow_event",
                    {
                        "event": {
                            "workspace_id": workspace_id,
                            "fleet_id": fleet_id,
                            "client_id": client_id,
                            "pipeline": "site_build",
                            "event_type": "client_research_completed",
                            "idempotency_key": f"{fleet_id}:research-completed",
                            "payload": {"status": "qa", "cost_usd": 0.0},
                        }
                    },
                ),
                (
                    "save_approval_record",
                    {
                        "approval": {
                            "workspace_id": workspace_id,
                            "fleet_id": fleet_id,
                            "client_id": client_id,
                            "pipeline": "site_build",
                            "approval_id": f"approval-{stamp}",
                            "artifact_id": f"build-{stamp}",
                            "status": "pending",
                        }
                    },
                ),
                (
                    "save_publish_result",
                    {
                        "publish": {
                            "workspace_id": workspace_id,
                            "fleet_id": fleet_id,
                            "client_id": client_id,
                            "post_id": f"post-{stamp}",
                            "platform": "x",
                            "status": "not_applicable",
                            "provider_response": {"smoke_test": True},
                        }
                    },
                ),
            ]
            for name, arguments in calls:
                result = await session.call_tool(name, arguments)
                if result.isError:
                    raise RuntimeError(f"{name} failed: {result.content}")

            due_at = datetime.now(timezone.utc).isoformat()
            scheduled = await session.call_tool(
                "schedule_content_loop",
                {
                    "workspace_id": workspace_id,
                    "client_id": client_id,
                    "next_content_check_at": due_at,
                },
            )
            if scheduled.isError:
                raise RuntimeError(f"schedule failed: {scheduled.content}")
            enqueued = await session.call_tool(
                "enqueue_due_content_loops",
                {"workspace_id": workspace_id, "interval_hours": 6, "batch_size": 10},
            )
            if enqueued.isError:
                raise RuntimeError(f"enqueue failed: {enqueued.content}")
            enqueued_text = next(item.text for item in enqueued.content if hasattr(item, "text"))
            enqueued_payload = json.loads(enqueued_text)
            if enqueued_payload["enqueued"] != 1:
                raise AssertionError(f"expected one scheduled trigger: {enqueued_payload}")
            duplicate = await session.call_tool(
                "enqueue_due_content_loops",
                {"workspace_id": workspace_id, "interval_hours": 6, "batch_size": 10},
            )
            duplicate_text = next(item.text for item in duplicate.content if hasattr(item, "text"))
            if json.loads(duplicate_text)["enqueued"] != 0:
                raise AssertionError("same cadence window was enqueued more than once")

            status_result = await session.call_tool(
                "get_workflow_status", {"workspace_id": workspace_id, "fleet_id": fleet_id}
            )
            if status_result.isError:
                raise RuntimeError(f"status failed: {status_result.content}")
            text = next(item.text for item in status_result.content if hasattr(item, "text"))
            status = json.loads(text)
            expected = {
                "fleets": 1,
                "pipelines": 2,
                "artifacts": 1,
                "events": 2,
                "approvals": 1,
                "posts": 1,
                "triggers": 1,
            }
            if status["counts"] != expected:
                raise AssertionError(f"unexpected counts: {status['counts']} != {expected}")
            print(json.dumps({"workspace_id": workspace_id, "fleet_id": fleet_id, **status}, default=str))


if __name__ == "__main__":
    asyncio.run(main())
