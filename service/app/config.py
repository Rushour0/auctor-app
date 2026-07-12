from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    agency_env: str = "development"
    mongodb_uri: str = "mongodb://mongo:27017"
    mongodb_db: str = "auctor"

    cors_allow_origins: str = "http://localhost:5173"

    site_max_retry_attempts: int = 2
    content_max_retry_attempts: int = 1

    # Twitter/X API v2 — OAuth 2.0 Authorization Code + PKCE, per-client user-context tokens.
    # Blank by default so Settings loads cleanly with no .env values set; any code path that
    # actually calls the X API must fail loud at call time, never at import/app-boot time.
    twitter_api_key: str = ""
    twitter_api_secret: str = ""
    twitter_redirect_uri: str = "http://localhost:8000/api/x/oauth/callback"

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_allow_origins.split(",") if o.strip()]


settings = Settings()
