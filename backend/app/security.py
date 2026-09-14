"""Authentication and authorization.

Customer identity is always derived from the verified access token. A
client-supplied customer identifier is never trusted when deciding access to
customer information.
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt
from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.errors import ForbiddenError, UnauthorizedError
from app.models import User

ROLE_CUSTOMER = "CUSTOMER"
ROLE_AGENT = "AGENT"


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    # bcrypt raises on a malformed hash. That is a corrupt row rather than a
    # correct password, so it is treated as a failed check rather than allowed
    # to surface as a 500.
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(user: User) -> tuple[str, int]:
    settings = get_settings()
    expires_in = settings.jwt_expire_minutes * 60
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(user.id),
        "role": user.role,
        "email": user.email,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=expires_in)).timestamp()),
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, expires_in


def _decode(token: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        decoded: dict[str, Any] = jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
        return decoded
    except jwt.ExpiredSignatureError as exc:
        raise UnauthorizedError("Access token has expired.") from exc
    except jwt.InvalidTokenError as exc:
        raise UnauthorizedError("Access token is invalid.") from exc


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """Resolve the signed-in user from the bearer token.

    The user is re-loaded from the database on every request rather than
    trusted from the token body. A token stays valid until it expires, so a
    deleted or role-changed account would otherwise keep its old access for up
    to an hour.
    """
    header = request.headers.get("Authorization", "")
    if not header.lower().startswith("bearer "):
        raise UnauthorizedError("Authorization header with a Bearer token is required.")

    claims = _decode(header.split(" ", 1)[1].strip())
    try:
        user_id = uuid.UUID(str(claims.get("sub")))
    except ValueError as exc:
        raise UnauthorizedError("Access token subject is malformed.") from exc

    user = db.get(User, user_id)
    if user is None:
        raise UnauthorizedError("Access token does not identify a known user.")
    return user


def require_agent(user: User = Depends(get_current_user)) -> User:
    if user.role != ROLE_AGENT:
        raise ForbiddenError("This resource requires an authorized agent role.")
    return user
