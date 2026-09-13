"""Knowledge Base Module.

Exposes approved support content through a stable interface so that the AI
Integration Module never depends on storage implementation details.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import NotFoundError
from app.models import KnowledgeArticle

_STOP_WORDS = {
    "the",
    "a",
    "an",
    "is",
    "are",
    "was",
    "were",
    "i",
    "my",
    "me",
    "you",
    "your",
    "to",
    "for",
    "of",
    "on",
    "in",
    "it",
    "this",
    "that",
    "and",
    "or",
    "why",
    "how",
    "what",
    "when",
    "can",
    "do",
    "does",
    "did",
    "please",
    "help",
    "with",
}


@dataclass(frozen=True)
class Article:
    article_id: uuid.UUID
    title: str
    body: str
    tags: list[str]


def _to_article(row: KnowledgeArticle) -> Article:
    return Article(
        article_id=row.id,
        title=row.title,
        body=row.body,
        tags=[tag.strip() for tag in row.tags.split(",") if tag.strip()],
    )


def _tokenize(text: str) -> set[str]:
    cleaned = "".join(ch.lower() if ch.isalnum() else " " for ch in text)
    return {word for word in cleaned.split() if len(word) > 2 and word not in _STOP_WORDS}


class KnowledgeBaseService:
    def __init__(self, db: Session) -> None:
        self._db = db

    def search_articles(self, query: str, limit: int = 3) -> list[Article]:
        """Rank approved articles by keyword overlap with the customer inquiry."""
        terms = _tokenize(query)
        if not terms:
            return []

        rows = list(self._db.scalars(select(KnowledgeArticle)))
        scored: list[tuple[int, KnowledgeArticle]] = []
        for row in rows:
            haystack = _tokenize(f"{row.title} {row.tags} {row.body}")
            score = len(terms & haystack)
            if score > 0:
                scored.append((score, row))

        scored.sort(key=lambda pair: (-pair[0], pair[1].title))
        return [_to_article(row) for _, row in scored[:limit]]

    def get_article(self, article_id: uuid.UUID) -> Article:
        row = self._db.get(KnowledgeArticle, article_id)
        if row is None:
            raise NotFoundError("Knowledge article not found.", code="ARTICLE_NOT_FOUND")
        return _to_article(row)
