"""Health endpoint. Exposes no customer data."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.modules.ai_integration.service import AIIntegrationService
from app.modules.cache.service import get_cache
from app.modules.monitoring.service import INSTANCE_ID
from app.schemas import HealthResponse

router = APIRouter(prefix="/api/v1", tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health(response: Response, db: Session = Depends(get_db)) -> HealthResponse:
    settings = get_settings()
    dependencies: dict[str, str] = {}

    try:
        db.execute(text("SELECT 1"))
        dependencies["database"] = "ok"
    except Exception:
        dependencies["database"] = "unavailable"
    dependencies["database_engine"] = settings.database_engine

    ai_service = AIIntegrationService()
    dependencies["ai_provider"] = ai_service.provider_health()
    dependencies["ai_provider_name"] = ai_service.provider_name
    # The budget the provider will actually honour. A turn that dies at
    # exactly the old 8-second default, on a machine configured for 120, is
    # the signature of a stale process or a stale checkout -- and there was
    # no way to see which number was live without reading the source.
    dependencies["ai_timeout_seconds"] = f"{ai_service.provider_timeout_seconds:.0f}"

    cache = get_cache()
    dependencies["cache"] = cache.health()
    dependencies["cache_implementation"] = cache.name

    if dependencies["database"] != "ok":
        status = "unavailable"
        response.status_code = 503
    elif dependencies["ai_provider"] != "ok":
        # Degraded rather than unavailable: sign-in, the profile, the
        # recommender and the counsellor queue all still work. Only the
        # assistant cannot answer, and it says so and escalates.
        status = "degraded"
    else:
        status = "healthy"

    return HealthResponse(
        status=status,
        timestamp=datetime.now(timezone.utc),
        version=settings.app_version,
        instance_id=INSTANCE_ID,
        dependencies=dependencies,
    )
