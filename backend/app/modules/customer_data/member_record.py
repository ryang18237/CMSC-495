"""My record -- training and credentials a member adds themselves.

Part of the Customer Data Adapter. The legacy personnel record is read-only
and frequently incomplete: a certification earned after separation, a civilian
course, a license from a state board -- none of it ever reaches that system.
A member adds those items here once. The adapter merges them with the legacy
record, so every later conversation and every recommendation already knows
about them; nobody re-uploads anything per conversation.

Two ways in:

- **Typed** -- one item at a time from the "My record" panel.
- **Uploaded** -- a text, CSV or PDF list (a transcript export, a resume
  section). The document is read, likely items are extracted, and the member
  confirms which to keep. Nothing from an upload is saved until they do, and
  the document itself is never stored.
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

KINDS = ("TRAINING", "CREDENTIAL")
MAX_NAME_LENGTH = 200
# Generous for a real service history, and a ceiling on what one account can
# push into every prompt.
MAX_ITEMS = 100

# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


def _clean(name: str) -> str:
    return " ".join(name.split())


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

    def names(self, user_id: uuid.UUID) -> tuple[list[str], list[str]]:
        """(training, credentials) the member added, in the order they added them."""
        items = self.list_items(user_id)
        training = [item.name for item in items if item.kind == "TRAINING"]
        credentials = [item.name for item in items if item.kind == "CREDENTIAL"]
        return training, credentials

    def add(
        self, user_id: uuid.UUID, kind: str, name: str, source: str = "MANUAL"
    ) -> MemberRecordItem:
        kind = kind.upper()
        cleaned = _clean(name)
        if kind not in KINDS:
            raise UnprocessableError(
                "Kind must be TRAINING or CREDENTIAL.", code="INVALID_RECORD_ITEM"
            )
        if not cleaned or len(cleaned) > MAX_NAME_LENGTH:
            raise UnprocessableError(
                f"A name must contain between 1 and {MAX_NAME_LENGTH} characters.",
                code="INVALID_RECORD_ITEM",
            )

        existing = self.list_items(user_id)
        if any(item.kind == kind and item.name.lower() == cleaned.lower() for item in existing):
            raise ConflictError("That item is already on your record.", code="RECORD_ITEM_EXISTS")
        if len(existing) >= MAX_ITEMS:
            raise UnprocessableError(
                f"A record can hold at most {MAX_ITEMS} items.", code="RECORD_ITEM_LIMIT"
            )

        item = MemberRecordItem(user_id=user_id, kind=kind, name=cleaned, source=source)
        self._db.add(item)
        self._db.flush()
        _invalidate(user_id)
        return item

    def add_many(
        self, user_id: uuid.UUID, items: list[tuple[str, str]], source: str = "UPLOAD"
    ) -> tuple[list[MemberRecordItem], int]:
        """Add what is new; count what was already there. Used after an upload."""
        added: list[MemberRecordItem] = []
        skipped = 0
        for kind, name in items:
            try:
                added.append(self.add(user_id, kind, name, source=source))
            except ConflictError:
                skipped += 1
        return added, skipped

    def remove(self, user_id: uuid.UUID, item_id: uuid.UUID) -> None:
        item = self._db.get(MemberRecordItem, item_id)
        # Someone else's item is reported as missing, not forbidden, so ids
        # cannot be probed to learn that another member's item exists.
        if item is None or item.user_id != user_id:
            raise NotFoundError("Record item not found.", code="RECORD_ITEM_NOT_FOUND")
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
    r"\b(course|school|training|academy|class|program|programme|qualification|"
    r"apprenticeship|leader|instructor|seminar|workshop|curriculum)\b",
    re.IGNORECASE,
)
_SECTION = re.compile(
    r"^\s*(?P<title>(licen[cs]es?|certifications?|credentials?|training|courses?|"
    r"education|military (education|training|courses?)|schools?))\s*:?\s*$",
    re.IGNORECASE,
)
# Numbering, bullets, dates and course codes that transcripts put around a title.
_PREFIX = re.compile(r"^\s*([-*•●\d]+[.)]?\s+|[A-Z]{2,4}-\d{2,5}-\d{2,5}\s+)")
_DATE = re.compile(r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2}|(19|20)\d{2})\b")


@dataclass(frozen=True)
class Candidate:
    kind: str
    name: str


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
    if _CREDENTIAL_WORDS.search(line):
        return "CREDENTIAL"
    if _TRAINING_WORDS.search(line):
        return "TRAINING"
    return section


# Lines that are page furniture or personal details, never a course.
_NOISE = re.compile(
    r"^(page\s+\d+|name\s*:|ssn|dob\b|date of birth|rank\s*:|address\s*:|"
    r"(joint services )?transcript\b)",
    re.IGNORECASE,
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


def _rows_from_csv(text: str) -> list[tuple[str, str | None]]:
    """(name, kind hint) from a CSV, using a header when there is a useful one."""
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return []
    header = [cell.strip().lower() for cell in rows[0]]
    name_column = next(
        (i for i, h in enumerate(header) if h in ("name", "title", "course", "credential")), None
    )
    kind_column = next((i for i, h in enumerate(header) if h in ("kind", "type", "category")), None)

    if name_column is None:
        return [(cell, None) for row in rows for cell in row if cell.strip()]

    out: list[tuple[str, str | None]] = []
    for row in rows[1:]:
        if name_column >= len(row) or not row[name_column].strip():
            continue
        hint = None
        if kind_column is not None and kind_column < len(row):
            value = row[kind_column].strip().upper()
            hint = "CREDENTIAL" if value.startswith(("CRED", "CERT", "LIC")) else "TRAINING"
        out.append((row[name_column], hint))
    return out


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
        heading = _SECTION.match(raw)
        if heading:
            title = heading.group("title").lower()
            section = (
                "CREDENTIAL" if title.startswith(("licen", "certif", "credential")) else "TRAINING"
            )
            continue

        if _NOISE.match(raw.strip()):
            skipped += 1
            continue
        name = _tidy(raw)
        if not name:
            continue
        if len(name) < 3 or len(name) > MAX_NAME_LENGTH or not re.search(r"[A-Za-z]", name):
            skipped += 1
            continue

        kind = hint or _classify(name, section)
        if kind is None:
            skipped += 1
            continue

        key = (kind, name.lower())
        if key in seen:
            continue
        seen.add(key)
        found.append(Candidate(kind=kind, name=name))
        if len(found) >= MAX_ITEMS:
            break

    return found, skipped
