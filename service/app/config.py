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

    # GitHub operator LOGIN — OAuth 2.0 for gating the four frontend pages behind a
    # sign-in. This is a SEPARATE GitHub OAuth App from service/auctor/config.py's
    # github_client_id/secret, which is the data-COLLECTOR app connection. Do not
    # conflate the two. Blank by default so Settings loads cleanly with no .env values;
    # any code path that actually performs operator login must fail loud at call time.
    github_login_client_id: str = ""
    github_login_client_secret: str = ""
    github_login_redirect_uri: str = "http://localhost:8000/api/auth/github/callback"
    operator_session_secret: str = ""

    # Public, no-signup "suggest my posts" demo (POST /api/demo/suggest) — the only
    # unauthenticated route in this service by design. Research is Linkup-backed
    # (same provider/pattern as the real researcher/trend_researcher specialists,
    # never a raw LinkedIn/X profile scrape) and suggestions are LLM-drafted from
    # those sourced findings only. Blank by default so Settings loads cleanly with
    # no .env values; the route fails loud at call time, never at import/app-boot.
    linkup_api_key: str = ""
    anthropic_api_key: str = ""
    demo_rate_limit_per_day: int = 3

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_allow_origins.split(",") if o.strip()]


settings = Settings()
