from __future__ import annotations

from time import perf_counter
from typing import Any
from uuid import uuid4

from .collectors.linkup import LinkupCollector
from .workflow import ApprovalRecord, PublishRecord, WorkflowArtifact, WorkflowEvent, WorkflowStore


def derive_topic(pipeline: dict[str, Any]) -> str | None:
    """Pull a real content topic from what the client actually told us at onboarding
    (client_pipelines.intake.self_reported_context, written by
    OnboardingSubmission.to_fleet_intake) rather than requiring a manually-typed
    topic. First content_topics entry wins (that's the client's own stated
    interest); known_for is the fallback when no topics were given. None means
    "nothing usable" — the caller must not invent a topic to fill the gap."""
    context = (pipeline.get("intake") or {}).get("self_reported_context") or {}
    positioning = context.get("positioning") or {}
    topics = positioning.get("content_topics") or []
    if topics:
        return str(topics[0]).strip() or None
    known_for = positioning.get("known_for")
    if known_for:
        return str(known_for).strip() or None
    return None


class ContentAgencyRunner:
    """Executable, approval-gated content job using live research and a real web surface."""

    def __init__(self, store: WorkflowStore | None = None):
        self.store = store or WorkflowStore()
        self.store.ensure_indexes()

    def _event(
        self,
        *,
        workspace_id: str,
        fleet_id: str,
        client_id: str,
        run_id: str,
        stage: str,
        agent: str,
        outcome: str,
        duration_ms: int,
        cost_usd: float = 0.0,
        payload: dict | None = None,
    ) -> None:
        self.store.record_event(
            WorkflowEvent(
                workspace_id=workspace_id,
                fleet_id=fleet_id,
                client_id=client_id,
                pipeline="content_loop",
                run_id=run_id,
                stage_run_id=f"{run_id}:{stage}:1",
                agent=agent,
                stage=stage,
                event_type=f"stage.{outcome}",
                outcome=outcome,
                duration_ms=duration_ms,
                cost_usd=cost_usd,
                idempotency_key=f"{run_id}:{stage}:1:{outcome}",
                payload=payload or {},
            )
        )

    def run_until_approval(
        self, workspace_id: str, fleet_id: str, client_id: str, topic: str
    ) -> dict:
        run_id = f"run_{uuid4().hex[:12]}"
        pipeline = self.store.db.client_pipelines.find_one(
            {
                "workspace_id": workspace_id,
                "fleet_id": fleet_id,
                "client_id": client_id,
                "pipeline": "content_loop",
            }
        )
        if not pipeline:
            raise ValueError("content-loop pipeline not found")
        name = pipeline.get("intake", {}).get("name", client_id)

        started = perf_counter()
        result = LinkupCollector().collect(
            workspace_id=workspace_id,
            topics=[topic],
            depth="standard",
            max_results=5,
        )
        research_ms = round((perf_counter() - started) * 1000)
        memory = LinkupCollector().memory
        trends = list(
            memory.db.trend_items.find({"workspace_id": workspace_id}, {"_id": 0}).sort(
                "collected_at", -1
            )
        )[:5]
        self._event(
            workspace_id=workspace_id,
            fleet_id=fleet_id,
            client_id=client_id,
            run_id=run_id,
            stage="research",
            agent="trend_researcher",
            outcome="succeeded",
            duration_ms=research_ms,
            payload={"sources_found": len(trends), "collector": result.source},
        )
        if not trends:
            raise ValueError("live research returned no usable sources")

        started = perf_counter()
        source = trends[0]
        title = str(source.get("title") or topic).strip()
        url = str(source.get("url") or "")
        draft = (
            f"A development worth watching in {topic}: {title}\n\n"
            f"My takeaway: the useful question is not whether the trend is real, but what "
            f"builders can verify and apply next. I’m following the evidence as it develops.\n\n"
            f"Source: {url}"
        )
        draft_id = f"draft_{uuid4().hex[:12]}"
        self.store.save_artifact(
            WorkflowArtifact(
                workspace_id=workspace_id,
                fleet_id=fleet_id,
                client_id=client_id,
                pipeline="content_loop",
                artifact_type="post_draft",
                artifact_id=draft_id,
                producer="voice_writer",
                payload={"text": draft, "topic": topic, "source_refs": [url], "client_name": name},
                source_refs=[url],
            )
        )
        draft_ms = round((perf_counter() - started) * 1000)
        self._event(
            workspace_id=workspace_id,
            fleet_id=fleet_id,
            client_id=client_id,
            run_id=run_id,
            stage="draft",
            agent="voice_writer",
            outcome="succeeded",
            duration_ms=draft_ms,
            payload={"artifact_id": draft_id},
        )

        started = perf_counter()
        qa_passed = bool(url.startswith("http") and "Source:" in draft and len(draft) <= 1000)
        qa_ms = round((perf_counter() - started) * 1000)
        self._event(
            workspace_id=workspace_id,
            fleet_id=fleet_id,
            client_id=client_id,
            run_id=run_id,
            stage="voice_qa",
            agent="voice_qa",
            outcome="succeeded" if qa_passed else "failed",
            duration_ms=qa_ms,
            payload={"claim_sourcing": qa_passed, "artifact_id": draft_id},
        )
        if not qa_passed:
            raise ValueError("draft failed sourcing QA")

        approval_id = f"approval_{uuid4().hex[:12]}"
        self.store.save_approval(
            ApprovalRecord(
                workspace_id=workspace_id,
                fleet_id=fleet_id,
                client_id=client_id,
                pipeline="content_loop",
                approval_id=approval_id,
                artifact_id=draft_id,
                channel="web",
                status="pending",
                decision_metadata={"run_id": run_id, "topic": topic},
            )
        )
        self._event(
            workspace_id=workspace_id,
            fleet_id=fleet_id,
            client_id=client_id,
            run_id=run_id,
            stage="approval",
            agent="manager",
            outcome="blocked",
            duration_ms=0,
            payload={"approval_id": approval_id, "artifact_id": draft_id},
        )
        return {
            "run_id": run_id,
            "draft_id": draft_id,
            "approval_id": approval_id,
            "status": "awaiting_approval",
            "draft": draft,
            "sources": [url],
        }

    def approve_and_publish_web(self, workspace_id: str, approval_id: str) -> dict:
        approval = self.store.db.approval_requests.find_one(
            {"workspace_id": workspace_id, "approval_id": approval_id}
        )
        if not approval or approval.get("status") != "pending":
            raise ValueError("pending approval not found")
        run_id = approval.get("decision_metadata", {}).get("run_id")
        artifact = self.store.db.workflow_artifacts.find_one(
            {"workspace_id": workspace_id, "artifact_id": approval["artifact_id"]}, {"_id": 0}
        )
        if not artifact or not run_id:
            raise ValueError("approved artifact or run missing")
        approved = ApprovalRecord.model_validate(
            {
                **approval,
                "status": "approved",
                "decision_metadata": {**approval.get("decision_metadata", {}), "decision": "web"},
            }
        )
        self.store.save_approval(approved)
        post_id = f"post_{uuid4().hex[:12]}"
        self.store.db.public_deliveries.update_one(
            {"workspace_id": workspace_id, "post_id": post_id},
            {
                "$set": {
                    "workspace_id": workspace_id,
                    "post_id": post_id,
                    "client_id": approval["client_id"],
                    "run_id": run_id,
                    "text": artifact["payload"]["text"],
                    "source_refs": artifact.get("source_refs", []),
                    "status": "published",
                }
            },
            upsert=True,
        )
        self.store.save_publish(
            PublishRecord(
                workspace_id=workspace_id,
                fleet_id=approval["fleet_id"],
                client_id=approval["client_id"],
                post_id=post_id,
                platform="web",
                status="published",
                platform_post_id=post_id,
                post_url=f"/public/posts/{post_id}",
                provider_response={"surface": "auctor-web"},
            )
        )
        self._event(
            workspace_id=workspace_id,
            fleet_id=approval["fleet_id"],
            client_id=approval["client_id"],
            run_id=run_id,
            stage="publish",
            agent="publisher",
            outcome="succeeded",
            duration_ms=0,
            payload={"post_id": post_id, "post_url": f"/public/posts/{post_id}"},
        )
        self.store.record_event(
            WorkflowEvent(
                workspace_id=workspace_id,
                fleet_id=approval["fleet_id"],
                client_id=approval["client_id"],
                pipeline="content_loop",
                run_id=run_id,
                agent="manager",
                stage="delivery",
                event_type="run.completed",
                outcome="succeeded",
                idempotency_key=f"{run_id}:completed",
                payload={"post_id": post_id, "approval_id": approval_id},
            )
        )
        return {
            "run_id": run_id,
            "post_id": post_id,
            "status": "published",
            "post_url": f"/public/posts/{post_id}",
        }

    def consume_trigger(self, trigger: dict[str, Any]) -> dict[str, Any]:
        """The missing link between the scheduler and a real run: given ONE pending
        workflow_triggers row, derive a topic from the client's own onboarding data
        (derive_topic, never a hardcoded/manual topic) and run it up to the approval
        gate. Always resolves the trigger to a terminal status (completed/failed) —
        never leaves it pending, so it can't be silently re-picked-up forever.

        Cron still never publishes (per scheduler.py's own docstring): this stops at
        awaiting_approval, identically to the manual POST /api/content-jobs path.
        """
        workspace_id, client_id, fleet_id, trigger_id = (
            trigger["workspace_id"],
            trigger["client_id"],
            trigger["fleet_id"],
            trigger["trigger_id"],
        )
        pipeline = self.store.db.client_pipelines.find_one(
            {
                "workspace_id": workspace_id,
                "fleet_id": fleet_id,
                "client_id": client_id,
                "pipeline": "content_loop",
            }
        )
        topic = derive_topic(pipeline) if pipeline else None
        if not topic:
            self.store.acknowledge_trigger(workspace_id, trigger_id, "failed")
            return {"trigger_id": trigger_id, "status": "failed", "reason": "no_topic_available"}

        try:
            result = self.run_until_approval(workspace_id, fleet_id, client_id, topic)
        except ValueError as error:
            self.store.acknowledge_trigger(workspace_id, trigger_id, "failed")
            return {"trigger_id": trigger_id, "status": "failed", "reason": str(error)}

        self.store.acknowledge_trigger(workspace_id, trigger_id, "completed")
        # trigger_id/status set AFTER **result so they win over result's own "status"
        # (awaiting_approval) — this reports the TRIGGER's resolution, not the run's.
        return {**result, "trigger_id": trigger_id, "status": "completed"}
