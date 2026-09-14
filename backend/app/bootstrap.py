"""Schema creation and synthetic seed data.

Everything here is invented. No real service member's information, and no real
programme, school or employer, appears anywhere in this repository. The
knowledge base articles are illustrative sample content written for the
prototype -- they are not guidance from any agency and must not be treated as
such.

Run with:  python -m app.bootstrap
"""

import logging
import os
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import Base, SessionLocal, engine
from app.models import KnowledgeArticle, LegacyMemberMaster, User
from app.security import ROLE_AGENT, ROLE_CUSTOMER, hash_password

logger = logging.getLogger("app.bootstrap")

# Fixed ids so a reset produces the same demo every time, and so tests can
# refer to a member without first having to look one up.
MEMBER_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
MEMBER_TWO_ID = uuid.UUID("22222222-2222-4222-8222-222222222222")
COUNSELOR_ID = uuid.UUID("33333333-3333-4333-8333-333333333333")

# Kept as aliases so existing imports and tests keep working after the rename.
CUSTOMER_ID = MEMBER_ID
CUSTOMER_TWO_ID = MEMBER_TWO_ID
AGENT_ID = COUNSELOR_ID

# Sample content only. Written to be plausible and useful for a demonstration,
# not to state any real programme's rules.
KNOWLEDGE_ARTICLES: list[tuple[str, str, str]] = [
    (
        "Turning an occupational specialty into civilian job titles",
        "Start from the tasks you performed rather than the job title itself. An "
        "information systems role usually maps to network administrator, systems "
        "administrator or help desk analyst. Hiring managers respond to plain "
        "descriptions of scope: how many systems you were responsible for, how many "
        "people you trained, and what you were accountable for.",
        "resume,career,job,civilian,translate,title,interview,hiring",
    ),
    (
        "Certifications that build on training you have already completed",
        "Completed technical training often covers a large part of an entry level "
        "certification. Network and systems coursework lines up with foundational IT "
        "certifications, and medical training lines up with emergency care "
        "credentials. Reviewing the exam objectives against the training you have "
        "finished is usually faster than starting a new course from scratch.",
        "certification,certificate,credential,exam,license,comptia,security,study",
    ),
    (
        "Choosing between a degree programme and a credential",
        "A credential is shorter, cheaper and aimed at a specific role, so it suits "
        "someone who wants to work soon in a field they already know. A degree takes "
        "longer and opens roles that list one as a requirement. Many people do both, "
        "starting with a credential to get hired and completing a degree part time "
        "afterwards.",
        "degree,college,university,credential,certificate,study,education,tuition,school",
    ),
    (
        "Industry internships during transition",
        "An industry internship places you with a civilian employer for a fixed "
        "period near the end of service, while still serving. Placements are "
        "arranged well in advance and require command approval, so the time to ask "
        "about one is early -- typically several months before you plan to start, "
        "not weeks.",
        "skillbridge,internship,transition,separating,separation,placement,employer",
    ),
    (
        "Building a resume from completed training and awards",
        "List completed courses by what they taught rather than by course number. "
        "Awards are evidence of results, so pair each one with the outcome it "
        "recognised. Keep the resume to the experience relevant to the role you are "
        "applying for; a complete service history belongs in a separate record.",
        "resume,cv,training,awards,experience,career,job,writing",
    ),
    (
        "Apprenticeships and on the job training",
        "An apprenticeship pays while you learn and ends in a recognised "
        "qualification, which suits trades and technical fields. Prior military "
        "training sometimes shortens the programme, so it is worth asking a sponsor "
        "whether completed training counts toward the required hours before you "
        "enrol.",
        "apprenticeship,training,trade,on the job,career,hours,qualification",
    ),
]

# Synthetic personnel records, in the shape the legacy system stores them.
# Columns: member number, user id, branch, pay grade, specialty, years served,
# days until separation, completed training, credentials held, open cases.
_MEMBER_RECORDS = [
    (
        "MBR-100241",
        MEMBER_ID,
        "ARMY",
        "E5",
        "25B",
        6,
        120,
        "Basic Leader Course;Network Administration Course;Information Assurance Fundamentals",
        "CompTIA A+",
        1,
    ),
    (
        "MBR-100987",
        MEMBER_TWO_ID,
        "USN",
        "E6",
        "HM",
        9,
        300,
        "Hospital Corpsman A School;Emergency Medical Technician Course;Instructor Training",
        "EMT-Basic",
        0,
    ),
]


def create_schema() -> None:
    """Create any missing tables. Existing tables are left alone."""
    Base.metadata.create_all(bind=engine)
    logger.info("schema ensured")


def seed(db: Session) -> None:
    """Insert the demo accounts, personnel records and articles if absent.

    Idempotent by design: it runs on every startup in development, so each
    insert is guarded by an existence check rather than a truncate.
    """
    default_password = os.environ.get("SEED_PASSWORD", "DemoPassw0rd!")

    users = [
        (MEMBER_ID, "member@example.com", "Alex Rivera", ROLE_CUSTOMER),
        (MEMBER_TWO_ID, "member2@example.com", "Jordan Chen", ROLE_CUSTOMER),
        (COUNSELOR_ID, "counselor@example.com", "Sam Okafor", ROLE_AGENT),
    ]
    for user_id, email, display_name, role in users:
        existing = db.get(User, user_id)

        if existing is None:
            db.add(
                User(
                    id=user_id,
                    email=email,
                    display_name=display_name,
                    role=role,
                    password_hash=hash_password(default_password),
                )
            )
            continue

        # The seeded accounts are matched by id, so a row created by an earlier
        # version of this file is found even after its email changed -- and
        # would otherwise keep the old address forever, leaving anyone with an
        # existing database unable to sign in with the address the README
        # documents. Realign the mutable fields instead of skipping the row.
        #
        # The password hash is deliberately left alone: re-hashing on every
        # startup is slow, and a developer who changed their own local password
        # should keep it.
        if existing.email != email:
            logger.info("seed: updating account email %s -> %s", existing.email, email)
            existing.email = email
        if existing.display_name != display_name:
            existing.display_name = display_name
        if existing.role != role:
            existing.role = role

    now = datetime.now(timezone.utc)
    for (
        mbr_nbr,
        app_user_id,
        branch,
        pay_grade,
        specialty,
        years,
        days_to_separation,
        training,
        credentials,
        open_cases,
    ) in _MEMBER_RECORDS:
        if db.get(LegacyMemberMaster, mbr_nbr) is None:
            db.add(
                LegacyMemberMaster(
                    mbr_nbr=mbr_nbr,
                    app_user_id=app_user_id,
                    svc_brnch_cd=branch,
                    pay_grd_cd=pay_grade,
                    occ_spec_cd=specialty,
                    svc_yrs=years,
                    sep_dt=now + timedelta(days=days_to_separation),
                    cmpltd_trng_txt=training,
                    cred_erned_txt=credentials,
                    open_case_cnt=open_cases,
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
    print("  member@example.com / DemoPassw0rd!     (role CUSTOMER)")
    print("  member2@example.com / DemoPassw0rd!    (role CUSTOMER)")
    print("  counselor@example.com / DemoPassw0rd!  (role AGENT)")


if __name__ == "__main__":  # pragma: no cover
    main()
