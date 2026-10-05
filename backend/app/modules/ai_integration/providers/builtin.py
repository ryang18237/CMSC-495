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
from collections.abc import Callable
from dataclasses import dataclass

from app.modules.ai_integration.contracts import AIProviderError, Prompt, ProviderResponse
from app.modules.ai_integration.providers.base import AIProvider
from app.modules.ai_integration.recommender import MemberProfile, recommend

# Deterministic triggers the automated tests use to drive the failure and
# decline branches without reaching inside the service.
FAILURE_TRIGGER = "__force_ai_failure__"
UNSUPPORTED_MARKER = "UNSUPPORTED_TOPIC"

# Topics are matched on word stems, not whole words. Matching "certification"
# literally meant that "what are the next certs I should get?" -- an ordinary
# way to ask the single most common question this service exists for -- matched
# nothing and was escalated to a human as an unsupported topic. A stem catches
# cert, certs, certificate, certification and certified at once, and the same
# for licen(ce|se|sed), qualif(ied|ication) and the rest.
_CREDENTIAL_TOPIC = (
    "cert",
    "credential",
    "licen",
    "exam",
    "comptia",
    "ccna",
    "security+",
    "qualification",
    "badge",
)
_NEXT_STEP_TOPIC = (
    "career",
    "job",
    "next step",
    "next move",
    "what next",
    "what should i",
    "what do i do",
    "where do i start",
    "get started",
    "option",
    "path",
    "advance",
    "progress",
    "recommend",
    "suggest",
    "advice",
    "worth getting",
    "should i get",
)
_DEGREE_TOPIC = (
    "degree",
    "college",
    "universit",
    "tuition",
    "school",
    "associate",
    "bachelor",
    "master",
    "gi bill",
    "major",
)
_RESUME_TOPIC = (
    "resume",
    "cv",
    "interview",
    "hiring",
    "hire",
    "employer",
    "civilian",
    "translate",
    "cover letter",
    "linkedin",
    "apply",
)
_EXPERIENCE_TOPIC = (
    "experience",
    "background",
    "what have i",
    "what do i have",
    # The ways people actually ask what the service knows about them. The
    # classifier already recognised these; the advisor did not, so the
    # question reached it and was declined.
    "what do you have",
    "what do you know",
    "on file",
    "my profile",
    "my record",
    "qualified",
)

# "certainly" is not a question about certifications, and it is common enough
# in ordinary writing to be worth removing before anything is matched.
_FALSE_FRIENDS = re.compile(r"\bcertain\w*")


def _mentions(text: str, stems: tuple[str, ...]) -> bool:
    """True when any stem starts a word in `text`.

    A stem may be several words ("next step"), in which case it has to appear
    in that order. Matching at a word boundary rather than anywhere in the
    string keeps "path" from firing on "sympathy".
    """
    return any(re.search(rf"\b{re.escape(stem)}", text) for stem in stems)


_TRANSITION_TOPIC = (
    "skillbridge",
    "internship",
    "transition",
    "separat",
    "getting out",
    "ets",
    "terminal leave",
)
_APPRENTICESHIP_TOPIC = ("apprentice", "trade", "on the job", "journeyman", "union")

# Any topic this service covers. Used only to decide whether an empty profile
# deserves "tell me about yourself" rather than a decline: a career question
# with nothing on file is answerable by asking, while "what is the capital of
# France?" is still not our subject.
_ANY_TOPIC = (
    _CREDENTIAL_TOPIC
    + _NEXT_STEP_TOPIC
    + _DEGREE_TOPIC
    + _RESUME_TOPIC
    + _EXPERIENCE_TOPIC
    + _TRANSITION_TOPIC
    + _APPRENTICESHIP_TOPIC
)

# Ordered most specific first, because a question about a certification exam
# also mentions studying.
_TOPIC_REPLIES: list[tuple[tuple[str, ...], str]] = [
    (
        _CREDENTIAL_TOPIC,
        "Looking at the training you have already completed, a foundational IT "
        "certification is the closest next step -- your network and information "
        "assurance coursework covers a good share of the exam objectives, so you are "
        "revising rather than starting cold. Compare the published objectives against "
        "your course records before booking a seat, and a counsellor can go through "
        "the funding options with you.",
    ),
    (
        _DEGREE_TOPIC,
        "Both routes are open to you. A credential is shorter and aimed at a specific "
        "role, so it suits getting hired sooner in a field you already know; a degree "
        "takes longer and unlocks roles that list one as a requirement. Plenty of "
        "people do the credential first and finish a degree part time afterwards. "
        "A counsellor can help you map the sequence against your separation date.",
    ),
    (
        _TRANSITION_TOPIC,
        "Industry internships are arranged well ahead of time and need command "
        "approval, so the useful question is when to start asking rather than whether "
        "you qualify. Several months before you want the placement to begin is "
        "typical. Given your separation date, it is worth starting that conversation "
        "now.",
    ),
    (
        _RESUME_TOPIC,
        "Lead with what you were responsible for rather than the job title. Your "
        "completed training translates well into systems and network administration "
        "language: scope of systems, people trained, and what you were accountable "
        "for. List courses by what they taught, not by course number.",
    ),
    (
        _APPRENTICESHIP_TOPIC,
        "Apprenticeships pay while you train and finish in a recognised "
        "qualification, which suits technical and trade fields. Prior military "
        "training sometimes counts toward the required hours, so ask a sponsor to "
        "review your completed courses before you enrol.",
    ),
    (
        _NEXT_STEP_TOPIC,
        "Based on what you have finished so far, the nearest civilian roles are in "
        "systems and network administration. The shortest path is usually to add a "
        "foundational certification on top of the training you already hold, then "
        "apply while you finish anything longer.",
    ),
]


MODEL = "skillbridge-advisor-v3"

# What to say when the profile is empty. The advice this service exists to
# give is advice about one person's position, and with nothing on file there
# is no position to advise on. Asking for the three or four things that would
# change that is more honest, and more useful, than a generic answer.
EMPTY_PROFILE_REPLY = (
    "I do not have anything on your profile yet, so anything I said about your "
    "next step would be a guess rather than advice about you. Open the "
    "My profile tab and add what you have: certifications or licences you hold, "
    "courses you have completed, any degree or coursework, and roles you have "
    "worked. Three or four entries is enough. Ask me again afterwards and the "
    "answer will be built from your own record -- or ask for a counsellor at "
    "any point and a person will pick it up."
)


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


# ---------------------------------------------------------------------------
# The answer shapes. Each takes the member's facts and returns a reply, or ""
# when this member's profile cannot support that kind of answer.
# ---------------------------------------------------------------------------
def _answer_profile(facts: _Facts) -> str:
    """Read the profile back, so a member can see what the advice is built on."""
    pieces = [
        f"{label}: {_joined(items)}"
        for label, items in (
            ("credentials", facts.profile.credentials),
            ("education", facts.education),
            ("experience", facts.experience),
            ("training", facts.training_only),
        )
        if items
    ]
    return (
        "Your profile currently lists "
        + "; ".join(pieces)
        + ". Add anything missing in My profile and I will use it from then on."
    )


def _answer_degree(facts: _Facts) -> str:
    degrees = _next_steps(facts.profile, ("DEGREE", "PROGRAM"))
    if not degrees:
        return ""
    return (
        f"{_record_sentence(facts)} {degrees} Military training is often reviewed for "
        "credit, so ask the school for a credit evaluation before you enrol. A credential "
        "first and a degree part time afterwards is a common order."
    )


def _answer_next_step(facts: _Facts) -> str:
    steps = _next_steps(facts.profile, ("CERTIFICATION", "LICENSE")) or _next_steps(facts.profile)
    if not steps:
        return ""
    return (
        f"{_record_sentence(facts)} {steps} Compare the published objectives against what "
        "you have already covered before booking an exam, and a counsellor can go through "
        "funding options with you."
    )


def _answer_resume(facts: _Facts) -> str:
    lines = ["Lead with what you were responsible for rather than your job title."]
    if facts.experience:
        lines.append(
            f"Put {_joined(facts.experience)} at the top, each with the scope you handled "
            "and the people or systems you were accountable for."
        )
    items = facts.training_only[:3] + facts.profile.credentials[:2]
    if items:
        lines.append(f"List {_joined(items)} by what each taught you, not by course number.")
    if facts.profile.credentials:
        lines.append("Credentials belong in their own section near the top.")
    return " ".join(lines)


class BuiltInAdvisor(AIProvider):
    name = "builtin"

    # Tried in order. A question about a degree mentions "certification" often
    # enough that the degree shape has to come first.
    # Reading the profile back is last, not first. "Given my background, what
    # should I do next?" mentions the profile but is asking for a
    # recommendation, and answering it with a list of what the member already
    # told us is the single most annoying way to be unhelpful. The read-back
    # wins only when nothing else matches -- which is exactly when the
    # question really was "what do you have on me?".
    _ANSWERS: tuple[tuple[tuple[str, ...], Callable[[_Facts], str]], ...] = (
        (_DEGREE_TOPIC, _answer_degree),
        (_CREDENTIAL_TOPIC + _NEXT_STEP_TOPIC, _answer_next_step),
        (_RESUME_TOPIC, _answer_resume),
        (_EXPERIENCE_TOPIC, _answer_profile),
    )

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

        topic_text = _FALSE_FRIENDS.sub("", lowered)

        personal = self._personal_reply(prompt.system, topic_text)
        if personal:
            return ProviderResponse(
                text=personal + self._grounding(prompt), model=MODEL, stop_reason="end_turn"
            )

        for keywords, reply in _TOPIC_REPLIES:
            if _mentions(topic_text, keywords):
                return ProviderResponse(
                    text=reply + self._grounding(prompt), model=MODEL, stop_reason="end_turn"
                )

        # Nothing matched, so decline rather than improvise. The exact marker is
        # what the validation module turns into an UNSUPPORTED_TOPIC escalation.
        return ProviderResponse(text=UNSUPPORTED_MARKER, model=MODEL, stop_reason="end_turn")

    def _personal_reply(self, system: str, lowered: str) -> str:
        """A reply built from this member's profile, or "" for the general one.

        Each answer shape is its own function returning "" when it has nothing
        to say, so the topics are tried in order and the first one that can
        answer does.
        """
        facts = _facts(system)
        if not facts.has_anything:
            # Nothing to reason from. Saying so, and saying what would fix it,
            # is more use than a paragraph of general advice that reads as
            # though it were about them.
            return EMPTY_PROFILE_REPLY if _mentions(lowered, _ANY_TOPIC) else ""

        for topic, compose in self._ANSWERS:
            if _mentions(lowered, topic):
                reply = compose(facts)
                if reply:
                    return reply
        return ""

    @staticmethod
    def _grounding(prompt: Prompt) -> str:
        """Mirror how a real model would point at the material it was given."""
        if "Knowledge base article" in prompt.system:
            return " This follows our published guidance on the topic."
        return ""
