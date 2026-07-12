import asyncio
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def test_hermes_mcp_exposes_collector_tools() -> None:
    async def run() -> None:
        script = Path(__file__).resolve().parents[2] / "integrations" / "hermes" / "agency_mcp.py"
        params = StdioServerParameters(command=sys.executable, args=[str(script)])
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.list_tools()
                assert sorted(tool.name for tool in result.tools) == [
                    "acknowledge_workflow_trigger",
                    "enqueue_due_content_loops",
                    "get_collection_status",
                    "get_pending_workflow_triggers",
                    "get_recent_collected_data",
                    "get_workflow_status",
                    "record_workflow_event",
                    "save_approval_record",
                    "save_publish_result",
                    "save_workflow_artifact",
                    "schedule_content_loop",
                    "start_fleet",
                    "sync_github",
                    "sync_industry_trends",
                    "sync_posthog",
                    "verify_linkup_connection",
                    "verify_posthog_connection",
                ]

    asyncio.run(run())
