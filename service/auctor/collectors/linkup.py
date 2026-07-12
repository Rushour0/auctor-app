from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from ..config import Settings, get_settings
from ..memory import AuctorMemory, stable_checksum, utc_now
from ..models import CollectorResult, Provenance, RawRecord, TrendItem

BASE_API = "https://api.linkup.so/v1"
SEARCH_API = f"{BASE_API}/search"
VERSION = "linkup-v1"


class LinkupAPIError(RuntimeError):
    def __init__(self, response: httpx.Response):
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        error = payload.get("error", {}) if isinstance(payload, dict) else {}
        code = error.get("code") or f"HTTP_{response.status_code}"
        message = error.get("message") or response.reason_phrase
        super().__init__(f"Linkup {code}: {message}")
        self.status_code = response.status_code
        self.code = code


def canonical_url(value: str) -> str:
    parts = urlsplit(value)
    query = urlencode(
        [
            (key, item)
            for key, item in parse_qsl(parts.query)
            if not key.lower().startswith("utm_") and key.lower() not in {"fbclid", "gclid"}
        ]
    )
    return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path.rstrip("/"), query, ""))


def parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc).astimezone(timezone.utc)
    except ValueError:
        return None


class LinkupCollector:
    def __init__(
        self,
        memory: AuctorMemory | None = None,
        settings: Settings | None = None,
        client: httpx.Client | None = None,
    ):
        self.settings = settings or get_settings()
        self.memory = memory or AuctorMemory(self.settings)
        self.client = client or httpx.Client(timeout=60)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.settings.linkup_api_key}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        if not response.is_success:
            raise LinkupAPIError(response)

    def verify_authentication(self, workspace_id: str | None = None) -> dict[str, Any]:
        if not self.settings.linkup_api_key:
            raise ValueError("LINKUP_API_KEY is required")
        started_at = utc_now()
        if workspace_id:
            self.memory.save_sync_state(
                workspace_id,
                "linkup",
                "authentication",
                last_started_at=started_at,
                last_error=None,
            )
        try:
            response = self.client.get(
                f"{BASE_API}/credits/balance",
                headers=self._headers(),
            )
            self._raise_for_status(response)
            balance = float(response.json()["balance"])
            result = {"authenticated": True, "credits_balance": balance}
            if workspace_id:
                self.memory.save_sync_state(
                    workspace_id,
                    "linkup",
                    "authentication",
                    last_started_at=started_at,
                    last_completed_at=utc_now(),
                    last_error=None,
                    metadata=result,
                )
            return result
        except Exception as error:
            if workspace_id:
                self.memory.save_sync_state(
                    workspace_id,
                    "linkup",
                    "authentication",
                    last_started_at=started_at,
                    last_error=str(error),
                )
            raise

    def collect(
        self,
        workspace_id: str,
        topics: list[str],
        queries: list[str] | None = None,
        depth: str = "standard",
        max_results: int = 10,
        lookback_days: int = 14,
        include_domains: list[str] | None = None,
        exclude_domains: list[str] | None = None,
    ) -> CollectorResult:
        self.verify_authentication(workspace_id)
        if depth not in {"fast", "standard", "deep"}:
            raise ValueError("Linkup depth must be fast, standard, or deep")
        searches = list(queries or []) + [
            f"Latest significant developments about {topic}. Prioritize recent primary sources."
            for topic in topics
        ]
        searches = list(dict.fromkeys(query.strip() for query in searches if query.strip()))
        if not searches:
            raise ValueError("At least one topic or query is required")

        started_at = utc_now()
        cursor = self.memory.get_cursor(workspace_id, "linkup", "industry-trends")
        from_date = cursor or started_at - timedelta(days=max(1, min(lookback_days, 365)))
        # Linkup rejects fromDate >= toDate (strict "fromDate must be before toDate").
        # A same-day cursor (e.g. a second run within 24h of the first) would otherwise
        # collapse fromDate.date() == toDate.date() and 400 every time. Clamp to at
        # least a 1-day window when that happens.
        if from_date.date() >= started_at.date():
            from_date = started_at - timedelta(days=1)
        self.memory.save_sync_state(
            workspace_id,
            "linkup",
            "industry-trends",
            last_started_at=started_at,
            last_error=None,
        )
        try:
            candidates: dict[str, dict[str, Any]] = {}
            for query in searches:
                request_body: dict[str, Any] = {
                    "q": query,
                    "depth": depth,
                    "outputType": "searchResults",
                    "maxResults": max(1, min(max_results, 100)),
                    "fromDate": from_date.date().isoformat(),
                    "toDate": started_at.date().isoformat(),
                }
                if include_domains:
                    request_body["includeDomains"] = include_domains
                if exclude_domains:
                    request_body["excludeDomains"] = exclude_domains
                response = self.client.post(
                    SEARCH_API,
                    headers=self._headers(),
                    json=request_body,
                )
                self._raise_for_status(response)
                payload = response.json()
                for source in payload.get("results", payload.get("sources", [])):
                    if not source.get("url"):
                        continue
                    url = canonical_url(source["url"])
                    external_id = stable_checksum(url)
                    candidate = candidates.setdefault(
                        external_id,
                        {
                            "url": url,
                            "title": source.get("name") or source.get("title") or url,
                            "content": source.get("content") or source.get("snippet") or "",
                            "published_at": parse_timestamp(
                                source.get("date") or source.get("publishedAt")
                            ),
                            "queries": [],
                            "topics": set(),
                            "sources": [],
                        },
                    )
                    candidate["queries"].append(query)
                    candidate["topics"].update(
                        topic for topic in topics if topic.lower() in query.lower()
                    )
                    candidate["sources"].append(source)

            collected_at = utc_now()
            for external_id, candidate in candidates.items():
                raw_payload = {
                    "queries": candidate["queries"],
                    "topics": sorted(candidate["topics"]),
                    "sources": candidate["sources"],
                }
                raw = RawRecord(
                    workspace_id=workspace_id,
                    source="linkup",
                    external_id=external_id,
                    kind="search-result",
                    payload=raw_payload,
                    checksum=stable_checksum(raw_payload),
                    collected_at=collected_at,
                    occurred_at=candidate["published_at"],
                    source_url=candidate["url"],
                    collector_version=VERSION,
                )
                raw_id = self.memory.save_raw(raw)
                provenance = Provenance(
                    source="linkup",
                    external_id=external_id,
                    raw_record_id=raw_id,
                    collected_at=collected_at,
                    occurred_at=candidate["published_at"],
                    source_url=candidate["url"],
                    collector_version=VERSION,
                )
                self.memory.save_trend(
                    TrendItem(
                        workspace_id=workspace_id,
                        external_id=external_id,
                        query=candidate["queries"][0],
                        title=candidate["title"],
                        url=candidate["url"],
                        content=candidate["content"],
                        topics=sorted(candidate["topics"]),
                        checksum=stable_checksum(
                            [candidate["title"], candidate["content"], candidate["url"]]
                        ),
                        collected_at=collected_at,
                        published_at=candidate["published_at"],
                        publisher=urlsplit(candidate["url"]).netloc.removeprefix("www."),
                        provenance=provenance,
                    )
                )

            completed_at = utc_now()
            self.memory.save_sync_state(
                workspace_id,
                "linkup",
                "industry-trends",
                last_started_at=started_at,
                last_completed_at=completed_at,
                last_error=None,
                cursor=started_at,
                metadata={
                    "searches": searches,
                    "trends": len(candidates),
                    "depth": depth,
                    "checked_from": from_date,
                    "checked_through": started_at,
                    "include_domains": include_domains or [],
                    "exclude_domains": exclude_domains or [],
                },
            )
            return CollectorResult(
                source="linkup",
                workspace_id=workspace_id,
                raw_records=len(candidates),
                trends=len(candidates),
                started_at=started_at,
                completed_at=completed_at,
                details={"checked_from": from_date, "depth": depth},
            )
        except Exception as error:
            self.memory.save_sync_state(
                workspace_id,
                "linkup",
                "industry-trends",
                last_started_at=started_at,
                last_error=str(error),
            )
            raise
