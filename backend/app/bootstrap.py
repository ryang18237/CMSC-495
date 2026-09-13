"""Schema creation and synthetic seed data.

All seed data is synthetic. No real customer information is used anywhere in
this repository, which keeps the Alpha free of privacy exposure while still
exercising the full customer-context path.

Run with:  python -m app.bootstrap
"""

import logging
import os
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import Base, SessionLocal, engine
from app.models import KnowledgeArticle, LegacyCustomerMaster, User
from app.security import ROLE_AGENT, ROLE_CUSTOMER, hash_password

logger = logging.getLogger("app.bootstrap")

# Fixed ids keep the seeded demo reproducible across resets.
CUSTOMER_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
CUSTOMER_TWO_ID = uuid.UUID("22222222-2222-4222-8222-222222222222")
AGENT_ID = uuid.UUID("33333333-3333-4333-8333-333333333333")

KNOWLEDGE_ARTICLES: list[tuple[str, str, str]] = [
    (
        "Duplicate charges and pending authorisations",
        "When an order is placed the bank may show a pending authorisation alongside the "
        "settled charge. Pending authorisations are released automatically within three to "
        "five business days. If both amounts have settled, the duplicate is refunded to the "
        "original payment method once support confirms the order history.",
        "billing,charge,duplicate,refund,payment,invoice",
    ),
    (
        "Order tracking and delivery timelines",
        "Tracking information becomes available once the carrier scans the parcel, normally "
        "within one business day of dispatch. Standard delivery takes three to five business "
        "days and expedited delivery takes one to two. If tracking has not updated for three "
        "business days, support can open a carrier trace.",
        "order,tracking,delivery,shipping,shipment",
    ),
    (
        "Returns and exchanges",
        "Items may be returned within 30 days of delivery in their original packaging. A "
        "prepaid return label is issued once the return request is approved. Refunds are "
        "processed within five business days of the returned item arriving at the warehouse.",
        "return,exchange,refund,damaged,broken",
    ),
    (
        "Password resets and account access",
        "Customers reset their own password using the 'Forgot password' link on the sign-in "
        "page. The reset email arrives within a few minutes and the link is valid for one "
        "hour. Support staff never read, set or confirm a customer password.",
        "password,login,signin,locked,access,account",
    ),
    (
        "Plan changes, upgrades and cancellations",
        "Plan upgrades take effect immediately and are prorated for the remainder of the "
        "billing period. Downgrades and cancellations take effect at the end of the current "
        "billing period, and access continues until then.",
        "plan,subscription,upgrade,downgrade,cancel,billing",
    ),
]


def create_schema() -> None:
    Base.metadata.create_all(bind=engine)
    logger.info("schema ensured")


def seed(db: Session) -> None:
    default_password = os.environ.get("SEED_PASSWORD", "DemoPassw0rd!")

    users = [
        (CUSTOMER_ID, "customer@example.com", "Alex Customer", ROLE_CUSTOMER),
        (CUSTOMER_TWO_ID, "customer2@example.com", "Jordan Customer", ROLE_CUSTOMER),
        (AGENT_ID, "agent@example.com", "Sam Agent", ROLE_AGENT),
    ]
    for user_id, email, display_name, role in users:
        if db.get(User, user_id) is None:
            db.add(
                User(
                    id=user_id,
                    email=email,
                    display_name=display_name,
                    role=role,
                    password_hash=hash_password(default_password),
                )
            )

    legacy_rows = [
        ("CUST-100241", CUSTOMER_ID, "A", "PRM", "ORD-88231", 129.98, 2, 3),
        ("CUST-100987", CUSTOMER_TWO_ID, "A", "STD", "ORD-88450", 42.50, 0, 9),
    ]
    for cust_nbr, app_user_id, stat, plan, order_id, amount, tickets, days_ago in legacy_rows:
        if db.get(LegacyCustomerMaster, cust_nbr) is None:
            db.add(
                LegacyCustomerMaster(
                    cust_nbr=cust_nbr,
                    app_user_id=app_user_id,
                    acct_stat_cd=stat,
                    plan_cd=plan,
                    lst_ordr_id=order_id,
                    lst_ordr_amt=amount,
                    lst_ordr_dt=datetime.now(timezone.utc) - timedelta(days=days_ago),
                    open_tkt_cnt=tickets,
                )
            )

    existing_titles = set(db.scalars(select(KnowledgeArticle.title)))
    for title, body, tags in KNOWLEDGE_ARTICLES:
        if title not in existing_titles:
            db.add(KnowledgeArticle(title=title, body=body, tags=tags))

    db.commit()
    logger.info("seed data ensured")


def main() -> None:  # pragma: no cover - operational entry point
    logging.basicConfig(level=logging.INFO)
    create_schema()
    db = SessionLocal()
    try:
        seed(db)
    finally:
        db.close()
    print("Database ready. Seeded accounts:")
    print("  customer@example.com / DemoPassw0rd!  (role CUSTOMER)")
    print("  customer2@example.com / DemoPassw0rd! (role CUSTOMER)")
    print("  agent@example.com / DemoPassw0rd!     (role AGENT)")


if __name__ == "__main__":  # pragma: no cover
    main()
