"""Which AI models a member can choose from.

OWNER: Benjamin Madden (Integration Lead)

Lists only the providers this server has a key for, plus the demo assistant,
which needs none. The keys stay on the server: a member sees a name and a
model id, never a credential.
"""

from fastapi import APIRouter, Depends

from app.models import User
from app.modules.ai_integration.service import available_providers
from app.schemas import AIProviderView
from app.security import get_current_user

router = APIRouter(prefix="/api/v1/ai", tags=["ai"])


@router.get("/providers", response_model=list[AIProviderView])
def list_providers(user: User = Depends(get_current_user)) -> list[AIProviderView]:
    return [
        AIProviderView(
            provider_id=option.provider_id,
            label=option.label,
            model=option.model,
            is_default=option.is_default,
        )
        for option in available_providers()
    ]
