"""My profile -- what the member has done, entered once and kept.

Part of the Customer Data Adapter. The legacy personnel record holds military
training and nothing else: a certification earned after separation, a degree,
a civilian job never reach it. A member enters those here once. The adapter
merges them with the legacy record, so every later conversation and every
recommendation already knows about them; nobody restates anything per
conversation.

Four kinds, covering what a career conversation actually needs:

| Kind | Example |
| --- | --- |
| `CREDENTIAL` | CompTIA Security+, an EMT license |
| `TRAINING` | a course, a school, a military qualification |
| `EDUCATION` | an associate degree, a bachelor's, coursework in progress |
| `EXPERIENCE` | a job or role, military or civilian |

Every item is a name plus an optional organisation (issuer, school, employer)
and an optional detail line. Only the name is required, because a half-filled
profile is still better than none.

Two ways in:

- **Typed** -- one item at a time in the "My profile" panel.
- **Uploaded** -- a text, CSV or PDF list (a transcript export, a resume).
  The document is read, likely items are extracted, and the member confirms
  which to keep. Nothing is saved until they do, and the document itself is
  never stored.
"""

import base64
import binascii
import csv
import io
import re
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import ConflictError, NotFoundError, UnprocessableError
from app.models import MemberRecordItem
from app.modules.cache.service import get_cache

# What a member has already done. These four are what the completeness score
# measures and what the assistant treats as fact about them.
HELD_KINDS = ("CREDENTIAL", "TRAINING", "EDUCATION", "EXPERIENCE")

# What a member intends to do. A plan is deliberately a separate kind rather
# than a credential with a flag: a goal must never be read as something the
# member holds, or the assistant would start recommending the step after a
# degree nobody has earned yet.
PLAN_KIND = "GOAL"

KINDS = (*HELD_KINDS, PLAN_KIND)
MAX_NAME_LENGTH = 200
MAX_ORGANIZATION_LENGTH = 200
MAX_DETAIL_LENGTH = 500
# Generous for a real career history, and a ceiling on what one account can
# push into every prompt.
MAX_ITEMS = 150

# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


def _clean(name: str) -> str:
    return " ".join(name.split())


@dataclass(frozen=True)
class Entry:
    """One profile item, validated and ready to store or offer."""

    kind: str
    name: str
    organization: str | None = None
    detail: str | None = None


class MemberRecordService:
    def __init__(self, db: Session) -> None:
        self._db = db

    def list_items(self, user_id: uuid.UUID) -> list[MemberRecordItem]:
        return list(
            self._db.scalars(
                select(MemberRecordItem)
                .where(MemberRecordItem.user_id == user_id)
                .order_by(MemberRecordItem.kind, MemberRecordItem.created_at)
            )
        )

    def by_kind(self, user_id: uuid.UUID) -> dict[str, list[str]]:
        """Item names per kind, in the order the member added them.

        An item with an organisation reads better with it attached -- "Associate
        of Applied Science (Central Texas College)" tells the recommender and
        the assistant more than the title alone.
        """
        grouped: dict[str, list[str]] = {kind: [] for kind in KINDS}
        for item in self.list_items(user_id):
            label = f"{item.name} ({item.organization})" if item.organization else item.name
            grouped.setdefault(item.kind, []).append(label)
        return grouped

    @staticmethod
    def _validated(kind: str, name: str, organization: str | None, detail: str | None) -> Entry:
        kind = kind.strip().upper()
        if kind not in KINDS:
            raise UnprocessableError(
                "Kind must be one of " + ", ".join(KINDS) + ".",
                code="INVALID_RECORD_ITEM",
            )

        cleaned = _clean(name)
        if not cleaned or len(cleaned) > MAX_NAME_LENGTH:
            raise UnprocessableError(
                f"A name must contain between 1 and {MAX_NAME_LENGTH} characters.",
                code="INVALID_RECORD_ITEM",
            )

        # Optional fields: blank and absent mean the same thing.
        org = _clean(organization or "") or None
        if org and len(org) > MAX_ORGANIZATION_LENGTH:
            raise UnprocessableError(
                f"An organisation must be at most {MAX_ORGANIZATION_LENGTH} characters.",
                code="INVALID_RECORD_ITEM",
            )
        text = _clean(detail or "") or None
        if text and len(text) > MAX_DETAIL_LENGTH:
            raise UnprocessableError(
                f"A detail must be at most {MAX_DETAIL_LENGTH} characters.",
                code="INVALID_RECORD_ITEM",
            )
        return Entry(kind=kind, name=cleaned, organization=org, detail=text)

    def add(
        self,
        user_id: uuid.UUID,
        kind: str,
        name: str,
        organization: str | None = None,
        detail: str | None = None,
        source: str = "MANUAL",
    ) -> MemberRecordItem:
        entry = self._validated(kind, name, organization, detail)

        existing = self.list_items(user_id)
        if any(
            item.kind == entry.kind and item.name.lower() == entry.name.lower() for item in existing
        ):
            raise ConflictError("That item is already on your profile.", code="RECORD_ITEM_EXISTS")
        if len(existing) >= MAX_ITEMS:
            raise UnprocessableError(
                f"A profile can hold at most {MAX_ITEMS} items.", code="RECORD_ITEM_LIMIT"
            )

        item = MemberRecordItem(
            user_id=user_id,
            kind=entry.kind,
            name=entry.name,
            organization=entry.organization,
            detail=entry.detail,
            source=source,
        )
        self._db.add(item)
        self._db.flush()
        _invalidate(user_id)
        return item

    def add_many(
        self, user_id: uuid.UUID, entries: list[Entry], source: str = "UPLOAD"
    ) -> tuple[list[MemberRecordItem], int]:
        """Add what is new; count what was already there. Used after an upload."""
        added: list[MemberRecordItem] = []
        skipped = 0
        for entry in entries:
            try:
                added.append(
                    self.add(
                        user_id,
                        entry.kind,
                        entry.name,
                        entry.organization,
                        entry.detail,
                        source=source,
                    )
                )
            except ConflictError:
                skipped += 1
        return added, skipped

    def remove(self, user_id: uuid.UUID, item_id: uuid.UUID) -> None:
        item = self._db.get(MemberRecordItem, item_id)
        # Someone else's item is reported as missing, not forbidden, so ids
        # cannot be probed to learn that another member's item exists.
        if item is None or item.user_id != user_id:
            raise NotFoundError("Profile item not found.", code="RECORD_ITEM_NOT_FOUND")
        self._db.delete(item)
        self._db.flush()
        _invalidate(user_id)


def _invalidate(user_id: uuid.UUID) -> None:
    # The adapter caches a member's context per inquiry type. A record change
    # has to reach the very next message, so every cached view is dropped.
    get_cache().invalidate(f"member:{user_id}:")


# ---------------------------------------------------------------------------
# Reading an uploaded document
# ---------------------------------------------------------------------------

SUPPORTED_TYPES = (".txt", ".csv", ".pdf")

_CREDENTIAL_WORDS = re.compile(
    r"\b(certif\w*|licen[cs]e\w*|credential\w*|comptia|ccna|ccnp|cissp|pmp|capm|emt|"
    r"paramedic|nremt|cdl|itil|aws|azure|security\+|network\+|a\+|linux\+|six sigma|"
    r"registered|board)\b",
    re.IGNORECASE,
)
_TRAINING_WORDS = re.compile(
    r"\b(course|school|training|academy|class|qualification|"
    r"apprenticeship|leader|instructor|seminar|workshop|curriculum)\b",
    re.IGNORECASE,
)
_EDUCATION_WORDS = re.compile(
    r"\b(associate|bachelor\w*|master\w*|doctorate|phd|b\.?s\.?|b\.?a\.?|m\.?s\.?|"
    r"m\.?b\.?a\.?|a\.?a\.?s\.?|degree|diploma|ged|university|college|major\w*|"
    r"semester|credit hours?)\b",
    re.IGNORECASE,
)
_EXPERIENCE_WORDS = re.compile(
    r"\b(specialist|technician|operator|manager|supervisor|lead|analyst|engineer|"
    r"administrator|assistant|coordinator|officer|sergeant|corpsman|medic|"
    r"mechanic|electrician|driver|nurse|clerk|intern|experience|employed|"
    r"years? at|worked)\b",
    re.IGNORECASE,
)
# A heading tells us what the lines under it are, which beats guessing.
_SECTION_KINDS = (
    ("CREDENTIAL", r"licen[cs]es?|certifications?|certificates?|credentials?"),
    ("EDUCATION", r"education|degrees?|academics?|colleges?|universit(y|ies)"),
    (
        "EXPERIENCE",
        r"(work |employment |professional |military )?(experience|history)|"
        r"employment|positions?|assignments?|roles?",
    ),
    ("TRAINING", r"training|courses?|military (education|training|courses?)|schools?"),
)
_SECTION = re.compile(
    r"^\s*(?P<title>(" + "|".join(pattern for _, pattern in _SECTION_KINDS) + r"))\s*:?\s*$",
    re.IGNORECASE,
)
# Numbering, bullets, dates and course codes that transcripts put around a title.
_PREFIX = re.compile(r"^\s*([-*•●\d]+[.)]?\s+|[A-Z]{2,4}-\d{2,5}-\d{2,5}\s+)")
_DATE = re.compile(r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2}|(19|20)\d{2})\b")


# An extracted line is offered as the same Entry shape the member could have
# typed, so confirming an upload and typing an item take the identical path.
Candidate = Entry


def _decode(filename: str, content_base64: str) -> str:
    try:
        raw = base64.b64decode(content_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise UnprocessableError("The file could not be read.", code="INVALID_RECORD_FILE") from exc

    if filename.lower().endswith(".pdf"):
        # Imported here so the rest of the platform does not load a PDF library.
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError

        try:
            reader = PdfReader(io.BytesIO(raw))
            return "\n".join(page.extract_text() or "" for page in reader.pages[:20])
        except (PdfReadError, ValueError, OSError) as exc:
            raise UnprocessableError(
                "The PDF could not be read. Try saving it as text.", code="INVALID_RECORD_FILE"
            ) from exc

    for encoding in ("utf-8-sig", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise UnprocessableError("The file could not be read.", code="INVALID_RECORD_FILE")


def _classify(line: str, section: str | None) -> str | None:
    """Which kind a line looks like, or the heading it sits under.

    Order is deliberate. A credential name is the most distinctive, a degree
    next. Job titles are last because words like "specialist" and "technician"
    also appear inside course names, so they only decide a line that nothing
    more specific has claimed.
    """
    if _CREDENTIAL_WORDS.search(line):
        return "CREDENTIAL"
    if _EDUCATION_WORDS.search(line):
        return "EDUCATION"
    if _TRAINING_WORDS.search(line):
        return "TRAINING"
    if _EXPERIENCE_WORDS.search(line):
        return "EXPERIENCE"
    return section


# Lines that are page furniture or personal details, never a profile item.
_NOISE = re.compile(
    r"^(page\s+\d+|name\s*:|ssn|dob\b|date of birth|rank\s*:|address\s*:|"
    r"e-?mail|phone|resum[eé]\b|curriculum vitae|"
    r"(joint services )?transcript\b)",
    re.IGNORECASE,
)

# "Title -- Organisation", "Title at Employer", "Title, University". Splitting
# these is what lets an upload fill the organisation field instead of jamming
# everything into the name.
_SPLIT_ORGANIZATION = re.compile(
    r"^(?P<name>.{3,}?)\s*(?:\s[-\u2013\u2014]\s|\sat\s|\s\|\s|,\s)(?P<org>.{2,})$"
)


def _tidy(line: str) -> str:
    previous = None
    while previous != line:  # "1. AR-1715-0799 Title" needs two passes
        previous = line
        line = _PREFIX.sub("", line)
    line = _DATE.sub("", line)
    line = re.sub(r"\(\s*\)|\[\s*\]", "", line)  # brackets emptied by date removal
    line = re.sub(r"\s*[|,;]\s*$", "", line)
    return _clean(line.strip(" -:|\t"))


def _column(header: list[str], names: tuple[str, ...]) -> int | None:
    return next((index for index, title in enumerate(header) if title in names), None)


def _kind_hint(row: list[str], column: int | None) -> str | None:
    if column is None or column >= len(row):
        return None
    value = row[column].strip().upper()
    return "CREDENTIAL" if value.startswith(("CRED", "CERT", "LIC")) else "TRAINING"


def _rows_from_csv(text: str) -> list[tuple[str, str | None]]:
    """(name, kind hint) from a CSV, using a header when there is a useful one."""
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return []
    header = [cell.strip().lower() for cell in rows[0]]
    name_column = _column(header, ("name", "title", "course", "credential"))
    kind_column = _column(header, ("kind", "type", "category"))

    if name_column is None:
        # No usable header: every non-empty cell is a candidate line.
        return [(cell, None) for row in rows for cell in row if cell.strip()]

    return [
        (row[name_column], _kind_hint(row, kind_column))
        for row in rows[1:]
        if name_column < len(row) and row[name_column].strip()
    ]


def _section_kind(raw: str) -> str | None:
    """The kind this line announces as a heading, or None if it is not one."""
    heading = _SECTION.match(raw)
    if not heading:
        return None
    title = heading.group("title")
    for kind, pattern in _SECTION_KINDS:
        if re.fullmatch(pattern, title, re.IGNORECASE):
            return kind
    return None


def _usable_name(raw: str) -> str | None:
    """The tidied title, or None for noise, fragments and non-text lines."""
    if _NOISE.match(raw.strip()):
        return None
    name = _tidy(raw)
    if len(name) < 3 or len(name) > MAX_NAME_LENGTH or not re.search(r"[A-Za-z]", name):
        return None
    return name


def _split_organization(name: str) -> tuple[str, str | None]:
    """ "Associate of Science, Central Texas College" -> title and school."""
    match = _SPLIT_ORGANIZATION.match(name)
    if not match:
        return name, None
    title, org = match.group("name").strip(), match.group("org").strip()
    # Only split when both halves survive as something readable; otherwise the
    # line was a single title that happened to contain a comma.
    if len(title) < 3 or len(org) < 2 or len(org) > MAX_ORGANIZATION_LENGTH:
        return name, None
    return title, org


def extract_candidates(filename: str, content_base64: str) -> tuple[list[Candidate], int]:
    """Likely record items in an uploaded document, and how many lines were skipped.

    Deliberately conservative: a line is kept only when it reads like a course
    or a credential, or sits under a heading that says it is one. The member
    reviews the list before anything is saved, so missing an item costs a
    moment of typing, while inventing one would put something false on their
    record.
    """
    if not filename.lower().endswith(SUPPORTED_TYPES):
        raise UnprocessableError(
            "Upload a .txt, .csv or .pdf file.", code="UNSUPPORTED_RECORD_FILE"
        )
    text = _decode(filename, content_base64)

    if filename.lower().endswith(".csv"):
        lines = _rows_from_csv(text)
    else:
        lines = [(line, None) for line in text.splitlines()]

    found: list[Candidate] = []
    seen: set[tuple[str, str]] = set()
    skipped = 0
    section: str | None = None

    for raw, hint in lines:
        heading = _section_kind(raw)
        if heading:
            section = heading
            continue
        if not raw.strip():
            continue

        name = _usable_name(raw)
        kind = (hint or _classify(name, section)) if name else None
        if name is None or kind is None:
            skipped += 1
            continue

        name, organization = _split_organization(name)
        if (kind, name.lower()) not in seen:
            seen.add((kind, name.lower()))
            found.append(Candidate(kind=kind, name=name, organization=organization))
        if len(found) >= MAX_ITEMS:
            break

    return found, skipped
