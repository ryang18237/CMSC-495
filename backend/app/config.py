"""Application configuration.

All runtime configuration is read from environment variables so that the
application instances remain stateless and horizontally scalable (see the
Non-Functional Requirements section of the System Design Specification).
"""

import secrets
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict

# Placeholder shipped in .env.example. When it survives into a development run
# it is replaced by a locally generated secret rather than used as-is.
PLACEHOLDER_JWT_SECRET = "dev-only-insecure-secret-change-me"
DEV_SECRET_FILE = Path(__file__).resolve().parent.parent / ".jwt_secret"


def _local_dev_secret() -> str:
    """Return a per-machine development signing secret, creating it if needed.

    Keeping it in a git-ignored file (rather than regenerating per process)
    means access tokens survive an auto-reload, so a developer is not signed
    out every time they save a file.
    """
    try:
        existing = DEV_SECRET_FILE.read_text(encoding="utf-8").strip()
        if len(existing) >= 32:
            return existing
    except OSError:
        pass

    generated = secrets.token_urlsafe(48)
    try:
        DEV_SECRET_FILE.write_text(generated, encoding="utf-8")
        DEV_SECRET_FILE.chmod(0o600)
    except OSError:
        # A read-only checkout still runs; tokens just do not survive a restart.
        pass
    return generated


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "SkillBridge AI"
    app_version: str = "0.1.0-alpha"
    environment: str = "development"

    # Data layer. PostgreSQL is the supported data layer and what CI runs
    # against; `python run.py` falls back to a local SQLite file only when no
    # PostgreSQL server is reachable, so the app still starts on a clean
    # machine.
    database_url: str = "postgresql+psycopg://csp:csp@localhost:5432/csp"

    # Create the schema and load synthetic seed data on startup. Convenient for
    # local runs and demos; CI and any deployment run `python -m app.bootstrap`
    # as an explicit step instead.
    auto_bootstrap: bool = True

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

    # Cache (Data Layer). Alpha uses a process-local implementation; see
    # app/modules/cache/service.py for what a shared cache would change.
    cache_enabled: bool = True
    cache_ttl_seconds: int = 60

    # Interface contract limits
    max_message_length: int = 2000
    max_response_length: int = 4000
    max_comment_length: int = 1000
    max_request_bytes: int = 65536

    # Rate limiting (per authenticated user)
    rate_limit_messages_per_minute: int = 30

    def model_post_init(self, __context: Any) -> None:
        if self.environment == "development" and self.jwt_secret == PLACEHOLDER_JWT_SECRET:
            self.jwt_secret = _local_dev_secret()

    @property
    def database_engine(self) -> str:
        """Which engine the configured URL points at, for health reporting."""
        return self.database_url.split(":", 1)[0].split("+", 1)[0] or "unknown"

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
