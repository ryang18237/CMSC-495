"""Shared route dependencies."""

import uuid

from fastapi import Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import BadRequestError
from app.models import User
from app.modules.conversation.service import ConversationService
from app.security import get_current_user, require_agent

__all__ = ["Depends", "Session", "User", "get_current_user", "get_db", "require_agent"]


def parse_uuid(value: str, field_name: str) -> uuid.UUID:
    """Reject a malformed identifier with 400 rather than a framework 422."""
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError, TypeError) as exc:
        raise BadRequestError(
            f"{field_name} must be a valid UUID.",
            code="INVALID_IDENTIFIER",
        ) from exc


def get_conversation_service(db: Session = Depends(get_db)) -> ConversationService:
    return ConversationService(db)
