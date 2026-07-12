from __future__ import annotations

from time import perf_counter
from uuid import uuid4

from .collectors.linkup import LinkupCollector
from .workflow import ApprovalRecord, PublishRecord, WorkflowArtifact, WorkflowEvent, WorkflowStore


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
