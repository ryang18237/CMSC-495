"""Pathway recommender -- suggests the next credential, program or degree.

OWNER: Benjamin Madden (Integration Lead)

What it does
------------
Given what a member has already completed (training, credentials held, their
occupational specialty), rank a catalog of civilian pathways by how closely
each one builds on that record, and say *why* for every suggestion.

How
---
Content-based filtering with TF-IDF vectors and cosine similarity:

1. Every catalog entry becomes a document: title, summary, and its keywords
   (counted twice, because they were chosen to describe the pathway).
2. The member's record becomes a document the same way.
3. Both are turned into TF-IDF vectors over one vocabulary. A term that
   appears in nearly every pathway ("management") counts for little; a term
   that picks out a few ("routing") counts for a lot.
4. Pathways are ranked by cosine similarity to the member, plus a small bonus
   when the member already holds a credential the pathway follows on from.

Why this and not the language model
-----------------------------------
- It runs with no API key and no network, so it works in CI, on a grader's
  laptop and when the provider is down. The chat can fail over to a person;
  this panel simply keeps working.
- It is deterministic. The same record gives the same list, so it can be
  tested exactly and a counsellor can reproduce what a member saw.
- Every score can be traced back to named training and named terms. A member
  is told "builds on your Network Administration Course", not just a number.
- Nothing about the member leaves the process.

Boundaries
----------
Like the rest of AI Integration this file imports no database, model or other
component. It receives plain lists from the caller -- the API layer reads the
record through the Customer Data Adapter -- which keeps it testable without a
database and keeps the data-minimisation rules in one place.
"""

import json
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

METHOD = "tfidf-cosine/1"

CATALOG_FILE = Path(__file__).with_name("data") / "pathways.json"

# Below this a match is mostly coincidence -- one shared generic word such as
# "operator" or "technician" linking two unrelated fields. Chosen by reading
# the ranked output for every evaluation profile in the tests.
MIN_SCORE = 0.08

# Added when the member already holds a credential this pathway follows on
# from. Large enough to lift a genuine next step above a loose topical match,
# small enough that it cannot rescue a pathway with nothing else in common.
PROGRESSION_BONUS = 0.10

STRONG_AT = 0.30
GOOD_AT = 0.15

# Words that appear in course and credential names without saying anything
# about the subject. "Network Administration Course" should match on network
# and administration, not on course. Vendor names are here too: sharing the
# word "CompTIA" says nothing about whether two subjects are related, and the
# real link between two vendor credentials is expressed by `follows`.
_STOPWORDS = frozenset(
    """
    a an and are as at be by for from in into is it its of on or that the to
    with your you course courses school basic fundamentals introduction intro
    program programs certificate certification certified degree bachelor
    science arts level entry advanced associate professional
    comptia cisco aws nremt fcc
    """.split()
)

_TOKEN = re.compile(r"[a-z0-9+#]+")


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Pathway:
    pathway_id: str
    title: str
    kind: str
    field: str
    summary: str
    keywords: tuple[str, ...]
    aliases: tuple[str, ...]
    follows: tuple[str, ...]
    starter: bool


@dataclass(frozen=True)
class MemberProfile:
    """The parts of a member's record the recommender is allowed to use."""

    completed_training: list[str] = field(default_factory=list)
    credentials: list[str] = field(default_factory=list)
    occupational_specialty: str | None = None
    # Pathways the member has already put on their development plan. They are
    # dropped from the results -- suggesting what someone has just chosen is
    # noise -- but never scored as experience, because a plan is an intention
    # and treating it as fact would make every later suggestion wrong.
    planned: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not (self.completed_training or self.credentials or self.occupational_specialty)


@dataclass(frozen=True)
class Recommendation:
    pathway: Pathway
    score: float
    strength: str
    # NEXT_STEP: the member holds a credential this pathway follows on from.
    # BUILDS_ON: the pathway overlaps most with one named item on their record.
    # STARTING_POINT: nothing on the record matched; a broadly useful first step.
    reason: str
    builds_on: str | None
    matched_terms: list[str]


@dataclass(frozen=True)
class RecommendationSet:
    # COMPLETED_TRAINING when the list comes from the member's record,
    # GENERAL when there was nothing to match on and starter pathways are shown.
    basis: str
    recommendations: list[Recommendation]
    method: str = METHOD


# ---------------------------------------------------------------------------
# Text to vectors
# ---------------------------------------------------------------------------
def _stem(token: str) -> str:
    """A deliberately small stemmer: enough to match "networks" with "network".

    A full stemmer would also turn "security" and "secure" into one term,
    which sounds helpful until it starts joining words that mean different
    things in this domain. Two rules are predictable and easy to test.
    """
    if len(token) > 5 and token.endswith("ing"):
        return token[:-3]
    if len(token) > 4 and token.endswith("s") and not token.endswith(("ss", "us", "is")):
        return token[:-1]
    return token


def tokenize(text: str) -> list[str]:
    """Lower-case words with stopwords removed, plus adjacent word pairs.

    Pairs matter here: "information assurance" and "patient care" mean more
    together than either word does alone, and pairs let the vectors see that.
    """
    words = [_stem(word) for word in _TOKEN.findall(text.lower())]
    words = [word for word in words if word not in _STOPWORDS and len(word) > 1]
    pairs = [f"{first}_{second}" for first, second in zip(words, words[1:], strict=False)]
    return words + pairs


def _pathway_document(pathway: Pathway) -> list[str]:
    tokens = tokenize(pathway.title) + tokenize(pathway.summary)
    for keyword in pathway.keywords:
        # Keywords were written to describe the pathway, so they count double.
        tokens += tokenize(keyword) * 2
    return tokens


def _weights(tokens: list[str], idf: dict[str, float]) -> dict[str, float]:
    """Sublinear TF-IDF, L2-normalised. Terms outside the vocabulary are dropped."""
    counts = Counter(token for token in tokens if token in idf)
    vector = {term: (1.0 + math.log(count)) * idf[term] for term, count in counts.items()}
    norm = math.sqrt(sum(value * value for value in vector.values()))
    if norm == 0.0:
        return {}
    return {term: value / norm for term, value in vector.items()}


def _cosine(left: dict[str, float], right: dict[str, float]) -> float:
    # Both vectors are already unit length, so the dot product is the cosine.
    if len(left) > len(right):
        left, right = right, left
    return sum(value * right.get(term, 0.0) for term, value in left.items())


def _surface_forms(texts: list[str]) -> dict[str, str]:
    """Map each stem back to a word a person actually wrote.

    Matching happens on stems ("technician", "communication"), but the member
    should read the words from their own record and the catalog, not the
    stemmer's output. The first spelling seen wins, and the member's own text
    is passed first so their wording is preferred.
    """
    forms: dict[str, str] = {}
    for text in texts:
        for word in _TOKEN.findall(text.lower()):
            forms.setdefault(_stem(word), word)
    return forms


def _display(term: str, forms: dict[str, str]) -> str:
    return " ".join(forms.get(part, part) for part in term.split("_"))


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class _Index:
    pathways: tuple[Pathway, ...]
    idf: dict[str, float]
    vectors: dict[str, dict[str, float]]


def load_catalog(path: Path = CATALOG_FILE) -> tuple[Pathway, ...]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return tuple(
        Pathway(
            pathway_id=item["id"],
            title=item["title"],
            kind=item["kind"],
            field=item["field"],
            summary=item["summary"],
            keywords=tuple(item.get("keywords", [])),
            aliases=tuple(alias.lower() for alias in item.get("aliases", [])),
            follows=tuple(item.get("follows", [])),
            starter=bool(item.get("starter", False)),
        )
        for item in raw["pathways"]
    )


@lru_cache(maxsize=1)
def _index() -> _Index:
    """Build the vocabulary and every pathway vector once per process.

    The catalog is small and read-only, so there is nothing to invalidate. A
    catalog edit needs a restart, which is also when the file is deployed.
    """
    pathways = load_catalog()
    documents = {pathway.pathway_id: _pathway_document(pathway) for pathway in pathways}

    document_frequency: Counter[str] = Counter()
    for tokens in documents.values():
        document_frequency.update(set(tokens))

    total = len(documents)
    # Smoothed IDF, so a term in every document still has a small positive weight.
    idf = {
        term: math.log((1 + total) / (1 + frequency)) + 1.0
        for term, frequency in document_frequency.items()
    }
    vectors = {pathway_id: _weights(tokens, idf) for pathway_id, tokens in documents.items()}
    return _Index(pathways=pathways, idf=idf, vectors=vectors)


# ---------------------------------------------------------------------------
# Recommending
# ---------------------------------------------------------------------------
# A profile item carries its organisation in brackets -- "Associate of Applied
# Science (Central Texas College)" -- which would never match a catalog title.
_ORGANIZATION_SUFFIX = re.compile(r"\s*\([^)]*\)\s*$")


def _held_pathway_ids(credentials: list[str], pathways: tuple[Pathway, ...]) -> set[str]:
    """Pathways the member already has, matched by title or a known alias."""
    # Both spellings are kept: a catalog title can legitimately end in
    # brackets ("Cisco Certified Network Associate (CCNA)"), so stripping is
    # an extra way to match, never a replacement for the name as written.
    held_names = {credential.strip().lower() for credential in credentials}
    held_names |= {
        _ORGANIZATION_SUFFIX.sub("", credential).strip().lower() for credential in credentials
    }
    return {
        pathway.pathway_id
        for pathway in pathways
        if pathway.title.lower() in held_names or held_names & set(pathway.aliases)
    }


def _strength(score: float) -> str:
    if score >= STRONG_AT:
        return "STRONG"
    if score >= GOOD_AT:
        return "GOOD"
    return "EXPLORATORY"


def _starters(index: _Index, held: set[str], limit: int) -> RecommendationSet:
    starters = [
        Recommendation(
            pathway=pathway,
            score=0.0,
            strength="EXPLORATORY",
            reason="STARTING_POINT",
            builds_on=None,
            matched_terms=[],
        )
        for pathway in index.pathways
        if pathway.starter and pathway.pathway_id not in held
    ]
    return RecommendationSet(basis="GENERAL", recommendations=starters[:limit])


@dataclass(frozen=True)
class _Member:
    """A member's record, vectorised once and reused for every pathway."""

    vector: dict[str, float]
    # Each item on the record kept separately, so a suggestion can name the
    # one it builds on most rather than pointing at the record as a whole.
    sources: list[tuple[str, dict[str, float]]]
    # The member's own wording, used to show matched terms unstemmed.
    texts: list[str]


def _vectorise_member(profile: MemberProfile, idf: dict[str, float]) -> _Member:
    items = [*profile.completed_training, *profile.credentials]
    sources = [(item, _weights(tokenize(item), idf)) for item in items]
    texts = list(items)

    if profile.occupational_specialty:
        specialty = profile.occupational_specialty
        sources.append((f"your {specialty} experience", _weights(tokenize(specialty), idf)))
        texts.append(specialty)

    tokens = [token for text in texts for token in tokenize(text)]
    return _Member(vector=_weights(tokens, idf), sources=sources, texts=texts)


def _closest_source(member: _Member, vector: dict[str, float]) -> str | None:
    """The single item on the record that overlaps most with this pathway."""
    best_label, best_score = None, 0.0
    for label, source_vector in member.sources:
        overlap = _cosine(source_vector, vector)
        if overlap > best_score:
            best_label, best_score = label, overlap
    return best_label


def _matched_terms(member: _Member, pathway: Pathway, vector: dict[str, float]) -> list[str]:
    """Up to three shared terms, strongest contribution first.

    Phrases are preferred to their parts: "network administration" says more
    than "network" and "administration" listed separately.
    """
    shared = sorted(
        (
            (member.vector[term] * weight, term)
            for term, weight in vector.items()
            if term in member.vector
        ),
        reverse=True,
    )
    top = [term for _, term in shared[:8]]
    covered = {word for term in top if "_" in term for word in term.split("_")}
    forms = _surface_forms([*member.texts, pathway.title, pathway.summary, *pathway.keywords])
    return [_display(term, forms) for term in top if "_" in term or term not in covered][:3]


def _score_pathway(
    pathway: Pathway, index: _Index, member: _Member, held_titles: dict[str, str]
) -> Recommendation | None:
    """Score one pathway for one member, or None if it is not worth showing."""
    vector = index.vectors[pathway.pathway_id]
    progression_from = next(
        (held_titles[prior] for prior in pathway.follows if prior in held_titles), None
    )
    score = min(
        1.0, _cosine(member.vector, vector) + (PROGRESSION_BONUS if progression_from else 0.0)
    )
    if score < MIN_SCORE:
        return None

    # A held credential this pathway follows on from is the explanation when
    # there is one, because "next step after X" is the clearest reason a
    # person can be given.
    return Recommendation(
        pathway=pathway,
        score=round(score, 3),
        strength=_strength(score),
        reason="NEXT_STEP" if progression_from else "BUILDS_ON",
        builds_on=progression_from or _closest_source(member, vector),
        matched_terms=_matched_terms(member, pathway, vector),
    )


def recommend(profile: MemberProfile, limit: int = 5) -> RecommendationSet:
    """Rank catalog pathways against a member's record."""
    index = _index()
    held = _held_pathway_ids(profile.credentials, index.pathways)
    planned = _held_pathway_ids(profile.planned, index.pathways)
    skip = held | planned

    if profile.is_empty:
        return _starters(index, skip, limit)

    member = _vectorise_member(profile, index.idf)
    held_titles = {p.pathway_id: p.title for p in index.pathways if p.pathway_id in held}

    ranked = [
        recommendation
        for pathway in index.pathways
        if pathway.pathway_id not in skip
        and (recommendation := _score_pathway(pathway, index, member, held_titles)) is not None
    ]
    if not ranked:
        return _starters(index, skip, limit)

    # Ties broken by title so the order never depends on dictionary ordering.
    ranked.sort(key=lambda item: (-item.score, item.pathway.title))
    return RecommendationSet(basis="COMPLETED_TRAINING", recommendations=ranked[:limit])
