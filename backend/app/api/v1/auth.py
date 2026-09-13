"""Authentication endpoints.

Alpha scope: sign-in against seeded accounts. Self-service registration is out
of scope for the Alpha and is intentionally not exposed.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import UnauthorizedError
from app.models import User
from app.schemas import LoginRequest, LoginResponse
from app.security import create_access_token, verify_password

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> LoginResponse:
    user = db.scalars(select(User).where(User.email == payload.email.lower().strip())).first()
    # The same message is returned for an unknown address and a wrong password
    # so the endpoint does not disclose which accounts exist.
    if user is None or not verify_password(payload.password, user.password_hash):
        raise UnauthorizedError("Email address or password is incorrect.")

    token, expires_in = create_access_token(user)
    return LoginResponse(
        access_token=token,
        token_type="Bearer",
        expires_in=expires_in,
        role=user.role,
        display_name=user.display_name,
    )
