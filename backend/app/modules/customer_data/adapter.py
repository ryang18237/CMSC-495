"""Customer Data Adapter.

Translates the existing customer database structures into the stable
`CustomerContext` contract. No other module reads the legacy tables, so a
change to the legacy schema is absorbed here and nowhere else.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.errors import DependencyUnavailableError
from app.models import LegacyCustomerMaster

_ACCOUNT_STATUS = {"A": "ACTIVE", "S": "SUSPENDED", "C": "CLOSED"}
_PLAN_NAMES = {"STD": "Standard", "PRM": "Premium", "TRL": "Trial"}

# Which fields the adapter is allowed to surface for a given inquiry type.
# Anything not listed is withheld, which keeps AI prompts minimal by default.
_INQUIRY_FIELDS: dict[str, tuple[str, ...]] = {
    "BILLING": ("account_status", "plan_name", "last_order"),
    "ORDER": ("account_status", "last_order"),
    "ACCOUNT": ("account_status", "plan_name", "open_ticket_count"),
    "GENERAL": ("account_status",),
}


@dataclass(frozen=True)
class OrderSummary:
    order_id: str
    amount: float
    ordered_at: datetime | None


@dataclass(frozen=True)
class CustomerContext:
    """Stable, minimised view of a customer for downstream modules."""

    customer_ref: str
    account_status: str
    plan_name: str | None = None
    open_ticket_count: int | None = None
    last_order: OrderSummary | None = None
    available_fields: list[str] = field(default_factory=list)

    def to_prompt_facts(self) -> list[str]:
        """Render only the fields this context was permitted to expose."""
        facts: list[str] = []
        if "account_status" in self.available_fields:
            facts.append(f"Account status: {self.account_status}")
        if "plan_name" in self.available_fields and self.plan_name:
            facts.append(f"Plan: {self.plan_name}")
        if "open_ticket_count" in self.available_fields and self.open_ticket_count is not None:
            facts.append(f"Open support tickets: {self.open_ticket_count}")
        if "last_order" in self.available_fields and self.last_order is not None:
            facts.append(
                f"Most recent order {self.last_order.order_id} for ${self.last_order.amount:.2f}"
            )
        return facts


UNKNOWN_CONTEXT = CustomerContext(
    customer_ref="UNKNOWN",
    account_status="UNKNOWN",
    available_fields=["account_status"],
)


def classify_inquiry(message: str) -> str:
    """Deterministic inquiry classification used to minimise shared data."""
    lowered = message.lower()
    billing_words = ("charge", "charged", "billing", "invoice", "refund", "payment")
    if any(word in lowered for word in billing_words):
        return "BILLING"
    if any(word in lowered for word in ("order", "delivery", "shipment", "shipping", "tracking")):
        return "ORDER"
    if any(word in lowered for word in ("account", "plan", "subscription", "upgrade", "cancel")):
        return "ACCOUNT"
    return "GENERAL"


class CustomerDataAdapter:
    def __init__(self, db: Session) -> None:
        self._db = db

    def _load(self, user_id: uuid.UUID) -> LegacyCustomerMaster | None:
        try:
            return self._db.scalars(
                select(LegacyCustomerMaster).where(LegacyCustomerMaster.app_user_id == user_id)
            ).first()
        except SQLAlchemyError as exc:
            raise DependencyUnavailableError(
                "The customer data system is currently unavailable."
            ) from exc

    def get_customer_context(self, user_id: uuid.UUID) -> CustomerContext:
        """Full translation of the legacy record into the application contract."""
        return self.get_relevant_account_data(user_id, "ACCOUNT")

    def get_relevant_account_data(self, user_id: uuid.UUID, inquiry_type: str) -> CustomerContext:
        row = self._load(user_id)
        if row is None:
            return UNKNOWN_CONTEXT

        allowed = _INQUIRY_FIELDS.get(inquiry_type.upper(), _INQUIRY_FIELDS["GENERAL"])
        last_order = None
        if row.lst_ordr_id is not None:
            last_order = OrderSummary(
                order_id=row.lst_ordr_id,
                amount=float(row.lst_ordr_amt or 0),
                ordered_at=row.lst_ordr_dt,
            )

        return CustomerContext(
            customer_ref=row.cust_nbr,
            account_status=_ACCOUNT_STATUS.get(row.acct_stat_cd, "UNKNOWN"),
            plan_name=_PLAN_NAMES.get(row.plan_cd, row.plan_cd),
            open_ticket_count=row.open_tkt_cnt,
            last_order=last_order,
            available_fields=list(allowed),
        )
