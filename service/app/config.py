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

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_allow_origins.split(",") if o.strip()]


settings = Settings()
