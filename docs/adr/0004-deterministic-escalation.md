# 0004 — Escalation is rule-based, not confidence-based

**Status:** Accepted
**Date:** Unit 5, Alpha release
**Deciders:** Ravonne Wade, Benjamin Madden, Ryan Gant

## Context

The obvious design is to escalate when the model's confidence is low. We
rejected it. A language model does not expose a calibrated probability that its
answer is correct; any number we invented would be untestable, would vary
between providers, and would silently change meaning the day the model version
moved.

For a service advising members on education and career decisions, "why did this
get escalated?" needs an answer better than "the score was below 0.7".

## Decision

Escalate on named, deterministic conditions, each mapping to one of five
approved reasons. Two are evaluated before the model is called at all -- an
explicit request for a person, and security-sensitive content. Three are
evaluated after generation -- the model declining, a response failing
validation, and a provider failure surviving the retry policy.

## Consequences

**What this buys.** Every escalation has a reason a person can read, test and
argue with. Security-sensitive messages never reach the provider, which is a
privacy property, not just a routing one. The rules are unit-testable without a
model. Swapping providers does not change escalation behaviour.

**What it costs.** Keyword rules have false positives and false negatives, and
they need maintenance as real usage reveals phrasings nobody predicted. A
confidence score would in principle generalise; these rules only catch what
they were written to catch.

**Why that trade is right here.** A missed escalation sends someone to a human
slightly later than ideal. A wrong-but-confident answer about a career decision
is worse. The Learning Analytics Worker exists partly to surface the phrasings
the rules are missing, so the gap closes with evidence rather than guesswork.

## Enforcement

The five reasons are a closed enumeration in `app/schemas.py`; adding a sixth
is an interface change that has to go through the contract.
`test_escalation_does_not_reach_into_other_components` keeps the rules from
growing dependencies on the AI or personnel data that would make them
non-deterministic.
