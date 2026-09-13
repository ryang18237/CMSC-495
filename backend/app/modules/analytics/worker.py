"""Learning Analytics Worker (asynchronous processing boundary).

Drains the feedback event outbox, aggregates interaction patterns and writes
improvement candidates for human review. Nothing it produces is applied to the
production AI automatically -- every recommendation starts as PENDING_REVIEW.

Run it with:  python -m app.modules.analytics.worker
"""

import json
import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import ConversationMessage, FeedbackEvent, ImprovementRecommendation

logger = logging.getLogger("app.analytics")

# A pattern must recur at least this many times before it is worth a human's time.
RECURRENCE_THRESHOLD = 2


@dataclass(frozen=True)
class DateRange:
    start: datetime
    end: datetime

    @classmethod
    def last_days(cls, days: int = 7) -> "DateRange":
        end = datetime.now(timezone.utc)
        return cls(start=end - timedelta(days=days), end=end)


@dataclass
class PatternSummary:
    period: DateRange
    total_events: int = 0
    ratings: Counter[str] = field(default_factory=Counter)
    escalation_reasons: Counter[str] = field(default_factory=Counter)
    unhelpful_by_status: Counter[str] = field(default_factory=Counter)

    @property
    def unhelpful_rate(self) -> float:
        total = sum(self.ratings.values())
        return (self.ratings.get("UNHELPFUL", 0) / total) if total else 0.0


@dataclass(frozen=True)
class ImprovementCandidate:
    category: str
    detail: str
    occurrences: int


@dataclass(frozen=True)
class ConfigurationRecommendation:
    category: str
    detail: str
    occurrences: int
    review_status: str = "PENDING_REVIEW"


class LearningAnalyticsWorker:
    def __init__(self, db: Session) -> None:
        self._db = db

    def aggregate_interaction_patterns(self, period: DateRange) -> PatternSummary:
        summary = PatternSummary(period=period)

        events = list(
            self._db.scalars(
                select(FeedbackEvent)
                .where(FeedbackEvent.processed.is_(False))
                .order_by(FeedbackEvent.created_at)
            )
        )
        for event in events:
            try:
                payload = json.loads(event.payload)
            except json.JSONDecodeError:
                logger.warning("skipping malformed feedback event %s", event.id)
                continue

            summary.total_events += 1
            rating = str(payload.get("rating", "UNKNOWN"))
            summary.ratings[rating] += 1
            if rating == "UNHELPFUL":
                summary.unhelpful_by_status[str(payload.get("assistantStatus", "UNKNOWN"))] += 1
            event.processed = True

        # Escalation reasons come from the stored messages, not from feedback,
        # so the picture covers turns nobody left feedback on.
        escalated = self._db.scalars(
            select(ConversationMessage)
            .where(ConversationMessage.escalation_reason.is_not(None))
            .where(ConversationMessage.created_at >= period.start)
        )
        for message in escalated:
            summary.escalation_reasons[str(message.escalation_reason)] += 1

        self._db.flush()
        return summary

    def identify_recurring_failures(self, summary: PatternSummary) -> list[ImprovementCandidate]:
        candidates: list[ImprovementCandidate] = []

        for reason, count in summary.escalation_reasons.most_common():
            if count >= RECURRENCE_THRESHOLD:
                candidates.append(
                    ImprovementCandidate(
                        category=f"ESCALATION_{reason}",
                        detail=(
                            f"{count} conversations escalated with reason {reason} during "
                            "the review period."
                        ),
                        occurrences=count,
                    )
                )

        for status, count in summary.unhelpful_by_status.most_common():
            if count >= RECURRENCE_THRESHOLD:
                candidates.append(
                    ImprovementCandidate(
                        category=f"UNHELPFUL_{status}",
                        detail=(f"{count} responses with status {status} were rated unhelpful."),
                        occurrences=count,
                    )
                )

        return candidates

    def produce_review_recommendations(
        self, summary: PatternSummary
    ) -> list[ConfigurationRecommendation]:
        recommendations: list[ConfigurationRecommendation] = []

        for candidate in self.identify_recurring_failures(summary):
            if candidate.category.startswith("ESCALATION_UNSUPPORTED_TOPIC"):
                detail = (
                    f"{candidate.detail} Review the knowledge base for a coverage gap and "
                    "propose a new approved article."
                )
            elif candidate.category.startswith("ESCALATION_AI_SERVICE_FAILURE"):
                detail = f"{candidate.detail} Review provider timeout and retry configuration."
            elif candidate.category.startswith("ESCALATION_VALIDATION_FAILURE"):
                detail = (
                    f"{candidate.detail} Review the system prompt against the validation "
                    "rules that rejected the responses."
                )
            else:
                detail = f"{candidate.detail} Review routing and prompt configuration."

            recommendation = ConfigurationRecommendation(
                category=candidate.category,
                detail=detail,
                occurrences=candidate.occurrences,
            )
            recommendations.append(recommendation)

            self._db.add(
                ImprovementRecommendation(
                    period_start=summary.period.start,
                    period_end=summary.period.end,
                    category=recommendation.category,
                    detail=recommendation.detail,
                    occurrences=recommendation.occurrences,
                    review_status="PENDING_REVIEW",
                )
            )

        self._db.flush()
        return recommendations

    def run_once(self, period: DateRange | None = None) -> list[ConfigurationRecommendation]:
        window = period or DateRange.last_days(7)
        summary = self.aggregate_interaction_patterns(window)
        recommendations = self.produce_review_recommendations(summary)
        logger.info(
            "analytics run: events=%d unhelpful_rate=%.2f recommendations=%d",
            summary.total_events,
            summary.unhelpful_rate,
            len(recommendations),
        )
        return recommendations


def main() -> None:  # pragma: no cover - operational entry point
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    db = SessionLocal()
    try:
        worker = LearningAnalyticsWorker(db)
        recommendations = worker.run_once()
        db.commit()
        if not recommendations:
            print("No recurring patterns met the review threshold.")
        for item in recommendations:
            print(f"[{item.review_status}] {item.category} x{item.occurrences}: {item.detail}")
    finally:
        db.close()


if __name__ == "__main__":  # pragma: no cover
    main()
