"""Built-in advisor -- the provider that needs no API key.

OWNER: Benjamin Madden (Integration Lead)

This is the default, and it is a real feature rather than a placeholder. A
member can install the platform and get useful, personal answers with nothing
to sign up for and no key to paste anywhere. Claude and ChatGPT are upgrades
on top of it, configured once by whoever runs the server (ADR 0009).

How it answers
--------------
It reads the member facts in the prompt -- the same minimised facts a managed
model receives, produced by the Customer Data Adapter -- and composes a reply
from them, asking the pathway recommender which next steps actually follow
from that profile. Nothing is canned: two members get different answers, and
one member gets a different answer after adding a degree or a job to their
profile.

What it is not
--------------
It does not understand free text the way a language model does. It routes on
topic keywords and declines anything it does not recognise, which becomes an
`UNSUPPORTED_TOPIC` escalation to a human counsellor -- the same safe ending
a managed model gets when it is out of its depth. That is the honest trade:
no key, no cost, no data leaving the process, narrower coverage.

Being deterministic is also what lets CI exercise the whole conversation path
on every push with no key and no spend.
"""

import re
from dataclasses import dataclass

from app.modules.ai_integration.contracts import AIProviderError, Prompt, ProviderResponse
from app.modules.ai_integration.providers.base import AIProvider
from app.modules.ai_integration.recommender import MemberProfile, recommend

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


MODEL = "skillbridge-advisor-v3"

_CREDENTIAL_TOPIC = ("certification", "certificate", "credential", "license", "exam", "comptia")
_NEXT_STEP_TOPIC = ("career", "job", "next step", "what should i do", "options", "path")
_DEGREE_TOPIC = ("degree", "college", "university", "tuition", "school", "associate", "bachelor")
_RESUME_TOPIC = ("resume", "cv", "interview", "hiring", "employer", "civilian", "translate")
_EXPERIENCE_TOPIC = ("experience", "background", "what have i", "my profile", "qualified")


def _fact(system: str, label: str) -> list[str]:
    """Read one 'Label: a, b, c' fact line out of the system prompt."""
    match = re.search(rf"^- {re.escape(label)}: (.+)$", system, re.MULTILINE)
    if not match:
        return []
    return [item.strip() for item in match.group(1).split(",") if item.strip()]


def _joined(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


@dataclass(frozen=True)
class _Facts:
    """Everything the prompt was permitted to carry about this member.

    `profile` is the subset the recommender ranks against; education and
    experience are kept separately because they answer different questions --
    a degree already held changes what to study next, and a job title is what
    a resume question is really about.
    """

    profile: MemberProfile
    education: list[str]
    experience: list[str]

    @property
    def training_only(self) -> list[str]:
        """Training without the education folded in for ranking."""
        return [item for item in self.profile.completed_training if item not in self.education]

    @property
    def has_anything(self) -> bool:
        return bool(
            self.profile.credentials
            or self.profile.completed_training
            or self.education
            or self.experience
        )


def _facts(system: str) -> _Facts:
    specialty = _fact(system, "Occupational specialty")
    education = _fact(system, "Education")
    return _Facts(
        profile=MemberProfile(
            # Study already finished counts as completed training when ranking
            # what to do next: a degree is as much a prerequisite as a course.
            completed_training=_fact(system, "Completed training") + education,
            credentials=_fact(system, "Credentials already held"),
            occupational_specialty=specialty[0] if specialty else None,
        ),
        education=education,
        experience=_fact(system, "Experience"),
    )


def _record_sentence(facts: _Facts) -> str:
    """One sentence back to the member about what their profile says.

    Kept to the two most relevant kinds per answer; listing four would bury
    the advice under a recital of their own history.
    """
    parts = []
    if facts.profile.credentials:
        parts.append(f"you already hold {_joined(facts.profile.credentials)}")
    if facts.education:
        parts.append(f"you have studied {_joined(facts.education)}")
    if facts.training_only and len(parts) < 2:
        parts.append(f"you have completed {_joined(facts.training_only)}")
    if facts.experience and len(parts) < 2:
        parts.append(f"you have worked as {_joined(facts.experience)}")
    return ("Looking at your profile, " + " and ".join(parts) + ".") if parts else ""


def _next_steps(profile: MemberProfile, kinds: tuple[str, ...] | None = None) -> str:
    """Name the top pathways and why, straight from the recommender."""
    result = recommend(profile, limit=6)
    if result.basis != "COMPLETED_TRAINING":
        return ""
    picks = [
        item for item in result.recommendations if kinds is None or item.pathway.kind in kinds
    ][:2]
    if not picks:
        return ""
    described = []
    for item in picks:
        if item.reason == "NEXT_STEP":
            described.append(f"{item.pathway.title}, the natural step after {item.builds_on}")
        elif item.builds_on:
            described.append(f"{item.pathway.title}, which builds on {item.builds_on}")
        else:
            described.append(item.pathway.title)
    if len(described) == 1:
        return f"The closest next step from that is {described[0]}."
    return f"The closest next steps from that are {described[0]}; and {described[1]}."


class BuiltInAdvisor(AIProvider):
    name = "builtin"

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

        personal = self._personal_reply(prompt.system, lowered)
        if personal:
            return ProviderResponse(
                text=personal + self._grounding(prompt), model=MODEL, stop_reason="end_turn"
            )

        for keywords, reply in _TOPIC_REPLIES:
            if any(keyword in lowered for keyword in keywords):
                return ProviderResponse(
                    text=reply + self._grounding(prompt), model=MODEL, stop_reason="end_turn"
                )

        # Nothing matched, so decline rather than improvise. The exact marker is
        # what the validation module turns into an UNSUPPORTED_TOPIC escalation.
        return ProviderResponse(text=UNSUPPORTED_MARKER, model=MODEL, stop_reason="end_turn")

    @staticmethod
    def _personal_reply(system: str, lowered: str) -> str:
        """A reply built from this member's profile, or "" for the general one."""
        facts = _facts(system)
        if not facts.has_anything:
            return ""
        profile = facts.profile
        record = _record_sentence(facts)

        if any(word in lowered for word in _EXPERIENCE_TOPIC):
            held = _joined(profile.credentials) if profile.credentials else None
            studied = _joined(facts.education) if facts.education else None
            worked = _joined(facts.experience) if facts.experience else None
            pieces = [
                text
                for text in (
                    f"credentials: {held}" if held else None,
                    f"education: {studied}" if studied else None,
                    f"experience: {worked}" if worked else None,
                    f"training: {_joined(facts.training_only)}" if facts.training_only else None,
                )
                if text
            ]
            missing = " Add anything missing in My profile and I will use it from then on."
            return "Your profile currently lists " + "; ".join(pieces) + "." + missing

        if any(word in lowered for word in _DEGREE_TOPIC):
            degrees = _next_steps(profile, ("DEGREE", "PROGRAM"))
            if degrees:
                return (
                    f"{record} {degrees} Military training is often reviewed for credit, "
                    "so ask the school for a credit evaluation before you enrol. A credential "
                    "first and a degree part time afterwards is a common order."
                )

        if any(word in lowered for word in _CREDENTIAL_TOPIC + _NEXT_STEP_TOPIC):
            steps = _next_steps(profile, ("CERTIFICATION", "LICENSE"))
            if not steps:
                steps = _next_steps(profile)
            if steps:
                return (
                    f"{record} {steps} Compare the published objectives against what you "
                    "have already covered before booking an exam, and a counsellor can go "
                    "through funding options with you."
                )

        if any(word in lowered for word in _RESUME_TOPIC):
            lines = ["Lead with what you were responsible for rather than your job title."]
            if facts.experience:
                lines.append(
                    f"Put {_joined(facts.experience)} at the top, each with the scope you "
                    "handled and the people or systems you were accountable for."
                )
            items = facts.training_only[:3] + profile.credentials[:2]
            if items:
                lines.append(
                    f"List {_joined(items)} by what each taught you, not by course number."
                )
            if profile.credentials:
                lines.append("Credentials belong in their own section near the top.")
            return " ".join(lines)
        return ""

    @staticmethod
    def _grounding(prompt: Prompt) -> str:
        """Mirror how a real model would point at the material it was given."""
        if "Knowledge base article" in prompt.system:
            return " This follows our published guidance on the topic."
        return ""
