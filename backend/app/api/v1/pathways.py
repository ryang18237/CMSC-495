"""Pathway recommendations -- the member-facing AI feature that needs no key.

OWNER: Benjamin Madden (Integration Lead)

The route is thin on purpose. It reads the member's record through the
Customer Data Adapter using the CREDENTIAL permission set -- specialty,
completed training and credentials held, nothing else -- and hands those plain
lists to the recommender in AI Integration. The recommender never sees the
database, the branch, the pay grade or the separation date.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import ForbiddenError
from app.models import User
from app.modules.ai_integration.recommender import MemberProfile, recommend
from app.modules.customer_data.adapter import CustomerDataAdapter
from app.modules.customer_data.member_record import PLAN_KIND, MemberRecordService
from app.schemas import (
    PathwayBasis,
    PathwayReason,
    PathwayRecommendationsResponse,
    PathwayRecommendationView,
    PathwayStrength,
)
from app.security import ROLE_CUSTOMER, get_current_user

router = APIRouter(prefix="/api/v1/pathways", tags=["pathways"])

DISCLAIMER = (
    "Suggestions are based on the training and credentials on your record. They are "
    "a starting point for a conversation, not a guarantee of eligibility, credit, "
    "funding or employment. A counsellor can help you check any of them."
)


@router.get("/recommended", response_model=PathwayRecommendationsResponse)
def recommended_pathways(
    limit: int = Query(default=5, ge=1, le=10),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PathwayRecommendationsResponse:
    """Rank civilian pathways against what the signed-in member has completed."""
    # Counsellors have no personnel record of their own, and looking up a
    # member's suggestions on their behalf is a different feature with its own
    # access rules. Refusing is clearer than returning an empty list.
    if user.role != ROLE_CUSTOMER:
        raise ForbiddenError("Pathway recommendations are available to members only.")

    context = CustomerDataAdapter(db).get_relevant_account_data(user.id, "CREDENTIAL")
    # The plan is read separately from the permission set. It is not a fact
    # about the member, so it never belongs in the data the adapter minimises
    # for a provider; it is only used here to drop what they have already
    # chosen from the list of what to choose next.
    planned = MemberRecordService(db).by_kind(user.id)[PLAN_KIND]

    profile = MemberProfile(
        completed_training=list(context.completed_training),
        credentials=list(context.credentials),
        occupational_specialty=(
            context.occupational_specialty
            if "occupational_specialty" in context.available_fields
            else None
        ),
        planned=planned,
    )
    result = recommend(profile, limit=limit)

    return PathwayRecommendationsResponse(
        basis=PathwayBasis(result.basis),
        method=result.method,
        disclaimer=DISCLAIMER,
        recommendations=[
            PathwayRecommendationView(
                pathway_id=item.pathway.pathway_id,
                title=item.pathway.title,
                kind=item.pathway.kind,
                field=item.pathway.field,
                summary=item.pathway.summary,
                score=item.score,
                strength=PathwayStrength(item.strength),
                reason=PathwayReason(item.reason),
                builds_on=item.builds_on,
                matched_terms=item.matched_terms,
            )
            for item in result.recommendations
        ],
    )
