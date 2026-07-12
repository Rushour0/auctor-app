from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    mongodb_uri: str
    mongodb_db: str = "auctor"
    auctor_workspace_id: str = "kriti-personal"

    github_token: str = ""
    github_owner: str = ""
    github_repositories: str = ""
    github_app_id: str = ""
    github_app_slug: str = ""
    github_client_id: str = ""
    github_client_secret: str = ""
    github_private_key: str = ""
    github_private_key_base64: str = ""
    github_webhook_secret: str = ""
    github_oauth_callback_url: str = "http://localhost:8000/integrations/github/callback"
    github_oauth_state_secret: str = ""

    linkup_api_key: str = ""

    posthog_host: str = "https://us.posthog.com"
    posthog_project_id: str = ""
    posthog_personal_api_key: str = ""
    posthog_auth_mode: str = "personal_api_key"

    product_metrics_ingest_secret: str = ""

    scheduler_interval_hours: int = 6
    scheduler_batch_size: int = 100


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
