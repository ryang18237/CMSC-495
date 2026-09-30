# 0007 — Members maintain their own record alongside the personnel system

**Status:** Accepted
**Date:** Final release
**Deciders:** Ryan Gant, Ravonne Wade, Benjamin Madden

## Context

Advice is only as good as the record it is grounded in, and the legacy
personnel record is read-only and often behind: certifications earned after
separation, civilian courses and state licenses never reach it. Members were
left to restate those in every conversation, and the assistant forgot them
the moment a new one started.

## Decision

Members keep a **My record** list of training and credentials, stored per
account in a `member_record_items` table owned by the Customer Data Adapter.
The adapter merges it with the legacy record when it builds `CustomerContext`,
so the chat, the pathway recommender and the demo assistant all see one list
under the same per-question permission rules. Items are typed in, or suggested
from an uploaded `.txt`, `.csv` or `.pdf` and saved only when the member
confirms them. The uploaded document is never stored.

## Consequences

**What this buys.** Saved once, used in every conversation. The legacy record
is never written to, so its integrity is untouched, and nothing outside the
adapter learns that two sources exist.

**What it costs.** Member-entered items are self-reported and unverified. The
assistant treats them exactly like the official record, which is right for
suggestions and wrong for any eligibility decision — which the platform does
not make, and a counsellor would check. Upload parsing is heuristic; the
confirm step exists because it will sometimes miss or misread a line.

## Enforcement

`test_member_record.py` checks that saved items reach new conversations,
that one member cannot remove another's, and that an upload saves nothing
until confirmed. The boundary tests keep the new table inside the adapter.
