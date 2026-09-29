"""My record -- the member's own training and credentials.

Every route is member-only and acts on the signed-in member. No route accepts
a member identifier from the client.
"""

from fastapi import APIRouter, Depends, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import parse_uuid
from app.db import get_db
from app.errors import ForbiddenError
from app.models import MemberRecordItem, User
from app.modules.customer_data.adapter import CustomerDataAdapter
from app.modules.customer_data.member_record import MemberRecordService, extract_candidates
from app.schemas import (
    MemberRecordItemView,
    MemberRecordResponse,
    RecordCandidate,
    RecordImportRequest,
    RecordImportResponse,
    RecordItemKind,
    RecordItemRequest,
    RecordItemsAddedResponse,
    RecordItemSource,
    RecordItemsRequest,
    ServiceRecordSummary,
)
from app.security import ROLE_CUSTOMER, get_current_user

router = APIRouter(prefix="/api/v1/profile", tags=["profile"])


def require_member(user: User = Depends(get_current_user)) -> User:
    if user.role != ROLE_CUSTOMER:
        raise ForbiddenError("My record is available to members only.")
    return user


def _view(item: MemberRecordItem) -> MemberRecordItemView:
    return MemberRecordItemView(
        item_id=item.id,
        kind=RecordItemKind(item.kind),
        name=item.name,
        source=RecordItemSource(item.source),
        added_at=item.created_at,
    )


@router.get("/record", response_model=MemberRecordResponse)
def get_record(
    db: Session = Depends(get_db), member: User = Depends(require_member)
) -> MemberRecordResponse:
    """The service record (read-only) and everything the member has added."""
    official = CustomerDataAdapter(db).service_record(member.id)
    return MemberRecordResponse(
        service_record=(
            ServiceRecordSummary(
                service_branch=official.service_branch,
                occupational_specialty=official.occupational_specialty,
                completed_training=official.completed_training,
                credentials=official.credentials,
            )
            if official
            else None
        ),
        added=[_view(item) for item in MemberRecordService(db).list_items(member.id)],
    )


@router.post(
    "/record/items", response_model=MemberRecordItemView, status_code=status.HTTP_201_CREATED
)
def add_item(
    payload: RecordItemRequest,
    db: Session = Depends(get_db),
    member: User = Depends(require_member),
) -> MemberRecordItemView:
    item = MemberRecordService(db).add(member.id, payload.kind, payload.name, source="MANUAL")
    db.commit()
    return _view(item)


@router.post(
    "/record/items/bulk",
    response_model=RecordItemsAddedResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_items(
    payload: RecordItemsRequest,
    db: Session = Depends(get_db),
    member: User = Depends(require_member),
) -> RecordItemsAddedResponse:
    """Save the items the member confirmed after an upload. Repeats are counted, not errors."""
    added, skipped = MemberRecordService(db).add_many(
        member.id, [(item.kind, item.name) for item in payload.items], source="UPLOAD"
    )
    db.commit()
    return RecordItemsAddedResponse(
        added=[_view(item) for item in added], already_on_record=skipped
    )


@router.delete("/record/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_item(
    item_id: str,
    db: Session = Depends(get_db),
    member: User = Depends(require_member),
) -> Response:
    MemberRecordService(db).remove(member.id, parse_uuid(item_id, "itemId"))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/record/import", response_model=RecordImportResponse)
def import_record(
    payload: RecordImportRequest, member: User = Depends(require_member)
) -> RecordImportResponse:
    """Read an uploaded .txt, .csv or .pdf and suggest items. Saves nothing."""
    candidates, skipped = extract_candidates(payload.filename, payload.content_base64)
    return RecordImportResponse(
        candidates=[
            RecordCandidate(kind=RecordItemKind(item.kind), name=item.name) for item in candidates
        ],
        skipped_lines=skipped,
    )
