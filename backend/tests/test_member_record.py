"""My profile: members enter their credentials, training, education and
experience once, and every conversation after that uses them.
"""

import base64

from fastapi.testclient import TestClient

from app.modules.customer_data.member_record import extract_candidates

RECORD = "/api/v1/profile/record"


def _b64(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


# ---------------------------------------------------------------------------
# Reading and editing
# ---------------------------------------------------------------------------
def test_a_new_member_starts_with_an_empty_profile(
    client: TestClient, customer_auth: dict[str, str]
) -> None:
    """Nothing is claimed on a member's behalf.

    The personnel feed is read-only here, so anything it supplied was training
    and credentials a member could see and could not remove. They now start
    empty and add what they have.
    """
    body = client.get(RECORD, headers=customer_auth).json()
    assert body["serviceRecord"]["credentials"] == []
    assert body["serviceRecord"]["completedTraining"] == []
    assert body["added"] == []


def test_profile_reports_how_complete_it_is(
    client: TestClient, customer_auth: dict[str, str]
) -> None:
    """The score tells the member what is still worth adding."""
    start = client.get(RECORD, headers=customer_auth).json()["completeness"]
    # A service record but no profile items: one of five parts filled.
    assert start["percent"] == 20
    assert set(start["missingKinds"]) == {"CREDENTIAL", "TRAINING", "EDUCATION", "EXPERIENCE"}

    for kind, name in (
        ("EDUCATION", "Associate of Applied Science"),
        ("EXPERIENCE", "Help Desk Technician"),
    ):
        client.post(f"{RECORD}/items", headers=customer_auth, json={"kind": kind, "name": name})

    after = client.get(RECORD, headers=customer_auth).json()["completeness"]
    assert after["percent"] == 60
    assert set(after["missingKinds"]) == {"CREDENTIAL", "TRAINING"}


def test_education_and_experience_are_saved_with_their_organisation(
    client: TestClient, customer_auth: dict[str, str]
) -> None:
    degree = client.post(
        f"{RECORD}/items",
        headers=customer_auth,
        json={
            "kind": "EDUCATION",
            "name": "Bachelor of Science in Information Technology",
            "organization": "Western Governors University",
            "detail": "Expected 2027",
        },
    )
    assert degree.status_code == 201
    body = degree.json()
    assert body["kind"] == "EDUCATION"
    assert body["organization"] == "Western Governors University"
    assert body["detail"] == "Expected 2027"

    job = client.post(
        f"{RECORD}/items",
        headers=customer_auth,
        json={"kind": "EXPERIENCE", "name": "Help Desk Technician", "organization": "Fort Hood"},
    ).json()
    assert job["detail"] is None  # optional, and absent means absent

    kinds = {item["kind"] for item in client.get(RECORD, headers=customer_auth).json()["added"]}
    assert kinds == {"EDUCATION", "EXPERIENCE"}


def test_member_adds_and_removes_an_item(client: TestClient, customer_auth: dict[str, str]) -> None:
    created = client.post(
        f"{RECORD}/items",
        headers=customer_auth,
        json={"kind": "CREDENTIAL", "name": "  CompTIA   Security+ "},
    )
    assert created.status_code == 201
    item = created.json()
    assert item["name"] == "CompTIA Security+"  # whitespace tidied
    assert item["source"] == "MANUAL"

    assert len(client.get(RECORD, headers=customer_auth).json()["added"]) == 1

    removed = client.delete(f"{RECORD}/items/{item['itemId']}", headers=customer_auth)
    assert removed.status_code == 204
    assert client.get(RECORD, headers=customer_auth).json()["added"] == []


def test_duplicates_are_refused_case_insensitively(
    client: TestClient, customer_auth: dict[str, str]
) -> None:
    client.post(
        f"{RECORD}/items", headers=customer_auth, json={"kind": "TRAINING", "name": "Lean Basics"}
    )
    again = client.post(
        f"{RECORD}/items", headers=customer_auth, json={"kind": "TRAINING", "name": "lean basics"}
    )
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "RECORD_ITEM_EXISTS"


def test_bad_items_all_return_one_code(client: TestClient, customer_auth: dict[str, str]) -> None:
    for bad in (
        {"kind": "HOBBY", "name": "Chess"},
        {"kind": "TRAINING", "name": "   "},
        {"kind": "TRAINING", "name": "x" * 201},
        {"kind": "EDUCATION", "name": "Degree", "organization": "x" * 201},
        {"kind": "EXPERIENCE", "name": "Role", "detail": "x" * 501},
    ):
        response = client.post(f"{RECORD}/items", headers=customer_auth, json=bad)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "INVALID_RECORD_ITEM"


def test_one_member_cannot_remove_anothers_item(
    client: TestClient, customer_auth: dict[str, str], other_customer_auth: dict[str, str]
) -> None:
    item = client.post(
        f"{RECORD}/items", headers=customer_auth, json={"kind": "TRAINING", "name": "Mine"}
    ).json()
    response = client.delete(f"{RECORD}/items/{item['itemId']}", headers=other_customer_auth)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "RECORD_ITEM_NOT_FOUND"


def test_record_is_member_only(client: TestClient, agent_auth: dict[str, str]) -> None:
    assert client.get(RECORD, headers=agent_auth).status_code == 403
    assert client.get(RECORD).status_code == 401


# ---------------------------------------------------------------------------
# The point of the feature: saved once, used in every conversation
# ---------------------------------------------------------------------------
def test_added_items_reach_every_new_conversation(
    client: TestClient, member_with_history: dict[str, str], monkeypatch
) -> None:
    customer_auth = member_with_history
    from app.modules.ai_integration import service as ai_service

    seen_prompts: list[str] = []
    original = ai_service.AIIntegrationService.build_prompt

    def spy(self, context):  # type: ignore[no-untyped-def]
        prompt = original(self, context)
        seen_prompts.append(prompt.system)
        return prompt

    monkeypatch.setattr(ai_service.AIIntegrationService, "build_prompt", spy)

    # Ask once before, so the member's context is cached.
    first = client.post("/api/v1/conversations", headers=customer_auth).json()["conversationId"]
    client.post(
        f"/api/v1/conversations/{first}/messages",
        headers=customer_auth,
        json={"message": "Which certification should I work toward next?"},
    )
    assert "CompTIA Security+" not in seen_prompts[-1]

    client.post(
        f"{RECORD}/items",
        headers=customer_auth,
        json={"kind": "CREDENTIAL", "name": "CompTIA Security+"},
    )

    # Two fresh conversations; neither asks the member to repeat anything.
    for _ in range(2):
        conversation = client.post("/api/v1/conversations", headers=customer_auth).json()[
            "conversationId"
        ]
        client.post(
            f"/api/v1/conversations/{conversation}/messages",
            headers=customer_auth,
            json={"message": "Which certification should I work toward next?"},
        )
        assert "CompTIA Security+" in seen_prompts[-1]
        # Added to what was already there, not replacing it.
        assert "CompTIA A+" in seen_prompts[-1]


# ---------------------------------------------------------------------------
# Uploads
# ---------------------------------------------------------------------------
TRANSCRIPT = """JOINT SERVICES TRANSCRIPT (sample)
Name: Alex Rivera

Military Courses
1. AR-1715-0799 Network Administration Course 2019
2. Basic Leader Course 03/14/2021
- Information Assurance Fundamentals

Certifications
- CompTIA Security+ (2023)
- Cisco CCNA
Page 1 of 2
"""


def test_transcript_text_is_split_into_training_and_credentials() -> None:
    found, skipped = extract_candidates("transcript.txt", _b64(TRANSCRIPT))
    by_kind = {(item.kind, item.name) for item in found}

    assert ("TRAINING", "Network Administration Course") in by_kind
    assert ("TRAINING", "Basic Leader Course") in by_kind
    assert ("TRAINING", "Information Assurance Fundamentals") in by_kind
    assert ("CREDENTIAL", "CompTIA Security+ ()") not in by_kind  # dates stripped cleanly
    assert any(
        kind == "CREDENTIAL" and name.startswith("CompTIA Security+") for kind, name in by_kind
    )
    assert ("CREDENTIAL", "Cisco CCNA") in by_kind
    # Headers, names and page numbers are not treated as training.
    assert not any("Page 1" in name or "Alex Rivera" in name for _, name in by_kind)
    assert skipped >= 1


def test_csv_with_a_header_uses_its_columns() -> None:
    csv_text = "type,name,date\ncertification,AWS Certified Cloud Practitioner,2024\ncourse,Lean Six Sigma Yellow Belt Course,2023\n"
    found, _ = extract_candidates("record.csv", _b64(csv_text))
    assert {(item.kind, item.name) for item in found} == {
        ("CREDENTIAL", "AWS Certified Cloud Practitioner"),
        ("TRAINING", "Lean Six Sigma Yellow Belt Course"),
    }


def test_pdf_text_is_extracted() -> None:
    from io import BytesIO

    from pypdf import PdfWriter
    from pypdf.generic import NameObject

    # A minimal one-page PDF with a text stream.
    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=200)
    stream = b"BT /F1 12 Tf 20 150 Td (Certifications) Tj 0 -20 Td (CompTIA Network+) Tj ET"
    from pypdf.generic import DecodedStreamObject, DictionaryObject

    content = DecodedStreamObject()
    content.set_data(stream)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
    )
    page[NameObject("/Contents")] = writer._add_object(content)
    buffer = BytesIO()
    writer.write(buffer)

    found, _ = extract_candidates("record.pdf", base64.b64encode(buffer.getvalue()).decode())
    assert ("CREDENTIAL", "CompTIA Network+") in {(item.kind, item.name) for item in found}


def test_import_previews_without_saving_then_bulk_saves(
    client: TestClient, customer_auth: dict[str, str]
) -> None:
    preview = client.post(
        f"{RECORD}/import",
        headers=customer_auth,
        json={"filename": "transcript.txt", "contentBase64": _b64(TRANSCRIPT)},
    )
    assert preview.status_code == 200
    candidates = preview.json()["candidates"]
    assert candidates
    assert client.get(RECORD, headers=customer_auth).json()["added"] == []  # nothing saved

    saved = client.post(
        f"{RECORD}/items/bulk", headers=customer_auth, json={"items": candidates}
    ).json()
    assert len(saved["added"]) == len(candidates)
    assert all(item["source"] == "UPLOAD" for item in saved["added"])

    again = client.post(
        f"{RECORD}/items/bulk", headers=customer_auth, json={"items": candidates}
    ).json()
    assert again["added"] == []
    assert again["alreadyOnRecord"] == len(candidates)


def test_unsupported_or_broken_files_are_refused(
    client: TestClient, customer_auth: dict[str, str]
) -> None:
    wrong_type = client.post(
        f"{RECORD}/import",
        headers=customer_auth,
        json={"filename": "photo.jpg", "contentBase64": _b64("x")},
    )
    assert wrong_type.json()["error"]["code"] == "UNSUPPORTED_RECORD_FILE"

    broken = client.post(
        f"{RECORD}/import",
        headers=customer_auth,
        json={"filename": "notes.txt", "contentBase64": "@@not base64@@"},
    )
    assert broken.json()["error"]["code"] == "INVALID_RECORD_FILE"


def test_upload_route_accepts_a_document_larger_than_other_routes(
    client: TestClient, customer_auth: dict[str, str]
) -> None:
    big = _b64("Basic Leader Course\n" * 5000)  # ~130 KB, over the normal 64 KB limit
    response = client.post(
        f"{RECORD}/import",
        headers=customer_auth,
        json={"filename": "long.txt", "contentBase64": big},
    )
    assert response.status_code == 200

    normal = client.post(
        f"{RECORD}/items", headers=customer_auth, json={"kind": "TRAINING", "name": "x" * 70000}
    )
    assert normal.status_code == 413


# ---------------------------------------------------------------------------
# A whole resume, in one upload
# ---------------------------------------------------------------------------
RESUME = """Alex Rivera
alex@example.com

Education
Associate of Applied Science in Network Systems, Central Texas College
Bachelor of Science in Information Technology - Western Governors University

Certifications
CompTIA Security+ (2023)
Cisco CCNA

Military Training
Network Administration Course
Basic Leader Course

Work Experience
Information Technology Specialist at 1st Signal Brigade
Help Desk Technician - Fort Hood
"""


def test_a_resume_fills_all_four_kinds() -> None:
    found, _ = extract_candidates("resume.txt", _b64(RESUME))
    by_kind: dict[str, list[str]] = {}
    for item in found:
        by_kind.setdefault(item.kind, []).append(item.name)

    assert set(by_kind) == {"CREDENTIAL", "TRAINING", "EDUCATION", "EXPERIENCE"}
    assert "CompTIA Security+" in by_kind["CREDENTIAL"]
    assert "Basic Leader Course" in by_kind["TRAINING"]
    assert "Bachelor of Science in Information Technology" in by_kind["EDUCATION"]
    assert "Help Desk Technician" in by_kind["EXPERIENCE"]
    # Contact details are not experience.
    assert not any("alex@example.com" in name for names in by_kind.values() for name in names)


def test_an_upload_separates_the_title_from_the_organisation() -> None:
    found, _ = extract_candidates("resume.txt", _b64(RESUME))
    by_name = {item.name: item.organization for item in found}

    assert (
        by_name["Bachelor of Science in Information Technology"] == "Western Governors University"
    )
    assert by_name["Associate of Applied Science in Network Systems"] == "Central Texas College"
    assert by_name["Information Technology Specialist"] == "1st Signal Brigade"
    # A title with no organisation stays whole.
    assert by_name["Cisco CCNA"] is None


def test_a_resume_upload_is_saved_once_confirmed(
    client: TestClient, customer_auth: dict[str, str]
) -> None:
    candidates = client.post(
        f"{RECORD}/import",
        headers=customer_auth,
        json={"filename": "resume.txt", "contentBase64": _b64(RESUME)},
    ).json()["candidates"]

    saved = client.post(
        f"{RECORD}/items/bulk", headers=customer_auth, json={"items": candidates}
    ).json()
    assert len(saved["added"]) == len(candidates)

    record = client.get(RECORD, headers=customer_auth).json()
    assert record["completeness"]["percent"] == 100
    assert record["completeness"]["missingKinds"] == []
    degree = next(item for item in record["added"] if item["kind"] == "EDUCATION")
    assert degree["organization"]


# ---------------------------------------------------------------------------
# The development plan
# ---------------------------------------------------------------------------
def test_a_plan_item_is_stored_and_removable(client: TestClient, customer_auth) -> None:
    """A member decides what they are working toward, and can change their mind."""
    created = client.post(
        f"{RECORD}/items",
        headers=customer_auth,
        json={"kind": "GOAL", "name": "Bachelor of Science in Information Technology"},
    )
    assert created.status_code == 201
    item_id = created.json()["itemId"]

    record = client.get(RECORD, headers=customer_auth).json()
    assert any(item["kind"] == "GOAL" for item in record["added"])

    assert client.delete(f"{RECORD}/items/{item_id}", headers=customer_auth).status_code == 204
    record = client.get(RECORD, headers=customer_auth).json()
    assert not any(item["kind"] == "GOAL" for item in record["added"])


def test_a_plan_does_not_count_toward_completeness(client: TestClient, customer_auth) -> None:
    """Completeness measures what you have done, not what you intend to do."""
    before = client.get(RECORD, headers=customer_auth).json()["completeness"]
    client.post(
        f"{RECORD}/items",
        headers=customer_auth,
        json={"kind": "GOAL", "name": "CompTIA Security+"},
    )
    after = client.get(RECORD, headers=customer_auth).json()["completeness"]

    assert after["percent"] == before["percent"]
    assert "GOAL" not in after["missingKinds"]


def test_a_plan_is_never_sent_to_the_provider(client: TestClient, customer_auth) -> None:
    """A goal is an intention. Nothing downstream may treat it as a fact."""
    client.post(
        f"{RECORD}/items",
        headers=customer_auth,
        json={"kind": "GOAL", "name": "Bachelor of Science in Information Technology"},
    )
    record = client.get(RECORD, headers=customer_auth).json()
    goal = next(item for item in record["added"] if item["kind"] == "GOAL")

    reply = client.post(
        "/api/v1/conversations",
        headers=customer_auth,
    ).json()["conversationId"]
    answer = client.post(
        f"/api/v1/conversations/{reply}/messages",
        headers=customer_auth,
        json={"message": "What should I do next?"},
    ).json()

    assert goal["name"] not in answer["response"]
