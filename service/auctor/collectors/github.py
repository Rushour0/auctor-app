from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

import httpx

from ..config import Settings, get_settings
from ..github_auth import GitHubAuth
from ..memory import AuctorMemory, stable_checksum, utc_now
from ..models import CollectorResult, MemoryEvent, Provenance, RawRecord

API = "https://api.github.com"
VERSION = "github-main-merges-v1"
MAX_PATCH_CHARS = 20_000


class GitHubCollector:
    def __init__(
        self,
        memory: AuctorMemory | None = None,
        settings: Settings | None = None,
        client: httpx.Client | None = None,
    ):
        self.settings = settings or get_settings()
        self.memory = memory or AuctorMemory(self.settings)
        self.client = client

    def _authenticate(self, workspace_id: str) -> None:
        if self.client is not None:
            return
        token = self.settings.github_token
        if not token:
            token = GitHubAuth(self.settings, self.memory).installation_token(workspace_id)
        self.client = httpx.Client(
            base_url=API,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "auctor-github-collector",
            },
            timeout=30,
        )

    def _get(self, path: str, **params: Any) -> Any:
        if self.client is None:
            raise RuntimeError("GitHub collector is not authenticated")
        response = self.client.get(path, params={k: v for k, v in params.items() if v is not None})
        response.raise_for_status()
        return response.json()

    def _pages(self, path: str, max_pages: int = 5, **params: Any) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for page in range(1, max_pages + 1):
            batch = self._get(path, **params, per_page=100, page=page)
            if not isinstance(batch, list):
                raise ValueError(f"Expected a list from GitHub endpoint {path}")
            rows.extend(batch)
            if len(batch) < 100:
                break
        return rows

    @staticmethod
    def _timestamp(value: str | None) -> datetime:
        if not value:
            return datetime.fromtimestamp(0, timezone.utc)
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    @staticmethod
    def _files(files: list[dict[str, Any]]) -> list[dict[str, Any]]:
        normalized = []
        for file in files:
            patch = file.get("patch")
            normalized.append(
                {
                    "filename": file.get("filename"),
                    "status": file.get("status"),
                    "additions": file.get("additions", 0),
                    "deletions": file.get("deletions", 0),
                    "changes": file.get("changes", 0),
                    "previous_filename": file.get("previous_filename"),
                    "patch": patch[:MAX_PATCH_CHARS] if isinstance(patch, str) else None,
                    "patch_truncated": isinstance(patch, str) and len(patch) > MAX_PATCH_CHARS,
                }
            )
        return normalized

    def collect(
        self,
        workspace_id: str,
        repositories: list[str] | None = None,
        username: str | None = None,
        target_branch: str = "main",
        since_days: int = 30,
        max_pages: int = 5,
        max_pull_requests_per_repository: int = 100,
    ) -> CollectorResult:
        self._authenticate(workspace_id)
        started_at = utc_now()
        sync_key = f"main-merges:{target_branch}"
        self.memory.save_sync_state(
            workspace_id, "github", sync_key, last_started_at=started_at, last_error=None
        )
        try:
            viewer = self._get("/user")
            owner = username or self.settings.github_owner or viewer.get("login")
            if not owner:
                raise ValueError("Unable to determine GitHub owner")
            cursor = self.memory.get_cursor(workspace_id, "github", sync_key)
            since = cursor or started_at - timedelta(days=max(1, min(since_days, 3650)))

            connection = (
                None
                if self.settings.github_token
                else self.memory.get_provider_connection(workspace_id, "github")
            )
            connected_repositories = [
                repo.get("full_name")
                for repo in (connection or {}).get("repositories", [])
                if repo.get("full_name")
            ]
            allow = (
                repositories
                or connected_repositories
                or [
                    item.strip()
                    for item in self.settings.github_repositories.split(",")
                    if item.strip()
                ]
            )
            if allow:
                repo_names = allow
            else:
                endpoint = (
                    "/user/repos"
                    if owner.lower() == viewer.get("login", "").lower()
                    else f"/users/{owner}/repos"
                )
                repo_names = [
                    row["full_name"] for row in self._pages(endpoint, max_pages=max_pages)
                ]

            raw_count = event_count = 0
            for full_name in repo_names:
                encoded = "/".join(quote(part, safe="") for part in full_name.split("/"))
                pulls = self._pages(
                    f"/repos/{encoded}/pulls",
                    max_pages=max_pages,
                    state="closed",
                    base=target_branch,
                    sort="updated",
                    direction="desc",
                )
                merged = [
                    pull
                    for pull in pulls
                    if pull.get("merged_at")
                    and since < self._timestamp(pull["merged_at"]) <= started_at
                ][: max(1, min(max_pull_requests_per_repository, 500))]

                for summary in merged:
                    number = summary["number"]
                    detail = self._get(f"/repos/{encoded}/pulls/{number}")
                    files = self._pages(
                        f"/repos/{encoded}/pulls/{number}/files", max_pages=max_pages
                    )
                    commits = self._pages(
                        f"/repos/{encoded}/pulls/{number}/commits", max_pages=max_pages
                    )
                    merged_at = self._timestamp(detail["merged_at"])
                    external_id = f"main-merge:{full_name}:{number}"
                    payload = {"pull_request": detail, "files": files, "commits": commits}
                    raw = RawRecord(
                        workspace_id=workspace_id,
                        source="github",
                        external_id=external_id,
                        kind="main-merge",
                        payload=payload,
                        checksum=stable_checksum(payload),
                        collected_at=started_at,
                        occurred_at=merged_at,
                        source_url=detail.get("html_url"),
                        collector_version=VERSION,
                    )
                    raw_id = self.memory.save_raw(raw)
                    raw_count += 1
                    provenance = Provenance(
                        source="github",
                        external_id=external_id,
                        raw_record_id=raw_id,
                        collected_at=started_at,
                        occurred_at=merged_at,
                        source_url=detail.get("html_url"),
                        collector_version=VERSION,
                    )
                    commit_messages = [
                        {
                            "sha": commit.get("sha"),
                            "message": commit.get("commit", {}).get("message"),
                            "authored_at": commit.get("commit", {}).get("author", {}).get("date"),
                            "committed_at": commit.get("commit", {})
                            .get("committer", {})
                            .get("date"),
                        }
                        for commit in commits
                    ]
                    self.memory.save_event(
                        MemoryEvent(
                            workspace_id=workspace_id,
                            source="github",
                            external_id=external_id,
                            event_type="github.pull_request.merged_to_main",
                            object_type="pull_request",
                            object_id=str(number),
                            title=detail.get("title"),
                            body=detail.get("body"),
                            occurred_at=merged_at,
                            attributes={
                                "repository": full_name,
                                "pull_request_number": number,
                                "url": detail.get("html_url"),
                                "target_branch": target_branch,
                                "source_branch": detail.get("head", {}).get("ref"),
                                "merge_commit_sha": detail.get("merge_commit_sha"),
                                "author": detail.get("user", {}).get("login"),
                                "additions": detail.get("additions", 0),
                                "deletions": detail.get("deletions", 0),
                                "changed_files": detail.get("changed_files", 0),
                                "commit_messages": commit_messages,
                                "files": self._files(files),
                            },
                            provenance=provenance,
                        )
                    )
                    event_count += 1

            completed_at = utc_now()
            self.memory.save_sync_state(
                workspace_id,
                "github",
                sync_key,
                cursor=started_at,
                last_started_at=started_at,
                last_completed_at=completed_at,
                last_error=None,
                metadata={
                    "checked_from": since,
                    "checked_through": started_at,
                    "target_branch": target_branch,
                    "repositories": repo_names,
                    "merges": event_count,
                    "collector_version": VERSION,
                },
            )
            return CollectorResult(
                source="github",
                workspace_id=workspace_id,
                raw_records=raw_count,
                events=event_count,
                started_at=started_at,
                completed_at=completed_at,
                details={"checked_from": since, "target_branch": target_branch},
            )
        except Exception as error:
            self.memory.save_sync_state(
                workspace_id,
                "github",
                sync_key,
                last_started_at=started_at,
                last_error=str(error),
                metadata={"collector_version": VERSION},
            )
            raise
