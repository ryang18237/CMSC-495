"""Customer Data Adapter.

Turns a row from the legacy personnel system into the stable `CustomerContext`
contract the rest of the platform depends on. Two things are going on here:

1.  Translation. The legacy table stores abbreviated codes and semicolon
    delimited lists. Nothing outside this file should ever have to know that.
2.  Minimisation. A member's record holds more than any single question needs.
    `_INQUIRY_FIELDS` decides, per inquiry type, which parts may be shared --
    and `to_prompt_facts()` renders only those. That is what keeps the data
    sent to the AI provider limited to what the question actually requires.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.errors import DependencyUnavailableError
from app.models import LegacyMemberMaster
from app.modules.cache.service import get_cache
from app.modules.customer_data.member_record import MemberRecordService

# Legacy code lookups. Kept here so the codes stop at the adapter boundary.
_BRANCHES = {
    "ARMY": "Army",
    "USN": "Navy",
    "USAF": "Air Force",
    "USMC": "Marine Corps",
    "USCG": "Coast Guard",
    "USSF": "Space Force",
}

_PAY_GRADES = {
    "E4": "E-4",
    "E5": "E-5",
    "E6": "E-6",
    "E7": "E-7",
    "O2": "O-2",
    "O3": "O-3",
}

# Occupational specialty codes differ by branch, so the lookup is keyed by both.
# A code with no entry falls back to the raw value rather than guessing.
_SPECIALTIES = {
    ("ARMY", "25B"): "Information Technology Specialist",
    ("ARMY", "88M"): "Motor Transport Operator",
    ("ARMY", "68W"): "Combat Medic Specialist",
    ("USN", "IT"): "Information Systems Technician",
    ("USN", "HM"): "Hospital Corpsman",
    ("USAF", "3D0X2"): "Cyber Systems Operations",
    ("USMC", "0311"): "Rifleman",
    ("USCG", "ET"): "Electronics Technician",
}

# Which parts of the record each kind of question is permitted to see. Anything
# not listed here is withheld, so the default is always the narrower one.
_INQUIRY_FIELDS: dict[str, tuple[str, ...]] = {
    # "What can I study?" -- needs finished training and study already done,
    # not the job title and not the employment history.
    "EDUCATION": (
        "service_branch",
        "years_of_service",
        "completed_training",
        "education",
    ),
    # "Which certification should I sit?" -- needs the specialty and what is held.
    "CREDENTIAL": ("occupational_specialty", "completed_training", "credentials"),
    # "How do I describe this on a resume?" -- needs the full picture, which is
    # the one question where the work history is the point.
    "CAREER": (
        "occupational_specialty",
        "years_of_service",
        "completed_training",
        "credentials",
        "education",
        "experience",
    ),
    # "When should I start an internship?" -- needs timing, not the lists.
    "TRANSITION": ("service_branch", "years_of_service", "separation_date"),
    "GENERAL": ("service_branch",),
}


@dataclass(frozen=True)
class CustomerContext:
    """Stable, minimised view of a member for downstream modules.

    `available_fields` is not decoration. It is the permission list, and
    `to_prompt_facts()` is the only thing that should turn this object into
    text bound for the AI provider.
    """

    customer_ref: str
    service_branch: str
    pay_grade: str | None = None
    occupational_specialty: str | None = None
    years_of_service: int | None = None
    separation_date: datetime | None = None
    completed_training: list[str] = field(default_factory=list)
    credentials: list[str] = field(default_factory=list)
    # From the member's own profile. Nothing in the personnel record
    # corresponds to these, which is exactly why members enter them.
    education: list[str] = field(default_factory=list)
    experience: list[str] = field(default_factory=list)
    available_fields: list[str] = field(default_factory=list)

    def to_prompt_facts(self) -> list[str]:
        """Render only the fields this context was permitted to expose."""
        facts: list[str] = []

        if "service_branch" in self.available_fields:
            facts.append(f"Branch of service: {self.service_branch}")

        if "occupational_specialty" in self.available_fields and self.occupational_specialty:
            facts.append(f"Occupational specialty: {self.occupational_specialty}")

        if "years_of_service" in self.available_fields and self.years_of_service is not None:
            facts.append(f"Years of service: {self.years_of_service}")

        if "separation_date" in self.available_fields and self.separation_date is not None:
            facts.append(f"Separation date: {self.separation_date.date().isoformat()}")

        # These two are the point of the platform: recommendations have to be
        # anchored to what the member has actually finished.
        if "completed_training" in self.available_fields and self.completed_training:
            facts.append("Completed training: " + ", ".join(self.completed_training))

        if "credentials" in self.available_fields and self.credentials:
            facts.append("Credentials already held: " + ", ".join(self.credentials))

        if "education" in self.available_fields and self.education:
            facts.append("Education: " + ", ".join(self.education))

        if "experience" in self.available_fields and self.experience:
            facts.append("Experience: " + ", ".join(self.experience))

        return facts


# Returned when no personnel record matches. The assistant still works; it just
# answers generally instead of referring to anything the member has done.
UNKNOWN_CONTEXT = CustomerContext(
    customer_ref="UNKNOWN",
    service_branch="UNKNOWN",
    available_fields=["service_branch"],
)


def classify_inquiry(message: str) -> str:
    """Decide what kind of question this is, using fixed keyword rules.

    Deliberately not a model call. This runs before the AI module and decides
    how much of the member's record is allowed to leave the platform, so it has
    to be predictable and reviewable. Order matters: the more specific
    categories are checked first.
    """
    lowered = message.lower()

    credential_words = (
        "certification",
        "certificate",
        "certified",
        "credential",
        "license",
        "licensing",
        "exam",
        "comptia",
        "security+",
        "pmp",
    )
    if any(word in lowered for word in credential_words):
        return "CREDENTIAL"

    education_words = (
        "degree",
        "college",
        "university",
        "school",
        "course",
        "class",
        "tuition",
        "study",
        "studying",
        "education",
        "associate",
        "bachelor",
    )
    if any(word in lowered for word in education_words):
        return "EDUCATION"

    transition_words = (
        "skillbridge",
        "internship",
        "transition",
        "separating",
        "separation",
        "terminal leave",
        "ets",
        "getting out",
    )
    if any(word in lowered for word in transition_words):
        return "TRANSITION"

    career_words = (
        "resume",
        "résumé",
        "job",
        "career",
        "hiring",
        "interview",
        "employer",
        "civilian",
        "apprenticeship",
        "salary",
        "translate",
    )
    if any(word in lowered for word in career_words):
        return "CAREER"

    return "GENERAL"


def _split_list(raw: str) -> list[str]:
    """Legacy list columns are semicolon delimited, sometimes with stray spaces."""
    return [item.strip() for item in raw.split(";") if item.strip()]


def _merge(official: list[str], added: list[str]) -> list[str]:
    """The service record first, then what the member added, without repeats."""
    seen = {item.lower() for item in official}
    merged = list(official)
    for item in added:
        if item.lower() not in seen:
            seen.add(item.lower())
            merged.append(item)
    return merged


@dataclass(frozen=True)
class ServiceRecordView:
    """What the personnel system says, shown back to the member read-only."""

    service_branch: str
    occupational_specialty: str | None
    completed_training: list[str]
    credentials: list[str]


class CustomerDataAdapter:
    def __init__(self, db: Session) -> None:
        self._db = db

    def _load(self, user_id: uuid.UUID) -> LegacyMemberMaster | None:
        try:
            return self._db.scalars(
                select(LegacyMemberMaster).where(LegacyMemberMaster.app_user_id == user_id)
            ).first()
        except SQLAlchemyError as exc:
            # The personnel system being down is not the customer's problem and
            # should not surface as a stack trace.
            raise DependencyUnavailableError(
                "The personnel data system is currently unavailable."
            ) from exc

    @staticmethod
    def invalidate(user_id: uuid.UUID) -> int:
        """Drop cached context for one member.

        Called whenever the member edits "My record", so the very next message
        sees the change.
        """
        return get_cache().invalidate(f"member:{user_id}:")

    def service_record(self, user_id: uuid.UUID) -> ServiceRecordView | None:
        """The legacy record alone, translated, for the member to see."""
        row = self._load(user_id)
        if row is None:
            return None
        return ServiceRecordView(
            service_branch=_BRANCHES.get(row.svc_brnch_cd, row.svc_brnch_cd),
            occupational_specialty=_SPECIALTIES.get(
                (row.svc_brnch_cd, row.occ_spec_cd), row.occ_spec_cd
            ),
            completed_training=_split_list(row.cmpltd_trng_txt),
            credentials=_split_list(row.cred_erned_txt),
        )

    def get_customer_context(self, user_id: uuid.UUID) -> CustomerContext:
        """Full translation, used where the whole picture is wanted."""
        return self.get_relevant_account_data(user_id, "CAREER")

    def get_relevant_account_data(self, user_id: uuid.UUID, inquiry_type: str) -> CustomerContext:
        # Cached per member *and* per inquiry type. A single key would let a
        # context built for one question be served to another, which would
        # quietly widen what reaches the AI provider.
        cache = get_cache()
        cache_key = f"member:{user_id}:{inquiry_type.upper()}"
        cached = cache.get(cache_key)
        if cached is not None:
            assert isinstance(cached, CustomerContext)
            return cached

        row = self._load(user_id)
        # What the member added in "My record". It counts exactly like the
        # service record, under the same per-inquiry permission list.
        profile = MemberRecordService(self._db).by_kind(user_id)
        added_training = profile["TRAINING"]
        added_credentials = profile["CREDENTIAL"]
        allowed = _INQUIRY_FIELDS.get(inquiry_type.upper(), _INQUIRY_FIELDS["GENERAL"])

        if row is None:
            if not any(profile.values()):
                return UNKNOWN_CONTEXT
            # No personnel record, but the member has filled in a profile. Use
            # it rather than answering as if we knew nothing about them.
            context = CustomerContext(
                customer_ref="SELF-REPORTED",
                service_branch="UNKNOWN",
                completed_training=added_training,
                credentials=added_credentials,
                education=profile["EDUCATION"],
                experience=profile["EXPERIENCE"],
                available_fields=[field for field in allowed if field != "service_branch"],
            )
            cache.set(cache_key, context)
            return context

        branch = _BRANCHES.get(row.svc_brnch_cd, row.svc_brnch_cd)

        context = CustomerContext(
            customer_ref=row.mbr_nbr,
            service_branch=branch,
            pay_grade=_PAY_GRADES.get(row.pay_grd_cd, row.pay_grd_cd),
            # Fall back to the raw code rather than inventing a job title for it.
            occupational_specialty=_SPECIALTIES.get(
                (row.svc_brnch_cd, row.occ_spec_cd), row.occ_spec_cd
            ),
            years_of_service=row.svc_yrs,
            separation_date=row.sep_dt,
            completed_training=_merge(_split_list(row.cmpltd_trng_txt), added_training),
            credentials=_merge(_split_list(row.cred_erned_txt), added_credentials),
            education=profile["EDUCATION"],
            experience=profile["EXPERIENCE"],
            available_fields=list(allowed),
        )
        cache.set(cache_key, context)
        return context
