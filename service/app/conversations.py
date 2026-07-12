"""Pure-helper module that maps raw ``fleet_events`` docs onto the docs/08 message contract.

The conversations router uses this to keep its own logic thin: persist events raw (via
``WorkflowStore``), then call :func:`summarize_event` to produce a render-ready message for the
Conversations page (or :func:`to_sse` to stream one over Server-Sent Events).

Deliberately import-light — only ``json`` and ``datetime`` — and holds no database handle, so every
function here is unit-testable with plain dicts. The 8 message types below are the authoritative
contract; do not rename them (see ``.agent/prompts/domains/auctor/`` and docs/08).
"""

from __future__ import annotations

import json
from datetime import datetime

# Raw ``event_type`` (as written into fleet_events) -> (contract message_type, default render text).
# The eight message types on the right are the whole contract; keep this map in sync with them.
EVENT_MESSAGE_MAP: dict[str, tuple[str, str]] = {
    "content_loop_scheduled": ("progress", "Scheduled the next content check."),
    "run_started": ("progress", "Started your agency run."),
    "fleet_started": ("progress", "Started your agency run."),
    "run_completed": ("run_completed", "Completed. Artifacts are ready."),
    "run_failed": ("run_failed", "A run failed and needs attention."),
    "approval_requested": ("approval_request", "Approval is needed before publishing."),
    "artifact_saved": ("artifact_ready", "An artifact is ready."),
    "artifact_ready": ("artifact_ready", "An artifact is ready."),
    "clarification_requested": ("clarification", "More information is needed."),
    "user_message": ("user_message", ""),
    "assistant_message": ("assistant_message", ""),
}

# The eight valid contract message types. Every value produced by :func:`summarize_event` is one of
# these, so callers can filter/route on it without a lookup table of their own.
MESSAGE_TYPES: frozenset[str] = frozenset(
    {
        "progress",
        "run_completed",
        "run_failed",
        "approval_request",
        "artifact_ready",
        "clarification",
        "user_message",
        "assistant_message",
    }
)


def _role_for(message_type: str) -> str:
    """Chat role for a contract message type: only ``user_message`` is authored by the user."""
    return "user" if message_type == "user_message" else "assistant"


def _iso(dt: datetime | str | None) -> str | None:
    """Null-safe ISO-8601 string. Passes through strings and ``None``; formats datetimes."""
    if dt is None:
        return None
    if isinstance(dt, str):
        return dt
    return dt.isoformat()


def summarize_event(event: dict) -> dict:
    """Map one raw ``fleet_events`` doc onto a render-ready contract message.

    Resolution order for ``message_type``/``text``:

    1. Known ``event_type`` -> its ``EVENT_MESSAGE_MAP`` entry.
    2. Unknown ``event_type`` but ``payload.status`` refines it: ``failed`` -> ``run_failed``,
       ``completed`` -> ``run_completed``.
    3. Otherwise fall back to ``('progress', <event_type as text>)``.

    In every case an explicit ``payload.summary`` (or ``payload.text``) overrides the default text.
    """
    event_type = event.get("event_type") or "progress"
    payload = event.get("payload") or {}

    if event_type in EVENT_MESSAGE_MAP:
        message_type, default_text = EVENT_MESSAGE_MAP[event_type]
    else:
        status = payload.get("status")
        if status == "failed":
            message_type, default_text = EVENT_MESSAGE_MAP["run_failed"]
        elif status == "completed":
            message_type, default_text = EVENT_MESSAGE_MAP["run_completed"]
        else:
            message_type, default_text = "progress", event_type

    text = payload.get("summary") or payload.get("text") or default_text

    recorded_at = _iso(event.get("recorded_at"))
    message_id = event.get("idempotency_key") or event.get("event_id") or recorded_at

    return {
        "id": message_id,
        "message_type": message_type,
        "role": _role_for(message_type),
        "text": text,
        "event_type": event_type,
        "client_id": event.get("client_id"),
        "pipeline": event.get("pipeline"),
        "payload": payload,
        "recorded_at": recorded_at,
    }


def to_sse(message: dict) -> str:
    """Frame one render-ready message (from :func:`summarize_event`) as a single SSE record."""
    data = json.dumps(message, default=str)
    return f"id: {message['id']}\nevent: {message['message_type']}\ndata: {data}\n\n"
