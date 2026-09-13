"""Application configuration.

All runtime configuration is read from environment variables so that the
application instances remain stateless and horizontally scalable (see the
Non-Functional Requirements section of the System Design Specification).
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "AI-Powered Customer Service Platform"
    app_version: str = "0.1.0-alpha"
    environment: str = "development"

    # Data layer
    database_url: str = "postgresql+psycopg://csp:csp@localhost:5432/csp"

    # Authentication
    jwt_secret: str = "dev-only-insecure-secret-change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60

    # Client layer
    cors_origins: str = "http://localhost:5173"

    # AI Integration Module
    ai_provider: str = "mock"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-5"
    anthropic_base_url: str = "https://api.anthropic.com"
    ai_timeout_seconds: float = 20.0
    ai_max_retries: int = 2

    # Interface contract limits
    max_message_length: int = 2000
    max_response_length: int = 4000
    max_comment_length: int = 1000
    max_request_bytes: int = 65536

    # Rate limiting (per authenticated user)
    rate_limit_messages_per_minute: int = 30

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
