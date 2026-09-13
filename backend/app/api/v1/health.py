"""Health endpoint. Exposes no customer data."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.modules.ai_integration.service import AIIntegrationService
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

    ai_service = AIIntegrationService()
    dependencies["ai_provider"] = ai_service.provider_health()
    dependencies["ai_provider_name"] = ai_service.provider_name

    if dependencies["database"] != "ok":
        status = "unavailable"
        response.status_code = 503
    elif dependencies["ai_provider"] != "ok":
        # The platform still answers: failed AI calls fall back and escalate.
        status = "degraded"
    else:
        status = "healthy"

    return HealthResponse(
        status=status,
        timestamp=datetime.now(timezone.utc),
        version=settings.app_version,
        dependencies=dependencies,
    )
