"""Pathway recommender: ranking, explanations, evaluation and the HTTP route.

The unit tests need no database -- the recommender takes plain lists -- which
is the boundary the design asks for. The evaluation section measures ranking
quality against hand-labelled profiles, so a catalog or scoring change that
makes suggestions worse fails the build instead of shipping quietly.
"""

import threading
import time

import pytest
from fastapi.testclient import TestClient

from app.modules.ai_integration.providers import anthropic_provider
from app.modules.ai_integration.recommender import (
    MIN_SCORE,
    MemberProfile,
    load_catalog,
    recommend,
    tokenize,
)

IT_SPECIALIST = MemberProfile(
    completed_training=[
        "Basic Leader Course",
        "Network Administration Course",
        "Information Assurance Fundamentals",
    ],
    credentials=["CompTIA A+"],
    occupational_specialty="Information Technology Specialist",
)

CORPSMAN = MemberProfile(
    completed_training=[
        "Hospital Corpsman A School",
        "Emergency Medical Technician Course",
        "Instructor Training",
    ],
    credentials=["EMT-Basic"],
    occupational_specialty="Hospital Corpsman",
)


def _ids(profile: MemberProfile, limit: int = 5) -> list[str]:
    return [item.pathway.pathway_id for item in recommend(profile, limit).recommendations]


# ---------------------------------------------------------------------------
# Text handling
# ---------------------------------------------------------------------------
def test_tokenize_drops_generic_course_words_and_keeps_phrases() -> None:
    tokens = tokenize("Network Administration Course")
    assert "course" not in tokens
    assert "network" in tokens
    assert "network_administration" in tokens


def test_tokenize_matches_plurals_and_ing_forms() -> None:
    assert "network" in tokenize("networks")
    assert "network" in tokenize("networking")
    # "ss" endings are not plurals.
    assert "access" in tokenize("access")


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------
def test_it_specialist_is_steered_to_networking_and_security() -> None:
    top = _ids(IT_SPECIALIST, 3)
    assert "comptia-network-plus" in top
    assert "comptia-security-plus" in top


def test_corpsman_is_steered_to_clinical_pathways() -> None:
    top = _ids(CORPSMAN, 3)
    assert "nremt-paramedic" in top
    assert {"lpn-program", "bsn-nursing"} & set(top)


def test_credentials_already_held_are_never_suggested() -> None:
    assert "comptia-a-plus" not in _ids(IT_SPECIALIST, 10)
    assert "emt-basic" not in _ids(CORPSMAN, 10)


def test_held_credential_is_matched_by_alias_as_well_as_title() -> None:
    profile = MemberProfile(credentials=["Security+"], completed_training=["Cyber course"])
    assert "comptia-security-plus" not in _ids(profile, 10)


def test_next_step_is_explained_by_the_credential_it_follows() -> None:
    result = recommend(CORPSMAN, 5)
    paramedic = next(i for i in result.recommendations if i.pathway.pathway_id == "nremt-paramedic")
    assert paramedic.reason == "NEXT_STEP"
    assert paramedic.builds_on == "Emergency Medical Technician (EMT)"


def test_topical_match_names_the_training_it_builds_on() -> None:
    result = recommend(CORPSMAN, 5)
    design = next(
        i for i in result.recommendations if i.pathway.pathway_id == "instructional-design"
    )
    assert design.reason == "BUILDS_ON"
    assert design.builds_on == "Instructor Training"
    # Shown in the member's own words, not the stemmer's.
    assert "instructor training" in design.matched_terms


def test_scores_are_bounded_sorted_and_labelled() -> None:
    items = recommend(IT_SPECIALIST, 10).recommendations
    scores = [item.score for item in items]
    assert scores == sorted(scores, reverse=True)
    assert all(MIN_SCORE <= score <= 1.0 for score in scores)
    for item in items:
        expected = "STRONG" if item.score >= 0.30 else "GOOD" if item.score >= 0.15 else None
        if expected:
            assert item.strength == expected


def test_same_record_gives_the_same_list() -> None:
    assert _ids(IT_SPECIALIST, 10) == _ids(IT_SPECIALIST, 10)


def test_limit_is_respected() -> None:
    assert len(recommend(IT_SPECIALIST, 2).recommendations) == 2


def test_unrelated_fields_are_not_forced_in() -> None:
    """A driver is not told to become a radio technician because both say "operator"."""
    driver = MemberProfile(
        completed_training=["Motor Transport Operator Course"],
        occupational_specialty="Motor Transport Operator",
    )
    assert "fcc-grol" not in _ids(driver, 10)


def test_empty_record_falls_back_to_starting_points() -> None:
    result = recommend(MemberProfile(), 5)
    assert result.basis == "GENERAL"
    assert result.recommendations
    assert all(item.reason == "STARTING_POINT" for item in result.recommendations)


def test_record_with_nothing_in_common_also_falls_back() -> None:
    result = recommend(MemberProfile(completed_training=["Xylophone"]), 5)
    assert result.basis == "GENERAL"


def test_catalog_references_are_valid() -> None:
    """Every `follows` entry must name a pathway that exists."""
    catalog = load_catalog()
    ids = {pathway.pathway_id for pathway in catalog}
    assert len(ids) == len(catalog), "duplicate pathway ids"
    for pathway in catalog:
        assert set(pathway.follows) <= ids, pathway.pathway_id
        assert pathway.pathway_id not in pathway.follows


# ---------------------------------------------------------------------------
# Offline evaluation
#
# Each profile is a realistic service record and the pathways a counsellor
# would expect to see near the top. Hit rate asks "is at least one of them in
# the top three?"; precision asks "what share of the top three are relevant?".
# ---------------------------------------------------------------------------
EVALUATION = [
    (IT_SPECIALIST, {"comptia-network-plus", "comptia-security-plus", "cisco-ccna"}),
    (CORPSMAN, {"nremt-paramedic", "lpn-program", "bsn-nursing"}),
    (
        MemberProfile(
            ["Motor Transport Operator Course", "Hazardous Materials Handling"],
            [],
            "Motor Transport Operator",
        ),
        {"cdl-class-a", "supply-chain-certificate"},
    ),
    (
        MemberProfile(
            ["Electronics Technician A School", "Radio Communications Maintenance"],
            [],
            "Electronics Technician",
        ),
        {"fcc-grol", "electrical-apprenticeship"},
    ),
    (
        MemberProfile(
            ["Cyber Systems Operations Course", "Information Assurance Fundamentals"],
            ["CompTIA Security+"],
            "Cyber Systems Operations",
        ),
        {"comptia-cysa-plus", "comptia-linux-plus", "bs-information-technology"},
    ),
    (
        MemberProfile(
            ["Combat Medic Specialist Course", "Tactical Combat Casualty Care"],
            [],
            "Combat Medic Specialist",
        ),
        {"nremt-paramedic", "lpn-program", "emt-basic"},
    ),
    (
        MemberProfile(["Basic Leader Course", "Senior Leader Course"], [], None),
        {"ba-organizational-leadership", "pmp", "capm"},
    ),
]


def evaluate(k: int = 3) -> tuple[float, float]:
    """Hit rate and mean precision at k across the labelled profiles."""
    hits, precision = 0, 0.0
    for profile, relevant in EVALUATION:
        top = _ids(profile, k)
        found = len(set(top) & relevant)
        hits += 1 if found else 0
        precision += found / k
    return hits / len(EVALUATION), precision / len(EVALUATION)


def test_every_labelled_profile_gets_a_relevant_pathway_in_the_top_three() -> None:
    hit_rate, _ = evaluate(3)
    assert hit_rate == 1.0


def test_most_of_the_top_three_is_relevant() -> None:
    _, precision = evaluate(3)
    # 0.60 is the floor, not the target: the measured value is reported in
    # docs/metrics. Anything below this means the catalog or scoring regressed.
    assert precision >= 0.60, precision


# ---------------------------------------------------------------------------
# HTTP route
# ---------------------------------------------------------------------------
def test_member_gets_recommendations_from_their_own_record(
    client: TestClient, member_with_history: dict[str, str]
) -> None:
    """Ranked against what the member entered, now that nothing is seeded."""
    response = client.get("/api/v1/pathways/recommended", headers=member_with_history)
    assert response.status_code == 200
    body = response.json()

    assert body["basis"] == "COMPLETED_TRAINING"
    assert body["method"].startswith("tfidf-cosine")
    assert body["disclaimer"]
    ids = [item["pathwayId"] for item in body["recommendations"]]
    assert "comptia-network-plus" in ids
    assert "comptia-a-plus" not in ids  # already held
    first = body["recommendations"][0]
    assert set(first) >= {"title", "score", "strength", "reason", "buildsOn", "matchedTerms"}


def test_two_members_get_different_suggestions(
    client: TestClient, customer_auth: dict[str, str], other_customer_auth: dict[str, str]
) -> None:
    it_member = client.get("/api/v1/pathways/recommended", headers=customer_auth).json()
    corpsman = client.get("/api/v1/pathways/recommended", headers=other_customer_auth).json()
    first_it = it_member["recommendations"][0]["pathwayId"]
    assert first_it not in {item["pathwayId"] for item in corpsman["recommendations"]}


def test_limit_is_validated(client: TestClient, member_with_history: dict[str, str]) -> None:
    customer_auth = member_with_history
    ok = client.get("/api/v1/pathways/recommended?limit=2", headers=customer_auth)
    assert len(ok.json()["recommendations"]) == 2

    for bad in ("0", "11", "many"):
        response = client.get(f"/api/v1/pathways/recommended?limit={bad}", headers=customer_auth)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_counsellors_are_refused(client: TestClient, agent_auth: dict[str, str]) -> None:
    response = client.get("/api/v1/pathways/recommended", headers=agent_auth)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_sign_in_is_required(client: TestClient) -> None:
    assert client.get("/api/v1/pathways/recommended").status_code == 401


# ---------------------------------------------------------------------------
# Shared HTTP client (peer review follow-up)
# ---------------------------------------------------------------------------
@pytest.fixture
def _fresh_pool() -> object:
    anthropic_provider.reset_shared_client()
    yield
    anthropic_provider.reset_shared_client()


@pytest.mark.usefixtures("_fresh_pool")
def test_concurrent_first_requests_share_one_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    """Twenty threads asking at once must all get the same client.

    Building the client is slowed down so the race window is wide enough to
    hit every time. Without the lock this creates several pools.
    """
    real_client = anthropic_provider.httpx.Client

    def slow_client(*args: object, **kwargs: object) -> object:
        time.sleep(0.05)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(anthropic_provider.httpx, "Client", slow_client)
    start = threading.Barrier(20)
    seen: list[int] = []

    def grab() -> None:
        start.wait()
        seen.append(id(anthropic_provider._shared_http_client(5.0)))

    threads = [threading.Thread(target=grab) for _ in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(seen) == 20
    assert len(set(seen)) == 1


# ---------------------------------------------------------------------------
# The development plan steers the list
# ---------------------------------------------------------------------------
def test_a_planned_pathway_drops_out_of_the_list() -> None:
    """Choosing something should move the member on, not keep offering it."""
    profile = MemberProfile(completed_training=["Network Administration Course"])
    before = recommend(profile, limit=5)
    chosen = before.recommendations[0].pathway

    after = recommend(
        MemberProfile(completed_training=["Network Administration Course"], planned=[chosen.title]),
        limit=5,
    )

    assert chosen.pathway_id not in {item.pathway.pathway_id for item in after.recommendations}
    # The rest move up rather than the list simply getting shorter.
    assert len(after.recommendations) == len(before.recommendations)


def test_a_plan_item_carrying_an_organisation_still_matches() -> None:
    """A profile item reads 'Title (Where)'; the catalog title has no brackets."""
    profile = MemberProfile(completed_training=["Network Administration Course"])
    chosen = recommend(profile, limit=5).recommendations[0].pathway

    after = recommend(
        MemberProfile(
            completed_training=["Network Administration Course"],
            planned=[f"{chosen.title} (Central Texas College)"],
        ),
        limit=5,
    )

    assert chosen.pathway_id not in {item.pathway.pathway_id for item in after.recommendations}


def test_a_plan_is_never_scored_as_experience() -> None:
    """A goal must not make the member look more qualified than they are."""
    planned_only = MemberProfile(planned=["CompTIA Security+"])
    assert planned_only.is_empty, "a plan alone is not a record"
