"""Public, no-signup "suggest my posts" demo — the one unauthenticated flow in this
service by design (see routers/demo.py for the rate-limited route wrapping this).

Two real calls, both fail-loud on a missing key rather than fabricating a result:

1. Linkup search (same provider/pattern service/auctor/collectors/linkup.py already
   uses for the real researcher/trend_researcher specialists) — sourced, public web
   findings about the given LinkedIn/X handle. Never a raw profile scrape; Linkup is
   a search API, not a scraper, which is the whole reason it was picked here over
   directly hitting linkedin.com/x.com (see policy.md ANTI-FABRICATION + the
   AskUserQuestion decision this session: Linkup over direct scraping).
2. OpenAI Chat Completions API — drafts 3 short post suggestions strictly from the
   findings returned above. The prompt explicitly forbids inventing a claim that
   isn't in the findings, mirroring the real product's claim_sourcing gate — this
   demo exists to prove the provenance mechanic, so it must not fabricate either.

No Mongo writes here — that's the router's job (rate-limit bookkeeping only, no
raw findings/suggestions are persisted for a stranger's public lookup).
"""

from __future__ import annotations

from typing import Any

import httpx

from .config import settings

LINKUP_SEARCH_URL = "https://api.linkup.so/v1/search"
OPENAI_CHAT_COMPLETIONS_URL = "https://api.openai.com/v1/chat/completions"
OPENAI_MODEL = "gpt-5.6-terra"


class DemoError(RuntimeError):
    """Raised for any failure in the public demo flow. ``kind`` is a stable code the
    router maps to an HTTP status; ``message`` is safe to show the caller verbatim."""

    def __init__(self, kind: str, message: str) -> None:
        self.kind = kind
        self.message = message
        super().__init__(message)


def _handle_query(linkedin_url: str | None, twitter_handle: str | None) -> str:
    parts: list[str] = []
    if linkedin_url:
        parts.append(f"the person at LinkedIn profile {linkedin_url}")
    if twitter_handle:
        handle = twitter_handle.lstrip("@")
        parts.append(f"the X/Twitter account @{handle}")
    subject = " and ".join(parts)
    return (
        f"Recent public posts, professional achievements, and shipped work by {subject}. "
        "Prioritize their own posts and primary sources over third-party mentions."
    )


def research_handle(
    linkedin_url: str | None,
    twitter_handle: str | None,
    client: httpx.Client | None = None,
) -> list[dict[str, Any]]:
    """Real Linkup search for public signal about the given handle(s).

    Returns a list of ``{claim, source_url}`` findings — deliberately the same shape
    ``client_research.achievement_signals`` uses, so the suggestion prompt below can
    apply the identical claim_sourcing discipline the real pipeline uses.
    """
    if not settings.linkup_api_key:
        raise DemoError("missing_api_key", "Search is temporarily unavailable.")
    if not linkedin_url and not twitter_handle:
        raise DemoError("missing_handle", "Provide a LinkedIn URL or an X/Twitter handle.")

    owns_client = client is None
    client = client or httpx.Client(timeout=30)
    try:
        response = client.post(
            LINKUP_SEARCH_URL,
            headers={
                "Authorization": f"Bearer {settings.linkup_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "q": _handle_query(linkedin_url, twitter_handle),
                "depth": "standard",
                "outputType": "searchResults",
            },
        )
        if not response.is_success:
            raise DemoError("search_failed", "Couldn't find public data for that handle.")
        payload = response.json()
    finally:
        if owns_client:
            client.close()

    results = payload.get("results") or []
    findings = [
        {"claim": str(r.get("name") or r.get("title") or "")[:280], "source_url": r.get("url", "")}
        for r in results
        if r.get("url")
    ][:8]
    if not findings:
        raise DemoError("no_signal", "No public posts or achievements found for that handle yet.")
    return findings


def draft_suggestions(
    findings: list[dict[str, Any]],
    client: httpx.Client | None = None,
) -> list[dict[str, str]]:
    """Real OpenAI call: 3 post suggestions, each citing one of ``findings`` by index.

    The model is instructed to never state a claim absent from ``findings`` — the same
    zero-tolerance claim_sourcing rule the real ghostwriter/voice_qa pipeline enforces,
    applied here at the prompt level since this demo has no verifier stage of its own.
    """
    if not settings.openai_api_key:
        raise DemoError("missing_api_key", "Suggestions are temporarily unavailable.")

    numbered = "\n".join(f"{i}. {f['claim']} ({f['source_url']})" for i, f in enumerate(findings))
    prompt = f"""Here are real, sourced findings about a person, numbered:
{numbered}

Suggest exactly 3 short X/Twitter post ideas for this person, each grounded in ONE of the
findings above by its number. Every post MUST cite a finding_index for a finding that
actually supports it — never state a fact, number, or achievement not present in the
findings list. If a post is generic framing with no specific claim, that's fine, but never
invent a claim to fill a post out.

Respond with ONLY a JSON object, no prose, no markdown fences:
{{"suggestions": [{{"post_type": "ship-announcement|hot-take|build-in-public|milestone",
"topic": "string", "draft": "string, under 280 chars", "finding_index": 0}}]}}"""

    owns_client = client is None
    client = client or httpx.Client(timeout=30)
    try:
        response = client.post(
            OPENAI_CHAT_COMPLETIONS_URL,
            headers={
                "Authorization": f"Bearer {settings.openai_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": OPENAI_MODEL,
                "response_format": {"type": "json_object"},
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        if not response.is_success:
            raise DemoError("suggest_failed", "Couldn't generate suggestions right now.")
        payload = response.json()
    finally:
        if owns_client:
            client.close()

    import json

    text = payload["choices"][0]["message"]["content"]
    try:
        suggestions = json.loads(text)["suggestions"]
    except (ValueError, KeyError, TypeError) as error:
        raise DemoError("suggest_failed", "Couldn't generate suggestions right now.") from error

    out: list[dict[str, str]] = []
    for item in suggestions[:3]:
        idx = item.get("finding_index")
        if not isinstance(idx, int) or not (0 <= idx < len(findings)):
            continue  # drop any suggestion that doesn't cite a real finding
        out.append(
            {
                "post_type": str(item.get("post_type", "build-in-public")),
                "topic": str(item.get("topic", ""))[:200],
                "draft": str(item.get("draft", ""))[:400],
                "source_url": findings[idx]["source_url"],
            }
        )
    if not out:
        raise DemoError("no_signal", "Couldn't ground any suggestion in real findings.")
    return out


def run_public_suggestion(linkedin_url: str | None, twitter_handle: str | None) -> dict[str, Any]:
    """The full demo flow: research -> draft. One entry point for the router."""
    findings = research_handle(linkedin_url, twitter_handle)
    suggestions = draft_suggestions(findings)
    return {"suggestions": suggestions, "sources": [f["source_url"] for f in findings]}
