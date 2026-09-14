"""Deterministic provider used for local development, CI and demos.

No network, no API key, no cost -- which is what lets the pipeline exercise the
whole conversation path on every push. It implements exactly the same interface
as a managed provider, so swapping the real one in changes no caller.

The replies are canned, but the routing between them is keyword based in the
same way a real model's behaviour is topic driven, so the demo exercises the
same branches: an answer, a decline, and a provider failure.
"""

from app.modules.ai_integration.contracts import AIProviderError, Prompt, ProviderResponse
from app.modules.ai_integration.providers.base import AIProvider

# Deterministic triggers the automated tests use to drive the failure and
# decline branches without reaching inside the service.
FAILURE_TRIGGER = "__force_ai_failure__"
UNSUPPORTED_MARKER = "UNSUPPORTED_TOPIC"

# Ordered most specific first, because a question about a certification exam
# also mentions studying.
_TOPIC_REPLIES: list[tuple[tuple[str, ...], str]] = [
    (
        ("certification", "certificate", "credential", "license", "exam", "comptia"),
        "Looking at the training you have already completed, a foundational IT "
        "certification is the closest next step -- your network and information "
        "assurance coursework covers a good share of the exam objectives, so you are "
        "revising rather than starting cold. Compare the published objectives against "
        "your course records before booking a seat, and a counsellor can go through "
        "the funding options with you.",
    ),
    (
        ("degree", "college", "university", "tuition", "school", "associate", "bachelor"),
        "Both routes are open to you. A credential is shorter and aimed at a specific "
        "role, so it suits getting hired sooner in a field you already know; a degree "
        "takes longer and unlocks roles that list one as a requirement. Plenty of "
        "people do the credential first and finish a degree part time afterwards. "
        "A counsellor can help you map the sequence against your separation date.",
    ),
    (
        ("skillbridge", "internship", "transition", "separating", "separation", "getting out"),
        "Industry internships are arranged well ahead of time and need command "
        "approval, so the useful question is when to start asking rather than whether "
        "you qualify. Several months before you want the placement to begin is "
        "typical. Given your separation date, it is worth starting that conversation "
        "now.",
    ),
    (
        ("resume", "cv", "interview", "hiring", "employer", "civilian", "translate"),
        "Lead with what you were responsible for rather than the job title. Your "
        "completed training translates well into systems and network administration "
        "language: scope of systems, people trained, and what you were accountable "
        "for. List courses by what they taught, not by course number.",
    ),
    (
        ("apprenticeship", "trade", "on the job", "hours"),
        "Apprenticeships pay while you train and finish in a recognised "
        "qualification, which suits technical and trade fields. Prior military "
        "training sometimes counts toward the required hours, so ask a sponsor to "
        "review your completed courses before you enrol.",
    ),
    (
        ("career", "job", "next step", "what should i do", "options", "path"),
        "Based on what you have finished so far, the nearest civilian roles are in "
        "systems and network administration. The shortest path is usually to add a "
        "foundational certification on top of the training you already hold, then "
        "apply while you finish anything longer.",
    ),
]


class MockAIProvider(AIProvider):
    name = "mock"

    def generate(self, prompt: Prompt) -> ProviderResponse:
        # The newest customer turn is always last; earlier turns are history.
        last_user_turn = ""
        for message in reversed(prompt.messages):
            if message.get("role") == "user":
                last_user_turn = message.get("content", "")
                break

        lowered = last_user_turn.lower()

        if FAILURE_TRIGGER in lowered:
            raise AIProviderError("Simulated provider outage.", retryable=True)

        for keywords, reply in _TOPIC_REPLIES:
            if any(keyword in lowered for keyword in keywords):
                return ProviderResponse(
                    text=reply + self._grounding(prompt),
                    model="mock-skillbridge-v1",
                    stop_reason="end_turn",
                )

        # Nothing matched, so decline rather than improvise. The exact marker is
        # what the validation module turns into an UNSUPPORTED_TOPIC escalation.
        return ProviderResponse(
            text=UNSUPPORTED_MARKER, model="mock-skillbridge-v1", stop_reason="end_turn"
        )

    @staticmethod
    def _grounding(prompt: Prompt) -> str:
        """Mirror how a real model would point at the material it was given."""
        if "Knowledge base article" in prompt.system:
            return " This follows our published guidance on the topic."
        return ""
